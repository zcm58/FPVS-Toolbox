from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from Tools.Ratio_Calculator.compute import compute_roi_harmonic_means
from Tools.Ratio_Calculator.constants import RatioCalculatorSettings
from Tools.Ratio_Calculator.pipeline import run_ratio_calculator


def _metric_frame(
    electrodes: list[str],
    values: list[float],
) -> pd.DataFrame:
    return pd.DataFrame({"Electrode": electrodes, "0.3000_Hz": values})


@pytest.mark.parametrize(
    ("electrodes", "values", "match"),
    [
        (["O1"], [1.0], "O2.*missing"),
        (["O1", "O1", "O2"], [1.0, 1.5, 2.0], "O1.*appears 2 times"),
        (["O1", "O2"], [1.0, np.nan], "nonfinite"),
    ],
)
def test_fixed_roi_never_uses_partial_duplicate_or_nonfinite_members(
    electrodes: list[str],
    values: list[float],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        compute_roi_harmonic_means(
            _metric_frame(electrodes, values),
            ["O1", "O2"],
            ["0.3000_Hz"],
        )


def _write_managed_input(path: Path, scale: float) -> None:
    values = [[scale, scale * 2], [scale * 3, scale * 4]]
    frame = pd.DataFrame(
        {
            "Electrode": ["O1", "O2"],
            "0.3000_Hz": [row[0] for row in values],
            "0.6000_Hz": [row[1] for row in values],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".fpvs":
        from Main_App.io.condition_data import write_condition_companion
        from Main_App.io.result_manifest import write_result_manifest

        descriptor = write_condition_companion(
            path, {sheet: frame for sheet in ("Z Score", "SNR", "BCA (uV)")},
        )
        write_result_manifest(
            path, sheet_names=descriptor["sheets"],
            spectral_companion=None, condition_companion=descriptor,
        )
        return
    with pd.ExcelWriter(path) as writer:
        for sheet_name in ("Z Score", "SNR", "BCA (uV)"):
            frame.to_excel(writer, sheet_name=sheet_name, index=False)


@pytest.mark.parametrize("suffix", [".xlsx", ".fpvs"])
def test_managed_ratio_uses_accepted_project_harmonics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    from Tools.Ratio_Calculator import pipeline

    input_a = tmp_path / "A"
    input_b = tmp_path / "B"
    project_root = tmp_path / "Project"
    output = tmp_path / "Output"
    project_root.mkdir()
    _write_managed_input(input_a / f"P1_A{suffix}", 1.0)
    _write_managed_input(input_b / f"P1_B{suffix}", 2.0)
    if suffix == ".fpvs":
        _write_managed_input(input_a / "P1_A.xlsx", 99.0)
        _write_managed_input(input_b / "P1_B.xlsx", 99.0)

    monkeypatch.setattr(
        pipeline,
        "load_project_processing_harmonics",
        lambda **_kwargs: SimpleNamespace(
            selected_harmonics_hz=(0.3, 0.6),
            fingerprint_text="selection:project-0.3-hz",
        ),
    )
    monkeypatch.setattr(pipeline, "make_raincloud_figure", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "make_raincloud_figure_roi_x",
        lambda *_args, **_kwargs: None,
    )

    result = run_ratio_calculator(
        input_dir_a=str(input_a),
        condition_label_a="A",
        input_dir_b=str(input_b),
        condition_label_b="B",
        output_dir=str(output),
        run_label="managed",
        manual_exclude=[],
        settings=RatioCalculatorSettings(),
        roi_defs={"Posterior": ["O1", "O2"]},
        project_root=project_root,
    )

    parameters = pd.read_excel(result.excel_path, sheet_name="Parameters")
    parameter_map = dict(zip(parameters["key"], parameters["value"]))
    participant_sums = pd.read_excel(
        result.excel_path,
        sheet_name="Participant_Sums_ALL",
    )
    assert parameter_map["HARMONIC_SOURCE"] == "fpvs_toolbox_significant_harmonics"
    assert parameter_map["INCLUDED_ODDBALL_HARMONICS_HZ"] == "0.3, 0.6"
    assert int(parameter_map["N_INCLUDED_HARMONICS"]) == 2
    assert participant_sums["n_harmonics_summed"].tolist() == [2, 2]
    assert participant_sums["sum_BCA_uV"].tolist() == [5.0, 10.0]


def test_unmanaged_ratio_has_no_legacy_frequency_default(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicitly entered"):
        run_ratio_calculator(
            input_dir_a=str(tmp_path / "A"),
            condition_label_a="A",
            input_dir_b=str(tmp_path / "B"),
            condition_label_b="B",
            output_dir=str(tmp_path / "Output"),
            run_label="unmanaged",
            manual_exclude=[],
            settings=RatioCalculatorSettings(),
            roi_defs={"Posterior": ["O1", "O2"]},
        )
