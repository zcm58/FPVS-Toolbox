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
from Tools.Stats.workers import stats_workers


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
        requested_values="1.2, 2.4, 2.4, 3.6, 4.8, 6.0, 7.2",
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


def test_fixed_harmonic_selection_rejects_nearest_bca_column_fallback() -> None:
    with pytest.raises(RuntimeError, match="requires exact BCA column 1.2000_Hz"):
        build_fixed_harmonic_selection(
            requested_values="1.2",
            bca_columns=["1.2001_Hz", "2.4000_Hz"],
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
    first_row = next(row for row in selection.rows if row.target_frequency_hz == pytest.approx(1.2))
    assert first_row.target_amplitude_uv == pytest.approx(20.0)
    assert first_row.noise_mean_uv is not None
    assert first_row.noise_std_uv is not None
    assert first_row.noise_bin_indices
    assert first_row.noise_used_bin_indices


def test_group_significant_policy_reports_tested_candidates_when_none_selected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "no_selected_group_policy.xlsx"
    _write_group_policy_workbook(path, scale=1, peak_targets=set())
    messages: list[str] = []

    with pytest.raises(RuntimeError) as exc:
        build_group_significant_harmonic_selection(
            subjects=["S1"],
            conditions=["C1"],
            subject_data={"S1": {"C1": str(path)}},
            base_frequency_hz=6.0,
            rois={"Posterior": ["O1", "O2"]},
            log_func=messages.append,
            settings=normalize_dv_policy({"name": GROUP_SIGNIFICANT_POLICY_NAME}),
            max_freq=3.6,
        )

    message = str(exc.value)
    assert "Tested candidates:" in message
    assert "1.2000 Hz z=" in message
    assert "2.4000 Hz z=" in message
    assert "3.6000 Hz z=" in message
    assert any("tested candidates:" in item for item in messages)
    assert any("grand_avg_amp_uv=" in item for item in messages)
    assert any("noise_bins=[" in item for item in messages)


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
    group_policy.clear_group_significant_selection_cache()
    subjects = ["S1"]
    conditions = ["C1", "C2"]
    rois = {"Posterior": ["O1", "O2"], "Central": ["FZ"]}
    subject_data = {"S1": {}}
    for idx, condition in enumerate(conditions, start=1):
        path = tmp_path / f"instrumented_{condition}.xlsx"
        _write_group_policy_workbook(path, scale=idx)
        subject_data["S1"][condition] = str(path)

    original_read_excel = group_policy.safe_read_excel
    original_fullfft_loader = group_policy._load_mean_amplitude_series
    original_fullfft_plan = group_policy._plan_workbook_full_fft_usecols_from_header
    calls: list[dict[str, object]] = []
    fullfft_load_count = 0
    planned_fullfft_usecols: list[list[str]] = []

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

    def _recording_fullfft_loader(*args, **kwargs):
        nonlocal fullfft_load_count
        fullfft_load_count += 1
        return original_fullfft_loader(*args, **kwargs)

    def _recording_fullfft_plan(*args, **kwargs):
        usecols, mapping = original_fullfft_plan(*args, **kwargs)
        planned_fullfft_usecols.append(list(usecols))
        return usecols, mapping

    monkeypatch.setattr(group_policy, "safe_read_excel", _recording_read_excel)
    monkeypatch.setattr(
        group_policy,
        "_load_mean_amplitude_series",
        _recording_fullfft_loader,
    )
    monkeypatch.setattr(
        group_policy,
        "_plan_workbook_full_fft_usecols_from_header",
        _recording_fullfft_plan,
    )

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
    bca_calls = [call for call in calls if call["sheet_name"] == "BCA (uV)"]

    assert not [call for call in calls if call["sheet_name"] == "FullFFT Amplitude (uV)"]
    assert len(planned_fullfft_usecols) == len(conditions)
    assert all("Electrode" in usecols for usecols in planned_fullfft_usecols)
    assert all(len(usecols) < 36 for usecols in planned_fullfft_usecols)

    assert len(bca_calls) == len(conditions)
    assert all(call["use_cache"] is False for call in bca_calls)
    group_policy.clear_group_significant_selection_cache()


def test_group_significant_policy_reuses_cached_selection_between_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_policy.clear_group_significant_selection_cache()
    subjects = ["S1"]
    conditions = ["C1", "C2"]
    rois = {"Posterior": ["O1", "O2"], "Central": ["FZ"]}
    subject_data = {"S1": {}}
    for idx, condition in enumerate(conditions, start=1):
        path = tmp_path / f"cached_{condition}.xlsx"
        _write_group_policy_workbook(path, scale=idx)
        subject_data["S1"][condition] = str(path)

    original_read_excel = group_policy.safe_read_excel
    original_fullfft_loader = group_policy._load_mean_amplitude_series
    calls: list[dict[str, object]] = []
    fullfft_load_count = 0

    def _recording_read_excel(path, sheet_name, *, index_col=None, usecols=None, use_cache=True):
        calls.append({"path": str(path), "sheet_name": sheet_name})
        return original_read_excel(
            path,
            sheet_name,
            index_col=index_col,
            usecols=usecols,
            use_cache=use_cache,
        )

    def _recording_fullfft_loader(*args, **kwargs):
        nonlocal fullfft_load_count
        fullfft_load_count += 1
        return original_fullfft_loader(*args, **kwargs)

    monkeypatch.setattr(group_policy, "safe_read_excel", _recording_read_excel)
    monkeypatch.setattr(
        group_policy,
        "_load_mean_amplitude_series",
        _recording_fullfft_loader,
    )
    messages: list[str] = []

    try:
        for _run_idx in range(2):
            result = dv_policies.prepare_summed_bca_data(
                subjects=subjects,
                conditions=conditions,
                subject_data=subject_data,
                base_freq=6.0,
                log_func=messages.append,
                rois=rois,
                provenance_map={},
                dv_policy={"name": GROUP_SIGNIFICANT_POLICY_NAME},
                dv_metadata={},
                max_freq=3.6,
            )
            assert result is not None
    finally:
        group_policy.clear_group_significant_selection_cache()

    bca_calls = [call for call in calls if call["sheet_name"] == "BCA (uV)"]
    assert fullfft_load_count == len(conditions)
    assert len(bca_calls) == len(conditions) * 2
    assert any("Group harmonic selection cache hit" in message for message in messages)


def test_group_significant_policy_rejects_offgrid_fullfft_frequency_grids(
    tmp_path: Path,
) -> None:
    group_policy.clear_group_significant_selection_cache()
    subjects = ["S1"]
    conditions = ["C1", "C2"]
    rois = {"Posterior": ["O1", "O2"], "Central": ["FZ"]}
    subject_data = {"S1": {}}
    for condition, frequency_step in [("C1", 0.0079365), ("C2", 0.0083333)]:
        path = tmp_path / f"mixed_grid_{condition}.xlsx"
        _write_group_policy_workbook(path, scale=1, frequency_step=frequency_step)
        subject_data["S1"][condition] = str(path)

    with pytest.raises(RuntimeError, match="requires exact nominal oddball harmonic columns"):
        dv_policies.prepare_summed_bca_data(
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
    group_policy.clear_group_significant_selection_cache()


def test_group_significant_policy_fails_fast_when_any_workbook_lacks_exact_harmonic_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_policy.clear_group_significant_selection_cache()
    subjects = ["S1"]
    conditions = ["C1", "C2"]
    rois = {"Posterior": ["O1", "O2"], "Central": ["FZ"]}
    first_path = tmp_path / "exact_grid.xlsx"
    second_path = tmp_path / "near_but_not_exact_grid.xlsx"
    _write_group_policy_workbook(first_path, scale=1, frequency_step=0.3)
    _write_group_policy_workbook(second_path, scale=1, frequency_step=0.300025)
    subject_data = {
        "S1": {
            "C1": str(first_path),
            "C2": str(second_path),
        }
    }
    fullfft_row_reads: list[str] = []
    bca_reads: list[str] = []

    def _unexpected_fullfft_row_read(*_args, **_kwargs):
        fullfft_row_reads.append("called")
        raise AssertionError("FullFFT row loading should not run before exact-column preflight fails")

    def _unexpected_excel_read(path, sheet_name, **_kwargs):
        bca_reads.append(f"{path}:{sheet_name}")
        raise AssertionError("BCA sheets should not be read before exact-column preflight fails")

    monkeypatch.setattr(
        group_policy,
        "_load_mean_amplitude_series",
        _unexpected_fullfft_row_read,
    )
    monkeypatch.setattr(group_policy, "safe_read_excel", _unexpected_excel_read)

    with pytest.raises(
        RuntimeError,
        match="requires exact nominal oddball harmonic columns in every included FullFFT sheet",
    ):
        dv_policies.prepare_summed_bca_data(
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

    assert fullfft_row_reads == []
    assert bca_reads == []
    group_policy.clear_group_significant_selection_cache()


def test_group_significant_stats_worker_preflights_exact_columns_before_qc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_policy.clear_group_significant_selection_cache()
    subjects = ["S1"]
    conditions = ["C1", "C2"]
    rois = {"Posterior": ["O1", "O2"]}
    first_path = tmp_path / "worker_exact_grid.xlsx"
    second_path = tmp_path / "worker_near_grid.xlsx"
    _write_group_policy_workbook(first_path, scale=1, frequency_step=0.3)
    _write_group_policy_workbook(second_path, scale=1, frequency_step=0.300025)
    subject_data = {
        "S1": {
            "C1": str(first_path),
            "C2": str(second_path),
        }
    }
    qc_calls: list[str] = []

    def _unexpected_qc_screening(**_kwargs):
        qc_calls.append("called")
        raise AssertionError("QC screening should not run before exact-column preflight fails")

    monkeypatch.setattr(stats_workers, "_apply_qc_screening", _unexpected_qc_screening)
    monkeypatch.setattr(stats_workers, "_resolve_max_freq", lambda _value: 3.6)

    with pytest.raises(
        RuntimeError,
        match="requires exact nominal oddball harmonic columns in every included FullFFT sheet",
    ):
        stats_workers._prepare_single_group_data(
            subjects=subjects,
            conditions=conditions,
            conditions_all=conditions,
            subject_data=subject_data,
            base_freq=6.0,
            rois=rois,
            rois_all=rois,
            dv_policy={"name": GROUP_SIGNIFICANT_POLICY_NAME},
            outlier_exclusion_enabled=False,
            outlier_abs_limit=50.0,
            qc_config={},
            qc_state={},
            manual_excluded_pids=[],
            message_cb=lambda _message: None,
        )

    assert qc_calls == []
    group_policy.clear_group_significant_selection_cache()


def test_group_significant_policy_requires_exact_selected_bca_columns(tmp_path: Path) -> None:
    group_policy.clear_group_significant_selection_cache()
    path = tmp_path / "near_bca_columns.xlsx"
    _write_group_policy_workbook(path, scale=1, frequency_step=0.3, bca_column_offset=0.0001)

    with pytest.raises(
        RuntimeError,
        match="requires exact selected BCA harmonic columns",
    ):
        dv_policies.prepare_summed_bca_data(
            subjects=["S1"],
            conditions=["C1"],
            subject_data={"S1": {"C1": str(path)}},
            base_freq=6.0,
            log_func=lambda _message: None,
            rois={"Posterior": ["O1", "O2"]},
            provenance_map={},
            dv_policy={"name": GROUP_SIGNIFICANT_POLICY_NAME},
            dv_metadata={},
            max_freq=3.6,
        )

    group_policy.clear_group_significant_selection_cache()


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


def _write_group_policy_workbook(
    path: Path,
    *,
    scale: int,
    frequency_step: float = 0.3,
    peak_targets: set[float] | None = None,
    bca_column_offset: float = 0.0,
) -> None:
    if peak_targets is None:
        peak_targets = {1.2, 3.6, 7.2}
    frequency_values = [
        round(frequency_step * idx, 4)
        for idx in range(0, int(round(10.2 / frequency_step)) + 1)
    ]
    fft_values = []
    for idx, freq in enumerate(frequency_values):
        base_noise = 1.2 if idx % 2 == 0 else 0.8
        if any(abs(freq - target) <= frequency_step / 2 for target in peak_targets):
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
            f"{1.2 + bca_column_offset:.4f}_Hz": [1.0 * scale, 2.0 * scale, 0.5],
            f"{2.4 + bca_column_offset:.4f}_Hz": [100.0, 100.0, 100.0],
            f"{3.6 + bca_column_offset:.4f}_Hz": [0.5, 0.5, 0.1],
            f"{4.8 + bca_column_offset:.4f}_Hz": [100.0, 100.0, 100.0],
            f"{6.0 + bca_column_offset:.4f}_Hz": [100.0, 100.0, 100.0],
            f"{7.2 + bca_column_offset:.4f}_Hz": [1.0, 1.0, 0.1],
        },
        index=["O1", "O2", "FZ"],
    )
    bca.index.name = "Electrode"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)")
        full_fft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)")
