"""Formatting helpers for Stats Excel exports.

This module applies output-only formatting adjustments after legacy exports.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import openpyxl
import pandas as pd

logger = logging.getLogger(__name__)

RM_ANOVA_P_COLUMNS: tuple[str, ...] = ("Pr > F", "Pr > F (GG)", "Pr > F (HF)")
SCIENTIFIC_P_THRESHOLD = 0.001
SCIENTIFIC_FMT = "0.00E+00"
DEFAULT_P_FMT = "0.0000"


def log_rm_anova_p_minima(anova_df: pd.DataFrame) -> None:
    """Emit diagnostic stats confirming whether tiny p-values are real zeros or display artifacts."""

    def _series_metrics(column: str) -> tuple[float | None, bool]:
        if column not in anova_df.columns:
            return None, False
        numeric = pd.to_numeric(anova_df[column], errors="coerce")
        exact_zero = bool((numeric == 0.0).fillna(False).any())
        positives = numeric[(numeric > 0.0) & numeric.notna()]
        if positives.empty:
            return None, exact_zero
        return float(positives.min()), exact_zero

    min_p_unc, any_exact_zero_unc = _series_metrics("Pr > F")
    min_p_gg, any_exact_zero_gg = _series_metrics("Pr > F (GG)")
    logger.info(
        "rm_anova_p_min",
        extra={
            "min_p_unc": min_p_unc,
            "min_p_gg": min_p_gg,
            "any_exact_zero_unc": any_exact_zero_unc,
            "any_exact_zero_gg": any_exact_zero_gg,
        },
    )


def apply_rm_anova_pvalue_number_formats(
    workbook_path: str | Path,
    *,
    sheet_name: str = "RM-ANOVA Table",
) -> None:
    """Apply scientific formatting for tiny RM-ANOVA p-values in Excel output."""

    path = Path(workbook_path)
    workbook = openpyxl.load_workbook(path)
    try:
        if sheet_name not in workbook.sheetnames:
            logger.info(
                "rm_anova_sheet_not_found_for_formatting",
                extra={"sheet_name": sheet_name, "path": str(path)},
            )
            return
        worksheet = workbook[sheet_name]
        headers = {
            str(cell.value).strip(): idx
            for idx, cell in enumerate(worksheet[1], start=1)
            if isinstance(cell.value, str)
        }
        target_indices = [headers[col] for col in RM_ANOVA_P_COLUMNS if col in headers]
        if not target_indices:
            return
        for row_idx in range(2, worksheet.max_row + 1):
            for col_idx in target_indices:
                cell = worksheet.cell(row=row_idx, column=col_idx)
                value = cell.value
                if isinstance(value, bool) or value is None:
                    continue
                try:
                    numeric = float(value)
                except Exception:
                    continue
                if not math.isfinite(numeric):
                    continue
                if numeric != 0.0 and abs(numeric) < SCIENTIFIC_P_THRESHOLD:
                    cell.number_format = SCIENTIFIC_FMT
                else:
                    cell.number_format = DEFAULT_P_FMT
    finally:
        workbook.save(path)
        workbook.close()

