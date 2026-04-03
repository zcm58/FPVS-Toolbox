from __future__ import annotations

import json
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

try:
    from PySide6.QtWidgets import QMessageBox
    from Main_App.PySide6_App.Backend.project import EXCEL_SUBFOLDER_NAME, STATS_SUBFOLDER_NAME
    from Tools.Stats.PySide6 import stats_ui_pyside6 as stats_mod
    from Tools.Stats.PySide6 import stats_workers
    from Tools.Stats.PySide6.stats_controller import WORKER_FN_BY_STEP, StepId
    from Tools.Stats.PySide6.stats_multigroup_scan import MultiGroupScanResult
    from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pytest.skip("PySide6 is required for Stats smoke tests", allow_module_level=True)


@pytest.fixture
def stats_smoke_env(monkeypatch):
    """Patch heavy stats helpers so smoke tests focus on metadata wiring."""

    store: dict[str, dict] = {"payload": {}}

    dummy_df = pd.DataFrame({"Effect": ["group"], "Pr > F": [0.5]})

    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers.prepare_summed_bca_data",
        lambda *a, **k: store["payload"],
        raising=False,
    )
    monkeypatch.setattr(
        stats_mod,
        "analysis_run_rm_anova",
        lambda *a, **k: (None, dummy_df.copy()),
        raising=False,
    )
    monkeypatch.setattr(
        stats_mod,
        "run_mixed_group_anova",
        lambda *a, **k: dummy_df.copy(),
        raising=False,
    )
    monkeypatch.setattr(
        stats_mod,
        "run_mixed_effects_model",
        lambda *a, **k: dummy_df.copy(),
        raising=False,
    )
    monkeypatch.setattr(
        stats_mod,
        "generate_lme_summary",
        lambda *_a, **_k: "\nsummary",
        raising=False,
    )

    def _run_rm_anova(*_args, **_kwargs):
        return {"anova_df_results": dummy_df.copy(), "output_text": "rm"}

    def _run_lmm(*_args, **kwargs):
        payload = {"mixed_results_df": dummy_df.copy(), "output_text": "lmm"}
        if kwargs.get("include_group"):
            payload["missingness"] = {"mixed_model_missing_cells": [], "mixed_model_subjects": ["P1", "P2"]}
        return payload

    def _run_group_contrasts(*_args, **_kwargs):
        return {"results_df": dummy_df.copy(), "output_text": "contrasts"}

    def start_immediate(self, pipeline_id, step, *, finished_cb, error_cb):  # noqa: ARG001
        try:
            payload = step.worker_fn(lambda *_a, **_k: None, lambda *_a, **_k: None, **step.kwargs)
        except Exception as exc:  # noqa: BLE001
            error_cb(pipeline_id, step.id, str(exc))
        else:
            finished_cb(pipeline_id, step.id, payload or {})

    monkeypatch.setattr(stats_workers, "run_rm_anova", _run_rm_anova, raising=False)
    monkeypatch.setattr(stats_workers, "run_lmm", _run_lmm, raising=False)
    monkeypatch.setattr(stats_workers, "run_group_contrasts", _run_group_contrasts, raising=False)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.RM_ANOVA, _run_rm_anova)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.MIXED_MODEL, _run_lmm)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.BETWEEN_GROUP_MIXED_MODEL, _run_lmm)
    monkeypatch.setitem(WORKER_FN_BY_STEP, StepId.GROUP_CONTRASTS, _run_group_contrasts)
    monkeypatch.setattr(StatsWindow, "start_step_worker", start_immediate, raising=False)
    monkeypatch.setattr(StatsWindow, "export_pipeline_results", lambda self, pid: True, raising=False)
    monkeypatch.setattr(StatsWindow, "build_and_render_summary", lambda self, pid: None, raising=False)
    monkeypatch.setattr(StatsWindow, "refresh_rois", lambda self: setattr(self, "rois", {"ROI": ["Cz"]}), raising=False)
    monkeypatch.setattr(StatsWindow, "_get_analysis_settings", lambda self: (6.0, 0.05), raising=False)
    monkeypatch.setattr(StatsWindow, "_check_for_open_excel_files", lambda self, folder: False, raising=False)
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)

    return store


def _write_project_manifest(root: Path, *, groups: dict | None = None, participants: dict | None = None) -> None:
    data: dict[str, object] = {"name": "Test Project"}
    if groups:
        data["groups"] = groups
    if participants:
        data["participants"] = participants
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")


def _seed_excel_files(excel_root: Path, *, subjects: list[str], conditions: list[str]) -> None:
    for cond in conditions:
        cond_dir = excel_root / cond
        cond_dir.mkdir(parents=True, exist_ok=True)
        for pid in subjects:
            (cond_dir / f"{pid}_{cond}_Results.xlsx").write_text("", encoding="utf-8")


def _build_project(tmp_path: Path, *, subjects: list[str], conditions: list[str], groups: dict | None = None, participants: dict | None = None) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    root.mkdir()
    excel_root = root / EXCEL_SUBFOLDER_NAME
    excel_root.mkdir()
    _write_project_manifest(root, groups=groups, participants=participants)
    _seed_excel_files(excel_root, subjects=subjects, conditions=conditions)
    return root, excel_root


def _prime_supported_multigroup_state(win: StatsWindow, payload: dict[str, dict[str, dict[str, float]]]) -> None:
    rows: list[dict[str, object]] = []
    for subject, condition_map in payload.items():
        for condition, roi_map in condition_map.items():
            for roi_name, value in roi_map.items():
                rows.append(
                    {
                        "subject": subject,
                        "condition": condition,
                        "roi": roi_name,
                        "dv_value": value,
                    }
                )
    subject_to_group = win._between_subject_groups()
    group_to_subjects: dict[str, list[str]] = {}
    for subject, group_name in subject_to_group.items():
        if not group_name:
            continue
        group_to_subjects.setdefault(str(group_name), []).append(str(subject))
    assigned_subjects = sorted(subject_to_group)
    win._multigroup_scan_result = MultiGroupScanResult(
        subject_groups=sorted(group_to_subjects),
        group_to_subjects=group_to_subjects,
        unassigned_subjects=[],
        issues=[],
        multi_group_ready=True,
        discovered_subjects=assigned_subjects,
        assigned_subjects=assigned_subjects,
    )
    win._shared_harmonics_payload = {"harmonics_by_roi": {"ROI": [1.2]}}
    win._fixed_harmonic_dv_payload = {"dv_table": pd.DataFrame(rows)}


@pytest.mark.qt
def test_stats_single_group_behavior(qtbot, tmp_path, monkeypatch, stats_smoke_env):
    project_root, excel_root = _build_project(tmp_path, subjects=["P01"], conditions=["CondA", "CondB"])
    warnings: list[str] = []
    infos: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: warnings.append("warn"), raising=False)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, message, *_rest: infos.append(message),
        raising=False,
    )

    win = StatsWindow(project_dir=str(project_root))
    qtbot.addWidget(win)
    win.le_folder.setText(str(excel_root))
    win._scan_button_clicked()

    assert not warnings, "Legacy project should not raise group warnings during scan"

    stats_smoke_env["payload"] = {"P01": {"CondA": {"ROI": 1.0}, "CondB": {"ROI": 1.2}}}

    win.on_run_rm_anova()
    assert isinstance(win.rm_anova_results_data, pd.DataFrame)

    win.on_run_between_anova()
    assert any("paused" in msg.lower() for msg in infos)


@pytest.mark.qt
def test_stats_between_group_complete_metadata(qtbot, tmp_path, monkeypatch, stats_smoke_env):
    groups = {"GroupA": {"raw_input_folder": ""}, "GroupB": {"raw_input_folder": ""}}
    participants = {
        "P01": {"group": "GroupA"},
        "P02": {"group": "GroupB"},
    }
    project_root, excel_root = _build_project(
        tmp_path,
        subjects=["P01", "P02"],
        conditions=["CondA", "CondB"],
        groups=groups,
        participants=participants,
    )
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_k: warnings.append("warn"), raising=False)

    export_calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        StatsWindow,
        "export_results",
        lambda self, kind, _data, out_dir: export_calls.append((kind, Path(out_dir))),
        raising=False,
    )

    win = StatsWindow(project_dir=str(project_root))
    qtbot.addWidget(win)
    win.le_folder.setText(str(excel_root))
    win._scan_button_clicked()
    assert not warnings

    stats_smoke_env["payload"] = {
        "P01": {"CondA": {"ROI": 1.0}, "CondB": {"ROI": 1.2}},
        "P02": {"CondA": {"ROI": 2.0}, "CondB": {"ROI": 2.2}},
    }
    _prime_supported_multigroup_state(win, stats_smoke_env["payload"])

    win.on_run_between_mixed_model()
    win.on_run_group_contrasts()

    assert isinstance(win.between_mixed_model_results_data, pd.DataFrame)
    assert isinstance(win.group_contrasts_results_data, pd.DataFrame)

    win.on_export_between_mixed()
    win.on_export_group_contrasts()
    kinds = {kind for kind, _path in export_calls}
    assert {"lmm_between", "group_contrasts"}.issubset(kinds)
    assert any(STATS_SUBFOLDER_NAME in str(path) for _kind, path in export_calls)


@pytest.mark.qt
def test_stats_multigroup_missing_participants_warns_once(qtbot, tmp_path, monkeypatch, stats_smoke_env):
    groups = {"GroupA": {"raw_input_folder": ""}, "GroupB": {"raw_input_folder": ""}}
    participants = {
        "P01": {"group": "GroupA"},
        "P02": {"group": "GroupB"},
    }
    project_root, excel_root = _build_project(
        tmp_path,
        subjects=["P01", "P02", "P03", "P04"],
        conditions=["CondA", "CondB"],
        groups=groups,
        participants=participants,
    )

    warnings: list[str] = []
    infos: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message, *_rest: warnings.append(message),
        raising=False,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_a, **_k: infos.append("info"),
        raising=False,
    )

    win = StatsWindow(project_dir=str(project_root))
    qtbot.addWidget(win)
    win.le_folder.setText(str(excel_root))
    win._scan_button_clicked()

    assert len(warnings) == 1
    assert "not recognized" in warnings[0]

    stats_smoke_env["payload"] = {
        "P01": {"CondA": {"ROI": 1.0}, "CondB": {"ROI": 1.2}},
        "P02": {"CondA": {"ROI": 2.0}, "CondB": {"ROI": 2.2}},
        "P03": {"CondA": {"ROI": 3.0}, "CondB": {"ROI": 3.2}},
        "P04": {"CondA": {"ROI": 4.0}, "CondB": {"ROI": 4.2}},
    }
    _prime_supported_multigroup_state(win, stats_smoke_env["payload"])

    win.on_run_between_mixed_model()
    win.on_run_group_contrasts()

    assert isinstance(win.between_mixed_model_results_data, pd.DataFrame)
    assert isinstance(win.group_contrasts_results_data, pd.DataFrame)
    assert not infos, "Between-group actions should succeed without multi-group errors"
