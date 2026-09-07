"""CI-only visible exclusions manager checks using synthetic snapshots."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QObject, Qt, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from Main_App.gui import dataset_exclusions_dialog as module  # noqa: E402


def _snapshot(root):
    return SimpleNamespace(project_root=root, revision="fixture", rows=(
        SimpleNamespace(identity="p:P1", participant_id="P1", recording_id="", group_label="Group A",
                        has_processed_data=True, scope="both", reason="Existing note",
                        details=("Condition-specific exclusions: Faces",)),
        SimpleNamespace(identity="r:P2-1", participant_id="P2", recording_id="P2-1", group_label="Group A",
                        has_processed_data=True, scope="exclude_analysis", reason="QC decision",
                        details=("Whole-participant exclusions also apply to this recording.",)),
        SimpleNamespace(identity="p:P3", participant_id="P3", recording_id="", group_label="Group B",
                        has_processed_data=False, scope="skip_processing", reason="", details=()),
        SimpleNamespace(identity="r:P1-1", participant_id="P1", recording_id="P1-1", group_label="Group A",
                        has_processed_data=True, scope="include", reason="", details=()),
    ))


def _dialog(qtbot, monkeypatch, tmp_path):
    result = _snapshot(tmp_path)
    calls = []

    class Worker(QObject):
        result_ready = Signal(object)
        failed = Signal(str)
        finished = Signal()
        error = ""
        hold = False

        def __init__(self, root, **kwargs):
            super().__init__()
            calls.append((root, kwargs))

        def start(self):
            if not self.hold:
                QTimer.singleShot(0, self.complete)

        def complete(self):
            if self.error:
                self.failed.emit(self.error)
            else:
                self.result_ready.emit(result)
            self.finished.emit()

    monkeypatch.setattr(module, "DatasetExclusionsWorker", Worker)
    dialog = module.DatasetExclusionsDialog(tmp_path)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    qtbot.waitUntil(lambda: not dialog._busy)
    return dialog, Worker, calls


def test_exclusions_layout_and_unprocessed_scope_are_visible(qtbot, monkeypatch, tmp_path):
    dialog, _, _ = _dialog(qtbot, monkeypatch, tmp_path)
    assert dialog.width() == 1100
    assert dialog.height() == 650
    assert dialog.windowModality() == Qt.ApplicationModal
    assert dialog.table.horizontalScrollBar().maximum() == 0
    assert dialog.apply_button.isVisible()
    assert "Condition-specific exclusions: Faces" in dialog.details.toPlainText()
    assert dialog.scope_combo.currentData() == "both"
    dialog.table.selectRow(2)
    assert not dialog.scope_combo.model().item(dialog.scope_combo.findData("exclude_analysis")).isEnabled()
    assert "No processed data yet" in dialog.eligibility.text()
    assert not dialog.bulk_scope.model().item(2).isEnabled()


def test_pending_parent_choices_update_recording_effective_scope(qtbot, monkeypatch, tmp_path):
    dialog, _, _ = _dialog(qtbot, monkeypatch, tmp_path)
    assert dialog.table.item(3, 4).text() == "Both exclusions"
    dialog.table.selectRow(0)
    dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("include"))
    assert dialog.table.item(3, 4).text() == "Included"
    assert dialog._scopes["r:P1-1"] == "include"


def test_include_all_reaches_filtered_rows_but_preserves_condition_details(qtbot, monkeypatch, tmp_path):
    dialog, _, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dialog.search.setText("P1")
    assert dialog.table.isRowHidden(1)
    dialog.include_all_button.click()
    assert set(dialog._scopes.values()) == {"include"}
    assert "Condition-specific exclusions: Faces" in dialog.details.toPlainText()


def test_individual_choices_and_reasons_survive_navigation_and_save(qtbot, monkeypatch, tmp_path):
    dialog, _, calls = _dialog(qtbot, monkeypatch, tmp_path)
    dialog.table.selectRow(1)
    dialog.scope_combo.setCurrentIndex(dialog.scope_combo.findData("skip_processing"))
    dialog.reason_edit.setFocus()
    dialog.reason_edit.selectAll()
    qtbot.keyClicks(dialog.reason_edit, "Keep out of processing")
    dialog.table.selectRow(0)
    dialog.table.selectRow(1)
    assert dialog.reason_edit.text() == "Keep out of processing"
    with qtbot.waitSignal(dialog.exclusions_changed):
        dialog.apply_button.click()
    assert calls[-1][1]["changes"] == {"r:P2-1": "skip_processing"}
    assert calls[-1][1]["reasons"] == {"r:P2-1": "Keep out of processing"}
    assert dialog.result() == QDialog.Accepted


def test_busy_close_is_blocked_and_save_error_keeps_choices(qtbot, monkeypatch, tmp_path):
    dialog, Worker, _ = _dialog(qtbot, monkeypatch, tmp_path)
    dialog.include_all_button.click()
    Worker.hold = True
    dialog.apply_button.click()
    assert dialog._busy
    assert not dialog.cancel_button.isEnabled()
    dialog.reject()
    dialog.close()
    assert dialog.isVisible()
    Worker.error = "Project changed; reload before saving"
    dialog._worker.complete()
    assert not dialog._busy
    assert dialog.isVisible()
    assert "Project changed" in dialog.status.text()
    assert set(dialog._scopes.values()) == {"include"}


def test_cancel_never_saves_pending_choices(qtbot, monkeypatch, tmp_path):
    dialog, _, calls = _dialog(qtbot, monkeypatch, tmp_path)
    dialog.include_all_button.click()
    dialog.cancel_button.click()
    assert len(calls) == 1
    assert dialog.result() == QDialog.Rejected
