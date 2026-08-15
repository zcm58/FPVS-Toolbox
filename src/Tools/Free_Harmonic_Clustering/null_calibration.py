"""Reproducible powered-null calibration for automatic harmonic selection.

This module is GUI- and project-neutral.  It owns the frozen synthetic protocol,
deterministic replicate generation, exact binomial acceptance calculations, and
machine-readable receipts.  The 4,000 x 10,000 powered study is intentionally
invoked only by the developer runner in ``scripts/manual_diagnostics``; routine
pytest keeps a much smaller regression envelope.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.stats import beta

from .analysis import (
    BIOSEMI64_ADJACENCY_FINGERPRINT,
    BIOSEMI64_ADJACENCY_VERSION,
    biosemi64_spatial_adjacency,
    run_cluster_permutation,
)
from .models import (
    AnalysisDesign,
    FreeHarmonicMethodSpec,
    METHOD_VERSION,
    NoHarmonicsSelectedError,
)
from .preparation import (
    build_frequency_window_plan,
    compute_participant_snr,
    l2_normalize_snr,
    select_harmonics,
    select_snr_harmonics,
)


CALIBRATION_PROTOCOL_ID = "fhc_automatic_unconditional_null_v1"
CALIBRATION_IMPLEMENTATION_VERSION = "1.1"
CALIBRATION_RECEIPT_SCHEMA_VERSION = 1
CALIBRATION_FREQUENCY_STEP_HZ = 0.025
CALIBRATION_FREQUENCY_MARGIN_HZ = 0.1
CALIBRATION_PERMUTATION_BATCH_SIZE = 512
CALIBRATION_REPLICATES_PER_SCENARIO = 500
CALIBRATION_PERMUTATIONS_PER_REPLICATE = 10_000
CALIBRATION_DESIGN_BOUND = 0.070
CALIBRATION_DESIGN_CONFIDENCE = 0.975
CALIBRATION_SCENARIO_BOUND = 0.100
CALIBRATION_SCENARIO_CONFIDENCE = 0.950
CALIBRATION_DETERMINISM_PROTOCOL_ID = "fhc_null_determinism_smoke_v1"
CALIBRATION_DETERMINISM_PERMUTATIONS = 19
CALIBRATION_DETERMINISM_BATCH_SIZE = 7
CALIBRATION_DETERMINISM_REPLICATE_INDEX = 10_000


@dataclass(frozen=True, slots=True)
class NullCalibrationScenario:
    """One frozen positive-amplitude global-null data-generating regime."""

    scenario_id: str
    distribution: str
    log_scale: float
    target_boosts: tuple[float, ...]
    sensor_smoothing: float = 0.0
    frequency_correlation: float = 0.0
    paired_shared_fraction: float = 0.60
    student_t_degrees_of_freedom: float | None = None

    def __post_init__(self) -> None:
        if not self.scenario_id.strip():
            raise ValueError("scenario_id must not be empty.")
        if self.distribution not in {"lognormal", "student_lognormal"}:
            raise ValueError(f"Unsupported calibration distribution: {self.distribution!r}.")
        if not np.isfinite(self.log_scale) or self.log_scale <= 0.0:
            raise ValueError("log_scale must be finite and positive.")
        boosts = tuple(float(value) for value in self.target_boosts)
        if not boosts or any(not np.isfinite(value) or value < 0.0 for value in boosts):
            raise ValueError("target_boosts must contain finite non-negative values.")
        object.__setattr__(self, "target_boosts", boosts)
        for field_name in (
            "sensor_smoothing",
            "frequency_correlation",
            "paired_shared_fraction",
        ):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or not 0.0 <= value < 1.0:
                raise ValueError(f"{field_name} must be finite in [0, 1).")
            object.__setattr__(self, field_name, value)
        degrees = self.student_t_degrees_of_freedom
        if self.distribution == "student_lognormal":
            if degrees is None or not np.isfinite(degrees) or degrees <= 2.0:
                raise ValueError("student_lognormal requires degrees of freedom greater than two.")
            object.__setattr__(self, "student_t_degrees_of_freedom", float(degrees))
        elif degrees is not None:
            raise ValueError("student_t_degrees_of_freedom is valid only for student_lognormal.")


CALIBRATION_SCENARIOS: tuple[NullCalibrationScenario, ...] = (
    NullCalibrationScenario(
        scenario_id="iid_two_harmonic_lognormal",
        distribution="lognormal",
        log_scale=0.18,
        target_boosts=(2.0, 1.35),
    ),
    NullCalibrationScenario(
        scenario_id="correlated_two_harmonic_lognormal",
        distribution="lognormal",
        log_scale=0.18,
        target_boosts=(2.0, 1.35),
        sensor_smoothing=0.35,
        frequency_correlation=0.55,
    ),
    NullCalibrationScenario(
        scenario_id="threshold_edge_lognormal",
        distribution="lognormal",
        log_scale=0.18,
        target_boosts=(0.08, 0.016, 0.012, 0.008),
        sensor_smoothing=0.20,
        frequency_correlation=0.30,
    ),
    NullCalibrationScenario(
        scenario_id="heavy_tail_two_harmonic",
        distribution="student_lognormal",
        log_scale=0.20,
        target_boosts=(0.50, 0.20),
        sensor_smoothing=0.20,
        frequency_correlation=0.30,
        student_t_degrees_of_freedom=5.0,
    ),
)


@dataclass(frozen=True, slots=True)
class NullCalibrationProtocol:
    """Frozen protocol used by the official powered study."""

    protocol_id: str = CALIBRATION_PROTOCOL_ID
    independent_group_sizes: tuple[int, int] = (18, 16)
    paired_participant_count: int = 18
    scenarios: tuple[NullCalibrationScenario, ...] = CALIBRATION_SCENARIOS
    replicates_per_scenario: int = CALIBRATION_REPLICATES_PER_SCENARIO
    permutations_per_replicate: int = CALIBRATION_PERMUTATIONS_PER_REPLICATE
    permutation_batch_size: int = CALIBRATION_PERMUTATION_BATCH_SIZE
    design_upper_confidence: float = CALIBRATION_DESIGN_CONFIDENCE
    design_error_bound: float = CALIBRATION_DESIGN_BOUND
    scenario_upper_confidence: float = CALIBRATION_SCENARIO_CONFIDENCE
    scenario_error_bound: float = CALIBRATION_SCENARIO_BOUND
    oddball_frequency_hz: float = 1.2
    base_frequency_hz: float = 6.0
    max_harmonic_hz: float = 48.0
    noise_half_width_hz: float = 0.1
    harmonic_z_threshold: float = 3.29
    harmonic_z_ddof: int = 1
    cluster_entry_alpha: float = 0.01
    cluster_alpha_per_tail: float = 0.025
    frequency_step_hz: float = CALIBRATION_FREQUENCY_STEP_HZ
    frequency_margin_hz: float = CALIBRATION_FREQUENCY_MARGIN_HZ

    def __post_init__(self) -> None:
        if self.protocol_id != CALIBRATION_PROTOCOL_ID:
            raise ValueError(f"Unsupported calibration protocol: {self.protocol_id!r}.")
        group_sizes = tuple(int(value) for value in self.independent_group_sizes)
        if len(group_sizes) != 2 or any(value < 2 for value in group_sizes):
            raise ValueError("independent_group_sizes must contain two sizes of at least two.")
        object.__setattr__(self, "independent_group_sizes", group_sizes)
        if int(self.paired_participant_count) < 2:
            raise ValueError("paired_participant_count must be at least two.")
        object.__setattr__(self, "paired_participant_count", int(self.paired_participant_count))
        scenarios = tuple(self.scenarios)
        if not scenarios or any(not isinstance(value, NullCalibrationScenario) for value in scenarios):
            raise TypeError("scenarios must contain NullCalibrationScenario values.")
        scenario_ids = tuple(value.scenario_id for value in scenarios)
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("Calibration scenario IDs must be unique.")
        object.__setattr__(self, "scenarios", scenarios)
        for field_name in (
            "replicates_per_scenario",
            "permutations_per_replicate",
            "permutation_batch_size",
        ):
            value = int(getattr(self, field_name))
            if value < 1:
                raise ValueError(f"{field_name} must be positive.")
            object.__setattr__(self, field_name, value)
        for field_name in (
            "design_upper_confidence",
            "design_error_bound",
            "scenario_upper_confidence",
            "scenario_error_bound",
        ):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or not 0.0 < value < 1.0:
                raise ValueError(f"{field_name} must be strictly between zero and one.")
            object.__setattr__(self, field_name, value)
        for field_name in ("frequency_step_hz", "frequency_margin_hz"):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(f"{field_name} must be finite and positive.")
            object.__setattr__(self, field_name, value)
        for field_name in (
            "oddball_frequency_hz",
            "base_frequency_hz",
            "max_harmonic_hz",
            "noise_half_width_hz",
            "harmonic_z_threshold",
        ):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(f"{field_name} must be finite and positive.")
            object.__setattr__(self, field_name, value)
        if self.max_harmonic_hz < self.oddball_frequency_hz:
            raise ValueError("max_harmonic_hz must contain at least one oddball harmonic.")
        if int(self.harmonic_z_ddof) < 0:
            raise ValueError("harmonic_z_ddof must be non-negative.")
        object.__setattr__(self, "harmonic_z_ddof", int(self.harmonic_z_ddof))
        for field_name in ("cluster_entry_alpha", "cluster_alpha_per_tail"):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or not 0.0 < value < 1.0:
                raise ValueError(f"{field_name} must be strictly between zero and one.")
            object.__setattr__(self, field_name, value)

    @property
    def designs(self) -> tuple[AnalysisDesign, ...]:
        return (AnalysisDesign.INDEPENDENT_GROUPS, AnalysisDesign.PAIRED_CONDITIONS)

    @property
    def replicates_per_design(self) -> int:
        return len(self.scenarios) * self.replicates_per_scenario

    @property
    def total_replicates(self) -> int:
        return len(self.designs) * self.replicates_per_design


DEFAULT_NULL_CALIBRATION_PROTOCOL = NullCalibrationProtocol()


@dataclass(frozen=True, slots=True)
class NullCalibrationTask:
    """One deterministic design x regime x replicate job."""

    design: AnalysisDesign
    scenario_id: str
    replicate_index: int

    @property
    def task_id(self) -> str:
        return f"{self.design.value}:{self.scenario_id}:{self.replicate_index:04d}"


@dataclass(frozen=True, slots=True)
class NullCalibrationReplicate:
    """Compact resumable result for one powered-null replicate."""

    task_id: str
    design: str
    scenario_id: str
    replicate_index: int
    data_seed: int
    permutation_seed: int
    status: str
    selected_orders: tuple[int, ...] = ()
    global_rejection: bool = False
    positive_rejection: bool = False
    negative_rejection: bool = False
    permutation_assignment_hash: str = ""
    elapsed_seconds: float = 0.0
    error: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"complete", "no_selection", "error"}:
            raise ValueError(f"Unsupported calibration replicate status: {self.status!r}.")
        if self.status == "complete" and not self.selected_orders:
            raise ValueError("Completed calibration replicates require selected_orders.")
        if self.status != "complete" and (self.global_rejection or self.positive_rejection or self.negative_rejection):
            raise ValueError("Non-completed replicates cannot reject the null.")
        if self.global_rejection != (self.positive_rejection or self.negative_rejection):
            raise ValueError("global_rejection must equal the union of tail rejections.")
        if self.status == "error" and not self.error:
            raise ValueError("Error calibration replicates require an error message.")
        if not np.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0.0:
            raise ValueError("elapsed_seconds must be finite and non-negative.")


def canonical_json_bytes(value: object) -> bytes:
    """Return stable UTF-8 JSON bytes for fingerprints and receipts."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def protocol_payload(protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL) -> dict[str, Any]:
    """Return the frozen protocol plus the numerical method identities."""

    payload = asdict(protocol)
    payload.update(
        {
            "calibration_implementation_version": CALIBRATION_IMPLEMENTATION_VERSION,
            "method_version": METHOD_VERSION,
            "sensor_adjacency_version": BIOSEMI64_ADJACENCY_VERSION,
            "sensor_adjacency_fingerprint_sha256": BIOSEMI64_ADJACENCY_FINGERPRINT,
            "harmonic_selection_mode": "automatic",
            "frequency_correlation_geometry": "physical_fft_bin_ar1",
            "determinism_check": {
                "protocol_id": CALIBRATION_DETERMINISM_PROTOCOL_ID,
                "permutations_per_replicate": CALIBRATION_DETERMINISM_PERMUTATIONS,
                "permutation_batch_size": CALIBRATION_DETERMINISM_BATCH_SIZE,
                "replicate_index": CALIBRATION_DETERMINISM_REPLICATE_INDEX,
            },
        }
    )
    # Normalize dataclass tuples into the exact JSON list shape stored in the
    # committed protocol/receipt documents.
    return json.loads(json.dumps(payload))


def protocol_fingerprint(protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL) -> str:
    """Fingerprint every frozen scientific and acceptance parameter."""

    return hashlib.sha256(canonical_json_bytes(protocol_payload(protocol))).hexdigest()


def calibration_tasks(
    protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL,
) -> tuple[NullCalibrationTask, ...]:
    """Return all official tasks in deterministic receipt order."""

    return tuple(
        NullCalibrationTask(
            design=design,
            scenario_id=scenario.scenario_id,
            replicate_index=replicate_index,
        )
        for design in protocol.designs
        for scenario in protocol.scenarios
        for replicate_index in range(protocol.replicates_per_scenario)
    )


def task_seeds(task: NullCalibrationTask, *, protocol_id: str = CALIBRATION_PROTOCOL_ID) -> tuple[int, int]:
    """Return stable, independent uint32 data and permutation seeds."""

    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "protocol_id": protocol_id,
                "design": task.design.value,
                "scenario_id": task.scenario_id,
                "replicate_index": int(task.replicate_index),
            }
        )
    ).digest()
    return (
        int.from_bytes(digest[:4], byteorder="little", signed=False),
        int.from_bytes(digest[4:8], byteorder="little", signed=False),
    )


def determinism_tasks(
    protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL,
) -> tuple[NullCalibrationTask, ...]:
    """Return the two frozen non-official tasks used for execution checks."""

    if len(protocol.scenarios) < 2:
        raise ValueError("The determinism check requires at least two scenarios.")
    return (
        NullCalibrationTask(
            design=AnalysisDesign.INDEPENDENT_GROUPS,
            scenario_id=protocol.scenarios[0].scenario_id,
            replicate_index=CALIBRATION_DETERMINISM_REPLICATE_INDEX,
        ),
        NullCalibrationTask(
            design=AnalysisDesign.PAIRED_CONDITIONS,
            scenario_id=protocol.scenarios[1].scenario_id,
            replicate_index=CALIBRATION_DETERMINISM_REPLICATE_INDEX,
        ),
    )


def calibration_frequency_header(
    protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL,
) -> tuple[str, ...]:
    """Build a full default-domain FFT header with complete edge noise windows."""

    highest_hz = protocol.max_harmonic_hz + protocol.frequency_margin_hz
    bin_count = int(round(highest_hz / protocol.frequency_step_hz)) + 1
    frequencies = np.arange(bin_count, dtype=np.float64) * protocol.frequency_step_hz
    return ("Electrode", *(f"{frequency:.6f}_Hz" for frequency in frequencies))


def _scenario_by_id(protocol: NullCalibrationProtocol, scenario_id: str) -> NullCalibrationScenario:
    for scenario in protocol.scenarios:
        if scenario.scenario_id == scenario_id:
            return scenario
    raise KeyError(f"Unknown calibration scenario: {scenario_id!r}.")


def _correlated_standard_field(
    rng: np.random.Generator,
    *,
    participant_count: int,
    sensor_count: int,
    selected_frequencies_hz: np.ndarray,
    frequency_step_hz: float,
    scenario: NullCalibrationScenario,
) -> np.ndarray:
    frequencies_hz = np.asarray(selected_frequencies_hz, dtype=np.float64)
    if frequencies_hz.ndim != 1 or frequencies_hz.size < 1:
        raise ValueError("selected_frequencies_hz must be a non-empty vector.")
    if np.any(~np.isfinite(frequencies_hz)) or np.any(np.diff(frequencies_hz) <= 0.0):
        raise ValueError("selected_frequencies_hz must be finite and strictly increasing.")
    step_hz = float(frequency_step_hz)
    if not np.isfinite(step_hz) or step_hz <= 0.0:
        raise ValueError("frequency_step_hz must be finite and positive.")
    frequency_count = int(frequencies_hz.size)
    if scenario.distribution == "student_lognormal":
        degrees = float(scenario.student_t_degrees_of_freedom or 5.0)
        field = rng.standard_t(
            degrees,
            size=(participant_count, sensor_count, frequency_count),
        ) / np.sqrt(degrees / (degrees - 2.0))
    else:
        field = rng.standard_normal((participant_count, sensor_count, frequency_count))

    frequency_rho = scenario.frequency_correlation
    if frequency_rho > 0.0:
        physical_bin_gaps = np.rint(np.diff(frequencies_hz) / step_hz).astype(np.int64)
        if np.any(physical_bin_gaps < 1) or np.any(
            np.abs(np.diff(frequencies_hz) - physical_bin_gaps * step_hz) > 1e-9
        ):
            raise ValueError("Selected calibration frequencies must lie on the declared FFT grid.")
        for index in range(1, frequency_count):
            physical_rho = frequency_rho ** int(physical_bin_gaps[index - 1])
            innovation_scale = np.sqrt(1.0 - physical_rho**2)
            field[..., index] = physical_rho * field[..., index - 1] + innovation_scale * field[..., index]

    sensor_smoothing = scenario.sensor_smoothing
    if sensor_smoothing > 0.0:
        adjacency = biosemi64_spatial_adjacency()
        row_sums = np.sum(adjacency, axis=1, keepdims=True)
        normalized = np.divide(
            adjacency,
            row_sums,
            out=np.zeros_like(adjacency, dtype=np.float64),
            where=row_sums > 0.0,
        )
        neighbor_mean = np.einsum("ij,pjf->pif", normalized, field, optimize=True)
        field = np.sqrt(1.0 - sensor_smoothing) * field + np.sqrt(sensor_smoothing) * neighbor_mean
    return np.asarray(field, dtype=np.float64)


def _paired_or_independent_fields(
    rng: np.random.Generator,
    *,
    design: AnalysisDesign,
    participant_counts: tuple[int, int],
    sensor_count: int,
    selected_frequencies_hz: np.ndarray,
    frequency_step_hz: float,
    scenario: NullCalibrationScenario,
) -> tuple[np.ndarray, np.ndarray]:
    if design is AnalysisDesign.PAIRED_CONDITIONS:
        participant_count = participant_counts[0]
        shared = _correlated_standard_field(
            rng,
            participant_count=participant_count,
            sensor_count=sensor_count,
            selected_frequencies_hz=selected_frequencies_hz,
            frequency_step_hz=frequency_step_hz,
            scenario=scenario,
        )
        residual_a = _correlated_standard_field(
            rng,
            participant_count=participant_count,
            sensor_count=sensor_count,
            selected_frequencies_hz=selected_frequencies_hz,
            frequency_step_hz=frequency_step_hz,
            scenario=scenario,
        )
        residual_b = _correlated_standard_field(
            rng,
            participant_count=participant_count,
            sensor_count=sensor_count,
            selected_frequencies_hz=selected_frequencies_hz,
            frequency_step_hz=frequency_step_hz,
            scenario=scenario,
        )
        shared_fraction = scenario.paired_shared_fraction
        shared_scale = np.sqrt(shared_fraction)
        residual_scale = np.sqrt(1.0 - shared_fraction)
        return (
            shared_scale * shared + residual_scale * residual_a,
            shared_scale * shared + residual_scale * residual_b,
        )
    return (
        _correlated_standard_field(
            rng,
            participant_count=participant_counts[0],
            sensor_count=sensor_count,
            selected_frequencies_hz=selected_frequencies_hz,
            frequency_step_hz=frequency_step_hz,
            scenario=scenario,
        ),
        _correlated_standard_field(
            rng,
            participant_count=participant_counts[1],
            sensor_count=sensor_count,
            selected_frequencies_hz=selected_frequencies_hz,
            frequency_step_hz=frequency_step_hz,
            scenario=scenario,
        ),
    )


def _simulated_amplitudes(
    rng: np.random.Generator,
    *,
    task: NullCalibrationTask,
    protocol: NullCalibrationProtocol,
    selected_frequencies_hz: np.ndarray,
    target_selected_indices: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    scenario = _scenario_by_id(protocol, task.scenario_id)
    participant_counts = (
        protocol.independent_group_sizes
        if task.design is AnalysisDesign.INDEPENDENT_GROUPS
        else (protocol.paired_participant_count, protocol.paired_participant_count)
    )
    field_a, field_b = _paired_or_independent_fields(
        rng,
        design=task.design,
        participant_counts=participant_counts,
        sensor_count=64,
        selected_frequencies_hz=selected_frequencies_hz,
        frequency_step_hz=protocol.frequency_step_hz,
        scenario=scenario,
    )
    amplitude_a = np.exp(np.clip(scenario.log_scale * field_a, -6.0, 6.0))
    amplitude_b = np.exp(np.clip(scenario.log_scale * field_b, -6.0, 6.0))
    for target_index, common_boost in zip(
        target_selected_indices,
        scenario.target_boosts,
        strict=False,
    ):
        amplitude_a[..., int(target_index)] += common_boost
        amplitude_b[..., int(target_index)] += common_boost
    return (
        np.ascontiguousarray(amplitude_a, dtype=np.float64),
        np.ascontiguousarray(amplitude_b, dtype=np.float64),
    )


def run_null_calibration_replicate(
    task: NullCalibrationTask,
    protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL,
) -> NullCalibrationReplicate:
    """Run one complete automatic-selection-plus-permutation null replicate."""

    started = perf_counter()
    data_seed, permutation_seed = task_seeds(task, protocol_id=protocol.protocol_id)
    try:
        method = FreeHarmonicMethodSpec(
            method_version=METHOD_VERSION,
            oddball_frequency_hz=protocol.oddball_frequency_hz,
            base_frequency_hz=protocol.base_frequency_hz,
            max_harmonic_hz=protocol.max_harmonic_hz,
            noise_half_width_hz=protocol.noise_half_width_hz,
            harmonic_z_threshold=protocol.harmonic_z_threshold,
            harmonic_z_ddof=protocol.harmonic_z_ddof,
            cluster_entry_alpha=protocol.cluster_entry_alpha,
            cluster_alpha_per_tail=protocol.cluster_alpha_per_tail,
            n_permutations=protocol.permutations_per_replicate,
            seed=permutation_seed,
            sensor_adjacency_version=BIOSEMI64_ADJACENCY_VERSION,
        )
        plan = build_frequency_window_plan(calibration_frequency_header(protocol), method)
        amplitude_a, amplitude_b = _simulated_amplitudes(
            np.random.default_rng(data_seed),
            task=task,
            protocol=protocol,
            selected_frequencies_hz=plan.selected_frequencies_hz,
            target_selected_indices=plan.target_selected_indices,
        )
        selection = select_harmonics(
            np.mean(amplitude_a, axis=(0, 1)),
            np.mean(amplitude_b, axis=(0, 1)),
            plan,
            method,
        )
        snr_a = compute_participant_snr(amplitude_a, plan)
        snr_b = compute_participant_snr(amplitude_b, plan)
        values_a = l2_normalize_snr(select_snr_harmonics(snr_a, selection))
        values_b = l2_normalize_snr(select_snr_harmonics(snr_b, selection))
        result = run_cluster_permutation(
            values_a,
            values_b,
            design=task.design,
            method=method,
            batch_size=protocol.permutation_batch_size,
        )
    except NoHarmonicsSelectedError:
        return NullCalibrationReplicate(
            task_id=task.task_id,
            design=task.design.value,
            scenario_id=task.scenario_id,
            replicate_index=task.replicate_index,
            data_seed=data_seed,
            permutation_seed=permutation_seed,
            status="no_selection",
            elapsed_seconds=perf_counter() - started,
        )
    except Exception as exc:  # pragma: no cover - exercised by the long runner's failure receipt
        return NullCalibrationReplicate(
            task_id=task.task_id,
            design=task.design.value,
            scenario_id=task.scenario_id,
            replicate_index=task.replicate_index,
            data_seed=data_seed,
            permutation_seed=permutation_seed,
            status="error",
            elapsed_seconds=perf_counter() - started,
            error=f"{type(exc).__name__}: {exc}",
        )

    positive_rejection = any(cluster.sign == "positive" and cluster.significant for cluster in result.clusters)
    negative_rejection = any(cluster.sign == "negative" and cluster.significant for cluster in result.clusters)
    return NullCalibrationReplicate(
        task_id=task.task_id,
        design=task.design.value,
        scenario_id=task.scenario_id,
        replicate_index=task.replicate_index,
        data_seed=data_seed,
        permutation_seed=permutation_seed,
        status="complete",
        selected_orders=tuple(int(value) for value in selection.selected_orders),
        global_rejection=positive_rejection or negative_rejection,
        positive_rejection=positive_rejection,
        negative_rejection=negative_rejection,
        permutation_assignment_hash=result.permutation_assignment_hash,
        elapsed_seconds=perf_counter() - started,
    )


def clopper_pearson_upper(rejections: int, replicates: int, *, confidence: float) -> float:
    """Return the exact one-sided Clopper-Pearson binomial upper bound."""

    rejected = int(rejections)
    total = int(replicates)
    confidence_level = float(confidence)
    if total < 1 or not 0 <= rejected <= total:
        raise ValueError("Binomial counts must satisfy 0 <= rejections <= replicates.")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence must be strictly between zero and one.")
    if rejected == total:
        return 1.0
    return float(beta.ppf(confidence_level, rejected + 1, total - rejected))


def critical_rejection_count(*, replicates: int, confidence: float, error_bound: float) -> int:
    """Largest rejection count whose exact upper bound is below ``error_bound``."""

    valid = [
        rejected
        for rejected in range(int(replicates) + 1)
        if clopper_pearson_upper(rejected, replicates, confidence=confidence) < float(error_bound)
    ]
    return max(valid, default=-1)


def replicate_payload(result: NullCalibrationReplicate) -> dict[str, Any]:
    """Return one canonical JSON-compatible checkpoint row."""

    return asdict(result)


def replicate_from_payload(payload: Mapping[str, Any]) -> NullCalibrationReplicate:
    """Validate and restore one checkpoint row."""

    values = dict(payload)
    values["selected_orders"] = tuple(int(value) for value in values.get("selected_orders", ()))
    return NullCalibrationReplicate(**values)


def validate_replicate_for_task(
    result: NullCalibrationReplicate,
    task: NullCalibrationTask,
    *,
    protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL,
) -> None:
    """Reject checkpoint rows that do not exactly represent their scheduled task."""

    expected_data_seed, expected_permutation_seed = task_seeds(
        task,
        protocol_id=protocol.protocol_id,
    )
    expected = {
        "task_id": task.task_id,
        "design": task.design.value,
        "scenario_id": task.scenario_id,
        "replicate_index": int(task.replicate_index),
        "data_seed": expected_data_seed,
        "permutation_seed": expected_permutation_seed,
    }
    mismatches = [
        f"{field_name}={getattr(result, field_name)!r}, expected {expected_value!r}"
        for field_name, expected_value in expected.items()
        if getattr(result, field_name) != expected_value
    ]
    if result.status == "complete":
        selected_orders = tuple(int(value) for value in result.selected_orders)
        if any(value < 1 for value in selected_orders) or tuple(sorted(set(selected_orders))) != selected_orders:
            mismatches.append("selected_orders must be positive, unique, and increasing")
        assignment_hash = result.permutation_assignment_hash
        if len(assignment_hash) != 64 or any(character not in "0123456789abcdef" for character in assignment_hash):
            mismatches.append("permutation_assignment_hash must be one lowercase SHA-256 digest")
    elif result.permutation_assignment_hash:
        mismatches.append("non-complete rows must not contain an assignment hash")
    if mismatches:
        raise ValueError(f"Calibration row {task.task_id!r} does not match its frozen task: " + "; ".join(mismatches))


def ordered_results_fingerprint(results: Sequence[NullCalibrationReplicate]) -> str:
    """Fingerprint ordered scientific rows for serial/resume/parallel comparison."""

    ordered = sorted(results, key=lambda value: value.task_id)
    scientific_rows = []
    for value in ordered:
        payload = replicate_payload(value)
        payload.pop("elapsed_seconds", None)
        scientific_rows.append(payload)
    return hashlib.sha256(b"\n".join(canonical_json_bytes(payload) for payload in scientific_rows)).hexdigest()


def validate_determinism_check(payload: Mapping[str, Any]) -> None:
    """Validate the serial/checkpoint/parallel execution-equivalence receipt."""

    tasks = determinism_tasks()
    expected_task_ids = [task.task_id for task in tasks]
    if payload.get("protocol_id") != CALIBRATION_DETERMINISM_PROTOCOL_ID:
        raise ValueError("Determinism-check protocol ID does not match.")
    if payload.get("task_ids") != expected_task_ids:
        raise ValueError("Determinism-check task IDs do not match.")
    if int(payload.get("permutations_per_replicate", -1)) != CALIBRATION_DETERMINISM_PERMUTATIONS:
        raise ValueError("Determinism-check permutation count does not match.")
    if int(payload.get("permutation_batch_size", -1)) != CALIBRATION_DETERMINISM_BATCH_SIZE:
        raise ValueError("Determinism-check batch size does not match.")
    hashes = tuple(
        payload.get(field_name)
        for field_name in (
            "serial_results_sha256",
            "resumed_results_sha256",
            "parallel_results_sha256",
        )
    )
    if any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in hashes
    ):
        raise ValueError("Determinism-check fingerprints must be SHA-256 digests.")
    if len(set(hashes)) != 1 or payload.get("status") != "pass":
        raise ValueError("Serial, resumed, and parallel scientific rows do not match.")
    official_task_ids = {task.task_id for task in calibration_tasks()}
    if any(task_id in official_task_ids for task_id in expected_task_ids):
        raise ValueError("Determinism-check tasks must not overlap official powered tasks.")


def _group_summary(
    results: Sequence[NullCalibrationReplicate],
    *,
    confidence: float,
    error_bound: float,
) -> dict[str, Any]:
    complete = tuple(value for value in results if value.status == "complete")
    no_selection = sum(value.status == "no_selection" for value in results)
    errors = sum(value.status == "error" for value in results)
    rejections = sum(value.global_rejection for value in results)
    positive = sum(value.positive_rejection for value in results)
    negative = sum(value.negative_rejection for value in results)
    selected_ceilings = tuple(max(value.selected_orders) for value in complete)
    upper = clopper_pearson_upper(rejections, len(results), confidence=confidence)
    return {
        "replicates": len(results),
        "completed": len(complete),
        "no_selection": no_selection,
        "errors": errors,
        "global_rejections": rejections,
        "positive_rejections": positive,
        "negative_rejections": negative,
        "global_rejection_rate": rejections / len(results),
        "upper_confidence": confidence,
        "upper_bound": upper,
        "acceptance_error_bound": error_bound,
        "critical_rejection_count": critical_rejection_count(
            replicates=len(results),
            confidence=confidence,
            error_bound=error_bound,
        ),
        "selected_ceiling_min": min(selected_ceilings, default=None),
        "selected_ceiling_max": max(selected_ceilings, default=None),
        "selected_ceiling_distinct_count": len(set(selected_ceilings)),
        "passes_error_bound": upper < error_bound,
        "passes_validity": errors == 0 and no_selection == 0 and len(set(selected_ceilings)) >= 2,
    }


def summarize_null_calibration(
    results: Iterable[NullCalibrationReplicate],
    protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL,
) -> dict[str, Any]:
    """Validate all official tasks and return the prespecified acceptance summary."""

    rows = tuple(results)
    expected_tasks = calibration_tasks(protocol)
    expected_ids = tuple(task.task_id for task in expected_tasks)
    row_ids = tuple(value.task_id for value in rows)
    task_counts = Counter(row_ids)
    duplicate_ids = sorted(task_id for task_id, count in task_counts.items() if count > 1)
    row_by_id = {value.task_id: value for value in rows}
    missing_ids = tuple(task_id for task_id in expected_ids if task_id not in row_by_id)
    expected_id_set = set(expected_ids)
    unexpected_ids = tuple(task_id for task_id in row_ids if task_id not in expected_id_set)
    ordered = tuple(row_by_id[task_id] for task_id in expected_ids if task_id in row_by_id)
    invalid_task_rows: list[str] = []
    for task in expected_tasks:
        result = row_by_id.get(task.task_id)
        if result is None:
            continue
        try:
            validate_replicate_for_task(result, task, protocol=protocol)
        except ValueError as exc:
            invalid_task_rows.append(str(exc))

    design_summaries: dict[str, Any] = {}
    scenario_summaries: dict[str, Any] = {}
    for design in protocol.designs:
        design_rows = tuple(value for value in ordered if value.design == design.value)
        if design_rows:
            design_summaries[design.value] = _group_summary(
                design_rows,
                confidence=protocol.design_upper_confidence,
                error_bound=protocol.design_error_bound,
            )
        for scenario in protocol.scenarios:
            scenario_rows = tuple(value for value in design_rows if value.scenario_id == scenario.scenario_id)
            if scenario_rows:
                scenario_summaries[f"{design.value}:{scenario.scenario_id}"] = _group_summary(
                    scenario_rows,
                    confidence=protocol.scenario_upper_confidence,
                    error_bound=protocol.scenario_error_bound,
                )

    complete_task_set = not duplicate_ids and not missing_ids and not unexpected_ids and not invalid_task_rows
    design_pass = len(design_summaries) == len(protocol.designs) and all(
        summary["passes_error_bound"] and summary["passes_validity"] for summary in design_summaries.values()
    )
    scenario_pass = len(scenario_summaries) == len(protocol.designs) * len(protocol.scenarios) and all(
        summary["passes_error_bound"] and summary["passes_validity"] for summary in scenario_summaries.values()
    )
    return {
        "status": "pass" if complete_task_set and design_pass and scenario_pass else "fail",
        "complete_task_set": complete_task_set,
        "expected_replicates": protocol.total_replicates,
        "received_replicates": len(rows),
        "duplicate_task_ids": duplicate_ids,
        "missing_task_ids": missing_ids,
        "unexpected_task_ids": unexpected_ids,
        "invalid_task_rows": invalid_task_rows,
        "designs": design_summaries,
        "scenarios": scenario_summaries,
        "ordered_results_sha256": ordered_results_fingerprint(ordered) if ordered else None,
    }


def build_calibration_receipt(
    results: Iterable[NullCalibrationReplicate],
    *,
    determinism_check: Mapping[str, Any],
    protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL,
    runtime: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the compact official receipt written after the long run."""

    rows = tuple(results)
    determinism = dict(determinism_check)
    validate_determinism_check(determinism)
    assessment = summarize_null_calibration(rows, protocol)
    powered_null_status = assessment["status"]
    assessment["powered_null_status"] = powered_null_status
    assessment["determinism_check"] = determinism
    assessment["status"] = "pass" if powered_null_status == "pass" and determinism["status"] == "pass" else "fail"
    return {
        "schema_version": CALIBRATION_RECEIPT_SCHEMA_VERSION,
        "protocol_id": protocol.protocol_id,
        "protocol_fingerprint_sha256": protocol_fingerprint(protocol),
        "protocol": protocol_payload(protocol),
        "status": "complete",
        "assessment": assessment,
        "runtime": dict(runtime or {}),
    }


def pending_calibration_receipt_template(
    protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL,
) -> dict[str, Any]:
    """Return a non-result template that freezes schema and protocol only."""

    return {
        "schema_version": CALIBRATION_RECEIPT_SCHEMA_VERSION,
        "protocol_id": protocol.protocol_id,
        "protocol_fingerprint_sha256": protocol_fingerprint(protocol),
        "protocol": protocol_payload(protocol),
        "status": "pending",
        "assessment": None,
        "runtime": None,
    }


def validate_calibration_receipt(
    payload: Mapping[str, Any],
    *,
    protocol: NullCalibrationProtocol = DEFAULT_NULL_CALIBRATION_PROTOCOL,
    allow_pending: bool = False,
) -> None:
    """Fail if a receipt/template is stale, malformed, or scientifically mismatched."""

    expected_fingerprint = protocol_fingerprint(protocol)
    if int(payload.get("schema_version", -1)) != CALIBRATION_RECEIPT_SCHEMA_VERSION:
        raise ValueError("Calibration receipt schema version does not match.")
    if payload.get("protocol_id") != protocol.protocol_id:
        raise ValueError("Calibration receipt protocol ID does not match.")
    if payload.get("protocol_fingerprint_sha256") != expected_fingerprint:
        raise ValueError("Calibration receipt protocol fingerprint is stale.")
    if payload.get("protocol") != protocol_payload(protocol):
        raise ValueError("Calibration receipt protocol payload does not match.")
    status = payload.get("status")
    if status == "pending":
        if not allow_pending or payload.get("assessment") is not None:
            raise ValueError("Pending calibration receipt is not allowed here.")
        return
    if status != "complete" or not isinstance(payload.get("assessment"), Mapping):
        raise ValueError("Completed calibration receipt requires an assessment mapping.")
    assessment = payload["assessment"]
    determinism = assessment.get("determinism_check")
    if not isinstance(determinism, Mapping):
        raise ValueError("Completed calibration receipt requires a determinism check.")
    validate_determinism_check(determinism)
    powered_status = assessment.get("powered_null_status")
    expected_status = "pass" if powered_status == "pass" and determinism.get("status") == "pass" else "fail"
    if assessment.get("status") != expected_status:
        raise ValueError("Calibration receipt overall assessment status is inconsistent.")


__all__ = [
    "CALIBRATION_DETERMINISM_BATCH_SIZE",
    "CALIBRATION_DETERMINISM_PERMUTATIONS",
    "CALIBRATION_DETERMINISM_PROTOCOL_ID",
    "CALIBRATION_DETERMINISM_REPLICATE_INDEX",
    "CALIBRATION_DESIGN_BOUND",
    "CALIBRATION_DESIGN_CONFIDENCE",
    "CALIBRATION_PERMUTATIONS_PER_REPLICATE",
    "CALIBRATION_IMPLEMENTATION_VERSION",
    "CALIBRATION_PROTOCOL_ID",
    "CALIBRATION_RECEIPT_SCHEMA_VERSION",
    "CALIBRATION_REPLICATES_PER_SCENARIO",
    "CALIBRATION_SCENARIOS",
    "CALIBRATION_SCENARIO_BOUND",
    "CALIBRATION_SCENARIO_CONFIDENCE",
    "DEFAULT_NULL_CALIBRATION_PROTOCOL",
    "NullCalibrationProtocol",
    "NullCalibrationReplicate",
    "NullCalibrationScenario",
    "NullCalibrationTask",
    "build_calibration_receipt",
    "calibration_frequency_header",
    "calibration_tasks",
    "canonical_json_bytes",
    "clopper_pearson_upper",
    "critical_rejection_count",
    "determinism_tasks",
    "ordered_results_fingerprint",
    "pending_calibration_receipt_template",
    "protocol_fingerprint",
    "protocol_payload",
    "replicate_from_payload",
    "replicate_payload",
    "run_null_calibration_replicate",
    "summarize_null_calibration",
    "task_seeds",
    "validate_calibration_receipt",
    "validate_determinism_check",
    "validate_replicate_for_task",
]
