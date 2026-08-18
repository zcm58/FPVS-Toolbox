"""Pure repeated-session SNR aggregation tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from Tools.Plot_Generator.session_aggregation import (
    RepeatedSessionSNRDataError,
    RepeatedSessionSNRIdentityError,
    aggregate_repeated_session_snr,
)


def _record(
    participant_id: str,
    group_id: str,
    session_id: str,
    visit_index: int,
) -> SimpleNamespace:
    return SimpleNamespace(
        path=f"/{participant_id}-{session_id}.xlsx",
        participant_id=participant_id,
        condition="Faces",
        group_id=group_id,
        group_label={
            "control": "No birth control",
            "birth_control": "Birth control",
        }[group_id],
        recording_id=f"{participant_id}-{session_id}",
        session_id=session_id,
        session_label=session_id.title(),
        visit_index=visit_index,
    )


def _cohort() -> tuple[SimpleNamespace, ...]:
    return (
        _record("P01", "control", "luteal", 1),
        _record("P01", "control", "follicular", 2),
        _record("P02", "control", "luteal", 1),
        _record("P02", "control", "follicular", 2),
        _record("P03", "birth_control", "luteal", 1),
        _record("P03", "birth_control", "follicular", 2),
        _record("P04", "birth_control", "luteal", 1),
    )


def test_group_session_cells_preserve_repeated_ids_and_pair_before_averaging() -> None:
    curves = {
        "P01-luteal": {"Posterior": [1.0, 10.0, float("nan")]},
        "P01-follicular": {"Posterior": [3.0, 14.0, 8.0]},
        "P02-luteal": {"Posterior": [5.0, 20.0, 4.0]},
        "P02-follicular": {"Posterior": [9.0, float("nan"), 10.0]},
        "P03-luteal": {"Posterior": [2.0, 2.0, 2.0]},
        "P03-follicular": {"Posterior": [4.0, 4.0, 4.0]},
        "P04-luteal": {"Posterior": [6.0, 6.0, 6.0]},
    }

    result = aggregate_repeated_session_snr(
        workbook_records=_cohort(),
        curves_by_recording=curves,
        condition="Faces",
        roi_names=("Posterior",),
    )

    assert result.group_ids == ("birth_control", "control")
    assert result.session_ids == ("luteal", "follicular")
    assert result.reference_session_id == "luteal"
    assert result.comparison_session_id == "follicular"

    luteal = result.cell("control", "luteal", "Posterior")
    follicular = result.cell("control", "follicular", "Posterior")
    assert luteal.plotted_values == pytest.approx((3.0, 15.0, 4.0))
    assert luteal.participant_n_by_frequency == (2, 2, 1)
    assert luteal.participant_ids == ("P01", "P02")
    assert luteal.recording_ids == ("P01-luteal", "P02-luteal")
    assert follicular.plotted_values == pytest.approx((6.0, 14.0, 9.0))
    assert follicular.participant_n_by_frequency == (2, 1, 2)

    difference = result.paired_difference("control", "Posterior")
    assert difference.plotted_values == pytest.approx((3.0, 4.0, 6.0))
    assert difference.paired_n_by_frequency == (2, 1, 1)
    assert difference.participant_ids == ("P01", "P02")
    assert difference.paired_n_roi == 2
    # At bin 2, paired P01 contributes +4. A subtraction of the two
    # independently available group means would incorrectly yield -1.
    assert difference.plotted_values[1] != pytest.approx(follicular.plotted_values[1] - luteal.plotted_values[1])

    birth_control = result.paired_difference("birth_control", "Posterior")
    assert birth_control.plotted_values == pytest.approx((2.0, 2.0, 2.0))
    assert birth_control.paired_n_by_frequency == (1, 1, 1)
    assert birth_control.participant_ids == ("P03",)
    assert result.cell("birth_control", "luteal", "Posterior").participant_n_roi == 2
    assert result.cell("birth_control", "follicular", "Posterior").participant_n_roi == 1


def test_incomplete_repeated_session_identity_is_not_inferred_from_path() -> None:
    record = _record("P01", "control", "follicular", 2)
    record.session_id = None
    record.path = "/Follicular/P01_Faces_Results.xlsx"

    with pytest.raises(RepeatedSessionSNRIdentityError, match="canonical session_id"):
        aggregate_repeated_session_snr(
            workbook_records=(record,),
            curves_by_recording={record.recording_id: {"Posterior": [1.0]}},
            condition="Faces",
        )


def test_ambiguous_visit_order_and_duplicate_participant_session_are_rejected() -> None:
    first = _record("P01", "control", "luteal", 1)
    second = _record("P01", "control", "follicular", 1)

    with pytest.raises(RepeatedSessionSNRIdentityError, match="share one visit_index"):
        aggregate_repeated_session_snr(
            workbook_records=(first, second),
            curves_by_recording={},
            condition="Faces",
        )

    duplicate = _record("P01", "control", "luteal", 1)
    duplicate.recording_id = "P01-luteal-repeat"
    with pytest.raises(RepeatedSessionSNRIdentityError, match="more than one recording"):
        aggregate_repeated_session_snr(
            workbook_records=(first, duplicate),
            curves_by_recording={},
            condition="Faces",
        )


def test_recording_curves_require_one_exact_frequency_width() -> None:
    records = (
        _record("P01", "control", "luteal", 1),
        _record("P01", "control", "follicular", 2),
    )

    with pytest.raises(RepeatedSessionSNRDataError, match="exact frequency grid"):
        aggregate_repeated_session_snr(
            workbook_records=records,
            curves_by_recording={
                "P01-luteal": {"Posterior": [1.0, 2.0]},
                "P01-follicular": {"Posterior": [1.0]},
            },
            condition="Faces",
        )
