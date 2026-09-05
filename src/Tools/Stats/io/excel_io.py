"""Thread-safe Excel I/O helpers for Legacy stats modules."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, Sequence, Tuple

import pandas as pd

from Main_App.io.condition_data import CONDITION_DATA_SHEET_NAMES, read_condition_sheet

_EXCEL_IO_LOCK = threading.Lock()

# Simple per-process cache: (path, sheet_name, index_col) -> DataFrame
_excel_cache: Dict[Tuple[str, str, str], pd.DataFrame] = {}


def _cache_key(path: Path, sheet_name: str, index_col: str | None) -> Tuple[str, str, str]:
    """Run the cache key helper used by the Stats workflow."""
    return (str(path), str(sheet_name), str(index_col or ""))


def safe_read_excel(
    path: str | Path,
    sheet_name: str,
    *,
    index_col: str | None = None,
    usecols: Sequence[str] | str | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Thread-serialized Excel reader for Legacy stats.

    - Compact processing metrics use the validated shared companion reader.
    - Other sheets use openpyxl with optional process-lifetime caching.
    - Safe to call from Qt worker threads.
    """

    p = Path(path)
    if sheet_name in CONDITION_DATA_SHEET_NAMES:
        # The shared bounded cache revalidates source artifacts. Never put these
        # frames into the old path-only cache, which can outlive a reprocessed file.
        df = read_condition_sheet(p, sheet_name=sheet_name)
        if isinstance(usecols, str):
            from openpyxl.utils.cell import column_index_from_string

            positions: set[int] = set()
            for part in usecols.split(","):
                endpoints = part.strip().split(":")
                first = column_index_from_string(endpoints[0]) - 1
                last = column_index_from_string(endpoints[-1]) - 1
                positions.update(range(first, last + 1))
            df = df.iloc[:, sorted(positions)]
        elif usecols is not None:
            missing = set(usecols).difference(df.columns)
            if missing:
                raise ValueError(f"Usecols do not match columns: {sorted(missing)}")
            df = df.loc[:, [column for column in df.columns if column in usecols]]
        if index_col is not None:
            df = df.set_index(index_col)
        return df
    key = _cache_key(p, sheet_name, index_col)
    if usecols is not None:
        use_cache = False

    if use_cache and key in _excel_cache:
        return _excel_cache[key].copy()

    with _EXCEL_IO_LOCK:
        with pd.ExcelFile(str(p), engine="openpyxl") as xls:
            df = pd.read_excel(
                xls,
                sheet_name=sheet_name,
                index_col=index_col,
                usecols=usecols,
            )

    if use_cache:
        _excel_cache[key] = df.copy()

    return df


__all__ = ["safe_read_excel"]
