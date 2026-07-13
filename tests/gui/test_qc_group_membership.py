from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QTableWidget

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
        ["PID", "Group", "Flag", "Reason", "More info"],
        preflight_workflow._hard_candidate_row_values([result], labels),
        stretch_column=3,
    )
    preflight_workflow._install_hard_exclusion_details(host, [result], labels)

    assert table.horizontalHeaderItem(1).text() == "Group"
    assert table.item(0, 0).text() == "P01"
    assert table.item(0, 1).text() == "Control"
    assert table.cellWidget(0, 4).text() == "More info"


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

