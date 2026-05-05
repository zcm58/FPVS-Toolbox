import importlib.util
import os

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

from Main_App.PySide6_App.GUI import main_window as main_window_module
import Main_App.PySide6_App.GUI.update_manager as update_manager


def _build_window(tmp_path, qtbot, monkeypatch):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    monkeypatch.setattr(update_manager, "cleanup_old_executable", lambda: None)
    monkeypatch.setattr(update_manager, "check_for_updates_on_launch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_window_module,
        "select_projects_root",
        lambda self: setattr(self, "projectsRoot", tmp_path),
    )

    QApplication.instance() or QApplication(["pytest", "-platform", "offscreen"])
    win = main_window_module.MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.wait(50)
    return win


def _live_rows(win):
    return tuple(win._live_event_map_rows())


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
