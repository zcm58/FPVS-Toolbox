"""Seeded offline source-ready EEG spectral/null/sensitivity experiment.

This opt-in runner executes the native production inverse/PSD, neighboring-bin
Z and cluster engine. It does not run sensor preprocessing or qualify population
inference. The adaptive stress selector is deliberately simpler than Stats.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
from scipy.signal import lfilter
from scipy.stats import beta, skew

from .hauk_source_psd import (
    HaukSourcePsdConfig, compute_hauk_source_psd,
    SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL, SOURCE_ORIENTATION_MODE_VECTOR_NORM,
)
from .inference_qualification import source_inference_qualification_metadata
from .native_spectral_reference import NativeDiagnosticModel, build_native_sphere_model
from .source_space_statistics import (
    adjacency_from_triangular_faces, compute_source_space_cluster_permutation_mask,
)

logger = logging.getLogger(__name__)
SCENARIOS = (
    "white_null", "correlated_null", "adaptive_stress_null", "low_signal",
    "high_signal", "correlated_sources", "sensor_gain_mismatch",
)


@dataclass(frozen=True)
class SpectralDiagnosticConfig:
    model: str = "sphere"
    participant_count: int = 24
    null_replicates: int = 64
    signal_replicates: int = 16
    repetitions: int = 4
    n_times: int = 4000
    sfreq: float = 200.
    harmonics_hz: tuple[float, ...] = (1.2, 2.4, 3.6, 4.8)
    permutation_count: int = 999
    cluster_forming_p: float = 1e-5
    cluster_alpha: float = 0.05
    seed: int = 20261104

    def __post_init__(self):
        if self.model not in {"sphere", "fsaverage"}:
            raise ValueError("Diagnostic model must be sphere or fsaverage.")
        for name in ("participant_count", "null_replicates", "signal_replicates", "repetitions", "n_times", "permutation_count"):
            value = getattr(self, name)
            if int(value) != value or value < (2 if name in {"participant_count", "n_times"} else 1):
                raise ValueError(f"{name} must be a positive integer with sufficient samples/participants.")


def binomial_rejection_summary(rejections: int, replicates: int) -> dict[str, Any]:
    """Two-sided exact Clopper-Pearson uncertainty, including zero rejections."""
    if not 0 <= rejections <= replicates or replicates < 1:
        raise ValueError("Rejection count must lie between zero and positive replicate count.")
    lower = 0. if rejections == 0 else float(beta.ppf(.025, rejections, replicates - rejections + 1))
    upper = 1. if rejections == replicates else float(beta.ppf(.975, rejections + 1, replicates - rejections))
    return {
        "rejections": int(rejections), "replicates": int(replicates),
        "rate": float(rejections / replicates), "binomial_95_percent_interval": [lower, upper],
        "interval_method": "two_sided_exact_clopper_pearson",
    }


def build_diagnostic_model(method: str, config: SpectralDiagnosticConfig) -> NativeDiagnosticModel:
    """Load native models without fetching; prepare the invariant inverse once."""
    from mne.minimum_norm import prepare_inverse_operator

    if config.model == "sphere":
        model = build_native_sphere_model(method, sfreq=config.sfreq)
    elif method == "MNE":
        from .project_l2_mne_export import build_mne_fsaverage_source_psd_model

        native = build_mne_fsaverage_source_psd_model(sfreq=config.sfreq, allow_fetch_fsaverage=False)
        forward = native.forward_model
        model = NativeDiagnosticModel(
            method, native.info, native.inverse_operator, native.native_leadfield,
            forward.source_points, adjacency_from_triangular_faces(forward.faces, source_count=len(forward.source_points)),
            geometry="fsaverage_biosemi64_production_model",
        )
    else:
        from config import DEFAULT_ELECTRODE_NAMES_64
        from .project_eloreta_volume_export import build_mne_fsaverage_eloreta_volume_source_psd_model
        from .project_eloreta_volume_hauk_source_psd_export import DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS

        native = build_mne_fsaverage_eloreta_volume_source_psd_model(
            sfreq=config.sfreq, allow_fetch_fsaverage=False, prepare_inverse=True,
            channel_names=DEFAULT_ELECTRODE_NAMES_64, method_params=DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS,
        )
        model = NativeDiagnosticModel(
            method, native.info, native.inverse_operator, native.forward_model.leadfield,
            native.forward_model.source_points, tuple(native.forward_model.source_adjacency),
            native.prepared, dict(native.method_params), "fsaverage_biosemi64_production_model",
        )
    if not model.prepared:
        inverse = prepare_inverse_operator(
            model.inverse, nave=1, lambda2=1 / 9, method=method,
            method_params=model.method_params, verbose=False,
        )
        model = replace(model, inverse=inverse, prepared=True)
    return model


def synthetic_signed_cohort(
    model: NativeDiagnosticModel, config: SpectralDiagnosticConfig, *, scenario: str, replicate: int,
) -> tuple[list[np.ndarray], dict[str, Any]]:
    """Average signed repetitions; use a named and reproducible noise/signal model."""
    if scenario not in SCENARIOS:
        raise ValueError("Unknown spectral diagnostic scenario.")
    rng = np.random.default_rng(np.random.SeedSequence([config.seed, SCENARIOS.index(scenario), replicate]))
    channels = len(model.info["ch_names"])
    sample = np.arange(config.n_times) / config.sfreq
    source_indices = [len(model.points_mm) // 3]
    if scenario == "correlated_sources":
        source_indices.append(2 * len(model.points_mm) // 3)
    component = 2
    sensor_pattern = sum(model.leadfield[:, 3 * source + component] for source in source_indices)
    sensor_pattern -= sensor_pattern.mean()
    sensor_pattern /= np.sqrt(np.mean(sensor_pattern**2))
    if scenario == "sensor_gain_mismatch":
        # A reproducible 10% channel-gain perturbation, not electrode/anatomy evidence.
        sensor_pattern = sensor_pattern * (1. + 0.1 * np.sin(np.arange(channels)))
    signal_scale = 0. if scenario.endswith("null") else 0.1 if scenario == "low_signal" else 0.5
    cohort = []
    for participant in range(config.participant_count):
        noise = rng.normal(size=(config.repetitions, channels, config.n_times))
        if scenario != "white_null":
            common = rng.normal(size=(config.repetitions, 1, config.n_times))
            spatial_pattern = np.cos(2 * np.pi * np.arange(channels) / channels)
            noise = np.sqrt(.75) * noise + .5 * common * spatial_pattern[None, :, None]
            noise = lfilter([np.sqrt(1 - .8**2)], [1., -.8], noise, axis=-1)
        noise_scale = 1e-6 * (1. + .5 * participant / max(config.participant_count - 1, 1))
        signed = noise * noise_scale
        phase = rng.uniform(0., 2 * np.pi)
        signal = sum(np.sin(2 * np.pi * frequency * sample + phase) / (index + 1) for index, frequency in enumerate(config.harmonics_hz))
        signed += signal_scale * noise_scale * sensor_pattern[None, :, None] * signal[None, None, :]
        # Preserve polarity/phase until after averaging and native source inversion.
        average = signed.mean(axis=0)
        average -= average.mean(axis=0, keepdims=True)
        cohort.append(average)
    return cohort, {
        "injected_source_indices": source_indices if signal_scale else [],
        "signal_peak_multiplier_of_single_repetition_noise_sd": signal_scale,
        "noise_sd_volts_range": [1e-6, 1.5e-6],
        "temporal_ar1": 0. if scenario == "white_null" else .8,
        "spatial_shared_component": "none" if scenario == "white_null" else "0.5*cos(2*pi*channel_index/channel_count)*independent_shared_noise",
        "spatial_dependence_after_reference": "average_reference_and_native_inverse",
        "sensor_gain_perturbation": "1 + .1*sin(channel_index) on generated signal only" if scenario == "sensor_gain_mismatch" else None,
    }


def stress_harmonics(cohort: list[np.ndarray], config: SpectralDiagnosticConfig) -> tuple[float, ...]:
    """Same-sample top-two sensor-amplitude stress, explicitly not the Stats selector."""
    bins = np.rint(np.asarray(config.harmonics_hz) * config.n_times / config.sfreq).astype(int)
    amplitudes = np.mean([np.linalg.norm(np.fft.rfft(row, axis=-1)[:, bins], axis=0) for row in cohort], axis=0)
    chosen = np.argsort(amplitudes, kind="stable")[-min(2, len(bins)):]
    return tuple(sorted(config.harmonics_hz[int(index)] for index in chosen))


def _run_cohort(model: NativeDiagnosticModel, config: SpectralDiagnosticConfig, scenario: str, replicate: int) -> dict[str, Any]:
    import mne

    cohort, simulation = synthetic_signed_cohort(model, config, scenario=scenario, replicate=replicate)
    harmonics = stress_harmonics(cohort, config) if scenario == "adaptive_stress_null" else config.harmonics_hz
    psd_config = HaukSourcePsdConfig(
        selected_harmonics_hz=harmonics, inverse_method=model.method, prepared=model.prepared,
        method_params=model.method_params or {}, source_orientation_mode=(
            SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL if model.method == "MNE" else SOURCE_ORIENTATION_MODE_VECTOR_NORM
        ),
    )
    rows = []
    for data in cohort:
        raw = mne.io.RawArray(data, model.info.copy(), verbose=False)
        with mne.use_log_level("ERROR"):
            estimate = compute_hauk_source_psd(averaged_raw=raw, inverse_operator=model.inverse, config=psd_config)
        values = estimate.values
        rows.append(SimpleNamespace(values=values, valid_source_mask=np.isfinite(values)))
    statistics = compute_source_space_cluster_permutation_mask(
        rows, adjacency=model.adjacency, cluster_forming_p_value=config.cluster_forming_p,
        cluster_alpha=config.cluster_alpha, permutation_count=config.permutation_count,
        permutation_seed=config.seed + replicate, tail="positive",
    )
    matrix = np.vstack([row.values for row in rows])
    finite = matrix[np.isfinite(matrix)]
    target_z, peak_distance = None, None
    if simulation["injected_source_indices"]:
        source = simulation["injected_source_indices"][0]
        mean = np.nanmean(matrix, axis=0)
        target_z = float(mean[source])
        peak = int(np.nanargmax(mean))
        peak_distance = float(np.min(np.linalg.norm(model.points_mm[simulation["injected_source_indices"]] - model.points_mm[peak], axis=1)))
    return {
        "rejection": bool(np.any(statistics.mask)),
        "moments": [float(finite.mean()), float(skew(finite)), float(np.mean(finite > 0))],
        "unsupported_source_count": int(np.count_nonzero(~statistics.valid_source_mask)),
        "selected_harmonics_hz": list(harmonics), "target_z": target_z,
        "peak_distance_mm": peak_distance, "simulation": simulation,
    }


def _save_checkpoint(path: Path, state: dict[str, Any]) -> None:
    from Main_App.io.atomic_write import atomic_write

    path.parent.mkdir(parents=True, exist_ok=True)
    with atomic_write(path) as handle:
        json.dump(state, handle, allow_nan=False)
        handle.write("\n")


def run_spectral_diagnostic(
    config: SpectralDiagnosticConfig, *, scenarios: tuple[str, ...] = SCENARIOS,
    methods: tuple[str, ...] = ("MNE", "eLORETA"), checkpoint_path: Path | None = None,
    resume: bool = False, max_seconds: float = 2700.,
) -> dict[str, Any]:
    """Run bounded cohorts with atomic checkpoints; never promote qualification.

    The budget is checked between cohorts. A currently running native cohort
    finishes before stopping, preserving its result and avoiding partial evidence.
    """
    import mne
    import scipy

    if not np.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("Diagnostic wall-time budget must be positive and finite.")
    started = time.monotonic()
    source_hashes = {
        name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
        for name in ("source_spectral_diagnostics.py", "hauk_source_psd.py", "source_space_statistics.py", "source_validity.py")
    }
    dependencies = {"mne": mne.__version__, "numpy": np.__version__, "scipy": scipy.__version__}
    identity = json.loads(json.dumps({"config": asdict(config), "scenarios": scenarios, "methods": methods, "source_hashes": source_hashes, "dependencies": dependencies}))
    state: dict[str, Any] = {"format": "fpvs-source-spectral-checkpoint-v1", "identity": identity, "completed": {}, "elapsed_seconds": 0.}
    if resume:
        if checkpoint_path is None or not checkpoint_path.is_file():
            raise ValueError("Resume requires an existing diagnostic checkpoint.")
        state = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if state.get("identity") != identity:
            raise ValueError("Checkpoint configuration, dependencies or source hashes do not match this run.")
    previous_seconds = float(state["elapsed_seconds"])
    results = []
    for method in methods:
        model = build_diagnostic_model(method, config)
        for scenario in scenarios:
            replicates = config.null_replicates if scenario.endswith("null") else config.signal_replicates
            records = []
            for replicate in range(replicates):
                key = f"{method}:{scenario}:{replicate}"
                if key not in state["completed"]:
                    if time.monotonic() - started >= max_seconds:
                        raise RuntimeError("Diagnostic time budget reached; completed cohorts are checkpointed. Resume explicitly.")
                    state["completed"][key] = _run_cohort(model, config, scenario, replicate)
                    state["elapsed_seconds"] = previous_seconds + time.monotonic() - started
                    if checkpoint_path is not None:
                        _save_checkpoint(checkpoint_path, state)
                record = state["completed"][key]
                records.append(record)
                logger.info("%s %s cohort %d/%d; any retained cluster=%s", method, scenario, replicate + 1, replicates, record["rejection"])
            outcomes = [record["rejection"] for record in records]
            results.append({
                "method": method, "geometry": model.geometry, "source_count": len(model.points_mm),
                "scenario": scenario, "is_no_signal_null": scenario.endswith("null"),
                "family": "all_supported_sources_of_this_method_in_one_cohort",
                "any_cluster_rejection": binomial_rejection_summary(sum(outcomes), replicates),
                "cohort_rejections": outcomes,
                "cohort_z_mean_skew_positive_fraction": [record["moments"] for record in records],
                "cohort_unsupported_source_counts": [record["unsupported_source_count"] for record in records],
                "cohort_selected_harmonics_hz": [record["selected_harmonics_hz"] for record in records],
                "mean_z_at_first_injected_source": [record["target_z"] for record in records if record["target_z"] is not None],
                "peak_distance_to_nearest_injected_source_mm": [record["peak_distance_mm"] for record in records if record["peak_distance_mm"] is not None],
                "simulation": records[0]["simulation"],
                "selection": "same_sample_top_two_sensor_amplitudes_simplified_stress_not_locked_Stats" if scenario == "adaptive_stress_null" else "fixed_harmonics",
            })
    return {
        "format": "fpvs-source-spectral-diagnostic-v1", "synthetic": True,
        "elapsed_seconds": previous_seconds + time.monotonic() - started,
        "source_file_sha256_at_start": source_hashes,
        "config": asdict(config), "dependencies": dependencies,
        "scope": "source-ready signed EEG through native production spectral inverse, neighbor Z, full model adjacency and group cluster engine",
        "not_tested": ["sensor preprocessing", "real-data accuracy", "empirical noise covariance suitability", "individual MRI or electrode error", "locked Stats adaptive selection", "joint multiple-condition or method families"],
        "qualification": source_inference_qualification_metadata(), "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", choices=("sphere", "fsaverage"), default="sphere")
    parser.add_argument("--null-replicates", type=int, default=64)
    parser.add_argument("--signal-replicates", type=int, default=16)
    parser.add_argument("--participants", type=int, default=24)
    parser.add_argument("--permutations", type=int, default=999)
    parser.add_argument("--scenarios", nargs="+", choices=SCENARIOS, default=list(SCENARIOS))
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-seconds", type=float, default=2700.)
    args = parser.parse_args()
    report = run_spectral_diagnostic(SpectralDiagnosticConfig(
        model=args.model, null_replicates=args.null_replicates, signal_replicates=args.signal_replicates,
        participant_count=args.participants, permutation_count=args.permutations,
    ), scenarios=tuple(args.scenarios), checkpoint_path=args.checkpoint, resume=args.resume, max_seconds=args.max_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
