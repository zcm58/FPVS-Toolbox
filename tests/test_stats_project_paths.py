from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from Main_App.PySide6_App.Backend.project import (
    EXCEL_SUBFOLDER_NAME,
    STATS_SUBFOLDER_NAME,
)
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow


def _patch_scan(monkeypatch):
    def _fake_scan(self):
        setattr(self, "_scan_called", True)

    monkeypatch.setattr(StatsWindow, "_scan_button_clicked", _fake_scan, raising=False)


def _write_manifest(root: Path, data: dict) -> None:
    (root / "project.json").write_text(json.dumps(data))


def test_stats_prefers_flat_layout(tmp_path, qtbot, monkeypatch):
    _patch_scan(monkeypatch)
    proj = tmp_path / "Flat"
    proj.mkdir()
    excel = proj / EXCEL_SUBFOLDER_NAME
    stats_dir = proj / STATS_SUBFOLDER_NAME
    excel.mkdir(parents=True)
    data = {
        "results_folder": ".",
        "subfolders": {
            "excel": EXCEL_SUBFOLDER_NAME,
            "stats": STATS_SUBFOLDER_NAME,
        },
    }
    _write_manifest(proj, data)

    win = StatsWindow(project_dir=str(proj))
    qtbot.addWidget(win)
    win._load_default_data_folder()

    assert Path(win.le_folder.text()) == excel.resolve()
    assert Path(win._ensure_results_dir()) == stats_dir.resolve()
    win.close()


def test_stats_handles_legacy_results_root(tmp_path, qtbot, monkeypatch):
    _patch_scan(monkeypatch)
    proj = tmp_path / "Legacy"
    proj.mkdir()
    results = proj / "Results"
    excel = results / EXCEL_SUBFOLDER_NAME
    stats_dir = results / STATS_SUBFOLDER_NAME
    excel.mkdir(parents=True)
    data = {
        "results_folder": "Results",
        "subfolders": {
            "excel": EXCEL_SUBFOLDER_NAME,
            "stats": STATS_SUBFOLDER_NAME,
        },
    }
    _write_manifest(proj, data)

    win = StatsWindow(project_dir=str(proj))
    qtbot.addWidget(win)
    win._load_default_data_folder()

    assert Path(win.le_folder.text()) == excel.resolve()
    assert Path(win._ensure_results_dir()) == stats_dir.resolve()
    win.close()
