from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from Tools.Stats.Legacy.stats_export import _auto_format_and_write_excel


QC_SUMMARY_COLUMNS: tuple[str, ...] = (
    "Group",
    "N_subjects",
    "N_rows",
    "DV_missing_rows",
    "DV_missing_harmonics_count",
    "N_conditions",
    "N_rois",
)

QC_DISTRIBUTION_COLUMNS: tuple[str, ...] = (
    "Group",
    "ROI",
    "mean",
    "sd",
    "median",
    "IQR",
    "min",
    "max",
    "n_nonmissing",
)

QC_SUBJECT_LEVEL_COLUMNS: tuple[str, ...] = (
    "Group",
    "Subject",
    "Condition",
    "ROI",
    "DV_value",
    "Flags",
)


def _normalize_group(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_fixed_dv_table(dv_table: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(dv_table, pd.DataFrame) or dv_table.empty:
        return pd.DataFrame(columns=["subject", "condition", "roi", "value"])

    table = dv_table.copy()
    if "value" not in table.columns and "dv_value" in table.columns:
        table = table.rename(columns={"dv_value": "value"})

    for col in ("subject", "condition", "roi"):
        if col not in table.columns:
            table[col] = ""

    table["subject"] = table["subject"].astype(str)
    table["condition"] = table["condition"].astype(str)
    table["roi"] = table["roi"].astype(str)
    table["value"] = pd.to_numeric(table.get("value"), errors="coerce")
    return table[["subject", "condition", "roi", "value"]]


def build_qc_context_tables(
    *,
    dv_table: pd.DataFrame,
    subject_to_group: dict[str, str | None],
    missing_harmonics_rows: list[dict[str, object]] | None = None,
    flagged_pid_map: dict[str, list[str]] | None = None,
) -> dict[str, pd.DataFrame]:
    """Build stable QC/context report tables from the fixed-harmonic DV table."""

    fixed = _coerce_fixed_dv_table(dv_table)
    flagged_pid_map = flagged_pid_map or {}
    missing_harmonics_rows = missing_harmonics_rows or []

    if fixed.empty:
        return {
            "Summary": pd.DataFrame(columns=QC_SUMMARY_COLUMNS),
            "DV_Distribution": pd.DataFrame(columns=QC_DISTRIBUTION_COLUMNS),
            "Subject_Level": pd.DataFrame(columns=QC_SUBJECT_LEVEL_COLUMNS),
        }

    fixed = fixed.copy()
    fixed["Group"] = fixed["subject"].map(lambda pid: _normalize_group(subject_to_group.get(str(pid))))
    fixed["Flags"] = fixed["subject"].map(lambda pid: "; ".join(flagged_pid_map.get(str(pid), [])))

    missing_by_group: dict[str, int] = {}
    for row in missing_harmonics_rows:
        subject = str(row.get("subject", ""))
        group = _normalize_group(subject_to_group.get(subject))
        missing_by_group[group] = missing_by_group.get(group, 0) + 1

    summary_rows: list[dict[str, object]] = []
    for group, group_df in fixed.groupby("Group", dropna=False):
        group_name = _normalize_group(group)
        summary_rows.append(
            {
                "Group": group_name,
                "N_subjects": int(group_df["subject"].nunique()),
                "N_rows": int(len(group_df)),
                "DV_missing_rows": int(group_df["value"].isna().sum()),
                "DV_missing_harmonics_count": int(missing_by_group.get(group_name, 0)),
                "N_conditions": int(group_df["condition"].nunique()),
                "N_rois": int(group_df["roi"].nunique()),
            }
        )
    summary_df = pd.DataFrame(summary_rows).sort_values(["Group"], kind="stable")
    summary_df = summary_df.reindex(columns=QC_SUMMARY_COLUMNS)

    dist_rows: list[dict[str, object]] = []
    grouped = fixed.groupby(["Group", "roi"], dropna=False)
    for (group, roi), slice_df in grouped:
        values = pd.to_numeric(slice_df["value"], errors="coerce").dropna()
        iqr = float(values.quantile(0.75) - values.quantile(0.25)) if not values.empty else np.nan
        dist_rows.append(
            {
                "Group": _normalize_group(group),
                "ROI": str(roi),
                "mean": float(values.mean()) if not values.empty else np.nan,
                "sd": float(values.std(ddof=1)) if len(values) > 1 else np.nan,
                "median": float(values.median()) if not values.empty else np.nan,
                "IQR": iqr,
                "min": float(values.min()) if not values.empty else np.nan,
                "max": float(values.max()) if not values.empty else np.nan,
                "n_nonmissing": int(values.size),
            }
        )
    distribution_df = pd.DataFrame(dist_rows).sort_values(["Group", "ROI"], kind="stable")
    distribution_df = distribution_df.reindex(columns=QC_DISTRIBUTION_COLUMNS)

    subject_level_df = fixed.rename(
        columns={
            "subject": "Subject",
            "condition": "Condition",
            "roi": "ROI",
            "value": "DV_value",
        }
    )[["Group", "Subject", "Condition", "ROI", "DV_value", "Flags"]]
    subject_level_df = subject_level_df.sort_values(
        ["Group", "Subject", "Condition", "ROI"], kind="stable"
    )

    return {
        "Summary": summary_df,
        "DV_Distribution": distribution_df,
        "Subject_Level": subject_level_df,
    }


def export_qc_context_workbook(
    *,
    save_path: str | Path,
    dv_table: pd.DataFrame,
    subject_to_group: dict[str, str | None],
    missing_harmonics_rows: list[dict[str, object]] | None,
    flagged_pid_map: dict[str, list[str]] | None,
    log_func,
) -> Path:
    tables = build_qc_context_tables(
        dv_table=dv_table,
        subject_to_group=subject_to_group,
        missing_harmonics_rows=missing_harmonics_rows,
        flagged_pid_map=flagged_pid_map,
    )

    save_path = Path(save_path)
    with pd.ExcelWriter(save_path, engine="xlsxwriter") as writer:
        for sheet_name, table in tables.items():
            _auto_format_and_write_excel(writer, table, sheet_name, log_func)
    return save_path
