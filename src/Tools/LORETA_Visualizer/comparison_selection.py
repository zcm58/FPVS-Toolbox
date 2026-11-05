"""Select prepared metrics and comparison operands without calculating sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .prepared_payload_importer import PreparedSourceManifestEntry


METRIC_Z_SCORE = "z_score"
METRIC_AMPLITUDE = "baseline_corrected_amplitude"
METRIC_SAVED = "saved_values"
METRIC_LABELS = {
    METRIC_Z_SCORE: "Z-score",
    METRIC_AMPLITUDE: "Baseline-corrected amplitude",
    METRIC_SAVED: "Prepared values",
}


def entry_metric(entry: PreparedSourceManifestEntry) -> str:
    declared = entry.metadata.get("source_metric")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    unit = str(entry.metadata.get("source_value_unit", "")).lower()
    if "z-score" in unit or "zscore" in unit or "participant_zscore_aggregation" in entry.metadata:
        return METRIC_Z_SCORE
    return METRIC_SAVED


def metric_entries(
    entries: Iterable[PreparedSourceManifestEntry], metric: str,
) -> tuple[PreparedSourceManifestEntry, ...]:
    return tuple(entry for entry in entries if entry_metric(entry) == metric)


def entry_identity(entry: PreparedSourceManifestEntry, name: str) -> str:
    values = [entry.metadata[key] for key in (name, f"condition_{name}") if key in entry.metadata]
    if values and any(value != values[0] for value in values[1:]):
        raise ValueError(f"{entry.label} has conflicting {name} metadata. Reload its source bundle.")
    value = values[0] if values else ""
    return value.strip() if isinstance(value, str) else ""


def comparison_targets(
    entries: Iterable[PreparedSourceManifestEntry], left: PreparedSourceManifestEntry, *, kind: str,
) -> tuple[PreparedSourceManifestEntry, ...]:
    """Offer canonical operands; numerical compatibility is checked by the producer."""
    if kind not in {"groups", "conditions"}:
        raise ValueError("Choose a group or condition comparison.")
    condition = entry_identity(left, "canonical_condition_id")
    group = entry_identity(left, "group_id")
    if not condition:
        return ()
    summary = left.metadata.get("participant_zscore_aggregation")
    matches = []
    for right in entries:
        if right.condition_id == left.condition_id or entry_metric(right) != entry_metric(left):
            continue
        if right.metadata.get("participant_zscore_aggregation") != summary:
            continue
        other_condition = entry_identity(right, "canonical_condition_id")
        other_group = entry_identity(right, "group_id")
        if kind == "groups":
            valid = bool(group and other_group and group != other_group and condition == other_condition)
        else:
            valid = bool(other_condition and condition != other_condition and group == other_group)
        if valid:
            matches.append(right)
    return tuple(matches)


def operand_label(entry: PreparedSourceManifestEntry, *, kind: str) -> str:
    name = "group_label" if kind == "groups" else "canonical_condition_label"
    return entry_identity(entry, name) or entry.label


@dataclass(frozen=True)
class DescriptiveComparisonRequest:
    manifest_path: Path
    left_entry_id: str
    right_entry_id: str
    comparison_kind: str


def comparison_request(
    left: PreparedSourceManifestEntry, right: PreparedSourceManifestEntry, *, kind: str,
) -> DescriptiveComparisonRequest:
    left_path = left.metadata.get("_loaded_manifest_path")
    right_path = right.metadata.get("_loaded_manifest_path")
    if not left_path or left_path != right_path:
        raise ValueError("Both maps must come from the same source bundle. Rebuild or reload the source maps.")
    if right not in comparison_targets((right,), left, kind=kind):
        raise ValueError("Select different groups for one condition, or different conditions within one group.")
    return DescriptiveComparisonRequest(
        Path(left_path), left.raw_id or left.condition_id, right.raw_id or right.condition_id, kind,
    )


def comparison_bundle_signature(manifest_path: Path) -> tuple:
    """Invalidate prepared comparisons when any bundle JSON is replaced or removed.

    Numerical validation and receipt hashes remain producer-owned. Statting the
    bundle also catches a missing/changed participant sidecar without reading its
    potentially large arrays on the GUI thread.
    """
    rows = []
    manifest_path.stat()
    for path in sorted(manifest_path.parent.glob("*.json")):
        stat = path.stat()
        rows.append((path.name, stat.st_ino, stat.st_mtime_ns, stat.st_size))
    return tuple(rows)
