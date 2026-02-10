from __future__ import annotations

from pathlib import Path

import pandas as pd

from Tools.Stats.PySide6.stats_qc_reports import (
    QC_DISTRIBUTION_COLUMNS,
    QC_SUBJECT_LEVEL_COLUMNS,
    QC_SUMMARY_COLUMNS,
    build_qc_context_tables,
    export_qc_context_workbook,
)


def _fixed_dv_df() -> pd.DataFrame:
    rows = [
        {"subject": "P1", "condition": "A", "roi": "ROI1", "dv_value": 1.0},
        {"subject": "P1", "condition": "B", "roi": "ROI1", "dv_value": 2.0},
        {"subject": "P2", "condition": "A", "roi": "ROI1", "dv_value": 3.0},
        {"subject": "P2", "condition": "B", "roi": "ROI1", "dv_value": None},
        {"subject": "P3", "condition": "A", "roi": "ROI1", "dv_value": 4.0},
        {"subject": "P3", "condition": "B", "roi": "ROI1", "dv_value": 5.0},
    ]
    return pd.DataFrame(rows)


def test_build_qc_context_tables_schema_and_stats() -> None:
    dv_df = _fixed_dv_df()
    subject_to_group = {"P1": "G1", "P2": "G1", "P3": "G2"}
    missing_harmonics = [
        {"subject": "P2", "condition": "B", "roi": "ROI1", "missing_hz": [2.4]},
        {"subject": "P3", "condition": "A", "roi": "ROI1", "missing_hz": [2.4]},
    ]

    tables = build_qc_context_tables(
        dv_table=dv_df,
        subject_to_group=subject_to_group,
        missing_harmonics_rows=missing_harmonics,
        flagged_pid_map={"P2": ["DV_NONFINITE"]},
    )

    assert list(tables["Summary"].columns) == list(QC_SUMMARY_COLUMNS)
    assert list(tables["DV_Distribution"].columns) == list(QC_DISTRIBUTION_COLUMNS)
    assert list(tables["Subject_Level"].columns) == list(QC_SUBJECT_LEVEL_COLUMNS)

    summary = tables["Summary"].set_index("Group")
    assert int(summary.loc["G1", "N_subjects"]) == 2
    assert int(summary.loc["G1", "DV_missing_rows"]) == 1
    assert int(summary.loc["G1", "DV_missing_harmonics_count"]) == 1
    assert int(summary.loc["G2", "DV_missing_harmonics_count"]) == 1

    dist = tables["DV_Distribution"]
    g1 = dist[(dist["Group"] == "G1") & (dist["ROI"] == "ROI1")].iloc[0]
    assert int(g1["n_nonmissing"]) == 3
    assert float(g1["median"]) == 2.0

    subject_level = tables["Subject_Level"]
    flagged_row = subject_level[(subject_level["Subject"] == "P2") & (subject_level["Condition"] == "A")].iloc[0]
    assert flagged_row["Flags"] == "DV_NONFINITE"


def test_export_qc_context_workbook(tmp_path: Path) -> None:
    dv_df = _fixed_dv_df()
    export_path = export_qc_context_workbook(
        save_path=tmp_path / "QC_Context_ByGroup.xlsx",
        dv_table=dv_df,
        subject_to_group={"P1": "G1", "P2": "G1", "P3": "G2"},
        missing_harmonics_rows=[],
        flagged_pid_map={},
        log_func=lambda _msg: None,
    )

    assert export_path.exists()
    sheets = pd.ExcelFile(export_path).sheet_names
    assert sheets == ["Summary", "DV_Distribution", "Subject_Level"]
