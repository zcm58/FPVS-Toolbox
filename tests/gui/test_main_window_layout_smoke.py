import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import QEvent, QPoint, QSize, Signal, Qt
from PySide6.QtGui import QAction, QIcon, QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QWidget,
)

from Main_App.settings.settings_manager import SettingsManager
from Main_App.gui import main_window as main_window_module
from Main_App.gui.components import ActionRow
from Main_App.gui.components import SectionCard
from Main_App.gui.components import SubsectionHeaderLabel
from Main_App.gui.processing_log_dialog import ProcessingLogDialog
from Main_App.gui.settings_panel import EmbeddedSettingsPage
from Main_App.gui.style_tokens import PAGE_MARGIN
from Main_App.processing.preflight_qc_cache import preflight_qc_cache_directory
from Main_App.processing.project_processing_cache import ProjectProcessingCacheUsage
from Main_App.projects import Project
import Main_App.gui.update_manager as update_manager
from Tools.Individual_Detectability.main_window import IndividualDetectabilityWindow
from Tools.Plot_Generator.plot_generator import PlotGeneratorWindow
from Tools.Publication_Maps.gui import PublicationMapsWindow
from Tools.Publication_Maps.generation_outcome import PublicationMapsWorkerOutcome
from Tools.Sensitivity_Analysis.gui import SensitivityAnalysisWindow
from Tools.Stats import StatsWindow


DEFAULT_TOOL_ROLES = [
    "btn_free_harmonic_clustering",
    "btn_graphs",
]
BETA_TOOL_ROLES = [
    "btn_publication_maps",
    "btn_data",
    "btn_sensitivity_analysis",
    "btn_loreta_visualizer",
    "btn_sequence_figure",
    "btn_individual_detectability",
]
BETA_TOOL_ACCESSIBLE_NAMES = [
    "Scalp Maps",
    "Standard FPVS Screening",
    "Sensitivity Analysis",
    "LORETA Visualizer",
    "Sequence Figure",
    "Individual Detectability",
]


def _build_window(
    tmp_path: Path,
    qtbot,
    monkeypatch,
    *,
    enable_beta_tools: bool = False,
    debug_enabled: bool = False,
    appearance_mode: str = "Auto",
) -> main_window_module.MainWindow:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(update_manager, "cleanup_old_executable", lambda: None)
    monkeypatch.setattr(update_manager, "check_for_updates_on_launch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_window_module,
        "select_projects_root",
        lambda self: setattr(self, "projectsRoot", tmp_path),
    )
    settings = SettingsManager()
    settings.set_beta_tools_enabled(enable_beta_tools)
    settings.set_appearance_mode(appearance_mode)
    settings.set("debug", "enabled", str(debug_enabled))
    settings.save()

    win = main_window_module.MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.wait(50)
    return win


def _menu(win: main_window_module.MainWindow, object_name: str) -> QMenu:
    menu = win.menuBar().findChild(QMenu, object_name)
    assert menu is not None
    return menu


def _menu_action(win: main_window_module.MainWindow, menu_name: str, role: str) -> QAction:
    return next(action for action in _menu(win, menu_name).actions() if action.objectName() == role)


def _open_beta_tool(win: main_window_module.MainWindow, role: str) -> None:
    _menu_action(win, "betaToolsMenu", role).trigger()


@pytest.mark.parametrize("beta_enabled", [False, True])
def test_tools_menu_contains_default_and_enabled_beta_tools(tmp_path: Path, qtbot, monkeypatch, beta_enabled) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch, enable_beta_tools=beta_enabled)
    win.show_home_page()
    tools_actions = _menu(win, "toolsMenu").actions()
    assert [action.text() for action in tools_actions[:2]] == [
        "Free Harmonic Clustering Analysis", "SNR Plots",
    ]
    assert [action.objectName() for action in tools_actions[:2]] == DEFAULT_TOOL_ROLES
    assert tools_actions[-2].isSeparator()
    assert tools_actions[-1] is win.shell_actions.processing_log
    if beta_enabled:
        assert tools_actions[2].isSeparator()
        beta_menu = _menu(win, "betaToolsMenu")
        assert tools_actions[3].menu() is beta_menu
        assert [action.objectName() for action in beta_menu.actions()] == BETA_TOOL_ROLES
        assert [action.text() for action in beta_menu.actions()] == BETA_TOOL_ACCESSIBLE_NAMES
    else:
        assert len(tools_actions) == 4
        assert win.menuBar().findChild(QMenu, "betaToolsMenu") is None


def test_welcome_prioritizes_opening_a_project_and_fits_minimum_window(
    tmp_path: Path, qtbot, monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)

    assert win.stacked.currentWidget() is win.landing_page
    assert win.minimumSize() == QSize(1200, 800)
    assert win.size() == QSize(1200, 800)
    assert win.windowTitle() == f"FPVS Toolbox v{main_window_module.FPVS_TOOLBOX_VERSION}"
    assert not win.findChildren(QStatusBar)
    assert win.menuBar().isVisibleTo(win)

    title = win.landing_page.findChild(QLabel, "landing_title")
    icon = win.landing_page.findChild(QLabel, "welcomeAppIcon")
    assert title is not None and title.text() == "FPVS Toolbox"
    assert icon is not None and not icon.pixmap().isNull()
    assert win.btn_open_project.text() == "Open Existing Project…"
    assert win.btn_create_project.text() == "Create New Project…"
    assert win.btn_open_project.property("variant") == "primary"
    assert win.btn_create_project.property("variant") == "secondary"
    buttons = win.landing_page.findChildren(QPushButton)
    assert len(buttons) == 2
    assert win.btn_open_project in buttons and win.btn_create_project in buttons
    assert win.btn_open_project.width() > 340
    assert win.actionImportFpvsConfigProject is not win.actionCreateNewProject

    win.resize(win.minimumSize())
    QApplication.processEvents()
    for widget in (title, icon, win.btn_open_project, win.btn_create_project):
        assert widget.isVisibleTo(win)
        assert win.rect().contains(widget.mapTo(win, widget.rect().topLeft()))
        assert win.rect().contains(widget.mapTo(win, widget.rect().bottomRight()))
    open_button, create_button = win.btn_open_project, win.btn_create_project
    assert open_button.height() >= 52 and create_button.height() >= 52
    assert open_button.width() == create_button.width()
    assert (
        open_button.mapTo(win, open_button.rect().bottomLeft()).y()
        < create_button.mapTo(win, create_button.rect().topLeft()).y()
    )


def test_welcome_open_existing_project_runs_directly(tmp_path: Path, qtbot, monkeypatch) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    calls = []
    monkeypatch.setattr(
        main_window_module.project_workflows,
        "_open_existing_project",
        lambda host, parent: calls.append((host, parent)),
    )

    qtbot.mouseClick(win.btn_open_project, Qt.LeftButton)

    assert calls == [(win, win)]
    assert QApplication.activeModalWidget() is None


def _open_project_creation_choices(win: main_window_module.MainWindow, qtbot) -> QDialog:
    qtbot.mouseClick(win.btn_create_project, Qt.LeftButton)
    chooser = win.findChild(QDialog, "projectCreationChoices")
    assert chooser is not None and chooser.isVisible()
    assert chooser.windowTitle() == "Create New Project"
    return chooser


@pytest.fixture
def project_creation_calls(monkeypatch):
    calls = []
    for route in ("_new_project", "_new_project_from_fpvs_config"):
        monkeypatch.setattr(
            main_window_module.project_workflows,
            route,
            lambda *_args, name=route: calls.append((name, QApplication.activeModalWidget())),
        )
    return calls


@pytest.mark.parametrize(("button_name", "button_text", "workflow_name"), [
    ("welcomeCreateManually", "Create Project Manually…", "_new_project"),
    ("welcomeImportStudio", "Import FPVS Studio Config…", "_new_project_from_fpvs_config"),
])
def test_cancelled_project_creation_returns_to_welcome(
    tmp_path: Path,
    qtbot,
    monkeypatch,
    project_creation_calls,
    button_name,
    button_text,
    workflow_name,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    chooser = _open_project_creation_choices(win, qtbot)
    button = chooser.findChild(QPushButton, button_name)
    assert button is not None and button.text() == button_text
    assert project_creation_calls == []
    qtbot.mouseClick(button, Qt.LeftButton)

    qtbot.waitUntil(lambda: bool(project_creation_calls))
    assert project_creation_calls == [(workflow_name, None)]
    assert win.currentProject is None
    assert win.stacked.currentWidget() is win.landing_page
    assert win.menuBar().isVisibleTo(win)


@pytest.mark.parametrize("dismiss_with_escape", [False, True], ids=["cancel", "escape"])
def test_dismissing_creation_choices_runs_no_project_action(
    tmp_path: Path, qtbot, monkeypatch, project_creation_calls, dismiss_with_escape: bool,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    chooser = _open_project_creation_choices(win, qtbot)

    with qtbot.waitSignal(chooser.rejected, timeout=1000):
        if dismiss_with_escape:
            qtbot.keyClick(chooser, Qt.Key_Escape)
        else:
            buttons = chooser.findChild(QDialogButtonBox)
            assert buttons is not None
            cancel = buttons.button(QDialogButtonBox.Cancel)
            assert cancel is not None
            qtbot.mouseClick(cancel, Qt.LeftButton)

    QApplication.processEvents()
    assert project_creation_calls == []
    assert win.currentProject is None
    assert win.stacked.currentWidget() is win.landing_page


def test_main_window_layout_smoke(tmp_path: Path, qtbot, monkeypatch) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    assert not win.menuBar().isHidden()
    workspace_stack = win.findChild(QStackedWidget, "workspace_stack")
    assert workspace_stack is not None
    assert workspace_stack.currentWidget() is win.homeWidget
    assert win.homeWidget.objectName() == "setup_panel"
    assert win.findChild(QWidget, "main_page_splitter") is None
    assert isinstance(win.processing_log_dialog, ProcessingLogDialog)
    assert win.text_log is win.processing_log_dialog.viewer
    assert not win.homeWidget.isAncestorOf(win.text_log)
    assert win.processing_history_label.objectName() == "project_processing_history"
    assert not win.processing_history_label.isVisibleTo(win)
    assert win.processing_history_label.wordWrap()
    workflow = win.findChild(QWidget, "home_workflow")
    processing = win.findChild(QWidget, "processing_group")
    assert workflow.isAncestorOf(win.processing_history_label)
    assert win.homeWidget.findChildren(SectionCard) == []
    assert workflow.width() <= 760
    assert win.lbl_single_file.buddy() is win.le_input_file
    assert win.lbl_input_folder.buddy() is win.le_input_folder
    assert win.lbl_input_folder.text() == "Data Input Folder"
    assert win.lbl_currentProject.text() == "Current Project: None"

    assert win.btn_start.text() == "Start Processing"
    assert not win.btn_start.icon().isNull()
    run_panel = win.findChild(ActionRow, "run_panel")
    assert run_panel is not None
    assert run_panel.row_layout.indexOf(win.btn_start) >= 0
    assert run_panel.row_layout.indexOf(win.progress_bar) < 0
    assert abs(win.btn_start.geometry().center().x() - run_panel.rect().center().x()) <= 1
    assert win.findChild(QWidget, "processing_page") is win.processing_page
    assert win.workspace_stack.indexOf(win.processing_page) >= 0
    assert win.processing_page.isAncestorOf(win.progress_bar)
    assert win.findChild(QWidget, "processing_activity_header") is not None
    assert win.findChild(QWidget, "processing_status_card") is not None
    assert win.findChild(QWidget, "processing_files_card") is not None
    assert not isinstance(win.processing_status_card, SectionCard)
    assert not isinstance(win.processing_files_card, SectionCard)
    assert win.processing_page.findChildren(SectionCard) == []
    assert isinstance(win.processing_status_title_label, SubsectionHeaderLabel)
    assert isinstance(win.processing_files_title_label, SubsectionHeaderLabel)
    assert win.processing_instruction_panel.property("processingSection") is None
    assert win.processing_checklist_panel.property("processingSection") is None
    assert win.progress_bar.objectName() == "processing_progress_bar"
    assert win.findChild(QWidget, "processing_action_slot") is win.processing_action_slot
    assert win.processing_files_table.columnCount() == 2
    assert win.findChild(QWidget, "preprocessing_info_strip") is None
    assert not win.condition_editor_body.isVisible()
    assert not win.btn_add_row.isVisible()
    assert not win.trigger_maps_button.isVisible()
    assert not win.source_participants_button.isVisible()
    assert win.condition_editor_toggle.text() == "Edit conditions"
    qtbot.mouseClick(win.condition_editor_toggle, Qt.LeftButton)
    assert win.condition_editor_body.isVisibleTo(win)
    assert not win.processing_history_label.isVisibleTo(win)

    event_map_header = win.findChild(QWidget, "event_map_header")
    assert event_map_header is not None
    condition_header = next(
        label
        for label in event_map_header.findChildren(SubsectionHeaderLabel)
        if label.text() == "Condition"
    )
    trigger_header = next(
        label
        for label in event_map_header.findChildren(SubsectionHeaderLabel)
        if label.text() == "Trigger ID"
    )
    assert condition_header.font().bold()
    assert trigger_header.font().bold()
    assert win.findChild(QWidget, "log_group") is None
    assert win.homeWidget.findChild(QPushButton, "processing_view_log_button") is None
    assert not hasattr(win, "btn_detect")
    assert win.btn_select_input_file.text() == "Browse…"
    assert win.btn_select_input_folder.text() == "Browse…"
    assert win.btn_select_input_file.accessibleName() == "Choose EEG recording"
    assert win.btn_select_input_folder.accessibleName() == "Choose data input folder"
    assert win.btn_select_input_folder.width() == win.condition_editor_toggle.width()
    assert win.btn_add_row.text() == "+ Add Condition"
    event_map_group = win.findChild(QWidget, "event_map_group")
    assert event_map_group is not None
    assert processing.geometry().bottom() < event_map_group.geometry().top()
    assert any(label.text() == "Conditions" for label in event_map_group.findChildren(SubsectionHeaderLabel))
    event_rows = win._live_event_map_rows()
    assert event_rows
    assert event_rows[0].layout().contentsMargins().left() == 0
    event_remove_buttons = win.findChildren(QPushButton, "event_map_remove_button")
    assert event_remove_buttons
    assert all(button.text() == "x" for button in event_remove_buttons)
    assert all(button.property("variant") == "secondary" for button in event_remove_buttons)
    assert all(button.property("compact") is True for button in event_remove_buttons)
    assert all(button.property("iconButton") is True for button in event_remove_buttons)
    assert all(
        button.minimumWidth() == button.maximumWidth()
        for button in event_remove_buttons
    )
    assert all(
        button.minimumHeight() == button.maximumHeight()
        and button.minimumWidth() == button.minimumHeight()
        for button in event_remove_buttons
    )

    assert hasattr(win, "row_single_file")
    assert hasattr(win, "row_input_folder")
    assert win.row_input_folder.isVisible()
    assert not win.row_single_file.isVisible()

    assert win.workspace_stack.width() == win.stacked.width() - 2 * PAGE_MARGIN
    assert [action.text() for action in win.menuBar().actions()] == ["&File", "&View", "&Tools"]
    file_actions = _menu(win, "fileMenu").actions()
    assert [None if action.isSeparator() else action.text() for action in file_actions] == [
        "Import FPVS Studio Config…",
        "Review Studio Cohort…",
        "Share study results…",
        "Open Existing Project…",
        "Create Project Manually…",
        "Save Project Settings",
        None,
        "Settings",
        "Reset Project Processing Cache...",
        None,
        "Check for Updates",
        "About…",
        None,
        "Exit",
    ]
    assert file_actions[0] is win.actionImportFpvsConfigProject
    assert file_actions[4] is win.actionCreateNewProject
    assert file_actions[3] is win.actionOpenExistingProject
    assert file_actions[8] is win.actionResetProjectProcessingCache
    assert file_actions[-1] is win.exit_action
    assert [action.text() for action in _menu(win, "viewMenu").actions()] == ["Home", "Experiment Library…"]


@pytest.mark.parametrize("enable_beta", [False, True])
def test_home_analysis_entry_points_live_in_the_tools_menu(
    tmp_path: Path, qtbot, monkeypatch, enable_beta: bool,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch, enable_beta_tools=enable_beta)
    win.show_home_page()
    routes = ["btn_graphs"]
    if enable_beta:
        routes += ["btn_publication_maps", "btn_loreta_visualizer"]
    for role in ("btn_graphs", "btn_publication_maps", "btn_loreta_visualizer"):
        assert win.homeWidget.findChild(QPushButton, f"home_{role}") is None

    opened = []
    for role in routes:
        action = win.tool_actions[role]
        action.triggered.connect(lambda _checked, name=role: opened.append(name))
    monkeypatch.setattr(win, "_frequency_domain_outputs_ready_for_tool", lambda _name: False)
    warnings = []
    monkeypatch.setattr(win, "_acknowledge_beta_tool_warning", warnings.append)
    for role in routes:
        menu_name = "toolsMenu" if role == "btn_graphs" else "betaToolsMenu"
        _menu_action(win, menu_name, role).trigger()
    assert opened == routes
    assert warnings == routes[1:]
    assert win.workspace_stack.currentWidget() is win.homeWidget


@pytest.mark.parametrize(("count", "noun"), [(1, "folder"), (2, "folders")])
def test_home_group_folder_summary_uses_configured_count(qtbot, tmp_path, count, noun):
    from Main_App.gui.project_workflows import sync_input_folder_display

    field = QLineEdit()
    qtbot.addWidget(field)
    groups = {
        name: {"label": name, "raw_input_folder": str(tmp_path / name)}
        for name in ("Control", "Study")[:count]
    }
    project = SimpleNamespace(project_root=tmp_path, groups=groups, participants={})
    sync_input_folder_display(SimpleNamespace(currentProject=project, le_input_folder=field))
    assert field.text() == f"{count} group raw-data {noun} configured"
    assert len(field.toolTip().splitlines()) == count


def test_home_previews_folder_and_switches_scope_only_after_file_selection(tmp_path, qtbot, monkeypatch):
    win = _build_window(tmp_path, qtbot, monkeypatch)
    root = tmp_path / "ACR"
    raw = root / "raw"
    raw.mkdir(parents=True)
    first, second = raw / "P01.bdf", raw / "P02.bdf"
    first.touch()
    second.touch()
    project = Project.load(root)
    project.input_folder = raw
    project.options["mode"] = "single"
    project.event_map = {"Faces": 1}
    project.save()
    manifest_before = project.manifest_path.read_bytes()
    win.loadProject(project)
    win.show_home_page()

    assert win.lbl_currentProject.text() == "Current Project: ACR"
    assert win.file_mode.get() == "Batch"
    assert win.le_input_folder.text() == str(raw)
    assert win.home_workbook_path.text() == str(project.project_root / project.subfolders["excel"])
    qtbot.waitUntil(lambda: win.home_input_summary.title.text() == "2 files found")

    picks = iter([("", ""), (str(first), "")])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: next(picks))
    qtbot.mouseClick(win.processing_scope_button, Qt.LeftButton)
    assert win.file_mode.get() == "Batch"
    assert win.row_input_folder.isVisible()

    qtbot.mouseClick(win.processing_scope_button, Qt.LeftButton)
    assert win.file_mode.get() == "Single"
    assert win.row_single_file.isVisible()
    assert win.le_input_file.text() == str(first)
    assert not win.row_input_folder.isVisible()
    assert not win.project_draft_status.isVisible()

    qtbot.mouseClick(win.processing_scope_button, Qt.LeftButton)
    assert win.file_mode.get() == "Batch"
    assert win.row_input_folder.isVisible()
    qtbot.waitUntil(lambda: win.home_input_summary.title.text() == "2 files found")
    assert project.manifest_path.read_bytes() == manifest_before


def test_home_processing_history_long_content_fits_minimum_window(
    tmp_path: Path, qtbot, monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.resize(win.minimumSize())
    win.show_home_page()
    history = win.processing_history_label
    history.setText(
        "Last completed processing: 31 Dec 2099, 23:59 Chatham Standard Time "
        "- 1,234,567 participants"
    )
    history.show()
    qtbot.wait(20)

    assert win.size() == QSize(1200, 800)
    assert win.workspace_stack.currentWidget() is win.homeWidget
    assert history.isVisibleTo(win)
    assert history.wordWrap()
    assert history.height() >= history.heightForWidth(history.width())
    assert win.homeWidget.rect().contains(
        history.mapTo(win.homeWidget, history.rect().bottomRight())
    )
    assert win.homeWidget.parentWidget() is win.workspace_stack
    assert win.btn_start.isVisibleTo(win)
    start_bottom = win.btn_start.mapTo(win.homeWidget, win.btn_start.rect().bottomRight())
    assert win.homeWidget.rect().contains(start_bottom)


@pytest.mark.parametrize("debug_enabled", [False, True])
def test_main_window_has_toolbox_logo_and_no_toolbar_gap(tmp_path: Path, qtbot, monkeypatch, debug_enabled) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch, debug_enabled=debug_enabled)
    assert not win.findChildren(QToolBar)
    assert not win.windowIcon().isNull()
    actual_logo = win.windowIcon().pixmap(16, 16)
    expected_logo = QIcon(str(Path(__file__).resolve().parents[2] / "assets" / "ToolBox_Icon.ico")).pixmap(16, 16)
    assert not actual_logo.isNull()
    assert actual_logo.toImage() == expected_logo.toImage()

    win.stacked.setCurrentIndex(1)
    qtbot.waitUntil(lambda: win.stacked.y() == win.menuBar().geometry().bottom() + 1)
    assert win.menuBar().cornerWidget(Qt.TopRightCorner) is win.lbl_debug
    assert win.lbl_debug.isVisibleTo(win.menuBar()) is debug_enabled


def test_view_menu_returns_to_home(tmp_path: Path, qtbot, monkeypatch) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    assert win.menuBar().isVisibleTo(win)
    win.open_settings_window()
    assert win.workspace_stack.currentWidget() is win._settings_page
    assert win.menuBar().isVisibleTo(win)
    assert win.menuBar().isEnabled()
    assert [action.text() for action in win.menuBar().actions()] == ["&File", "&View", "&Tools"]

    _menu(win, "viewMenu").actions()[0].trigger()

    assert win.workspace_stack.currentWidget() is win.homeWidget
    assert win.menuBar().isVisibleTo(win)
    win.stacked.setCurrentWidget(win.landing_page)
    assert win.menuBar().isVisibleTo(win)


def _activate_menu_window(win, qtbot) -> None:
    win.raise_()
    win.activateWindow()
    qtbot.waitExposed(win)
    qtbot.waitUntil(win.isActiveWindow)


def _menu_action_image(bar, action):
    return bar.grab(bar.actionGeometry(action)).toImage()


@pytest.mark.parametrize("appearance_mode", ["Light", "Dark"])
def test_workspace_menu_keeps_native_style_and_readable_labels(
    tmp_path: Path, qtbot, monkeypatch, appearance_mode: str,
) -> None:
    app = QApplication.instance()
    previous_palette = app.palette()
    previous_font = app.font()
    previous_stylesheet = app.styleSheet()
    app.setStyleSheet("")
    previous_style = app.style().objectName()
    try:
        win = _build_window(tmp_path, qtbot, monkeypatch, appearance_mode=appearance_mode, enable_beta_tools=True)
        win.show_home_page()
        _activate_menu_window(win, qtbot)
        bar = win.menuBar()
        assert bar.isVisibleTo(win)
        assert bar.focusPolicy() == Qt.FocusPolicy.NoFocus
        QTest.mouseMove(win.stacked, QPoint(20, 20), delay=10)
        def assert_readable(menu, action):
            rect = menu.actionGeometry(action)
            # Sample the label, excluding menu borders, icon gutters, arrows and dividers.
            inset = 4 if menu is bar else menu.fontMetrics().horizontalAdvance("MMMM")
            rect.adjust(inset, 3, -4, -3)
            image = menu.grab(rect).toImage()
            levels = [
                image.pixelColor(x, y).lightness()
                for y in range(image.height())
                for x in range(image.width())
            ]
            assert max(levels) - min(levels) > 80, (appearance_mode, action.text())

        for action in bar.actions():
            assert_readable(bar, action)
        tools = _menu(win, "toolsMenu")
        beta = _menu(win, "betaToolsMenu")
        try:
            tools.popup(bar.mapToGlobal(bar.actionGeometry(tools.menuAction()).bottomLeft()))
            qtbot.waitUntil(tools.isVisible)
            assert_readable(tools, tools.actions()[0])
            beta.popup(tools.mapToGlobal(tools.actionGeometry(beta.menuAction()).topRight()))
            qtbot.waitUntil(beta.isVisible)
            assert_readable(beta, beta.actions()[0])
        finally:
            beta.hide()
            tools.hide()
    finally:
        app.setStyleSheet("")
        app.setStyle(previous_style)
        app.setPalette(previous_palette)
        app.setFont(previous_font)
        app.setStyleSheet(previous_stylesheet)


@pytest.mark.parametrize("appearance_mode", ["Light", "Dark"])
def test_workspace_menu_mouse_hover_changes_selection_without_opening_or_triggering(
    tmp_path: Path, qtbot, monkeypatch, appearance_mode: str,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch, appearance_mode=appearance_mode)
    _activate_menu_window(win, qtbot)
    bar = win.menuBar()
    actions = bar.actions()
    triggered = QSignalSpy(bar.triggered)
    opened = [QSignalSpy(action.menu().aboutToShow) for action in actions]

    def move_on_menu(position):
        # Qt's menu bar ignores mouse moves synthesized from touch. Deliver
        # an ordinary pointer event even on CI's offscreen platform.
        event = QMouseEvent(
            QEvent.Type.MouseMove, position, position, bar.mapToGlobal(position),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier, Qt.MouseEventSource.MouseEventNotSynthesized,
        )
        QApplication.sendEvent(bar, event)

    blank = QPoint(bar.width() - 12, bar.height() // 2)
    move_on_menu(blank)
    assert bar.activeAction() is None
    # Fusion paints its selection background only while a menu is open.
    # Windows native styles also paint the idle hover.
    platform_style = QApplication.instance().property("fpvsPlatformMenuStyleName")
    check_hover_pixels = str(platform_style).casefold().startswith("windows")
    idle_images = [_menu_action_image(bar, action) for action in actions] if check_hover_pixels else []
    for index, action in enumerate(actions):
        move_on_menu(bar.actionGeometry(action).center())
        assert bar.activeAction() is action
        if check_hover_pixels:
            assert _menu_action_image(bar, action) != idle_images[index]
            if index:
                assert _menu_action_image(bar, actions[index - 1]) == idle_images[index - 1]
        assert not any(candidate.menu().isVisible() for candidate in actions)

    assert triggered.count() == 0
    assert all(spy.count() == 0 for spy in opened)
    move_on_menu(blank)
    assert bar.activeAction() is None
    if check_hover_pixels:
        assert all(
            _menu_action_image(bar, action) == image
            for action, image in zip(actions, idle_images)
        )

    move_on_menu(bar.actionGeometry(actions[0]).center())
    assert bar.activeAction() is actions[0]
    QApplication.sendEvent(bar, QEvent(QEvent.Type.Leave))
    assert bar.activeAction() is None
    if check_hover_pixels:
        assert _menu_action_image(bar, actions[0]) == idle_images[0]


def test_workspace_menu_popup_and_keyboard_keep_native_navigation(
    tmp_path: Path, qtbot, monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    _activate_menu_window(win, qtbot)
    bar = win.menuBar()
    file_action, view_action, _tools_action = bar.actions()
    file_menu, view_menu = file_action.menu(), view_action.menu()
    triggered = QSignalSpy(bar.triggered)
    try:
        QTest.mouseMove(win.stacked, QPoint(20, 20), delay=10)
        idle_file = _menu_action_image(bar, file_action)
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.actionGeometry(file_action).center())
        qtbot.waitUntil(file_menu.isVisible)
        QTest.mouseMove(file_menu, file_menu.actionGeometry(file_menu.actions()[0]).center(), delay=10)
        assert bar.activeAction() is file_action
        assert _menu_action_image(bar, file_action) != idle_file

        qtbot.keyClick(file_menu, Qt.Key.Key_Right)
        qtbot.waitUntil(view_menu.isVisible)
        assert not file_menu.isVisible()
        assert bar.activeAction() is view_action
        qtbot.keyClick(view_menu, Qt.Key.Key_Escape)
        qtbot.waitUntil(lambda: not view_menu.isVisible())
        qtbot.keyClick(bar, Qt.Key.Key_Escape)

        qtbot.keyClick(win, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
        qtbot.waitUntil(file_menu.isVisible)
        assert bar.activeAction() is file_action
        qtbot.keyClick(file_menu, Qt.Key.Key_Escape)
        qtbot.waitUntil(lambda: not file_menu.isVisible())
        assert triggered.count() == 0
    finally:
        file_menu.hide()
        view_menu.hide()


@pytest.mark.parametrize("disable_bar", [False, True], ids=["disabled-action", "disabled-bar"])
def test_workspace_menu_disabled_controls_ignore_pointer_and_do_not_open(
    tmp_path: Path, qtbot, monkeypatch, disable_bar: bool,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    _activate_menu_window(win, qtbot)
    bar = win.menuBar()
    action = bar.actions()[0]
    triggered = QSignalSpy(bar.triggered)
    (bar if disable_bar else action).setEnabled(False)
    QTest.mouseMove(win.stacked, QPoint(20, 20), delay=10)
    idle_image = _menu_action_image(bar, action)
    QTest.mouseMove(bar, bar.actionGeometry(action).center(), delay=10)
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.actionGeometry(action).center())
    qtbot.wait(80)
    assert _menu_action_image(bar, action) == idle_image
    assert not action.menu().isVisible()
    assert triggered.count() == 0


def test_tool_navigation_guard_keeps_home_size(tmp_path: Path, qtbot, monkeypatch) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.show_home_page()
    initial_size = win.size()
    monkeypatch.setattr(win, "_frequency_domain_outputs_ready_for_tool", lambda _title: False)

    _menu_action(win, "toolsMenu", "btn_graphs").trigger()

    assert win.workspace_stack.currentWidget() is win.homeWidget
    assert win.size() == initial_size


def test_long_project_title_does_not_resize_home(tmp_path: Path, qtbot, monkeypatch) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.show_home_page()
    win.resize(win.minimumSize())
    name = "Long project name " * 30
    win._set_project_title(name)

    assert win.size() == QSize(1200, 800)
    assert win.windowTitle() == f"{name} — FPVS Toolbox v{main_window_module.FPVS_TOOLBOX_VERSION}"


@pytest.mark.parametrize(("width", "height"), [(1200, 800), (1340, 940)])
def test_workspace_navigation_keeps_window_size(tmp_path: Path, qtbot, monkeypatch, width, height) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.resize(width, height)
    size = QSize(width, height)
    win.show_home_page()
    assert win.size() == size
    settings = _menu_action(win, "fileMenu", "btn_settings")
    home = _menu_action(win, "viewMenu", "btn_home")

    settings.trigger()
    assert win.workspace_stack.currentWidget() is win._settings_page
    assert win.minimumSize() == QSize(1200, 800)
    assert win.size() == size
    home.trigger()
    assert win.size() == size
    assert win.workspace_stack.width() == win.width() - 2 * PAGE_MARGIN

    tool = win._ensure_sensitivity_analysis_page()
    win._show_workspace_page(tool)
    assert win.workspace_stack.currentWidget() is tool
    assert win.size() == size
    home.trigger()
    assert win.size() == size
    win.stacked.setCurrentWidget(win.landing_page)
    assert win.minimumSize() == QSize(1200, 800)
    assert win.size() == size


def test_processing_log_opens_in_focused_modal(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.stacked.setCurrentIndex(1)
    win.text_log.append("Visible processing detail")

    _menu_action(win, "toolsMenu", "actionProcessingLog").trigger()
    qtbot.waitUntil(win.processing_log_dialog.isVisible)

    assert win.processing_log_dialog.isModal()
    assert "Visible processing detail" in win.text_log.toPlainText()
    clear_button = win.processing_log_dialog.findChild(
        QPushButton,
        "processing_log_clear",
    )
    assert clear_button is not None
    qtbot.mouseClick(clear_button, Qt.LeftButton)
    assert win.text_log.toPlainText() == ""
    win.processing_log_dialog.reject()


def test_processing_activity_page_locks_navigation_and_reuses_start_button(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    run_panel = win.findChild(ActionRow, "run_panel")
    assert run_panel is not None
    assert run_panel.row_layout.indexOf(win.btn_start) >= 0

    win._busy_start()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.processing_page
    assert win.processing_action_layout.indexOf(win.btn_start) >= 0
    assert win.btn_start.icon().isNull()
    assert run_panel.row_layout.indexOf(win.btn_start) < 0
    assert win.processing_spinner.isVisible()
    assert win.size() == QSize(1200, 800)
    assert not win.menuBar().isEnabled()
    _menu_action(win, "viewMenu", "btn_home").trigger()
    assert win.workspace_stack.currentWidget() is win.processing_page

    view_log = win.processing_page.findChild(QPushButton, "processing_view_log_button")
    assert view_log.isVisibleTo(win) and view_log.isEnabled()
    qtbot.mouseClick(view_log, Qt.LeftButton)
    qtbot.waitUntil(win.processing_log_dialog.isVisible)
    win.processing_log_dialog.reject()
    assert win.workspace_stack.currentWidget() is win.processing_page
    assert not win.menuBar().isEnabled()

    win._busy_stop()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
    assert run_panel.row_layout.indexOf(win.btn_start) >= 0
    assert win.processing_action_layout.indexOf(win.btn_start) < 0
    assert not win.btn_start.icon().isNull()
    assert abs(win.btn_start.geometry().center().x() - run_panel.rect().center().x()) <= 1
    assert win.size() == QSize(1200, 800)
    assert win.menuBar().isEnabled()


def test_snr_plot_entries_share_action_availability(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        main_window_module.MainWindow,
        "open_plot_generator",
        lambda _window: opened.append("SNR Plots"),
    )
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)
    action = _menu_action(win, "toolsMenu", "btn_graphs")
    assert action.actionGroup() is win.shell_actions
    assert any(action is shared for shared in win.shell_actions.default_tools)
    assert _menu_action(win, "fileMenu", "btn_settings") is win.shell_actions.settings

    triggered = QSignalSpy(action.triggered)
    action.trigger()
    assert triggered.count() == len(opened) == 1
    action.setEnabled(False)
    action.trigger()
    assert triggered.count() == len(opened) == 1
    action.setEnabled(True)

    disabled_action = _menu_action(win, "toolsMenu", "btn_free_harmonic_clustering")
    disabled_action.setEnabled(False)
    win._busy_start()
    assert not action.isEnabled()
    assert not win.shell_actions.home.isEnabled()
    assert not _menu_action(win, "viewMenu", "actionExperimentLibrary").isEnabled()
    action.trigger()
    assert triggered.count() == len(opened) == 1

    win._busy_stop()
    assert action.isEnabled()
    assert win.shell_actions.home.isEnabled()
    assert not disabled_action.isEnabled()
    action.trigger()
    assert triggered.count() == len(opened) == 2


def test_reset_project_processing_cache_action_requires_confirmation_and_is_scoped(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    project_root = tmp_path / "project"
    project_root.mkdir()
    win.currentProject = SimpleNamespace(project_root=project_root, event_map={}, options={})

    preprocessed_cache = project_root / ".fpvs_cache" / "preprocessed"
    preprocessed_cache.mkdir(parents=True)
    (preprocessed_cache / "P01_raw.fif").write_bytes(b"cached-raw")
    preflight_cache = preflight_qc_cache_directory(project_root)
    preflight_cache.mkdir(parents=True)
    (preflight_cache / "P01.json").write_bytes(b"cached-qc")
    ledger = project_root / ".fpvs_processing" / "processing_ledger.json"
    ledger.write_bytes(b'{"entries":{"P01":{}}}')

    preserved = {
        project_root / "project.json": b'{"name":"Valence"}',
        project_root / ".fpvs_processing" / "processing_runs.jsonl": b"run-history\n",
        project_root / "1 - Excel Data Files" / "P01_Results.xlsx": b"output",
    }
    for path, payload in preserved.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    action = win.actionResetProjectProcessingCache
    assert action.text() == "Reset Project Processing Cache..."
    assert action.objectName() == "actionResetProjectProcessingCache"

    monkeypatch.setattr(
        main_window_module.project_workflows.QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.No,
    )
    action.trigger()
    assert preprocessed_cache.exists()
    assert preflight_cache.exists()
    assert ledger.exists()

    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        main_window_module.project_workflows.QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )
    monkeypatch.setattr(
        main_window_module.project_workflows.QMessageBox,
        "information",
        lambda _parent, title, message, *_args, **_kwargs: messages.append(
            (title, message)
        ),
    )
    action.trigger()

    qtbot.waitUntil(
        lambda: getattr(win, "_project_processing_cache_thread", None) is None,
        timeout=5_000,
    )

    assert not preprocessed_cache.exists()
    assert not preflight_cache.exists()
    assert not ledger.exists()
    assert {path: path.read_bytes() for path in preserved} == preserved
    assert messages
    assert messages[-1][0] == "Processing Cache Reset"
    assert "preprocess from raw BDF data" in messages[-1][1]


def test_reset_project_processing_cache_refuses_without_project_or_while_busy(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    warnings: list[tuple[str, str]] = []
    questions: list[str] = []
    monkeypatch.setattr(
        main_window_module.project_workflows.QMessageBox,
        "warning",
        lambda _parent, title, message, *_args, **_kwargs: warnings.append(
            (title, message)
        ),
    )
    monkeypatch.setattr(
        main_window_module.project_workflows.QMessageBox,
        "question",
        lambda _parent, title, *_args, **_kwargs: questions.append(title),
    )

    win.actionResetProjectProcessingCache.trigger()

    project_root = tmp_path / "project"
    project_root.mkdir()
    win.currentProject = SimpleNamespace(project_root=project_root, event_map={}, options={})
    win._settings_harmonic_recalc_thread = SimpleNamespace(isRunning=lambda: True)
    win.actionResetProjectProcessingCache.trigger()
    win._settings_harmonic_recalc_thread = None
    win._settings_full_fft_grid_qc_thread = SimpleNamespace(
        isRunning=lambda: True
    )
    win.actionResetProjectProcessingCache.trigger()

    assert [title for title, _message in warnings] == [
        "No Project",
        "Processing Is Active",
        "Processing Is Active",
    ]
    assert not questions


def test_reset_project_processing_cache_disables_start_until_worker_finishes(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    project_root = tmp_path / "project"
    project_root.mkdir()
    win.currentProject = SimpleNamespace(project_root=project_root, event_map={}, options={})
    event_edits = win.event_rows[0].findChildren(QLineEdit)
    event_edits[0].setText("Condition")
    event_edits[1].setText("1")
    win._update_start_enabled()
    assert win.btn_start.isEnabled()

    worker_started = threading.Event()
    release_worker = threading.Event()

    def slow_cache_reset(_project_root: Path) -> ProjectProcessingCacheUsage:
        worker_started.set()
        release_worker.wait(timeout=5.0)
        return ProjectProcessingCacheUsage()

    monkeypatch.setattr(
        "Main_App.workers.project_processing_cache_worker.clear_project_processing_cache",
        slow_cache_reset,
    )
    monkeypatch.setattr(
        main_window_module.project_workflows.QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )
    monkeypatch.setattr(
        main_window_module.project_workflows.QMessageBox,
        "information",
        lambda *_args, **_kwargs: None,
    )

    win.actionResetProjectProcessingCache.trigger()
    try:
        qtbot.waitUntil(worker_started.is_set, timeout=5_000)
        assert not win.btn_start.isEnabled()
        assert win._start_guard.is_active()
        assert not win.workspace_stack.isEnabled()
    finally:
        release_worker.set()

    qtbot.waitUntil(
        lambda: getattr(win, "_project_processing_cache_thread", None) is None,
        timeout=5_000,
    )
    assert not win._start_guard.is_active()
    assert win.btn_start.isEnabled()
    assert win.workspace_stack.isEnabled()


def test_processing_activity_tracks_completed_files(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    first_file = tmp_path / "P001.bdf"
    second_file = tmp_path / "P002.bdf"
    win.processing_status_title_label.setText("Stale status title")
    win.processing_files_title_label.setText("Stale review title")

    win._prepare_processing_activity([first_file, second_file])

    assert win.processing_message_label.text() == (
        "Toolbox may respond slowly while recordings are processing."
    )
    assert win.processing_status_title_label.text() == "Run Progress"
    assert win.processing_progress_heading_label.isHidden()
    assert win.processing_files_title_label.text() == "File Completion"
    assert win.processing_files_table.rowCount() == 2
    assert win.processing_files_table.item(0, 0).text() == "Queued"
    assert win.processing_files_table.item(0, 1).text() == "P001.bdf"
    assert win.processing_summary_label.text() == "0 of 2 files complete (0%)"

    win._on_processing_file_status({"status": "ok", "file": str(first_file)})

    assert win.processing_files_table.item(0, 0).text() == "Complete"
    assert win.processing_summary_label.text() == "1 of 2 files complete"
    assert win.processing_current_file_label.text() == "Latest file: Completed P001.bdf"

    win._update_processing_progress(50)
    assert win.processing_summary_label.text() == "1 of 2 files complete (50%)"


def test_processing_activity_switches_to_post_processing_phase_progress(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    files = [tmp_path / "P001.bdf", tmp_path / "P002.bdf"]
    win._prepare_processing_activity(files)
    win.progress_bar.setValue(100)

    main_window_module.shell_status.prepare_post_processing_activity(win)

    assert win.processing_files_card.isHidden()
    assert not win.processing_status_card.isHidden()
    assert win.processing_progress_heading_label.text() == "Post-Processing Progress"
    assert win.progress_bar.value() == 0

    main_window_module.shell_status.update_post_processing_progress(
        win,
        completed_units=1,
        total_units=3,
        phase_index=2,
    )
    qtbot.waitUntil(lambda: win.progress_bar.value() == 33, timeout=1_000)
    assert win.processing_step_label.text() == "Post-processing phase 2 of 3"

    win._prepare_processing_activity(files)
    assert not win.processing_files_card.isHidden()
    assert win.processing_progress_heading_label.text() == "Overall Progress"
    assert (win.progress_bar.minimum(), win.progress_bar.maximum()) == (0, 100)
    assert win.progress_bar.value() == 0


def test_processing_activity_tracks_excluded_files(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    first_file = tmp_path / "P001.bdf"
    second_file = tmp_path / "P002.bdf"

    win._prepare_processing_activity([first_file, second_file])
    win._on_processing_file_status({"status": "ok", "file": str(first_file)})
    win._on_processing_file_status(
        {
            "status": "excluded",
            "file": str(second_file),
            "reason": "recording_not_started",
        }
    )

    assert win.processing_files_table.item(1, 0).text() == "Excluded"
    assert win.processing_summary_label.text() == "1 of 2 files complete; 1 excluded"
    assert win.processing_current_file_label.text() == "Latest file: Excluded P002.bdf"


def test_workspace_settings_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.stacked.setCurrentIndex(1)
    win.resize(win.minimumSize())
    qtbot.wait(20)

    _menu_action(win, "fileMenu", "btn_settings").trigger()
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), EmbeddedSettingsPage)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_settings_page"
    assert win._settings_page.parent() is win.workspace_stack
    assert win.size() == QSize(1200, 800)

    win._settings_page.reject()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget


def test_workspace_stats_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch, enable_beta_tools=True)
    monkeypatch.setattr(win, "_acknowledge_beta_tool_warning", lambda _key: None)
    project_root = tmp_path / "project"
    project_root.mkdir()
    win.currentProject = SimpleNamespace(
        project_root=project_root,
        input_folder=project_root,
        subfolders={},
        event_map={},
        options={},
    )
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    _open_beta_tool(win, "btn_data")
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), StatsWindow)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_stats_page"
    assert win._stats_page.parent() is win.workspace_stack
    assert win._stats_page.project_dir == str(project_root)
    assert win._stats_page.minimumWidth() <= win.workspace_stack.width()
    assert win._stats_page.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored

    _menu_action(win, "viewMenu", "btn_home").trigger()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget


def test_workspace_free_harmonic_clustering_is_available_without_beta_tools(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    monkeypatch.setattr(
        win,
        "_acknowledge_beta_tool_warning",
        lambda key: pytest.fail(f"Stable tool requested beta warning: {key}"),
    )
    project_root = tmp_path / "project"
    project_root.mkdir()
    win.currentProject = SimpleNamespace(project_root=project_root, event_map={}, options={})
    page = QWidget(win.workspace_stack)
    page.setObjectName("embedded_free_harmonic_clustering_page")
    win.workspace_stack.addWidget(page)
    monkeypatch.setattr(
        win,
        "_frequency_domain_outputs_ready_for_tool",
        lambda title: title == "Free Harmonic Clustering Analysis",
    )
    monkeypatch.setattr(win, "_ensure_free_harmonic_clustering_page", lambda: page)

    _menu_action(win, "toolsMenu", "btn_free_harmonic_clustering").trigger()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is page


def test_workspace_sensitivity_analysis_embeds_without_project_data(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    generated = iter((101, 202))
    monkeypatch.setattr(
        "Tools.Sensitivity_Analysis.gui._new_lmm_seed",
        lambda: next(generated),
    )
    win = _build_window(tmp_path, qtbot, monkeypatch, enable_beta_tools=True)
    monkeypatch.setattr(win, "_acknowledge_beta_tool_warning", lambda _key: None)
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    _open_beta_tool(win, "btn_sensitivity_analysis")
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), SensitivityAnalysisWindow)
    assert (
        win.workspace_stack.currentWidget().objectName()
        == "embedded_sensitivity_analysis_page"
    )
    assert win._sensitivity_analysis_page.parent() is win.workspace_stack
    first_page = win._sensitivity_analysis_page
    assert first_page._lmm_config().seed == 101
    first_page.analysis_combo.setCurrentIndex(first_page.LMM_SIMULATION)
    first_page.lmm_sample_size_spin.setValue(24)
    first_page.lmm_conditions_spin.setValue(4)
    first_page.lmm_rois_spin.setValue(3)

    _menu_action(win, "viewMenu", "btn_home").trigger()
    _open_beta_tool(win, "btn_sensitivity_analysis")

    assert win._sensitivity_analysis_page is first_page
    assert first_page._lmm_config().seed == 202
    assert first_page.lmm_sample_size_spin.value() == 0
    assert first_page.lmm_conditions_spin.value() == 0
    assert first_page.lmm_rois_spin.value() == 0


def test_workspace_snr_plot_generator_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    monkeypatch.setattr(
        win,
        "_acknowledge_beta_tool_warning",
        lambda key: pytest.fail(f"Stable tool requested beta warning: {key}"),
    )
    project_root = tmp_path / "project"
    excel_dir = project_root / "1 - Excel Data Files"
    snr_dir = project_root / "2 - SNR Plots"
    excel_dir.mkdir(parents=True)
    snr_dir.mkdir()
    (excel_dir / "CondA").mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "name": "PlotProject",
                "subfolders": {
                    "excel": "1 - Excel Data Files",
                    "snr": "2 - SNR Plots",
                },
            }
        ),
        encoding="utf-8",
    )
    win.currentProject = SimpleNamespace(
        project_root=project_root,
        input_folder=project_root,
        subfolders={"excel": "1 - Excel Data Files", "snr": "2 - SNR Plots"},
        event_map={},
        options={},
    )
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    _menu_action(win, "toolsMenu", "btn_graphs").trigger()
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), PlotGeneratorWindow)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_plot_generator_page"
    assert win._plot_generator_page.parent() is win.workspace_stack
    assert win._plot_generator_page.folder_edit.text() == str(excel_dir)
    assert win._plot_generator_page.out_edit.text() == str(snr_dir)

    _menu_action(win, "viewMenu", "btn_home").trigger()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget


def test_workspace_scalp_maps_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch, enable_beta_tools=True)
    warning_keys: list[str] = []
    monkeypatch.setattr(
        win,
        "_acknowledge_beta_tool_warning",
        warning_keys.append,
    )
    project_root = tmp_path / "project"
    excel_dir = project_root / "1 - Excel Data Files"
    excel_dir.mkdir(parents=True)
    (excel_dir / "CondA").mkdir()
    (excel_dir / "CondA" / "P01_CondA_Results.xlsx").touch()
    (excel_dir / "CondB").mkdir()
    (excel_dir / "CondB" / "P01_CondB_Results.xlsx").touch()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "name": "Scalp Maps layout smoke",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "participants": {"P01": {}},
            }
        ),
        encoding="utf-8",
    )
    win.currentProject = SimpleNamespace(
        project_root=project_root,
        input_folder=project_root,
        subfolders={"excel": "1 - Excel Data Files"},
        event_map={},
        options={},
    )
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    _open_beta_tool(win, "btn_publication_maps")
    qtbot.wait(20)

    assert warning_keys == ["btn_publication_maps"]
    assert isinstance(win.workspace_stack.currentWidget(), PublicationMapsWindow)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_publication_maps_page"
    assert win._publication_maps_page.parent() is win.workspace_stack
    assert win._publication_maps_page.input_root_edit.text() == str(excel_dir)
    assert win._publication_maps_page.output_root_edit.text() == str(
        project_root / "4 - Scalp Maps"
    )
    page = win._publication_maps_page
    assert page.conditions_list.minimumHeight() == 140
    assert page.conditions_list.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert page.conditions_list.height() >= 140
    conditions_card = page.findChild(SectionCard, "publication_maps_conditions")
    settings_section = page.findChild(QWidget, "publication_maps_settings")
    output_card = page.findChild(SectionCard, "publication_maps_output")
    figure_layout_card = page.findChild(
        SectionCard,
        "publication_maps_figure_layout",
    )
    run_section = page.findChild(QWidget, "publication_maps_run")
    assert conditions_card is not None
    assert settings_section is not None
    assert not isinstance(settings_section, SectionCard)
    assert output_card is not None
    assert figure_layout_card is not None
    assert run_section is not None
    assert not isinstance(run_section, SectionCard)
    assert conditions_card.geometry().top() == run_section.geometry().top()
    assert run_section.isAncestorOf(settings_section)
    assert [
        page.workflow_tabs.tabText(index)
        for index in range(page.workflow_tabs.count())
    ] == ["Generate Maps", "Advanced Settings"]
    assert page.workflow_tabs.currentIndex() == 0
    assert page.workflow_tabs.widget(0).isAncestorOf(conditions_card)
    assert page.workflow_tabs.widget(0).isAncestorOf(run_section)
    assert page.workflow_tabs.widget(0).isAncestorOf(page.metric_bca_check)
    assert page.workflow_tabs.widget(0).isAncestorOf(settings_section)
    assert page.workflow_tabs.widget(1).isAncestorOf(output_card)
    assert page.workflow_tabs.widget(1).isAncestorOf(figure_layout_card)
    assert page.workflow_tabs.widget(1).isAncestorOf(page.output_root_row)
    assert page.workflow_tabs.widget(1).isAncestorOf(
        page.view_generation_log_btn
    )
    assert not page.workflow_tabs.widget(0).isAncestorOf(page.log_box)
    assert not page.workflow_tabs.widget(1).isAncestorOf(page.log_box)
    assert page.generation_log_dialog.isAncestorOf(page.log_box)
    assert page.run_btn.text() == "Generate Scalp Maps"
    assert page.output_format_label.text() == "PNG and PDF (600 DPI)"
    assert page.status_label.isVisible()
    assert "Paired-condition figure ready for CondA and CondB" in (
        page.status_label.text()
    )
    for widget in (
        page.conditions_list,
        page.metric_bca_check,
        page.status_label,
        page.run_btn,
        page.cancel_btn,
        page.progress,
    ):
        assert widget.visibleRegion().contains(widget.rect())
    assert page.run_btn.height() > 0
    assert len(
        {
            page.run_btn.height(),
            page.cancel_btn.height(),
            page.progress.height(),
        }
    ) == 1
    generation_text = " ".join(
        label.text()
        for label in page.workflow_tabs.widget(0).findChildren(QLabel)
    )
    assert "Advanced Settings" not in generation_text
    assert not hasattr(page, "base_freq_value")
    assert not hasattr(page, "bca_limit_value")
    assert page.metric_bca_check.isChecked()
    assert page.metric_snr_check.isChecked()
    assert page.metric_z_check.isChecked()
    assert not page.fixed_bca_range_check.isChecked()
    assert not page.bca_vmin_spin.isEnabled()
    assert not page.bca_vmax_spin.isEnabled()
    page.fixed_bca_range_check.setChecked(True)
    assert page.bca_vmin_spin.value() == pytest.approx(0.0)
    assert page.bca_vmax_spin.value() == pytest.approx(0.4)
    assert page.bca_vmin_spin.minimumWidth() >= 104
    assert page.bca_vmax_spin.minimumWidth() >= 104
    assert page.bca_vmin_spin.isEnabled()
    assert page.bca_vmax_spin.isEnabled()
    assert page.fixed_snr_range_check.isChecked()
    assert page.snr_vmin_spin.value() == pytest.approx(1.0)
    assert page.snr_vmax_spin.value() == pytest.approx(1.5)
    assert page.snr_vmin_spin.minimumWidth() >= 104
    assert page.snr_vmax_spin.minimumWidth() >= 104
    assert page.fixed_snr_range_check.isEnabled()
    assert page.snr_vmin_spin.isEnabled()
    assert page.snr_vmax_spin.isEnabled()
    assert page.z_threshold_spin.value() == pytest.approx(1.64)
    assert page.z_threshold_spin.isEnabled()
    assert page.run_btn.isEnabled()
    page.metric_bca_check.setChecked(False)
    assert page.run_btn.isEnabled()
    page.metric_snr_check.setChecked(False)
    assert page.run_btn.isEnabled()
    page.metric_z_check.setChecked(False)
    assert not page.run_btn.isEnabled()
    assert page.status_label.text() == "Select at least one map type."
    page.metric_bca_check.setChecked(True)
    page.metric_snr_check.setChecked(True)
    page.metric_z_check.setChecked(True)
    assert "Paired-condition figure ready for CondA and CondB" in (
        page.status_label.text()
    )
    assert page.fixed_snr_range_check.isEnabled()
    assert page.snr_vmin_spin.isEnabled()
    assert page.snr_vmax_spin.isEnabled()
    page.metric_snr_check.setChecked(False)
    assert not page.fixed_snr_range_check.isEnabled()
    page.metric_snr_check.setChecked(True)
    page.workflow_tabs.setCurrentIndex(1)
    qtbot.wait(20)
    assert not settings_section.isVisible()
    assert page.input_group.geometry().bottom() < output_card.geometry().top()
    assert output_card.geometry().bottom() < figure_layout_card.geometry().top()
    assert abs(output_card.geometry().left() - figure_layout_card.geometry().left()) <= 1
    assert (
        abs(output_card.geometry().right() - figure_layout_card.geometry().right())
        <= 1
    )
    advanced_text = " ".join(
        label.text()
        for label in page.workflow_tabs.widget(1).findChildren(QLabel)
    )
    assert "exactly two canonical groups" not in advanced_text.casefold()
    assert not hasattr(page, "group_comparison_hint")
    assert "exactly two canonical groups" not in (
        page.group_comparison_check.toolTip().casefold()
    )
    assert page.paired_figures_check.isChecked()
    page.paired_figures_check.setChecked(False)
    assert "Paired-condition figure ready" not in page.status_label.text()
    page.paired_figures_check.setChecked(True)
    assert "Paired-condition figure ready for CondA and CondB" in (
        page.status_label.text()
    )
    assert page.paired_conditions_widget.isVisible()
    assert page.paired_condition_a_combo.currentText() == "CondA"
    assert page.paired_condition_b_combo.currentText() == "CondB"
    page.paired_condition_a_combo.setCurrentText("CondB")
    assert page.paired_condition_a_combo.currentText() == "CondB"
    assert page.paired_condition_b_combo.currentText() == "CondA"
    assert "Paired-condition figure ready for CondB and CondA" in (
        page.status_label.text()
    )
    assert page.paired_condition_a_combo.isEnabled()
    assert page.paired_condition_b_combo.isEnabled()
    for widget in (
        page.output_root_edit,
        page.open_output_btn,
        page.view_generation_log_btn,
        page.input_root_edit,
        page.paired_condition_a_combo,
        page.paired_condition_b_combo,
    ):
        assert widget.visibleRegion().contains(widget.rect())
    page._set_busy_state(True)
    qtbot.wait(20)

    assert not page.input_root_row.isEnabled()
    assert not page.refresh_btn.isEnabled()
    assert not page.conditions_list.isEnabled()
    assert not page.metric_bca_check.isEnabled()
    assert not page.metric_snr_check.isEnabled()
    assert not page.metric_z_check.isEnabled()
    assert not page.color_low_btn.isEnabled()
    assert not page.color_high_btn.isEnabled()
    assert not page.fixed_bca_range_check.isEnabled()
    assert not page.bca_vmin_spin.isEnabled()
    assert not page.bca_vmax_spin.isEnabled()
    assert not page.fixed_snr_range_check.isEnabled()
    assert not page.snr_vmin_spin.isEnabled()
    assert not page.snr_vmax_spin.isEnabled()
    assert not page.z_threshold_spin.isEnabled()
    assert not page.output_root_row.isEnabled()
    assert page.view_generation_log_btn.isEnabled()
    assert not page.paired_figures_check.isEnabled()
    assert not page.paired_condition_a_combo.isEnabled()
    assert not page.paired_condition_b_combo.isEnabled()
    assert not page.run_btn.isEnabled()
    assert page.cancel_btn.isEnabled()
    assert not win.menuBar().isEnabled()

    page._set_busy_state(False)
    qtbot.wait(20)

    assert page.input_root_row.isEnabled()
    assert page.refresh_btn.isEnabled()
    assert page.conditions_list.isEnabled()
    assert page.metric_bca_check.isEnabled()
    assert page.metric_snr_check.isEnabled()
    assert page.metric_z_check.isEnabled()
    assert page.color_low_btn.isEnabled()
    assert page.color_high_btn.isEnabled()
    assert page.fixed_bca_range_check.isEnabled()
    assert page.bca_vmin_spin.isEnabled()
    assert page.bca_vmax_spin.isEnabled()
    assert page.fixed_snr_range_check.isEnabled()
    assert page.snr_vmin_spin.isEnabled()
    assert page.snr_vmax_spin.isEnabled()
    assert page.z_threshold_spin.isEnabled()
    assert page.output_root_row.isEnabled()
    assert page.view_generation_log_btn.isEnabled()
    assert page.paired_condition_a_combo.isEnabled()
    assert page.paired_condition_b_combo.isEnabled()
    assert not page.cancel_btn.isEnabled()
    assert win.menuBar().isEnabled()

    opened: list[bool] = []

    def fake_confirm(parent, title, message):
        assert parent is page
        assert title == "Finished"
        assert message == "Plots have been successfully generated. View plots?"
        return True

    monkeypatch.setattr("Tools.Publication_Maps.gui.confirm", fake_confirm)
    monkeypatch.setattr(page, "_open_output_folder", lambda: opened.append(True))
    page._pending_outcome = PublicationMapsWorkerOutcome.success(
        (
            SimpleNamespace(
                group_label=None,
                diagnostics=(),
                figure_paths=(Path("map.png"), Path("map.pdf")),
            ),
        )
    )
    page._cleanup_worker()

    assert opened == [True]
    assert page._last_generated_figure_count == 0


    _menu_action(win, "viewMenu", "btn_home").trigger()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget


def test_beta_warning_is_generic_and_shown_once_per_tool(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    warning_calls: list[tuple[str, str]] = []
    events: list[str] = []

    def fake_warning(parent, title, message, *args):
        warning_calls.append((title, message))
        events.append("warning")
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(main_window_module.QMessageBox, "warning", fake_warning)

    def opener(_self) -> None:
        events.append("opened")

    monkeypatch.setattr(main_window_module.MainWindow, "open_loreta_visualizer", opener)
    monkeypatch.setattr(main_window_module.MainWindow, "open_sequence_figure", opener)
    win = _build_window(tmp_path, qtbot, monkeypatch, enable_beta_tools=True)
    win.stacked.setCurrentIndex(1)

    beta_menu = _menu(win, "betaToolsMenu")
    beta_actions = {action.objectName(): action for action in beta_menu.actions()}
    beta_actions["btn_loreta_visualizer"].trigger()
    _open_beta_tool(win, "btn_loreta_visualizer")
    beta_actions["btn_sequence_figure"].trigger()

    assert warning_calls == [
        (
            "Beta Tool",
            "This tool is currently in beta. Features are subject to change.",
        ),
        (
            "Beta Tool",
            "This tool is currently in beta. Features are subject to change.",
        ),
    ]
    assert events == ["warning", "opened", "opened", "warning", "opened"]


def test_shared_post_processing_remedy_launches_for_active_project(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    project_root = tmp_path / "project"
    project_root.mkdir()
    win.currentProject = SimpleNamespace(project_root=project_root, event_map={}, options={})
    prompts: list[tuple[str, str]] = []
    launches: list[object] = []
    monkeypatch.setattr(
        main_window_module,
        "show_post_processing_required",
        lambda _parent, *, tool_name, reason: (
            prompts.append((tool_name, reason)) or True
        ),
    )
    monkeypatch.setattr(
        main_window_module.processing_workflows,
        "resume_post_processing",
        launches.append,
    )

    started = win.request_post_processing_rebuild(
        "SNR Plots",
        "The active workbook cohort changed.",
        str(project_root),
    )

    assert started is True
    assert prompts == [("SNR Plots", "The active workbook cohort changed.")]
    assert launches == [win]


def test_shared_post_processing_remedy_rejects_different_project(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    active_root = tmp_path / "active-project"
    other_root = tmp_path / "other-project"
    active_root.mkdir()
    other_root.mkdir()
    win.currentProject = SimpleNamespace(project_root=active_root, event_map={}, options={})
    warnings: list[tuple[str, str]] = []
    prompts: list[object] = []
    launches: list[object] = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    monkeypatch.setattr(
        main_window_module,
        "show_post_processing_required",
        lambda *_args, **_kwargs: prompts.append(object()) or True,
    )
    monkeypatch.setattr(
        main_window_module.processing_workflows,
        "resume_post_processing",
        launches.append,
    )

    started = win.request_post_processing_rebuild(
        "SNR Plots",
        "The active workbook cohort changed.",
        str(other_root),
    )

    assert started is False
    assert warnings == [
        (
            "Different Project Selected",
            "SNR Plots reported stale outputs for a different project. "
            "Open that project before running post-processing.",
        )
    ]
    assert prompts == []
    assert launches == []


def test_fhc_post_processing_remedy_refreshes_current_page(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    import Main_App.processing.full_fft_provenance as full_fft_provenance

    win = _build_window(tmp_path, qtbot, monkeypatch)
    project_root = tmp_path / "project"
    project_root.mkdir()
    win.currentProject = SimpleNamespace(project_root=project_root, event_map={}, options={})
    refreshes: list[dict[str, object]] = []
    win._free_harmonic_clustering_page = SimpleNamespace(
        project_root=project_root,
        refresh_project_context=lambda **kwargs: refreshes.append(kwargs),
    )
    frequency_snapshot = object()
    monkeypatch.setattr(
        win,
        "_free_harmonic_frequency_snapshot",
        lambda: frequency_snapshot,
    )
    monkeypatch.setattr(
        main_window_module,
        "show_post_processing_required",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_full_fft_provenance",
        lambda root: SimpleNamespace(project_root=root),
    )
    callbacks: list[object] = []

    def resume_post_processing(_host, *, on_finished=None) -> None:
        callbacks.append(on_finished)

    monkeypatch.setattr(
        main_window_module.processing_workflows,
        "resume_post_processing",
        resume_post_processing,
    )

    started = win.request_post_processing_rebuild(
        "Free Harmonic Clustering Analysis",
        "The saved analysis files are out of date.",
        str(project_root),
    )

    assert started is True
    assert len(callbacks) == 1
    callback = callbacks[0]
    assert callable(callback)
    callback()
    assert refreshes == [
        {
            "project_root": project_root.resolve(),
            "frequency_snapshot": frequency_snapshot,
            "frequency_error": None,
        }
    ]


def test_snr_page_routes_post_processing_request_to_main_window(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    requests: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        win,
        "request_post_processing_rebuild",
        lambda *args: requests.append(args) or True,
    )
    page = win._ensure_plot_generator_page()

    page.post_processing_required.emit(
        "SNR Plots",
        "The active workbook cohort changed.",
        str(tmp_path / "project"),
    )

    assert requests == [
        (
            "SNR Plots",
            "The active workbook cohort changed.",
            str(tmp_path / "project"),
        )
    ]


def test_fhc_page_routes_post_processing_request_to_main_window(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    from Tools.Free_Harmonic_Clustering import gui as free_harmonic_gui

    class FakeFreeHarmonicPage(QWidget):
        post_processing_required = Signal(str, str, str)
        protocol_settings_required = Signal()

        def __init__(
            self,
            project_root,
            _frequency_snapshot=None,
            *,
            parent=None,
            **_kwargs,
        ):
            super().__init__(parent)
            self.project_root = Path(project_root).resolve()

        def shutdown(self) -> None:
            return None

        def refresh_project_context(self, **_kwargs) -> bool:
            return False

    win = _build_window(tmp_path, qtbot, monkeypatch)
    project_root = tmp_path / "project"
    project_root.mkdir()
    win.currentProject = SimpleNamespace(project_root=project_root, event_map={}, options={})
    requests: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        free_harmonic_gui,
        "FreeHarmonicClusteringPage",
        FakeFreeHarmonicPage,
    )
    monkeypatch.setattr(
        win,
        "request_post_processing_rebuild",
        lambda *args: requests.append(args) or True,
    )

    page = win._ensure_free_harmonic_clustering_page()
    page.post_processing_required.emit(
        "Free Harmonic Clustering Analysis",
        "The saved analysis files are out of date.",
        str(project_root),
    )

    assert requests == [
        (
            "Free Harmonic Clustering Analysis",
            "The saved analysis files are out of date.",
            str(project_root),
        )
    ]


@pytest.mark.parametrize(
    ("role", "opener_name"),
    [
        ("btn_publication_maps", "open_publication_maps"),
        ("btn_data", "open_stats_analyzer"),
        ("btn_sensitivity_analysis", "open_sensitivity_analysis"),
        ("btn_loreta_visualizer", "open_loreta_visualizer"),
        ("btn_sequence_figure", "open_sequence_figure"),
        ("btn_individual_detectability", "open_individual_detectability"),
    ],
)
def test_beta_registry_routes_every_entry_through_shared_gate(
    tmp_path: Path,
    qtbot,
    monkeypatch,
    role: str,
    opener_name: str,
) -> None:
    routed: list[tuple[str, str]] = []

    def route_beta(self, tool_key: str, opener) -> None:
        routed.append((tool_key, opener.__name__))

    monkeypatch.setattr(main_window_module.MainWindow, "_open_beta_tool", route_beta)
    win = _build_window(tmp_path, qtbot, monkeypatch, enable_beta_tools=True)

    _open_beta_tool(win, role)

    assert routed == [(role, opener_name)]


def test_workspace_individual_detectability_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch, enable_beta_tools=True)
    monkeypatch.setattr(win, "_acknowledge_beta_tool_warning", lambda _key: None)
    project_root = tmp_path / "project"
    excel_dir = project_root / "1 - Excel Data Files"
    excel_dir.mkdir(parents=True)
    (excel_dir / "CondA").mkdir()
    win.currentProject = SimpleNamespace(
        project_root=project_root,
        input_folder=project_root,
        subfolders={"excel": "1 - Excel Data Files"},
        event_map={},
        options={},
    )
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)
    workspace_width_before = win.workspace_stack.width()

    _open_beta_tool(win, "btn_individual_detectability")
    qtbot.wait(20)

    assert win.workspace_stack.width() == workspace_width_before
    assert isinstance(win.workspace_stack.currentWidget(), IndividualDetectabilityWindow)
    assert (
        win.workspace_stack.currentWidget().objectName()
        == "embedded_individual_detectability_page"
    )
    assert win._individual_detectability_page.parent() is win.workspace_stack
    assert win._individual_detectability_page.minimumWidth() <= win.workspace_stack.width()
    assert win._individual_detectability_page._project_root == project_root
    assert win._individual_detectability_page.input_root_edit.text() == str(excel_dir)

    _menu_action(win, "viewMenu", "btn_home").trigger()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
