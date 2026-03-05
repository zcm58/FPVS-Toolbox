"""Provide the stats missingness features for the Stats PySide6 statistics workflow."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from Tools.Stats.Legacy.stats_export import _auto_format_and_write_excel


def _normalize_group(value: Any) -> str:
    """Handle the normalize group step for the Stats PySide6 workflow."""
    if value is None:
        return ""
    text = str(value).strip()
    return text


def compute_missingness(
    dv_table: pd.DataFrame,
    required_conditions: list[str],
    subject_to_group: dict[str, str | None],
) -> list[dict[str, str]]:
    """Return missing subject×condition cells for mixed-model reporting."""
    if dv_table is None or dv_table.empty:
        return []

    required = [str(cond) for cond in required_conditions]
    if not required:
        return []

    working = dv_table.copy()
    if "value" in working.columns:
        working = working.loc[working["value"].notna()].copy()

    missing_rows: list[dict[str, str]] = []
    subjects = sorted({str(subject) for subject in working.get("subject", pd.Series(dtype=str)).dropna().tolist()})

    for subject in subjects:
        subject_rows = working.loc[working["subject"].astype(str) == subject]
        present = {str(cond) for cond in subject_rows.get("condition", pd.Series(dtype=str)).dropna().tolist()}
        group_name = _normalize_group(subject_to_group.get(subject))
        for condition in required:
            if condition in present:
                continue
            missing_rows.append(
                {
                    "Subject": subject,
                    "Group": group_name,
                    "Condition": condition,
                    "Status": "Missing",
                    "Note": "Required condition cell absent; retained for mixed model.",
                }
            )

    return missing_rows


def compute_complete_case_subjects(
    dv_table: pd.DataFrame,
    required_conditions: list[str],
    subject_to_group: dict[str, str | None],
) -> tuple[list[str], list[dict[str, str]]]:
    """Return included complete-case subjects and explicit ANOVA exclusions."""
    missing_rows = compute_missingness(
        dv_table=dv_table,
        required_conditions=required_conditions,
        subject_to_group=subject_to_group,
    )
    missing_map: dict[str, list[str]] = {}
    for row in missing_rows:
        missing_map.setdefault(row["Subject"], []).append(row["Condition"])

    subjects = sorted({str(subject) for subject in dv_table.get("subject", pd.Series(dtype=str)).dropna().tolist()})
    included = [subject for subject in subjects if subject not in missing_map]

    excluded_rows: list[dict[str, str]] = []
    for subject in sorted(missing_map):
        missing_conditions = sorted(set(missing_map[subject]))
        excluded_rows.append(
            {
                "Subject": subject,
                "Group": _normalize_group(subject_to_group.get(subject)),
                "MissingConditions": ", ".join(missing_conditions),
                "Reason": "Incomplete required condition cells for between-group ANOVA complete-case rule.",
            }
        )

    return included, excluded_rows


def build_missingness_export_tables(
    *,
    mixed_missing_rows: list[dict[str, str]],
    anova_excluded_rows: list[dict[str, str]],
    summary_rows: list[dict[str, Any]] | None = None,
) -> dict[str, pd.DataFrame]:
    """Handle the build missingness export tables step for the Stats PySide6 workflow."""
    summary_rows = summary_rows or []
    return {
        "ANOVA_ExcludedSubjects": pd.DataFrame(
            anova_excluded_rows,
            columns=["Subject", "Group", "MissingConditions", "Reason"],
        ),
        "MixedModel_MissingCells": pd.DataFrame(
            mixed_missing_rows,
            columns=["Subject", "Group", "Condition", "Status", "Note"],
        ),
        "Summary": pd.DataFrame(summary_rows),
    }


def export_missingness_workbook(
    *,
    save_path: str | Path,
    mixed_missing_rows: list[dict[str, str]],
    anova_excluded_rows: list[dict[str, str]],
    summary_rows: list[dict[str, Any]] | None,
    log_func,
) -> Path:
    """Handle the export missingness workbook step for the Stats PySide6 workflow."""
    tables = build_missingness_export_tables(
        mixed_missing_rows=mixed_missing_rows,
        anova_excluded_rows=anova_excluded_rows,
        summary_rows=summary_rows,
    )
    save_path = Path(save_path)
    with pd.ExcelWriter(save_path, engine="xlsxwriter") as writer:
        for sheet_name, table in tables.items():
            _auto_format_and_write_excel(writer, table, sheet_name, log_func)
    return save_path
