from __future__ import annotations

import sys

import pytest

pytest.importorskip("PySide6")

from Tools.Stats.ui.stats_window import StatsWindow


@pytest.mark.qt
def test_pyside_stats_window_does_not_import_customtkinter(qtbot, tmp_path):
    sys.modules.pop("customtkinter", None)
    sys.modules.pop("tkinter", None)

    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    window.refresh_rois()

    assert "customtkinter" not in sys.modules
    assert "tkinter" not in sys.modules


@pytest.mark.qt
def test_main_window_stats_launch_does_not_import_legacy_stats(qtbot, tmp_path, monkeypatch):
    sys.modules.pop("customtkinter", None)
    for name in list(sys.modules):
        if name.startswith(("Tools.Stats.Legacy", "Tools.Stats.PySide6")):
            sys.modules.pop(name, None)

    from PySide6.QtWidgets import QWidget, QMessageBox

    from Main_App.gui import main_window as main_window_module
    import Main_App.gui.update_manager as update_manager

    class _DummyStatsWindow(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)

    monkeypatch.setattr(update_manager, "cleanup_old_executable", lambda: None)
    monkeypatch.setattr(update_manager, "check_for_updates_on_launch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_window_module,
        "select_projects_root",
        lambda self: setattr(self, "projectsRoot", tmp_path),
    )
    monkeypatch.setattr(main_window_module, "PysideStatsWindow", _DummyStatsWindow)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Ok))

    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.open_stats_analyzer()

    assert "customtkinter" not in sys.modules
    assert not any(name.startswith("Tools.Stats.Legacy") for name in sys.modules)
    assert not any(name.startswith("Tools.Stats.PySide6") for name in sys.modules)
    assert hasattr(window, "_child_windows")
    assert len(window._child_windows) == 1
    assert isinstance(window._child_windows[0], _DummyStatsWindow)
