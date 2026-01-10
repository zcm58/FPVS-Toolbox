import os
from math import isclose
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_ratio_calculator_smoke import _make_inputs, _write_participant_file

from Tools.Ratio_Calculator.PySide6.controller import RatioCalculatorController
from Tools.Ratio_Calculator.PySide6.view import RatioCalculatorWindow


def _setup_tool(tmp_path, qtbot, monkeypatch):
    class FakeSettingsManager:
        def get_roi_pairs(self):
            return [("Bilateral OT", ["O1", "O2"])]

    monkeypatch.setattr("Main_App.SettingsManager", lambda *_, **__: FakeSettingsManager())
    monkeypatch.setattr(
        "Tools.Ratio_Calculator.PySide6.controller.SettingsManager",
        lambda *_, **__: FakeSettingsManager(),
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "project.json").write_text("{}")

    excel_root = project_root / "1 - Excel Data Files"
    cond_a_dir = excel_root / "ConditionA"
    cond_b_dir = excel_root / "ConditionB"
    cond_a_dir.mkdir(parents=True)
    cond_b_dir.mkdir(parents=True)

    monkeypatch.chdir(project_root)
    view = RatioCalculatorWindow()
    qtbot.addWidget(view)
    controller = RatioCalculatorController(view)
    return project_root, excel_root, cond_a_dir, cond_b_dir, view, controller


def test_logratio_and_ratio_percent(tmp_path, qtbot, monkeypatch):
    project_root, excel_root, cond_a_dir, cond_b_dir, view, controller = _setup_tool(tmp_path, qtbot, monkeypatch)

    _write_participant_file(
        cond_a_dir / "P01_A.xlsx",
        snr_values=[[4.0, 4.0, 4.0]] * 3,
        z_values=[[3.0, 3.0, 3.0]] * 3,
    )
    _write_participant_file(
        cond_b_dir / "P01_B.xlsx",
        snr_values=[[2.0, 2.0, 2.0]] * 3,
        z_values=[[3.0, 3.0, 3.0]] * 3,
    )

    controller.set_excel_root(excel_root)
    view.cond_b_combo.setCurrentText("ConditionB")
    view.roi_combo.setCurrentText("Bilateral OT")
    inputs = _make_inputs(view, controller, excel_root, "Bilateral OT")
    result = controller.compute_ratios_sync(inputs)
    df = result.dataframe
    participant = df[df["PID"] == "P01"].iloc[0]
    assert isclose(participant["Ratio"], 2.0, rel_tol=1e-6)
    assert isclose(participant["LogRatio"], np.log(2.0), rel_tol=1e-6)
    assert isclose(participant["RatioPercent"], 100.0, rel_tol=1e-6)


def test_summary_stats_on_logratio(tmp_path, qtbot, monkeypatch):
    project_root, excel_root, cond_a_dir, cond_b_dir, view, controller = _setup_tool(tmp_path, qtbot, monkeypatch)

    ratios = {"P01": 2.0, "P02": 4.0}
    for pid, ratio in ratios.items():
        cond_a_vals = [2.0 * ratio] * 3
        cond_b_vals = [2.0] * 3
        _write_participant_file(
            cond_a_dir / f"{pid}_A.xlsx",
            snr_values=[cond_a_vals] * 3,
            z_values=[[3.0, 3.0, 3.0]] * 3,
        )
        _write_participant_file(
            cond_b_dir / f"{pid}_B.xlsx",
            snr_values=[cond_b_vals] * 3,
            z_values=[[3.0, 3.0, 3.0]] * 3,
        )

    controller.set_excel_root(excel_root)
    view.cond_b_combo.setCurrentText("ConditionB")
    view.roi_combo.setCurrentText("Bilateral OT")
    inputs = _make_inputs(view, controller, excel_root, "Bilateral OT")
    result = controller.compute_ratios_sync(inputs)
    df = result.dataframe
    summary_row = df[df["PID"] == "SUMMARY"].iloc[0]
    expected_logs = [np.log(r) for r in ratios.values()]
    assert isclose(summary_row["Mean"], float(np.mean(expected_logs)), rel_tol=1e-6)
    assert isclose(summary_row["MeanRatio_fromLog"], float(np.exp(np.mean(expected_logs))), rel_tol=1e-6)


def test_minimum_harmonics_rule(tmp_path, qtbot, monkeypatch):
    project_root, excel_root, cond_a_dir, cond_b_dir, view, controller = _setup_tool(tmp_path, qtbot, monkeypatch)

    _write_participant_file(
        cond_a_dir / "P01_A.xlsx",
        snr_values=[[4.0, 4.0]] * 3,
        z_values=[[3.0, 3.0]] * 3,
    )
    _write_participant_file(
        cond_b_dir / "P01_B.xlsx",
        snr_values=[[2.0, 2.0]] * 3,
        z_values=[[3.0, 3.0]] * 3,
    )

    controller.set_excel_root(excel_root)
    view.cond_b_combo.setCurrentText("ConditionB")
    view.roi_combo.setCurrentText("Bilateral OT")
    inputs = _make_inputs(view, controller, excel_root, "Bilateral OT")
    result = controller.compute_ratios_sync(inputs)
    df = result.dataframe
    summary_row = df[df["PID"] == "SUMMARY"].iloc[0]
    assert summary_row["N_used"] == 0
    assert summary_row["SkipReason"] == "insufficient_sig_harmonics"


def test_denominator_floor_quantile(tmp_path, qtbot, monkeypatch):
    project_root, excel_root, cond_a_dir, cond_b_dir, view, controller = _setup_tool(tmp_path, qtbot, monkeypatch)

    values = {"P01": [4.0, 4.0, 4.0], "P02": [4.0, 4.0, 4.0]}
    summary_b_values = {"P01": [1.0, 1.0, 1.0], "P02": [4.0, 4.0, 4.0]}
    for pid in values:
        _write_participant_file(
            cond_a_dir / f"{pid}_A.xlsx",
            snr_values=[values[pid]] * 3,
            z_values=[[3.0, 3.0, 3.0]] * 3,
        )
        _write_participant_file(
            cond_b_dir / f"{pid}_B.xlsx",
            snr_values=[summary_b_values[pid]] * 3,
            z_values=[[3.0, 3.0, 3.0]] * 3,
        )

    controller.set_excel_root(excel_root)
    view.cond_b_combo.setCurrentText("ConditionB")
    view.roi_combo.setCurrentText("Bilateral OT")
    view.denom_floor_checkbox.setChecked(True)
    view.denom_floor_quantile_spin.setValue(0.25)
    inputs = _make_inputs(view, controller, excel_root, "Bilateral OT")
    result = controller.compute_ratios_sync(inputs)
    df = result.dataframe
    p01_row = df[df["PID"] == "P01"].iloc[0]
    summary_row = df[df["PID"] == "SUMMARY"].iloc[0]
    assert p01_row["SkipReason"] == "denom_below_floor"
    assert p01_row["IncludedInSummary"] is False
    assert p01_row["DenomFloor"] > 1.0
    assert summary_row["N_floor_excluded"] == 1
    assert summary_row["N_used"] == 1


def test_outlier_exclusion_counts(tmp_path, qtbot, monkeypatch):
    project_root, excel_root, cond_a_dir, cond_b_dir, view, controller = _setup_tool(tmp_path, qtbot, monkeypatch)

    ratios = {"P01": 1.0, "P02": 1.1, "P03": 1.2, "P04": 1.05, "P05": 5.0}
    for pid, ratio in ratios.items():
        cond_a_vals = [2.0 * ratio] * 3
        cond_b_vals = [2.0] * 3
        _write_participant_file(
            cond_a_dir / f"{pid}_A.xlsx",
            snr_values=[cond_a_vals] * 3,
            z_values=[[3.0, 3.0, 3.0]] * 3,
        )
        _write_participant_file(
            cond_b_dir / f"{pid}_B.xlsx",
            snr_values=[cond_b_vals] * 3,
            z_values=[[3.0, 3.0, 3.0]] * 3,
        )

    controller.set_excel_root(excel_root)
    view.cond_b_combo.setCurrentText("ConditionB")
    view.roi_combo.setCurrentText("Bilateral OT")
    view.outlier_checkbox.setChecked(True)
    view.outlier_action_combo.setCurrentIndex(view.outlier_action_combo.findData("exclude"))
    inputs = _make_inputs(
        view,
        controller,
        excel_root,
        "Bilateral OT",
        outlier_enabled=True,
        outlier_action="exclude",
    )
    result = controller.compute_ratios_sync(inputs)
    df = result.dataframe
    p05_row = df[df["PID"] == "P05"].iloc[0]
    summary_row = df[df["PID"] == "SUMMARY"].iloc[0]
    assert p05_row["OutlierFlag"] is True
    assert p05_row["ExcludedAsOutlier"] is True
    assert summary_row["N_outliers_excluded"] == 1
    assert summary_row["N_used"] == 4
