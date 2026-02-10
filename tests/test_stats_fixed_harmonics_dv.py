from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from Tools.Stats.PySide6.dv_policies import compute_fixed_harmonic_dv_table


def _write_bca_excel(path: Path, rows: dict[str, dict[str, float]]) -> None:
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "Electrode"
    with pd.ExcelWriter(path) as writer:
        df.to_excel(writer, sheet_name="BCA (uV)")


def test_fixed_harmonic_uses_existing_frequency_matching(tmp_path: Path) -> None:
    file_path = tmp_path / "P1_CondA.xlsx"
    _write_bca_excel(
        file_path,
        {
            "O1": {"1.2000_Hz": 1.0, "2.4000_Hz": 2.5, "3.6000_Hz": 99.0},
            "O2": {"1.2000_Hz": 2.0, "2.4000_Hz": 3.5, "3.6000_Hz": 99.0},
        },
    )

    payload = compute_fixed_harmonic_dv_table(
        subjects=["P1"],
        conditions=["CondA"],
        subject_data={"P1": {"CondA": str(file_path)}},
        rois={"Occipital": ["O1", "O2"]},
        harmonics_by_roi={"Occipital": [1.2, 2.4]},
        log_func=lambda _msg: None,
    )

    out = payload["dv_df"]
    assert out.shape[0] == 1
    assert np.isclose(float(out.loc[0, "dv_value"]), 4.5)


def test_fixed_harmonic_missing_column_returns_nan_and_reports(tmp_path: Path) -> None:
    file_path = tmp_path / "P1_CondA.xlsx"
    _write_bca_excel(
        file_path,
        {
            "O1": {"1.2000_Hz": 1.0, "2.4000_Hz": 2.0},
            "O2": {"1.2000_Hz": 1.5, "2.4000_Hz": 2.5},
        },
    )

    payload = compute_fixed_harmonic_dv_table(
        subjects=["P1"],
        conditions=["CondA"],
        subject_data={"P1": {"CondA": str(file_path)}},
        rois={"Occipital": ["O1", "O2"]},
        harmonics_by_roi={"Occipital": [1.2, 4.8]},
        log_func=lambda _msg: None,
    )

    out = payload["dv_df"]
    assert np.isnan(float(out.loc[0, "dv_value"]))
    missing = payload["missing_harmonics"]
    assert len(missing) == 1
    assert missing[0]["missing_hz"] == [4.8]


def test_fixed_harmonic_deterministic_ordering(tmp_path: Path) -> None:
    file_path = tmp_path / "P1_CondA.xlsx"
    _write_bca_excel(
        file_path,
        {
            "O1": {"1.2000_Hz": 1.0, "2.4000_Hz": 2.0},
            "O2": {"1.2000_Hz": 3.0, "2.4000_Hz": 4.0},
        },
    )
    common_kwargs = dict(
        subjects=["P1"],
        conditions=["CondA"],
        subject_data={"P1": {"CondA": str(file_path)}},
        rois={"Occipital": ["O1", "O2"]},
        log_func=lambda _msg: None,
    )

    p1 = compute_fixed_harmonic_dv_table(
        harmonics_by_roi={"Occipital": [1.2, 2.4]},
        **common_kwargs,
    )
    p2 = compute_fixed_harmonic_dv_table(
        harmonics_by_roi={"Occipital": [2.4, 1.2]},
        **common_kwargs,
    )

    assert list(p1["dv_df"].columns) == ["subject", "condition", "roi", "dv_value"]
    pd.testing.assert_frame_equal(p1["dv_df"], p2["dv_df"])
