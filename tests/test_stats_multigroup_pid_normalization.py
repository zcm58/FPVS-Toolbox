from __future__ import annotations

import pytest

try:
    from Tools.Stats.PySide6.stats_core import PipelineId, StepId
    from Tools.Stats.PySide6.stats_multigroup_scan import MultiGroupScanResult, ScanIssue
    from Tools.Stats.PySide6.stats_multigroup_ids import build_multigroup_runtime_snapshot
    from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytest.skip("PySide6 is required for multigroup PID normalization tests", allow_module_level=True)


@pytest.fixture(autouse=True)
def _stub_default_loader(monkeypatch):
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)


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


@pytest.mark.qt
def test_between_get_step_config_uses_canonical_multigroup_snapshot(qtbot, tmp_path, monkeypatch) -> None:
    win = StatsWindow(project_dir=str(tmp_path))
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
    monkeypatch.setattr(StatsWindow, "_ensure_results_dir", lambda self: str(tmp_path), raising=False)

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
def test_update_multigroup_summary_does_not_overwrite_logrecord_message(qtbot, tmp_path) -> None:
    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)

    result = MultiGroupScanResult(
        subject_groups=["GroupA"],
        group_to_subjects={"GroupA": ["P1"]},
        unassigned_subjects=[],
        issues=[ScanIssue(severity="warning", message="Normalized P01 -> P1", context={"pid": "P1"})],
        multi_group_ready=True,
        discovered_subjects=["P1"],
        assigned_subjects=["P1"],
    )

    win._update_multigroup_summary(result)
