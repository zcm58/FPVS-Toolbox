"""Opt-in native inverse resolution and synthetic sensitivity diagnostics.

This producer-side diagnostic injects isolated sources through each model's
native forward matrix, then applies that same model's inverse. It does not
validate EEG preprocessing, spectral z scoring, inference, or real-data
localization. Sampled cross-talk, noise and channel-gain sensitivity remain
explicitly synthetic. No project data, GUI, or renderer is loaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.io.atomic_write import atomic_write

logger = logging.getLogger(__name__)


def summarize_source_recovery(
    *, points_mm: np.ndarray, recovered_amplitudes: np.ndarray,
    injected_source_indices: Sequence[int], leakage_radius_mm: float = 20.0,
) -> list[dict[str, Any]]:
    """Compute explicit Euclidean-distance and squared-amplitude metrics."""
    points = np.asarray(points_mm, dtype=float)
    amplitudes = np.asarray(recovered_amplitudes, dtype=float)
    indices = np.asarray(injected_source_indices, dtype=int)
    if points.ndim != 2 or points.shape[1] != 3 or not np.all(np.isfinite(points)):
        raise ValueError("Source points must be a finite N x 3 millimetre array.")
    if amplitudes.shape != (len(points), len(indices)) or not np.all(np.isfinite(amplitudes)):
        raise ValueError("Recovery amplitudes must be a finite source x probe array.")
    if np.any(amplitudes < 0) or np.any(indices < 0) or np.any(indices >= len(points)):
        raise ValueError("Amplitudes must be nonnegative and injected indices must exist.")
    radius = float(leakage_radius_mm)
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError("Leakage radius must be positive and finite.")
    rows = []
    for column, injected in enumerate(indices):
        values = amplitudes[:, column]
        peak = float(np.max(values))
        if peak <= 0:
            raise ValueError("A recovered probe has no measurable amplitude.")
        # Normalize first to avoid scale-dependent overflow/underflow.
        energy = np.square(values / peak)
        distances = np.linalg.norm(points - points[injected], axis=1)
        peak_indices = np.flatnonzero(values == peak)
        total = float(np.sum(energy))
        rows.append({
            "injected_source_index": int(injected),
            "injected_position_mm": points[injected].tolist(),
            "peak_source_indices": peak_indices.tolist(),
            "nearest_peak_distance_mm": float(np.min(distances[peak_indices])),
            "farthest_peak_distance_mm": float(np.max(distances[peak_indices])),
            "rms_spread_from_injected_source_mm": float(np.sqrt(np.sum(energy * distances**2) / total)),
            "energy_fraction_outside_radius": float(np.sum(energy[distances > radius]) / total),
            "injected_source_amplitude_relative_to_peak": float(values[injected] / peak),
        })
    return rows


def probe_native_inverse(
    *, leadfield: np.ndarray, points_mm: np.ndarray,
    estimate_amplitudes: Callable[[np.ndarray], np.ndarray],
    probe_count: int, orientation_components: Sequence[int],
) -> list[dict[str, Any]]:
    """Inject isolated native-basis sources at deterministic source indices."""
    points = np.asarray(points_mm, dtype=float)
    gain = np.asarray(leadfield, dtype=float)
    if gain.ndim != 2 or gain.shape[1] != 3 * len(points) or not np.all(np.isfinite(gain)):
        raise ValueError("Native leadfield must have three finite orientation columns per source.")
    if int(probe_count) < 1 or int(probe_count) != probe_count:
        raise ValueError("Probe count must be a positive integer.")
    components = tuple(orientation_components)
    if not components or any(component not in (0, 1, 2) for component in components):
        raise ValueError("Native orientation components must be 0, 1, or 2.")
    selected = np.linspace(0, len(points) - 1, min(int(probe_count), len(points)), dtype=int)
    probes = [(int(index), int(component)) for index in selected for component in components]
    # A 1 nAm isolated source produces EEG in V via the native leadfield.
    sensor_data = gain[:, [3 * index + component for index, component in probes]] * 1e-9
    rows = summarize_source_recovery(
        points_mm=points, recovered_amplitudes=estimate_amplitudes(sensor_data),
        injected_source_indices=[index for index, _ in probes],
    )
    for row, (_, component) in zip(rows, probes, strict=True):
        row["native_orientation_component"] = component
    return rows


def sampled_resolution_metrics(
    *, leadfield: np.ndarray, inverse_kernel: np.ndarray, points_mm: np.ndarray,
    probe_indices: Sequence[int], components: int,
) -> dict[str, Any]:
    """Sample PSF columns and CTF rows without allocating a full resolution matrix.

    Scalar cortical normal input/output uses absolute entries. Volume input and
    output each have three components; spatial summaries use the Frobenius norm
    of each 3x3 resolution block. These describe the linear inverse, not Z maps.
    """
    points = np.asarray(points_mm, dtype=float)
    gain = np.asarray(leadfield, dtype=float)
    kernel = np.asarray(inverse_kernel, dtype=float)
    indices = np.asarray(probe_indices, dtype=int)
    count = len(points)
    if components not in (1, 3) or gain.shape[1] != components * count or kernel.shape != (components * count, gain.shape[0]):
        raise ValueError("Resolution kernel/leadfield must align with one or three components per source.")
    if not np.all(np.isfinite(gain)) or not np.all(np.isfinite(kernel)) or not len(indices) or np.any(indices < 0) or np.any(indices >= count):
        raise ValueError("Resolution probes require finite matrices and existing source indices.")
    columns = (indices[:, None] * components + np.arange(components)).reshape(-1)
    psf = kernel @ gain[:, columns]
    ctf = kernel[columns] @ gain
    if components == 3:
        psf = np.sqrt(np.sum(psf.reshape(count, 3, len(indices), 3)**2, axis=(1, 3)))
        ctf = np.sqrt(np.sum(ctf.reshape(len(indices), 3, count, 3)**2, axis=(1, 3))).T
    else:
        psf, ctf = np.abs(psf), np.abs(ctf).T
    result: dict[str, Any] = {
        "scope": "sampled_linear_inverse_resolution_not_spectral_Z",
        "amplitude_reduction": "absolute_scalar" if components == 1 else "3_by_3_orientation_block_frobenius_norm",
        "source_components": components,
    }
    for name, values in (("point_spread_columns", psf), ("cross_talk_rows", ctf)):
        rows = summarize_source_recovery(points_mm=points, recovered_amplitudes=values, injected_source_indices=indices)
        for column, (row, index) in enumerate(zip(rows, indices, strict=True)):
            row["target_source_index"] = row.pop("injected_source_index")
            row["target_position_mm"] = row.pop("injected_position_mm")
            row["rms_spread_from_target_source_mm"] = row.pop("rms_spread_from_injected_source_mm")
            row["target_amplitude_relative_to_peak"] = row.pop("injected_source_amplitude_relative_to_peak")
            row["target_absolute_resolution_amplitude"] = float(values[index, column])
        result[name] = rows
    return result


def probe_inverse_sensitivity(
    *, leadfield: np.ndarray, points_mm: np.ndarray,
    estimate_amplitudes: Callable[[np.ndarray], np.ndarray], probe_count: int,
    seed: int = 20261104,
) -> dict[str, Any]:
    """Named 20%-RMS sensor noise and 10% gain perturbations on isolated probes."""
    gain = np.asarray(leadfield, dtype=float)
    points = np.asarray(points_mm, dtype=float)
    indices = np.linspace(0, len(points) - 1, min(probe_count, len(points)), dtype=int)
    sensor = gain[:, 3 * indices + 2] * 1e-9
    rng = np.random.default_rng(seed)
    noise = rng.normal(size=sensor.shape)
    noise *= .2 * np.sqrt(np.mean(sensor**2, axis=0)) / np.sqrt(np.mean(noise**2, axis=0))
    gain_multiplier = 1. + .1 * np.sin(np.arange(len(sensor)))
    scenarios = {
        "matched_model": sensor,
        "sensor_noise_20_percent_rms": sensor + noise,
        "sensor_gain_10_percent_sinusoidal": sensor * gain_multiplier[:, None],
    }
    return {
        "seed": seed, "native_orientation_component": 2,
        "scope": "one_seed_synthetic_sensor_noise_and_gain_perturbations_not_anatomical_or_empirical_accuracy",
        "scenarios": {
            name: summarize_source_recovery(points_mm=points, recovered_amplitudes=estimate_amplitudes(data), injected_source_indices=indices)
            for name, data in scenarios.items()
        },
    }


def run_fsaverage_source_recovery_benchmark(*, probe_count: int = 8) -> dict[str, Any]:
    """Run both current inverse configurations using installed template files."""
    import mne
    from mne.minimum_norm import apply_inverse

    from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import (
        DEFAULT_HAUK_SOURCE_PSD_LAMBDA2,
        HAUK_SOURCE_PSD_CORTICAL_NORMAL_METHOD_ID,
    )
    from Tools.LORETA_Visualizer.source_producers.eloreta_volume import (
        METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1,
    )
    from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import build_mne_fsaverage_source_psd_model
    from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_export import (
        build_mne_fsaverage_eloreta_volume_source_psd_model,
    )
    from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_hauk_source_psd_export import (
        DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS,
    )

    results = []
    for method in ("MNE", "eLORETA"):
        logger.info("Preparing %s matched-model recovery benchmark", method)
        model = (
            build_mne_fsaverage_source_psd_model(sfreq=200.0, allow_fetch_fsaverage=False)
            if method == "MNE" else build_mne_fsaverage_eloreta_volume_source_psd_model(
                sfreq=200.0, allow_fetch_fsaverage=False, prepare_inverse=True,
                channel_names=DEFAULT_ELECTRODE_NAMES_64,
                method_params=DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS,
            )
        )
        pick_ori = "normal" if method == "MNE" else "vector"
        params = {} if method == "MNE" else dict(model.method_params)

        def estimate_signed(sensor_data: np.ndarray) -> np.ndarray:
            evoked = mne.EvokedArray(sensor_data, model.info.copy(), tmin=0, nave=1, verbose=False)
            evoked.apply_proj(verbose=False)
            result = apply_inverse(
                evoked, model.inverse_operator, method=method,
                lambda2=DEFAULT_HAUK_SOURCE_PSD_LAMBDA2,
                pick_ori=pick_ori, prepared=method == "eLORETA",
                method_params=params or None, verbose=False,
            )
            return np.asarray(result.data)

        def estimate(sensor_data: np.ndarray) -> np.ndarray:
            data = estimate_signed(sensor_data)
            return np.abs(data) if method == "MNE" else np.sqrt(np.sum(np.abs(data)**2, axis=1))

        native_gain = model.native_leadfield if method == "MNE" else model.forward_model.leadfield
        points = model.forward_model.source_points
        kernel = estimate_signed(np.eye(len(model.info["ch_names"]))).reshape((-1, len(model.info["ch_names"])))
        indices = np.linspace(0, len(points) - 1, min(probe_count, len(points)), dtype=int)
        resolution = sampled_resolution_metrics(
            leadfield=native_gain[:, 2::3] if method == "MNE" else native_gain,
            inverse_kernel=kernel, points_mm=points, probe_indices=indices,
            components=1 if method == "MNE" else 3,
        )

        rows = probe_native_inverse(
            leadfield=model.native_leadfield if method == "MNE" else model.forward_model.leadfield,
            points_mm=model.forward_model.source_points, estimate_amplitudes=estimate,
            probe_count=probe_count, orientation_components=(2,) if method == "MNE" else (0, 1, 2),
        )
        results.append({
            "method_id": HAUK_SOURCE_PSD_CORTICAL_NORMAL_METHOD_ID if method == "MNE" else METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1,
            "model_preparation_signature": model.metadata["model_preparation_signature"],
            "source_count": len(model.forward_model.source_points),
            "lambda2": DEFAULT_HAUK_SOURCE_PSD_LAMBDA2,
            "pick_ori": pick_ori, "method_params": params,
            "coordinate_frame": "FreeSurfer fsaverage MRI surface RAS millimetres",
            "probes": rows,
            "sampled_resolution": resolution,
            "sensitivity": probe_inverse_sensitivity(
                leadfield=native_gain, points_mm=points, estimate_amplitudes=estimate, probe_count=probe_count,
            ),
        })
    return {
        "format": "fpvs-native-inverse-resolution-sensitivity-v2",
        "diagnostic_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "synthetic": True, "mne_version": mne.__version__, "numpy_version": np.__version__,
        "scope": "Native template inverse-only recovery, sampled PSFs/CTFs and named synthetic sensor perturbations.",
        "not_tested": ["real-data accuracy", "anatomical head-model mismatch", "empirical noise", "correlated sources", "FPVS spectral processing", "statistical calibration"],
        "probe_selection": "Evenly spaced source indices including endpoints; not an anatomical sample.",
        "injected_amplitude_nAm": 1.0, "leakage_radius_mm": 20.0,
        "spread_definition": "sqrt(sum(amplitude^2 * distance_from_injected_source^2) / sum(amplitude^2))",
        "leakage_definition": "sum(amplitude^2 at distance > 20 mm) / sum(amplitude^2)",
        "methods": results,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="JSON destination for this synthetic diagnostic.")
    parser.add_argument("--probe-count", type=int, default=8, help="Source locations per method (volume uses all three orientations).")
    args = parser.parse_args(argv)
    if args.probe_count < 1:
        parser.error("--probe-count must be positive")
    report = run_fsaverage_source_recovery_benchmark(probe_count=args.probe_count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(args.output) as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")
    logger.info("Synthetic source-recovery report written to %s", args.output)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
