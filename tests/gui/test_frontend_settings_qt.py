"""Approved visible checks for Settings drafts, validation and bounded layout."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QWidget,
)

from Main_App.settings.settings_manager import SettingsManager
from Main_App.gui.settings_panel import SettingsDialog
from Main_App.gui.theme import apply_fpvs_theme, set_appearance_mode
from Main_App.gui.typography import APP_FONT_FAMILY
from Main_App.projects import Project
from tests.gui.test_gui_preproc_dialog import _prep_project


@pytest.fixture
def panel(tmp_path, qtbot, monkeypatch):
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    project = _prep_project(tmp_path)
    manager = SettingsManager(str(tmp_path / "settings.ini"))
    widget = SettingsDialog(manager, project=project)
    qtbot.addWidget(widget)
    apply_fpvs_theme(QApplication.instance())
    widget.resize(1020, 790)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _capture(widget, name):
    folder = os.environ.get("FPVS_UX_SCREENSHOT_DIR")
    if folder:
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        assert widget.grab().save(str(path / f"{name}.png"))


def test_settings_draft_tracks_values_but_not_roi_navigation(panel):
    assert not panel.has_unsaved_changes()
    edit = panel.preproc_edits[0]
    original = edit.text()
    edit.setText("40")
    assert panel.has_unsaved_changes()
    edit.setText(original)
    assert not panel.has_unsaved_changes()
    panel.roi_editor.select_roi(1)
    assert not panel.has_unsaved_changes()
    panel.roi_editor.add_entry("Draft ROI")
    assert panel.has_unsaved_changes()
    panel.roi_editor.remove_active_entry()
    assert not panel.has_unsaved_changes()
    panel.roi_editor.map_widget.electrode_buttons["Cz"].click()
    assert panel.has_unsaved_changes()


def test_settings_categories_support_keyboard_navigation_without_saving(panel, qtbot):
    navigation = panel.settings_navigation
    assert not panel.tabs.tabBar().isVisible()
    assert navigation.accessibleName() == "Settings categories"
    assert navigation.currentItem().text() == "Processing"
    saved_low_pass = Project.load(panel.project.project_root).preprocessing["low_pass"]
    panel.preproc_edits[0].setText("40")

    navigation.setFocus()
    qtbot.waitUntil(navigation.hasFocus)
    qtbot.keyClick(navigation, Qt.Key.Key_Down)

    assert panel.tabs.currentIndex() == panel._protocol_tab_index
    assert panel.settings_page_title.text() == "Protocol"
    assert panel.has_unsaved_changes()
    assert Project.load(panel.project.project_root).preprocessing["low_pass"] == saved_low_pass


def test_settings_category_rail_groups_navigation_and_aligns_the_headings(panel):
    sidebar = panel.findChild(QFrame, "settings_sidebar")
    assert sidebar is not None and sidebar.isVisibleTo(panel)
    page_header = panel.findChild(QFrame, "settings_page_header")
    assert page_header is not None and page_header.isVisibleTo(panel)
    sidebar_bounds = QRect(sidebar.mapTo(panel, QPoint()), sidebar.size())
    header_bounds = QRect(page_header.mapTo(panel, QPoint()), page_header.size())
    assert header_bounds.top() == sidebar_bounds.top()
    assert header_bounds.left() == sidebar_bounds.right() + 1
    assert header_bounds.bottom() < panel.tabs.mapTo(panel, QPoint()).y()
    navigation = panel.settings_navigation
    title = panel.settings_page_title
    assert title.parentWidget() is page_header
    assert navigation.parentWidget() is sidebar
    assert sidebar.rect().contains(navigation.geometry())
    assert navigation.sizeHintForColumn(0) <= navigation.viewport().width()
    assert title.objectName() == "settings_page_title"
    assert sidebar.width() < panel.tabs.width()
    assert sidebar.mapTo(panel, sidebar.rect().topRight()).x() < title.mapTo(panel, QPoint()).x()

    application_index = next(
        index for index in range(panel.tabs.count()) if panel.tabs.tabText(index) == "Application"
    )
    panel.tabs.setCurrentIndex(application_index)
    assert navigation.currentItem().text() == title.text() == "Application"
    heading = sidebar.findChild(QLabel, "settings_sidebar_title")
    assert heading is not None
    assert heading.mapTo(panel, QPoint()).y() == title.mapTo(panel, QPoint()).y()
    assert heading.height() == title.height()
    assert heading.fontMetrics().ascent() == title.fontMetrics().ascent()
    assert heading.fontMetrics().height() == title.fontMetrics().height()
    assert title.mapTo(panel, QPoint()).x() == panel.tabs.mapTo(panel, QPoint()).x()


def test_settings_category_marker_retargets_and_snaps_when_hidden(panel, qtbot, monkeypatch):
    from Main_App.gui import settings_navigation

    monkeypatch.setattr(settings_navigation, "widget_animation_duration", lambda _widget, maximum: maximum)
    navigation = panel.settings_navigation
    animation = navigation._indicator_animation
    navigation.setFocus()
    qtbot.waitUntil(navigation.hasFocus)
    qtbot.keyClick(navigation, Qt.Key.Key_Down)

    assert animation.state() == QAbstractAnimation.State.Running
    assert panel.tabs.currentIndex() == panel._protocol_tab_index
    assert panel.settings_page_title.text() == "Protocol"
    animation.setCurrentTime(animation.duration() // 3)
    assert panel._preproc_tab_index < navigation._indicator_row < panel._protocol_tab_index

    qtbot.keyClick(navigation, Qt.Key.Key_Down)
    assert panel.tabs.currentIndex() == panel._harmonic_tab_index
    assert panel.tabs.currentWidget().isVisibleTo(panel)
    assert panel.settings_page_title.text() == "Harmonics"
    assert navigation.hasFocus()
    assert panel._preproc_tab_index < animation.startValue() < panel._harmonic_tab_index
    assert animation.endValue() == panel._harmonic_tab_index
    animation.setCurrentTime(animation.duration())
    selected_row = QRectF(navigation.visualItemRect(navigation.currentItem()))
    assert navigation._indicator_rect().center().y() == pytest.approx(selected_row.center().y())

    navigation.setCurrentRow(panel._preproc_tab_index)
    assert animation.state() == QAbstractAnimation.State.Running
    panel.tabs.setCurrentIndex(panel._roi_tab_index)
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert navigation.currentRow() == navigation._indicator_row == panel._roi_tab_index

    navigation.setCurrentRow(panel._preproc_tab_index)
    assert animation.state() == QAbstractAnimation.State.Running
    navigation.hide()
    assert animation.state() == QAbstractAnimation.State.Stopped
    assert navigation.currentRow() == navigation._indicator_row == panel._preproc_tab_index
    assert not panel.has_unsaved_changes()


def test_settings_reduced_motion_keeps_keyboard_selection_immediate(panel, qtbot, monkeypatch):
    from Main_App.gui import settings_navigation

    monkeypatch.setattr(settings_navigation, "widget_animation_duration", lambda _widget, _maximum: 0)
    navigation = panel.settings_navigation
    navigation.setFocus()
    qtbot.waitUntil(navigation.hasFocus)
    qtbot.keyClick(navigation, Qt.Key.Key_End)

    assert panel.tabs.currentIndex() == panel.tabs.count() - 1
    assert navigation.currentItem().text() == panel.settings_page_title.text() == "Diagnostics"
    assert navigation.currentRow() == navigation._indicator_row == panel.tabs.currentIndex()
    assert navigation._indicator_animation.state() == QAbstractAnimation.State.Stopped
    assert navigation.hasFocus()
    assert not panel.has_unsaved_changes()


def test_settings_invalid_draft_can_navigate_and_save_locates_field(panel, qtbot, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args))
    panel.preproc_edits[0].setText("0.1")
    panel.preproc_edits[1].setText("50")
    panel.tabs.setCurrentIndex(panel._roi_tab_index)
    assert panel.tabs.currentIndex() == panel._roi_tab_index
    assert not messages
    assert not panel.save_pending_changes()
    assert panel.tabs.currentIndex() == panel._preproc_tab_index
    assert panel.settings_navigation.currentRow() == panel._preproc_tab_index
    qtbot.waitUntil(panel.preproc_edits[0].hasFocus)
    assert panel.preproc_error_labels[0].isVisible()
    assert panel.settings_validation_status.isVisible()
    assert not messages
    _capture(panel, "settings-invalid-save")
    panel.preproc_edits[0].setText("60")
    panel.preproc_edits[1].setText("0.5")
    assert not panel.preproc_error_labels[0].isVisible()
    assert not panel.settings_validation_status.isVisible()


def test_settings_successful_save_clears_dirty_state(panel):
    panel.preproc_edits[0].setText("40")
    assert panel.has_unsaved_changes()
    assert panel.save_pending_changes()
    assert not panel.has_unsaved_changes()
    assert panel.project.preprocessing["low_pass"] == 40.0


@pytest.mark.parametrize("save", [True, False])
def test_application_appearance_uses_shared_save_and_cancel(panel, monkeypatch, save):
    from Main_App.gui import settings_panel

    apply_appearance = Mock()
    monkeypatch.setattr(settings_panel, "set_appearance_mode", apply_appearance)
    navigation = panel.settings_navigation
    (application_item,) = navigation.findItems("Application", Qt.MatchFlag.MatchExactly)
    navigation.setCurrentItem(application_item)
    combo = panel.appearance_mode_combo
    assert combo.isVisibleTo(panel)
    assert [combo.itemText(index) for index in range(combo.count())] == ["Light", "Dark", "Auto"]
    assert combo.currentText() == "Auto"
    combo.setCurrentText("Dark")
    assert panel.has_unsaved_changes()
    apply_appearance.assert_not_called()
    assert panel.manager.get_appearance_mode() == "Auto"

    if save:
        assert panel.save_pending_changes()
        apply_appearance.assert_called_once_with(QApplication.instance(), "Dark")
    else:
        panel.reject()
        apply_appearance.assert_not_called()
    reopened = SettingsManager(panel.manager.ini_path)
    assert reopened.get_appearance_mode() == ("Dark" if save else "Auto")


def test_extracted_pages_keep_one_dialog_owner_and_initial_draft(tmp_path, qtbot, monkeypatch):
    from Main_App.gui import settings_panel
    from Main_App.gui import settings_experimental_preprocessing_page

    calls = []
    section_calls = []
    for module_name, builder_name in (
        ("settings_preprocessing_page", "build_preprocessing_page"),
        ("settings_protocol_page", "build_protocol_page"),
        ("settings_harmonic_page", "build_harmonic_page"),
        ("settings_preferences_pages", "build_quality_control_page"),
        ("settings_experimental_page", "build_experimental_page"),
        ("settings_preferences_pages", "build_application_page"),
    ):
        module = getattr(settings_panel, module_name)
        original = getattr(module, builder_name)

        def build(owner, tabs, *, _original=original, _name=builder_name, **kwargs):
            calls.append((_name, owner, tabs))
            return _original(owner, tabs, **kwargs)

        monkeypatch.setattr(module, builder_name, build)

    for builder_name in (
        "build_signal_review", "build_removed_electrode_review", "build_raw_spectral_review",
    ):
        original = getattr(settings_experimental_preprocessing_page, builder_name)

        def build_section(owner, page, *args, _original=original):
            section_calls.append((owner, page))
            return _original(owner, page, *args)

        monkeypatch.setattr(settings_experimental_preprocessing_page, builder_name, build_section)

    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    project = _prep_project(tmp_path)
    manager = SettingsManager(str(tmp_path / "settings.ini"))
    widget = SettingsDialog(manager, project=project)
    qtbot.addWidget(widget)

    assert len(calls) == 6
    assert all(owner is widget and tabs is widget.tabs for _, owner, tabs in calls)
    assert section_calls == [
        (widget, widget.preprocessing_qc_tabs.widget(index)) for index in range(3)
    ]
    assert [widget.tabs.tabText(index) for index in range(widget.tabs.count())] == [
        "Processing", "Protocol", "Harmonics", "ROIs", "Quality Control",
        "Experimental", "Application", "Diagnostics",
    ]
    assert not widget.has_unsaved_changes()

    opened = []
    monkeypatch.setattr(settings_panel, "changeProjectsRoot", opened.append)
    widget.btn_changeRoot.click()
    assert opened == [widget]
    assert not widget.has_unsaved_changes()


def test_diagnostics_copy_and_preference_persist_immediately(tmp_path, qtbot, monkeypatch):
    from Main_App.diagnostics import crash_reporting
    from Main_App.diagnostics.crash_reporting import CrashReporter
    from Main_App.diagnostics.crash_store import CrashStore

    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(crash_reporting.faulthandler, "is_enabled", lambda: True)
    store = CrashStore(tmp_path / "crashes")
    reporter = CrashReporter(store, "3.0.0")
    reporter.set_preference(True)
    monkeypatch.setattr(crash_reporting, "_active", reporter)
    manager = SettingsManager(str(tmp_path / "settings.ini"))
    widget = SettingsDialog(manager)
    qtbot.addWidget(widget)
    apply_fpvs_theme(QApplication.instance())
    widget.resize(1020, 790)
    widget.show()
    qtbot.waitExposed(widget)
    widget.settings_navigation.setCurrentRow(widget.tabs.count() - 1)
    page = widget.tabs.currentWidget()
    assert widget.settings_page_title.text() == "Diagnostics"
    assert any("operating system versions" in label.text() for label in page.findChildren(QLabel))
    toggle = page.findChild(QCheckBox, "settings_automatic_crash_reporting")
    assert toggle.isVisible() and toggle.isChecked()
    toggle.click()
    assert store.preference() is False
    assert not widget.has_unsaved_changes()
    toggle.click()
    assert store.preference() is True
    reporter.shutdown(clean=True)


@pytest.mark.parametrize(("appearance", "action"), [("Dark", "enable"), ("Light", "decline"), ("Dark", "escape")])
def test_diagnostics_discloses_before_default_capture(tmp_path, qtbot, monkeypatch, appearance, action):
    from Main_App.diagnostics import crash_reporting
    from Main_App.diagnostics.crash_reporting import CrashReporter
    from Main_App.diagnostics.crash_store import CrashStore
    from Main_App.gui.diagnostics_preferences import disclose_automatic_reporting

    monkeypatch.setattr(crash_reporting.faulthandler, "is_enabled", lambda: True)
    set_appearance_mode(QApplication.instance(), appearance)
    reporter = CrashReporter(CrashStore(tmp_path / "crashes"), "3.0.0")
    observed = []

    def choose():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QDialog) or dialog.objectName() != "automatic_reporting_disclosure":
            return
        labels = dialog.findChildren(QLabel)
        enable = dialog.findChild(QPushButton, "automatic_reporting_enable")
        decline = dialog.findChild(QPushButton, "automatic_reporting_decline")
        observed.append(
            (
                reporter.preference(),
                reporter._session,
                "\n".join(label.text() for label in labels),
                not dialog.windowIcon().isNull() and any(not label.pixmap().isNull() for label in labels),
                set(label.font().family() for label in labels),
                enable.isDefault() and enable.property("variant") == "primary",
                all(label.height() >= label.heightForWidth(label.width()) for label in labels if label.wordWrap()),
                all(button.height() >= 40 and button.width() >= button.sizeHint().width() for button in (enable, decline)),
            )
        )
        if action == "enable":
            qtbot.keyClick(enable, Qt.Key.Key_Return)
        elif action == "decline":
            decline.click()
        else:
            qtbot.keyClick(dialog, Qt.Key.Key_Escape)

    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(lambda: QApplication.activeModalWidget().close() if QApplication.activeModalWidget() else None)
    timeout.start(3000)
    QTimer.singleShot(25, choose)
    disclose_automatic_reporting(reporter)
    timeout.stop()
    assert len(observed) == 1
    preference, session, copy, has_logo, fonts, primary_default, labels_fit, buttons_fit = observed[0]
    assert preference is None and session is None
    assert "CPU and graphics models" in copy
    assert "What stays local" in copy and "Turning it off deletes pending reports." in copy
    assert has_logo and fonts == {APP_FONT_FAMILY}
    assert primary_default and labels_fit and buttons_fit
    assert reporter.preference() is (action == "enable")
    assert (reporter._session is not None) is (action == "enable")
    reporter.shutdown(clean=True)


def test_settings_enter_on_shared_save_persists_draft(panel, qtbot):
    panel.preproc_edits[0].setText("40")
    save_button = panel.findChild(QPushButton, "settings_footer_save")
    save_button.setFocus()
    qtbot.waitUntil(save_button.hasFocus)

    with qtbot.waitSignal(panel.accepted):
        qtbot.keyClick(save_button, Qt.Key.Key_Return)

    assert not panel.isVisible()
    assert not panel.has_unsaved_changes()
    reloaded = Project.load(panel.project.project_root)
    assert reloaded.preprocessing["low_pass"] == 40.0


def test_settings_escape_cancels_draft_without_persistence(panel, qtbot):
    original = panel.project.preprocessing["low_pass"]
    edit = panel.preproc_edits[0]
    edit.setText("40")
    edit.setFocus()
    qtbot.waitUntil(edit.hasFocus)
    assert panel.has_unsaved_changes()

    with qtbot.waitSignal(panel.rejected):
        qtbot.keyClick(edit, Qt.Key.Key_Escape)

    assert not panel.isVisible()
    assert panel.project.preprocessing["low_pass"] == original
    reloaded = Project.load(panel.project.project_root)
    assert reloaded.preprocessing["low_pass"] == original


def test_settings_failed_save_keeps_draft_and_stays_open(panel, monkeypatch):
    panel.preproc_edits[0].setText("40")
    monkeypatch.setattr(panel.project, "save", lambda: (_ for _ in ()).throw(OSError("Disk unavailable")))
    assert not panel.save_pending_changes()
    assert panel.has_unsaved_changes()
    assert panel.isVisible()


@pytest.mark.parametrize("activity", ["_run_active", "_settings_post_processing_activity_active"])
def test_save_that_starts_postprocessing_does_not_allow_project_exit(panel, monkeypatch, activity):
    def save_and_start():
        panel._pending_save_succeeded = True
        setattr(panel, activity, True)
    monkeypatch.setattr(panel, "_save", save_and_start)
    assert not panel.save_pending_changes()


def test_partial_recalculation_keeps_unrelated_settings_draft(panel, monkeypatch):
    from Main_App.gui import processing_workflows

    resumed = []
    panel.host = object()
    original_debug = panel.debug_check.isChecked()
    panel.debug_check.setChecked(not original_debug)
    monkeypatch.setattr(panel, "_settings_post_processing_activity_is_active", lambda: False)
    monkeypatch.setattr(processing_workflows, "resume_post_processing", resumed.append)
    panel._resume_frequency_domain_post_processing()
    assert resumed == [panel.host]
    assert panel.isVisible()
    assert panel.has_unsaved_changes()
    assert panel.debug_check.isChecked() is not original_debug


@pytest.mark.parametrize("tab", range(7))
def test_settings_tabs_and_actions_fit_supported_workspace(panel, qtbot, tab):
    panel.tabs.setCurrentIndex(tab)
    qtbot.wait(25)
    _capture(panel, f"settings-tab-{tab}")
    assert panel.width() <= 1020 and panel.height() <= 790, {
        panel.tabs.tabText(index): panel.tabs.widget(index).minimumSizeHint().toTuple()
        for index in range(panel.tabs.count())
    }
    for name in ("settings_footer_save", "settings_footer_cancel"):
        button = panel.findChild(QPushButton, name)
        assert button is not None and button.isVisibleTo(panel), name
    for button in panel._settings_footer_buttons:
        if button.isVisible():
            bounds = QRect(button.mapTo(panel, QPoint(0, 0)), button.size())
            assert panel.rect().contains(bounds), button.objectName()
    for widget in panel.findChildren(QWidget):
        if not widget.isVisibleTo(panel) or not isinstance(
            widget, (QLabel, QLineEdit, QComboBox, QAbstractButton)
        ):
            continue
        ancestors = []
        ancestor = widget.parentWidget()
        while ancestor is not None and ancestor is not panel:
            ancestors.append(ancestor)
            ancestor = ancestor.parentWidget()
        # Qt's list and table internals do not need form-control bounds checks.
        if any(
            isinstance(parent, QAbstractScrollArea) and not isinstance(parent, QScrollArea)
            for parent in ancestors
        ):
            continue
        name = widget.objectName() or type(widget).__name__
        icon_only = (
            isinstance(widget, QAbstractButton)
            and widget.property("iconButton")
            and not widget.text()
        )
        minimum_height = widget.minimumSizeHint().height()
        electrode_button = widget in panel.roi_editor.map_widget.electrode_buttons.values()
        if electrode_button:
            # Map buttons have custom circular geometry and zero text padding;
            # the native tool-button size hint includes unused style chrome.
            minimum_height = widget.fontMetrics().height() + 6
        elif icon_only:
            minimum_height = widget.iconSize().height() + 4
        if isinstance(widget, QLabel) and widget.wordWrap():
            minimum_height = max(minimum_height, widget.heightForWidth(widget.width()))
        assert widget.height() >= minimum_height, name
        if isinstance(widget, (QLineEdit, QComboBox, QAbstractButton)):
            minimum_width = (
                widget.fontMetrics().horizontalAdvance(widget.text()) + 6
                if electrode_button else widget.iconSize().width() + 4
                if icon_only else widget.minimumSizeHint().width()
            )
            assert widget.width() >= minimum_width, name
        for ancestor in [*ancestors, panel]:
            scroll = ancestor.parentWidget()
            if isinstance(scroll, QScrollArea) and ancestor is scroll.viewport() and (
                scroll.verticalScrollBar().maximum() or scroll.horizontalScrollBar().maximum()
            ):
                break
            bounds = QRect(widget.mapTo(ancestor, QPoint(0, 0)), widget.size())
            assert ancestor.rect().contains(bounds), (name, ancestor.objectName())


def test_compact_settings_keep_navigation_and_actions_above_overflow(panel, qtbot):
    panel.resize(900, 460)
    qtbot.waitUntil(lambda: panel.size().toTuple() == (900, 460))
    save = panel.findChild(QPushButton, "settings_footer_save")
    cancel = panel.findChild(QPushButton, "settings_footer_cancel")
    for index in range(panel.tabs.count()):
        panel.tabs.setCurrentIndex(index)
        QApplication.processEvents()
        scroll = panel.tabs.currentWidget().findChild(QScrollArea, "settings_category_scroll")
        assert scroll.isVisibleTo(panel)
        assert scroll.horizontalScrollBar().maximum() == 0
        assert not scroll.isAncestorOf(panel.settings_navigation)
        assert not scroll.isAncestorOf(panel.settings_page_title)
        for button in (save, cancel):
            assert button.isVisibleTo(panel) and not scroll.isAncestorOf(button)
            assert panel.rect().contains(QRect(button.mapTo(panel, QPoint()), button.size()))

    panel.tabs.setCurrentIndex(panel._roi_tab_index)
    map_scroll = panel.roi_editor.map_scroll
    qtbot.waitUntil(lambda: map_scroll.verticalScrollBar().maximum() > 0)
    electrode = panel.roi_editor.map_widget.electrode_buttons["Oz"]
    electrode.setFocus()
    qtbot.waitUntil(electrode.hasFocus)
    viewport = map_scroll.viewport()
    assert viewport.rect().contains(QRect(electrode.mapTo(viewport, QPoint()), electrode.size()))
    assert electrode.width() >= 36 and electrode.height() >= 36
    _capture(panel, "settings-compact-roi")


def test_preprocessing_keyboard_focus_can_leave_invalid_field(panel, qtbot):
    panel.preproc_edits[0].setFocus()
    panel.preproc_edits[0].setText("invalid")
    qtbot.keyClick(panel.preproc_edits[0], Qt.Key.Key_Tab)
    assert not panel.preproc_edits[0].hasFocus()
    assert panel.has_unsaved_changes()
