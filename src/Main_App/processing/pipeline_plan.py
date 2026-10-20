"""Versioned, fixed-slot processing methods without scientific or GUI imports.

Project files select IDs, never Python imports or executable code. Built-in
callables remain at their current numerical owners; replacements are explicitly
registered by application code and must accept the same slot-specific arguments.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


PIPELINE_SETTINGS_KEY = "processing_pipeline"
PIPELINE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class PipelineStep:
    id: str
    label: str
    phase: str
    default_method: str
    parameter_keys: tuple[str, ...] = ()


PIPELINE_STEPS = (
    PipelineStep("raw_screening", "Raw signal screening", "admission", "qualified_raw_screening_v1", ("raw_signal_screening_enabled", "removed_electrode_detection_mode")),
    PipelineStep("condition_raw_screening", "Condition signal screening", "review", "qualified_condition_screening_v1", ("raw_signal_screening_enabled", "removed_electrode_detection_mode")),
    PipelineStep("raw_spectral_screening", "Raw spectral screening", "review", "condition_spectral_screening_v1", ("raw_spectral_screening",)),
    PipelineStep("initial_reference", "Initial reference", "preprocessing", "resolved_reference_v1", ("initial_reference", "initial_reference_channels", "ref_channel1", "ref_channel2")),
    PipelineStep("reference_channel_drop", "Reference channel removal", "preprocessing", "selected_reference_drop_v1", ("drop_reference_channels",)),
    PipelineStep("channel_selection", "Scalp channel selection", "preprocessing", "ordered_scalp_limit_v1", ("max_idx_keep", "max_chan_idx_keep")),
    PipelineStep("temporal_filter", "Temporal filter", "preprocessing", "fir_hamming_zero_double_v1", ("high_pass", "low_pass")),
    PipelineStep("line_noise_filter", "Line noise filter", "preprocessing", "fft_multinotch_v1", ("line_noise_filter_enabled", "line_noise_frequency_hz")),
    PipelineStep("resample", "Resampling", "preprocessing", "guarded_fft_resample_v1", ("downsample_rate",)),
    PipelineStep("bad_channel_screening", "Bad channel screening", "preprocessing", "reviewed_kurtosis_v1", ("kurtosis_screening_enabled", "reject_thresh")),
    PipelineStep("interpolation", "Interpolation", "preprocessing", "mne_spherical_spline_v1"),
    PipelineStep("final_reference", "Final reference", "preprocessing", "scalp_average_v1"),
    PipelineStep("condition_repairs", "Condition-specific repairs", "preprocessing", "reviewed_interval_repairs_v1"),
    PipelineStep("epoching", "Reviewed epochs", "epochs", "reviewed_onbin_epochs_v1"),
    PipelineStep("repetition_average", "Repetition averaging", "spectral", "float64_repetition_mean_v1"),
    PipelineStep("spectrum", "Amplitude spectrum", "spectral", "fft_amplitude_v1"),
    PipelineStep("full_snr", "Full-spectrum SNR", "spectral", "neighbor_noise_full_snr_v1"),
    PipelineStep("target_metrics", "Target-frequency metrics", "spectral", "fpvs_neighbor_noise_v1"),
    PipelineStep("occurrence_average", "Occurrence aggregation", "spectral", "equal_occurrence_mean_v1"),
)
_STEPS = {step.id: step for step in PIPELINE_STEPS}


class PipelineConfigurationError(ValueError):
    """The project selects an unavailable or incompatible processing method."""


class PipelineExecutionError(RuntimeError):
    """A selected replacement failed; incomplete numerical results are invalid."""


class PipelineCancelled(RuntimeError):
    """Cooperative cancellation remains distinct from a method failure."""


@dataclass(frozen=True)
class PipelineMethod:
    stage_id: str
    method_id: str
    label: str
    implementation: Callable[..., Any] | None = None
    required_capabilities: tuple[str, ...] = ()


_BUILTIN_METHODS = tuple(
    PipelineMethod(step.id, step.default_method, step.label) for step in PIPELINE_STEPS
)
_BUILTIN_BY_ID = {method.method_id: method for method in _BUILTIN_METHODS}


@dataclass(frozen=True)
class PipelineRegistry:
    """An immutable application-owned catalog; never serialized into a project."""
    methods: tuple[PipelineMethod, ...] = _BUILTIN_METHODS

    def __post_init__(self) -> None:
        if not isinstance(self.methods, tuple):
            raise PipelineConfigurationError("Pipeline methods must be an immutable tuple.")
        seen = set()
        for method in self.methods:
            if not isinstance(method, PipelineMethod) or method.stage_id not in _STEPS:
                raise PipelineConfigurationError("A method must belong to a known pipeline step.")
            if not isinstance(method.method_id, str) or not method.method_id.strip() or method.method_id in seen:
                raise PipelineConfigurationError("Pipeline method IDs must be nonempty and unique.")
            seen.add(method.method_id)
            builtin = _BUILTIN_BY_ID.get(method.method_id)
            if builtin is not None and method != builtin:
                raise PipelineConfigurationError("Changing a built-in method requires a new method ID/version.")
            if builtin is None and not callable(method.implementation):
                raise PipelineConfigurationError("A replacement method requires an executable implementation.")
            if not isinstance(method.required_capabilities, tuple) or any(
                not isinstance(name, str) or not name for name in method.required_capabilities
            ):
                raise PipelineConfigurationError("Capability requirements must be immutable named flags.")
        if not set(_BUILTIN_BY_ID).issubset(seen):
            raise PipelineConfigurationError("A registry must retain the historical built-in methods.")

    def with_methods(self, *methods: PipelineMethod) -> PipelineRegistry:
        return PipelineRegistry(self.methods + methods)

    def method(self, stage_id: str, method_id: str) -> PipelineMethod:
        for candidate in self.methods:
            if candidate.method_id == method_id:
                if candidate.stage_id != stage_id:
                    raise PipelineConfigurationError(f"Method {method_id!r} does not belong to step {stage_id!r}.")
                return candidate
        raise PipelineConfigurationError(f"Unavailable processing method {method_id!r} for step {stage_id!r}.")

    def available_methods(self, stage_id: str, contract: Any = None) -> tuple[PipelineMethod, ...]:
        if stage_id not in _STEPS:
            raise PipelineConfigurationError(f"Unknown processing step {stage_id!r}.")
        return tuple(method for method in self.methods if method.stage_id == stage_id and (
            contract is None or all(getattr(contract, name, False) is True for name in method.required_capabilities)
        ))


BUILTIN_PIPELINE_REGISTRY = PipelineRegistry()


def get_pipeline_registry() -> PipelineRegistry:
    """Return the application catalog; future methods are registered here in code."""
    return BUILTIN_PIPELINE_REGISTRY


@dataclass(frozen=True)
class PipelinePlan:
    methods: tuple[PipelineMethod, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.methods, tuple) or tuple(method.stage_id for method in self.methods) != tuple(_STEPS):
            raise PipelineConfigurationError("A pipeline plan must retain every step in its fixed order.")

    @property
    def is_legacy_default(self) -> bool:
        return self.methods == _BUILTIN_METHODS

    def to_config(self) -> dict[str, Any]:
        return {"schema_version": PIPELINE_SCHEMA_VERSION,
                "methods": {method.stage_id: method.method_id for method in self.methods}}

    def validate_capabilities(self, contract: Any) -> None:
        for method in self.methods:
            missing = [name for name in method.required_capabilities if getattr(contract, name, False) is not True]
            if missing:
                raise PipelineConfigurationError(
                    f"Method {method.method_id!r} requires unavailable recording capabilities: {', '.join(missing)}."
                )

    def execute(self, stage_id: str, builtin: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run the selected implementation with the slot owner's typed arguments."""
        method = next((method for method in self.methods if method.stage_id == stage_id), None)
        if method is None:
            raise PipelineConfigurationError(f"Unknown processing step {stage_id!r}.")
        if method.implementation is None:
            return builtin(*args, **kwargs)
        try:
            return method.implementation(*args, **kwargs)
        except (PipelineExecutionError, PipelineCancelled):
            raise
        except Exception as exc:
            raise PipelineExecutionError(f"Processing method {method.method_id!r} failed in step {stage_id!r}.") from exc


def default_pipeline_config() -> dict[str, Any]:
    return PipelinePlan(_BUILTIN_METHODS).to_config()


def normalize_pipeline_config(value: Any, *, registry: PipelineRegistry | None = None) -> dict[str, Any]:
    registry = registry or get_pipeline_registry()
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "methods"}:
        raise PipelineConfigurationError("processing_pipeline requires schema_version and methods only; step order is fixed.")
    if value["schema_version"] != PIPELINE_SCHEMA_VERSION:
        raise PipelineConfigurationError("Unsupported processing pipeline schema version.")
    methods = value["methods"]
    if not isinstance(methods, Mapping) or set(methods) != set(_STEPS):
        raise PipelineConfigurationError("The processing pipeline must select exactly one method for every fixed step.")
    ordered = []
    for step in PIPELINE_STEPS:
        selected = methods[step.id]
        if not isinstance(selected, str):
            raise PipelineConfigurationError("Pipeline method selections must be registered versioned IDs.")
        ordered.append(registry.method(step.id, selected))
    return PipelinePlan(tuple(ordered)).to_config()


def resolve_pipeline_plan(settings: Mapping[str, Any] | None = None, *, registry: PipelineRegistry | None = None) -> PipelinePlan:
    registry = registry or get_pipeline_registry()
    settings = settings or {}
    config = normalize_pipeline_config(settings[PIPELINE_SETTINGS_KEY], registry=registry) if PIPELINE_SETTINGS_KEY in settings else default_pipeline_config()
    return PipelinePlan(tuple(registry.method(step.id, config["methods"][step.id]) for step in PIPELINE_STEPS))


def pipeline_fingerprint_payload(settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Keep legacy identities exact; bind any genuinely different method plan."""
    plan = resolve_pipeline_plan(settings)
    return {} if plan.is_legacy_default else {PIPELINE_SETTINGS_KEY: plan.to_config()}


def fingerprint_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(settings)
    result.pop(PIPELINE_SETTINGS_KEY, None)
    result.update(pipeline_fingerprint_payload(settings))
    return result
