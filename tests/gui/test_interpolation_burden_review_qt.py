"""Visible Qt coverage for review navigation and unsaved-choice protection."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QPoint, QRect, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from Main_App.gui.interpolation_burden_review_dialog import InterpolationBurdenReviewDialog  # noqa: E402
from tests.gui.ux_capture import capture, ux_capture_theme  # noqa: E402, F401
from Main_App.processing.interpolation_burden import InterpolationBurdenReviewFinding  # noqa: E402
from Main_App.processing.interpolation_burden_review import (  # noqa: E402
    InterpolationBurdenReviewBatch, InterpolationBurdenReviewItem,
)


@pytest.fixture
def dialog(qtbot, monkeypatch):
    # The general test harness suppresses message boxes; these tests exercise
    # the real discard prompt and schedule their explicit response below.
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QDialog.exec(box))
    items = tuple(InterpolationBurdenReviewItem(
        finding=InterpolationBurdenReviewFinding(
            f"P{index:03d}-visit2", str(index), ("Cz", "Pz", "Oz", "Fz"), 4, 64, 6.25, "Review burden",
        ), participant_id=f"P{index:03d}", recording_id=f"P{index:03d}-visit2",
        session_id="follow-up", session_label="Follow-up", visit_index=2,
        group_label="Control", default_scope="recording", evidence_status="new",
    ) for index in range(60))
    widget = InterpolationBurdenReviewDialog(InterpolationBurdenReviewBatch(items, 60, 0, 0, True))
    qtbot.addWidget(widget, before_close_func=lambda review: review._remember_initial_review_state())
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def test_missing_decision_focuses_and_scrolls_to_unfinished_recording(qtbot, dialog):
    for item in dialog._batch.items[:50]:
        dialog._decision_controls[item.processing_id].setCurrentIndex(1)
    assert dialog.progress_label.text() == "50 of 60 recordings ready to submit · 10 need a decision"
    dialog.apply_button.click()
    assert dialog.isVisible() and dialog.error_banner.isVisible()
    assert dialog.table.currentRow() == 50
    control = dialog._decision_controls[dialog._batch.items[50].processing_id]
    qtbot.waitUntil(control.hasFocus)
    assert dialog.table.visualRect(dialog.table.model().index(50, 7)).intersects(dialog.table.viewport().rect())
    assert dialog.result() == QDialog.DialogCode.Rejected
    capture(dialog, "interpolation-burden-unfinished-row")


def test_next_attention_wraps_and_completed_choices_still_require_apply(dialog, monkeypatch):
    for item in dialog._batch.items:
        dialog._decision_controls[item.processing_id].setCurrentIndex(1)
    for row in (2, 55):
        dialog._decision_controls[dialog._batch.items[row].processing_id].setCurrentIndex(0)
    dialog.table.setCurrentCell(2, 0)
    dialog.next_button.click()
    assert dialog.table.currentRow() == 55
    dialog.next_button.click()
    assert dialog.table.currentRow() == 2
    for row in (2, 55):
        dialog._decision_controls[dialog._batch.items[row].processing_id].setCurrentIndex(1)
    assert not dialog.next_button.isEnabled()
    assert dialog.progress_label.text() == "60 of 60 recordings ready to submit"
    assert dialog.isVisible()
    with monkeypatch.context() as patch:
        patch.setattr(dialog, "_confirm_discard", lambda: pytest.fail("Apply must not ask to discard choices"))
        dialog.apply_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert all(choice.decision == "retain" and choice.exclusion_scope == "recording"
               for choice in dialog.choices().values())


def _respond_to_discard(qtbot, response, prompts):
    def respond():
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        prompts.append(box.windowTitle())
        assert box.defaultButton().text() == "Keep reviewing"
        capture(box, "qc-discard-confirmation")
        if response == "escape":
            qtbot.keyClick(box, Qt.Key.Key_Escape)
        else:
            next(button for button in box.buttons() if button.text() == response).click()
    QTimer.singleShot(0, respond)


@pytest.mark.parametrize("exit_action", ["cancel", "escape", "close"])
def test_dirty_exit_can_keep_reviewing_or_explicitly_discard(qtbot, dialog, exit_action):
    first = dialog._batch.items[0].processing_id
    dialog._decision_controls[first].setCurrentIndex(2)
    dialog._reason_controls[first].setText("Reviewed signal evidence")
    snapshot = dialog._review_state()
    prompts = []
    _respond_to_discard(qtbot, "Keep reviewing", prompts)
    if exit_action == "cancel":
        dialog.cancel_button.click()
    elif exit_action == "escape":
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    else:
        dialog.close()
    assert dialog.isVisible()
    assert dialog._review_state() == snapshot
    assert len(prompts) == 1
    _respond_to_discard(qtbot, "Discard choices", prompts)
    dialog.close()
    assert not dialog.isVisible()
    assert len(prompts) == 2  # Window close prompts once, never twice.
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_discard_prompt_escape_keeps_choices(qtbot, dialog):
    dialog._reason_controls[dialog._batch.items[0].processing_id].setText("Draft reason")
    prompts = []
    _respond_to_discard(qtbot, "escape", prompts)
    dialog.reject()
    assert dialog.isVisible() and len(prompts) == 1


def test_unchanged_or_reverted_choices_close_without_prompt(dialog, monkeypatch):
    first = dialog._batch.items[0].processing_id
    dialog._scope_controls[first].setCurrentIndex(1)
    assert dialog._review_state() != dialog._initial_review_state
    dialog._scope_controls[first].setCurrentIndex(0)
    dialog.table.setCurrentCell(10, 0)
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: pytest.fail("No changed choices to discard"))
    dialog.close()
    assert not dialog.isVisible()


@pytest.mark.parametrize("size", [(1180, 650), (1280, 900)])
def test_attention_controls_fit_dialog(qtbot, dialog, size):
    dialog.resize(*size)
    qtbot.wait(1)
    for control in (dialog.progress_label, dialog.next_button, dialog.apply_button, dialog.cancel_button):
        bounds = QRect(control.mapTo(dialog, QPoint(0, 0)), control.size())
        assert dialog.rect().contains(bounds)
        assert control.isVisibleTo(dialog)
    capture(dialog, f"interpolation-burden-{size[0]}x{size[1]}")
