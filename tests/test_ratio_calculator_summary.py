import os
from math import isclose
import numpy as np
import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_ratio_calculator_rules import _setup_tool
from tests.test_ratio_calculator_smoke import _make_inputs, _write_participant_file


def test_trimmed_summary_excludes_extremes(tmp_path, qtbot, monkeypatch):
    project_root, excel_root, cond_a_dir, cond_b_dir, view, controller = _setup_tool(tmp_path, qtbot, monkeypatch)

    log_values = np.array([-0.2, 0.0, 0.5, 1.0, 1.5])
    for idx, log_val in enumerate(log_values, start=1):
        ratio = float(np.exp(log_val))
        pid = f"P{idx:02d}"
        cond_a_vals = [ratio] * 3
        cond_b_vals = [1.0] * 3
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
    trimmed_row = df[(df["PID"] == "SUMMARY_TRIMMED") & df["Ratio Label"].str.contains("Bilateral OT", na=False)].iloc[0]
    trimmed_expected = np.sort(log_values)[1:-1]
    assert trimmed_row["N_used_trimmed"] == len(trimmed_expected)
    assert trimmed_row["N_trimmed_excluded"] == 2
    assert isclose(float(trimmed_row["Mean"]), float(trimmed_expected.mean()), rel_tol=1e-6)
    assert isclose(float(trimmed_row["Median"]), float(np.median(trimmed_expected)), rel_tol=1e-6)


def test_trimmed_summary_with_small_sample_returns_na(tmp_path, qtbot, monkeypatch):
    project_root, excel_root, cond_a_dir, cond_b_dir, view, controller = _setup_tool(tmp_path, qtbot, monkeypatch)

    for idx in range(2):
        pid = f"P{idx+1:02d}"
        cond_a_vals = [1.5] * 3
        cond_b_vals = [1.0] * 3
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
    trimmed_row = df[(df["PID"] == "SUMMARY_TRIMMED") & df["Ratio Label"].str.contains("Bilateral OT", na=False)].iloc[0]
    assert trimmed_row["N_used_trimmed"] == 0
    assert trimmed_row["N_trimmed_excluded"] == 0
    assert pd.isna(trimmed_row["Mean"])
    assert pd.isna(trimmed_row["MeanRatio_fromLog_trim"])


def test_metric_headers_switch_for_bca(tmp_path, qtbot, monkeypatch):
    project_root, excel_root, cond_a_dir, cond_b_dir, view, controller = _setup_tool(tmp_path, qtbot, monkeypatch)

    for pid in ("P01", "P02", "P03"):
        cond_a_vals = [3.0] * 3
        cond_b_vals = [1.0] * 3
        _write_participant_file(
            cond_a_dir / f"{pid}_A.xlsx",
            snr_values=[cond_a_vals] * 3,
            z_values=[[3.0, 3.0, 3.0]] * 3,
            bca_values=[cond_a_vals] * 3,
        )
        _write_participant_file(
            cond_b_dir / f"{pid}_B.xlsx",
            snr_values=[cond_b_vals] * 3,
            z_values=[[3.0, 3.0, 3.0]] * 3,
            bca_values=[cond_b_vals] * 3,
        )

    controller.set_excel_root(excel_root)
    view.cond_b_combo.setCurrentText("ConditionB")
    view.roi_combo.setCurrentText("Bilateral OT")
    view.metric_combo.setCurrentIndex(view.metric_combo.findData("bca"))
    inputs = _make_inputs(view, controller, excel_root, "Bilateral OT")
    result = controller.compute_ratios_sync(inputs)
    columns = list(result.dataframe.columns)
    assert "BCA_A" in columns
    assert "BCA_B" in columns
    assert "SNR_A" not in columns
    assert "SNR_B" not in columns


def test_summary_dialog_builds_without_crashing(tmp_path, qtbot, monkeypatch):
    project_root, excel_root, cond_a_dir, cond_b_dir, view, controller = _setup_tool(tmp_path, qtbot, monkeypatch)

    for pid in ("P01", "P02", "P03"):
        cond_a_vals = [2.0] * 3
        cond_b_vals = [1.0] * 3
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
    view.handle_result(result)
    dialog = view._summary_dialog
    assert dialog is not None
    qtbot.addWidget(dialog)
    qtbot.waitUntil(dialog.isVisible)
    dialog.close()
