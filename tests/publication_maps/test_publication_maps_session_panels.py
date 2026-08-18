"""Pure repeated-session publication-map panel tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from Tools.Publication_Maps.models import PublicationMetric
from Tools.Publication_Maps.session_panels import (
    RepeatedSessionMapDataError,
    RepeatedSessionMapIdentityError,
    build_repeated_session_map_panels,
)


def _record(
    root: Path,
    participant_id: str,
    group_id: str,
    session_id: str,
    visit_index: int,
) -> SimpleNamespace:
    recording_id = f"{participant_id}-{session_id}"
    return SimpleNamespace(
        path=root / f"{recording_id}.xlsx",
        participant_id=participant_id,
        condition="Faces",
        group_id=group_id,
        group_label={
            "control": "No birth control",
            "birth_control": "Birth control",
        }[group_id],
        recording_id=recording_id,
        session_id=session_id,
        session_label=session_id.title(),
        visit_index=visit_index,
    )


def _cohort(root: Path) -> tuple[SimpleNamespace, ...]:
    return tuple(
        _record(root, participant, group, session, visit)
        for participant, group in (
            ("P01", "control"),
            ("P02", "control"),
            ("P03", "birth_control"),
            ("P04", "birth_control"),
        )
        for session, visit in (("luteal", 1), ("follicular", 2))
    )


def _long_values(
    records: tuple[SimpleNamespace, ...],
    totals: dict[str, dict[str, float]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for record in records:
        for electrode, total in totals[record.recording_id].items():
            harmonic_value = total / 2.0
            for harmonic_hz in (1.2, 2.4):
                rows.append(
                    {
                        "condition": record.condition,
                        "group_id": record.group_id,
                        "subject_id": record.participant_id,
                        "workbook_path": str(record.path),
                        "electrode": electrode,
                        "is_montage_electrode": True,
                        "metric": PublicationMetric.BCA.value,
                        "harmonic_hz": harmonic_hz,
                        "value": harmonic_value,
                    }
                )
    return pd.DataFrame(rows)


def _electrode_values(values: tuple[object, ...]) -> dict[str, object]:
    return {str(value.electrode): value for value in values}


def test_panels_share_scale_and_pair_recordings_before_group_averaging(
    tmp_path: Path,
) -> None:
    records = _cohort(tmp_path)
    totals = {
        "P01-luteal": {"Cz": -2.0, "Oz": -2.0},
        "P01-follicular": {"Cz": 3.0, "Oz": -1.0},
        "P02-luteal": {"Cz": 5.0, "Oz": -4.0},
        "P02-follicular": {"Cz": np.nan, "Oz": np.nan},
        "P03-luteal": {"Cz": 10.0, "Oz": 8.0},
        "P03-follicular": {"Cz": 14.0, "Oz": 12.0},
        "P04-luteal": {"Cz": 20.0, "Oz": 16.0},
        "P04-follicular": {"Cz": 22.0, "Oz": 18.0},
    }

    result = build_repeated_session_map_panels(
        long_values=_long_values(records, totals),
        workbook_records=records,
        condition="Faces",
        metric=PublicationMetric.BCA,
        selected_harmonics_hz=(1.2, 2.4),
    )

    assert result.group_ids == ("birth_control", "control")
    assert result.session_ids == ("luteal", "follicular")
    assert len(result.panels) == 4
    assert result.common_vmin == pytest.approx(0.0)
    assert result.common_vmax == pytest.approx(18.0)

    luteal = result.panel("control", "luteal")
    follicular = result.panel("control", "follicular")
    luteal_values = _electrode_values(luteal.values)
    follicular_values = _electrode_values(follicular.values)
    assert luteal.participant_ids == ("P01", "P02")
    assert luteal.recording_ids == ("P01-luteal", "P02-luteal")
    assert follicular.participant_ids == ("P01",)
    assert follicular.recording_ids == ("P01-follicular",)
    assert luteal_values["Cz"].aggregate_value == pytest.approx(1.5)
    assert luteal_values["Oz"].aggregate_value == pytest.approx(-3.0)
    assert luteal_values["Oz"].render_value == pytest.approx(0.0)
    assert follicular_values["Cz"].aggregate_value == pytest.approx(3.0)

    difference = result.paired_difference("control")
    difference_values = _electrode_values(difference.values)
    assert difference.participant_ids == ("P01",)
    assert difference.paired_n == 1
    assert difference_values["Cz"].aggregate_difference == pytest.approx(5.0)
    assert difference_values["Cz"].paired_subject_count == 1
    # Independent cell means would yield 1.5, but only P01 has both visits.
    assert difference_values["Cz"].aggregate_difference != pytest.approx(
        follicular_values["Cz"].aggregate_value - luteal_values["Cz"].aggregate_value
    )

    treated_difference = result.paired_difference("birth_control")
    treated_values = _electrode_values(treated_difference.values)
    assert treated_difference.participant_ids == ("P03", "P04")
    assert treated_values["Cz"].aggregate_difference == pytest.approx(3.0)
    assert treated_values["Cz"].paired_subject_count == 2
    assert result.difference_vmin == pytest.approx(-5.0)
    assert result.difference_vmax == pytest.approx(5.0)


def test_session_identity_is_required_and_never_parsed_from_workbook_path(
    tmp_path: Path,
) -> None:
    records = list(_cohort(tmp_path))
    records[0].session_id = None
    records[0].path = tmp_path / "luteal" / "P01_Faces_Results.xlsx"

    with pytest.raises(RepeatedSessionMapIdentityError, match="canonical session_id"):
        build_repeated_session_map_panels(
            long_values=pd.DataFrame(),
            workbook_records=records,
            condition="Faces",
            metric=PublicationMetric.BCA,
            selected_harmonics_hz=(1.2,),
        )


def test_long_values_must_join_an_exact_canonical_workbook_path(tmp_path: Path) -> None:
    records = _cohort(tmp_path)
    long_values = _long_values(
        records,
        {record.recording_id: {"Cz": 1.0} for record in records},
    )
    long_values.loc[0, "workbook_path"] = str(tmp_path / "follicular" / "P01_Faces_Results.xlsx")

    with pytest.raises(
        RepeatedSessionMapIdentityError,
        match="without canonical repeated-session identity",
    ):
        build_repeated_session_map_panels(
            long_values=long_values,
            workbook_records=records,
            condition="Faces",
            metric=PublicationMetric.BCA,
            selected_harmonics_hz=(1.2, 2.4),
        )


def test_panel_builder_requires_exactly_two_groups_and_sessions(tmp_path: Path) -> None:
    records = (
        _record(tmp_path, "P01", "control", "luteal", 1),
        _record(tmp_path, "P01", "control", "follicular", 2),
    )

    with pytest.raises(RepeatedSessionMapIdentityError, match="exactly two groups"):
        build_repeated_session_map_panels(
            long_values=pd.DataFrame(),
            workbook_records=records,
            condition="Faces",
            metric=PublicationMetric.BCA,
            selected_harmonics_hz=(1.2,),
        )


def test_panel_builder_uses_only_the_exact_canonical_harmonics(tmp_path: Path) -> None:
    records = _cohort(tmp_path)
    long_values = _long_values(
        records,
        {record.recording_id: {"Cz": 2.0} for record in records},
    )
    extra = long_values.loc[long_values["harmonic_hz"].eq(1.2)].copy()
    extra["harmonic_hz"] = 3.6
    extra["value"] = 1000.0
    long_values = pd.concat([long_values, extra], ignore_index=True)

    result = build_repeated_session_map_panels(
        long_values=long_values,
        workbook_records=records,
        condition="Faces",
        metric=PublicationMetric.BCA,
        selected_harmonics_hz=(1.2, 2.4),
    )

    values = _electrode_values(result.panel("control", "luteal").values)
    assert values["Cz"].aggregate_value == pytest.approx(2.0)

    with pytest.raises(RepeatedSessionMapDataError, match="unique canonical harmonics"):
        build_repeated_session_map_panels(
            long_values=long_values,
            workbook_records=records,
            condition="Faces",
            metric=PublicationMetric.BCA,
            selected_harmonics_hz=(1.2, 1.20001),
        )


def test_panel_builder_never_silently_drops_a_canonical_recording(
    tmp_path: Path,
) -> None:
    records = _cohort(tmp_path)
    long_values = _long_values(
        records,
        {record.recording_id: {"Cz": 1.0} for record in records},
    )
    long_values = long_values.loc[~long_values["workbook_path"].eq(str(records[0].path))].copy()

    with pytest.raises(
        RepeatedSessionMapDataError,
        match=r"no exact selected-harmonic map rows: P01-luteal",
    ):
        build_repeated_session_map_panels(
            long_values=long_values,
            workbook_records=records,
            condition="Faces",
            metric=PublicationMetric.BCA,
            selected_harmonics_hz=(1.2, 2.4),
        )


@pytest.mark.parametrize(
    ("metric", "expected"),
    (
        (PublicationMetric.SNR, 3.0),
        (PublicationMetric.Z_SCORE, 6.0 / np.sqrt(2.0)),
    ),
)
def test_session_panels_preserve_metric_specific_harmonic_aggregation(
    tmp_path: Path,
    metric: PublicationMetric,
    expected: float,
) -> None:
    records = _cohort(tmp_path)
    long_values = _long_values(
        records,
        {record.recording_id: {"Cz": 1.0} for record in records},
    )
    long_values["metric"] = metric.value
    long_values["value"] = long_values["harmonic_hz"].map({1.2: 2.0, 2.4: 4.0})

    result = build_repeated_session_map_panels(
        long_values=long_values,
        workbook_records=records,
        condition="Faces",
        metric=metric,
        selected_harmonics_hz=(1.2, 2.4),
    )

    values = _electrode_values(result.panel("control", "luteal").values)
    assert values["Cz"].aggregate_value == pytest.approx(expected)
