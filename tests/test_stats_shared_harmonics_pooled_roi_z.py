from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from Tools.Stats.Legacy.stats_analysis import _match_freq_column
from Tools.Stats.PySide6.shared_harmonics import (
    CONDITION_COMBINATION_RULE,
    compute_shared_harmonics,
)


def _write_z_workbook(path: Path, *, sheet_name: str, rows: dict[str, dict[str, float]]) -> None:
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index.name = "Electrode"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name)


def _build_subject_data(tmp_path: Path, values: dict[str, dict[str, dict[str, dict[str, float]]]]) -> tuple[list[str], dict[str, dict[str, str]]]:
    subject_data: dict[str, dict[str, str]] = {}
    subjects = sorted(values.keys())
    for subject, cond_map in values.items():
        subject_data[subject] = {}
        for condition, z_rows in cond_map.items():
            workbook = tmp_path / f"{subject}_{condition}.xlsx"
            _write_z_workbook(workbook, sheet_name="Z Scores", rows=z_rows)
            subject_data[subject][condition] = str(workbook)
    return subjects, subject_data


def _run_compute(subjects, subject_data, *, conditions: list[str]):
    return compute_shared_harmonics(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=6.0,
        rois={"Occ": ["O1", "O2"]},
        exclude_harmonic1=False,
        z_threshold=1.64,
        log_func=lambda _msg: None,
    )


def test_pooled_roi_z_non_empty_two_consecutive(tmp_path: Path) -> None:
    values = {
        "G1S1": {
            "Face": {"O1": {"1.2000_Hz": 2.1, "2.4000_Hz": 2.2, "3.6000_Hz": 0.4}, "O2": {"1.2000_Hz": 2.0, "2.4000_Hz": 2.1, "3.6000_Hz": 0.3}},
        },
        "G2S1": {
            "Face": {"O1": {"1.2000_Hz": 2.0, "2.4000_Hz": 2.0, "3.6000_Hz": 0.2}, "O2": {"1.2000_Hz": 1.9, "2.4000_Hz": 1.9, "3.6000_Hz": 0.1}},
        },
    }
    subjects, subject_data = _build_subject_data(tmp_path, values)
    result = _run_compute(subjects, subject_data, conditions=["Face"])

    assert result.z_sheet_used == "Z Scores"
    assert result.harmonics_by_roi["Occ"] == [1.2, 2.4]
    assert _match_freq_column(result.mean_z_by_condition["Face"].columns, 1.2) is None


def test_pooled_roi_z_empty_when_two_consecutive_not_met(tmp_path: Path) -> None:
    values = {
        "G1S1": {
            "Obj": {"O1": {"1.2000_Hz": 2.0, "2.4000_Hz": 1.2, "3.6000_Hz": 1.0}, "O2": {"1.2000_Hz": 1.9, "2.4000_Hz": 1.0, "3.6000_Hz": 0.8}},
        },
        "G2S1": {
            "Obj": {"O1": {"1.2000_Hz": 2.1, "2.4000_Hz": 1.3, "3.6000_Hz": 0.9}, "O2": {"1.2000_Hz": 2.0, "2.4000_Hz": 1.1, "3.6000_Hz": 0.7}},
        },
    }
    subjects, subject_data = _build_subject_data(tmp_path, values)
    result = _run_compute(subjects, subject_data, conditions=["Obj"])

    assert result.harmonics_by_roi["Occ"] == []


def test_pooled_roi_z_all_nan_reports_empty_diagnostics(tmp_path: Path) -> None:
    nan = float("nan")
    values = {
        "G1S1": {
            "Words": {"O1": {"1.2000_Hz": nan, "2.4000_Hz": nan, "3.6000_Hz": nan}, "O2": {"1.2000_Hz": nan, "2.4000_Hz": nan, "3.6000_Hz": nan}},
        },
        "G2S1": {
            "Words": {"O1": {"1.2000_Hz": nan, "2.4000_Hz": nan, "3.6000_Hz": nan}, "O2": {"1.2000_Hz": nan, "2.4000_Hz": nan, "3.6000_Hz": nan}},
        },
    }
    subjects, subject_data = _build_subject_data(tmp_path, values)
    result = _run_compute(subjects, subject_data, conditions=["Words"])

    assert result.harmonics_by_roi["Occ"] == []
    assert result.diagnostics["empty_reasons"]
    assert any("No finite pooled ROI Z values" in reason for reason in result.diagnostics["empty_reasons"])


def test_condition_combination_rule_uses_mean_across_conditions(tmp_path: Path) -> None:
    values = {
        "G1S1": {
            "CondA": {"O1": {"1.2000_Hz": 2.2, "2.4000_Hz": 2.1, "3.6000_Hz": 0.4}, "O2": {"1.2000_Hz": 2.1, "2.4000_Hz": 2.0, "3.6000_Hz": 0.3}},
            "CondB": {"O1": {"1.2000_Hz": 1.5, "2.4000_Hz": 1.5, "3.6000_Hz": 0.3}, "O2": {"1.2000_Hz": 1.4, "2.4000_Hz": 1.5, "3.6000_Hz": 0.2}},
        },
        "G2S1": {
            "CondA": {"O1": {"1.2000_Hz": 2.2, "2.4000_Hz": 2.2, "3.6000_Hz": 0.5}, "O2": {"1.2000_Hz": 2.0, "2.4000_Hz": 2.1, "3.6000_Hz": 0.4}},
            "CondB": {"O1": {"1.2000_Hz": 1.5, "2.4000_Hz": 1.5, "3.6000_Hz": 0.2}, "O2": {"1.2000_Hz": 1.4, "2.4000_Hz": 1.5, "3.6000_Hz": 0.2}},
        },
    }
    subjects, subject_data = _build_subject_data(tmp_path, values)
    result = _run_compute(subjects, subject_data, conditions=["CondA", "CondB"])

    assert result.condition_combination_rule_used == CONDITION_COMBINATION_RULE
    assert result.harmonics_by_roi["Occ"] == [1.2, 2.4]
    assert result.strict_intersection_harmonics_by_roi["Occ"] == []

    pooled = result.pooled_mean_z_table.set_index(["roi", "harmonic_hz"])["mean_z"]
    assert pooled[("Occ", 1.2)] > 1.64
    assert pooled[("Occ", 2.4)] > 1.64
    assert np.isfinite(pooled[("Occ", 1.2)])
