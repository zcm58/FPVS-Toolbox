from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from Tools.Free_Harmonic_Clustering.models import (
    FreeHarmonicMethodSpec,
    FreeHarmonicPreparationError,
    HarmonicSelectionMode,
    NoHarmonicsSelectedError,
)
from Tools.Free_Harmonic_Clustering.preparation import (
    build_frequency_window_plan,
    compute_harmonic_z,
    compute_participant_snr,
    l2_normalize_snr,
    select_harmonics,
    select_snr_harmonics,
)


def _header(*, spacing_hz: float = 0.025, upper_hz: float = 5.0) -> list[str]:
    frequencies = np.arange(
        int(round(upper_hz / spacing_hz)) + 1,
        dtype=np.float64,
    ) * spacing_hz
    return ["Electrode", *(f"{frequency:.6f}_Hz" for frequency in frequencies)]


def _selected_spectrum(plan, *, target_value: float = 1.0) -> np.ndarray:
    spectrum = 1.0 + np.arange(
        len(plan.selected_frequency_columns),
        dtype=np.float64,
    ) % 7 * 0.05
    spectrum[plan.target_selected_indices] = target_value
    return spectrum


def test_frequency_plan_uses_physical_window_and_excludes_adjacent_bins() -> None:
    spec = FreeHarmonicMethodSpec(max_harmonic_hz=1.2)

    plan = build_frequency_window_plan(_header(), spec)

    target_index = int(plan.target_selected_indices[0])
    target_hz = float(plan.selected_frequencies_hz[target_index])
    noise_hz = plan.selected_frequencies_hz[plan.noise_selected_indices[0]]
    assert target_hz == pytest.approx(1.2)
    assert noise_hz.tolist() == pytest.approx([1.1, 1.125, 1.15, 1.25, 1.275, 1.3])
    for excluded_hz in (1.175, 1.2, 1.225):
        assert not np.any(np.isclose(noise_hz, excluded_hz))
    assert plan.required_columns[0] == "Electrode"
    assert plan.noise_selected_indices.shape == (1, 6)


def test_frequency_plan_requires_at_least_four_finite_noise_bins() -> None:
    spec = FreeHarmonicMethodSpec(max_harmonic_hz=1.2)

    with pytest.raises(FreeHarmonicPreparationError, match="at least four"):
        build_frequency_window_plan(
            _header(spacing_hz=0.05, upper_hz=1.35),
            spec,
        )


def test_harmonic_z_uses_sample_standard_deviation() -> None:
    spec = FreeHarmonicMethodSpec(max_harmonic_hz=1.2)
    plan = build_frequency_window_plan(_header(), spec)
    spectrum = np.zeros(len(plan.selected_frequency_columns), dtype=np.float64)
    noise = np.array([1.0, 2.0, 4.0, 5.0, 7.0, 8.0])
    spectrum[plan.noise_selected_indices[0]] = noise
    spectrum[plan.target_selected_indices[0]] = 12.0

    actual = compute_harmonic_z(spectrum, plan, ddof=1)

    expected = (12.0 - noise.mean()) / noise.std(ddof=1)
    population_result = (12.0 - noise.mean()) / noise.std(ddof=0)
    assert actual.tolist() == pytest.approx([expected])
    assert actual[0] != pytest.approx(population_result)


def test_selection_is_strict_and_fills_through_highest_without_base_overlaps() -> None:
    spec = FreeHarmonicMethodSpec(
        base_frequency_hz=2.4,
        max_harmonic_hz=4.8,
    )
    plan = build_frequency_window_plan(_header(), spec)
    assert plan.candidate_orders.tolist() == [1, 3]
    assert plan.excluded_base_orders.tolist() == [2, 4]
    grand = _selected_spectrum(plan, target_value=1.0)
    highest_index = int(np.flatnonzero(plan.candidate_orders == 3)[0])
    grand[plan.target_selected_indices[highest_index]] = 20.0

    z = compute_harmonic_z(grand, plan, ddof=1)
    equal_threshold_spec = replace(spec, harmonic_z_threshold=float(z[highest_index]))
    with pytest.raises(NoHarmonicsSelectedError, match="No eligible") as captured:
        select_harmonics(grand, grand, plan, equal_threshold_spec)
    assert captured.value.code == "NO_HARMONICS_SELECTED"
    assert captured.value.candidate_orders.tolist() == plan.candidate_orders.tolist()
    assert captured.value.arm_a_z == pytest.approx(captured.value.arm_b_z)
    assert captured.value.z_threshold == equal_threshold_spec.harmonic_z_threshold

    selection = select_harmonics(grand, grand, plan, spec)
    assert selection.highest_detected_order == 3
    assert selection.selected_orders.tolist() == [1, 3]
    assert selection.detected_arm_a.tolist() == [False, True]


def test_participant_snr_and_l2_normalization_are_vectorized_per_matrix() -> None:
    spec = FreeHarmonicMethodSpec(max_harmonic_hz=3.6)
    plan = build_frequency_window_plan(_header(), spec)
    amplitudes = np.ones(
        (2, 4, len(plan.selected_frequency_columns)),
        dtype=np.float64,
    )
    amplitudes[0, :, plan.target_selected_indices] = 2.0
    amplitudes[1, :, plan.target_selected_indices] = 3.0

    snr = compute_participant_snr(amplitudes, plan)

    assert snr.shape == (2, 4, 3)
    assert snr[0] == pytest.approx(np.full((4, 3), 2.0))
    assert snr[1] == pytest.approx(np.full((4, 3), 3.0))

    grand = _selected_spectrum(plan, target_value=20.0)
    selection = select_harmonics(grand, grand, plan, spec)
    selected = select_snr_harmonics(snr, selection)
    normalized = l2_normalize_snr(selected)
    assert normalized.flags.c_contiguous
    assert np.sqrt(np.sum(np.square(normalized), axis=(1, 2))) == pytest.approx(
        np.ones(2)
    )


def test_participant_snr_rejects_negative_fullfft_amplitude() -> None:
    spec = FreeHarmonicMethodSpec(max_harmonic_hz=1.2)
    plan = build_frequency_window_plan(_header(), spec)
    amplitudes = np.ones((2, len(plan.selected_frequency_columns)))
    amplitudes[0, 0] = -0.01

    with pytest.raises(FreeHarmonicPreparationError, match="non-negative"):
        compute_participant_snr(amplitudes, plan)


def test_fixed_highest_mode_uses_declared_fill_through_without_z_detection() -> None:
    spec = FreeHarmonicMethodSpec(
        base_frequency_hz=2.4,
        max_harmonic_hz=4.8,
        harmonic_selection_mode=HarmonicSelectionMode.FIXED_HIGHEST,
        fixed_highest_harmonic_order=3,
        harmonic_z_threshold=1_000.0,
    )
    plan = build_frequency_window_plan(_header(), spec)
    grand = _selected_spectrum(plan, target_value=1.0)

    selection = select_harmonics(grand, grand, plan, spec)

    assert selection.selection_mode is HarmonicSelectionMode.FIXED_HIGHEST
    assert selection.fixed_highest_harmonic_order == 3
    assert selection.selected_orders.tolist() == [1, 3]
    assert selection.highest_detected_order is None
    assert not np.any(selection.detected_arm_a)
    assert np.all(np.isfinite(selection.arm_a_z))


def test_fixed_highest_mode_rejects_base_overlap_or_unavailable_order() -> None:
    base_overlap = FreeHarmonicMethodSpec(
        base_frequency_hz=2.4,
        max_harmonic_hz=4.8,
        harmonic_selection_mode="fixed_highest",
        fixed_highest_harmonic_order=2,
    )
    plan = build_frequency_window_plan(_header(), base_overlap)
    grand = _selected_spectrum(plan)
    with pytest.raises(FreeHarmonicPreparationError, match="overlaps the base"):
        select_harmonics(grand, grand, plan, base_overlap)

    unavailable = replace(base_overlap, fixed_highest_harmonic_order=5)
    with pytest.raises(FreeHarmonicPreparationError, match="exceeds the available"):
        select_harmonics(grand, grand, plan, unavailable)


def test_method_spec_rejects_ambiguous_harmonic_selection_configuration() -> None:
    with pytest.raises(ValueError, match="must be omitted"):
        FreeHarmonicMethodSpec(fixed_highest_harmonic_order=2)
    with pytest.raises(ValueError, match="requires a positive integer"):
        FreeHarmonicMethodSpec(harmonic_selection_mode="fixed_highest")
