from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from Tools.Stats.analysis import dv_policies
from Tools.Stats.analysis.dv_policy_fixed_predefined import build_fixed_harmonic_selection
from Tools.Stats.analysis.dv_policy_settings import FIXED_PREDEFINED_POLICY_NAME


def _bca_columns() -> list[str]:
    return [
        "1.2000_Hz",
        "2.4000_Hz",
        "3.6000_Hz",
        "4.8000_Hz",
        "6.0000_Hz",
        "7.2000_Hz",
    ]


def test_fixed_harmonic_selection_parses_dedupes_excludes_base_and_matches() -> None:
    selection = build_fixed_harmonic_selection(
        requested_values="1.2, 2.4, 2.4, 3.60001, 4.8, 6.0, 7.2",
        bca_columns=_bca_columns(),
        base_frequency_hz=6.0,
        auto_exclude_base_overlaps=True,
        base_overlap_tolerance_hz=0.01,
        matching_tolerance_hz=0.01,
    )

    assert selection.included_frequencies_hz == pytest.approx([1.2, 2.4, 3.6, 4.8, 7.2])
    assert selection.excluded_base_overlap_frequencies_hz == pytest.approx([6.0])
    assert selection.duplicate_frequencies_hz == pytest.approx([2.4])
    assert selection.matched_columns == [
        "1.2000_Hz",
        "2.4000_Hz",
        "3.6000_Hz",
        "4.8000_Hz",
        "7.2000_Hz",
    ]


def test_fixed_harmonic_selection_fails_when_requested_frequency_is_out_of_range() -> None:
    with pytest.raises(RuntimeError, match="validation failed"):
        build_fixed_harmonic_selection(
            requested_values="99.9",
            bca_columns=_bca_columns(),
            base_frequency_hz=6.0,
            matching_tolerance_hz=0.01,
        )


def test_fixed_predefined_policy_sums_bca_uniformly_and_ignores_z(tmp_path: Path) -> None:
    subjects = ["S1", "S2"]
    conditions = ["C1", "C2"]
    rois = {"Posterior": ["O1", "O2"], "Central": ["FZ"]}
    subject_data: dict[str, dict[str, str]] = {}
    for subject_idx, subject in enumerate(subjects, start=1):
        subject_data[subject] = {}
        for condition_idx, condition in enumerate(conditions, start=1):
            path = tmp_path / f"{subject}_{condition}.xlsx"
            _write_workbook(path, subject_idx=subject_idx, condition_idx=condition_idx)
            subject_data[subject][condition] = str(path)

    dv_policies._DV_DATA_CACHE.clear()
    metadata: dict[str, object] = {}
    provenance: dict[tuple[str, str, str], dict[str, object]] = {}
    result = dv_policies.prepare_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=6.0,
        log_func=lambda _message: None,
        rois=rois,
        provenance_map=provenance,
        dv_policy={
            "name": FIXED_PREDEFINED_POLICY_NAME,
            "fixed_harmonic_frequencies_hz": "1.2, 2.4, 3.6, 4.8, 6.0, 7.2",
            "fixed_harmonic_auto_exclude_base": True,
        },
        dv_metadata=metadata,
    )

    assert result is not None
    selected = metadata["fixed_predefined_harmonics"]["fixed_harmonic_included_frequencies_hz"]
    assert selected == pytest.approx([1.2, 2.4, 3.6, 4.8, 7.2])
    assert metadata["fixed_predefined_harmonics"]["snr_used_for_statistics"] is False

    for subject in subjects:
        for condition in conditions:
            for roi in rois:
                assert provenance[(subject, condition, roi)]["col_label"] == [
                    "1.2000_Hz",
                    "2.4000_Hz",
                    "3.6000_Hz",
                    "4.8000_Hz",
                    "7.2000_Hz",
                ]

    assert result["S1"]["C1"]["Posterior"] == pytest.approx(1.5)
    assert result["S1"]["C1"]["Central"] == pytest.approx(0.0001)
    assert result["S2"]["C2"]["Posterior"] == pytest.approx(4.5)


def _write_workbook(path: Path, *, subject_idx: int, condition_idx: int) -> None:
    scale = subject_idx + condition_idx - 1
    bca = pd.DataFrame(
        {
            "1.2000_Hz": [1.0 * scale, 2.0 * scale, 0.0],
            "2.4000_Hz": [0.5, -0.5, 0.0001],
            "3.6000_Hz": [0.0, 0.0, 0.0],
            "4.8000_Hz": [-1.0, -1.0, -0.0001],
            "6.0000_Hz": [100.0, 100.0, 100.0],
            "7.2000_Hz": [1.0, 1.0, 0.0001],
        },
        index=["O1", "O2", "FZ"],
    )
    bca.index.name = "Electrode"
    z_score = pd.DataFrame(
        {column: [-999.0, -999.0, -999.0] for column in bca.columns},
        index=bca.index,
    )
    z_score.index.name = "Electrode"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)")
        z_score.to_excel(writer, sheet_name="Z Score")
