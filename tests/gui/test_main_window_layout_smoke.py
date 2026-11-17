import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import QSize, Signal, Qt
from PySide6.QtGui import QAction, QColor, QIcon
from PySide6.QtWidgets import (
    QApplication,
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
from Main_App.gui.style_tokens import HEADER_BG, PAGE_MARGIN
from Main_App.processing.preflight_qc_cache import preflight_qc_cache_directory
from Main_App.processing.project_processing_cache import ProjectProcessingCacheUsage
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
    if beta_enabled:
        assert tools_actions[2].isSeparator()
        beta_menu = _menu(win, "betaToolsMenu")
        assert tools_actions[3].menu() is beta_menu
        assert [action.objectName() for action in beta_menu.actions()] == BETA_TOOL_ROLES
        assert [action.text() for action in beta_menu.actions()] == BETA_TOOL_ACCESSIBLE_NAMES
    else:
        assert len(tools_actions) == 2
        assert win.menuBar().findChild(QMenu, "betaToolsMenu") is None


def test_welcome_prioritizes_studio_import_and_fits_minimum_window(tmp_path: Path, qtbot, monkeypatch) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)

    assert win.stacked.currentWidget() is win.landing_page
    assert win.minimumSize() == QSize(900, 520)
    assert win.size() == QSize(960, 520)
    assert win.windowTitle() == f"FPVS Toolbox v{main_window_module.FPVS_TOOLBOX_VERSION}"
    assert not win.findChildren(QStatusBar)
    assert win.menuBar().isVisibleTo(win)

    title = win.landing_page.findChild(QLabel, "landing_title")
    instructions = win.landing_page.findChild(QLabel, "landing_subtitle")
    assert title.text() == "FPVS Toolbox"
    assert ".fpvsconfig" in instructions.text()
    assert win.btn_import_project.text() == "Import FPVS Studio Config…"
    assert win.btn_open_project.text() == "Open Existing Project…"
    assert win.btn_create_project.text() == "Create Manually…"
    assert win.btn_import_project.property("variant") == "primary"
    assert win.btn_open_project.property("variant") == "secondary"
    assert win.btn_create_project.property("variant") == "tertiary"
    assert win.actionImportFpvsConfigProject is not win.actionCreateNewProject

    win.resize(win.minimumSize())
    QApplication.processEvents()
    for widget in (title, instructions, win.btn_import_project, win.btn_open_project, win.btn_create_project):
        assert widget.isVisibleTo(win)
        assert win.rect().contains(widget.mapTo(win, widget.rect().topLeft()))
        assert win.rect().contains(widget.mapTo(win, widget.rect().bottomRight()))


@pytest.mark.parametrize(("button_name", "workflow_name"), [
    ("btn_create_project", "_new_project"),
    ("btn_import_project", "_new_project_from_fpvs_config"),
])
def test_cancelled_project_creation_returns_to_welcome(
    tmp_path: Path,
    qtbot,
    monkeypatch,
    button_name,
    workflow_name,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    calls = []
    monkeypatch.setattr(
        main_window_module.project_workflows,
        workflow_name,
        lambda *_args: calls.append(workflow_name),
    )

    qtbot.mouseClick(getattr(win, button_name), Qt.LeftButton)

    assert calls == [workflow_name]
    assert win.currentProject is None
    assert win.stacked.currentWidget() is win.landing_page
    assert win.menuBar().isVisibleTo(win)


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
    assert win.processing_history_label.isVisibleTo(win)
    assert win.processing_history_label.wordWrap()
    workflow = win.findChild(QWidget, "home_workflow")
    processing = win.findChild(QWidget, "processing_group")
    assert workflow.isAncestorOf(win.processing_history_label)
    assert win.homeWidget.findChildren(SectionCard) == []
    assert workflow.width() <= 760
    assert win.lbl_single_file.buddy() is win.le_input_file
    assert win.lbl_input_folder.buddy() is win.le_input_folder

    assert win.btn_start.text() == "Start Processing"
    run_panel = win.findChild(ActionRow, "run_panel")
    assert run_panel is not None
    assert run_panel.row_layout.indexOf(win.btn_view_log) >= 0
    assert run_panel.row_layout.indexOf(win.btn_start) >= 0
    assert run_panel.row_layout.indexOf(win.progress_bar) < 0
    assert win.processing_history_label.geometry().top() > run_panel.geometry().bottom()
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
    assert win.processing_history_label.isVisibleTo(win)

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
    assert win.btn_view_log.text() == "View Log"
    assert win.btn_view_log.accessibleName() == "View processing log"
    assert not hasattr(win, "btn_detect")
    assert win.btn_select_input_file.text() == "Select EEG File..."
    assert win.btn_select_input_folder.text() == "Select Data Folder..."
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

    assert win.workspace_stack.width() == win.stacked.width() - 2 * PAGE_MARGIN
    assert [action.text() for action in win.menuBar().actions()] == ["&File", "&View", "&Tools", "&Help"]
    assert [action.text() for action in _menu(win, "helpMenu").actions()] == ["Documentation"]
    file_actions = _menu(win, "fileMenu").actions()
    assert [None if action.isSeparator() else action.text() for action in file_actions] == [
        "Import FPVS Studio Config…",
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
    assert file_actions[2] is win.actionCreateNewProject
    assert file_actions[1] is win.actionOpenExistingProject
    assert file_actions[6] is win.actionResetProjectProcessingCache
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


def test_home_processing_history_long_content_fits_minimum_window(
    tmp_path: Path, qtbot, monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.resize(900, 520)
    win.show_home_page()
    history = win.processing_history_label
    history.setText(
        "Last completed processing: 31 Dec 2099, 23:59 Chatham Standard Time "
        "- 1,234,567 participants"
    )
    qtbot.wait(20)

    assert win.size() == QSize(900, 520)
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
    expected_logo = QIcon(str(Path(__file__).resolve().parents[2] / "assets" / "experiment_library" / "wave.svg")).pixmap(16, 16)
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
    assert [action.text() for action in win.menuBar().actions()] == ["&File", "&View", "&Tools", "&Help"]

    _menu(win, "viewMenu").actions()[0].trigger()

    assert win.workspace_stack.currentWidget() is win.homeWidget
    assert win.menuBar().isVisibleTo(win)
    win.stacked.setCurrentWidget(win.landing_page)
    assert win.menuBar().isVisibleTo(win)


def test_workspace_menu_paints_slate_and_readable_labels(
    tmp_path: Path, qtbot, monkeypatch,
) -> None:
    app = QApplication.instance()
    previous_palette = app.palette()
    previous_font = app.font()
    previous_stylesheet = app.styleSheet()
    app.setStyleSheet("")
    previous_style = app.style().objectName()
    try:
        win = _build_window(tmp_path, qtbot, monkeypatch, appearance_mode="Light")
        win.show_home_page()
        qtbot.waitUntil(win.menuBar().isVisible)
        bar = win.menuBar()
        menu_image = bar.grab().toImage()
        slate = QColor(HEADER_BG)
        assert menu_image.pixelColor(menu_image.width() - 20, 5) == slate
        for action in bar.actions():
            image = bar.grab(bar.actionGeometry(action)).toImage()
            assert any(
                image.pixelColor(x, y).lightness() > 150
                for y in range(image.height())
                for x in range(image.width())
            ), action.text()
    finally:
        app.setStyleSheet("")
        app.setStyle(previous_style)
        app.setPalette(previous_palette)
        app.setFont(previous_font)
        app.setStyleSheet(previous_stylesheet)


def test_tool_navigation_guard_keeps_home_compact(tmp_path: Path, qtbot, monkeypatch) -> None:
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
    win.resize(900, 520)
    name = "Long project name " * 30
    win._set_project_title(name)

    assert win.size() == QSize(900, 520)
    assert win.windowTitle() == f"{name} — FPVS Toolbox v{main_window_module.FPVS_TOOLBOX_VERSION}"


def test_workspace_expands_and_restores_only_automatic_resizes(tmp_path: Path, qtbot, monkeypatch) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    monkeypatch.setattr(win, "_frequency_domain_outputs_ready_for_tool", lambda _name: True)
    win.show_home_page()
    win.resize(930, 550)
    settings = _menu_action(win, "fileMenu", "actionSettings")
    home = _menu_action(win, "viewMenu", "btn_home")
    snr = _menu_action(win, "toolsMenu", "btn_graphs")

    settings.trigger()
    assert win.minimumSize() == QSize(900, 520)
    assert win.size() == QSize(930, 550)

    snr.trigger()
    assert win.minimumSize() == QSize(960, 600)
    assert win.size() == QSize(960, 600)
    win.open_stats_analyzer()
    assert win.minimumSize() == QSize(1280, 900)
    assert win.size() == QSize(1280, 900)
    snr.trigger()
    assert win.size() == QSize(960, 600)
    settings.trigger()
    assert win.minimumSize() == QSize(900, 520)
    assert win.size() == QSize(930, 550)
    home.trigger()
    assert win.size() == QSize(930, 550)
    assert win.workspace_stack.width() == win.width() - 2 * PAGE_MARGIN

    snr.trigger()
    win.resize(1340, 940)
    home.trigger()
    assert win.minimumSize() == QSize(900, 520)
    assert win.size() == QSize(1340, 940)


def test_processing_log_opens_in_focused_modal(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.stacked.setCurrentIndex(1)
    win.text_log.append("Visible processing detail")

    qtbot.mouseClick(win.btn_view_log, Qt.LeftButton)
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
    assert run_panel.row_layout.indexOf(win.btn_start) < 0
    assert win.processing_spinner.isVisible()
    assert win.minimumSize() == QSize(1280, 900)
    assert not win.menuBar().isEnabled()
    _menu_action(win, "viewMenu", "btn_home").trigger()
    assert win.workspace_stack.currentWidget() is win.processing_page

    win._busy_stop()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
    assert run_panel.row_layout.indexOf(win.btn_start) >= 0
    assert win.processing_action_layout.indexOf(win.btn_start) < 0
    assert win.size() == QSize(960, 520)
    assert win.menuBar().isEnabled()


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
        total_units=5,
        phase_index=2,
    )
    qtbot.waitUntil(lambda: win.progress_bar.value() == 20, timeout=1_000)
    assert win.processing_step_label.text() == "Post-processing phase 2 of 5"

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
    win.resize(900, 520)
    qtbot.wait(20)

    _menu_action(win, "fileMenu", "actionSettings").trigger()
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), EmbeddedSettingsPage)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_settings_page"
    assert win._settings_page.parent() is win.workspace_stack
    assert win.size() == QSize(900, 520)

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

    assert win.workspace_stack.width() > workspace_width_before
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
