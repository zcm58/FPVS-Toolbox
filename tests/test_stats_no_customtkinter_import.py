from __future__ import annotations

import sys

import pytest

pytest.importorskip("PySide6")

from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow


@pytest.mark.qt
def test_pyside_stats_window_does_not_import_customtkinter(qtbot, tmp_path):
    sys.modules.pop("customtkinter", None)

    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    window.refresh_rois()

    assert "customtkinter" not in sys.modules
