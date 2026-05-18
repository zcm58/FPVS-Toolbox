import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QSplitter, QStackedWidget, QWidget

from Main_App.gui import main_window as main_window_module
from Main_App.gui.components import ActionRow
import Main_App.gui.update_manager as update_manager
from Tools.Average_Preprocessing.New_PySide6.main_window import AdvancedAveragingWindow
from Tools.Image_Resizer.pyside_resizer import FPVSImageResizerQt


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


def _sidebar_button(win: main_window_module.MainWindow, role: str) -> QWidget:
    matches = [
        widget
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("role") == role
    ]
    assert len(matches) == 1
    return matches[0]


def test_landing_page_full_window_welcome_layout(tmp_path: Path, qtbot, monkeypatch) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)

    assert win.stacked.currentIndex() == 0
    assert win.landing_page is win.stacked.currentWidget()
    assert win.landing_card.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert win.landing_card.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert win.landing_card.maximumWidth() >= 10_000
    assert not hasattr(win, "landing_brain_animation")

    labels = {label.text() for label in win.landing_page.findChildren(QLabel)}
    assert "FPVS Toolbox" in labels
    assert "Welcome to FPVS Toolbox!" in labels
    assert "Create a new FPVS project or open an existing one." in labels
    title = next(
        label
        for label in win.landing_page.findChildren(QLabel)
        if label.text() == "Welcome to FPVS Toolbox!"
    )
    assert not title.wordWrap()
    assert title.minimumHeight() >= 58
    assert title.sizeHint().height() <= title.minimumHeight()

    assert win.btn_create_project.text() == "New Project"
    assert win.btn_open_project.text() == "Open Project"
    assert win.actionImportFpvsConfigProject.text() == "Import FPVS Studio Config..."
    assert win.btn_create_project.isVisibleTo(win)
    assert win.btn_open_project.isVisibleTo(win)
    landing_actions = win.findChild(ActionRow, "main_landing_actions")
    assert landing_actions is not None
    assert landing_actions.row_layout.indexOf(win.btn_create_project) >= 0
    assert landing_actions.row_layout.indexOf(win.btn_open_project) >= 0


def test_main_window_layout_smoke(tmp_path: Path, qtbot, monkeypatch) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    splitter = win.findChild(QSplitter, "main_page_splitter")
    assert splitter is not None
    workspace_stack = win.findChild(QStackedWidget, "workspace_stack")
    assert workspace_stack is not None
    assert workspace_stack.currentWidget() is win.homeWidget
    assert splitter.orientation() == Qt.Vertical
    assert splitter.widget(0) is not None
    assert splitter.widget(1) is not None
    assert splitter.widget(1).isAncestorOf(win.text_log)

    assert win.btn_start.text() == "Start Processing"
    run_panel = win.findChild(ActionRow, "run_panel")
    assert run_panel is not None
    assert run_panel.row_layout.indexOf(win.btn_start) >= 0
    assert run_panel.row_layout.indexOf(win.progress_bar) >= 0
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
    settings_buttons = [
        widget
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("role") == "btn_settings"
    ]
    assert len(settings_buttons) == 1
    settings_pixmaps = [
        label.pixmap()
        for label in settings_buttons[0].findChildren(QLabel)
        if label.pixmap() is not None
    ]
    assert any(not pixmap.isNull() for pixmap in settings_pixmaps)

    help_actions = []
    for action in win.menuBar().actions():
        menu = action.menu()
        if menu and menu.title() == "Help":
            help_actions = [child.text() for child in menu.actions() if child.text()]
            break
    assert "Relevant Publications" not in help_actions
    assert any(text.startswith("About") for text in help_actions)


def test_sidebar_image_resizer_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    qtbot.mouseClick(_sidebar_button(win, "btn_image"), Qt.LeftButton)
    qtbot.wait(20)

    assert win.stacked.currentIndex() == 1
    assert isinstance(win.workspace_stack.currentWidget(), FPVSImageResizerQt)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_image_resizer_page"
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_image"]

    qtbot.mouseClick(_sidebar_button(win, "btn_home"), Qt.LeftButton)
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_home"]


def test_sidebar_epoch_averaging_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    project_root = tmp_path / "project"
    data_dir = project_root / "data"
    excel_dir = project_root / "excel"
    data_dir.mkdir(parents=True)
    excel_dir.mkdir()
    (data_dir / "P001.bdf").touch()
    win.currentProject = SimpleNamespace(
        project_root=project_root,
        input_folder=data_dir,
        subfolders={"data": "data", "excel": "excel"},
    )
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    qtbot.mouseClick(_sidebar_button(win, "btn_epoch"), Qt.LeftButton)
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), AdvancedAveragingWindow)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_epoch_averaging_page"
    assert win._epoch_page.parent() is win.workspace_stack
    assert win._epoch_page.main_app() is win
    assert win._epoch_page.source_eeg_files == [str(data_dir / "P001.bdf")]
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_epoch"]

    qtbot.mouseClick(win._epoch_page.btn_close, Qt.LeftButton)
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_home"]
