from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from Tools.Stats.analysis import dv_policies
from Tools.Stats.analysis import dv_policy_group_significant as group_policy
from Tools.Stats.analysis.dv_policy_fixed_predefined import build_fixed_harmonic_selection
from Tools.Stats.analysis.dv_policy_group_significant import (
    build_group_significant_harmonic_selection,
)
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_PREDEFINED_POLICY_NAME,
    GROUP_SIGNIFICANT_POLICY_NAME,
    normalize_dv_policy,
)


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


def test_group_significant_policy_selects_common_grand_average_harmonics(tmp_path: Path) -> None:
    subjects = ["S1", "S2"]
    conditions = ["C1", "C2"]
    rois = {"Posterior": ["O1", "O2"], "Central": ["FZ"]}
    subject_data: dict[str, dict[str, str]] = {}
    for subject_idx, subject in enumerate(subjects, start=1):
        subject_data[subject] = {}
        for condition_idx, condition in enumerate(conditions, start=1):
            path = tmp_path / f"group_{subject}_{condition}.xlsx"
            _write_group_policy_workbook(
                path,
                scale=subject_idx + condition_idx - 1,
            )
            subject_data[subject][condition] = str(path)

    settings = normalize_dv_policy({"name": GROUP_SIGNIFICANT_POLICY_NAME})
    selection = build_group_significant_harmonic_selection(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_frequency_hz=6.0,
        rois=rois,
        log_func=lambda _message: None,
        settings=settings,
        max_freq=8.4,
    )

    assert selection.selected_harmonics_hz == pytest.approx([1.2, 3.6, 7.2])
    assert selection.excluded_base_harmonics_hz == pytest.approx([6.0])
    assert selection.selection_scope == "group_level_all_scalp_electrodes_all_selected_conditions"
    assert selection.z_by_harmonic[1.2] > settings.group_significant_z_threshold
    assert selection.z_by_harmonic[2.4] < settings.group_significant_z_threshold


def test_group_significant_policy_sums_selected_common_bca_for_every_roi(tmp_path: Path) -> None:
    subjects = ["S1", "S2"]
    conditions = ["C1", "C2"]
    rois = {"Posterior": ["O1", "O2"], "Central": ["FZ"]}
    subject_data: dict[str, dict[str, str]] = {}
    for subject_idx, subject in enumerate(subjects, start=1):
        subject_data[subject] = {}
        for condition_idx, condition in enumerate(conditions, start=1):
            path = tmp_path / f"group_sum_{subject}_{condition}.xlsx"
            _write_group_policy_workbook(
                path,
                scale=subject_idx + condition_idx - 1,
            )
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
        dv_policy={"name": GROUP_SIGNIFICANT_POLICY_NAME},
        dv_metadata=metadata,
        max_freq=8.4,
    )

    assert result is not None
    group_meta = metadata["group_significant_harmonics"]
    assert group_meta["selected_harmonics_hz"] == pytest.approx([1.2, 3.6, 7.2])
    assert group_meta["snr_used_for_statistics"] is False
    assert group_meta["applied_uniformly_across_rois"] is True

    for subject in subjects:
        for condition in conditions:
            for roi in rois:
                assert provenance[(subject, condition, roi)]["col_label"] == [
                    "1.2000_Hz",
                    "3.6000_Hz",
                    "7.2000_Hz",
                ]

    assert result["S1"]["C1"]["Posterior"] == pytest.approx(3.0)
    assert result["S1"]["C1"]["Central"] == pytest.approx(0.7)
    assert result["S2"]["C2"]["Posterior"] == pytest.approx(6.0)


def test_group_significant_policy_limits_fullfft_columns_and_reads_bca_once_per_workbook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = ["S1"]
    conditions = ["C1", "C2"]
    rois = {"Posterior": ["O1", "O2"], "Central": ["FZ"]}
    subject_data = {"S1": {}}
    for idx, condition in enumerate(conditions, start=1):
        path = tmp_path / f"instrumented_{condition}.xlsx"
        _write_group_policy_workbook(path, scale=idx)
        subject_data["S1"][condition] = str(path)

    original_read_excel = group_policy.safe_read_excel
    calls: list[dict[str, object]] = []

    def _recording_read_excel(path, sheet_name, *, index_col=None, usecols=None, use_cache=True):
        calls.append(
            {
                "path": str(path),
                "sheet_name": sheet_name,
                "usecols": list(usecols) if isinstance(usecols, list) else usecols,
                "use_cache": use_cache,
            }
        )
        return original_read_excel(
            path,
            sheet_name,
            index_col=index_col,
            usecols=usecols,
            use_cache=use_cache,
        )

    monkeypatch.setattr(group_policy, "safe_read_excel", _recording_read_excel)

    result = dv_policies.prepare_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=6.0,
        log_func=lambda _message: None,
        rois=rois,
        provenance_map={},
        dv_policy={"name": GROUP_SIGNIFICANT_POLICY_NAME},
        dv_metadata={},
        max_freq=3.6,
    )

    assert result is not None
    fullfft_calls = [
        call for call in calls if call["sheet_name"] == "FullFFT Amplitude (uV)"
    ]
    bca_calls = [call for call in calls if call["sheet_name"] == "BCA (uV)"]

    assert len(fullfft_calls) == len(conditions)
    assert all(call["use_cache"] is False for call in fullfft_calls)
    assert all(isinstance(call["usecols"], list) for call in fullfft_calls)
    assert all("Electrode" in call["usecols"] for call in fullfft_calls)
    assert all(len(call["usecols"]) < 36 for call in fullfft_calls)

    assert len(bca_calls) == len(conditions)
    assert all(call["use_cache"] is False for call in bca_calls)


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


def _write_group_policy_workbook(path: Path, *, scale: int) -> None:
    frequency_values = [round(0.3 * idx, 4) for idx in range(0, 35)]
    fft_values = []
    for idx, freq in enumerate(frequency_values):
        base_noise = 1.2 if idx % 2 == 0 else 0.8
        if freq in {1.2, 3.6, 7.2}:
            base_noise = 20.0
        fft_values.append(base_noise)
    full_fft = pd.DataFrame(
        {
            f"{freq:.4f}_Hz": [value, value, value]
            for freq, value in zip(frequency_values, fft_values)
        },
        index=["O1", "O2", "FZ"],
    )
    full_fft.index.name = "Electrode"

    bca = pd.DataFrame(
        {
            "1.2000_Hz": [1.0 * scale, 2.0 * scale, 0.5],
            "2.4000_Hz": [100.0, 100.0, 100.0],
            "3.6000_Hz": [0.5, 0.5, 0.1],
            "4.8000_Hz": [100.0, 100.0, 100.0],
            "6.0000_Hz": [100.0, 100.0, 100.0],
            "7.2000_Hz": [1.0, 1.0, 0.1],
        },
        index=["O1", "O2", "FZ"],
    )
    bca.index.name = "Electrode"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)")
        full_fft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)")
