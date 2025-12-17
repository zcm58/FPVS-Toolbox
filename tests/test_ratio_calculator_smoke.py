import os
from pathlib import Path

import pandas as pd
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from Tools.Ratio_Calculator.PySide6.controller import RatioCalculatorController
from Tools.Ratio_Calculator.PySide6.model import RatioCalcInputs
from Tools.Ratio_Calculator.PySide6.view import RatioCalculatorWindow


def _write_participant_file(path: Path, snr_values: list[list[float]], z_values: list[list[float]]) -> None:
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
    inputs = RatioCalcInputs(
        excel_root=excel_root,
        cond_a=view.cond_a_combo.currentText(),
        cond_b=view.cond_b_combo.currentText(),
        roi_name="Bilateral OT",
        z_threshold=1.64,
        output_path=output_path,
        significance_mode=view.significance_combo.currentData(),
        rois=controller._rois,
    )

    result = controller.compute_ratios_sync(inputs)

    assert output_path.exists()
    assert output_path.parent == project_root / "4 - Ratio Calculator Results"
    df = result.dataframe
    assert list(df.columns) == [
        "Ratio Label",
        "PID",
        "SNR_A",
        "SNR_B",
        "Ratio",
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

    monkeypatch.setattr(QMessageBox, "question", lambda *_, **__: QMessageBox.Yes)
    opened = []

    def _fake_open(url):
        opened.append(url)
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", _fake_open)
    controller._on_finished(result)
    assert opened
