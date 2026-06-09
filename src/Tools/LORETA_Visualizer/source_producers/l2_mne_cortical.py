"""Beta L2-MNE cortical-surface source producer.

This module owns calculation-side source-ready L2 minimum-norm estimates for
FPVS oddball topographies. It writes prepared JSON payloads for the visualizer
validator/importer. It does not import GUI, renderer, display transforms,
fsaverage display mesh loading, or prepared-payload importer code.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.LORETA_Visualizer.prepared_payload_validator import (
    PREPARED_SOURCE_MANIFEST_FORMAT,
    PREPARED_SOURCE_PAYLOAD_FORMAT,
    validate_prepared_source_manifest_json,
    validate_prepared_source_payload_json,
    validate_prepared_source_payload_mapping,
)
from Tools.LORETA_Visualizer.source_producers.contracts import ProducedPayload, SourceProducerRunResult

logger = logging.getLogger(__name__)

METHOD_ID_L2_MNE_CORTICAL_SURFACE_BETA = "l2_mne_cortical_surface_beta"
COORDINATE_SPACE_FSAVERAGE = "fsaverage_surface"
SOURCE_KIND_SURFACE_MESH = "surface_mesh"
HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT = "sum_sensor_topographies_then_invert"
HARMONIC_STRATEGY_SUM_SOURCE_MAGNITUDES = "invert_each_harmonic_then_sum_source_magnitudes"
DEFAULT_LAMBDA2 = 1.0 / 9.0


@dataclass(frozen=True)
class L2MNEProducerConfig:
    """Configuration for the beta L2-MNE cortical-surface producer."""

    selected_harmonics_hz: tuple[float, ...]
    method_id: str = METHOD_ID_L2_MNE_CORTICAL_SURFACE_BETA
    lambda2: float = DEFAULT_LAMBDA2
    harmonic_strategy: str = HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT
    apply_average_reference: bool = True
    montage_name: str = "BioSemi ActiveTwo 64-channel 10-10"
    harmonic_policy_id: str = "stats_group_significant_oddball_harmonics"
    template_subject: str = "fsaverage"
    value_label: str = "beta L2-MNE cortical source amplitude"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        selected = _validate_harmonics(self.selected_harmonics_hz)
        lambda2 = float(self.lambda2)
        if not np.isfinite(lambda2) or lambda2 <= 0.0:
            raise ValueError("L2-MNE lambda2 must be positive and finite.")
        if self.harmonic_strategy not in {
            HARMONIC_STRATEGY_SUM_SENSOR_TOPOGRAPHIES_THEN_INVERT,
            HARMONIC_STRATEGY_SUM_SOURCE_MAGNITUDES,
        }:
            raise ValueError(f"Unsupported L2-MNE harmonic strategy: {self.harmonic_strategy!r}.")
        object.__setattr__(self, "selected_harmonics_hz", selected)
        object.__setattr__(self, "lambda2", lambda2)
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class L2MNECorticalForwardModel:
    """Source-ready cortical surface forward/inverse model for L2-MNE."""

    channel_names: tuple[str, ...]
    source_points: np.ndarray
    leadfield: np.ndarray
    faces: np.ndarray
    coordinate_space: str = COORDINATE_SPACE_FSAVERAGE
    label: str = "fsaverage cortical surface"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_estimator: Callable[..., Sequence[float] | np.ndarray] | None = None

    def __post_init__(self) -> None:
        channels = tuple(_validate_channel_name(name) for name in self.channel_names)
        if not channels:
            raise ValueError("L2-MNE forward model requires at least one channel.")
        if len(set(channels)) != len(channels):
            raise ValueError("L2-MNE forward model channel names must be unique.")
        points = _validate_points(self.source_points, field_name="source_points")
        leadfield = _validate_matrix(self.leadfield, field_name="leadfield")
        source_estimator = self.source_estimator
        if source_estimator is not None and not callable(source_estimator):
            raise TypeError("L2-MNE source_estimator must be callable when provided.")
        if source_estimator is None and leadfield.shape != (len(channels), len(points)):
            raise ValueError(
                "L2-MNE leadfield must have shape n_channels x n_sources "
                f"({len(channels)} x {len(points)} expected, got {leadfield.shape})."
            )
        if source_estimator is not None and leadfield.shape[0] != len(channels):
            raise ValueError(
                "L2-MNE estimator-backed leadfield must have one row per channel "
                f"({len(channels)} expected, got {leadfield.shape[0]})."
            )
        faces = _validate_triangle_faces(self.faces, point_count=len(points))
        object.__setattr__(self, "channel_names", channels)
        object.__setattr__(self, "source_points", points)
        object.__setattr__(self, "leadfield", leadfield)
        object.__setattr__(self, "faces", faces)
        object.__setattr__(self, "coordinate_space", _validate_label(self.coordinate_space, "coordinate_space"))
        object.__setattr__(self, "label", _validate_label(self.label, "label"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class L2MNEFPVSCondition:
    """Frequency-domain FPVS condition topographies for source-ready L2-MNE."""

    condition_id: str
    label: str
    harmonic_topographies: Mapping[float, Sequence[float]]
    sensor_value_unit: str = "uV amplitude"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        condition_id = _slug(_validate_label(self.condition_id, "condition_id"))
        label = _validate_label(self.label, "label")
        lookup: dict[float, np.ndarray] = {}
        for harmonic, values in self.harmonic_topographies.items():
            key = _round_harmonic(float(harmonic))
            if key in lookup:
                raise ValueError(f"Duplicate harmonic topography for {key:g} Hz.")
            vector = np.asarray(values, dtype=float).reshape(-1)
            if len(vector) == 0 or not np.all(np.isfinite(vector)):
                raise ValueError(f"Harmonic topography for {key:g} Hz must contain finite values.")
            lookup[key] = vector.astype(float)
        if not lookup:
            raise ValueError("L2-MNE FPVS condition requires at least one harmonic topography.")
        object.__setattr__(self, "condition_id", condition_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "harmonic_topographies", lookup)
        object.__setattr__(self, "sensor_value_unit", _validate_label(self.sensor_value_unit, "sensor_value_unit"))
        object.__setattr__(self, "metadata", dict(self.metadata))


def compute_l2_mne_source_values(
    *,
    forward_model: L2MNECorticalForwardModel,
    condition: L2MNEFPVSCondition,
    config: L2MNEProducerConfig,
) -> np.ndarray:
    """Compute beta L2-MNE source amplitudes for one condition."""
    topographies = _selected_condition_topographies(
        condition,
        selected_harmonics=config.selected_harmonics_hz,
        n_channels=len(forward_model.channel_names),
        apply_average_reference=config.apply_average_reference,
    )

    if forward_model.source_estimator is not None:
        if config.harmonic_strategy == HARMONIC_STRATEGY_SUM_SOURCE_MAGNITUDES:
            values = np.sum(
                [
                    _source_amplitudes_from_topography(
                        forward_model,
                        topography,
                        lambda2=config.lambda2,
                    )
                    for topography in topographies
                ],
                axis=0,
            )
        else:
            values = _source_amplitudes_from_topography(
                forward_model,
                np.sum(topographies, axis=0),
                lambda2=config.lambda2,
            )
    else:
        leadfield = _referenced_leadfield(
            forward_model.leadfield,
            apply_average_reference=config.apply_average_reference,
        )
        inverse = _minimum_norm_inverse_matrix(leadfield, lambda2=config.lambda2)
        if config.harmonic_strategy == HARMONIC_STRATEGY_SUM_SOURCE_MAGNITUDES:
            values = np.sum(np.abs(topographies @ inverse.T), axis=0)
        else:
            summed_topography = np.sum(topographies, axis=0)
            values = np.abs(inverse @ summed_topography)
    if not np.all(np.isfinite(values)):
        raise ValueError("L2-MNE produced non-finite source values.")
    return values.astype(float)


def build_l2_mne_cortical_surface_payload(
    *,
    forward_model: L2MNECorticalForwardModel,
    condition: L2MNEFPVSCondition,
    config: L2MNEProducerConfig,
) -> dict[str, Any]:
    """Build one validator-ready prepared payload mapping for a condition."""
    values = compute_l2_mne_source_values(forward_model=forward_model, condition=condition, config=config)
    payload = {
        "format": PREPARED_SOURCE_PAYLOAD_FORMAT,
        "label": f"{condition.label} L2-MNE cortical source map",
        "kind": SOURCE_KIND_SURFACE_MESH,
        "coordinate_space": forward_model.coordinate_space,
        "source_model": config.method_id,
        "value_label": config.value_label,
        "points": _array_to_json_rows(forward_model.source_points),
        "values": _array_to_json_values(values),
        "faces": _array_to_json_rows(forward_model.faces),
        "metadata": _payload_metadata(forward_model=forward_model, condition=condition, config=config),
    }
    validate_prepared_source_payload_mapping(payload)
    return payload


def write_l2_mne_cortical_surface_payloads(
    *,
    forward_model: L2MNECorticalForwardModel,
    conditions: Sequence[L2MNEFPVSCondition],
    config: L2MNEProducerConfig,
    output_dir: str | Path,
    manifest_name: str = "l2_mne_cortical_surface_beta_manifest.json",
) -> SourceProducerRunResult:
    """Write validated L2-MNE cortical-surface payloads and a manifest."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    condition_list = tuple(conditions)
    if not condition_list:
        raise ValueError("L2-MNE producer requires at least one condition.")

    emitted: list[ProducedPayload] = []
    manifest_conditions: list[dict[str, Any]] = []
    used_file_names: set[str] = set()
    for condition in condition_list:
        payload = build_l2_mne_cortical_surface_payload(
            forward_model=forward_model,
            condition=condition,
            config=config,
        )
        file_name = _unique_payload_file_name(condition.condition_id, used_file_names)
        payload_path = output_path / file_name
        _write_json(payload_path, payload)
        validation = validate_prepared_source_payload_json(payload_path)
        emitted.append(
            ProducedPayload(
                condition_id=condition.condition_id,
                label=condition.label,
                payload_path=payload_path,
                validation=validation,
            )
        )
        manifest_conditions.append(
            {
                "id": condition.condition_id,
                "label": condition.label,
                "file": file_name,
                "metadata": {
                    "producer_method": config.method_id,
                    "selected_harmonics_hz": list(config.selected_harmonics_hz),
                    "harmonic_strategy": config.harmonic_strategy,
                },
            }
        )

    manifest = {
        "format": PREPARED_SOURCE_MANIFEST_FORMAT,
        "label": "L2-MNE cortical-surface beta source maps",
        "conditions": manifest_conditions,
    }
    manifest_path = output_path / manifest_name
    _write_json(manifest_path, manifest)
    manifest_validation = validate_prepared_source_manifest_json(manifest_path, require_payload_files=True)
    logger.info(
        "l2_mne_cortical_surface_payloads_written",
        extra={"output_dir": str(output_path), "condition_count": len(emitted)},
    )
    return SourceProducerRunResult(
        method_id=config.method_id,
        output_dir=output_path,
        manifest_path=manifest_path,
        payloads=tuple(emitted),
        manifest_validation=manifest_validation,
    )


def make_l2_mne_cortical_surface_beta_fixture() -> tuple[
    L2MNECorticalForwardModel,
    tuple[L2MNEFPVSCondition, ...],
    L2MNEProducerConfig,
]:
    """Return a deterministic source-ready fixture for Phase 6A validation."""
    channel_names = tuple(DEFAULT_ELECTRODE_NAMES_64)
    source_points, faces, source_regions = _fixture_source_space()
    sensor_positions = _fixture_sensor_positions(channel_names)
    leadfield = _fixture_leadfield(sensor_positions=sensor_positions, source_points=source_points)
    selected_harmonics = (1.2, 2.4, 3.6)
    config = L2MNEProducerConfig(
        selected_harmonics_hz=selected_harmonics,
        metadata={
            "fixture": True,
            "calculation_status": "beta source-ready deterministic fixture",
            "project_integration": "none",
        },
    )
    forward_model = L2MNECorticalForwardModel(
        channel_names=channel_names,
        source_points=source_points,
        leadfield=leadfield,
        faces=faces,
        metadata={
            "fixture": True,
            "source_regions": source_regions,
            "forward_model_status": "deterministic source-ready fixture, not subject MRI",
        },
    )
    conditions = (
        _fixture_condition(
            condition_id="occipital_oddball_beta",
            label="Occipital oddball beta fixture",
            selected_harmonics=selected_harmonics,
            leadfield=leadfield,
            source_weights=_fixture_true_source_weights("occipital", len(source_points)),
        ),
        _fixture_condition(
            condition_id="frontal_oddball_beta",
            label="Frontal oddball beta fixture",
            selected_harmonics=selected_harmonics,
            leadfield=leadfield,
            source_weights=_fixture_true_source_weights("frontal", len(source_points)),
        ),
    )
    return forward_model, conditions, config


def write_l2_mne_cortical_surface_fixture(output_dir: str | Path) -> SourceProducerRunResult:
    """Write the deterministic beta L2-MNE cortical-surface fixture payload set."""
    forward_model, conditions, config = make_l2_mne_cortical_surface_beta_fixture()
    return write_l2_mne_cortical_surface_payloads(
        forward_model=forward_model,
        conditions=conditions,
        config=config,
        output_dir=output_dir,
    )


def _minimum_norm_inverse_matrix(leadfield: np.ndarray, *, lambda2: float) -> np.ndarray:
    gram = leadfield @ leadfield.T
    scale = float(np.trace(gram) / max(gram.shape[0], 1))
    if not np.isfinite(scale) or scale <= 0.0:
        scale = 1.0
    regularized = gram + float(lambda2) * scale * np.eye(gram.shape[0], dtype=float)
    return leadfield.T @ np.linalg.pinv(regularized)


def _source_amplitudes_from_topography(
    forward_model: L2MNECorticalForwardModel,
    topography: Sequence[float],
    *,
    lambda2: float,
) -> np.ndarray:
    source_estimator = forward_model.source_estimator
    topography_array = np.asarray(topography, dtype=float).reshape(-1)
    if source_estimator is None:
        inverse = _minimum_norm_inverse_matrix(forward_model.leadfield, lambda2=lambda2)
        values = np.abs(inverse @ topography_array)
    else:
        values = np.asarray(source_estimator(topography_array, lambda2=float(lambda2)), dtype=float).reshape(-1)
    expected = len(forward_model.source_points)
    if len(values) != expected:
        raise ValueError(f"L2-MNE source estimator returned {len(values)} values; {expected} expected.")
    if not np.all(np.isfinite(values)):
        raise ValueError("L2-MNE source estimator returned non-finite source values.")
    return values.astype(float)


def _selected_condition_topographies(
    condition: L2MNEFPVSCondition,
    *,
    selected_harmonics: tuple[float, ...],
    n_channels: int,
    apply_average_reference: bool,
) -> np.ndarray:
    lookup = condition.harmonic_topographies
    rows: list[np.ndarray] = []
    for harmonic in selected_harmonics:
        key = _round_harmonic(harmonic)
        if key not in lookup:
            raise ValueError(f"{condition.label} is missing selected harmonic {key:g} Hz.")
        topography = np.asarray(lookup[key], dtype=float).reshape(-1)
        if len(topography) != n_channels:
            raise ValueError(
                f"{condition.label} harmonic {key:g} Hz has {len(topography)} channels; {n_channels} expected."
            )
        if apply_average_reference:
            topography = topography - float(np.mean(topography))
        rows.append(topography.astype(float))
    return np.vstack(rows)


def _referenced_leadfield(leadfield: np.ndarray, *, apply_average_reference: bool) -> np.ndarray:
    if not apply_average_reference:
        return leadfield.astype(float)
    return (leadfield - np.mean(leadfield, axis=0, keepdims=True)).astype(float)


def _payload_metadata(
    *,
    forward_model: L2MNECorticalForwardModel,
    condition: L2MNEFPVSCondition,
    config: L2MNEProducerConfig,
) -> dict[str, Any]:
    metadata = {
        "beta": True,
        "producer_method": config.method_id,
        "inverse_method": "L2 minimum-norm estimate",
        "source_space": "cortical_surface",
        "template_subject": config.template_subject,
        "montage_name": config.montage_name,
        "coordinate_space": forward_model.coordinate_space,
        "forward_model_label": forward_model.label,
        "harmonic_policy_id": config.harmonic_policy_id,
        "selected_harmonics_hz": list(config.selected_harmonics_hz),
        "harmonic_strategy": config.harmonic_strategy,
        "lambda2": float(config.lambda2),
        "inverse_backend": str(forward_model.metadata.get("inverse_backend", "manual_ridge")),
        "orientation_constraint": str(forward_model.metadata.get("orientation_constraint", "fixed")),
        "loose_orientation": forward_model.metadata.get("loose_orientation"),
        "fixed_orientation": forward_model.metadata.get("fixed_orientation", True),
        "depth_weighting": str(forward_model.metadata.get("depth_weighting", "not_applicable")),
        "noise_normalization": str(forward_model.metadata.get("noise_normalization", "none")),
        "regularization": str(
            forward_model.metadata.get("regularization", "lambda2 scaled by leadfield sensor-space trace")
        ),
        "average_reference_applied": bool(config.apply_average_reference),
        "sensor_value_unit": condition.sensor_value_unit,
        "source_value_unit": "arbitrary units",
        "source_value_unit_note": (
            "Template-scaled L2-MNE source amplitude proportional to the input sensor topography; "
            "not calibrated current density or dipole moment."
        ),
        "channel_count": len(forward_model.channel_names),
        "source_count": int(len(forward_model.source_points)),
        "channel_names": list(forward_model.channel_names),
        "deep_source_claim": "none; beta L2-MNE payload is cortical surface only",
        "project_integration": "none",
        "renderer_dependency": "none",
    }
    metadata.update(_json_safe_metadata(forward_model.metadata, prefix="forward_model"))
    metadata.update(_json_safe_metadata(config.metadata, prefix="config"))
    metadata.update(_json_safe_metadata(condition.metadata, prefix="condition"))
    return metadata


def _fixture_condition(
    *,
    condition_id: str,
    label: str,
    selected_harmonics: tuple[float, ...],
    leadfield: np.ndarray,
    source_weights: np.ndarray,
) -> L2MNEFPVSCondition:
    harmonic_scales = {selected_harmonics[0]: 1.0, selected_harmonics[1]: 0.68, selected_harmonics[2]: 0.42}
    topographies = {
        harmonic: leadfield @ (source_weights * scale)
        for harmonic, scale in harmonic_scales.items()
    }
    return L2MNEFPVSCondition(
        condition_id=condition_id,
        label=label,
        harmonic_topographies=topographies,
        metadata={
            "fixture": True,
            "source_ready_input": True,
            "synthetic_condition": condition_id,
        },
    )


def _fixture_true_source_weights(region: str, source_count: int) -> np.ndarray:
    weights = np.full(source_count, 0.03, dtype=float)
    if region == "occipital":
        weights[:6] = np.asarray([0.40, 0.85, 1.00, 0.92, 0.74, 0.36], dtype=float)
    elif region == "frontal":
        weights[6:] = np.asarray([0.34, 0.72, 0.95, 1.00, 0.82, 0.42], dtype=float)
    else:
        raise ValueError(f"Unknown fixture source region: {region!r}.")
    return weights


def _fixture_source_space() -> tuple[np.ndarray, np.ndarray, list[str]]:
    points = np.asarray(
        [
            [-48.0, -86.0, 9.0],
            [-30.0, -96.0, 20.0],
            [-10.0, -86.0, 12.0],
            [10.0, -86.0, 12.0],
            [30.0, -96.0, 20.0],
            [48.0, -86.0, 9.0],
            [-48.0, 56.0, 16.0],
            [-30.0, 68.0, 32.0],
            [-10.0, 58.0, 22.0],
            [10.0, 58.0, 22.0],
            [30.0, 68.0, 32.0],
            [48.0, 56.0, 16.0],
        ],
        dtype=float,
    )
    faces = np.asarray(
        [
            [0, 1, 2],
            [1, 3, 2],
            [1, 4, 3],
            [4, 5, 3],
            [6, 7, 8],
            [7, 9, 8],
            [7, 10, 9],
            [10, 11, 9],
        ],
        dtype=np.int64,
    )
    regions = ["occipital"] * 6 + ["frontal"] * 6
    return points, faces, regions


def _fixture_sensor_positions(channel_names: Sequence[str]) -> np.ndarray:
    return np.vstack([_fixture_sensor_position(name) for name in channel_names]).astype(float)


def _fixture_sensor_position(channel_name: str) -> np.ndarray:
    name = channel_name.strip()
    name_upper = name.upper()
    prefix = re.sub(r"\d+$", "", name_upper)
    y_by_prefix = {
        "FP": 82.0,
        "AF": 65.0,
        "F": 48.0,
        "FT": 24.0,
        "FC": 24.0,
        "C": 0.0,
        "T": 0.0,
        "TP": -30.0,
        "CP": -32.0,
        "P": -55.0,
        "PO": -75.0,
        "O": -90.0,
        "I": -102.0,
    }
    z_by_prefix = {
        "FP": 24.0,
        "AF": 44.0,
        "F": 58.0,
        "FT": 44.0,
        "FC": 62.0,
        "C": 70.0,
        "T": 34.0,
        "TP": 36.0,
        "CP": 58.0,
        "P": 55.0,
        "PO": 36.0,
        "O": 22.0,
        "I": 8.0,
    }
    x = 0.0
    digits = re.findall(r"\d+", name_upper)
    if digits:
        number = int(digits[-1])
        lateral = min(72.0, 10.0 + 8.0 * number)
        x = -lateral if number % 2 else lateral
    elif name_upper.endswith("Z"):
        x = 0.0
    compact_prefix = prefix.rstrip("Z")
    y = y_by_prefix.get(compact_prefix, 0.0)
    z = z_by_prefix.get(compact_prefix, 50.0)
    return np.asarray([x, y, z], dtype=float)


def _fixture_leadfield(*, sensor_positions: np.ndarray, source_points: np.ndarray) -> np.ndarray:
    deltas = sensor_positions[:, np.newaxis, :] - source_points[np.newaxis, :, :]
    scaled = deltas / np.asarray([70.0, 95.0, 70.0], dtype=float)
    distance = np.sum(scaled * scaled, axis=2)
    field = np.exp(-distance)
    lateral_term = 1.0 + 0.10 * np.sign(sensor_positions[:, np.newaxis, 0]) * np.sign(source_points[np.newaxis, :, 0])
    posterior_term = 1.0 + 0.08 * np.sign(-sensor_positions[:, np.newaxis, 1]) * np.sign(-source_points[np.newaxis, :, 1])
    return (field * lateral_term * posterior_term).astype(float)


def _validate_harmonics(values: Sequence[float]) -> tuple[float, ...]:
    harmonics = tuple(_round_harmonic(float(value)) for value in values)
    if not harmonics:
        raise ValueError("L2-MNE producer requires selected harmonics.")
    if len(set(harmonics)) != len(harmonics):
        raise ValueError("L2-MNE selected harmonics must be unique.")
    if any(not np.isfinite(value) or value <= 0.0 for value in harmonics):
        raise ValueError("L2-MNE selected harmonics must be positive finite values.")
    return harmonics


def _round_harmonic(value: float) -> float:
    return round(float(value), 4)


def _validate_channel_name(value: str) -> str:
    return _validate_label(value, "channel_name")


def _validate_label(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"L2-MNE {field_name} must be a non-empty string.")
    return value.strip()


def _validate_points(values: np.ndarray, *, field_name: str) -> np.ndarray:
    points = np.asarray(values, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) == 0:
        raise ValueError(f"L2-MNE {field_name} must be a non-empty N x 3 array.")
    if not np.all(np.isfinite(points)):
        raise ValueError(f"L2-MNE {field_name} must contain finite values.")
    return points.astype(float)


def _validate_matrix(values: np.ndarray, *, field_name: str) -> np.ndarray:
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2 or 0 in matrix.shape:
        raise ValueError(f"L2-MNE {field_name} must be a non-empty 2D array.")
    if not np.all(np.isfinite(matrix)):
        raise ValueError(f"L2-MNE {field_name} must contain finite values.")
    return matrix.astype(float)


def _validate_triangle_faces(values: np.ndarray, *, point_count: int) -> np.ndarray:
    faces = np.asarray(values, dtype=np.int64)
    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) == 0:
        raise ValueError("L2-MNE cortical surface faces must be non-empty triangle rows.")
    if not np.all(faces >= 0) or int(np.max(faces)) >= point_count:
        raise ValueError("L2-MNE cortical surface faces must refer to existing source points.")
    return faces


def _array_to_json_rows(values: np.ndarray) -> list[list[float]] | list[list[int]]:
    rows: list[list[float]] | list[list[int]]
    if np.issubdtype(values.dtype, np.integer):
        rows = [[int(item) for item in row] for row in values]
    else:
        rows = [[float(item) for item in row] for row in values]
    return rows


def _array_to_json_values(values: np.ndarray) -> list[float]:
    return [float(item) for item in np.asarray(values, dtype=float).reshape(-1)]


def _json_safe_metadata(metadata: Mapping[str, Any], *, prefix: str) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in dict(metadata).items():
        safe_key = f"{prefix}_{_slug(str(key))}"
        safe[safe_key] = _json_safe_value(value)
    return safe


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_safe_value(item) for item in value]
    return value


def _unique_payload_file_name(condition_id: str, used: set[str]) -> str:
    base = _slug(condition_id)
    candidate = f"{base}_l2_mne_cortical_surface_beta.json"
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}_l2_mne_cortical_surface_beta.json"
        suffix += 1
    used.add(candidate)
    return candidate


def _slug(value: str) -> str:
    lowered = value.strip().lower()
    chars = [char if char.isalnum() else "_" for char in lowered]
    slug = "_".join(part for part in "".join(chars).split("_") if part)
    return slug or "condition"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    temp_path.replace(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write deterministic beta L2-MNE cortical-surface fixture payloads."
    )
    parser.add_argument("--output", required=True, help="Output folder for payload JSON and manifest files.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_l2_mne_cortical_surface_fixture(args.output)
    logger.info("l2_mne_cortical_surface_fixture_written", extra={"manifest_path": str(result.manifest_path)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
