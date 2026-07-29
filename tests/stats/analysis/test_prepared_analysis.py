from __future__ import annotations

from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from Tools.Stats.analysis.inference_contracts import (
    AnalysisProfile,
    AnalysisRunSpec,
    HarmonicProvenance,
)
from Tools.Stats.analysis.prepared_analysis import (
    AnalysisMode,
    PreparedAnalysisError,
    prepare_analysis_payload,
)


def _run_spec() -> AnalysisRunSpec:
    return AnalysisRunSpec(
        profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        harmonic_provenance=HarmonicProvenance.USER_FIXED_UNVERIFIED,
    )


def _data() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for participant_index, participant in enumerate(("P1", "P2", "P3", "P4")):
        for condition in ("shared", "incomplete"):
            if condition == "incomplete" and participant == "P4":
                continue
            for roi_index, roi in enumerate(("left", "right")):
                rows.append(
                    {
                        "pid": participant,
                        "task": condition,
                        "region": roi,
                        "summed": (
                            float(participant_index + roi_index)
                            + (0.5 if condition == "incomplete" else 0.0)
                        ),
                    }
                )
    return pd.DataFrame(rows)


def test_payload_freezes_cohort_before_shared_condition_intersection() -> None:
    payload = prepare_analysis_payload(
        _data(),
        mode="multi_group",
        run_spec=_run_spec(),
        dv_col="summed",
        subject_col="pid",
        condition_col="task",
        roi_col="region",
        group_col="cohort_id",
        frozen_participants=("P1", "P2", "P3", "P4"),
        selected_conditions=("shared", "incomplete"),
        selected_rois=("left", "right"),
        canonical_group_ids={
            "P1": "control",
            "P2": "control",
            "P3": "anxious",
            "P4": "anxious",
        },
        group_display_labels={
            "control": "Non-anxious",
            "anxious": "Anxious",
        },
        participant_display_labels={
            "P1": "Non-anxious",
            "P2": "Non-anxious",
            "P3": "Anxious",
            "P4": "Anxious",
        },
        selected_group_pair=("anxious", "control"),
        settings={"resamples": 1999},
        preparation_id="fixed-preparation",
    )

    assert payload.ready
    assert payload.mode is AnalysisMode.MULTI
    assert payload.preparation_id == "fixed-preparation"
    assert payload.frozen_participants == ("P1", "P2", "P3", "P4")
    assert payload.complete_conditions == ("shared",)
    assert payload.excluded_conditions == ("incomplete",)
    assert set(payload.primary_data["pid"]) == {"P1", "P2", "P3", "P4"}
    assert set(payload.primary_data["task"]) == {"shared"}
    assert set(payload.primary_data["cohort_id"]) == {"control", "anxious"}
    assert payload.selected_group_pair == ("anxious", "control")
    assert payload.canonical_group_ids["P4"] == "anxious"
    assert payload.group_display_labels["control"] == "Non-anxious"
    assert payload.participant_display_labels["P4"] == "Anxious"
    assert payload.settings == {"resamples": 1999}


def test_payload_is_frozen_and_dataframe_properties_are_defensive_copies() -> None:
    payload = prepare_analysis_payload(
        _data(),
        mode="single",
        run_spec=_run_spec(),
        dv_col="summed",
        subject_col="pid",
        condition_col="task",
        roi_col="region",
        selected_conditions=("shared",),
    )

    with pytest.raises(FrozenInstanceError):
        payload.status_code = "changed"  # type: ignore[misc]
    exposed = payload.primary_data
    exposed.loc[:, "summed"] = -999.0
    frames = payload.design_frames
    frames["Primary Data"].loc[:, "summed"] = -888.0

    assert not payload.primary_data["summed"].eq(-999.0).any()
    assert not payload.design_frames["Primary Data"]["summed"].eq(-888.0).any()


def test_available_case_payload_keeps_incomplete_condition_observations() -> None:
    payload = prepare_analysis_payload(
        _data(),
        mode="single",
        run_spec=_run_spec(),
        dv_col="summed",
        subject_col="pid",
        condition_col="task",
        roi_col="region",
        frozen_participants=("P1", "P2", "P3", "P4"),
        selected_conditions=("shared", "incomplete"),
        selected_rois=("left", "right"),
        analysis_scope="available_case",
        preparation_id="available-preparation",
    )

    assert payload.ready
    assert payload.analysis_scope == "available_case"
    assert payload.complete_conditions == ("shared",)
    assert payload.retained_conditions == ("shared", "incomplete")
    assert payload.excluded_conditions == ()
    assert payload.contributing_participants == ("P1", "P2", "P3", "P4")
    assert len(payload.primary_data) == 14
    assert set(payload.primary_data["task"]) == {"shared", "incomplete"}
    metadata = payload.metadata_frame().iloc[0]
    assert metadata["partial_conditions"] == "incomplete"
    assert metadata["n_observed_rows"] == 14
    assert bool(metadata["missing_values_imputed"]) is False
    missing = payload.design_frames["Missing Observations"]
    assert len(missing.query("participant_id == 'P4'")) == 2


def test_blocked_multigroup_audit_and_all_metadata_frames_remain_explicit() -> None:
    payload = prepare_analysis_payload(
        _data(),
        mode="multi",
        run_spec=_run_spec(),
        dv_col="summed",
        subject_col="pid",
        condition_col="task",
        roi_col="region",
        selected_conditions=("shared",),
        canonical_group_ids={
            "P1": "control",
            "P2": "control",
            "P3": "anxious",
        },
    )

    assert not payload.ready
    assert payload.status_code == "missing_group_assignments"
    frames = payload.to_frames()
    assert {
        "Prepared Analysis",
        "Analysis Design",
        "Coverage",
        "Exclusions",
        "Group Assignments",
        "Primary Data",
        "Run Metadata",
        "Correction Families",
        "Group Display Labels",
        "Participant Display Labels",
        "Analysis Settings",
    }.issubset(frames)
    assert frames["Prepared Analysis"].iloc[0]["audit_status"] == "blocked"
    missing = frames["Group Assignments"].query(
        "assignment_status == 'missing_or_unknown'"
    )
    assert missing["participant_id"].tolist() == ["P4"]


def test_selected_group_pair_must_reference_frozen_canonical_groups() -> None:
    with pytest.raises(
        PreparedAnalysisError,
        match="not in the frozen cohort",
    ):
        prepare_analysis_payload(
            _data(),
            mode="multi",
            run_spec=_run_spec(),
            dv_col="summed",
            subject_col="pid",
            condition_col="task",
            roi_col="region",
            selected_conditions=("shared",),
            canonical_group_ids={
                "P1": "control",
                "P2": "control",
                "P3": "anxious",
                "P4": "anxious",
            },
            selected_group_pair=("anxious", "small_group"),
        )
