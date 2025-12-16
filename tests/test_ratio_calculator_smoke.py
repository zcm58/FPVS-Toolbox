from pathlib import Path

import pandas as pd

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


def test_ratio_calculator_smoke(tmp_path, qtbot):
    excel_root = tmp_path / "excel"
    cond_a_dir = excel_root / "ConditionA"
    cond_b_dir = excel_root / "ConditionB"
    cond_a_dir.mkdir(parents=True)
    cond_b_dir.mkdir(parents=True)

    participants = {"P01": ([10.0, 8.0], [2.0, 0.5]), "P02": ([12.0, 9.0], [2.5, 0.7])}
    for pid, (snr_vals, z_vals) in participants.items():
        _write_participant_file(cond_a_dir / f"{pid}_A.xlsx", snr_values=[snr_vals] * 3, z_values=[z_vals] * 3)
        _write_participant_file(cond_b_dir / f"{pid}_B.xlsx", snr_values=[[v / 2 for v in snr_vals]] * 3, z_values=[z_vals] * 3)

    view = RatioCalculatorWindow(project_root=excel_root)
    qtbot.addWidget(view)
    controller = RatioCalculatorController(view)
    controller.set_excel_root(excel_root)

    inputs = RatioCalcInputs(
        excel_root=excel_root,
        cond_a="ConditionA",
        cond_b="ConditionB",
        roi_name="Occipital Lobe",
        z_threshold=1.64,
        output_path=tmp_path / "ratio_output.xlsx",
    )

    result = controller.compute_ratios_sync(inputs)

    assert inputs.output_path.exists()
    df = result.dataframe
    assert not df.empty
    row = df[df["Ratio per ROI"].str.contains("Occipital Lobe")].iloc[0]
    for pid in participants:
        assert pid in df.columns
        assert not pd.isna(row[pid])
    assert {"N", "Mean", "Median", "Std", "Variance", "CV%", "Min", "Max"}.issubset(df.columns)
    assert row["N"] == len(participants)
