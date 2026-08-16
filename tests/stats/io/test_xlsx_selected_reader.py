"""Compatibility coverage for the retired Stats XLSX-reader ownership."""

from Main_App.io import (
    MissingXlsxColumnsError,
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
    xlsx_read_cache_scope,
)
import Tools.Stats.io.xlsx_selected_reader as stats_compat_reader


def test_stats_adapter_reexports_exact_shared_reader_objects() -> None:
    assert stats_compat_reader.MissingXlsxColumnsError is MissingXlsxColumnsError
    assert stats_compat_reader.read_xlsx_sheet_header is read_xlsx_sheet_header
    assert (
        stats_compat_reader.read_xlsx_sheet_selected_columns
        is read_xlsx_sheet_selected_columns
    )
    assert stats_compat_reader.xlsx_read_cache_scope is xlsx_read_cache_scope
