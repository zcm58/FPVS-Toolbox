import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from Main_App.gui import main_window as main_window_module
from Main_App.gui.components import ActionRow
from Main_App.gui.components import SectionCard
from Main_App.gui.components import SubsectionHeaderLabel
from Main_App.gui.style_tokens import EVENT_REMOVE_BUTTON_SIZE
from Main_App.gui.settings_panel import EmbeddedSettingsPage
import Main_App.gui.update_manager as update_manager
from Tools.Average_Preprocessing.New_PySide6.main_window import AdvancedAveragingWindow
from Tools.Image_Resizer.pyside_resizer import FPVSImageResizerQt
from Tools.Individual_Detectability.main_window import IndividualDetectabilityWindow
from Tools.Plot_Generator.plot_generator import PlotGeneratorWindow
from Tools.Publication_Maps.gui import PublicationMapsWindow
from Tools.Ratio_Calculator.gui import RatioCalculatorWindow
from Tools.Stats import StatsWindow


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
    assert win.minimumWidth() == 1280
    assert win.minimumHeight() == 900
    assert win.size().width() >= 1280
    assert win.size().height() >= 900
    assert win.windowTitle() == f"FPVS Toolbox v{main_window_module.FPVS_TOOLBOX_VERSION}"
    assert not win.findChildren(QStatusBar)
    assert win.landing_page is win.stacked.currentWidget()
    assert win.landing_card.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert win.landing_card.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert win.landing_card.maximumWidth() >= 10_000
    assert not hasattr(win, "landing_brain_animation")

    labels = {label.text() for label in win.landing_page.findChildren(QLabel)}
    assert "FPVS Toolbox" not in labels
    assert "Welcome to FPVS Toolbox!" in labels
    assert "Create a new FPVS project or open an existing one." in labels
    title = next(
        label
        for label in win.landing_page.findChildren(QLabel)
        if label.text() == "Welcome to FPVS Toolbox!"
    )
    assert not title.wordWrap()
    assert title.minimumHeight() >= 84
    assert title.sizeHint().height() <= title.minimumHeight()

    assert win.btn_create_project.text() == "New Project"
    assert win.btn_open_project.text() == "Open Project"
    assert win.btn_create_project.width() >= 260
    assert win.btn_create_project.height() >= 66
    assert win.actionImportFpvsConfigProject.text() == "Import FPVS Studio Config..."
    assert win.menuBar().isHidden()
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

    assert not win.menuBar().isHidden()
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
    assert run_panel.row_layout.indexOf(win.progress_bar) < 0
    assert win.findChild(QWidget, "processing_page") is win.processing_page
    assert win.workspace_stack.indexOf(win.processing_page) >= 0
    assert win.processing_page.isAncestorOf(win.progress_bar)
    assert win.findChild(QWidget, "processing_activity_header") is not None
    assert win.findChild(QWidget, "processing_status_card") is not None
    assert win.findChild(QWidget, "processing_files_card") is not None
    assert win.progress_bar.objectName() == "processing_progress_bar"
    assert win.findChild(QWidget, "processing_action_slot") is win.processing_action_slot
    assert win.processing_files_table.columnCount() == 2
    assert win.findChild(QWidget, "preprocessing_info_strip") is None
    event_map_header = win.findChild(QWidget, "event_map_header")
    assert event_map_header is not None
    assert event_map_header.isAncestorOf(win.btn_add_row)
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
    assert event_map_header.layout().indexOf(win.btn_add_row) < event_map_header.layout().indexOf(trigger_header)
    assert win.findChild(QWidget, "log_group") is not None
    assert not hasattr(win, "btn_detect")
    assert win.btn_select_input_file.text() == "Select EEG File..."
    assert win.btn_select_input_folder.text() == "Select Data Folder..."
    assert win.btn_add_row.text() == "+ Add Condition"
    event_map_group = win.findChild(QWidget, "event_map_group")
    assert event_map_group is not None
    assert not event_map_group.header.isVisible()
    event_map_titles = [
        label
        for label in event_map_group.findChildren(QLabel)
        if label.text() == "Event Map"
    ]
    assert not event_map_titles
    event_rows = win._live_event_map_rows()
    assert event_rows
    assert event_rows[0].layout().contentsMargins().left() == 0
    event_remove_buttons = win.findChildren(QPushButton, "event_map_remove_button")
    assert event_remove_buttons
    assert all(button.text() == "x" for button in event_remove_buttons)
    assert all(button.property("variant") == "secondary" for button in event_remove_buttons)
    assert all(button.property("compact") is True for button in event_remove_buttons)
    assert all(button.property("iconButton") is True for button in event_remove_buttons)
    assert all(button.width() == EVENT_REMOVE_BUTTON_SIZE for button in event_remove_buttons)
    assert all(button.height() == EVENT_REMOVE_BUTTON_SIZE for button in event_remove_buttons)

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
    assert win.sidebar.isEnabled()
    assert win.sidebar.graphicsEffect() is None
    assert win.sidebar.property("processingLocked") is False
    sidebar_section_titles = {
        label.text()
        for label in win.sidebar.findChildren(QLabel)
        if label.objectName() == "SidebarSectionLabel"
    }
    assert sidebar_section_titles == {"Workspace Tools", "Utilities"}
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
    assert win.sidebar.isEnabled()
    assert win.sidebar.graphicsEffect() is None
    assert win.sidebar.property("processingLocked") is True
    assert all(
        widget.property("processingLocked") is True
        for widget in win.sidebar.findChildren(QWidget)
        if widget.objectName() == "SidebarButton"
    )
    assert all(
        label.property("processingLocked") is None
        for label in win.sidebar.findChildren(QLabel)
        if label.objectName() == "SidebarSectionLabel"
    )
    assert not win.menuBar().isEnabled()

    win._busy_stop()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
    assert run_panel.row_layout.indexOf(win.btn_start) >= 0
    assert win.processing_action_layout.indexOf(win.btn_start) < 0
    assert win.sidebar.isEnabled()
    assert win.sidebar.graphicsEffect() is None
    assert win.sidebar.property("processingLocked") is False
    assert win.menuBar().isEnabled()


def test_processing_activity_tracks_completed_files(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    first_file = tmp_path / "P001.bdf"
    second_file = tmp_path / "P002.bdf"

    win._prepare_processing_activity([first_file, second_file])

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


def test_sidebar_settings_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    qtbot.mouseClick(_sidebar_button(win, "btn_settings"), Qt.LeftButton)
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), EmbeddedSettingsPage)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_settings_page"
    assert win._settings_page.parent() is win.workspace_stack
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_settings"]

    win._settings_page.reject()
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_home"]


def test_sidebar_ratio_calculator_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    project_root = tmp_path / "project"
    project_root.mkdir()
    win.currentProject = SimpleNamespace(
        project_root=project_root,
        input_folder=project_root,
        subfolders={},
    )
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    qtbot.mouseClick(_sidebar_button(win, "btn_ratio"), Qt.LeftButton)
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), RatioCalculatorWindow)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_ratio_calculator_page"
    assert win._ratio_calculator_page._project_root == project_root
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_ratio"]

    qtbot.mouseClick(_sidebar_button(win, "btn_home"), Qt.LeftButton)
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_home"]


def test_sidebar_stats_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    project_root = tmp_path / "project"
    project_root.mkdir()
    win.currentProject = SimpleNamespace(
        project_root=project_root,
        input_folder=project_root,
        subfolders={},
    )
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    qtbot.mouseClick(_sidebar_button(win, "btn_data"), Qt.LeftButton)
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), StatsWindow)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_stats_page"
    assert win._stats_page.parent() is win.workspace_stack
    assert win._stats_page.project_dir == str(project_root)
    assert win._stats_page.minimumWidth() <= win.workspace_stack.width()
    assert win._stats_page.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_data"]

    qtbot.mouseClick(_sidebar_button(win, "btn_home"), Qt.LeftButton)
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_home"]


def test_sidebar_snr_plot_generator_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
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
    )
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    qtbot.mouseClick(_sidebar_button(win, "btn_graphs"), Qt.LeftButton)
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), PlotGeneratorWindow)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_plot_generator_page"
    assert win._plot_generator_page.parent() is win.workspace_stack
    assert win._plot_generator_page.folder_edit.text() == str(excel_dir)
    assert win._plot_generator_page.out_edit.text() == str(snr_dir)
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_graphs"]

    qtbot.mouseClick(_sidebar_button(win, "btn_home"), Qt.LeftButton)
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_home"]


def test_sidebar_scalp_maps_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    project_root = tmp_path / "project"
    excel_dir = project_root / "1 - Excel Data Files"
    excel_dir.mkdir(parents=True)
    (excel_dir / "CondA").mkdir()
    (excel_dir / "CondA" / "P01_CondA_Results.xlsx").touch()
    (excel_dir / "CondB").mkdir()
    (excel_dir / "CondB" / "P01_CondB_Results.xlsx").touch()
    win.currentProject = SimpleNamespace(
        project_root=project_root,
        input_folder=project_root,
        subfolders={"excel": "1 - Excel Data Files"},
    )
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)

    qtbot.mouseClick(_sidebar_button(win, "btn_publication_maps"), Qt.LeftButton)
    qtbot.wait(20)

    assert isinstance(win.workspace_stack.currentWidget(), PublicationMapsWindow)
    assert win.workspace_stack.currentWidget().objectName() == "embedded_publication_maps_page"
    assert win._publication_maps_page.parent() is win.workspace_stack
    assert win._publication_maps_page.input_root_edit.text() == str(excel_dir)
    assert win._publication_maps_page.output_root_edit.text() == str(
        project_root / "4 - Scalp Maps"
    )
    page = win._publication_maps_page
    assert page.conditions_list.minimumHeight() == 140
    assert page.conditions_list.maximumHeight() == 220
    conditions_card = page.findChild(SectionCard, "publication_maps_conditions")
    settings_card = page.findChild(SectionCard, "publication_maps_settings")
    output_card = page.findChild(SectionCard, "publication_maps_output")
    run_card = page.findChild(SectionCard, "publication_maps_run")
    assert conditions_card is not None
    assert settings_card is not None
    assert output_card is not None
    assert run_card is not None
    assert conditions_card.geometry().top() == settings_card.geometry().top()
    assert output_card.geometry().top() == run_card.geometry().top()
    assert not settings_card.header.isVisible()
    assert not hasattr(page, "base_freq_value")
    assert not hasattr(page, "bca_limit_value")
    assert page.metric_bca_check.isChecked()
    assert page.metric_snr_check.isChecked()
    assert page.fixed_bca_range_check.isChecked()
    assert page.bca_vmin_spin.value() == pytest.approx(0.0)
    assert page.bca_vmax_spin.value() == pytest.approx(0.4)
    assert page.bca_vmin_spin.minimumWidth() >= 132
    assert page.bca_vmax_spin.minimumWidth() >= 132
    assert page.bca_vmin_spin.isEnabled()
    assert page.bca_vmax_spin.isEnabled()
    assert page.fixed_snr_range_check.isChecked()
    assert page.snr_vmin_spin.value() == pytest.approx(1.0)
    assert page.snr_vmax_spin.value() == pytest.approx(1.5)
    assert page.snr_vmin_spin.minimumWidth() >= 132
    assert page.snr_vmax_spin.minimumWidth() >= 132
    assert page.fixed_snr_range_check.isEnabled()
    assert page.snr_vmin_spin.isEnabled()
    assert page.snr_vmax_spin.isEnabled()
    assert page.run_btn.isEnabled()
    page.metric_bca_check.setChecked(False)
    assert page.run_btn.isEnabled()
    page.metric_snr_check.setChecked(False)
    assert not page.run_btn.isEnabled()
    page.metric_bca_check.setChecked(True)
    page.metric_snr_check.setChecked(True)
    assert page.fixed_snr_range_check.isEnabled()
    assert page.snr_vmin_spin.isEnabled()
    assert page.snr_vmax_spin.isEnabled()
    page.metric_snr_check.setChecked(False)
    assert not page.fixed_snr_range_check.isEnabled()
    page.metric_snr_check.setChecked(True)
    assert page.paired_condition_a_combo.currentText() == "CondA"
    assert page.paired_condition_b_combo.currentText() == "CondB"
    assert not page.paired_conditions_widget.isVisible()
    page.paired_figures_check.setChecked(True)
    assert page.paired_conditions_widget.isVisible()
    assert page.paired_condition_a_combo.isEnabled()
    assert page.paired_condition_b_combo.isEnabled()
    assert not page.status_label.isVisible()
    page._set_busy_state(True)
    qtbot.wait(20)

    assert not page.input_root_row.isEnabled()
    assert not page.refresh_btn.isEnabled()
    assert not page.conditions_list.isEnabled()
    assert not page.metric_bca_check.isEnabled()
    assert not page.metric_snr_check.isEnabled()
    assert not page.color_low_btn.isEnabled()
    assert not page.color_high_btn.isEnabled()
    assert not page.fixed_bca_range_check.isEnabled()
    assert not page.bca_vmin_spin.isEnabled()
    assert not page.bca_vmax_spin.isEnabled()
    assert not page.fixed_snr_range_check.isEnabled()
    assert not page.snr_vmin_spin.isEnabled()
    assert not page.snr_vmax_spin.isEnabled()
    assert not page.output_root_row.isEnabled()
    assert not page.export_png_check.isEnabled()
    assert not page.export_svg_check.isEnabled()
    assert not page.paired_figures_check.isEnabled()
    assert not page.paired_condition_a_combo.isEnabled()
    assert not page.paired_condition_b_combo.isEnabled()
    assert not page.run_btn.isEnabled()
    assert page.cancel_btn.isEnabled()
    assert not win.menuBar().isEnabled()
    assert win.sidebar.property("processingLocked") is True

    page._set_busy_state(False)
    qtbot.wait(20)

    assert page.input_root_row.isEnabled()
    assert page.refresh_btn.isEnabled()
    assert page.conditions_list.isEnabled()
    assert page.metric_bca_check.isEnabled()
    assert page.metric_snr_check.isEnabled()
    assert page.color_low_btn.isEnabled()
    assert page.color_high_btn.isEnabled()
    assert page.fixed_bca_range_check.isEnabled()
    assert page.bca_vmin_spin.isEnabled()
    assert page.bca_vmax_spin.isEnabled()
    assert page.fixed_snr_range_check.isEnabled()
    assert page.snr_vmin_spin.isEnabled()
    assert page.snr_vmax_spin.isEnabled()
    assert page.output_root_row.isEnabled()
    assert page.export_png_check.isEnabled()
    assert page.export_svg_check.isEnabled()
    assert page.paired_condition_a_combo.isEnabled()
    assert page.paired_condition_b_combo.isEnabled()
    assert not page.cancel_btn.isEnabled()
    assert win.menuBar().isEnabled()
    assert win.sidebar.property("processingLocked") is False

    opened: list[bool] = []

    def fake_confirm(parent, title, message):
        assert parent is page
        assert title == "Finished"
        assert message == "Plots have been successfully generated. View plots?"
        return True

    monkeypatch.setattr("Tools.Publication_Maps.gui.confirm", fake_confirm)
    monkeypatch.setattr(page, "_open_output_folder", lambda: opened.append(True))
    page._last_generated_figure_count = 2
    page._cleanup_worker()

    assert opened == [True]
    assert page._last_generated_figure_count == 0

    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_publication_maps"]

    qtbot.mouseClick(_sidebar_button(win, "btn_home"), Qt.LeftButton)
    qtbot.wait(20)

    assert win.workspace_stack.currentWidget() is win.homeWidget
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_home"]


def test_sidebar_individual_detectability_embeds_in_main_workspace(
    tmp_path: Path,
    qtbot,
    monkeypatch,
) -> None:
    win = _build_window(tmp_path, qtbot, monkeypatch)
    project_root = tmp_path / "project"
    excel_dir = project_root / "1 - Excel Data Files"
    excel_dir.mkdir(parents=True)
    (excel_dir / "CondA").mkdir()
    win.currentProject = SimpleNamespace(
        project_root=project_root,
        input_folder=project_root,
        subfolders={"excel": "1 - Excel Data Files"},
    )
    win.stacked.setCurrentIndex(1)
    qtbot.wait(20)
    sidebar_width_before = win.sidebar.width()
    workspace_width_before = win.workspace_stack.width()

    qtbot.mouseClick(_sidebar_button(win, "btn_individual_detectability"), Qt.LeftButton)
    qtbot.wait(20)

    assert win.sidebar.width() == sidebar_width_before
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
    selected_roles = [
        widget.property("role")
        for widget in win.sidebar.findChildren(QWidget)
        if widget.property("selected") is True
    ]
    assert selected_roles == ["btn_individual_detectability"]

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
