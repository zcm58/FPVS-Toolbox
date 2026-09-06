"""CI-only review-layout checks using synthetic, validator-compatible reports."""

from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QDialog, QPlainTextEdit  # noqa: E402

from Main_App.gui import frequency_domain_qc_dialog as module  # noqa: E402
from Main_App.processing.frequency_domain_qc import (  # noqa: E402
    DECISION_EXCLUDE_CONDITION_ELECTRODE,
    DECISION_EXCLUDE_RECORDING,
    DECISION_RETAIN,
)


def _report(scope="recording"):
    findings, summaries, assignments = [], [], []
    groups = {}
    for index, condition in enumerate(("Faces", "Objects", "Neutral")):
        participant = f"P{index + 1:02d}_" + "long_participant_identifier_" * 5
        recording = participant + "__long_recording_session_identifier_" * 4
        identity = {
            "participant_id": participant,
            "recording_id": recording if scope == "recording" else "",
            "session_id": "visit_2",
            "session_label": "A long session label with detailed phase information",
            "visit_index": 2,
            "group_id": "control",
        }
        groups[participant] = "Control group with a descriptive study label"
        assignments.append(identity)
        summaries.append({**identity, "pause_review": True,
                          "max_abs_summed_bca_uv": 55.125,
                          "warning_cell_count": 1, "extreme_electrode_count": 0})
        findings.append({
            **identity,
            "finding_fingerprint": f"{index + 1:064x}",
            "condition": condition + "_long_condition_identifier_" * 5,
            "electrode": "PO8" if index < 2 else "",
            "roi": "Occipital_ROI_with_a_long_descriptive_name" if index == 2 else "",
            "finding_type": "absolute_summed_bca" if index < 2 else "cohort_relative_summed_bca_context",
            "metric": "sum_absolute_roi_mean_harmonics",
            "summed_bca_uv": -55.125,
            "abs_summed_bca_uv": 55.125,
            "value_uv": 55.125,
            "severity": "strong",
            "band_crossed": "strong warning",
            "selected_harmonics_hz": [1.2, 2.4, 3.6, 4.8, 7.2, 8.4, 9.6, 10.8],
            "selected_harmonic_count": 8,
            "expected_analyzed_oddball_cycles": 144,
            "analyzed_duration_seconds": 120.,
            "independent_qc": ["Interpolation burden 1/64", "Kurtosis review current"],
            "independent_qc_status": "available",
        })
    prior = {"finding_fingerprint": findings[0]["finding_fingerprint"],
             "decision": "exclude_recording" if scope == "recording" else "exclude_participant",
             "reason": "Previous reason must remain context only"}
    return {
        "identity_scope": scope,
        "analysis_fingerprint": "f" * 64,
        "screening_enabled": True,
        "subjects": list(groups),
        "recording_assignments": assignments if scope == "recording" else [],
        "recording_summaries": summaries if scope == "recording" else [],
        "participant_summaries": summaries if scope == "participant" else [],
        "review_findings": findings,
        "flags": findings,
        "review_decisions": [prior],
        "review_prefill_decisions": [prior],
        "cohort_relative_rows": [{
            **assignments[1], "condition": findings[1]["condition"], "roi": "Occipital",
            "status": "unavailable_by_method", "reason_codes": ["not_enough_eligible_harmonics"],
        }],
        "thresholds": {},
    }, groups


def _dialog(qtbot, scope="recording", size=(1180, 780)):
    report, groups = _report(scope)
    dialog = module.FrequencyDomainQcReviewDialog(report, participant_groups=groups)
    qtbot.addWidget(dialog)
    dialog.resize(*size)
    dialog.show()
    qtbot.waitExposed(dialog)
    return dialog, report


def _context(dialog):
    page = dialog.detail_tabs.widget(1)
    viewer = page if isinstance(page, QPlainTextEdit) else page.findChild(QPlainTextEdit)
    assert viewer is not None
    return viewer.toPlainText()


@pytest.mark.parametrize("size", [(1000, 650), (1180, 780)])
@pytest.mark.parametrize("scope", ["participant", "recording"])
def test_compact_review_fits_without_horizontal_table_scrolling(qtbot, size, scope):
    dialog, _report_value = _dialog(qtbot, scope, size)
    table = dialog.details_table
    assert [table.horizontalHeaderItem(index).text() for index in range(table.columnCount())] == [
        "Recording" if scope == "recording" else "Participant", "Condition", "Electrode / ROI", "|Value|", "Decision",
    ]
    assert dialog.width() == size[0]
    assert dialog.height() == size[1]
    assert table.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert table.horizontalScrollBar().maximum() == 0
    assert table.horizontalHeader().length() <= table.viewport().width()
    assert dialog.detail_tabs.tabText(0) == "Finding evidence"
    assert dialog.detail_tabs.tabText(1) == "Review context"
    for column in (0, 4):
        assert table.visualItemRect(table.item(0, column)).intersects(table.viewport().rect())
    assert not hasattr(dialog, "summary_table")


def test_decisions_and_optional_reasons_survive_navigation_and_filtering(qtbot):
    dialog, report = _dialog(qtbot)
    first, second, third = report["review_findings"]
    first_controls = dialog._decision_controls[first["finding_fingerprint"]]
    combo, reason = first_controls
    combo.setCurrentIndex(combo.findData(DECISION_EXCLUDE_CONDITION_ELECTRODE))
    reason.setText("Keep this specific review note")
    assert re.findall(r"\d+", dialog.progress_label.text())[:2] == ["1", "3"]

    qtbot.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    assert dialog.details_table.currentRow() == 1
    second_combo, second_reason = dialog._decision_controls[second["finding_fingerprint"]]
    assert second_combo.isVisibleTo(dialog.decision_stack)
    second_combo.setCurrentIndex(second_combo.findData(DECISION_RETAIN))
    assert not second_reason.isEnabled()
    dialog.search_edit.setText("Neutral")
    assert dialog.details_table.isRowHidden(0)
    assert dialog.details_table.isRowHidden(1)
    assert not dialog.details_table.isRowHidden(2)
    third_combo, _third_reason = dialog._decision_controls[third["finding_fingerprint"]]
    third_combo.setCurrentIndex(third_combo.findData(DECISION_RETAIN))
    dialog.search_edit.setText("no matching finding")
    assert all(dialog.details_table.isRowHidden(row) for row in range(3))
    dialog.search_edit.clear()
    dialog.details_table.selectRow(0)
    assert dialog._decision_controls[first["finding_fingerprint"]] == first_controls
    assert combo.isVisibleTo(dialog.decision_stack)
    assert combo.currentData() == DECISION_EXCLUDE_CONDITION_ELECTRODE
    assert reason.text() == "Keep this specific review note"
    assert re.findall(r"\d+", dialog.progress_label.text())[:2] == ["3", "3"]
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    receipts = {row["finding_fingerprint"]: row for row in dialog.review_decisions()}
    assert receipts[first["finding_fingerprint"]]["reason"] == "Keep this specific review note"
    assert receipts[second["finding_fingerprint"]]["decision"] == DECISION_RETAIN


def test_prior_decisions_are_context_only_and_missing_decisions_still_block(qtbot, monkeypatch):
    dialog, report = _dialog(qtbot)
    warnings = []
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *_args: warnings.append(_args))
    for combo, reason in dialog._decision_controls.values():
        assert combo.currentData() == ""
        assert reason.text() == ""
        assert not reason.isEnabled()
    first_combo, first_reason = dialog._decision_controls[report["review_findings"][0]["finding_fingerprint"]]
    assert "Previous reason must remain context only" in first_combo.toolTip()
    assert first_reason.text() == ""
    dialog.accept()
    assert warnings and dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.review_decisions() == ()


def test_blank_reason_accepted_without_changing_recording_scope(qtbot):
    dialog, report = _dialog(qtbot)
    first = report["review_findings"][0]
    for fingerprint, (combo, reason) in dialog._decision_controls.items():
        decision = DECISION_EXCLUDE_RECORDING if fingerprint == first["finding_fingerprint"] else DECISION_RETAIN
        combo.setCurrentIndex(combo.findData(decision))
        assert reason.text() == ""
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    receipts = {item["finding_fingerprint"]: item for item in dialog.review_decisions()}
    excluded = receipts[first["finding_fingerprint"]]
    assert excluded["decision"] == DECISION_EXCLUDE_RECORDING
    assert excluded["recording_id"] == first["recording_id"]
    assert excluded["reason"] == "No reason provided"
    assert dialog.manual_recording_reasons() == {first["recording_id"]: "No reason provided"}


def test_next_undecided_reveals_a_filtered_finding_without_changing_choices(qtbot):
    dialog, report = _dialog(qtbot)
    first, second, _third = report["review_findings"]
    combo, _reason = dialog._decision_controls[first["finding_fingerprint"]]
    combo.setCurrentIndex(combo.findData(DECISION_RETAIN))
    dialog.search_edit.setText("Faces")
    assert dialog.details_table.isRowHidden(1)
    qtbot.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    assert dialog.search_edit.text() == ""
    assert dialog.details_table.currentRow() == 1
    assert dialog.details_table.item(1, 0).data(Qt.ItemDataRole.UserRole) == second["finding_fingerprint"]
    assert combo.currentData() == DECISION_RETAIN
    assert dialog._decision_controls[second["finding_fingerprint"]][0].currentData() == ""


def test_evidence_preserves_full_identifiers_values_groups_and_unavailable_context(qtbot):
    dialog, report = _dialog(qtbot)
    first = report["review_findings"][0]
    dialog.details_table.selectRow(0)
    evidence = dialog.evidence_view.toPlainText()
    for text in (first["participant_id"], first["recording_id"], first["condition"],
                 "Control group with a descriptive study label", "-55.125", "55.125",
                 "144", "120", "10.8", "Interpolation burden 1/64", "visit 2"):
        assert text in evidence
    context = _context(dialog)
    assert "Control group with a descriptive study label" in context
    assert report["review_findings"][1]["recording_id"] in context
    assert "not_enough_eligible_harmonics" in context
    assert "unavailable" in context.lower()
