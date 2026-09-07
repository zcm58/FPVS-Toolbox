"""CI-only review-layout checks using synthetic, validator-compatible reports."""

from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QDialog, QPlainTextEdit  # noqa: E402

from Main_App.gui import frequency_domain_qc_dialog as module  # noqa: E402
from Main_App.processing.frequency_domain_qc import (  # noqa: E402
    DECISION_INTERPOLATE_CONDITION_ELECTRODE,
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
        "condition_specific_interpolation_enabled": True,
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
        "Recording" if scope == "recording" else "Participant", "Condition", "Electrode", "|Value|", "Decision",
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
    combo.setCurrentIndex(combo.findData(DECISION_INTERPOLATE_CONDITION_ELECTRODE))
    dialog._artifact_controls[first["finding_fingerprint"]].setChecked(True)
    reason.setText("Keep this specific review note")
    assert re.findall(r"\d+", dialog.progress_label.text())[:2] == ["1", "3"]

    qtbot.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    assert dialog.details_table.currentRow() == 1
    second_combo, second_reason = dialog._decision_controls[second["finding_fingerprint"]]
    assert second_combo.isVisibleTo(dialog.decision_stack)
    second_combo.setCurrentIndex(second_combo.findData(DECISION_RETAIN))
    assert not second_reason.isEnabled()
    _select_section(dialog, "roi")
    dialog.search_edit.setText("Neutral")
    assert dialog.details_table.isRowHidden(0)
    assert dialog.details_table.isRowHidden(1)
    assert not dialog.details_table.isRowHidden(2)
    third_combo, _third_reason = dialog._decision_controls[third["finding_fingerprint"]]
    third_combo.setCurrentIndex(third_combo.findData(DECISION_RETAIN))
    dialog.search_edit.setText("no matching finding")
    assert all(dialog.details_table.isRowHidden(row) for row in range(3))
    dialog.search_edit.clear()
    _select_section(dialog, "electrode")
    dialog.details_table.selectRow(0)
    assert dialog._decision_controls[first["finding_fingerprint"]] == first_controls
    assert combo.isVisibleTo(dialog.decision_stack)
    assert combo.currentData() == DECISION_INTERPOLATE_CONDITION_ELECTRODE
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


def _visual_row(dialog, fingerprint):
    table = dialog.details_table
    return next(row for row in range(table.rowCount())
                if table.item(row, 0).data(Qt.ItemDataRole.UserRole) == fingerprint)


def _visible_fingerprints(dialog):
    table = dialog.details_table
    return [table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(table.rowCount()) if not table.isRowHidden(row)]


def _select_section(dialog, section):
    tabs = dialog.finding_sections
    index = next(index for index in range(tabs.count()) if tabs.tabData(index) == section)
    tabs.setCurrentIndex(index)


def _table_fingerprints(dialog):
    return [dialog.details_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in range(dialog.details_table.rowCount())]


def _open_column_menu(qtbot, dialog, column):
    header = dialog.details_table.horizontalHeader()
    point = header.viewport().rect().center()
    point.setX(header.sectionViewportPosition(column) + header.sectionSize(column) // 2)
    qtbot.mouseClick(header.viewport(), Qt.MouseButton.LeftButton, pos=point)
    menus = [menu for menu in dialog.findChildren(module.ColumnFilterMenu) if menu.isVisible()]
    assert len(menus) == 1
    return menus[0]


def test_sorted_findings_keep_evidence_decisions_and_reasons_on_exact_fingerprints(qtbot):
    dialog, report = _dialog(qtbot)
    first, second, third = report["review_findings"]
    first_combo, first_reason = dialog._decision_controls[first["finding_fingerprint"]]
    first_combo.setCurrentIndex(first_combo.findData(DECISION_INTERPOLATE_CONDITION_ELECTRODE))
    first_reason.setText("Only this recording, condition and electrode")

    dialog._sort_findings(1, Qt.SortOrder.DescendingOrder)
    first_row = _visual_row(dialog, first["finding_fingerprint"])
    assert first_row == 2
    dialog.details_table.setCurrentCell(first_row, 0)
    assert first_combo.isVisibleTo(dialog.decision_stack)
    assert first["recording_id"] in dialog.evidence_view.toPlainText()
    assert first["condition"] in dialog.evidence_view.toPlainText()
    assert dialog.details_table.item(first_row, 4).text() == "Excl. electrode"

    dialog._set_column_filter(1, {second["condition"]})
    assert _visible_fingerprints(dialog) == [second["finding_fingerprint"]]
    second_combo, second_reason = dialog._decision_controls[second["finding_fingerprint"]]
    assert second_combo.isVisibleTo(dialog.decision_stack)
    second_combo.setCurrentIndex(second_combo.findData(DECISION_EXCLUDE_RECORDING))
    second_reason.setText("Second recording only")
    assert dialog.details_table.item(_visual_row(dialog, second["finding_fingerprint"]), 4).text() == "Excl. recording"
    assert first_reason.text() == "Only this recording, condition and electrode"

    dialog._clear_filters()
    third_combo, _third_reason = dialog._decision_controls[third["finding_fingerprint"]]
    third_combo.setCurrentIndex(third_combo.findData(DECISION_RETAIN))
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    receipts = {row["finding_fingerprint"]: row for row in dialog.review_decisions()}
    assert receipts[first["finding_fingerprint"]]["decision"] == DECISION_INTERPOLATE_CONDITION_ELECTRODE
    assert receipts[first["finding_fingerprint"]]["reason"] == "Only this recording, condition and electrode"
    assert receipts[second["finding_fingerprint"]]["decision"] == DECISION_EXCLUDE_RECORDING
    assert receipts[second["finding_fingerprint"]]["reason"] == "Second recording only"
    assert receipts[third["finding_fingerprint"]]["decision"] == DECISION_RETAIN


def test_header_filters_combine_with_search_and_clear_zero_results(qtbot, monkeypatch):
    dialog, report = _dialog(qtbot)
    first, second, _third = report["review_findings"]
    dialog._set_column_filter(0, {first["recording_id"], second["recording_id"]})
    dialog._set_column_filter(1, {second["condition"]})
    assert _visible_fingerprints(dialog) == [second["finding_fingerprint"]]
    second_combo, _ = dialog._decision_controls[second["finding_fingerprint"]]
    second_combo.setCurrentIndex(second_combo.findData(DECISION_RETAIN))
    dialog.search_edit.setText("Faces")
    assert not _visible_fingerprints(dialog)
    assert not dialog.decision_stack.isEnabled()
    assert "No matching findings" in dialog.evidence_view.toPlainText()

    warnings = []
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *_args: warnings.append(_args))
    dialog.accept()
    assert warnings and dialog.result() != QDialog.DialogCode.Accepted
    dialog._clear_filters()
    assert dialog.search_edit.text() == ""
    assert dialog._column_filters == {}
    assert len(_visible_fingerprints(dialog)) == 2
    assert dialog.decision_stack.isEnabled()
    assert second_combo.currentData() == DECISION_RETAIN


def test_header_popup_applies_checks_and_escape_keeps_previous_filter(qtbot):
    dialog, report = _dialog(qtbot)
    target = report["review_findings"][1]
    menu = _open_column_menu(qtbot, dialog, 1)
    values = {menu.values_list.item(index).text(): menu.values_list.item(index)
              for index in range(menu.values_list.count())}
    assert set(values) == {item["condition"] for item in report["review_findings"] if item["electrode"]}
    assert all(item.checkState() == Qt.CheckState.Checked for item in values.values())
    for label, item in values.items():
        item.setCheckState(Qt.CheckState.Checked if label == target["condition"] else Qt.CheckState.Unchecked)
    qtbot.mouseClick(menu.apply_button, Qt.MouseButton.LeftButton)
    assert _visible_fingerprints(dialog) == [target["finding_fingerprint"]]

    reopened = _open_column_menu(qtbot, dialog, 1)
    checked = [reopened.values_list.item(index).text()
               for index in range(reopened.values_list.count())
               if reopened.values_list.item(index).checkState() == Qt.CheckState.Checked]
    assert checked == [target["condition"]]
    reopened.search_edit.setText("Faces")
    shown = [reopened.values_list.item(index).text()
             for index in range(reopened.values_list.count())
             if not reopened.values_list.item(index).isHidden()]
    assert shown == [report["review_findings"][0]["condition"]]
    assert _visible_fingerprints(dialog) == [target["finding_fingerprint"]]
    for index in range(reopened.values_list.count()):
        reopened.values_list.item(index).setCheckState(Qt.CheckState.Checked)
    qtbot.keyClick(reopened, Qt.Key.Key_Escape)
    assert _visible_fingerprints(dialog) == [target["finding_fingerprint"]]
    assert dialog._column_filters[1] == {target["condition"]}

    clear_menu = _open_column_menu(qtbot, dialog, 1)
    clear_action = clear_menu.findChild(QAction, "column_filter_clear")
    assert clear_action is not None
    qtbot.mouseClick(clear_menu, Qt.MouseButton.LeftButton,
                     pos=clear_menu.actionGeometry(clear_action).center())
    assert len(_visible_fingerprints(dialog)) == 2


def test_header_sort_action_orders_exact_numeric_values_not_rounded_labels(qtbot):
    report, groups = _report()
    amplitudes = (2.00049, 12.0, 2.00041)
    for finding, amplitude in zip(report["review_findings"], amplitudes):
        finding.update(summed_bca_uv=-amplitude, abs_summed_bca_uv=amplitude, value_uv=amplitude)
    dialog = module.FrequencyDomainQcReviewDialog(report, participant_groups=groups)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.details_table.item(0, 3).text() == dialog.details_table.item(2, 3).text()
    menu = _open_column_menu(qtbot, dialog, 3)
    ascending = menu.findChild(QAction, "column_filter_sort_ascending")
    assert ascending is not None
    qtbot.mouseClick(menu, Qt.MouseButton.LeftButton,
                     pos=menu.actionGeometry(ascending).center())
    fingerprints = [finding["finding_fingerprint"] for finding in report["review_findings"]]
    assert _table_fingerprints(dialog) == [fingerprints[2], fingerprints[0], fingerprints[1]]
    assert _visible_fingerprints(dialog) == [fingerprints[0], fingerprints[1]]
    menu = _open_column_menu(qtbot, dialog, 3)
    descending = menu.findChild(QAction, "column_filter_sort_descending")
    assert descending is not None
    qtbot.mouseClick(menu, Qt.MouseButton.LeftButton,
                     pos=menu.actionGeometry(descending).center())
    assert _table_fingerprints(dialog) == [fingerprints[1], fingerprints[0], fingerprints[2]]
    assert _visible_fingerprints(dialog) == [fingerprints[1], fingerprints[0]]
    # Opening another filter must not claim that a different sort was applied.
    menu = _open_column_menu(qtbot, dialog, 1)
    header = dialog.details_table.horizontalHeader()
    assert header.sortIndicatorSection() == 3
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    qtbot.keyClick(menu, Qt.Key.Key_Escape)
    assert _table_fingerprints(dialog) == [fingerprints[1], fingerprints[0], fingerprints[2]]
    assert _visible_fingerprints(dialog) == [fingerprints[1], fingerprints[0]]


def test_next_undecided_uses_sorted_order_and_reveals_column_filtered_target(qtbot):
    dialog, report = _dialog(qtbot)
    first, second, third = report["review_findings"]
    dialog._sort_findings(1, Qt.SortOrder.DescendingOrder)
    assert _table_fingerprints(dialog) == [second["finding_fingerprint"], third["finding_fingerprint"], first["finding_fingerprint"]]
    assert _visible_fingerprints(dialog) == [second["finding_fingerprint"], first["finding_fingerprint"]]
    second_combo, _ = dialog._decision_controls[second["finding_fingerprint"]]
    second_combo.setCurrentIndex(second_combo.findData(DECISION_RETAIN))
    dialog._set_column_filter(1, {second["condition"]})
    dialog.search_edit.setText("Objects")
    qtbot.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    assert dialog._column_filters == {}
    assert dialog.search_edit.text() == ""
    current = dialog.details_table.currentRow()
    assert dialog.details_table.item(current, 0).data(Qt.ItemDataRole.UserRole) == third["finding_fingerprint"]
    assert dialog._decision_controls[third["finding_fingerprint"]][0].isVisibleTo(dialog.decision_stack)
    assert second_combo.currentData() == DECISION_RETAIN


def _grouped_dialog(qtbot):
    report, _ = _report()
    template = report["review_findings"][0]
    identities = [
        ("P1", "P1_visit1", "O2", "Faces"),
        ("P1", "P1_visit1", "O2", "Objects"),
        ("P1", "P1_visit1", "O2", "Neutral"),
        ("P1", "P1_visit1", "O2", "Faces"),
        ("P1", "P1_visit2", "O2", "Faces"),
        ("P2", "P2_visit1", "O2", "Faces"),
        ("P1", "P1_visit1", "CP4", "Faces"),
        ("P1", "P1_visit1", "", "Faces"),
    ]
    findings = []
    for index, (participant, recording, electrode, condition) in enumerate(identities):
        findings.append({
            **template,
            "finding_fingerprint": f"{index + 1:064x}",
            "participant_id": participant,
            "recording_id": recording,
            "electrode": electrode,
            "condition": condition,
            "roi": "Occipital" if not electrode else "",
            "finding_type": ("cohort_relative_summed_bca_context"
                             if index in (3, 7) else "absolute_summed_bca"),
        })
    assignments = [
        {"participant_id": participant, "recording_id": recording,
         "group_id": "control", "session_id": recording, "visit_index": 1}
        for participant, recording in (("P1", "P1_visit1"), ("P1", "P1_visit2"), ("P2", "P2_visit1"))
    ]
    report.update(
        review_findings=findings, flags=findings, subjects=["P1", "P2"],
        recording_assignments=assignments, recording_summaries=[],
        review_decisions=[], review_prefill_decisions=[], cohort_relative_rows=[],
    )
    dialog = module.FrequencyDomainQcReviewDialog(report, participant_groups={"P1": "Control", "P2": "Control"})
    qtbot.addWidget(dialog)
    dialog.resize(1180, 780)
    dialog.show()
    qtbot.waitExposed(dialog)
    return dialog, findings


def _select_electrode_group(dialog, key=("P1", "P1_visit1", "O2")):
    combo = dialog.electrode_group_combo
    index = combo.findData(key)
    assert index >= 0
    combo.setCurrentIndex(index)


def _decision_state(dialog, findings):
    return {
        item["finding_fingerprint"]: (
            dialog._decision_controls[item["finding_fingerprint"]][0].currentData(),
            dialog._decision_controls[item["finding_fingerprint"]][1].text(),
        )
        for item in findings
    }


def test_roi_section_is_separate_and_next_undecided_crosses_sections(qtbot):
    dialog, findings = _grouped_dialog(qtbot)
    tabs = dialog.finding_sections
    assert [tabs.tabData(index) for index in range(tabs.count())] == ["electrode", "roi"]
    assert tabs.tabData(tabs.currentIndex()) == "electrode"
    assert _visible_fingerprints(dialog) == [item["finding_fingerprint"] for item in findings[:-1]]
    assert dialog.details_table.horizontalHeaderItem(2).text() == "Electrode"
    _select_section(dialog, "roi")
    assert _visible_fingerprints(dialog) == [findings[-1]["finding_fingerprint"]]
    assert dialog.details_table.horizontalHeaderItem(2).text() == "ROI"
    assert not dialog.bulk_retain_button.isEnabled()
    assert not dialog.bulk_interpolate_button.isEnabled()
    roi_combo, _ = dialog._decision_controls[findings[-1]["finding_fingerprint"]]
    assert roi_combo.findData(DECISION_INTERPOLATE_CONDITION_ELECTRODE) == -1

    _select_section(dialog, "electrode")
    for finding in findings[:-1]:
        combo, _ = dialog._decision_controls[finding["finding_fingerprint"]]
        combo.setCurrentIndex(combo.findData(DECISION_RETAIN))
    _select_electrode_group(dialog)
    dialog._set_column_filter(1, {"Objects"})
    dialog.search_edit.setText("Objects")
    qtbot.mouseClick(dialog.next_button, Qt.MouseButton.LeftButton)
    assert tabs.tabData(tabs.currentIndex()) == "roi"
    assert dialog.search_edit.text() == ""
    assert dialog._column_filters == {}
    assert dialog.electrode_group_combo.currentData() is None
    assert _visible_fingerprints(dialog) == [findings[-1]["finding_fingerprint"]]
    assert roi_combo.isVisibleTo(dialog.decision_stack)
    assert not roi_combo.currentData()


def test_roi_only_review_opens_its_nonempty_section(qtbot):
    report, groups = _report()
    roi = report["review_findings"][-1]
    report.update(review_findings=[roi], flags=[roi], review_decisions=[], review_prefill_decisions=[])
    dialog = module.FrequencyDomainQcReviewDialog(report, participant_groups=groups)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert dialog.finding_sections.tabData(dialog.finding_sections.currentIndex()) == "roi"
    assert _visible_fingerprints(dialog) == [roi["finding_fingerprint"]]
    assert dialog.details_table.horizontalHeaderItem(2).text() == "ROI"
    assert not dialog.bulk_retain_button.isEnabled()
    assert not dialog.bulk_interpolate_button.isEnabled()


def test_electrode_group_applies_to_filtered_flags_and_exact_receipts_only(qtbot):
    dialog, findings = _grouped_dialog(qtbot)
    targets = findings[:4]
    first_combo, first_reason = dialog._decision_controls[targets[0]["finding_fingerprint"]]
    first_combo.setCurrentIndex(first_combo.findData(DECISION_INTERPOLATE_CONDITION_ELECTRODE))
    first_reason.setText("Face-specific note")
    _select_electrode_group(dialog)
    assert _visible_fingerprints(dialog) == [item["finding_fingerprint"] for item in targets]
    assert dialog.detail_tabs.currentWidget() is dialog.bulk_panel
    assert "4 flags" in dialog.bulk_scope_label.text()
    scope = dialog.bulk_scope_view.toPlainText()
    for text in ("P1", "P1_visit1", "O2", "3 conditions", "Faces", "Objects", "Neutral"):
        assert text in scope
    dialog._sort_findings(1, Qt.SortOrder.DescendingOrder)
    dialog._set_column_filter(1, {"Objects"})
    dialog.search_edit.setText("Objects")
    assert _visible_fingerprints(dialog) == [targets[1]["finding_fingerprint"]]
    dialog.detail_tabs.setCurrentWidget(dialog.bulk_panel)
    assert not dialog.bulk_interpolate_button.isEnabled()
    dialog.bulk_artifact_check.setChecked(True)
    qtbot.mouseClick(dialog.bulk_interpolate_button, Qt.MouseButton.LeftButton)
    for finding in targets:
        combo, _ = dialog._decision_controls[finding["finding_fingerprint"]]
        assert combo.currentData() == DECISION_INTERPOLATE_CONDITION_ELECTRODE
    assert first_reason.text() == "Face-specific note"
    for finding in findings[4:]:
        combo, reason = dialog._decision_controls[finding["finding_fingerprint"]]
        assert not combo.currentData()
        assert reason.text() == ""
        combo.setCurrentIndex(combo.findData(DECISION_RETAIN))
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    receipts = {receipt["finding_fingerprint"]: receipt for receipt in dialog.review_decisions()}
    assert set(receipts) == {finding["finding_fingerprint"] for finding in findings}
    excluded = [receipt for receipt in receipts.values()
                if receipt["decision"] == DECISION_INTERPOLATE_CONDITION_ELECTRODE]
    assert {receipt["finding_fingerprint"] for receipt in excluded} == {
        finding["finding_fingerprint"] for finding in targets
    }
    assert {(receipt["participant_id"], receipt["recording_id"], receipt["electrode"])
            for receipt in excluded} == {("P1", "P1_visit1", "O2")}
    assert {receipt["decision_scope"] for receipt in excluded} == {"recording_condition_electrode"}
    assert receipts[targets[0]["finding_fingerprint"]]["reason"] == "Face-specific note"


def test_selected_electrode_group_remains_actionable_when_search_hides_every_flag(qtbot):
    dialog, findings = _grouped_dialog(qtbot)
    _select_electrode_group(dialog)
    dialog.search_edit.setText("no matching finding")
    assert not _visible_fingerprints(dialog)
    assert dialog.bulk_retain_button.isEnabled()
    assert not dialog.bulk_interpolate_button.isEnabled()
    dialog.bulk_artifact_check.setChecked(True)
    assert dialog.bulk_interpolate_button.isEnabled()
    dialog.detail_tabs.setCurrentWidget(dialog.bulk_panel)
    qtbot.mouseClick(dialog.bulk_retain_button, Qt.MouseButton.LeftButton)
    assert all(decision == DECISION_RETAIN for decision, _ in _decision_state(dialog, findings[:4]).values())
    assert all(not decision for decision, _ in _decision_state(dialog, findings[4:]).values())


@pytest.mark.parametrize("manual_edit", ["decision", "reason"])
def test_electrode_group_undo_restores_choices_and_manual_edits_invalidate_undo(qtbot, manual_edit):
    dialog, findings = _grouped_dialog(qtbot)
    first_combo, first_reason = dialog._decision_controls[findings[0]["finding_fingerprint"]]
    first_combo.setCurrentIndex(first_combo.findData(DECISION_INTERPOLATE_CONDITION_ELECTRODE))
    first_reason.setText("Existing reason")
    second_combo, second_reason = dialog._decision_controls[findings[1]["finding_fingerprint"]]
    second_combo.setCurrentIndex(second_combo.findData(DECISION_RETAIN))
    before = _decision_state(dialog, findings)
    _select_electrode_group(dialog)
    assert not dialog.bulk_undo_button.isEnabled()
    dialog.bulk_artifact_check.setChecked(True)
    qtbot.mouseClick(dialog.bulk_interpolate_button, Qt.MouseButton.LeftButton)
    assert dialog.bulk_undo_button.isEnabled()
    qtbot.mouseClick(dialog.bulk_undo_button, Qt.MouseButton.LeftButton)
    assert _decision_state(dialog, findings) == before
    assert not dialog.bulk_undo_button.isEnabled()

    qtbot.mouseClick(dialog.bulk_interpolate_button, Qt.MouseButton.LeftButton)
    assert dialog.bulk_undo_button.isEnabled()
    if manual_edit == "decision":
        second_combo.setCurrentIndex(second_combo.findData(DECISION_RETAIN))
    else:
        second_reason.setText("Individual follow-up reason")
    assert not dialog.bulk_undo_button.isEnabled()
    after_manual_edit = _decision_state(dialog, findings)
    qtbot.mouseClick(dialog.bulk_undo_button, Qt.MouseButton.LeftButton)
    assert _decision_state(dialog, findings) == after_manual_edit
    assert first_reason.text() == "Existing reason"


@pytest.mark.parametrize("enabled", [False, True])
def test_experimental_setting_controls_only_condition_electrode_repair(qtbot, enabled):
    report, groups = _report()
    report["condition_specific_interpolation_enabled"] = enabled
    dialog = module.FrequencyDomainQcReviewDialog(report, participant_groups=groups)
    qtbot.addWidget(dialog)
    for finding in report["review_findings"]:
        combo, _ = dialog._decision_controls[finding["finding_fingerprint"]]
        offered = combo.findData(DECISION_INTERPOLATE_CONDITION_ELECTRODE) >= 0
        assert offered is (enabled and bool(finding["electrode"]))
        assert combo.findData("exclude_condition_electrode") == -1
        assert combo.findData("exclude_condition_roi") == -1
        assert combo.findData("exclude_condition") >= 0
        assert combo.findData("exclude_recording") >= 0
        assert combo.findData("exclude_participant") >= 0
    assert dialog.bulk_interpolate_button.isHidden() is (not enabled)


def test_manual_repair_requires_new_artifact_confirmation_and_reason_is_optional(qtbot, monkeypatch):
    dialog, report = _dialog(qtbot)
    warnings = []
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *_args: warnings.append(_args))
    for combo, _reason in dialog._decision_controls.values():
        combo.setCurrentIndex(combo.findData(DECISION_RETAIN))
    first = report["review_findings"][0]
    combo, reason = dialog._decision_controls[first["finding_fingerprint"]]
    combo.setCurrentIndex(combo.findData(DECISION_INTERPOLATE_CONDITION_ELECTRODE))
    confirmation = dialog._artifact_controls[first["finding_fingerprint"]]
    assert not confirmation.isChecked()
    dialog.accept()
    assert warnings
    assert not dialog.review_decisions()
    assert dialog.result() != QDialog.DialogCode.Accepted
    confirmation.setChecked(True)
    combo.setCurrentIndex(combo.findData(DECISION_RETAIN))
    combo.setCurrentIndex(combo.findData(DECISION_INTERPOLATE_CONDITION_ELECTRODE))
    assert not confirmation.isChecked()
    confirmation.setChecked(True)
    assert reason.text() == ""
    dialog.accept()
    receipt = next(row for row in dialog.review_decisions()
                   if row["finding_fingerprint"] == first["finding_fingerprint"])
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert receipt["artifact_confirmed"] is True
    assert receipt["reason"] == "No reason provided"


def test_bulk_artifact_confirmation_cannot_carry_over_to_another_recording(qtbot):
    dialog, _findings = _grouped_dialog(qtbot)
    _select_electrode_group(dialog)
    dialog.bulk_artifact_check.setChecked(True)
    assert dialog.bulk_interpolate_button.isEnabled()
    _select_electrode_group(dialog, ("P1", "P1_visit2", "O2"))
    assert not dialog.bulk_artifact_check.isChecked()
    assert not dialog.bulk_interpolate_button.isEnabled()
