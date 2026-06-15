from __future__ import annotations

import json

from Tools.Publication_Workflow.state import (
    QCDecision,
    STEP_DATA_READY,
    STEP_ORDER,
    excluded_participants,
    load_qc_decisions,
    load_workflow_state,
    qc_decisions_path,
    save_qc_decisions,
    save_workflow_state,
    update_step,
    with_frozen_exclusions,
    workflow_state_path,
)


def test_workflow_state_roundtrip_uses_project_report_folder(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "results_folder": ".",
                "subfolders": {"excel": "1 - Excel Data Files"},
            }
        ),
        encoding="utf-8",
    )

    state = load_workflow_state(project_root)
    assert len(state.steps) == len(STEP_ORDER)
    assert workflow_state_path(project_root).parent == project_root / "5 - Publication Report"

    state = update_step(
        state,
        STEP_DATA_READY,
        status="complete",
        message="ready",
        artifacts=("1 - Excel Data Files",),
    )
    path = save_workflow_state(project_root, state)

    loaded = load_workflow_state(project_root)
    assert path == project_root / "5 - Publication Report" / "Workflow_State.json"
    assert loaded.steps[0].status == "complete"
    assert loaded.steps[0].message == "ready"
    assert loaded.steps[0].artifacts == ("1 - Excel Data Files",)


def test_qc_decisions_roundtrip_and_exclusions(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    decisions = (
        QCDecision(
            participant_id="p22",
            condition="Color Response",
            roi="Right Occipito-Temporal",
            metric_source="summed_bca_uv",
            metric_label="Summed BCA (uV)",
            value=-1.47,
            lower_iqr_fence=-0.59,
            upper_iqr_fence=1.2,
            outlier_direction="low",
            decision="exclude",
            reason="Manual QC exclusion after review.",
        ),
        QCDecision(
            participant_id="P16",
            condition="Color Response",
            roi="Left Occipito-Temporal",
            metric_source="summed_bca_uv",
            decision="watch",
        ),
    )

    path = save_qc_decisions(project_root, decisions)
    loaded = load_qc_decisions(project_root)

    assert path == qc_decisions_path(project_root)
    assert loaded[0].participant_id == "P22"
    assert loaded[0].decision == "exclude"
    assert loaded[0].reason == "Manual QC exclusion after review."
    assert excluded_participants(loaded) == ("P22",)

    state = with_frozen_exclusions(load_workflow_state(project_root), excluded_participants(loaded))
    assert state.frozen_excluded_subjects == ("P22",)
