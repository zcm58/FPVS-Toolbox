from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from Tools.Stats.Legacy.stats_export import _auto_format_and_write_excel

PAIRWISE_CONTRAST_COLUMNS: tuple[str, ...] = (
    "ModelType",
    "ROI",
    "Condition",
    "GroupA",
    "GroupB",
    "Estimate",
    "SE",
    "TestStat",
    "DF",
    "P",
    "P_corrected",
    "Method",
)


def normalize_group_contrasts_table(results_df: pd.DataFrame) -> pd.DataFrame:
    """Return a stable, export-friendly pairwise-contrasts table.

    Preserves existing legacy columns and prepends the normalized schema used by
    between-group exports.
    """

    if not isinstance(results_df, pd.DataFrame):
        return pd.DataFrame(columns=PAIRWISE_CONTRAST_COLUMNS)

    if results_df.empty:
        return pd.DataFrame(columns=PAIRWISE_CONTRAST_COLUMNS)

    df = results_df.copy()

    if "condition" not in df.columns:
        df["condition"] = ""
    if "roi" not in df.columns:
        df["roi"] = ""

    corrected_source = "p_fdr_bh" if "p_fdr_bh" in df.columns else "p_value"
    method = "fdr_bh" if corrected_source == "p_fdr_bh" else "none"

    normalized = pd.DataFrame(
        {
            "ModelType": "Welch_ttest",
            "ROI": df["roi"],
            "Condition": df["condition"],
            "GroupA": df.get("group_1", ""),
            "GroupB": df.get("group_2", ""),
            "Estimate": df.get("difference", np.nan),
            "SE": np.nan,
            "TestStat": df.get("t_stat", np.nan),
            "DF": np.nan,
            "P": df.get("p_value", np.nan),
            "P_corrected": df.get(corrected_source, np.nan),
            "Method": method,
        }
    )

    normalized["ROI"] = normalized["ROI"].astype(str)
    normalized["Condition"] = normalized["Condition"].astype(str)
    normalized["GroupA"] = normalized["GroupA"].astype(str)
    normalized["GroupB"] = normalized["GroupB"].astype(str)

    normalized = normalized.sort_values(
        by=["ROI", "Condition", "GroupA", "GroupB"],
        kind="mergesort",
    ).reset_index(drop=True)

    legacy_sorted = df.sort_values(
        by=["roi", "condition", "group_1", "group_2"],
        kind="mergesort",
    ).reset_index(drop=True)

    out = pd.concat([normalized, legacy_sorted], axis=1)
    ordered_columns = list(PAIRWISE_CONTRAST_COLUMNS) + [
        col for col in out.columns if col not in PAIRWISE_CONTRAST_COLUMNS
    ]
    return out.loc[:, ordered_columns]


def export_group_contrasts_workbook(results_df: pd.DataFrame, save_path: str | Path, log_func) -> bool:
    if results_df is None or not isinstance(results_df, pd.DataFrame) or results_df.empty:
        raise ValueError("No Group Contrasts results data available to export.")

    export_table = normalize_group_contrasts_table(results_df)
    with pd.ExcelWriter(Path(save_path), engine="xlsxwriter") as writer:
        _auto_format_and_write_excel(writer, export_table, "Pairwise_Contrasts", log_func)
    return True
