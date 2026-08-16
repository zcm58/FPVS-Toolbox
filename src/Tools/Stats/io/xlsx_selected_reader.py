"""Compatibility adapter for the shared Main App `.xlsx` reader.

The exact-column reader is neutral project I/O used by more than the beta
Stats tool. New callers should import it from :mod:`Main_App.io`.
"""

from Main_App.io import (
    MissingXlsxColumnsError,
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
    xlsx_read_cache_scope,
)

__all__ = [
    "MissingXlsxColumnsError",
    "read_xlsx_sheet_header",
    "read_xlsx_sheet_selected_columns",
    "xlsx_read_cache_scope",
]
