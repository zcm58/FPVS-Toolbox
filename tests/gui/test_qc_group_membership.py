from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QComboBox, QHeaderView, QTableWidget

from Main_App.gui import preprocessing_qc_workflow as preflight_workflow
from Main_App.gui.frequency_domain_qc_dialog import FrequencyDomainQcReviewDialog
from Main_App.processing.preflight_qc import PreflightQcFileResult


def test_preprocessing_qc_review_table_shows_group_membership(qtbot) -> None:
    table = QTableWidget()
    qtbot.addWidget(table)
    host = SimpleNamespace(processing_files_table=table)
    result = PreflightQcFileResult(
        path=Path("P01.bdf"),
        participant_id="P01",
        load_error=None,
        raw_channel_qc={
            "excluded": True,
            "triggered_rules": ["raw_amplitude_baseline_failure"],
        },
        raw_spectral_qc=None,
        group_id="control",
    )
    labels = {"control": "Control"}

    preflight_workflow._set_preflight_table(
        host,
        ["PID", "Group", "Flag", "Reason", "Decision", "More info"],
        preflight_workflow._hard_candidate_row_values([result], labels),
        stretch_column=3,
    )
    preflight_workflow._install_hard_exclusion_details(host, [result], labels)

    assert table.horizontalHeaderItem(1).text() == "Group"
    assert table.item(0, 0).text() == "P01"
    assert table.item(0, 1).text() == "Control"
    assert table.cellWidget(0, 5).text() == "More info"


@pytest.mark.parametrize(
    (
        "headers",
        "row_values",
        "reason_column",
        "scope_column",
        "preferred_widths",
    ),
    (
        (
            (
                "Participant",
                "Recording",
                "Session / phase-at-visit",
                "Visit",
                "Group",
                "Coverage",
                "FPVS Toolbox flagged",
                "Why flagged",
                "Manual additions",
                "Final confirmed removed",
                "Scope",
            ),
            (
                "P01",
                "P01__luteal_phase",
                "Luteal Phase",
                "1",
                "BC Group",
                "Available",
                "P10",
                "Low signal / flat candidate: P10; participant fallback applies",
                "",
                "P10",
                "",
            ),
            7,
            10,
            {1: 156, 2: 184, 7: 240, 8: 140, 9: 176, 10: 176},
        ),
        (
            (
                "Participant",
                "Recording",
                "Session / phase-at-visit",
                "Visit",
                "Group",
                "Condition",
                "Usable FFT crop",
                "Project reference",
                "Reason",
                "Scope",
                "Exclude downstream",
            ),
            (
                "P01",
                "P01__follicular_phase",
                "Follicular Phase",
                "2",
                "BC Group",
                "Angry Control",
                "20 s (24 oddball cycles)",
                "120 s (144 oddball cycles)",
                "Usable crop has a different FFT grid from the project majority",
                "",
                "",
            ),
            8,
            9,
            {1: 156, 2: 184, 6: 176, 7: 176, 8: 240, 9: 176, 10: 156},
        ),
    ),
    ids=("removed-electrodes", "condition-crop"),
)
def test_repeated_session_preflight_tables_remain_compact_and_reachable(
    qtbot,
    headers,
    row_values,
    reason_column,
    scope_column,
    preferred_widths,
) -> None:
    table = QTableWidget(1, 1)
    qtbot.addWidget(table)
    table.resize(1000, 400)
    table.setColumnWidth(0, 2000)
    stale_scope = QComboBox(table)
    stale_scope.addItem("This recording")
    table.setCellWidget(0, 0, stale_scope)
    table.show()
    qtbot.wait(1)
    table.horizontalScrollBar().setValue(table.horizontalScrollBar().maximum())
    assert table.horizontalScrollBar().value() > table.horizontalScrollBar().minimum()

    host = SimpleNamespace(processing_files_table=table)
    preflight_workflow._set_preflight_table(
        host,
        headers,
        [row_values],
        stretch_column=reason_column,
        compact_rows=True,
        preferred_column_widths=preferred_widths,
    )

    assert stale_scope.isHidden()
    scope = QComboBox(table)
    scope.setObjectName("repeated_session_scope")
    scope.addItem("This recording", "recording")
    scope.addItem("Participant (all visits)", "participant")
    preflight_workflow._install_preflight_cell_widget(
        table,
        0,
        scope_column,
        scope,
    )
    qtbot.wait(1)

    scrollbar = table.horizontalScrollBar()
    assert scrollbar.value() == scrollbar.minimum()
    first_item = table.item(0, 0)
    assert table.visualItemRect(first_item).intersects(table.viewport().rect())
    assert table.horizontalHeader().sectionResizeMode(reason_column) == (
        QHeaderView.Interactive
    )
    assert table.columnWidth(reason_column) >= preferred_widths[reason_column]
    assert table.item(0, reason_column).toolTip() == row_values[reason_column]

    row_limit = 2 * table.fontMetrics().lineSpacing() + 12
    assert table.rowHeight(0) <= row_limit
    assert scope.maximumHeight() == scope.sizeHint().height()
    assert scope.height() <= scope.maximumHeight()

    for column in (reason_column, scope_column, len(headers) - 1):
        item = table.item(0, column)
        table.scrollToItem(item)
        qtbot.wait(1)
        assert table.visualItemRect(item).intersects(table.viewport().rect())


def test_frequency_domain_qc_dialog_shows_groups_in_both_tables(qtbot) -> None:
    report = {
        "participant_summaries": [
            {
                "participant_id": "P01",
                "pause_review": True,
                "max_abs_summed_bca_uv": 55.0,
                "max_condition": "Faces",
                "max_electrode": "PO8",
                "warning_cell_count": 1,
                "strong_or_hard_cell_count": 1,
                "hard_excluded_electrode_count": 0,
                "auto_participant_excluded": False,
                "pause_reasons": ["strong warning"],
            }
        ],
        "flags": [
            {
                "participant_id": "P01",
                "condition": "Faces",
                "electrode": "PO8",
                "summed_bca_uv": 55.0,
                "severity": "strong",
            }
        ],
        "auto_participant_electrode_exclusions": [],
        "auto_participant_exclusions": [],
        "manual_participant_exclusions": [],
        "thresholds": {},
    }
    dialog = FrequencyDomainQcReviewDialog(
        report,
        participant_groups={"P01": "Control"},
    )
    qtbot.addWidget(dialog)

    assert dialog.summary_table.horizontalHeaderItem(1).text() == "Group"
    assert dialog.summary_table.item(0, 1).text() == "Control"
    assert dialog.details_table.horizontalHeaderItem(1).text() == "Group"
    assert dialog.details_table.item(0, 1).text() == "Control"

