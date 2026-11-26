from __future__ import annotations

import numpy as np
import pytest

from Tools.Stats.analysis.noise_utils import (
    compute_qc14_standard_metrics,
    compute_qc14_standard_metrics_for_channels,
)


def _candidate_indices(target: int) -> tuple[int, ...]:
    return tuple([*range(target - 10, target - 1), *range(target + 2, target + 11)])


@pytest.mark.parametrize("channel_count", [4, 64, 67, 128])
def test_qc14_channel_batch_matches_exact_scalar_payload(channel_count):
    amplitudes = np.random.default_rng(182).lognormal(size=(channel_count, 161))
    amplitudes[0] = 0.0
    amplitudes[1] = -0.0
    amplitudes[2] = 1e-12
    amplitudes[3, ::2] = 1
    amplitudes[3, 1::2] = -1
    target = 120
    kwargs = {
        "target_idx": target,
        "candidate_bin_indices": _candidate_indices(target),
        "static_reason_codes": ("retained_note", "retained_note"),
    }

    batch = compute_qc14_standard_metrics_for_channels(amplitudes, **kwargs)
    assert batch is not None
    for row, measured in zip(amplitudes, batch, strict=True):
        expected = compute_qc14_standard_metrics(row, **kwargs)
        assert measured == expected
        for key, value in measured.to_payload().items():
            if isinstance(value, float):
                assert value.hex() == expected.to_payload()[key].hex()


@pytest.mark.parametrize("unsupported", [np.nan, np.inf, 1e-200, 1e200])
def test_qc14_channel_batch_defers_unsupported_noise_to_scalar(unsupported):
    amplitudes = np.ones((4, 80), dtype=np.float64)
    amplitudes[1, 23] = unsupported
    assert compute_qc14_standard_metrics_for_channels(
        amplitudes, target_idx=30, candidate_bin_indices=_candidate_indices(30),
    ) is None


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
