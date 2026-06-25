from __future__ import annotations

from pathlib import Path

from Main_App.Shared.file_filters import (
    is_appledouble_sidecar,
    is_bdf_file,
    is_excel_output_file,
    is_excel_workbook_file,
    is_office_temp_excel_file,
)


def test_excel_filters_ignore_metadata_and_temp_files() -> None:
    assert is_excel_workbook_file("P01_Cond_Results.xlsx")
    assert is_excel_output_file("P01_Cond_Results.xlsm")

    assert is_appledouble_sidecar("._P01_Cond_Results.xlsx")
    assert not is_excel_workbook_file("._P01_Cond_Results.xlsx")
    assert not is_excel_output_file("._P01_Cond_Results.xlsm")

    assert is_office_temp_excel_file("~$P01_Cond_Results.xlsx")
    assert not is_excel_workbook_file("~$P01_Cond_Results.xlsx")


def test_bdf_filter_only_ignores_appledouble_sidecars() -> None:
    assert is_bdf_file("P13.bdf")
    assert is_bdf_file("SC_P13.bdf")
    assert is_bdf_file("_P13.bdf")
    assert is_bdf_file(Path("raw") / "Semantic_Response_P13.bdf")

    assert not is_bdf_file("._P13.bdf")
    assert not is_bdf_file(Path("raw") / "._SC_P13.bdf")
    assert not is_bdf_file("P13.set")
