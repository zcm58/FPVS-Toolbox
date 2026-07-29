from __future__ import annotations

from Tools.Stats.analysis.dv_policies import GROUP_SIGNIFICANT_POLICY_NAME
from Tools.Stats.common.stats_core import PipelineId
from Tools.Stats.ui.stats_window_actions import StatsWindowActionsMixin
from Tools.Stats.ui.stats_window_support import (
    build_native_group_state,
    build_preliminary_workbook_coverage,
    canonical_group_pairs,
    format_preliminary_workbook_coverage,
)


def test_native_group_state_keeps_canonical_and_display_identity_separate() -> None:
    state = build_native_group_state(
        ["P1", "P2", "P3"],
        {"p1": "control", "P2": "anxious"},
        {
            "P1": "Non-anxious",
            "p2": "Anxious",
            "P3": "Display label must not become a canonical ID",
        },
    )

    assert state.participant_group_id_map == {
        "P1": "control",
        "P2": "anxious",
    }
    assert state.subject_group_display_map == {
        "P1": "Non-anxious",
        "P2": "Anxious",
        "P3": "Display label must not become a canonical ID",
    }
    assert state.group_display_labels == {
        "anxious": "Anxious",
        "control": "Non-anxious",
    }
    assert state.group_participant_counts == {
        "anxious": 1,
        "control": 1,
    }
    assert state.unassigned_participants == ("P3",)


def test_canonical_group_pairs_are_deterministic_and_unique() -> None:
    assert canonical_group_pairs(
        ["small_group", "control", "anxious", "CONTROL"]
    ) == (
        ("anxious", "control"),
        ("anxious", "small_group"),
        ("control", "small_group"),
    )


def test_preliminary_coverage_retains_participants_and_flags_conditions() -> None:
    coverage = build_preliminary_workbook_coverage(
        ["P1", "P2", "P3"],
        ["Faces", "Objects"],
        {
            "P1": {"Faces": "p1_faces.xlsx", "Objects": "p1_objects.xlsx"},
            "p2": {"faces": "p2_faces.xlsx"},
            "P3": {"Faces": "p3_faces.xlsx", "Objects": "p3_objects.xlsx"},
        },
    )

    assert coverage.participants == ("P1", "P2", "P3")
    assert coverage.complete_conditions == ("Faces",)
    assert coverage.incomplete_conditions == ("Objects",)
    assert coverage.missing_by_condition == {"Faces": (), "Objects": ("P2",)}
    assert coverage.to_dict()["n_participants"] == 3

    summary = format_preliminary_workbook_coverage(coverage)
    assert summary.startswith("Preliminary workbook coverage")
    assert "Objects missing for P2" in summary
    assert "does not remove participants" in summary


def test_preliminary_coverage_reports_complete_selected_conditions() -> None:
    coverage = build_preliminary_workbook_coverage(
        ["P1", "P2"],
        ["Faces"],
        {
            "P1": {"Faces": "p1.xlsx"},
            "P2": {"Faces": "p2.xlsx"},
        },
    )

    assert coverage.complete_conditions == ("Faces",)
    assert coverage.incomplete_conditions == ()
    assert "all 1 selected conditions" in format_preliminary_workbook_coverage(
        coverage
    )


def test_native_state_snapshot_exposes_plain_pipeline_configuration() -> None:
    view = StatsWindowActionsMixin()
    view._project_is_multi_group = True
    view._dv_policy_name = GROUP_SIGNIFICANT_POLICY_NAME
    view.subjects = ["P1", "P2"]
    view.conditions = ["Faces"]
    view.selected_conditions = ["Faces"]
    view._condition_checkboxes = {}
    view.subject_data = {
        "P1": {"Faces": "p1.xlsx"},
        "P2": {"Faces": "p2.xlsx"},
    }
    view._participant_group_id_map = {
        "P1": "control",
        "P2": "anxious",
    }
    view._subject_group_map = {
        "P1": "Non-anxious",
        "P2": "Anxious",
    }
    view._group_display_labels = {
        "control": "Non-anxious",
        "anxious": "Anxious",
    }
    view._group_participant_counts = {"anxious": 1, "control": 1}
    view._unassigned_group_participants = ()

    snapshot = view._native_analysis_state_snapshot()

    assert snapshot["pipeline_id"] is PipelineId.MULTI
    assert snapshot["mode"] == "multi"
    assert snapshot["analysis_profile"] == "published_style_exploratory"
    assert snapshot["correction"] == "holm"
    assert snapshot["response_alternative"] == "two_sided"
    assert snapshot["analysis_scope"] == "complete_core"
    assert snapshot["strict_omnibus_family"] is True
    assert snapshot["harmonic_provenance"] == "same_sample_adaptive"
    assert snapshot["canonical_group_ids"] == view._participant_group_id_map
    assert snapshot["participant_display_labels"] == view._subject_group_map
    assert snapshot["selected_group_pair"] == ("anxious", "control")
    coverage = snapshot["preliminary_coverage"]
    assert coverage["complete_conditions"] == ["Faces"]
    assert coverage["n_participants"] == 2
