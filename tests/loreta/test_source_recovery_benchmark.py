from __future__ import annotations

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.source_recovery_benchmark import (
    probe_native_inverse,
    sampled_resolution_metrics,
    probe_inverse_sensitivity,
    summarize_source_recovery,
)


def test_recovery_metrics_distinguish_peak_error_spread_and_leakage() -> None:
    rows = summarize_source_recovery(
        points_mm=np.array([[0, 0, 0], [10, 0, 0], [30, 0, 0]], dtype=float),
        recovered_amplitudes=np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 1.0]]),
        injected_source_indices=[0, 0],
    )
    assert rows[0]["nearest_peak_distance_mm"] == 0
    assert rows[0]["rms_spread_from_injected_source_mm"] == 0
    assert rows[0]["energy_fraction_outside_radius"] == 0
    assert rows[1]["peak_source_indices"] == [1, 2]
    assert rows[1]["nearest_peak_distance_mm"] == 10
    assert rows[1]["farthest_peak_distance_mm"] == 30
    assert rows[1]["rms_spread_from_injected_source_mm"] == pytest.approx(np.sqrt(500))
    assert rows[1]["energy_fraction_outside_radius"] == 0.5


def test_native_inverse_probes_preserve_source_and_orientation_identity() -> None:
    gain = np.eye(9)
    calls = []

    def estimate(sensor: np.ndarray) -> np.ndarray:
        calls.append(sensor.copy())
        return np.linalg.norm(sensor.reshape(3, 3, -1), axis=1)

    rows = probe_native_inverse(
        leadfield=gain, points_mm=np.array([[0, 0, 0], [10, 0, 0], [20, 0, 0]]),
        estimate_amplitudes=estimate, probe_count=2, orientation_components=(0, 1, 2),
    )
    assert [row["injected_source_index"] for row in rows] == [0, 0, 0, 2, 2, 2]
    assert [row["native_orientation_component"] for row in rows] == [0, 1, 2, 0, 1, 2]
    assert all(row["nearest_peak_distance_mm"] == 0 for row in rows)
    assert all(row["rms_spread_from_injected_source_mm"] == 0 for row in rows)
    np.testing.assert_allclose(calls[0], gain[:, [0, 1, 2, 6, 7, 8]] * 1e-9, atol=0)


def test_cortical_probe_uses_only_native_normal_column() -> None:
    columns = []

    def estimate(sensor: np.ndarray) -> np.ndarray:
        columns.append(sensor)
        return np.array([[1.0], [0.0]])

    probe_native_inverse(
        leadfield=np.arange(12, dtype=float).reshape(2, 6),
        points_mm=np.array([[0, 0, 0], [10, 0, 0]]), estimate_amplitudes=estimate,
        probe_count=1, orientation_components=(2,),
    )
    np.testing.assert_allclose(columns[0].ravel(), [2e-9, 8e-9], atol=0)


def test_point_spread_and_cross_talk_sample_different_resolution_directions():
    # R = K G: input 1 leaks to output 0, while input 0 is localized.
    resolution = np.array([[1., .5, 0.], [0., 1., 0.], [0., 0., 1.]])
    result = sampled_resolution_metrics(
        leadfield=np.eye(3), inverse_kernel=resolution,
        points_mm=np.array([[0., 0, 0], [30., 0, 0], [60., 0, 0]]),
        probe_indices=[0], components=1,
    )
    psf = result["point_spread_columns"][0]
    ctf = result["cross_talk_rows"][0]
    assert psf["energy_fraction_outside_radius"] == 0
    assert ctf["energy_fraction_outside_radius"] == pytest.approx(.2)
    assert ctf["rms_spread_from_target_source_mm"] > 0
    assert ctf["target_absolute_resolution_amplitude"] == 1


def test_vector_resolution_block_metrics_are_orientation_rotation_invariant():
    gain = np.eye(6)
    rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    kernel = np.zeros((6, 6))
    kernel[:3, :3] = rotation
    kernel[3:, 3:] = rotation
    result = sampled_resolution_metrics(
        leadfield=gain, inverse_kernel=kernel,
        points_mm=np.array([[0., 0, 0], [30., 0, 0]]), probe_indices=[0, 1], components=3,
    )
    assert result["amplitude_reduction"] == "3_by_3_orientation_block_frobenius_norm"
    assert [row["target_absolute_resolution_amplitude"] for row in result["cross_talk_rows"]] == pytest.approx([np.sqrt(3), np.sqrt(3)])
    assert all(row["energy_fraction_outside_radius"] == 0 for row in result["point_spread_columns"])


def test_synthetic_noise_sensitivity_is_reproducible_and_reports_leakage():
    kwargs = dict(
        leadfield=np.eye(6), points_mm=np.array([[0., 0, 0], [30., 0, 0]]),
        estimate_amplitudes=lambda values: np.linalg.norm(values.reshape(2, 3, -1), axis=1),
        probe_count=2,
    )
    result = probe_inverse_sensitivity(**kwargs)
    assert result == probe_inverse_sensitivity(**kwargs)
    assert result["scenarios"]["matched_model"][0]["energy_fraction_outside_radius"] == 0
    assert result["scenarios"]["sensor_noise_20_percent_rms"][0]["energy_fraction_outside_radius"] > 0


@pytest.mark.parametrize("amplitudes", [np.array([[0.0]]), np.array([[np.nan]]), np.array([[-1.0]])])
def test_recovery_rejects_uninformative_or_invalid_maps(amplitudes: np.ndarray) -> None:
    with pytest.raises(ValueError):
        summarize_source_recovery(points_mm=np.zeros((1, 3)), recovered_amplitudes=amplitudes, injected_source_indices=[0])
