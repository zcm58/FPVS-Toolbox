"""Thread-safe Excel I/O helpers for Legacy stats modules."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

_EXCEL_IO_LOCK = threading.Lock()

# Simple per-process cache: (path, sheet_name, index_col) -> DataFrame
_excel_cache: Dict[Tuple[str, str, str], pd.DataFrame] = {}


def _cache_key(path: Path, sheet_name: str, index_col: str | None) -> Tuple[str, str, str]:
    return (str(path), str(sheet_name), str(index_col or ""))


def safe_read_excel(
    path: str | Path,
    sheet_name: str,
    *,
    index_col: str | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Thread-serialized Excel reader for Legacy stats.

    - Always uses openpyxl via a short-lived ExcelFile context.
    - Optionally caches DataFrames for the lifetime of the process.
    - Safe to call from Qt worker threads.
    """

    p = Path(path)
    key = _cache_key(p, sheet_name, index_col)

    if use_cache and key in _excel_cache:
        return _excel_cache[key].copy()

    with _EXCEL_IO_LOCK:
        with pd.ExcelFile(str(p), engine="openpyxl") as xls:
            df = pd.read_excel(xls, sheet_name=sheet_name, index_col=index_col)

    if use_cache:
        _excel_cache[key] = df.copy()

    return df


__all__ = ["safe_read_excel"]
