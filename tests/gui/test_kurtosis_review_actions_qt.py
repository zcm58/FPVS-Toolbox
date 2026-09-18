"""CI-only visible-widget coverage; do not run Qt locally or offscreen."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QItemSelectionModel, QModelIndex, Qt  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

from Main_App.gui.kurtosis_review_dialog import KurtosisReviewDialog  # noqa: E402
from Main_App.gui.qc_repair_support import RepairSupportDialog  # noqa: E402
from Main_App.processing.kurtosis_qc import (  # noqa: E402
    KURTOSIS_DECISION_APPROVE, KURTOSIS_DECISION_REJECT,
)
from Main_App.processing.kurtosis_review_scan import (  # noqa: E402
    KurtosisReviewDecisionReconciliation, KurtosisReviewFileResult,
    KurtosisReviewItem, KurtosisReviewScan,
)


def _item(recording, channel, score):
    valid = score is not None
    return KurtosisReviewItem(
        path=Path(f"{recording}.bdf"), participant_id=recording, recording_id=recording,
        session_id=None, session_label=None, visit_index=None, channel=channel,
        analyzed_conditions=("Faces", "Objects"), analyzed_occurrences=(),
        raw_kurtosis=3.0 if valid else None, signed_normalized_score=score,
        threshold=5.0, validity="valid" if valid else "undefined_statistic",
        validity_reason=None if valid else "Undefined kurtosis", corroborator_registry_version="test",
        corroborator_states=(), display_only_channel_health=(), signal_unit="uV",
        signal_source_sample_count=0, signal_preview=(), evidence={"channels": [{
            "channel": channel, "signed_z": score, "validity": "valid" if valid else "undefined_statistic",
            "exceeds_threshold": valid and abs(score) > 5.0,
        }]},
    )


@pytest.fixture
def dialog(qtbot, tmp_path):
    items = (
        _item("P1", "Cz", 6.0), _item("P1", "Pz", 7.0),
        _item("P2", "Oz", -8.0), _item("P2", "T7", 9.0),
        _item("P3", "Fz", 15.0), _item("P3", "C3", None),
    )
    scan = KurtosisReviewScan(tuple(KurtosisReviewFileResult(
        path=Path(f"{recording}.bdf"), participant_id=recording, recording_id=recording,
        session_id=None, session_label=None, visit_index=None, status="review_required",
        review_items=tuple(item for item in items if item.recording_id == recording),
    ) for recording in ("P1", "P2", "P3")))
    reconciliation = KurtosisReviewDecisionReconciliation(
        scan, current_receipts={"earlier": {"O1": {"decision": KURTOSIS_DECISION_REJECT, "reason": "Original note"}}},
        pending_status_by_recording={},
    )
    widget = KurtosisReviewDialog(reconciliation, project_root=tmp_path)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    for row in range(len(items)):
        _reason(widget, row).setText(f"Evidence note {row}")
    _decision(widget, 3).setCurrentIndex(2)
    return widget


def _key(dialog, row):
    item = dialog._items[row]
    return (item.recording_id.casefold(), item.channel.casefold())


def _decision(dialog, row):
    return dialog._decision_controls[_key(dialog, row)]


def _reason(dialog, row):
    return dialog._reason_controls[_key(dialog, row)]


def _select(dialog, *rows):
    model = dialog.table.selectionModel()
    model.clearSelection()
    for row in rows:
        model.select(dialog.table.model().index(row, 0),
                     QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)


def _draft(dialog):
    return tuple((_decision(dialog, row).currentData(), _reason(dialog, row).text())
                 for row in range(len(dialog._items)))


def test_bulk_button_preserves_existing_decisions_reasons_receipts_and_policy(qtbot, dialog):
    before = _draft(dialog)
    receipts = deepcopy(dialog._current_receipts)
    assert dialog.table.isRowHidden(4)
    qtbot.mouseClick(dialog.mark_all_button, Qt.MouseButton.LeftButton)
    assert [row[0] for row in _draft(dialog)] == [
        KURTOSIS_DECISION_APPROVE, KURTOSIS_DECISION_APPROVE, KURTOSIS_DECISION_APPROVE,
        KURTOSIS_DECISION_REJECT, "experimental_auto", "",
    ]
    assert [row[1] for row in _draft(dialog)] == [row[1] for row in before]
    assert dialog._current_receipts == receipts
    assert dialog.auto_checkbox.isChecked() and not dialog.auto_all_checkbox.isChecked()
    assert dialog.undo_button.isEnabled()
    qtbot.mouseClick(dialog.undo_button, Qt.MouseButton.LeftButton)
    assert _draft(dialog) == before
    assert not dialog.undo_button.isEnabled()


def test_selected_action_handles_only_selected_pending_rows_and_counts_recordings(qtbot, dialog):
    _select(dialog, 0, 2, 3, 4, 5)
    assert "2 undecided electrode(s) across 2 recording(s)" in dialog.scope_label.text()
    assert "All undecided: 3 electrode(s) across 2 recording(s)" in dialog.scope_label.text()
    assert "0 hidden rows affected" in dialog.scope_label.text()
    assert "every analyzed condition" in dialog.scope_label.text()
    dialog.selected_decision.setCurrentIndex(1)  # Keep channel.
    qtbot.mouseClick(dialog.selected_button, Qt.MouseButton.LeftButton)
    assert [_decision(dialog, row).currentData() for row in range(6)] == [
        KURTOSIS_DECISION_REJECT, "", KURTOSIS_DECISION_REJECT,
        KURTOSIS_DECISION_REJECT, "experimental_auto", "",
    ]
    assert not dialog.selected_button.isEnabled()
    assert dialog.mark_all_button.isEnabled()


def test_shown_automatic_rows_are_still_excluded_from_selected_action(qtbot, dialog):
    qtbot.mouseClick(dialog.show_auto_checkbox, Qt.MouseButton.LeftButton)
    assert not dialog.table.isRowHidden(4)
    _select(dialog, 4, 5)
    assert not dialog.selected_button.isEnabled()
    assert dialog._selected_pending_rows() == ()
    assert not _decision(dialog, 4).isEnabled()
    assert not _reason(dialog, 4).isEnabled()


@pytest.mark.parametrize("edit", ["decision", "reason", "automatic_policy", "all_automatic_policy"])
def test_manual_edit_or_policy_change_invalidates_bulk_undo(qtbot, dialog, edit):
    qtbot.mouseClick(dialog.mark_all_button, Qt.MouseButton.LeftButton)
    assert dialog.undo_button.isEnabled()
    if edit == "reason":
        control = _reason(dialog, 0)
        control.setFocus()
        qtbot.keyClicks(control, " updated")
        assert control.text().endswith(" updated")
    elif edit == "decision":
        control = _decision(dialog, 0)
        control.setFocus()
        qtbot.keyClick(control, Qt.Key.Key_Down)
        assert control.currentData() == KURTOSIS_DECISION_REJECT
    elif edit == "automatic_policy":
        qtbot.mouseClick(dialog.auto_checkbox, Qt.MouseButton.LeftButton)
    else:
        qtbot.mouseClick(dialog.auto_all_checkbox, Qt.MouseButton.LeftButton)
    assert not dialog.undo_button.isEnabled()
    assert dialog._bulk_undo == ()
    draft = _draft(dialog)
    dialog._undo_bulk_edit()
    assert _draft(dialog) == draft


def test_next_undecided_reaches_invalid_statistic_and_wraps(qtbot, dialog):
    qtbot.mouseClick(dialog.mark_all_button, Qt.MouseButton.LeftButton)
    dialog.table.setCurrentCell(3, 0)
    qtbot.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    assert dialog.table.currentRow() == 5
    assert "Undefined kurtosis" in dialog.details.toPlainText()
    _decision(dialog, 0).setCurrentIndex(0)
    qtbot.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    assert dialog.table.currentRow() == 0


def test_automatic_policy_toggle_restores_choices_and_immediately_updates_actions(qtbot, dialog):
    _select(dialog, 0, 1, 2)
    before = _draft(dialog)
    qtbot.mouseClick(dialog.auto_all_checkbox, Qt.MouseButton.LeftButton)
    assert not dialog.mark_all_button.isEnabled()
    assert not dialog.selected_button.isEnabled()
    assert dialog.table.currentRow() == 5
    assert "All undecided: 0 electrode(s) across 0 recording(s)" in dialog.scope_label.text()
    qtbot.mouseClick(dialog.auto_all_checkbox, Qt.MouseButton.LeftButton)
    assert _draft(dialog) == before
    assert dialog.mark_all_button.isEnabled()
    assert dialog.auto_checkbox.isChecked()


def test_row_navigation_updates_inspection_buttons_without_a_selection_change(dialog):
    model = dialog.table.selectionModel()
    before = model.selectedIndexes()
    model.setCurrentIndex(QModelIndex(), QItemSelectionModel.SelectionFlag.NoUpdate)
    assert not dialog.inspect_button.isEnabled()
    assert not dialog.support_button.isEnabled()
    model.setCurrentIndex(dialog.table.model().index(5, 0), QItemSelectionModel.SelectionFlag.NoUpdate)
    assert model.selectedIndexes() == before
    assert dialog.inspect_button.isEnabled() and dialog.support_button.isEnabled()


@pytest.mark.parametrize("confirmed", [False, True])
def test_repair_support_map_shows_only_retained_usable_donors_and_explicit_authority(qtbot, confirmed):
    retained = ("Cz", "Pz", "Oz", "POz", "O1", "O2", "T7", "T8")
    repairs = ("Oz", "O1")
    widget = RepairSupportDialog(
        channels=retained, repair_channels=repairs, confirmed=confirmed,
        unusable_channels=("Pz",),
    )
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    assert set(widget.map.positions) == set(retained)
    assert widget.map.repairs == set(repairs)
    assert widget.channel_combo.count() == len(repairs)
    labels = " ".join(label.text() for label in widget.findChildren(QLabel))
    assert ("Confirmed successful repairs" if confirmed else "Proposed repair scenario") in labels
    assert "not interpolation weights or proof" in labels
    for channel in repairs:
        widget.channel_combo.setCurrentText(channel)
        assert widget.map.selected == channel
        assert widget.map.donors == set(retained) - {*repairs, "Pz"}
        assert "5 usable donor(s)" in widget.details.toPlainText()
        assert "no automatic risk cutoff" in widget.details.toPlainText()
        assert "not the spline weights" in widget.details.toPlainText()
    assert not widget.map.grab().isNull()


def test_missing_retained_channel_provenance_shows_unavailable_support(qtbot):
    widget = RepairSupportDialog(channels=(), repair_channels=("Oz",), confirmed=True)
    qtbot.addWidget(widget)
    assert widget._report["status"] == "unavailable"
    assert widget.channel_combo.count() == 0
    assert widget.map.donors == set()
    assert "retained scalp-channel set is unavailable" in widget.details.toPlainText()


def test_unknown_repair_is_visible_as_incomplete_support_instead_of_silently_omitted(qtbot):
    widget = RepairSupportDialog(
        channels=("Cz", "Pz", "Oz"), repair_channels=("Oz", "EXG1"), confirmed=False,
    )
    qtbot.addWidget(widget)
    assert widget._report["status"] == "unavailable"
    assert "unavailable or incomplete" in widget.details.toPlainText()
    assert "Outside the retained scalp set: EXG1" in widget.details.toPlainText()
    assert "EXG1" not in widget.map.positions
