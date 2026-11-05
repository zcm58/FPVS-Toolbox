"""Add descriptive spectral-amplitude outputs without changing source inverses."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

import numpy as np

from Main_App.io.atomic_write import atomic_write
from Tools.LORETA_Visualizer.prepared_payload_validator import (
    validate_prepared_source_manifest_json,
    validate_prepared_source_payload_json,
)
from .contracts import ProducedPayload, SourceProducerRunResult
from .source_validity import complete_valid_source_support, source_validity_metadata, source_values_to_json

SOURCE_METRIC_Z_SCORE = "z_score"
SOURCE_METRIC_BASELINE_AMPLITUDE = "baseline_corrected_amplitude"
SOURCE_COMPARISON_VERSION = 1
SOURCE_AMPLITUDE_UNIT = "source spectral amplitude"


def source_document_sha256(document: Mapping[str, Any]) -> str:
    """Bind prepared documents independently of JSON whitespace/escaping."""
    content = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def descriptive_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Remove inherited inferential results before publishing descriptive values."""
    result = deepcopy(dict(metadata))
    for key in tuple(result):
        if key.startswith("cluster_") or (key.startswith("source_inference_") and key != "source_inference_selection_basis"):
            del result[key]
    result.update({
        "descriptive_only": True,
        "source_value_polarity": "signed",
        "cluster_mask": "not_applicable",
        "cluster_mask_status": "not_applicable",
        "source_inference_status": "descriptive_only",
        "source_inference_confirmatory": False,
        "source_inference_reasons": ["Descriptive values; no significance test was performed for this metric or contrast."],
    })
    return result


def summarize_source_matrix(
    matrix: np.ndarray, support: np.ndarray, *, aggregation: str, trim_fraction: float | None,
) -> np.ndarray:
    """Summarize fixed participant support, preserving signed and missing values."""
    if aggregation not in {"mean", "median", "trimmed_mean"}:
        raise ValueError("Source comparison requires mean, median or trimmed_mean summaries.")
    if matrix.ndim != 2 or not len(matrix) or matrix.shape[1] != len(support) or not np.any(support):
        raise ValueError("No common valid source support remains for this comparison.")
    selected = matrix[:, support]
    if not np.all(np.isfinite(selected)):
        raise ValueError("Source summary contains non-finite values on declared valid support.")
    if aggregation == "median":
        summary = np.median(selected, axis=0)
    elif aggregation == "trimmed_mean":
        if trim_fraction is None or not np.isfinite(trim_fraction) or not 0 <= trim_fraction < .5:
            raise ValueError("Trimmed source summaries require a fraction between zero and one half.")
        trim = int(np.floor(len(selected) * trim_fraction))
        ordered = np.sort(selected, axis=0)
        summary = np.mean(ordered[trim:len(ordered) - trim], axis=0)
    else:
        summary = np.mean(selected, axis=0)
    output = np.full(matrix.shape[1], np.nan)
    output[support] = summary
    return output


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    with atomic_write(path) as stream:
        stream.write(json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def source_comparison_signature(payload: Mapping[str, Any], frequency_metadata: Mapping[str, Any]) -> str:
    """Bind exact source geometry, inverse and spectral settings, excluding cohorts."""
    metadata = payload["metadata"]
    keys = (
        "base_producer_method", "inverse_method", "source_space", "template_subject",
        "montage_name", "selected_harmonics_hz", "lambda2", "orientation_constraint",
        "loose_orientation", "fixed_orientation", "depth_weighting", "noise_normalization",
        "average_reference_applied", "channel_names", "config_source_psd_method_metadata",
        "source_vertex_ids", "source_hemispheres", "source_indices",
    )
    identity = {
        "kind": payload["kind"], "coordinate_space": payload["coordinate_space"],
        "points": payload["points"],
        "faces": payload.get("faces"), "frequency": dict(frequency_metadata),
        "numerical_metadata": {key: value for key, value in metadata.items()
                               if key in keys or key.startswith("forward_model_")},
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def add_source_amplitude_outputs(
    producer_result: SourceProducerRunResult, *, participant_sidecar_path: Path,
    conditions: Sequence[Any], frequency_metadata: Mapping[str, Any],
) -> SourceProducerRunResult:
    """Add metric entries and participant diagnostics inside the staged bundle.

    Call only for signed-time-domain source-PSD exports, before report/publication.
    Existing Z values, method identities, numerical caches and masks are retained.
    """
    manifest = json.loads(producer_result.manifest_path.read_text(encoding="utf-8"))
    sidecar = json.loads(participant_sidecar_path.read_text(encoding="utf-8"))
    data_id = uuid4().hex
    conditions_by_id = {condition.condition_id: condition for condition in conditions}
    if len(conditions_by_id) != len(conditions):
        raise ValueError("Duplicate source condition identities prevent amplitude export.")
    sidecar_rows = {row["condition_id"]: row for row in sidecar["conditions"]}
    for condition_id, condition in conditions_by_id.items():
        cell = sidecar_rows[condition_id]
        cell["source_cell_id"] = condition_id
        cell["metadata"] = {**cell.get("metadata", {}), **deepcopy(dict(condition.metadata))}
        cell["metadata"]["source_spectral_settings"] = deepcopy(dict(frequency_metadata))
        source_rows = {row.participant_id: row for row in condition.participant_values}
        for participant in cell["participants"]:
            row = source_rows[participant["participant_id"]]
            participant.update({
                "target_source_values": np.asarray(row.target_source_values, dtype=float).tolist(),
                "noise_mean_values": np.asarray(row.noise_mean_values, dtype=float).tolist(),
                "noise_std_values": np.asarray(row.noise_std_values, dtype=float).tolist(),
            })
    sidecar.setdefault("metadata", {}).update({
        "source_comparison_version": SOURCE_COMPARISON_VERSION,
        "source_metrics": [SOURCE_METRIC_Z_SCORE, SOURCE_METRIC_BASELINE_AMPLITUDE],
        "source_amplitude_diagnostics": {
            "fields": ["target_source_values", "noise_mean_values", "noise_std_values"],
            "source_value_unit": SOURCE_AMPLITUDE_UNIT,
            "baseline_corrected_amplitude_formula": "target_source_values - noise_mean_values",
            "unit_note": "Method/window-dependent source spectral amplitude; not calibrated current or scalp microvolts.",
        },
        "source_spectral_settings": deepcopy(dict(frequency_metadata)),
        "source_comparison_data_id": data_id,
    })
    emitted = []
    added_entries = []
    payloads_by_id = {item.condition_id: item for item in producer_result.payloads}
    for entry in manifest["conditions"]:
        existing = payloads_by_id[entry["id"]]
        payload = json.loads(existing.payload_path.read_text(encoding="utf-8"))
        aggregation = payload["metadata"]["participant_zscore_aggregation"]
        matches = [key for key in conditions_by_id if entry["id"] == f"{key}_{aggregation}"]
        if len(matches) != 1:
            raise ValueError("Source payload identity does not match its participant condition.")
        condition_id = matches[0]
        condition = conditions_by_id[condition_id]
        signature = source_comparison_signature(payload, frequency_metadata)
        shared_metadata = {
            "source_cell_id": condition_id,
            "source_cell_label": condition.label,
            "source_comparison_version": SOURCE_COMPARISON_VERSION,
            "source_comparison_data_id": data_id,
            "source_comparison_signature": signature,
            "source_spectral_settings": deepcopy(dict(frequency_metadata)),
            "participant_sidecar_file": participant_sidecar_path.name,
            "source_metric": SOURCE_METRIC_Z_SCORE,
            "source_metric_label": "Z-score",
            "descriptive_comparison_available": True,
            "canonical_condition_id": condition.metadata["canonical_condition_id"],
            "group_id": condition.metadata.get("group_id"),
        }
        payload["metadata"].update(shared_metadata)
        entry.setdefault("metadata", {}).update(shared_metadata)
        sidecar_rows[condition_id]["metadata"]["source_comparison_signature"] = signature
        _write_json(existing.payload_path, payload)
        entry["metadata"]["source_payload_sha256"] = source_document_sha256(payload)
        emitted.append(replace(existing, validation=validate_prepared_source_payload_json(existing.payload_path)))

        _matrix, support = complete_valid_source_support(condition.participant_values)
        amplitudes = np.vstack([
            np.asarray(row.target_source_values) - np.asarray(row.noise_mean_values)
            for row in condition.participant_values
        ])
        values = summarize_source_matrix(
            amplitudes, support, aggregation=aggregation,
            trim_fraction=payload["metadata"].get("participant_zscore_trim_fraction"),
        )
        amplitude = deepcopy(payload)
        amplitude["values"] = source_values_to_json(values, support)
        amplitude["label"] = f"{condition.label} {aggregation.replace('_', ' ')} baseline-corrected amplitude"
        amplitude["value_label"] = "Baseline-corrected source amplitude"
        amplitude["metadata"] = descriptive_metadata(amplitude["metadata"])
        amplitude["metadata"].update({
            "source_metric": SOURCE_METRIC_BASELINE_AMPLITUDE,
            "source_metric_label": "Baseline-corrected amplitude",
            "source_value_unit": SOURCE_AMPLITUDE_UNIT,
            "source_value_unit_note": "Method/window-dependent source spectral amplitude; not calibrated current or scalp microvolts.",
            "value_label": amplitude["value_label"],
            "participant_zscore_aggregation_label": aggregation.replace("_", " ").capitalize(),
            "source_metric_formula": "summed target source amplitude minus neighboring-bin mean",
            "source_validity": source_validity_metadata(support, scope="group_complete_case", participant_count=len(amplitudes)),
        })
        amplitude_id = entry["id"] + "__baseline_corrected_amplitude"
        amplitude_path = existing.payload_path.with_name(existing.payload_path.stem + "__baseline_corrected_amplitude.json")
        _write_json(amplitude_path, amplitude)
        emitted.append(ProducedPayload(
            condition_id=amplitude_id, label=amplitude["label"], payload_path=amplitude_path,
            validation=validate_prepared_source_payload_json(amplitude_path),
        ))
        amplitude_entry = deepcopy(entry)
        amplitude_entry.update({"id": amplitude_id, "label": amplitude["label"], "file": amplitude_path.name})
        amplitude_entry["metadata"] = descriptive_metadata(amplitude_entry["metadata"])
        amplitude_entry["metadata"].update({key: amplitude["metadata"][key] for key in (
            "source_metric", "source_metric_label", "source_value_unit", "value_label", "source_validity",
        )})
        amplitude_entry["metadata"]["source_payload_sha256"] = source_document_sha256(amplitude)
        added_entries.append(amplitude_entry)
    manifest["conditions"].extend(added_entries)
    manifest.setdefault("metadata", {}).update({
        "source_comparison_version": SOURCE_COMPARISON_VERSION,
        "source_metrics": [SOURCE_METRIC_Z_SCORE, SOURCE_METRIC_BASELINE_AMPLITUDE],
        "participant_sidecar_file": participant_sidecar_path.name,
        "source_comparison_data_id": data_id,
        "source_comparison_hash_encoding": "canonical_json_v1",
    })
    _write_json(participant_sidecar_path, sidecar)
    manifest["metadata"]["participant_sidecar_sha256"] = source_document_sha256(sidecar)
    _write_json(producer_result.manifest_path, manifest)
    return replace(
        producer_result, payloads=tuple(emitted),
        manifest_validation=validate_prepared_source_manifest_json(producer_result.manifest_path, require_payload_files=True),
    )
