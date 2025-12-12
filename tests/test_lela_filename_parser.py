from pathlib import Path

import pandas as pd
import pytest

from Tools.Stats.Legacy.cross_phase_lmm_core import build_cross_phase_long_df
from Tools.Stats.PySide6.stats_data_loader import (
    LelaFilenameParseError,
    parse_lela_excel_filename,
    scan_lela_phase_folder,
)


def test_parse_uppercase_filename() -> None:
    metadata = parse_lela_excel_filename(Path("P2CGF_Angry_Results.xlsx"))

    assert metadata.subject_id == "P2"
    assert metadata.group_code == "CG"
    assert metadata.phase_code == "F"
    assert metadata.condition == "Angry"


def test_parse_multiword_condition_and_lowercase() -> None:
    metadata = parse_lela_excel_filename(Path("p20bcl_angry_control_results.xlsx"))

    assert metadata.subject_id == "P20"
    assert metadata.group_code == "BC"
    assert metadata.phase_code == "L"
    assert metadata.condition == "Angry Control"


def test_parse_failure_requires_results_suffix() -> None:
    with pytest.raises(LelaFilenameParseError):
        parse_lela_excel_filename(Path("P2CGF_Angry.xlsx"))


def test_merge_preserves_subjects_and_groups(tmp_path: Path) -> None:
    follicular = tmp_path / "Follicular"
    luteal = tmp_path / "Luteal"
    follicular.mkdir()
    luteal.mkdir()

    for name in ["P1CGF_Angry_Results.xlsx", "P2BCF_Angry_Results.xlsx"]:
        (follicular / name).write_text("", encoding="utf-8")
    for name in ["P1CGL_Angry_Results.xlsx", "P2BCL_Angry_Results.xlsx"]:
        (luteal / name).write_text("", encoding="utf-8")

    fol_scan = scan_lela_phase_folder(follicular)
    lut_scan = scan_lela_phase_folder(luteal)

    phase_data = {
        "Follicular": {
            "P1": {"Angry": {"ROI": 1.0}},
            "P2": {"Angry": {"ROI": 2.0}},
        },
        "Luteal": {
            "P1": {"Angry": {"ROI": 1.5}},
            "P2": {"Angry": {"ROI": 2.5}},
        },
    }
    phase_group_maps = {
        "Follicular": fol_scan.group_map,
        "Luteal": lut_scan.group_map,
    }

    df = build_cross_phase_long_df(
        phase_data,
        phase_group_maps,
        ("Follicular", "Luteal"),
        phase_label_to_code={"Follicular": fol_scan.phase_code, "Luteal": lut_scan.phase_code},
    )

    assert not df.empty
    assert sorted(df["subject"].unique()) == ["P1", "P2"]
    assert set(df["group"].unique()) == {"BC", "CG"}
    assert set(df["phase"].unique()) == {"F", "L"}
    assert len(df) == 4
    assert isinstance(df, pd.DataFrame)
