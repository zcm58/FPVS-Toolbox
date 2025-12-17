import os
from pathlib import Path

import pandas as pd
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from Tools.Ratio_Calculator.PySide6.controller import RatioCalculatorController
from Tools.Ratio_Calculator.PySide6.model import RatioCalcInputs
from Tools.Ratio_Calculator.PySide6.view import RatioCalculatorWindow


def _write_participant_file(
    path: Path,
    snr_values: list[list[float]],
    z_values: list[list[float]],
    bca_values: list[list[float]] | None = None,
) -> None:
    electrodes = ["O1", "O2", "Oz"]
    freqs = ["1.2000_Hz", "2.4000_Hz"]
    snr_df = pd.DataFrame({"Electrode": electrodes})
    z_df = pd.DataFrame({"Electrode": electrodes})
    for idx, freq in enumerate(freqs):
        snr_df[freq] = [row[idx] for row in snr_values]
        z_df[freq] = [row[idx] for row in z_values]
    with pd.ExcelWriter(path) as writer:
        snr_df.to_excel(writer, sheet_name="SNR", index=False)
        z_df.to_excel(writer, sheet_name="Z Score", index=False)
        if bca_values:
            bca_df = pd.DataFrame({"Electrode": electrodes})
            for idx, freq in enumerate(freqs):
                bca_df[freq] = [row[idx] for row in bca_values]
            bca_df.to_excel(writer, sheet_name="BCA (uV)", index=False)


def _make_inputs(view, controller, excel_root: Path, roi_name: str, **overrides):
    params = {
        "excel_root": excel_root,
        "cond_a": view.cond_a_combo.currentText(),
        "cond_b": view.cond_b_combo.currentText(),
        "roi_name": roi_name,
        "z_threshold": float(view.threshold_spin.value()),
        "output_path": view._resolve_output_path(),
        "significance_mode": view.significance_combo.currentData(),
        "rois": controller._rois,
        "metric": view.metric_combo.currentData(),
        "outlier_enabled": view.outlier_checkbox.isChecked(),
        "outlier_method": view.outlier_method_combo.currentData(),
        "outlier_threshold": float(view.outlier_threshold_spin.value()),
        "outlier_action": view.outlier_action_combo.currentData(),
        "bca_negative_mode": view.bca_handling_combo.currentData(),
    }
    params.update(overrides)
    return RatioCalcInputs(**params)


def test_ratio_calculator_smoke(tmp_path, qtbot, monkeypatch):
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

    participants = {"P01": ([10.0, 8.0], [2.0, 0.5]), "P02": ([12.0, 9.0], [2.5, 0.7])}
    for pid, (snr_vals, z_vals) in participants.items():
        _write_participant_file(cond_a_dir / f"{pid}_A.xlsx", snr_values=[snr_vals] * 3, z_values=[z_vals] * 3)
        _write_participant_file(cond_b_dir / f"{pid}_B.xlsx", snr_values=[[v / 2 for v in snr_vals]] * 3, z_values=[z_vals] * 3)

    monkeypatch.chdir(project_root)
    view = RatioCalculatorWindow()
    qtbot.addWidget(view)
    controller = RatioCalculatorController(view)

    detected_root = Path(view.excel_path_edit.text())
    assert detected_root == excel_root
    controller.set_excel_root(detected_root)
    view.cond_b_combo.setCurrentText("ConditionB")
    roi_items = [view.roi_combo.itemText(i) for i in range(view.roi_combo.count())]
    assert "Bilateral OT" in roi_items
    for default_roi in ("Occipital Lobe", "Frontal Lobe", "Parietal Lobe", "Central Lobe"):
        assert default_roi not in roi_items
    view.roi_combo.setCurrentText("Bilateral OT")
    view.significance_combo.setCurrentIndex(view.significance_combo.findData("individual"))

    output_path = view._resolve_output_path()
    inputs = _make_inputs(view, controller, excel_root, "Bilateral OT", output_path=output_path)

    result = controller.compute_ratios_sync(inputs)

    assert output_path.exists()
    assert output_path.parent == project_root / "4 - Ratio Calculator Results"
    df = result.dataframe
    assert list(df.columns) == [
        "Ratio Label",
        "PID",
        "SNR_A",
        "SNR_B",
        "SummaryA",
        "SummaryB",
        "Ratio",
        "MetricUsed",
        "SkipReason",
        "OutlierFlag",
        "OutlierMethod",
        "OutlierScore",
        "SigHarmonics_N",
        "N",
        "Mean",
        "Median",
        "Std",
        "Variance",
        "CV%",
        "Min",
        "Max",
    ]
    roi_rows = df[df["Ratio Label"].str.contains("Bilateral OT", na=False)]
    assert not roi_rows.empty
    participant_rows = roi_rows[roi_rows["PID"] != "SUMMARY"]
    assert len(participant_rows) >= 1
    assert (participant_rows["SigHarmonics_N"] > 0).any()
    summary_row = roi_rows[roi_rows["PID"] == "SUMMARY"].iloc[0]
    assert summary_row["N"] == len(participants)
    assert (participant_rows["MetricUsed"] == "SNR").all()
    assert (participant_rows["OutlierFlag"] == False).all()  # noqa: E712

    monkeypatch.setattr(QMessageBox, "question", lambda *_, **__: QMessageBox.Yes)
    opened = []

    def _fake_open(url):
        opened.append(url)
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", _fake_open)
    controller._on_finished(result)
    assert opened


def test_ratio_calculator_bca_strict(tmp_path, qtbot, monkeypatch):
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

    participant_data = {
        "P01": {"a": [2.0, 2.0], "b": [-1.0, -1.0]},
        "P02": {"a": [3.0, 3.0], "b": [1.0, 1.0]},
    }
    for pid, values in participant_data.items():
        _write_participant_file(
            cond_a_dir / f"{pid}_A.xlsx",
            snr_values=[values["a"]] * 3,
            z_values=[[3.0, 3.0]] * 3,
            bca_values=[values["a"]] * 3,
        )
        _write_participant_file(
            cond_b_dir / f"{pid}_B.xlsx",
            snr_values=[values["b"]] * 3,
            z_values=[[3.0, 3.0]] * 3,
            bca_values=[values["b"]] * 3,
        )

    monkeypatch.chdir(project_root)
    view = RatioCalculatorWindow()
    qtbot.addWidget(view)
    controller = RatioCalculatorController(view)

    detected_root = Path(view.excel_path_edit.text())
    controller.set_excel_root(detected_root)
    view.cond_b_combo.setCurrentText("ConditionB")
    view.roi_combo.setCurrentText("Bilateral OT")
    view.metric_combo.setCurrentIndex(view.metric_combo.findData("bca"))

    inputs = _make_inputs(view, controller, excel_root, "Bilateral OT")
    result = controller.compute_ratios_sync(inputs)
    df = result.dataframe

    roi_rows = df[df["Ratio Label"].str.contains("Bilateral OT", na=False)]
    p01_row = roi_rows[roi_rows["PID"] == "P01"].iloc[0]
    assert pd.isna(p01_row["Ratio"])
    assert p01_row["SkipReason"]
    assert p01_row["MetricUsed"] == "BCA"
    p02_row = roi_rows[roi_rows["PID"] == "P02"].iloc[0]
    assert not pd.isna(p02_row["Ratio"])
    summary_row = roi_rows[roi_rows["PID"] == "SUMMARY"].iloc[0]
    assert summary_row["N"] == 1


def test_ratio_calculator_outlier_detection(tmp_path, qtbot, monkeypatch):
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

    ratios = {"P01": 1.0, "P02": 1.1, "P03": 1.2, "P04": 1.05, "P05": 8.0}
    base = 2.0
    for pid, ratio in ratios.items():
        cond_a_vals = [base * ratio, base * ratio]
        cond_b_vals = [base, base]
        _write_participant_file(
            cond_a_dir / f"{pid}_A.xlsx",
            snr_values=[cond_a_vals] * 3,
            z_values=[[3.0, 3.0]] * 3,
        )
        _write_participant_file(
            cond_b_dir / f"{pid}_B.xlsx",
            snr_values=[cond_b_vals] * 3,
            z_values=[[3.0, 3.0]] * 3,
        )

    monkeypatch.chdir(project_root)
    view = RatioCalculatorWindow()
    qtbot.addWidget(view)
    controller = RatioCalculatorController(view)

    detected_root = Path(view.excel_path_edit.text())
    controller.set_excel_root(detected_root)
    view.cond_b_combo.setCurrentText("ConditionB")
    view.roi_combo.setCurrentText("Bilateral OT")
    view.outlier_checkbox.setChecked(True)
    view.outlier_threshold_spin.setValue(2.0)
    view.outlier_action_combo.setCurrentIndex(view.outlier_action_combo.findData("exclude"))

    inputs = _make_inputs(
        view,
        controller,
        excel_root,
        "Bilateral OT",
        outlier_enabled=True,
        outlier_threshold=2.0,
        outlier_action="exclude",
    )
    result = controller.compute_ratios_sync(inputs)
    df = result.dataframe

    roi_rows = df[df["Ratio Label"].str.contains("Bilateral OT", na=False)]
    participant_rows = roi_rows[roi_rows["PID"].isin(ratios.keys())]
    flagged = participant_rows[participant_rows["PID"] == "P05"].iloc[0]
    assert bool(flagged["OutlierFlag"]) is True
    assert flagged["OutlierMethod"] == "MAD (robust z)"
    summary_row = roi_rows[roi_rows["PID"] == "SUMMARY"].iloc[0]
    assert summary_row["N"] == 4
    assert summary_row["Mean"] < 2
