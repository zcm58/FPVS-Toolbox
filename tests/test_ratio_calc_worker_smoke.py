from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from Tools.Ratio_Calculator.PySide6.model import RatioCalcInputs
from Tools.Ratio_Calculator.PySide6.worker import compute_ratios
from Tools.Stats.roi_resolver import ROI

from tests._ratio_calc_fixtures import write_ratio_workbook


def test_compute_ratios_smoke(monkeypatch, tmp_path: Path) -> None:
    electrodes = ["F3", "F4"]
    freqs = ["1.2000_Hz", "2.4000_Hz"]
    roi = ROI(name="Frontal", channels=electrodes)
    participants = [f"P{idx:02d}" for idx in range(1, 7)]
    conditions = ["condA", "condB"]
    subject_data: dict[str, dict[str, str]] = {}

    for idx, pid in enumerate(participants, start=1):
        cond_files: dict[str, str] = {}
        for cond in conditions:
            file_path = tmp_path / f"{pid}_{cond}.xlsx"
            base = float(idx)
            z_values = [[5.0, 5.0], [5.0, 5.0]]
            snr_values = [[base, base + 1], [base + 2, base + 3]]
            if pid == "P06" and cond == "condB":
                bca_values = [[0.0, 0.0], [0.0, 0.0]]
            else:
                bca_values = [[base + 1, base + 2], [base + 3, base + 4]]
            write_ratio_workbook(file_path, electrodes, freqs, z_values, snr_values, bca_values)
            cond_files[cond] = str(file_path)
        subject_data[pid] = cond_files

    def fake_scan_folder(_root: str):
        return participants, conditions, subject_data

    monkeypatch.setattr(
        "Tools.Ratio_Calculator.PySide6.worker.scan_folder_simple",
        fake_scan_folder,
    )

    inputs = RatioCalcInputs(
        excel_root=tmp_path,
        cond_a="condA",
        cond_b="condB",
        roi_name=None,
        z_threshold=1.0,
        output_path=tmp_path / "ratio_output.xlsx",
        significance_mode="group",
        rois=[roi],
        metric="bca",
        outlier_enabled=False,
        outlier_method="mad",
        outlier_threshold=3.5,
        outlier_action="exclude",
        bca_negative_mode="strict",
        min_significant_harmonics=1,
        denominator_floor_enabled=False,
        denominator_floor_mode="absolute",
        denominator_floor_quantile=0.1,
        denominator_floor_scope="global",
        denominator_floor_reference="summary_b",
        denominator_floor_absolute=None,
        summary_metric="ratio",
        outlier_metric="summary",
        require_denom_sig=False,
    )

    result = compute_ratios(inputs)
    df = result.dataframe

    ratio_label = f"{inputs.cond_a} vs {inputs.cond_b} - {roi.name}"
    roi_rows = df[df["Ratio Label"] == ratio_label]
    assert "SUMMARY" in roi_rows["PID"].values

    summary_row = roi_rows[roi_rows["PID"] == "SUMMARY"].iloc[0]
    detail_rows = roi_rows[roi_rows["PID"].isin(participants)].copy()
    included_rows = detail_rows[detail_rows["IncludedInSummary"]]
    summary_metric = pd.to_numeric(included_rows["Ratio"], errors="coerce")
    expected_variance = float(summary_metric.var(ddof=1))
    assert summary_row["Variance"] == pytest.approx(expected_variance)

    def _is_base_valid(row: pd.Series) -> bool:
        summary_a = row["SummaryA"]
        summary_b = row["SummaryB"]
        return (
            pd.notna(summary_a)
            and pd.notna(summary_b)
            and summary_b != 0
        )

    base_valid_by_pid = {row["PID"]: _is_base_valid(row) for _, row in detail_rows.iterrows()}
    included_by_pid = dict(zip(detail_rows["PID"], detail_rows["IncludedInSummary"]))
    assert included_by_pid == base_valid_by_pid


def test_compute_ratios_condition_specific_sig_harmonics(monkeypatch, tmp_path: Path) -> None:
    electrodes = ["F3", "F4"]
    freqs = ["1.2000_Hz", "2.4000_Hz", "3.6000_Hz", "4.8000_Hz"]
    roi = ROI(name="Frontal", channels=electrodes)
    participants = ["P01"]
    conditions = ["condA", "condB"]
    subject_data: dict[str, dict[str, str]] = {}

    for pid in participants:
        cond_files: dict[str, str] = {}
        for cond in conditions:
            file_path = tmp_path / f"{pid}_{cond}.xlsx"
            if cond == "condA":
                z_values = [[5.0, 5.0, 0.0, 0.0], [5.0, 5.0, 0.0, 0.0]]
                snr_values = [[10.0, 20.0, 30.0, 40.0], [10.0, 20.0, 30.0, 40.0]]
            else:
                z_values = [[5.0, 0.0, 5.0, 5.0], [5.0, 0.0, 5.0, 5.0]]
                snr_values = [[5.0, 15.0, 25.0, 35.0], [5.0, 15.0, 25.0, 35.0]]
            bca_values = [[1.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]]
            write_ratio_workbook(file_path, electrodes, freqs, z_values, snr_values, bca_values)
            cond_files[cond] = str(file_path)
        subject_data[pid] = cond_files

    def fake_scan_folder(_root: str):
        return participants, conditions, subject_data

    monkeypatch.setattr(
        "Tools.Ratio_Calculator.PySide6.worker.scan_folder_simple",
        fake_scan_folder,
    )

    inputs = RatioCalcInputs(
        excel_root=tmp_path,
        cond_a="condA",
        cond_b="condB",
        roi_name=None,
        z_threshold=1.0,
        output_path=tmp_path / "ratio_output.xlsx",
        significance_mode="group",
        rois=[roi],
        metric="snr",
        outlier_enabled=False,
        outlier_method="mad",
        outlier_threshold=3.5,
        outlier_action="exclude",
        bca_negative_mode="strict",
        min_significant_harmonics=2,
        denominator_floor_enabled=False,
        denominator_floor_mode="absolute",
        denominator_floor_quantile=0.1,
        denominator_floor_scope="global",
        denominator_floor_reference="summary_b",
        denominator_floor_absolute=None,
        summary_metric="ratio",
        outlier_metric="summary",
        require_denom_sig=False,
    )

    result = compute_ratios(inputs)
    df = result.dataframe

    ratio_label = f"{inputs.cond_a} vs {inputs.cond_b} - {roi.name}"
    roi_rows = df[df["Ratio Label"] == ratio_label]
    detail_row = roi_rows[roi_rows["PID"] == participants[0]].iloc[0]

    assert detail_row["SigHarmonicsA_N"] != detail_row["SigHarmonicsB_N"]
    assert detail_row["SigHarmonicsA_N"] == 2
    assert detail_row["SigHarmonicsB_N"] == 3

    summary_row = roi_rows[roi_rows["PID"] == "SUMMARY"].iloc[0]
    assert summary_row["SigHarmonicsA_N"] == 2
    assert summary_row["SigHarmonicsB_N"] == 3

    expected_summary_a = 15.0
    expected_summary_b = (5.0 + 25.0 + 35.0) / 3.0
    assert detail_row["SummaryA"] == pytest.approx(expected_summary_a)
    assert detail_row["SummaryB"] == pytest.approx(expected_summary_b)
    assert detail_row["Ratio"] == pytest.approx(expected_summary_a / expected_summary_b)
    assert detail_row["Ratio"] < 1.0
