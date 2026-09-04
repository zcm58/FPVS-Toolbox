from __future__ import annotations

import numpy as np
import pytest

from Tools.Stats.analysis.noise_utils import compute_qc14_standard_metrics


def _candidate_indices(target: int) -> tuple[int, ...]:
    return tuple([*range(target - 10, target - 1), *range(target + 2, target + 11)])


def test_qc14_metrics_preserve_locked_formula_with_complete_support() -> None:
    amplitudes = np.linspace(1.0, 10.0, 80)
    target = 30
    candidates = _candidate_indices(target)
    result = compute_qc14_standard_metrics(
        amplitudes,
        target_idx=target,
        candidate_bin_indices=candidates,
    )

    candidate_values = amplitudes[list(candidates)]
    expected_retained = np.sort(candidate_values)[1:-1]
    expected_mean = float(expected_retained.mean())
    expected_sd = float(expected_retained.std(ddof=0))
    assert len(result.candidate_bin_indices) == 18
    assert len(result.retained_bin_indices) == 16
    assert result.noise_mean == pytest.approx(expected_mean)
    assert result.noise_population_sd == pytest.approx(expected_sd)
    assert result.bca == pytest.approx(amplitudes[target] - expected_mean)
    assert result.snr == pytest.approx(amplitudes[target] / expected_mean)
    assert result.local_z == pytest.approx(
        (amplitudes[target] - expected_mean) / expected_sd
    )
    assert result.bca_status == result.snr_status == result.local_z_status == "available"


def test_qc14_tied_extrema_still_remove_two_distinct_occurrences() -> None:
    amplitudes = np.ones(80)
    result = compute_qc14_standard_metrics(
        amplitudes,
        target_idx=30,
        candidate_bin_indices=_candidate_indices(30),
    )

    assert len(result.retained_bin_indices) == 16
    assert result.bca == pytest.approx(0.0)
    assert result.snr == pytest.approx(1.0)
    assert result.local_z is None
    assert result.local_z_status == "unavailable"
    assert "effectively_zero_noise_population_sd" in result.reason_codes


def test_qc14_nonfinite_support_is_structurally_unavailable() -> None:
    amplitudes = np.arange(80, dtype=float)
    amplitudes[23] = np.nan
    result = compute_qc14_standard_metrics(
        amplitudes,
        target_idx=30,
        candidate_bin_indices=_candidate_indices(30),
    )

    assert result.target_amplitude == 30.0
    assert result.bca is None
    assert result.snr is None
    assert result.local_z is None
    assert "nonfinite_noise_support" in result.reason_codes


def test_qc14_incomplete_or_asymmetric_support_never_computes_partial_baseline() -> None:
    amplitudes = np.arange(80, dtype=float)
    result = compute_qc14_standard_metrics(
        amplitudes,
        target_idx=30,
        candidate_bin_indices=_candidate_indices(30)[:-1],
    )

    assert result.retained_bin_indices == ()
    assert result.bca_status == "unavailable"
    assert "incomplete_or_asymmetric_noise_support" in result.reason_codes


def test_qc14_static_notch_hole_retains_target_as_audit_evidence() -> None:
    amplitudes = np.arange(80, dtype=float)
    result = compute_qc14_standard_metrics(
        amplitudes,
        target_idx=30,
        candidate_bin_indices=_candidate_indices(30),
        static_metrics_available=False,
        static_reason_codes=("required_noise_bin_inside_applied_notch",),
    )

    assert result.target_amplitude == 30.0
    assert result.target_amplitude_status == "available"
    assert result.bca is None
    assert result.reason_codes == ("required_noise_bin_inside_applied_notch",)


def test_qc14_zero_mean_only_invalidates_snr_and_zero_sd_only_invalidates_z() -> None:
    amplitudes = np.zeros(80, dtype=float)
    amplitudes[30] = 2.0
    candidate_indices = _candidate_indices(30)
    amplitudes[list(candidate_indices)] = np.linspace(-1.0, 1.0, len(candidate_indices))
    zero_mean = compute_qc14_standard_metrics(
        amplitudes,
        target_idx=30,
        candidate_bin_indices=candidate_indices,
    )

    assert zero_mean.bca == pytest.approx(2.0)
    assert zero_mean.snr is None
    assert zero_mean.snr_status == "unavailable"
    assert zero_mean.local_z is not None

    amplitudes[list(candidate_indices)] = 1.0
    zero_sd = compute_qc14_standard_metrics(
        amplitudes,
        target_idx=30,
        candidate_bin_indices=candidate_indices,
    )
    assert zero_sd.bca == pytest.approx(1.0)
    assert zero_sd.snr == pytest.approx(2.0)
    assert zero_sd.local_z is None
    assert zero_sd.local_z_status == "unavailable"
