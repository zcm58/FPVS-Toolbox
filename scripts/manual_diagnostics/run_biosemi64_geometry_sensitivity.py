"""Measure the isolated effect of BioSemi64 versus ``standard_1005`` geometry.

This diagnostic holds channel signals and bad-channel decisions fixed, runs
MNE's EEG interpolation with each montage, and compares the resulting time
series and exact-bin FPVS metrics.  It is intentionally separate from routine
verification and never modifies a managed FPVS project.

Synthetic protocol
------------------
The default invocation uses a deterministic, spatially smooth 64-channel
signal and nine prespecified bad-channel patterns: a zero-bad control, four
isolated regional channels, and four regional clusters.  The output directory
receives JSON and CSV evidence suitable for independent review.

Optional direct-BDF protocol
----------------------------
One BDF can be supplied explicitly.  Its header must contain every canonical
BioSemi64 anatomical label exactly once; A/B labels and ordinal inference are
rejected.  The caller must explicitly provide the fixed bad-channel list (or
``none``).  This mode is a bounded geometry comparison, not a replacement for
a representative full-project reprocessing study.

Examples
--------
python scripts/manual_diagnostics/run_biosemi64_geometry_sensitivity.py \
    --output-dir .codex-tmp/qc15-biosemi64-sensitivity-v1

python scripts/manual_diagnostics/run_biosemi64_geometry_sensitivity.py \
    --output-dir .codex-tmp/qc15-one-recording \
    --input-bdf D:/study/P001.bdf --bad-channels Fp1,AF7
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence


_SCRIPT_PATH = Path(__file__).resolve()
_REPOSITORY_ROOT = _SCRIPT_PATH.parents[2]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

import mne  # noqa: E402
import numpy as np  # noqa: E402


def _load_noise_stats_helper() -> Any:
    """Load the production numeric helper without importing the Stats GUI."""

    module_path = _SOURCE_ROOT / "Tools" / "Stats" / "analysis" / "noise_utils.py"
    specification = importlib.util.spec_from_file_location(
        "_fpvs_qc15_noise_utils",
        module_path,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot load production noise helper: {module_path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.compute_noise_stats_for_bin_channels


compute_noise_stats_for_bin_channels = _load_noise_stats_helper()


PROTOCOL_ID = "qc15_biosemi64_geometry_sensitivity_v1"
SCHEMA_VERSION = 1
STANDARD_MONTAGE = "standard_1005"
CANONICAL_MONTAGE = "biosemi64"
SYNTHETIC_SEED = 150064
SYNTHETIC_SFREQ_HZ = 256.0
SYNTHETIC_DURATION_SEC = 40.0
TARGET_FREQUENCIES_HZ = (1.2, 2.4, 3.6, 4.8, 7.2)
LOCAL_Z_THRESHOLDS = (1.64, 3.29)
INTERPOLATION_MODE = "accurate"
INTERPOLATION_METHOD = "spline"
INTERPOLATION_ORIGIN = "auto"
NOISE_HALF_WIDTH_BINS = 10
NOISE_MINIMUM_CANDIDATE_BINS = 4

# Freeze the anatomical identity independently of any acquisition header or
# future application setting.  This order is MNE's built-in BioSemi64 order
# and matches BioSemi's standard 64-channel 10/20 layout.
BIOSEMI64_CHANNELS = (
    "Fp1",
    "AF7",
    "AF3",
    "F1",
    "F3",
    "F5",
    "F7",
    "FT7",
    "FC5",
    "FC3",
    "FC1",
    "C1",
    "C3",
    "C5",
    "T7",
    "TP7",
    "CP5",
    "CP3",
    "CP1",
    "P1",
    "P3",
    "P5",
    "P7",
    "P9",
    "PO7",
    "PO3",
    "O1",
    "Iz",
    "Oz",
    "POz",
    "Pz",
    "CPz",
    "Fpz",
    "Fp2",
    "AF8",
    "AF4",
    "AFz",
    "Fz",
    "F2",
    "F4",
    "F6",
    "F8",
    "FT8",
    "FC6",
    "FC4",
    "FC2",
    "FCz",
    "Cz",
    "C2",
    "C4",
    "C6",
    "T8",
    "TP8",
    "CP6",
    "CP4",
    "CP2",
    "P2",
    "P4",
    "P6",
    "P8",
    "P10",
    "PO8",
    "PO4",
    "O2",
)

SYNTHETIC_BAD_CHANNEL_SCENARIOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("zero_bad_control", ()),
    ("isolated_frontal", ("Fp1",)),
    ("isolated_temporal", ("T7",)),
    ("isolated_central", ("Cz",)),
    ("isolated_posterior", ("Oz",)),
    ("cluster_frontal", ("Fp1", "AF7", "AF3")),
    ("cluster_temporal", ("FT7", "T7", "TP7")),
    ("cluster_central", ("C3", "Cz", "C4")),
    ("cluster_posterior", ("PO7", "Oz", "PO8")),
)

_COORDINATE_FIELDS = (
    "channel",
    "standard_1005_x_m",
    "standard_1005_y_m",
    "standard_1005_z_m",
    "biosemi64_x_m",
    "biosemi64_y_m",
    "biosemi64_z_m",
    "head_space_distance_mm",
    "fitted_sphere_angular_difference_deg",
    "fitted_sphere_radius_difference_mm",
)
_TIME_FIELDS = (
    "scenario",
    "bad_channels",
    "bad_channel_count",
    "channel",
    "is_interpolated_channel",
    "stage",
    "standard_1005_vs_biosemi64_rms_uv",
    "standard_1005_vs_biosemi64_max_abs_uv",
    "standard_1005_vs_truth_rms_uv",
    "biosemi64_vs_truth_rms_uv",
)
_TARGET_METRIC_FIELDS = (
    "scenario",
    "bad_channels",
    "bad_channel_count",
    "montage",
    "stage",
    "channel",
    "is_interpolated_channel",
    "target_frequency_hz",
    "target_bin_index",
    "fft_amplitude_uv",
    "noise_mean_uv",
    "noise_std_uv",
    "bca_uv",
    "snr",
    "local_z",
    "local_z_gt_1_64",
    "local_z_gt_3_29",
)
_TARGET_DIFFERENCE_FIELDS = (
    "scenario",
    "bad_channels",
    "bad_channel_count",
    "stage",
    "channel",
    "is_interpolated_channel",
    "target_frequency_hz",
    "target_bin_index",
    "fft_amplitude_difference_uv",
    "fft_amplitude_absolute_difference_uv",
    "fft_amplitude_relative_difference_percent",
    "bca_difference_uv",
    "bca_absolute_difference_uv",
    "bca_relative_difference_percent",
    "snr_difference",
    "local_z_difference",
    "local_z_gt_1_64_changed",
    "local_z_gt_3_29_changed",
)
_DECISION_FIELDS = (
    "scenario",
    "bad_channels",
    "bad_channel_count",
    "stage",
    "channel",
    "is_interpolated_channel",
    "target_frequency_hz",
    "threshold",
    "standard_1005_decision",
    "biosemi64_decision",
    "standard_1005_local_z",
    "biosemi64_local_z",
)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Compare fixed bad-channel interpolation under MNE standard_1005 and biosemi64 geometry.")
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Dedicated directory for the JSON summary and CSV evidence.",
    )
    parser.add_argument(
        "--input-bdf",
        type=Path,
        default=None,
        help=(
            "Optional explicit BDF. Every anatomical BioSemi64 name must be "
            "present exactly once; A/B or ordinal mapping is never inferred."
        ),
    )
    parser.add_argument(
        "--bad-channels",
        default=None,
        help=(
            "Comma-separated canonical bad-channel names for --input-bdf, or "
            "the literal 'none'. Required when --input-bdf is supplied."
        ),
    )
    parser.add_argument(
        "--analysis-start-sec",
        type=float,
        default=0.0,
        help="Start of the direct-BDF comparison interval (default: 0).",
    )
    parser.add_argument(
        "--analysis-duration-sec",
        type=float,
        default=SYNTHETIC_DURATION_SEC,
        help="Length of the direct-BDF comparison interval (default: 40 s).",
    )
    args = parser.parse_args(argv)
    if args.input_bdf is None and args.bad_channels is not None:
        parser.error("--bad-channels is only valid with --input-bdf.")
    if args.input_bdf is not None and args.bad_channels is None:
        parser.error("--input-bdf requires an explicit --bad-channels list or 'none'.")
    if args.analysis_start_sec < 0:
        parser.error("--analysis-start-sec must be non-negative.")
    if args.analysis_duration_sec <= 0:
        parser.error("--analysis-duration-sec must be positive.")
    return args


def _canonical_montage_channels() -> tuple[str, ...]:
    channels = tuple(mne.channels.make_standard_montage(CANONICAL_MONTAGE).ch_names)
    if channels != BIOSEMI64_CHANNELS:
        raise RuntimeError(
            f"The installed MNE BioSemi64 montage identity/order differs from the frozen {PROTOCOL_ID} channel list."
        )
    return channels


def _make_info_with_montage(
    montage_name: str,
    *,
    sfreq: float,
) -> mne.Info:
    info = mne.create_info(list(BIOSEMI64_CHANNELS), sfreq, ch_types="eeg")
    raw = mne.io.RawArray(
        np.zeros((len(BIOSEMI64_CHANNELS), 2), dtype=float),
        info,
        verbose=False,
    )
    raw.set_montage(
        mne.channels.make_standard_montage(montage_name),
        match_case=True,
        on_missing="raise",
        verbose=False,
    )
    positions = np.asarray([ch["loc"][:3] for ch in raw.info["chs"]])
    if positions.shape != (64, 3) or not np.isfinite(positions).all():
        raise RuntimeError(f"{montage_name} did not provide 64 finite head coordinates.")
    return raw.info.copy()


def _fit_sphere(info: mne.Info) -> tuple[float, np.ndarray]:
    # Public in supported MNE versions even when ``mne.bem`` is lazy-loaded.
    from mne.bem import fit_sphere_to_headshape

    radius_m, origin_head_m, _ = fit_sphere_to_headshape(
        info,
        units="m",
        verbose=False,
    )
    return float(radius_m), np.asarray(origin_head_m, dtype=float)


def build_coordinate_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return head-frame geometry differences and fitted-sphere identities."""

    standard_info = _make_info_with_montage(
        STANDARD_MONTAGE,
        sfreq=SYNTHETIC_SFREQ_HZ,
    )
    biosemi_info = _make_info_with_montage(
        CANONICAL_MONTAGE,
        sfreq=SYNTHETIC_SFREQ_HZ,
    )
    standard_positions = np.asarray([ch["loc"][:3] for ch in standard_info["chs"]])
    biosemi_positions = np.asarray([ch["loc"][:3] for ch in biosemi_info["chs"]])
    standard_radius, standard_origin = _fit_sphere(standard_info)
    biosemi_radius, biosemi_origin = _fit_sphere(biosemi_info)

    rows: list[dict[str, Any]] = []
    for index, channel in enumerate(BIOSEMI64_CHANNELS):
        standard_position = standard_positions[index]
        biosemi_position = biosemi_positions[index]
        standard_vector = standard_position - standard_origin
        biosemi_vector = biosemi_position - biosemi_origin
        cosine = float(
            np.dot(standard_vector, biosemi_vector) / (np.linalg.norm(standard_vector) * np.linalg.norm(biosemi_vector))
        )
        angle_degrees = math.degrees(math.acos(float(np.clip(cosine, -1.0, 1.0))))
        rows.append(
            {
                "channel": channel,
                "standard_1005_x_m": float(standard_position[0]),
                "standard_1005_y_m": float(standard_position[1]),
                "standard_1005_z_m": float(standard_position[2]),
                "biosemi64_x_m": float(biosemi_position[0]),
                "biosemi64_y_m": float(biosemi_position[1]),
                "biosemi64_z_m": float(biosemi_position[2]),
                "head_space_distance_mm": float(np.linalg.norm(standard_position - biosemi_position) * 1_000.0),
                "fitted_sphere_angular_difference_deg": float(angle_degrees),
                "fitted_sphere_radius_difference_mm": float(
                    (np.linalg.norm(standard_vector) - np.linalg.norm(biosemi_vector)) * 1_000.0
                ),
            }
        )

    sphere_identity = {
        STANDARD_MONTAGE: {
            "radius_m": standard_radius,
            "origin_head_m": standard_origin.tolist(),
        },
        CANONICAL_MONTAGE: {
            "radius_m": biosemi_radius,
            "origin_head_m": biosemi_origin.tolist(),
        },
    }
    return rows, sphere_identity


def _biosemi_unit_directions() -> np.ndarray:
    info = _make_info_with_montage(CANONICAL_MONTAGE, sfreq=SYNTHETIC_SFREQ_HZ)
    _, origin = _fit_sphere(info)
    positions = np.asarray([ch["loc"][:3] for ch in info["chs"]]) - origin
    return positions / np.linalg.norm(positions, axis=1, keepdims=True)


def _smooth_spatial_weights(
    directions: np.ndarray,
    center_channels: Sequence[str],
    *,
    width: float,
) -> np.ndarray:
    indices = [BIOSEMI64_CHANNELS.index(channel) for channel in center_channels]
    similarity = directions @ directions[indices].T
    weights = np.exp((similarity - 1.0) / width).sum(axis=1)
    maximum = float(np.max(weights))
    if maximum <= 0:
        raise RuntimeError("Synthetic spatial weights are degenerate.")
    return weights / maximum


def generate_synthetic_data() -> tuple[np.ndarray, float, dict[str, Any]]:
    """Create deterministic, spatially correlated EEG in volts."""

    _canonical_montage_channels()
    sfreq = SYNTHETIC_SFREQ_HZ
    sample_count = int(round(SYNTHETIC_DURATION_SEC * sfreq))
    time = np.arange(sample_count, dtype=float) / sfreq
    directions = _biosemi_unit_directions()
    rng = np.random.default_rng(SYNTHETIC_SEED)

    # A reproducible, smooth 1/f-like background.  Latent time courses are
    # mixed through overlapping scalp fields, with a small sensor-local term.
    latent_count = 16
    latent = rng.normal(size=(latent_count, sample_count))
    frequencies = np.fft.rfftfreq(sample_count, d=1.0 / sfreq)
    shaping = 1.0 / np.sqrt(np.maximum(frequencies, 0.2))
    shaping[0] = 0.0
    latent_spectrum = np.fft.rfft(latent, axis=1) * shaping[None, :]
    latent = np.fft.irfft(latent_spectrum, n=sample_count, axis=1)
    latent /= np.std(latent, axis=1, keepdims=True)

    centers = rng.choice(len(BIOSEMI64_CHANNELS), size=latent_count, replace=False)
    similarities = directions @ directions[centers].T
    mixing = np.exp((similarities - 1.0) / 0.20)
    mixing /= np.sqrt(np.sum(mixing**2, axis=1, keepdims=True))
    smooth_noise_uv = 3.2 * (mixing @ latent)
    local_noise_uv = 0.45 * rng.normal(size=(len(BIOSEMI64_CHANNELS), sample_count))
    data_uv = smooth_noise_uv + local_noise_uv

    target_specs = (
        (1.2, ("PO8", "O2"), 2.8, 0.00, 0.11),
        (2.4, ("PO7", "O1"), 1.6, 0.45, 0.13),
        (3.6, ("Oz", "POz"), 0.55, 0.85, 0.16),
        (4.8, ("FCz", "Cz"), 0.20, 1.20, 0.18),
        (7.2, ("T8", "TP8"), 0.12, 1.75, 0.14),
    )
    for frequency_hz, center_names, amplitude_uv, phase, width in target_specs:
        weights = _smooth_spatial_weights(
            directions,
            center_names,
            width=width,
        )
        # A weak counter-field avoids an artificial all-positive scalp map.
        signed_weights = weights - 0.22 * np.mean(weights)
        data_uv += amplitude_uv * signed_weights[:, None] * np.sin(2.0 * np.pi * frequency_hz * time + phase)

    metadata = {
        "source": "deterministic_synthetic",
        "seed": SYNTHETIC_SEED,
        "sampling_frequency_hz": sfreq,
        "duration_sec": SYNTHETIC_DURATION_SEC,
        "sample_count": sample_count,
    }
    return np.asarray(data_uv * 1e-6, dtype=np.float64), sfreq, metadata


def _parse_bad_channels(value: str) -> tuple[str, ...]:
    stripped = value.strip()
    if stripped.lower() == "none":
        return ()
    requested = tuple(part.strip() for part in stripped.split(",") if part.strip())
    if not requested:
        raise ValueError("The bad-channel list is empty; use the literal 'none'.")
    duplicates = sorted({name for name in requested if requested.count(name) > 1})
    if duplicates:
        raise ValueError(f"Duplicate bad-channel name(s): {duplicates}")
    unknown = sorted(set(requested) - set(BIOSEMI64_CHANNELS))
    if unknown:
        raise ValueError(f"Bad channels must use exact canonical BioSemi64 names; unknown: {unknown}")
    return requested


def load_explicit_bdf(
    path: Path,
    *,
    start_sec: float,
    duration_sec: float,
) -> tuple[np.ndarray, float, dict[str, Any]]:
    """Load one explicitly named BDF with exact anatomical channel identity."""

    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"BDF does not exist: {resolved}")
    raw = mne.io.read_raw_bdf(resolved, preload=False, verbose=False)
    header_names = tuple(raw.ch_names)
    duplicates = sorted({name for name in header_names if header_names.count(name) > 1})
    if duplicates:
        raise ValueError(f"BDF header has duplicate channel name(s): {duplicates}")
    missing = sorted(set(BIOSEMI64_CHANNELS) - set(header_names))
    if missing:
        raise ValueError(
            "Direct-BDF mode accepts only exact anatomical BioSemi64 labels. "
            "No A/B or ordinal mapping is inferred. Missing: "
            f"{missing}"
        )
    sfreq = float(raw.info["sfreq"])
    start = int(round(start_sec * sfreq))
    sample_count = int(round(duration_sec * sfreq))
    stop = start + sample_count
    if start < 0 or stop > raw.n_times:
        raise ValueError(
            f"Requested [{start_sec}, {start_sec + duration_sec}) s interval "
            f"is outside the {raw.n_times / sfreq:.6g} s BDF."
        )
    # Names carry the mapping.  Passing the explicit canonical name sequence
    # preserves signal identity and never infers anatomy from file order.
    data = raw.get_data(picks=list(BIOSEMI64_CHANNELS), start=start, stop=stop)
    if data.shape != (64, sample_count) or not np.isfinite(data).all():
        raise ValueError("The selected BDF interval is incomplete or non-finite.")
    _validate_exact_target_bins(sample_count, sfreq)
    metadata = {
        "source": "explicit_bdf",
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "sampling_frequency_hz": sfreq,
        "analysis_start_sec": start_sec,
        "duration_sec": duration_sec,
        "sample_count": sample_count,
        "mapping_rule": "exact_anatomical_channel_name_only",
    }
    return np.asarray(data, dtype=np.float64), sfreq, metadata


def _validate_exact_target_bins(sample_count: int, sfreq: float) -> tuple[int, ...]:
    indices: list[int] = []
    for target in TARGET_FREQUENCIES_HZ:
        position = target * sample_count / sfreq
        index = int(round(position))
        if abs(position - index) >= 1e-9:
            raise ValueError(
                f"Target {target:g} Hz is not exact for N={sample_count}, "
                f"sfreq={sfreq:g}; computed bin={position:.12g}."
            )
        if not (NOISE_HALF_WIDTH_BINS + 1 <= index < sample_count // 2):
            raise ValueError(f"Target {target:g} Hz lacks a complete FFT/noise domain.")
        indices.append(index)
    return tuple(indices)


def _interpolate_and_reference(
    data_v: np.ndarray,
    *,
    sfreq: float,
    montage_name: str,
    bad_channels: Sequence[str],
) -> tuple[np.ndarray, np.ndarray]:
    info = _make_info_with_montage(montage_name, sfreq=sfreq)
    raw = mne.io.RawArray(np.asarray(data_v, dtype=float).copy(), info, verbose=False)
    raw.info["bads"] = list(bad_channels)
    if bad_channels:
        raw.interpolate_bads(
            reset_bads=True,
            mode=INTERPOLATION_MODE,
            verbose=False,
        )
    interpolated = raw.get_data().copy()
    raw.set_eeg_reference(ref_channels="average", projection=False, verbose=False)
    average_referenced = raw.get_data().copy()
    return interpolated, average_referenced


def _exact_target_metrics(
    data_v: np.ndarray,
    *,
    sfreq: float,
) -> dict[float, dict[str, np.ndarray | int]]:
    sample_count = int(data_v.shape[1])
    target_indices = _validate_exact_target_bins(sample_count, sfreq)
    data_uv = np.asarray(data_v, dtype=np.float64) * 1e6
    fft_amplitudes = np.abs(np.fft.fft(data_uv, axis=1)[:, : sample_count // 2 + 1]) / sample_count * 2.0
    metrics: dict[float, dict[str, np.ndarray | int]] = {}
    for target, target_index in zip(
        TARGET_FREQUENCIES_HZ,
        target_indices,
        strict=True,
    ):
        noise_mean, noise_std = compute_noise_stats_for_bin_channels(
            np.ascontiguousarray(fft_amplitudes),
            target_index,
            window_size=NOISE_HALF_WIDTH_BINS,
            min_bins=NOISE_MINIMUM_CANDIDATE_BINS,
        )
        amplitude = fft_amplitudes[:, target_index]
        bca = amplitude - noise_mean
        snr = np.divide(
            amplitude,
            noise_mean,
            out=np.zeros_like(amplitude),
            where=noise_mean > 1e-12,
        )
        local_z = np.divide(
            bca,
            noise_std,
            out=np.zeros_like(amplitude),
            where=noise_std > 1e-12,
        )
        metrics[target] = {
            "target_bin_index": target_index,
            "fft_amplitude_uv": amplitude,
            "noise_mean_uv": noise_mean,
            "noise_std_uv": noise_std,
            "bca_uv": bca,
            "snr": snr,
            "local_z": local_z,
        }
    return metrics


def _rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(np.asarray(values, dtype=float)))))


def _relative_percent(difference: float, reference: float) -> float | None:
    denominator = abs(float(reference))
    if denominator <= 1e-12:
        return None
    return abs(float(difference)) / denominator * 100.0


def _metric_row(
    *,
    scenario: str,
    bad_channels: Sequence[str],
    montage_name: str,
    stage: str,
    channel_index: int,
    target: float,
    metric: Mapping[str, np.ndarray | int],
) -> dict[str, Any]:
    channel = BIOSEMI64_CHANNELS[channel_index]
    local_z = float(np.asarray(metric["local_z"])[channel_index])
    return {
        "scenario": scenario,
        "bad_channels": ";".join(bad_channels),
        "bad_channel_count": len(bad_channels),
        "montage": montage_name,
        "stage": stage,
        "channel": channel,
        "is_interpolated_channel": channel in bad_channels,
        "target_frequency_hz": target,
        "target_bin_index": int(metric["target_bin_index"]),
        "fft_amplitude_uv": float(np.asarray(metric["fft_amplitude_uv"])[channel_index]),
        "noise_mean_uv": float(np.asarray(metric["noise_mean_uv"])[channel_index]),
        "noise_std_uv": float(np.asarray(metric["noise_std_uv"])[channel_index]),
        "bca_uv": float(np.asarray(metric["bca_uv"])[channel_index]),
        "snr": float(np.asarray(metric["snr"])[channel_index]),
        "local_z": local_z,
        "local_z_gt_1_64": local_z > LOCAL_Z_THRESHOLDS[0],
        "local_z_gt_3_29": local_z > LOCAL_Z_THRESHOLDS[1],
    }


def compare_scenario(
    data_v: np.ndarray,
    *,
    sfreq: float,
    scenario: str,
    bad_channels: Sequence[str],
    observed_truth_is_valid: bool,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """Compare one fixed bad-channel scenario under the two montages."""

    bad_channels = tuple(bad_channels)
    unknown = sorted(set(bad_channels) - set(BIOSEMI64_CHANNELS))
    if unknown:
        raise ValueError(f"Unknown fixed bad channel(s): {unknown}")
    standard_interpolated, standard_average = _interpolate_and_reference(
        data_v,
        sfreq=sfreq,
        montage_name=STANDARD_MONTAGE,
        bad_channels=bad_channels,
    )
    biosemi_interpolated, biosemi_average = _interpolate_and_reference(
        data_v,
        sfreq=sfreq,
        montage_name=CANONICAL_MONTAGE,
        bad_channels=bad_channels,
    )
    truth_average = data_v - np.mean(data_v, axis=0, keepdims=True)
    stage_arrays = {
        "interpolated": (
            standard_interpolated,
            biosemi_interpolated,
            data_v,
        ),
        "average_referenced": (
            standard_average,
            biosemi_average,
            truth_average,
        ),
    }

    time_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    difference_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    stage_summaries: dict[str, Any] = {}
    for stage, (standard_data, biosemi_data, truth_data) in stage_arrays.items():
        difference_uv = (biosemi_data - standard_data) * 1e6
        bad_indices = [BIOSEMI64_CHANNELS.index(name) for name in bad_channels]
        for channel_index, channel in enumerate(BIOSEMI64_CHANNELS):
            time_rows.append(
                {
                    "scenario": scenario,
                    "bad_channels": ";".join(bad_channels),
                    "bad_channel_count": len(bad_channels),
                    "channel": channel,
                    "is_interpolated_channel": channel in bad_channels,
                    "stage": stage,
                    "standard_1005_vs_biosemi64_rms_uv": _rms(difference_uv[channel_index]),
                    "standard_1005_vs_biosemi64_max_abs_uv": float(np.max(np.abs(difference_uv[channel_index]))),
                    "standard_1005_vs_truth_rms_uv": (
                        _rms((standard_data[channel_index] - truth_data[channel_index]) * 1e6)
                        if observed_truth_is_valid
                        else None
                    ),
                    "biosemi64_vs_truth_rms_uv": (
                        _rms((biosemi_data[channel_index] - truth_data[channel_index]) * 1e6)
                        if observed_truth_is_valid
                        else None
                    ),
                }
            )

        standard_metrics = _exact_target_metrics(standard_data, sfreq=sfreq)
        biosemi_metrics = _exact_target_metrics(biosemi_data, sfreq=sfreq)
        for target in TARGET_FREQUENCIES_HZ:
            standard_metric = standard_metrics[target]
            biosemi_metric = biosemi_metrics[target]
            for channel_index in range(len(BIOSEMI64_CHANNELS)):
                standard_row = _metric_row(
                    scenario=scenario,
                    bad_channels=bad_channels,
                    montage_name=STANDARD_MONTAGE,
                    stage=stage,
                    channel_index=channel_index,
                    target=target,
                    metric=standard_metric,
                )
                biosemi_row = _metric_row(
                    scenario=scenario,
                    bad_channels=bad_channels,
                    montage_name=CANONICAL_MONTAGE,
                    stage=stage,
                    channel_index=channel_index,
                    target=target,
                    metric=biosemi_metric,
                )
                metric_rows.extend((standard_row, biosemi_row))
                fft_difference = biosemi_row["fft_amplitude_uv"] - standard_row["fft_amplitude_uv"]
                bca_difference = biosemi_row["bca_uv"] - standard_row["bca_uv"]
                difference_row = {
                    "scenario": scenario,
                    "bad_channels": ";".join(bad_channels),
                    "bad_channel_count": len(bad_channels),
                    "stage": stage,
                    "channel": BIOSEMI64_CHANNELS[channel_index],
                    "is_interpolated_channel": (BIOSEMI64_CHANNELS[channel_index] in bad_channels),
                    "target_frequency_hz": target,
                    "target_bin_index": standard_row["target_bin_index"],
                    "fft_amplitude_difference_uv": fft_difference,
                    "fft_amplitude_absolute_difference_uv": abs(fft_difference),
                    "fft_amplitude_relative_difference_percent": _relative_percent(
                        fft_difference,
                        standard_row["fft_amplitude_uv"],
                    ),
                    "bca_difference_uv": bca_difference,
                    "bca_absolute_difference_uv": abs(bca_difference),
                    "bca_relative_difference_percent": _relative_percent(
                        bca_difference,
                        standard_row["bca_uv"],
                    ),
                    "snr_difference": biosemi_row["snr"] - standard_row["snr"],
                    "local_z_difference": (biosemi_row["local_z"] - standard_row["local_z"]),
                    "local_z_gt_1_64_changed": (biosemi_row["local_z_gt_1_64"] != standard_row["local_z_gt_1_64"]),
                    "local_z_gt_3_29_changed": (biosemi_row["local_z_gt_3_29"] != standard_row["local_z_gt_3_29"]),
                }
                difference_rows.append(difference_row)
                for threshold, field in (
                    (1.64, "local_z_gt_1_64"),
                    (3.29, "local_z_gt_3_29"),
                ):
                    if standard_row[field] != biosemi_row[field]:
                        decision_rows.append(
                            {
                                "scenario": scenario,
                                "bad_channels": ";".join(bad_channels),
                                "bad_channel_count": len(bad_channels),
                                "stage": stage,
                                "channel": BIOSEMI64_CHANNELS[channel_index],
                                "is_interpolated_channel": (BIOSEMI64_CHANNELS[channel_index] in bad_channels),
                                "target_frequency_hz": target,
                                "threshold": threshold,
                                "standard_1005_decision": standard_row[field],
                                "biosemi64_decision": biosemi_row[field],
                                "standard_1005_local_z": standard_row["local_z"],
                                "biosemi64_local_z": biosemi_row["local_z"],
                            }
                        )

        bad_mask = np.zeros(len(BIOSEMI64_CHANNELS), dtype=bool)
        bad_mask[bad_indices] = True
        truth_summary: dict[str, float | None] = {
            "standard_1005_bad_channel_truth_rms_uv": None,
            "biosemi64_bad_channel_truth_rms_uv": None,
        }
        if observed_truth_is_valid and bad_indices:
            truth_summary = {
                "standard_1005_bad_channel_truth_rms_uv": _rms((standard_data[bad_mask] - truth_data[bad_mask]) * 1e6),
                "biosemi64_bad_channel_truth_rms_uv": _rms((biosemi_data[bad_mask] - truth_data[bad_mask]) * 1e6),
            }
        stage_difference_rows = [row for row in difference_rows if row["stage"] == stage]
        stage_summaries[stage] = {
            "all_channel_rms_difference_uv": _rms(difference_uv),
            "all_channel_max_abs_difference_uv": float(np.max(np.abs(difference_uv))),
            "interpolated_channel_rms_difference_uv": (_rms(difference_uv[bad_mask]) if bad_indices else 0.0),
            "max_abs_fft_amplitude_difference_uv": max(
                row["fft_amplitude_absolute_difference_uv"] for row in stage_difference_rows
            ),
            "max_abs_bca_difference_uv": max(row["bca_absolute_difference_uv"] for row in stage_difference_rows),
            "max_abs_snr_difference": max(abs(row["snr_difference"]) for row in stage_difference_rows),
            "max_abs_local_z_difference": max(abs(row["local_z_difference"]) for row in stage_difference_rows),
            "local_z_threshold_change_count": sum(
                int(row["local_z_gt_1_64_changed"]) + int(row["local_z_gt_3_29_changed"])
                for row in stage_difference_rows
            ),
            **truth_summary,
        }

    summary = {
        "scenario": scenario,
        "bad_channels": list(bad_channels),
        "bad_channel_count": len(bad_channels),
        "stages": stage_summaries,
    }
    return time_rows, metric_rows, difference_rows, decision_rows, summary


def _write_csv(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=list(fieldnames),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _git_worktree_dirty() -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=_REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return bool(result.stdout.strip())


def _protocol_payload(*, input_metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "protocol_id": PROTOCOL_ID,
        "schema_version": SCHEMA_VERSION,
        "comparison_montages": [STANDARD_MONTAGE, CANONICAL_MONTAGE],
        "canonical_channel_names": list(BIOSEMI64_CHANNELS),
        "interpolation": {
            "mne_call": "Raw.interpolate_bads",
            "method": INTERPOLATION_METHOD,
            "mode": INTERPOLATION_MODE,
            "origin": INTERPOLATION_ORIGIN,
            "reset_bads": True,
        },
        "final_reference": "average",
        "target_frequencies_hz": list(TARGET_FREQUENCIES_HZ),
        "exact_fft_bin_required": True,
        "fft_amplitude_scaling": "abs(fft) / N * 2",
        "local_noise": {
            "half_width_bins": NOISE_HALF_WIDTH_BINS,
            "excluded_bins": ["target-1", "target", "target+1"],
            "drop_one_finite_minimum": True,
            "drop_one_finite_maximum": True,
            "standard_deviation_ddof": 0,
        },
        "reported_local_z_thresholds": list(LOCAL_Z_THRESHOLDS),
        "input": dict(input_metadata),
    }


def run_diagnostic(
    *,
    output_dir: Path,
    data_v: np.ndarray,
    sfreq: float,
    input_metadata: Mapping[str, Any],
    scenarios: Sequence[tuple[str, Sequence[str]]],
    observed_truth_is_valid: bool,
) -> dict[str, Any]:
    """Execute the comparison and write its complete evidence bundle."""

    _canonical_montage_channels()
    if data_v.shape[0] != len(BIOSEMI64_CHANNELS):
        raise ValueError("Diagnostic data must contain exactly 64 canonical channels.")
    if not np.isfinite(data_v).all():
        raise ValueError("Diagnostic data must be finite.")
    _validate_exact_target_bins(data_v.shape[1], sfreq)

    coordinate_rows, sphere_identity = build_coordinate_rows()
    time_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    difference_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    scenario_summaries: list[dict[str, Any]] = []
    for scenario_name, bad_channels in scenarios:
        outputs = compare_scenario(
            data_v,
            sfreq=sfreq,
            scenario=scenario_name,
            bad_channels=bad_channels,
            observed_truth_is_valid=observed_truth_is_valid,
        )
        scenario_time, scenario_metrics, scenario_differences, scenario_decisions, summary = outputs
        time_rows.extend(scenario_time)
        metric_rows.extend(scenario_metrics)
        difference_rows.extend(scenario_differences)
        decision_rows.extend(scenario_decisions)
        scenario_summaries.append(summary)

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_outputs = {
        "coordinate_differences.csv": (coordinate_rows, _COORDINATE_FIELDS),
        "time_domain_differences.csv": (time_rows, _TIME_FIELDS),
        "target_metrics.csv": (metric_rows, _TARGET_METRIC_FIELDS),
        "target_metric_differences.csv": (
            difference_rows,
            _TARGET_DIFFERENCE_FIELDS,
        ),
        "threshold_decision_changes.csv": (decision_rows, _DECISION_FIELDS),
    }
    for filename, (rows, fields) in csv_outputs.items():
        _write_csv(output_dir / filename, rows, fieldnames=fields)

    scientific_payload = {
        "protocol": _protocol_payload(input_metadata=input_metadata),
        "fitted_spheres": sphere_identity,
        "coordinate_rows": coordinate_rows,
        "time_domain_rows": time_rows,
        "target_metric_rows": metric_rows,
        "target_metric_difference_rows": difference_rows,
        "threshold_decision_change_rows": decision_rows,
    }
    scientific_fingerprint = hashlib.sha256(_canonical_json_bytes(scientific_payload)).hexdigest()
    coordinate_distances = np.asarray([row["head_space_distance_mm"] for row in coordinate_rows])
    coordinate_angles = np.asarray([row["fitted_sphere_angular_difference_deg"] for row in coordinate_rows])
    zero_summary = next(
        (item for item in scenario_summaries if item["scenario"] == "zero_bad_control"),
        None,
    )
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "protocol_id": PROTOCOL_ID,
        "status": "complete",
        "scientific_results_sha256": scientific_fingerprint,
        "protocol": _protocol_payload(input_metadata=input_metadata),
        "runtime": {
            "toolbox_commit": _git_commit(),
            "git_worktree_dirty": _git_worktree_dirty(),
            "script_sha256": _sha256_file(_SCRIPT_PATH),
            "production_noise_helper_sha256": _sha256_file(
                _SOURCE_ROOT / "Tools" / "Stats" / "analysis" / "noise_utils.py"
            ),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "mne": mne.__version__,
            "numpy": np.__version__,
        },
        "fitted_spheres": sphere_identity,
        "coordinate_summary": {
            "channel_count": len(coordinate_rows),
            "head_space_distance_mm_min": float(np.min(coordinate_distances)),
            "head_space_distance_mm_median": float(np.median(coordinate_distances)),
            "head_space_distance_mm_max": float(np.max(coordinate_distances)),
            "fitted_sphere_angular_difference_deg_min": float(np.min(coordinate_angles)),
            "fitted_sphere_angular_difference_deg_median": float(np.median(coordinate_angles)),
            "fitted_sphere_angular_difference_deg_max": float(np.max(coordinate_angles)),
        },
        "scenario_summaries": scenario_summaries,
        "overall": {
            "scenario_count": len(scenario_summaries),
            "threshold_decision_change_count": len(decision_rows),
            "zero_bad_control_exactly_equal": (
                bool(
                    zero_summary
                    and all(
                        stage["all_channel_max_abs_difference_uv"] == 0.0 for stage in zero_summary["stages"].values()
                    )
                )
                if zero_summary is not None
                else None
            ),
            "max_time_domain_difference_uv": max(row["standard_1005_vs_biosemi64_max_abs_uv"] for row in time_rows),
            "max_fft_amplitude_absolute_difference_uv": max(
                row["fft_amplitude_absolute_difference_uv"] for row in difference_rows
            ),
            "max_bca_absolute_difference_uv": max(row["bca_absolute_difference_uv"] for row in difference_rows),
            "max_abs_snr_difference": max(abs(row["snr_difference"]) for row in difference_rows),
            "max_abs_local_z_difference": max(abs(row["local_z_difference"]) for row in difference_rows),
        },
        "limitations": [
            "Synthetic results isolate montage geometry and do not estimate effects in a representative lab sample.",
            "Direct-BDF mode compares one caller-selected interval and fixed caller-supplied bad channels; it is not the complete FPVS processing pipeline.",
            "The deterministic synthetic field is spatially smooth and cannot cover every physiological or artifact topology.",
            "Threshold comparisons report local-z crossings at 1.64 and 3.29; they do not by themselves establish participant or group-level result changes.",
            "Template coordinates are generic cap locations, not participant-digitized electrode positions.",
        ],
    }
    summary["output_files_sha256"] = {filename: _sha256_file(output_dir / filename) for filename in csv_outputs}
    _write_json(output_dir / "summary.json", summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.input_bdf is None:
        data_v, sfreq, input_metadata = generate_synthetic_data()
        scenarios: Sequence[tuple[str, Sequence[str]]] = SYNTHETIC_BAD_CHANNEL_SCENARIOS
        observed_truth_is_valid = True
    else:
        bad_channels = _parse_bad_channels(args.bad_channels)
        data_v, sfreq, input_metadata = load_explicit_bdf(
            args.input_bdf,
            start_sec=args.analysis_start_sec,
            duration_sec=args.analysis_duration_sec,
        )
        scenarios = (("explicit_bdf_fixed_bad_channels", bad_channels),)
        # A channel selected as bad cannot serve as known interpolation truth.
        observed_truth_is_valid = False
    summary = run_diagnostic(
        output_dir=args.output_dir,
        data_v=data_v,
        sfreq=sfreq,
        input_metadata=input_metadata,
        scenarios=scenarios,
        observed_truth_is_valid=observed_truth_is_valid,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
