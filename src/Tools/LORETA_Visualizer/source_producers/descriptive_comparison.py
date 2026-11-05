"""Prepare descriptive A/B/A−B maps from retained participant measurements."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from Main_App.io.safe_file import regular_file_info
from Tools.LORETA_Visualizer.prepared_payload_validator import validate_prepared_source_payload_mapping
from Tools.LORETA_Visualizer.source_validity_contract import declared_source_validity
from .source_metrics import (
    SOURCE_COMPARISON_VERSION, SOURCE_METRIC_BASELINE_AMPLITUDE, SOURCE_METRIC_Z_SCORE,
    descriptive_metadata, source_comparison_signature, source_document_sha256, summarize_source_matrix,
)
from .source_validity import source_validity_metadata, source_values_to_json
from .project_source_publication import SOURCE_BUNDLE_RECEIPT, validate_source_bundle


class SourceComparisonUnavailable(ValueError):
    """Prepared inputs cannot provide a coherent descriptive comparison."""


@dataclass(frozen=True)
class DescriptiveSourceComparison:
    left_payload: dict[str, Any]
    right_payload: dict[str, Any]
    difference_payload: dict[str, Any]
    metadata: dict[str, Any]


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        expected = regular_file_info(path)
        if expected is None or expected.st_size > 256 * 1024 * 1024:
            raise SourceComparisonUnavailable("Source comparison input is missing or exceeds the read limit.")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
                raise SourceComparisonUnavailable("Source bundle changed while opening; reload the maps.")
            content = stream.read(256 * 1024 * 1024 + 1)
        if len(content) > 256 * 1024 * 1024:
            raise SourceComparisonUnavailable("Source comparison input exceeds the read limit.")
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value, content
    except (OSError, ValueError, RecursionError) as exc:
        raise SourceComparisonUnavailable(f"Cannot read source comparison data: {path.name}. {exc}") from exc


def _local_file(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise SourceComparisonUnavailable("Source comparison files must stay inside their source bundle.")
    candidate = root / value
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        raise SourceComparisonUnavailable("Source comparison files must stay inside their source bundle.")
    # Do not resolve away a linked final component before validating it.
    regular_file_info(candidate)
    return candidate


def _one(rows: object, key: str, value: str, description: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise SourceComparisonUnavailable(f"Missing {description}; rebuild source maps.")
    matches = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(matches) != 1:
        raise SourceComparisonUnavailable(f"Missing or ambiguous {description}; rebuild source maps.")
    return matches[0]


def _metadata(document: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = document.get("metadata")
    if not isinstance(metadata, Mapping):
        raise SourceComparisonUnavailable("Comparison metadata is unavailable; rebuild source maps.")
    return metadata


def _cell_identity(cell: Mapping[str, Any]) -> tuple[object, str]:
    metadata = _metadata(cell)
    condition = metadata.get("canonical_condition_id")
    if not isinstance(condition, str) or not condition:
        raise SourceComparisonUnavailable("Canonical condition identity is unavailable; rebuild source maps.")
    group = metadata.get("group_id")
    if group is not None and (not isinstance(group, str) or not group):
        raise SourceComparisonUnavailable("Canonical group identity is invalid.")
    return group, condition


def _participants(cell: Mapping[str, Any], *, metric: str, source_count: int) -> dict[str, tuple[str, np.ndarray, np.ndarray]]:
    participants = cell.get("participants")
    if not isinstance(participants, list) or not participants:
        raise SourceComparisonUnavailable("Participant maps are unavailable; rebuild source maps.")
    rows = {}
    for row in participants:
        if not isinstance(row, Mapping) or not isinstance(row.get("participant_id"), str) or not row["participant_id"].strip():
            raise SourceComparisonUnavailable("Participant source identities are invalid.")
        identity = row["participant_id"].strip()
        key = identity.casefold()
        if key in rows:
            raise SourceComparisonUnavailable("Duplicate participant identities prevent comparison.")
        values = np.asarray(row.get("values"), dtype=float)
        if values.ndim != 1 or len(values) != source_count:
            raise SourceComparisonUnavailable("Participant source arrays do not match the source geometry.")
        support = declared_source_validity(values, row)
        if metric == SOURCE_METRIC_BASELINE_AMPLITUDE:
            target = np.asarray(row.get("target_source_values"), dtype=float)
            background = np.asarray(row.get("noise_mean_values"), dtype=float)
            if target.shape != values.shape or background.shape != values.shape or not np.all(np.isfinite(target)) or not np.all(np.isfinite(background)):
                raise SourceComparisonUnavailable("Participant amplitude diagnostics are unavailable; rebuild source maps.")
            values = target - background
            values[~support] = np.nan
        rows[key] = (identity, values, support)
    return rows


def _prepared_panel(
    template: Mapping[str, Any], values: np.ndarray, support: np.ndarray, *, label: str,
    participant_ids: list[str], comparison: Mapping[str, Any], role: str,
) -> dict[str, Any]:
    document = deepcopy(dict(template))
    document["label"] = label
    document["values"] = source_values_to_json(values, support)
    metadata = descriptive_metadata(_metadata(document))
    metadata.update({
        "participant_ids": participant_ids,
        "participant_count": len(participant_ids),
        "source_validity": source_validity_metadata(support, scope="group_complete_case", participant_count=len(participant_ids)),
        "descriptive_comparison": deepcopy(dict(comparison)),
        "source_comparison_role": role,
    })
    # The constituent rows remain traceable, but their original masks/counts do not.
    for key in ("condition_participant_ids", "config_included_participants"):
        if key in metadata:
            metadata[key] = participant_ids
    document["metadata"] = metadata
    if role == "difference":
        document["value_label"] = "A − B: " + str(template["value_label"])
        metadata["value_label"] = document["value_label"]
    validate_prepared_source_payload_mapping(document)
    return document


def build_descriptive_source_comparison(
    manifest_path: str | Path, left_entry_id: str, right_entry_id: str, *, comparison_kind: str = "groups",
) -> DescriptiveSourceComparison:
    """Prepare signed, unmasked maps in a worker; perform no inferential test.

    Conditions use complete participant pairs and summarize within-person A−B.
    Groups use separate cohorts and subtract their matching summary statistics.
    All panels retain identical complete-valid source support and full geometry.
    """
    if comparison_kind not in {"groups", "conditions"}:
        raise SourceComparisonUnavailable("Choose a groups or conditions comparison.")
    if left_entry_id == right_entry_id:
        raise SourceComparisonUnavailable("Choose two different source maps to compare.")
    manifest_path = Path(manifest_path).resolve()
    root = manifest_path.parent
    if (root / SOURCE_BUNDLE_RECEIPT).exists():
        validate_source_bundle(manifest_path)
    manifest, manifest_bytes = _read_json(manifest_path)
    if _metadata(manifest).get("source_comparison_version") != SOURCE_COMPARISON_VERSION:
        raise SourceComparisonUnavailable("These maps lack participant comparison data. Rebuild source maps from the saved FIFs.")
    sidecar_path = _local_file(root, _metadata(manifest).get("participant_sidecar_file"))
    sidecar, sidecar_bytes = _read_json(sidecar_path)
    if _metadata(sidecar).get("source_comparison_version") != SOURCE_COMPARISON_VERSION:
        raise SourceComparisonUnavailable("Participant comparison data are unavailable; rebuild source maps.")
    data_id = _metadata(manifest).get("source_comparison_data_id")
    if (not isinstance(data_id, str) or not data_id
            or _metadata(sidecar).get("source_comparison_data_id") != data_id
            or _metadata(manifest).get("source_comparison_hash_encoding") != "canonical_json_v1"
            or source_document_sha256(sidecar) != _metadata(manifest).get("participant_sidecar_sha256")):
        raise SourceComparisonUnavailable("Participant data do not match this source bundle; rebuild source maps.")
    entries, documents, cells = [], [], []
    read_files = [(manifest_path, manifest_bytes), (sidecar_path, sidecar_bytes)]
    for entry_id in (left_entry_id, right_entry_id):
        entry = _one(manifest.get("conditions"), "id", entry_id, "source-map entry")
        path = _local_file(root, entry.get("file"))
        document, content = _read_json(path)
        validate_prepared_source_payload_mapping(document)
        read_files.append((path, content))
        entry_metadata, metadata = _metadata(entry), _metadata(document)
        if (entry_metadata.get("source_comparison_data_id") != data_id
                or metadata.get("source_comparison_data_id") != data_id
                or source_document_sha256(document) != entry_metadata.get("source_payload_sha256")):
            raise SourceComparisonUnavailable("Source payload does not match this source bundle; rebuild source maps.")
        for key in ("source_metric", "source_comparison_signature", "source_cell_id", "participant_zscore_aggregation"):
            if not metadata.get(key) or metadata.get(key) != entry_metadata.get(key):
                raise SourceComparisonUnavailable("Source entry and payload metadata disagree; rebuild source maps.")
        cell = _one(sidecar.get("conditions"), "source_cell_id", metadata["source_cell_id"], "participant condition")
        if _metadata(cell).get("source_comparison_signature") != metadata["source_comparison_signature"]:
            raise SourceComparisonUnavailable("Participant data and source model metadata disagree; rebuild source maps.")
        spectral_settings = metadata.get("source_spectral_settings")
        if (not isinstance(spectral_settings, Mapping)
                or spectral_settings != entry_metadata.get("source_spectral_settings")
                or spectral_settings != _metadata(cell).get("source_spectral_settings")
                or spectral_settings != _metadata(sidecar).get("source_spectral_settings")
                or source_comparison_signature(document, spectral_settings) != metadata["source_comparison_signature"]):
            raise SourceComparisonUnavailable("Source inverse, harmonic or spectral provenance changed; rebuild source maps.")
        for key in ("canonical_condition_id", "group_id"):
            if metadata.get(key) != _metadata(cell).get(key) or metadata.get(key) != entry_metadata.get(key):
                raise SourceComparisonUnavailable("Canonical source condition/group identities disagree; rebuild source maps.")
        entries.append(entry)
        documents.append(document)
        cells.append(cell)
    left, right = documents
    left_meta, right_meta = _metadata(left), _metadata(right)
    for key in ("source_metric", "source_comparison_signature", "participant_zscore_aggregation", "participant_zscore_trim_fraction", "source_value_unit", "source_vertex_ids", "source_hemispheres", "source_indices"):
        if left_meta.get(key) != right_meta.get(key):
            raise SourceComparisonUnavailable("Compare maps with identical metric, summary, inverse, harmonics and spectral settings.")
    for key in ("kind", "coordinate_space", "source_model", "points", "faces"):
        if left.get(key) != right.get(key):
            raise SourceComparisonUnavailable("Source geometry and source identities must match exactly.")
    metric = left_meta["source_metric"]
    if metric not in {SOURCE_METRIC_Z_SCORE, SOURCE_METRIC_BASELINE_AMPLITUDE}:
        raise SourceComparisonUnavailable("This source metric does not support descriptive comparisons.")
    left_group, left_condition = _cell_identity(cells[0])
    right_group, right_condition = _cell_identity(cells[1])
    if comparison_kind == "groups":
        if left_group is None or right_group is None or left_group == right_group or left_condition != right_condition:
            raise SourceComparisonUnavailable("Group comparison requires distinct canonical groups for the same condition.")
    elif left_group != right_group or left_condition == right_condition:
        raise SourceComparisonUnavailable("Condition comparison requires different conditions in the same canonical group.")
    source_count = len(left["values"])
    a_rows = _participants(cells[0], metric=metric, source_count=source_count)
    b_rows = _participants(cells[1], metric=metric, source_count=source_count)
    for metadata, rows in ((left_meta, a_rows), (right_meta, b_rows)):
        identities = metadata.get("participant_ids")
        if (not isinstance(identities, list) or any(not isinstance(value, str) for value in identities)
                or len(identities) != len(rows) or {value.strip().casefold() for value in identities} != set(rows)):
            raise SourceComparisonUnavailable("Source summary and participant cohort identities disagree.")
    if comparison_kind == "conditions":
        keys = sorted(a_rows.keys() & b_rows.keys())
        if not keys:
            raise SourceComparisonUnavailable("No participants have both selected conditions.")
        a_keys = b_keys = keys
    else:
        if a_rows.keys() & b_rows.keys():
            raise SourceComparisonUnavailable("Independent groups contain overlapping participant identities.")
        a_keys, b_keys = sorted(a_rows), sorted(b_rows)
    a = np.vstack([a_rows[key][1] for key in a_keys])
    b = np.vstack([b_rows[key][1] for key in b_keys])
    support = np.logical_and.reduce([a_rows[key][2] for key in a_keys] + [b_rows[key][2] for key in b_keys])
    summary_options = {"aggregation": left_meta["participant_zscore_aggregation"], "trim_fraction": left_meta.get("participant_zscore_trim_fraction")}
    a_summary = summarize_source_matrix(a, support, **summary_options)
    b_summary = summarize_source_matrix(b, support, **summary_options)
    difference = summarize_source_matrix(a - b, support, **summary_options) if comparison_kind == "conditions" else a_summary - b_summary
    a_ids, b_ids = [a_rows[key][0] for key in a_keys], [b_rows[key][0] for key in b_keys]
    metadata = {
        "version": SOURCE_COMPARISON_VERSION, "kind": comparison_kind, "direction": "A-B",
        "left_entry_id": left_entry_id, "right_entry_id": right_entry_id,
        "left_label": cells[0]["label"], "right_label": cells[1]["label"],
        "left_participant_ids": a_ids, "right_participant_ids": b_ids,
        "left_participant_count": len(a_ids), "right_participant_count": len(b_ids),
        "left_omitted_participant_ids": [a_rows[key][0] for key in sorted(a_rows.keys() - set(a_keys))],
        "right_omitted_participant_ids": [b_rows[key][0] for key in sorted(b_rows.keys() - set(b_keys))],
        "source_metric": metric, "summary": summary_options["aggregation"],
        "source_comparison_signature": left_meta["source_comparison_signature"],
        "difference_policy": "summarize_within_participant_differences" if comparison_kind == "conditions" else "difference_of_independent_group_summaries",
        "inference": "descriptive_only_no_significance_test",
    }
    a_panel = _prepared_panel(left, a_summary, support, label=f"A: {cells[0]['label']} (n = {len(a_ids)})", participant_ids=a_ids, comparison=metadata, role="left")
    b_panel = _prepared_panel(right, b_summary, support, label=f"B: {cells[1]['label']} (n = {len(b_ids)})", participant_ids=b_ids, comparison=metadata, role="right")
    difference_panel = _prepared_panel(
        left, difference, support, label=f"A − B: {cells[0]['label']} − {cells[1]['label']}",
        participant_ids=a_ids if comparison_kind == "conditions" else a_ids + b_ids,
        comparison=metadata, role="difference",
    )
    # A concurrent transactional rebuild must not publish a mixed comparison.
    for path, original in read_files:
        if _read_json(path)[1] != original:
            raise SourceComparisonUnavailable("Source bundle changed during comparison; reload the maps.")
    if (root / SOURCE_BUNDLE_RECEIPT).exists():
        validate_source_bundle(manifest_path)
    return DescriptiveSourceComparison(a_panel, b_panel, difference_panel, metadata)


__all__ = ["DescriptiveSourceComparison", "SourceComparisonUnavailable", "build_descriptive_source_comparison"]
