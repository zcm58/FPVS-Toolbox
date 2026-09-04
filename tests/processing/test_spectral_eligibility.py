from __future__ import annotations

from fractions import Fraction

import pytest

from Main_App.processing.spectral_eligibility import (
    FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ,
    QC14_NOISE_CANDIDATE_OFFSETS,
    REASON_INSUFFICIENT_ODDBALL_CYCLES,
    REASON_NOISE_NOTCH_COLLISION,
    REASON_NOISE_WINDOW_ABOVE_LOW_PASS,
    REASON_TAGGED_HARMONIC_COLLISION,
    REASON_TARGET_NOTCH_COLLISION,
    SPECTRAL_ELIGIBILITY_METHOD_VERSION,
    TARGET_AMPLITUDE_AUDIT_ONLY,
    SpectralEligibilityError,
    intersect_eligible_harmonics,
    resolve_spectral_eligibility,
    spectral_eligibility_from_rows,
)
from Main_App.projects.frequency_protocol import (
    EXPECTED_CYCLES_SOURCE_MANUAL,
    FrequencyProtocol,
)


def _protocol(
    presentation_hz: object = 6,
    every_n: int = 5,
    *,
    cycles: int = 144,
) -> FrequencyProtocol:
    return FrequencyProtocol.from_recurrence(
        presentation_hz,
        every_n,
        expected_analyzed_oddball_cycles=cycles,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )


def _resolve(
    protocol: FrequencyProtocol | None = None,
    *,
    sfreq: object = 256,
    n_samples: int = 30_720,
    high_pass: object | None = "0.1",
    low_pass: object | None = 50,
    applied_high_pass: object | None = "0.1",
    applied_low_pass: object | None = 50,
    notch_centers: tuple[object, ...] = (),
):
    return resolve_spectral_eligibility(
        protocol=protocol or _protocol(),
        sampling_rate_hz=sfreq,
        analyzed_samples=n_samples,
        requested_high_pass_hz=high_pass,
        requested_low_pass_hz=low_pass,
        applied_high_pass_hz=applied_high_pass,
        applied_low_pass_hz=applied_low_pass,
        applied_notch_centers_hz=notch_centers,
    )


def test_default_protocol_uses_filter_domain_and_exceeds_legacy_ceiling() -> None:
    result = _resolve()

    assert result.method_version == SPECTRAL_ELIGIBILITY_METHOD_VERSION
    assert result.bin_width_hz == Fraction(1, 120)
    assert result.realized_oddball_cycles == 144
    assert result.targets[-1].target.frequency_hz == Fraction(246, 5)  # 49.2 Hz
    assert all(item.standard_metrics_available for item in result.targets)
    assert Fraction(84, 5) in {
        item.target.frequency_hz for item in result.eligible_targets
    }
    assert result.targets[4].target.presentation_harmonic_order == 1
    assert result.targets[4].target.oddball_harmonic_order == 5


def test_complete_ten_bin_window_controls_low_pass_edge() -> None:
    protocol = _protocol(10, 5, cycles=120)  # 2 Hz oddball, 60 seconds
    result = _resolve(
        protocol,
        n_samples=15_360,
        low_pass=50,
        applied_low_pass=50,
    )

    forty_eight = result.targets[23]
    fifty = result.targets[24]
    assert forty_eight.target.frequency_hz == 48
    assert forty_eight.standard_metrics_available
    assert fifty.target.frequency_hz == 50
    assert not fifty.standard_metrics_available
    assert REASON_NOISE_WINDOW_ABOVE_LOW_PASS in fifty.reason_codes


def test_exactly_ten_cycles_is_unavailable_and_eleven_is_eligible() -> None:
    ten_cycle_protocol = _protocol(10, 5, cycles=10)  # 2 Hz is exact at 256 Hz.
    ten = _resolve(
        ten_cycle_protocol,
        n_samples=1_280,
    )
    first_ten = ten.targets[0]
    assert REASON_INSUFFICIENT_ODDBALL_CYCLES in first_ten.reason_codes
    assert REASON_TAGGED_HARMONIC_COLLISION in first_ten.reason_codes
    assert not first_ten.standard_metrics_available

    eleven_cycle_protocol = _protocol(10, 5, cycles=11)
    eleven_samples = Fraction(11 * 256, 2)
    assert eleven_samples.denominator == 1
    eleven = _resolve(
        eleven_cycle_protocol,
        n_samples=eleven_samples.numerator,
    )
    assert eleven.targets[0].standard_metrics_available


def test_target_notch_collision_retains_only_audit_amplitude() -> None:
    protocol = _protocol(10, 5, cycles=120)
    result = _resolve(
        protocol,
        n_samples=15_360,
        low_pass=60,
        applied_low_pass=60,
        notch_centers=(50,),
    )

    target = result.targets[24]
    assert target.target.frequency_hz == 50
    assert target.target_amplitude_status == TARGET_AMPLITUDE_AUDIT_ONLY
    assert REASON_TARGET_NOTCH_COLLISION in target.reason_codes
    assert not target.bca_available
    assert not target.snr_available
    assert not target.local_z_available


def test_noise_bin_notch_collision_does_not_disable_target_amplitude() -> None:
    protocol = _protocol(3, 10, cycles=30)  # 0.3 Hz, 100 seconds
    result = _resolve(
        protocol,
        n_samples=25_600,
        low_pass=55,
        applied_low_pass=55,
        notch_centers=(50,),
    )

    target = result.targets[164]  # 49.5 Hz; the notch boundary is not attenuated.
    assert target.target.frequency_hz == Fraction(99, 2)
    assert target.target_amplitude_status == "available"
    assert REASON_TARGET_NOTCH_COLLISION not in target.reason_codes
    assert REASON_NOISE_NOTCH_COLLISION in target.reason_codes
    assert target.noise_notch_collisions
    assert not target.standard_metrics_available


def test_notch_half_width_boundary_is_not_a_collision() -> None:
    protocol = _protocol(2, 10, cycles=20)  # 0.2 Hz, 100 seconds.
    without_notch = _resolve(
        protocol,
        n_samples=25_600,
        low_pass=55,
        applied_low_pass=55,
    )
    with_notch = _resolve(
        protocol,
        n_samples=25_600,
        low_pass=55,
        applied_low_pass=55,
        notch_centers=(50,),
    )

    # 49.4 Hz has its +10 bin at 49.5 Hz, exactly on the half-width edge.
    item_without = without_notch.targets[246]
    item_with = with_notch.targets[246]
    assert item_with.target.frequency_hz == Fraction(247, 5)
    assert item_with.reason_codes == item_without.reason_codes


def test_missing_or_mismatched_applied_filter_evidence_is_a_hard_failure() -> None:
    with pytest.raises(SpectralEligibilityError, match="metadata is missing"):
        _resolve(applied_low_pass=None)

    with pytest.raises(SpectralEligibilityError, match="does not match"):
        _resolve(applied_low_pass=49.9)

    tolerated = _resolve(
        applied_low_pass=Fraction(50) - FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ,
    )
    assert tolerated.applied_filter.applied_low_pass_hz == (
        Fraction(50) - FILTER_EDGE_REPRESENTATION_TOLERANCE_HZ
    )


def test_omitted_edges_require_explicit_dc_and_nyquist_metadata() -> None:
    protocol = _protocol(cycles=24)
    n_samples = 5_120
    result = _resolve(
        protocol,
        n_samples=n_samples,
        high_pass=None,
        low_pass=None,
        applied_high_pass=0,
        applied_low_pass=128,
    )

    assert result.applied_filter.applied_high_pass_hz == 0
    assert result.applied_filter.applied_low_pass_hz == 128


def test_repeating_decimal_rate_keeps_exact_bin_and_harmonic_identity() -> None:
    protocol = _protocol(10, 3, cycles=20)
    result = _resolve(
        protocol,
        n_samples=1_536,
        low_pass=50,
        applied_low_pass=50,
    )

    assert protocol.oddball_rate_hz == Fraction(10, 3)
    assert result.bin_width_hz == Fraction(1, 6)
    assert result.targets[0].target_bin_index == 20
    assert result.targets[2].target.frequency_hz == 10
    assert result.targets[2].target.presentation_harmonic_order == 1


def test_candidate_offsets_are_complete_symmetric_qc14_set() -> None:
    result = _resolve()
    first = result.targets[0]

    assert QC14_NOISE_CANDIDATE_OFFSETS == tuple(
        [*range(-10, -1), *range(2, 11)]
    )
    assert len(first.noise_candidate_bin_indices) == 18
    assert tuple(
        index - first.target_bin_index
        for index in first.noise_candidate_bin_indices
    ) == QC14_NOISE_CANDIDATE_OFFSETS


def test_result_fingerprint_and_rows_bind_protocol_filter_grid_and_notches() -> None:
    first = _resolve(notch_centers=(50,))
    second = _resolve(notch_centers=(50,))
    changed = _resolve(notch_centers=())

    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != changed.fingerprint
    rows = first.to_rows()
    assert rows[0]["Eligibility Fingerprint"] == first.fingerprint
    assert rows[0]["Protocol Fingerprint"] == first.protocol.fingerprint
    assert rows[0]["Noise Candidate FFT Bins"]

    restored = spectral_eligibility_from_rows(rows, protocol=first.protocol)
    assert restored.fingerprint == first.fingerprint


def test_exported_eligibility_cannot_override_canonical_resolver() -> None:
    result = _resolve(notch_centers=(50,))
    rows = result.to_rows()
    rows[0]["BCA Available"] = not bool(rows[0]["BCA Available"])

    with pytest.raises(SpectralEligibilityError, match="canonical resolver"):
        spectral_eligibility_from_rows(rows, protocol=result.protocol)


def test_intersection_uses_only_standard_eligible_orders() -> None:
    default = _resolve()
    notched = _resolve(notch_centers=(24,))
    common = intersect_eligible_harmonics((default, notched))

    assert common
    assert {target.oddball_harmonic_order for target in common} == {
        item.target.oddball_harmonic_order for item in notched.eligible_targets
    }


def test_realized_cycle_mismatch_and_off_bin_grid_are_hard_failures() -> None:
    with pytest.raises(SpectralEligibilityError, match="expected analyzed"):
        _resolve(n_samples=30_720 - 640)

    protocol = _protocol(cycles=143)
    with pytest.raises(SpectralEligibilityError, match="exactly on a bin"):
        _resolve(protocol, n_samples=30_507)
