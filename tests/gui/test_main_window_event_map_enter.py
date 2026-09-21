import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox, QPushButton

from Main_App.gui import main_window as main_window_module
import Main_App.gui.update_manager as update_manager

_REAL_MESSAGEBOX_QUESTION = QMessageBox.question


def _build_window(tmp_path, qtbot, monkeypatch):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    monkeypatch.setattr(update_manager, "cleanup_old_executable", lambda: None)
    monkeypatch.setattr(update_manager, "check_for_updates_on_launch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_window_module,
        "select_projects_root",
        lambda self: setattr(self, "projectsRoot", tmp_path),
    )

    QApplication.instance() or QApplication(["pytest"])
    win = main_window_module.MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.wait(50)
    return win


def _live_rows(win):
    return tuple(win._live_event_map_rows())


def _capture(win, name):
    folder = os.environ.get("FPVS_UX_SCREENSHOT_DIR")
    if folder:
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        assert win.grab().save(str(path / f"{name}.png"))


def _row_fields(win, row):
    label_edit = win._event_row_label_edit(row)
    id_edit = win._event_row_id_edit(row)
    assert isinstance(label_edit, QLineEdit)
    assert isinstance(id_edit, QLineEdit)
    return label_edit, id_edit


def _type_valid_id(id_edit, qtbot, text="10"):
    id_edit.clear()
    id_edit.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(id_edit.hasFocus)
    qtbot.keyClicks(id_edit, text)
    assert id_edit.text() == text


@pytest.mark.parametrize("key", [Qt.Key_Return, Qt.Key_Enter])
def test_startup_event_id_enter_adds_one_row_and_focuses_new_label(tmp_path, qtbot, monkeypatch, key):
    win = _build_window(tmp_path, qtbot, monkeypatch)
    initial_rows = _live_rows(win)
    assert len(initial_rows) == 1

    startup_row = initial_rows[0]
    label_edit, id_edit = _row_fields(win, startup_row)
    label_edit.setText("Cond A")
    _type_valid_id(id_edit, qtbot, "10")

    qtbot.keyClick(id_edit, key)

    qtbot.waitUntil(lambda: len(_live_rows(win)) == len(initial_rows) + 1)
    qtbot.wait(50)
    current_rows = _live_rows(win)
    assert len(current_rows) == len(initial_rows) + 1
    new_row = next(row for row in current_rows if row not in initial_rows)
    new_label, _new_id = _row_fields(win, new_row)
    qtbot.waitUntil(new_label.hasFocus)
    assert QApplication.focusWidget() is new_label


def test_newly_added_event_id_field_is_bound(tmp_path, qtbot, monkeypatch):
    win = _build_window(tmp_path, qtbot, monkeypatch)
    first_rows = _live_rows(win)
    startup_row = first_rows[0]
    startup_label, startup_id = _row_fields(win, startup_row)
    startup_label.setText("Cond A")
    _type_valid_id(startup_id, qtbot, "10")
    qtbot.keyClick(startup_id, Qt.Key_Return)
    qtbot.waitUntil(lambda: len(_live_rows(win)) == 2)

    second_rows = _live_rows(win)
    second_row = next(row for row in second_rows if row not in first_rows)
    second_label, second_id = _row_fields(win, second_row)
    qtbot.waitUntil(second_label.hasFocus)
    second_label.setText("Cond B")
    _type_valid_id(second_id, qtbot, "20")
    qtbot.keyClick(second_id, Qt.Key_Return)

    qtbot.waitUntil(lambda: len(_live_rows(win)) == 3)
    third_rows = _live_rows(win)
    assert len(third_rows) == 3
    third_row = next(row for row in third_rows if row not in second_rows)
    third_label, _third_id = _row_fields(win, third_row)
    qtbot.waitUntil(third_label.hasFocus)
    assert QApplication.focusWidget() is third_label


def test_enter_in_label_field_is_unchanged(tmp_path, qtbot, monkeypatch):
    win = _build_window(tmp_path, qtbot, monkeypatch)
    initial_rows = _live_rows(win)
    startup_row = initial_rows[0]
    label_edit, _id_edit = _row_fields(win, startup_row)

    label_edit.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(label_edit.hasFocus)
    qtbot.keyClick(label_edit, Qt.Key_Return)
    qtbot.wait(50)

    assert len(_live_rows(win)) == len(initial_rows)


def test_invalid_event_id_enter_does_not_add_row(tmp_path, qtbot, monkeypatch):
    win = _build_window(tmp_path, qtbot, monkeypatch)
    initial_rows = _live_rows(win)
    startup_row = initial_rows[0]
    _label_edit, id_edit = _row_fields(win, startup_row)

    id_edit.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(id_edit.hasFocus)
    qtbot.keyClicks(id_edit, "0")
    assert id_edit.text() == "0"
    qtbot.keyClick(id_edit, Qt.Key_Return)
    qtbot.wait(50)

    assert len(_live_rows(win)) == len(initial_rows)


def test_disabled_add_button_blocks_enter(tmp_path, qtbot, monkeypatch):
    win = _build_window(tmp_path, qtbot, monkeypatch)
    initial_rows = _live_rows(win)
    startup_row = initial_rows[0]
    _label_edit, id_edit = _row_fields(win, startup_row)

    win.btn_add_row.setEnabled(False)
    _type_valid_id(id_edit, qtbot, "10")
    qtbot.keyClick(id_edit, Qt.Key_Return)
    qtbot.wait(50)

    assert len(_live_rows(win)) == len(initial_rows)


def test_start_processing_requires_complete_event_map_entry(tmp_path, qtbot, monkeypatch):
    win = _build_window(tmp_path, qtbot, monkeypatch)
    row = _live_rows(win)[0]
    label_edit, id_edit = _row_fields(win, row)

    assert win.rb_batch.isChecked()
    assert not win.btn_start.isEnabled()

    label_edit.setText("Cond A")
    assert not win.btn_start.isEnabled()

    id_edit.setText("0")
    assert not win.btn_start.isEnabled()

    label_edit.clear()
    _type_valid_id(id_edit, qtbot, "10")
    assert not win.btn_start.isEnabled()

    label_edit.setText("Cond A")
    assert win.btn_start.isEnabled()

    id_edit.clear()
    assert not win.btn_start.isEnabled()

    _type_valid_id(id_edit, qtbot, "10")
    assert win.btn_start.isEnabled()

    win.add_event_row()
    assert len(_live_rows(win)) == 2
    assert win.btn_start.isEnabled()

    remove_button = row.findChild(QPushButton, "event_map_remove_button")
    assert remove_button is not None
    qtbot.mouseClick(remove_button, Qt.LeftButton)
    assert not win.btn_start.isEnabled()


def test_single_mode_requires_event_map_and_bdf(tmp_path, qtbot, monkeypatch):
    win = _build_window(tmp_path, qtbot, monkeypatch)
    row = _live_rows(win)[0]
    label_edit, id_edit = _row_fields(win, row)
    bdf_path = tmp_path / "sample.bdf"
    bdf_path.touch()

    win.rb_single.setChecked(True)
    label_edit.setText("Cond A")
    _type_valid_id(id_edit, qtbot, "10")
    assert not win.btn_start.isEnabled()

    win.le_input_file.setText(str(bdf_path))
    assert win.btn_start.isEnabled()

    label_edit.clear()
    assert not win.btn_start.isEnabled()


def test_partial_and_duplicate_conditions_block_save_and_focus_exact_field(tmp_path, qtbot, monkeypatch):
    from Main_App.gui import event_map, project_workflows

    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.show_home_page()
    label, ident = _row_fields(win, _live_rows(win)[0])
    label.setText("Faces")
    ident.setText("1")
    project = SimpleNamespace(event_map={"Faces": 1}, options={"mode": "batch"}, save=Mock())
    win.currentProject = project
    win.add_event_row("Objects", "")
    row = _live_rows(win)[1]
    duplicate_label, missing_id = _row_fields(win, row)
    assert not win.btn_start.isEnabled()
    assert row.findChild(QLabel, "condition_row_error").text()
    assert project_workflows.save_project_settings(win) is False
    qtbot.waitUntil(missing_id.hasFocus)
    win.resize(1280, 900)
    qtbot.wait(25)
    error = row.findChild(QLabel, "condition_row_error")
    assert 0 <= error.y() - missing_id.geometry().bottom() <= 8
    _capture(win, "main-condition-validation")
    project.save.assert_not_called()
    assert project.event_map == {"Faces": 1}
    missing_id.setText("2")
    duplicate_label.setText("Faces")
    assert project_workflows.save_project_settings(win) is False
    qtbot.waitUntil(duplicate_label.hasFocus)
    duplicate_label.setText("Objects")
    assert event_map.validated_event_map(win) == {"Faces": 1, "Objects": 2}
    assert row.findChild(QLabel, "condition_row_error").isHidden()
    assert project_workflows.save_project_settings(win)
    assert project.event_map == {"Faces": 1, "Objects": 2}
    win.currentProject = None


@pytest.mark.parametrize("choice,allowed", [(QMessageBox.Cancel, False), (QMessageBox.Discard, True), (QMessageBox.Save, True)])
def test_dirty_project_guard_protects_setup_draft(tmp_path, qtbot, monkeypatch, choice, allowed):
    from Main_App.gui import project_drafts

    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.show_home_page()
    label, ident = _row_fields(win, _live_rows(win)[0])
    label.setText("Faces")
    ident.setText("1")
    project = SimpleNamespace(event_map={"Faces": 1}, options={"mode": "batch"}, save=Mock())
    win.currentProject = project
    project_drafts.remember_saved_setup(win)
    label.setText("Objects")
    assert win.project_draft_status.text() == "Unsaved changes"
    monkeypatch.setattr(project_drafts.QMessageBox, "question", lambda *_: choice)
    assert project_drafts.confirm_project_draft_exit(win) is allowed
    assert project.event_map == ({"Objects": 1} if choice == QMessageBox.Save else {"Faces": 1})
    assert label.text() == "Objects"
    win.currentProject = None


def test_dirty_project_prompt_defaults_to_cancel_and_preserves_draft(tmp_path, qtbot, monkeypatch):
    from Main_App.gui import project_drafts

    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.show_home_page()
    win.resize(1280, 900)
    label, ident = _row_fields(win, _live_rows(win)[0])
    label.setText("Faces")
    ident.setText("1")
    project = SimpleNamespace(event_map={"Faces": 1}, options={"mode": "batch"}, save=Mock())
    win.currentProject = project
    project_drafts.remember_saved_setup(win)
    label.setText("Objects")
    monkeypatch.setattr(QMessageBox, "question", _REAL_MESSAGEBOX_QUESTION)
    failures = []

    def inspect_and_cancel():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, QMessageBox)
            cancel = dialog.button(QMessageBox.Cancel)
            assert dialog.defaultButton() is cancel
            assert dialog.width() <= win.width()
            assert dialog.height() <= win.height()
            for choice in (QMessageBox.Save, QMessageBox.Discard, QMessageBox.Cancel):
                button = dialog.button(choice)
                assert button.isVisible()
                assert dialog.rect().contains(button.mapTo(dialog, button.rect().bottomRight()))
            _capture(dialog, "project-unsaved-confirmation")
        except Exception as exc:
            failures.append(exc)
        finally:
            if isinstance(dialog, QMessageBox):
                dialog.button(QMessageBox.Cancel).click()

    QTimer.singleShot(50, inspect_and_cancel)
    try:
        assert not project_drafts.confirm_project_draft_exit(win)
        if failures:
            raise failures[0]
        assert label.text() == "Objects"
        assert project.event_map == {"Faces": 1}
        assert project_drafts.has_condition_changes(win)
        project.save.assert_not_called()
    finally:
        win.currentProject = None


def test_failed_settings_save_keeps_project_open(tmp_path, qtbot, monkeypatch):
    from Main_App.gui import project_drafts

    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.currentProject = SimpleNamespace(event_map={}, options={"mode": "batch"})
    project_drafts.remember_saved_setup(win)
    win._settings_page = SimpleNamespace(has_unsaved_changes=lambda: True, save_pending_changes=lambda: False)
    monkeypatch.setattr(win, "open_settings_window", Mock())
    monkeypatch.setattr(project_drafts.QMessageBox, "question", lambda *_: QMessageBox.Save)
    assert not project_drafts.confirm_project_draft_exit(win)
    win.open_settings_window.assert_called_once()
    win.currentProject = None
    win._settings_page = None


@pytest.mark.parametrize("activity_attr", ["_run_active", "_settings_post_processing_activity_active"])
@pytest.mark.parametrize("saved", [False, True])
def test_settings_save_starting_work_blocks_exit_without_hiding_activity(
    tmp_path, qtbot, monkeypatch, activity_attr, saved,
):
    from Main_App.gui import project_drafts

    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.currentProject = SimpleNamespace(event_map={}, options={"mode": "batch"})
    project_drafts.remember_saved_setup(win)

    def save():
        setattr(win, activity_attr, True)
        return saved

    win._settings_page = SimpleNamespace(has_unsaved_changes=lambda: True, save_pending_changes=save)
    monkeypatch.setattr(win, "open_settings_window", Mock())
    monkeypatch.setattr(project_drafts.QMessageBox, "question", lambda *_: QMessageBox.Save)
    assert not project_drafts.confirm_project_draft_exit(win)
    win.open_settings_window.assert_not_called()
    setattr(win, activity_attr, False)
    win.currentProject = None
    win._settings_page = None


def test_single_selection_survives_completion_and_missing_file_disables_start(tmp_path, qtbot, monkeypatch):
    from Main_App.gui.processing_completion import finalize_processing_host_state
    from Main_App.gui.processing_inputs import selected_single_file
    from Main_App.Shared import user_messages

    win = _build_window(tmp_path, qtbot, monkeypatch)
    monkeypatch.setattr(user_messages, "show_info", lambda *_: None)
    path = tmp_path / "sample.bdf"
    path.touch()
    win.rb_single.setChecked(True)
    label, ident = _row_fields(win, _live_rows(win)[0])
    label.setText("Faces")
    ident.setText("1")
    win.le_input_file.setText(str(path))
    win.data_paths = [str(path)]
    win.validated_params = {}
    finalize_processing_host_state(win, True)
    assert selected_single_file(win) == str(path)
    assert win.data_paths == [str(path)]
    assert win.btn_start.isEnabled()
    path.unlink()
    win._update_start_enabled()
    assert not win.btn_start.isEnabled()
    assert "available BDF" in win.processing_readiness_label.text()


def test_last_run_summary_and_actions_fit_supported_workspace(tmp_path, qtbot, monkeypatch):
    from Main_App.gui.run_outcome import present_last_run
    from Main_App.gui.run_outcome_model import RunOutcome

    win = _build_window(tmp_path, qtbot, monkeypatch)
    win.show_home_page()
    win.resize(1280, 900)
    win._last_run_outcome = RunOutcome(completed=18, skipped=4, excluded=2, failed=1, condition_warnings=3)
    win._last_run_output_folder = str(tmp_path)
    win._post_processing_failure_reason = "QC review must finish."
    present_last_run(win, success=False)
    qtbot.wait(50)
    assert "Incomplete" in win.last_run_label.text()
    assert "18 completed" in win.last_run_label.text()
    for widget in (win.last_run_label, win.last_run_output_button, win.last_run_issues_button, win.btn_start):
        assert widget.isVisible()
        assert win.homeWidget.rect().contains(widget.mapTo(win.homeWidget, widget.rect().bottomRight()))
    _capture(win, "main-run-outcome")
