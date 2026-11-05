"""Match prepared group maps for descriptive side-by-side viewing only.

Canonical identities come from saved producer metadata, never labels, filenames
or output folders. This module performs no source or between-group statistics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from Tools.LORETA_Visualizer.prepared_payload_importer import PreparedSourceManifestEntry
from Tools.LORETA_Visualizer.source_payloads import SourcePayload


# Compare declared numerical settings without requiring metadata absent from
# both historical maps. These are model identities, not data-dependent masks,
# cohort sizes or source values, which are expected to differ between groups.
_METHOD_METADATA_FIELDS = (
    "source_metric", "source_value_polarity",
    "base_producer_method", "source_method", "source_value_unit",
    "selected_harmonics_hz", "template_subject", "source_space",
    "source_map_model", "orientation_constraint", "participant_zscore_trim_fraction",
    "lambda2", "inverse_backend", "loose_orientation", "fixed_orientation",
    "depth_weighting", "noise_normalization", "average_reference_applied",
    "montage_name", "source_spacing_mm", "source_spacing", "volume_pos_mm",
    "forward_model_source_spacing", "forward_model_volume_pos_mm",
    "forward_model_mindist_mm", "forward_model_noise_covariance",
    "forward_model_average_reference_projection", "forward_model_model_sfreq_hz",
    "forward_model_source_psd_lambda2", "forward_model_source_psd_method_params",
    "forward_model_native_mne_leadfield_sha256",
)


class GroupComparisonUnavailable(ValueError):
    """The loaded maps cannot make an unambiguous, comparable group pair."""


@dataclass(frozen=True)
class GroupMapCandidate:
    entry: PreparedSourceManifestEntry
    payload: SourcePayload
    group_id: str
    group_label: str
    condition_id: str
    condition_label: str
    summary_id: str
    participant_count: int | None
    method_signature: tuple[object, ...]

    @property
    def panel_label(self) -> str:
        if self.participant_count is None:
            return self.group_label
        return f"{self.group_label} (n = {self.participant_count})"


@dataclass(frozen=True)
class GroupComparisonPair:
    left: GroupMapCandidate
    right: GroupMapCandidate

    @property
    def condition_id(self) -> str:
        return self.left.condition_id

    @property
    def condition_label(self) -> str:
        return self.left.condition_label

    @property
    def summary_id(self) -> str:
        return self.left.summary_id

    @property
    def group_ids(self) -> tuple[str, str]:
        return self.left.group_id, self.right.group_id


def comparison_candidates(
    entries: Sequence[PreparedSourceManifestEntry],
    payloads_by_entry_id: Mapping[str, SourcePayload],
) -> tuple[GroupMapCandidate, ...]:
    """Validate loaded entry/payload identities without I/O or data mutation.

The current producer stores group fields as ``condition_*`` payload metadata;
older manifests alone do not contain enough information to establish a pair.
Callers load the prepared payloads through the ordinary importer in a worker.
"""
    candidates = []
    seen_ids: set[str] = set()
    for entry in entries:
        if entry.condition_id in seen_ids:
            raise GroupComparisonUnavailable("Duplicate source-map entry IDs prevent group comparison.")
        seen_ids.add(entry.condition_id)
        payload = payloads_by_entry_id.get(entry.condition_id)
        if payload is None:
            raise GroupComparisonUnavailable(f"Load the source map for {entry.label} before comparing groups.")
        candidates.append(_candidate(entry, payload))
    return tuple(candidates)


def build_group_comparison(
    candidates: Sequence[GroupMapCandidate],
    selected_entry_id: str,
    *,
    canonical_group_ids: Sequence[str] | None = None,
) -> GroupComparisonPair:
    """Return the exact summary/condition pair, or an actionable absence reason.

If available, canonical project groups constrain eligibility and left/right
order. For imported prepared maps, two explicit saved group identities suffice.
Other conditions may be missing a group; selecting one never substitutes a
different condition, summary or method.
"""
    selected_matches = [row for row in candidates if row.entry.condition_id == selected_entry_id]
    if len(selected_matches) != 1:
        raise GroupComparisonUnavailable("Select one unambiguous prepared source map to compare groups.")
    selected = selected_matches[0]
    group_ids = _comparison_group_ids(candidates, canonical_group_ids)
    matching_condition = [
        row for row in candidates
        if row.condition_id == selected.condition_id and row.summary_id == selected.summary_id
    ]
    paired = []
    for group_id in group_ids:
        group_maps = [row for row in matching_condition if row.group_id == group_id]
        matches = [row for row in group_maps if row.method_signature == selected.method_signature]
        if not matches:
            if group_maps:
                raise GroupComparisonUnavailable(
                    f"{group_maps[0].group_label} has no matching numerical method, metric and source space "
                    f"for {selected.condition_label} ({selected.summary_id})."
                )
            group_label = next((row.group_label for row in candidates if row.group_id == group_id), group_id)
            raise GroupComparisonUnavailable(
                f"{group_label} has no source map for {selected.condition_label} "
                f"with the selected summary ({selected.summary_id})."
            )
        if len(matches) != 1:
            raise GroupComparisonUnavailable(
                f"Multiple source maps match {matches[0].group_label} / {selected.condition_label} "
                f"({selected.summary_id}); load one source bundle for this method."
            )
        paired.append(matches[0])
    return GroupComparisonPair(paired[0], paired[1])


def _candidate(entry: PreparedSourceManifestEntry, payload: SourcePayload) -> GroupMapCandidate:
    metadata = payload.metadata
    split_applied = _identity_value(entry, metadata, "group_split_applied")
    group_id = _text(_identity_value(entry, metadata, "group_id"))
    condition_id = _text(_identity_value(entry, metadata, "canonical_condition_id"))
    if split_applied is not True or not group_id or not condition_id:
        raise GroupComparisonUnavailable(
            f"{entry.label} lacks explicit canonical group/condition metadata. "
            "Rebuild group source maps before comparing them."
        )
    summary_id = _shared_metadata(entry, metadata, "participant_zscore_aggregation")
    summary_id = _text(summary_id)
    if not summary_id:
        # Direct maps are comparable only when both explicitly have no aggregation.
        summary_id = "direct"
    producer_method = _text(_shared_metadata(entry, metadata, "producer_method"))
    if not producer_method:
        raise GroupComparisonUnavailable(f"{entry.label} has no explicit numerical source method.")
    signature = (
        producer_method,
        *(_freeze(_shared_metadata(entry, metadata, name)) for name in _METHOD_METADATA_FIELDS),
        payload.source_model,
        payload.kind,
        payload.coordinate_space,
        payload.value_label,
    )
    return GroupMapCandidate(
        entry=entry,
        payload=payload,
        group_id=group_id,
        group_label=_text(_identity_value(entry, metadata, "group_label")) or group_id,
        condition_id=condition_id,
        condition_label=_text(_identity_value(entry, metadata, "canonical_condition_label")) or condition_id,
        summary_id=summary_id,
        participant_count=_participant_count(metadata),
        method_signature=signature,
    )


def _comparison_group_ids(
    candidates: Sequence[GroupMapCandidate], canonical_group_ids: Sequence[str] | None,
) -> tuple[str, str]:
    saved_ids = {row.group_id for row in candidates}
    if canonical_group_ids is not None:
        group_ids = tuple(_text(group_id) for group_id in canonical_group_ids)
        if len(group_ids) != 2 or len(set(group_ids)) != 2 or not all(group_ids):
            raise GroupComparisonUnavailable("Group comparison requires a project with exactly two groups.")
        if not saved_ids.issubset(group_ids):
            raise GroupComparisonUnavailable(
                "Loaded source groups do not match the current project groups. Rebuild the source maps."
            )
    else:
        if len(saved_ids) != 2:
            raise GroupComparisonUnavailable("Load prepared source maps with exactly two explicit groups.")
        labels = {row.group_id: row.group_label for row in candidates}
        group_ids = tuple(sorted(saved_ids, key=lambda item: (labels[item].casefold(), item)))
    return group_ids[0], group_ids[1]


def _identity_value(entry: PreparedSourceManifestEntry, metadata: Mapping[str, object], name: str) -> object:
    values = [
        mapping[key] for mapping in (entry.metadata, metadata)
        for key in (name, f"condition_{name}") if key in mapping
    ]
    if values and any(_freeze(value) != _freeze(values[0]) for value in values[1:]):
        raise GroupComparisonUnavailable(f"{entry.label} has conflicting {name} metadata; reload its source bundle.")
    return values[0] if values else None


def _shared_metadata(entry: PreparedSourceManifestEntry, metadata: Mapping[str, object], name: str) -> object:
    if name in entry.metadata and name in metadata and _freeze(entry.metadata[name]) != _freeze(metadata[name]):
        raise GroupComparisonUnavailable(f"{entry.label} has conflicting {name} metadata; reload its source bundle.")
    return metadata.get(name, entry.metadata.get(name))


def _participant_count(metadata: Mapping[str, object]) -> int | None:
    value = metadata.get("participant_count")
    if isinstance(value, bool) or value is None:
        return None
    try:
        count = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return count if count >= 0 and count == value else None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _freeze(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value
