from __future__ import annotations

import json
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

try:
    from PySide6.QtWidgets import QMessageBox
    from Main_App.PySide6_App.Backend.project import EXCEL_SUBFOLDER_NAME, STATS_SUBFOLDER_NAME
    from Tools.Stats.PySide6 import stats_ui_pyside6 as stats_mod
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

    def immediate_wire(self, worker, finished_slot):
        payload = worker._fn(  # noqa: SLF001 - test helper
            lambda *_a, **_k: None,
            lambda *_a, **_k: None,
            *worker._args,
            **worker._kwargs,
        )
        finished_slot(payload or {})

    monkeypatch.setattr(StatsWindow, "_wire_and_start", immediate_wire, raising=False)
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


@pytest.mark.qt
def test_stats_single_group_behavior(qtbot, tmp_path, monkeypatch, stats_smoke_env):
    project_root, excel_root = _build_project(tmp_path, subjects=["P01"], conditions=["CondA"])
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

    stats_smoke_env["payload"] = {"P01": {"CondA": {"ROI": 1.0}}}

    win.on_run_rm_anova()
    assert isinstance(win.rm_anova_results_data, pd.DataFrame)

    win.on_run_between_anova()
    assert any("Between-group" in msg or "between-group" in msg.lower() for msg in infos)


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
        conditions=["CondA"],
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
        "P01": {"CondA": {"ROI": 1.0}},
        "P02": {"CondA": {"ROI": 2.0}},
    }

    win.on_run_between_anova()
    win.on_run_between_mixed_model()

    assert isinstance(win.between_anova_results_data, pd.DataFrame)
    assert isinstance(win.between_mixed_model_results_data, pd.DataFrame)

    win.on_export_between_anova()
    win.on_export_between_mixed()
    kinds = {kind for kind, _path in export_calls}
    assert {"anova_between", "lmm_between"}.issubset(kinds)
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
        conditions=["CondA"],
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
    assert "Unrecognized Excel Files" in warnings[0]

    stats_smoke_env["payload"] = {
        "P01": {"CondA": {"ROI": 1.0}},
        "P02": {"CondA": {"ROI": 2.0}},
        "P03": {"CondA": {"ROI": 3.0}},
        "P04": {"CondA": {"ROI": 4.0}},
    }

    win.on_run_between_anova()
    win.on_run_between_mixed_model()

    assert isinstance(win.between_anova_results_data, pd.DataFrame)
    assert isinstance(win.between_mixed_model_results_data, pd.DataFrame)
    assert not infos, "Between-group actions should succeed without multi-group errors"
