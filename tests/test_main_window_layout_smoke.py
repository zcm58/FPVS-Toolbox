import importlib.util
import os
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QWidget

from Main_App.gui import main_window as main_window_module
import Main_App.gui.update_manager as update_manager


def _build_window(tmp_path: Path, qtbot, monkeypatch) -> main_window_module.MainWindow:
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(update_manager, "cleanup_old_executable", lambda: None)
    monkeypatch.setattr(update_manager, "check_for_updates_on_launch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_window_module,
        "select_projects_root",
        lambda self: setattr(self, "projectsRoot", tmp_path),
    )

    win = main_window_module.MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.wait(50)
    return win


def test_main_window_layout_smoke(tmp_path: Path, qtbot, monkeypatch) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    splitter = win.findChild(QSplitter, "main_page_splitter")
    assert splitter is not None
    assert splitter.orientation() == Qt.Vertical
    assert splitter.widget(0) is not None
    assert splitter.widget(1) is not None
    assert splitter.widget(1).isAncestorOf(win.text_log)

    assert win.btn_start.text() == "Start Processing"
    assert win.findChild(QWidget, "preprocessing_info_strip") is not None
    assert win.findChild(QWidget, "event_map_header") is not None
    assert win.findChild(QWidget, "log_group") is not None

    assert hasattr(win, "row_single_file")
    assert hasattr(win, "row_input_folder")
    active_row = win.row_single_file if win.rb_single.isChecked() else win.row_input_folder
    inactive_row = win.row_input_folder if win.rb_single.isChecked() else win.row_single_file
    assert active_row.isVisible()
    assert not inactive_row.isVisible()

    win.rb_single.setChecked(True)
    qtbot.wait(20)
    assert win.row_single_file.isVisible()
    assert not win.row_input_folder.isVisible()

    win.rb_batch.setChecked(True)
    qtbot.wait(20)
    assert win.row_input_folder.isVisible()
    assert not win.row_single_file.isVisible()

    selected_sidebar_items = [
        widget
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_sidebar_items
