from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis import dv_policies
from Tools.Stats.analysis.dv_policies import ROSSION_POLICY_NAME
from Tools.Stats.analysis.group_harmonics import FULL_FFT_AMPLITUDE_SHEET_NAME


def _spectrum_frame(*, peak_12: float, peak_60: float) -> pd.DataFrame:
    freqs = np.round(np.arange(0.0, 8.401, 0.2), 4)
    rows = []
    for electrode_offset in (0.0, 0.2, -0.1, 0.1):
        values = []
        for freq in freqs:
            baseline = 1.0 + 0.08 * math.sin(freq * 3.0) + electrode_offset
            if abs(freq - 1.2) < 1e-9:
                baseline += peak_12
            if abs(freq - 6.0) < 1e-9:
                baseline += peak_60
            values.append(baseline)
        rows.append(values)
    df = pd.DataFrame(
        rows,
        index=["O1", "O2", "FZ", "CZ"],
        columns=[f"{freq:.4f}_Hz" for freq in freqs],
    )
    df.index.name = "Electrode"
    return df


def _bca_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "1.2000_Hz": [1.0, 2.0, 10.0, 20.0],
            "2.4000_Hz": [100.0, 200.0, 1000.0, 2000.0],
            "6.0000_Hz": [500.0, 500.0, 500.0, 500.0],
            "7.2000_Hz": [50.0, 50.0, 50.0, 50.0],
        },
        index=["O1", "O2", "FZ", "CZ"],
    )
    df.index.name = "Electrode"
    return df


def _write_workbook(path: Path, *, peak_12: float, peak_60: float) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _spectrum_frame(peak_12=peak_12, peak_60=peak_60).to_excel(
            writer,
            sheet_name=FULL_FFT_AMPLITUDE_SHEET_NAME,
        )
        _bca_frame().to_excel(writer, sheet_name="BCA (uV)")


def _make_subject_data(tmp_path: Path) -> tuple[list[str], list[str], dict[str, dict[str, str]]]:
    subjects = ["P1", "P2"]
    conditions = [f"C{i}" for i in range(1, 6)]
    subject_data: dict[str, dict[str, str]] = {}
    for subject in subjects:
        subject_data[subject] = {}
        for condition in conditions:
            path = tmp_path / f"{subject}_{condition}.xlsx"
            _write_workbook(
                path,
                peak_12=12.0 if subject == "P1" else 0.5,
                peak_60=50.0,
            )
            subject_data[subject][condition] = str(path)
    return subjects, conditions, subject_data


def test_common_rossion_selection_uses_one_harmonic_set_for_all_cells(tmp_path: Path) -> None:
    subjects, all_conditions, subject_data = _make_subject_data(tmp_path)
    dv_policies._DV_DATA_CACHE.clear()
    metadata: dict[str, object] = {}

    result = dv_policies.prepare_summed_bca_data(
        subjects=subjects,
        conditions=["C1", "C2"],
        selection_conditions=all_conditions,
        subject_data=subject_data,
        base_freq=6.0,
        rois={"Posterior": ["O1", "O2"], "Central": ["FZ", "CZ"]},
        log_func=lambda _message: None,
        dv_policy={
            "name": ROSSION_POLICY_NAME,
            "z_threshold": 1.64,
            "empty_list_policy": "Error",
        },
        dv_metadata=metadata,
        max_freq=8.4,
    )

    assert result is not None
    rossion_meta = metadata["rossion_method"]
    assert rossion_meta["selection_scope"] == "all_scalp_electrodes"
    assert rossion_meta["selection_conditions"] == all_conditions
    assert rossion_meta["common_harmonics_hz"] == pytest.approx([1.2])
    assert set(rossion_meta["union_harmonics_by_roi"]) == {"Posterior", "Central"}
    assert rossion_meta["union_harmonics_by_roi"]["Posterior"] == pytest.approx([1.2])
    assert rossion_meta["union_harmonics_by_roi"]["Central"] == pytest.approx([1.2])
    assert any(freq == pytest.approx(6.0) for freq in rossion_meta["excluded_base_harmonics_hz"])
    assert float(rossion_meta["selection_z_by_harmonic"][1.2]) > 1.64

    assert result["P1"]["C1"]["Posterior"] == pytest.approx(1.5)
    assert result["P1"]["C1"]["Central"] == pytest.approx(15.0)
    assert result["P2"]["C2"]["Posterior"] == pytest.approx(1.5)


def test_common_rossion_requires_regenerated_full_fft_workbooks(tmp_path: Path) -> None:
    workbook = tmp_path / "old.xlsx"
    _bca_frame().to_excel(workbook, sheet_name="BCA (uV)")
    dv_policies._DV_DATA_CACHE.clear()

    with pytest.raises(RuntimeError, match="FullFFT"):
        dv_policies.prepare_summed_bca_data(
            subjects=["P1"],
            conditions=["C1"],
            selection_conditions=["C1"],
            subject_data={"P1": {"C1": str(workbook)}},
            base_freq=6.0,
            rois={"Posterior": ["O1", "O2"]},
            log_func=lambda _message: None,
            dv_policy={"name": ROSSION_POLICY_NAME, "empty_list_policy": "Error"},
            max_freq=8.4,
        )
