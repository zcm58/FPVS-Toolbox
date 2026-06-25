from __future__ import annotations

from Tools.Ratio_Calculator.utils import is_excel_temp_lock_file


def test_ratio_excel_temp_filter_includes_appledouble_sidecars() -> None:
    assert is_excel_temp_lock_file("~$P01_Cond_Results.xlsx")
    assert is_excel_temp_lock_file("._P01_Cond_Results.xlsx")
    assert not is_excel_temp_lock_file("P01_Cond_Results.xlsx")
