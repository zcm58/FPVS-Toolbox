from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis.design_audit import (
    DesignAuditError,
    audit_analysis_design,
    audit_complete_core_design,
    build_factor_cell_coverage,
)


def _design_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for participant in ("P1", "P2", "P3"):
        for roi_index, roi in enumerate(("R1", "R2")):
            rows.append(
                {
                    "participant": participant,
                    "condition": "Shared",
                    "roi": roi,
                    "value": 1.0 + roi_index,
                }
            )
    for participant in ("P1", "P2"):
        for roi in ("R1", "R2"):
            rows.append(
                {
                    "participant": participant,
                    "condition": "Optional",
                    "roi": roi,
                    "value": 2.0,
                }
            )
    return pd.DataFrame(rows)


def test_complete_core_freezes_participants_before_condition_intersection() -> None:
    result = audit_complete_core_design(
        _design_frame(),
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        frozen_participants=("P1", "P2", "P3"),
        selected_conditions=("Shared", "Optional"),
        selected_rois=("R1", "R2"),
    )

    assert result.ready
    assert result.frozen_participants == ("P1", "P2", "P3")
    assert result.complete_conditions == ("Shared",)
    assert result.excluded_conditions == ("Optional",)
    assert set(result.primary_data["participant"]) == {"P1", "P2", "P3"}
    assert set(result.primary_data["condition"]) == {"Shared"}
    optional = result.coverage[result.coverage["condition"] == "Optional"]
    assert optional["n_frozen_participants"].eq(3).all()
    assert optional["retained_primary"].eq(False).all()


def test_duplicate_participant_condition_roi_cell_hard_fails() -> None:
    data = _design_frame()
    duplicated = pd.concat([data, data.iloc[[0]]], ignore_index=True)

    with pytest.raises(DesignAuditError, match="Duplicate participant x Condition x ROI"):
        audit_complete_core_design(
            duplicated,
            dv_col="value",
            subject_col="participant",
            condition_col="condition",
            roi_col="roi",
        )


def test_nonfinite_value_excludes_condition_without_dropping_participant() -> None:
    data = _design_frame()
    data.loc[
        (data["participant"] == "P3")
        & (data["condition"] == "Shared")
        & (data["roi"] == "R2"),
        "value",
    ] = np.inf

    result = audit_complete_core_design(
        data,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        frozen_participants=("P1", "P2", "P3"),
        selected_conditions=("Shared", "Optional"),
        selected_rois=("R1", "R2"),
    )

    assert not result.ready
    assert result.status_code == "no_shared_complete_condition"
    assert result.frozen_participants == ("P1", "P2", "P3")
    assert result.primary_data.empty
    flagged = result.coverage[
        (result.coverage["condition"] == "Shared")
        & (result.coverage["roi"] == "R2")
    ].iloc[0]
    assert flagged["n_nonfinite_values"] == 1


def test_multigroup_audit_uses_canonical_ids_and_blocks_missing_assignments() -> None:
    data = _design_frame()
    complete_map = {"P1": "control", "P2": "anxious", "P3": "control"}
    ready = audit_complete_core_design(
        data,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        frozen_participants=("P1", "P2", "P3"),
        selected_conditions=("Shared",),
        canonical_group_ids=complete_map,
        require_groups=True,
    )
    blocked = audit_complete_core_design(
        data,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        frozen_participants=("P1", "P2", "P3"),
        selected_conditions=("Shared",),
        canonical_group_ids={"P1": "control", "P2": "anxious"},
        require_groups=True,
    )

    assert ready.ready
    assert set(ready.primary_data["group_id"]) == {"control", "anxious"}
    assert blocked.status_code == "missing_group_assignments"
    missing = blocked.group_assignments[
        blocked.group_assignments["assignment_status"] == "missing_or_unknown"
    ]
    assert missing["participant_id"].tolist() == ["P3"]


def test_multigroup_audit_requires_two_canonical_groups() -> None:
    result = audit_complete_core_design(
        _design_frame(),
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        selected_conditions=("Shared",),
        canonical_group_ids={"P1": "one", "P2": "one", "P3": "one"},
        require_groups=True,
    )

    assert not result.ready
    assert result.status_code == "insufficient_groups"


def test_design_frames_are_explicitly_serializable() -> None:
    result = audit_complete_core_design(
        _design_frame(),
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        selected_conditions=("Shared", "Optional"),
    )

    frames = result.to_frames()
    assert set(frames) == {
        "Analysis Design",
        "Coverage",
        "Model Cell Coverage",
        "Participant Coverage",
        "Missing Observations",
        "Exclusions",
        "Group Assignments",
        "Primary Data",
    }
    metadata = frames["Analysis Design"].iloc[0]
    assert metadata["participant_scope"] == "frozen_before_condition_intersection"
    assert metadata["complete_conditions"] == "Shared"
    assert json.loads(frames["Analysis Design"].to_json(orient="records"))[0][
        "status"
    ] == "ready"


def test_available_case_retains_partial_condition_and_other_participant_rows() -> None:
    result = audit_analysis_design(
        _design_frame(),
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        frozen_participants=("P1", "P2", "P3"),
        selected_conditions=("Shared", "Optional"),
        selected_rois=("R1", "R2"),
        analysis_scope="available_case",
    )

    assert result.ready
    assert result.analysis_scope == "available_case"
    assert result.complete_conditions == ("Shared",)
    assert result.retained_conditions == ("Shared", "Optional")
    assert result.excluded_conditions == ()
    assert len(result.primary_data) == 10
    assert set(result.primary_data["participant"]) == {"P1", "P2", "P3"}
    missing = result.missing_observations.query(
        "participant_id == 'P3' and condition == 'Optional'"
    )
    assert len(missing) == 2
    assert missing["missingness_type"].eq("missing_row").all()
    assert missing["condition_retained"].all()
    metadata = result.metadata_frame().iloc[0]
    assert metadata["partial_conditions"] == "Optional"
    assert metadata["n_observed_rows"] == 10
    assert bool(metadata["missing_values_imputed"]) is False


def test_available_case_multigroup_excludes_structurally_empty_condition() -> None:
    result = audit_analysis_design(
        _design_frame(),
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        frozen_participants=("P1", "P2", "P3"),
        selected_conditions=("Shared", "Optional"),
        selected_rois=("R1", "R2"),
        canonical_group_ids={
            "P1": "control",
            "P2": "control",
            "P3": "anxious",
        },
        require_groups=True,
        analysis_scope="available_case",
    )

    assert result.ready
    assert result.retained_conditions == ("Shared",)
    assert result.excluded_conditions == ("Optional",)
    excluded = result.exclusions.iloc[0]
    assert excluded["reason"] == "structurally_unobserved_model_cell"
    empty_cells = result.model_cell_coverage.query(
        "condition == 'Optional' and group_id == 'anxious'"
    )
    assert empty_cells["structurally_observed"].eq(False).all()


def test_factor_cell_coverage_exposes_structural_missingness_inputs() -> None:
    data = pd.DataFrame(
        {
            "participant": ["P1", "P2", "P1"],
            "condition": ["A", "A", "B"],
            "protocol": ["old", "old", "new"],
        }
    )

    coverage = build_factor_cell_coverage(
        data,
        factors=("condition", "protocol"),
        subject_col="participant",
    )

    a_old = coverage[
        (coverage["condition"] == "A") & (coverage["protocol"] == "old")
    ].iloc[0]
    b_new = coverage[
        (coverage["condition"] == "B") & (coverage["protocol"] == "new")
    ].iloc[0]
    assert bool(a_old["complete_participant_coverage"]) is True
    assert bool(b_new["complete_participant_coverage"]) is False
