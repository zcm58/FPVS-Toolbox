from __future__ import annotations

import logging
from pathlib import Path

import pytest

try:
    from Tools.Stats.common.stats_core import PipelineId, StepId
    from Tools.Stats.data.stats_multigroup_scan import MultiGroupScanResult, ScanIssue
    from Tools.Stats.data.stats_multigroup_ids import build_multigroup_runtime_snapshot
    from Tools.Stats.ui.stats_window import StatsWindow
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytest.skip("PySide6 is required for multigroup PID normalization tests", allow_module_level=True)


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


def _project_dir(name: str) -> Path:
    path = Path.cwd() / ".codex-tmp" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_multigroup_runtime_snapshot_normalizes_and_warns() -> None:
    snapshot = build_multigroup_runtime_snapshot(
        manifest={
            "groups": {"GroupA": {}},
            "participants": {"P01": {"group": "GroupA"}},
        },
        subjects=["P1", "P01"],
        subject_data={
            "P01": {"CondA": "P01_CondA.xlsx"},
            "P1": {"CondB": "P1_CondB.xlsx"},
        },
    )

    assert snapshot.subjects == ["P1"]
    assert snapshot.subject_groups == {"P1": "GroupA"}
    assert snapshot.subject_data == {
        "P1": {
            "CondA": "P01_CondA.xlsx",
            "CondB": "P1_CondB.xlsx",
        }
    }
    assert snapshot.errors == []
    assert len(snapshot.warnings) == 1
    assert "P01 -> P1" in snapshot.warnings[0]


def test_multigroup_runtime_snapshot_ambiguous_condition_collision_fails_clearly() -> None:
    snapshot = build_multigroup_runtime_snapshot(
        manifest={
            "groups": {"GroupA": {}},
            "participants": {"P1": {"group": "GroupA"}},
        },
        subjects=["P1", "P01"],
        subject_data={
            "P1": {"CondA": "P1_CondA.xlsx"},
            "P01": {"CondA": "P01_CondA.xlsx"},
        },
    )

    assert snapshot.errors
    assert "collapse to P1" in snapshot.errors[0]


def test_multigroup_runtime_snapshot_accepts_prefixed_manifest_participant_ids() -> None:
    snapshot = build_multigroup_runtime_snapshot(
        manifest={
            "groups": {"GroupA": {}},
            "participants": {"ValenceP01": {"group": "GroupA"}},
        },
        subjects=["P1"],
        subject_data={"P1": {"CondA": "P1_CondA.xlsx"}},
    )

    assert snapshot.subjects == ["P1"]
    assert snapshot.subject_groups == {"P1": "GroupA"}
    assert snapshot.errors == []
    assert any("ValenceP01 -> P1" in warning for warning in snapshot.warnings)
    assert any(
        "left source files/manifests unchanged" in warning
        for warning in snapshot.warnings
    )
    assert all(
        "rename source files/manifests" not in warning.lower()
        for warning in snapshot.warnings
    )


@pytest.mark.qt
def test_between_get_step_config_uses_canonical_multigroup_snapshot(qtbot, monkeypatch) -> None:
    project_dir = _project_dir("multigroup-step-config")
    win = StatsWindow(project_dir=str(project_dir))
    qtbot.addWidget(win)

    manifest = {
        "groups": {"GroupA": {}},
        "participants": {"P01": {"group": "GroupA"}},
    }
    win._multi_group_manifest = True
    win.subjects = ["P01", "P1"]
    win.subject_data = {
        "P01": {"CondA": "P01_CondA.xlsx"},
        "P1": {"CondB": "P1_CondB.xlsx"},
    }
    win.subject_groups = {"P01": None, "P1": None}
    win._between_subject_snapshot = build_multigroup_runtime_snapshot(
        manifest=manifest,
        subjects=win.subjects,
        subject_data=win.subject_data,
    )
    win.conditions = ["CondA", "CondB"]
    win.rois = {"ROI": ["Cz"]}
    win._current_base_freq = 6.0
    win._current_alpha = 0.05
    win.manual_excluded_pids = {"P01"}

    monkeypatch.setattr(StatsWindow, "_get_selected_conditions", lambda self: ["CondA", "CondB"], raising=False)
    monkeypatch.setattr(StatsWindow, "_ensure_results_dir", lambda self: str(project_dir), raising=False)

    kwargs, _handler = win.get_step_config(PipelineId.BETWEEN, StepId.BETWEEN_GROUP_MIXED_MODEL)

    assert kwargs["subjects"] == ["P1"]
    assert kwargs["manual_excluded_pids"] == ["P1"]
    assert kwargs["subject_groups"] == {"P1": "GroupA"}
    assert kwargs["subject_to_group"] == {"P1": "GroupA"}
    assert kwargs["subject_data"] == {
        "P1": {
            "CondA": "P01_CondA.xlsx",
            "CondB": "P1_CondB.xlsx",
        }
    }


@pytest.mark.qt
def test_update_multigroup_summary_logs_one_issue_summary(qtbot, caplog) -> None:
    win = StatsWindow(project_dir=str(_project_dir("multigroup-summary-logrecord")))
    qtbot.addWidget(win)

    result = MultiGroupScanResult(
        subject_groups=["GroupA"],
        group_to_subjects={"GroupA": ["P1"]},
        unassigned_subjects=[],
        issues=[
            ScanIssue(
                severity="warning",
                message="Subject listed in manifest has no Excel outputs.",
                context={"pid": f"P{pid}"},
            )
            for pid in range(1, 6)
        ],
        multi_group_ready=True,
        discovered_subjects=["P1"],
        assigned_subjects=["P1"],
    )

    with caplog.at_level(logging.INFO, logger="Tools.Stats.ui.stats_window_multigroup"):
        win._update_multigroup_summary(result)

    issue_records = [
        record for record in caplog.records if record.message == "stats_multigroup_issue"
    ]
    summary_records = [
        record
        for record in caplog.records
        if record.message == "stats_multigroup_issues_summary"
    ]
    assert issue_records == []
    assert len(summary_records) == 1
    assert summary_records[0].issue_count == 5
    assert summary_records[0].warning_count == 5
    assert summary_records[0].blocking_count == 0
    assert "pid=P1" in summary_records[0].preview
    assert "... 2 more issue(s)" in summary_records[0].preview
    assert "P5" in win.multi_group_issue_text.toPlainText()
