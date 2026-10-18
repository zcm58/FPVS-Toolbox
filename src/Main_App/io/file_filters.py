"""Shared filename filters for user data files and generated workbooks."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

EXCEL_WORKBOOK_SUFFIXES = (".xlsx",)
EXCEL_OUTPUT_SUFFIXES = (".xls", ".xlsx", ".xlsm", ".xlsb")


def _filename(value: str | Path) -> str:
    return Path(value).name


def _has_suffix(value: str | Path, suffixes: Iterable[str]) -> bool:
    allowed = {suffix.lower() for suffix in suffixes}
    return Path(value).suffix.lower() in allowed


def is_appledouble_sidecar(value: str | Path) -> bool:
    """Return True for macOS AppleDouble metadata files such as ._P01.xlsx."""
    return _filename(value).startswith("._")


def is_office_temp_excel_file(value: str | Path) -> bool:
    """Return True for Office temporary lock workbooks such as ~$P01.xlsx."""
    return _filename(value).startswith("~$")


def is_excel_metadata_or_temp_file(value: str | Path) -> bool:
    """Return True for workbook-like files that should never be treated as data."""
    return is_appledouble_sidecar(value) or is_office_temp_excel_file(value)


def is_excel_workbook_file(
    value: str | Path,
    *,
    suffixes: Iterable[str] = EXCEL_WORKBOOK_SUFFIXES,
) -> bool:
    """Return True for real Excel workbook inputs, excluding metadata/temp files."""
    return _has_suffix(value, suffixes) and not is_excel_metadata_or_temp_file(value)


def is_excel_output_file(value: str | Path) -> bool:
    """Return True for real generated Excel output files."""
    return is_excel_workbook_file(value, suffixes=EXCEL_OUTPUT_SUFFIXES)


def is_bdf_file(value: str | Path) -> bool:
    """Return True for real BDF inputs, excluding macOS AppleDouble sidecars."""
    return _has_suffix(value, (".bdf",)) and not is_appledouble_sidecar(value)


__all__ = [
    "EXCEL_OUTPUT_SUFFIXES",
    "EXCEL_WORKBOOK_SUFFIXES",
    "is_appledouble_sidecar",
    "is_bdf_file",
    "is_excel_metadata_or_temp_file",
    "is_excel_output_file",
    "is_excel_workbook_file",
    "is_office_temp_excel_file",
]
