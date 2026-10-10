"""Approved visible checks for Settings drafts, validation and bounded layout."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from Main_App.Shared.settings_manager import SettingsManager
from Main_App.gui.settings_panel import SettingsDialog
from Main_App.gui.theme import apply_fpvs_theme
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
    assert panel.width() <= 1020 and panel.height() <= 790
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
        # Lists and chip viewers intentionally scroll their own content.
        if any(isinstance(parent, QAbstractScrollArea) for parent in ancestors):
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
            bounds = QRect(widget.mapTo(ancestor, QPoint(0, 0)), widget.size())
            assert ancestor.rect().contains(bounds), (name, ancestor.objectName())
    _capture(panel, f"settings-tab-{tab}")


def test_preprocessing_keyboard_focus_can_leave_invalid_field(panel, qtbot):
    panel.preproc_edits[0].setFocus()
    panel.preproc_edits[0].setText("invalid")
    qtbot.keyClick(panel.preproc_edits[0], Qt.Key.Key_Tab)
    assert not panel.preproc_edits[0].hasFocus()
    assert panel.has_unsaved_changes()
