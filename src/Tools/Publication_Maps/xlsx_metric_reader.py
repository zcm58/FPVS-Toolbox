"""Companion-aware selected-column adapter for scalp-map metric inputs."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from Main_App.io.xlsx_selected_reader import read_xlsx_sheet_selected_columns


def read_metric_sheet_selected_columns(
    excel_path: str | Path,
    *,
    sheet_name: str,
    required_columns: Sequence[str],
) -> pd.DataFrame:
    """Read only existing requested columns from one scalp-map metric worksheet.

    Missing requested columns are omitted so the caller can preserve its current
    exact-column diagnostics. The shared reader owns bounded caching.
    """

    return read_xlsx_sheet_selected_columns(
        excel_path,
        sheet_name=sheet_name,
        required_columns=required_columns,
        require_all=False,
    )


__all__ = ("read_metric_sheet_selected_columns",)
