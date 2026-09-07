from __future__ import annotations

from pathlib import Path

from Tools.Ratio_Calculator.utils import is_excel_temp_lock_file


def test_ratio_excel_temp_filter_includes_appledouble_sidecars() -> None:
    assert is_excel_temp_lock_file("~$P01_Cond_Results.xlsx")
    assert is_excel_temp_lock_file("._P01_Cond_Results.xlsx")
    assert not is_excel_temp_lock_file("P01_Cond_Results.xlsx")


def test_ratio_folder_helpers_include_native_and_preserve_flat_scope(tmp_path: Path) -> None:
    from Tools.Ratio_Calculator.gui_condition_selection import RatioConditionSelectionMixin
    from Tools.Ratio_Calculator.gui_participants import RatioParticipantsMixin

    condition = tmp_path / "Faces"
    condition.mkdir()
    native = condition / "P01_Faces_Results.fpvs"
    native.write_text("native input")
    native.with_suffix(".xlsx").write_text("historical sibling")
    (condition / "._P01_Faces_Results.fpvs").write_text("sidecar")
    deeper = condition / "Control"
    deeper.mkdir()
    (deeper / "P02_Faces_Results.fpvs").write_text("nested input")

    assert RatioConditionSelectionMixin._scan_condition_folders(object(), tmp_path) == [condition]
    assert RatioParticipantsMixin._index_folder(object(), condition) == {"P01": native}
