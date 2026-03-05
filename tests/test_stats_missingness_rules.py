from __future__ import annotations

from pathlib import Path

import pandas as pd

from Tools.Stats.PySide6.stats_missingness import (
    build_missingness_export_tables,
    compute_complete_case_subjects,
    compute_missingness,
    export_missingness_workbook,
)


def _synthetic_dv_table() -> pd.DataFrame:
    rows = [
        {"subject": "P1", "group": "G1", "condition": "A", "roi": "ROI1", "value": 1.0},
        {"subject": "P1", "group": "G1", "condition": "B", "roi": "ROI1", "value": 2.0},
        {"subject": "P2", "group": "G1", "condition": "A", "roi": "ROI1", "value": 1.5},
        {"subject": "P3", "group": "G2", "condition": "A", "roi": "ROI1", "value": 1.2},
        {"subject": "P3", "group": "G2", "condition": "B", "roi": "ROI1", "value": 2.3},
    ]
    return pd.DataFrame(rows)


def test_missingness_rules_complete_case_and_mixed() -> None:
    dv_table = _synthetic_dv_table()
    required_conditions = ["A", "B"]
    subject_to_group = {"P1": "G1", "P2": "G1", "P3": "G2"}

    mixed_missing = compute_missingness(dv_table, required_conditions, subject_to_group)
    assert len(mixed_missing) == 1
    assert mixed_missing[0]["Subject"] == "P2"
    assert mixed_missing[0]["Condition"] == "B"

    included, excluded = compute_complete_case_subjects(
        dv_table,
        required_conditions,
        subject_to_group,
    )
    assert included == ["P1", "P3"]
    assert len(excluded) == 1
    assert excluded[0]["Subject"] == "P2"
    assert excluded[0]["MissingConditions"] == "B"


def test_missingness_export_tables_schema_and_workbook(tmp_path: Path) -> None:
    mixed_missing = [
        {
            "Subject": "P2",
            "Group": "G1",
            "Condition": "B",
            "Status": "Missing",
            "Note": "Required condition cell absent; retained for mixed model.",
        }
    ]
    anova_excluded = [
        {
            "Subject": "P2",
            "Group": "G1",
            "MissingConditions": "B",
            "Reason": "Incomplete required condition cells for between-group ANOVA complete-case rule.",
        }
    ]
    summary_rows = [{"Metric": "N groups", "Value": 2}]

    tables = build_missingness_export_tables(
        mixed_missing_rows=mixed_missing,
        anova_excluded_rows=anova_excluded,
        summary_rows=summary_rows,
    )

    assert list(tables["ANOVA_ExcludedSubjects"].columns) == [
        "Subject",
        "Group",
        "MissingConditions",
        "Reason",
    ]
    assert list(tables["MixedModel_MissingCells"].columns) == [
        "Subject",
        "Group",
        "Condition",
        "Status",
        "Note",
    ]

    export_path = export_missingness_workbook(
        save_path=tmp_path / "missingness.xlsx",
        mixed_missing_rows=mixed_missing,
        anova_excluded_rows=anova_excluded,
        summary_rows=summary_rows,
        log_func=lambda _msg: None,
    )
    assert export_path.exists()
    sheets = pd.ExcelFile(export_path).sheet_names
    assert "ANOVA_ExcludedSubjects" in sheets
    assert "MixedModel_MissingCells" in sheets
    assert "Summary" in sheets
