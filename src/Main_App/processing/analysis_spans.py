"""Versioned source-to-target coordinates for approved analysis intervals.

The preflight marker plan is authoritative.  This module gives every retained
occurrence one immutable source coordinate record and deterministically
realizes those same time boundaries on the actual post-resample Raw grid.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction
import hashlib
import json
import math
from typing import Any

import numpy as np

from Main_App.processing.marker_integrity import validate_approved_event_plan
from Main_App.projects.frequency_protocol import FrequencyProtocol

ANALYSIS_SPAN_PLAN_VERSION = "analysis_span_plan_v2_v3_stim_alignment"
ANALYSIS_SPAN_COORDINATE_VERSION = "raw_half_open_relative_to_first_samp_v1"
TARGET_SPAN_ROUNDING_VERSION = "v3_mne_stim_window_start_exact_duration_v1"
ANALYSIS_CONDITION_SELECTION_VERSION = "manual_condition_exclusion_v1"

_EVENT_PLAN_DERIVED_KEYS = {
    "event_plan_fingerprint",
    "source_analysis_span_plan",
}


class AnalysisSpanPlanError(ValueError):
    """Raised when an analysis-span plan is absent, stale, or inconsistent."""


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _without_fingerprint(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "fingerprint"}


def _event_plan_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key not in _EVENT_PLAN_DERIVED_KEYS
    }


def event_plan_fingerprint(value: Mapping[str, Any]) -> str:
    """Return the identity of a preflight event plan before derived span data."""

    if not isinstance(value, Mapping):
        raise AnalysisSpanPlanError("Preflight event plan must be an object.")
    return _fingerprint(_event_plan_core(value))


def canonical_condition_event_map(
    event_map: Mapping[str, int],
) -> dict[str, int]:
    """Return the exact normalized condition identity used by span planning."""

    if not isinstance(event_map, Mapping):
        raise AnalysisSpanPlanError("Condition event map must be an object.")
    normalized: dict[str, int] = {}
    for raw_label, raw_code in event_map.items():
        label = str(raw_label).strip()
        if not label:
            continue
        if label in normalized:
            raise AnalysisSpanPlanError(
                "Condition event-map labels are duplicated after normalization."
            )
        try:
            code = int(raw_code)
        except (TypeError, ValueError) as exc:
            raise AnalysisSpanPlanError(
                "Condition event-map codes must be integers."
            ) from exc
        if isinstance(raw_code, bool) or code != raw_code:
            raise AnalysisSpanPlanError(
                "Condition event-map codes must be integers."
            )
        normalized[label] = code
    if not normalized:
        raise AnalysisSpanPlanError("Condition event map must not be empty.")
    return {label: normalized[label] for label in sorted(normalized)}


def _finite_positive_float(value: Any, *, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AnalysisSpanPlanError(
            f"{field_name} must be a finite positive number."
        ) from exc
    if not math.isfinite(number) or number <= 0.0:
        raise AnalysisSpanPlanError(
            f"{field_name} must be a finite positive number."
        )
    return number


def _nonnegative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise AnalysisSpanPlanError(f"{field_name} must be a nonnegative integer.")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalysisSpanPlanError(
            f"{field_name} must be a nonnegative integer."
        ) from exc
    if number < 0 or number != value:
        raise AnalysisSpanPlanError(f"{field_name} must be a nonnegative integer.")
    return number


def _integer(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise AnalysisSpanPlanError(f"{field_name} must be an integer.")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalysisSpanPlanError(f"{field_name} must be an integer.") from exc
    if number != value:
        raise AnalysisSpanPlanError(f"{field_name} must be an integer.")
    return number


def merge_relative_spans(
    spans: Sequence[Sequence[int]],
    *,
    n_times: int | None = None,
) -> tuple[tuple[int, int], ...]:
    """Validate and merge half-open relative spans so each sample occurs once."""

    limit = int(n_times) if n_times is not None else None
    normalized: list[tuple[int, int]] = []
    for index, raw_span in enumerate(spans):
        if (
            not isinstance(raw_span, Sequence)
            or isinstance(raw_span, (str, bytes))
            or len(raw_span) != 2
        ):
            raise AnalysisSpanPlanError(
                f"Analysis span {index} must contain [start, stop]."
            )
        start = _nonnegative_int(raw_span[0], field_name=f"span[{index}].start")
        stop = _nonnegative_int(raw_span[1], field_name=f"span[{index}].stop")
        if stop <= start:
            raise AnalysisSpanPlanError(
                f"Analysis span {index} must have stop greater than start."
            )
        if limit is not None and stop > limit:
            raise AnalysisSpanPlanError(
                f"Analysis span {index} exceeds the recording sample count."
            )
        normalized.append((start, stop))

    merged: list[list[int]] = []
    for start, stop in sorted(normalized):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], stop)
        else:
            merged.append([start, stop])
    return tuple((start, stop) for start, stop in merged)


def _sequence_of_mappings(value: Any, *, field_name: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AnalysisSpanPlanError(f"{field_name} must be a list.")
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise AnalysisSpanPlanError(f"{field_name} contains a malformed item.")
        result.append(item)
    return result


def _build_source_analysis_span_plan(
    event_plan_payload: Mapping[str, Any],
) -> dict[str, Any]:
    core = _event_plan_core(event_plan_payload)
    source_sfreq = _finite_positive_float(core.get("sfreq"), field_name="sfreq")
    source_n_times = _nonnegative_int(core.get("n_times"), field_name="n_times")
    if source_n_times <= 0:
        raise AnalysisSpanPlanError("n_times must be positive.")
    source_first_samp = _integer(
        core.get("first_samp", 0),
        field_name="first_samp",
    )
    marker_plan = core.get("marker_integrity_plan")
    if not isinstance(marker_plan, Mapping):
        raise AnalysisSpanPlanError(
            "Preflight event plan is missing marker integrity data."
        )
    protocol_fingerprint = str(marker_plan.get("protocol_fingerprint") or "")
    if not protocol_fingerprint:
        raise AnalysisSpanPlanError("Marker plan protocol fingerprint is missing.")

    raw_approved = _sequence_of_mappings(
        core.get("approved_occurrences"),
        field_name="approved_occurrences",
    )
    approved_by_key: dict[str, Mapping[str, Any]] = {}
    for approved in raw_approved:
        try:
            key = (
                f"{int(approved['condition_code'])}:"
                f"{int(approved['repetition_index'])}"
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisSpanPlanError(
                "Approved occurrence identity is malformed."
            ) from exc
        if key in approved_by_key:
            raise AnalysisSpanPlanError("Approved occurrence identities are duplicated.")
        approved_by_key[key] = approved

    source_spans: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw_span in _sequence_of_mappings(core.get("spans"), field_name="spans"):
        try:
            condition_code = int(raw_span["condition_id"])
            repetition_index = int(raw_span["repetition_index"])
            start = int(raw_span["time_start_sample"])
            stop = int(raw_span["time_stop_sample"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisSpanPlanError("Preflight analysis span is malformed.") from exc
        key = f"{condition_code}:{repetition_index}"
        if key in seen_keys:
            raise AnalysisSpanPlanError("Preflight analysis-span identities are duplicated.")
        seen_keys.add(key)
        approved = approved_by_key.get(key)
        if approved is None:
            raise AnalysisSpanPlanError(
                "Preflight analysis span has no approved marker occurrence."
            )
        if str(approved.get("disposition") or "") == "exclude_occurrence":
            raise AnalysisSpanPlanError("An excluded occurrence contains an analysis span.")
        if start != int(approved.get("start_sample", -1)) or stop != int(
            approved.get("stop_sample", -1)
        ):
            raise AnalysisSpanPlanError(
                "Preflight span bounds disagree with its approved occurrence."
            )
        start_relative = start - source_first_samp
        stop_relative = stop - source_first_samp
        if start_relative < 0 or stop_relative > source_n_times or stop_relative <= start_relative:
            raise AnalysisSpanPlanError(
                "Preflight analysis span is outside the source Raw sample grid."
            )
        span_core = {
            "condition_label": str(raw_span.get("condition_label") or ""),
            "condition_code": condition_code,
            "repetition_index": repetition_index,
            "occurrence_key": key,
            "oddball_marker_code": _integer(
                raw_span.get("oddball_id"), field_name="oddball_marker_code"
            ),
            "marker_plan_fingerprint": str(
                raw_span.get("marker_plan_fingerprint") or ""
            ),
            "approved_span_fingerprint": str(
                raw_span.get("approved_span_fingerprint") or ""
            ),
            "marker_disposition": str(raw_span.get("marker_disposition") or ""),
            "source_coordinates": {
                "first_samp": source_first_samp,
                "start_sample": start,
                "stop_sample": stop,
                "start_relative_sample": start_relative,
                "stop_relative_sample": stop_relative,
            },
        }
        source_spans.append({**span_core, "fingerprint": _fingerprint(span_core)})

    retained_approved_keys = {
        key
        for key, approved in approved_by_key.items()
        if str(approved.get("disposition") or "") != "exclude_occurrence"
    }
    if seen_keys != retained_approved_keys:
        raise AnalysisSpanPlanError(
            "Retained approved occurrences and preflight spans do not match."
        )
    unique_spans = merge_relative_spans(
        [
            (
                span["source_coordinates"]["start_relative_sample"],
                span["source_coordinates"]["stop_relative_sample"],
            )
            for span in source_spans
        ],
        n_times=source_n_times,
    )
    plan_core = {
        "version": ANALYSIS_SPAN_PLAN_VERSION,
        "coordinate_version": ANALYSIS_SPAN_COORDINATE_VERSION,
        "event_plan_fingerprint": event_plan_fingerprint(core),
        "protocol_fingerprint": protocol_fingerprint,
        "event_digest": str(core.get("event_digest") or ""),
        "source_grid": {
            "sfreq_hz": source_sfreq,
            "n_times": source_n_times,
            "first_samp": source_first_samp,
            "sample_origin": "raw.first_samp",
        },
        "spans": source_spans,
        "unique_relative_spans": [list(span) for span in unique_spans],
        "unique_sample_count": sum(stop - start for start, stop in unique_spans),
    }
    return {**plan_core, "fingerprint": _fingerprint(plan_core)}


def attach_source_analysis_span_plan(
    event_plan_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach the canonical event and source-span identities to a preflight plan."""

    core = _event_plan_core(event_plan_payload)
    event_fingerprint = event_plan_fingerprint(core)
    source_plan = _build_source_analysis_span_plan(core)
    return {
        **core,
        "event_plan_fingerprint": event_fingerprint,
        "source_analysis_span_plan": source_plan,
    }


def read_source_analysis_span_plan(
    event_plan_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a validated canonical source plan embedded by current preflight."""

    if not isinstance(event_plan_payload, Mapping):
        raise AnalysisSpanPlanError("Preflight event plan must be an object.")
    supplied_event_fingerprint = str(
        event_plan_payload.get("event_plan_fingerprint") or ""
    )
    expected_event_fingerprint = event_plan_fingerprint(event_plan_payload)
    if supplied_event_fingerprint != expected_event_fingerprint:
        raise AnalysisSpanPlanError("Preflight event-plan fingerprint is missing or stale.")
    raw_plan = event_plan_payload.get("source_analysis_span_plan")
    if not isinstance(raw_plan, Mapping):
        raise AnalysisSpanPlanError(
            "Preflight event plan is missing source analysis-span provenance."
        )
    expected_plan = _build_source_analysis_span_plan(event_plan_payload)
    if dict(raw_plan) != expected_plan:
        raise AnalysisSpanPlanError("Preflight source analysis-span plan is stale.")
    return expected_plan


def validate_source_analysis_span_context(
    *,
    event_plan_payload: Mapping[str, Any],
    event_map: Mapping[str, int],
    protocol: FrequencyProtocol,
) -> dict[str, Any]:
    """Bind an internally valid source plan to the current project context."""

    plan = read_source_analysis_span_plan(event_plan_payload)
    if not protocol.is_ready or str(plan["protocol_fingerprint"]) != protocol.fingerprint:
        raise AnalysisSpanPlanError(
            "Source analysis-span protocol is stale relative to the project."
        )
    planned_event_map = event_plan_payload.get("condition_event_map")
    if not isinstance(planned_event_map, Mapping):
        raise AnalysisSpanPlanError(
            "Preflight event plan is missing its condition event-map identity."
        )
    try:
        planned_identity = canonical_condition_event_map(planned_event_map)
    except AnalysisSpanPlanError as exc:
        raise AnalysisSpanPlanError(
            "Preflight condition event-map identity is malformed."
        ) from exc
    if planned_identity != canonical_condition_event_map(event_map):
        raise AnalysisSpanPlanError(
            "Source analysis-span condition event map is stale relative to the project."
        )
    return plan


def validate_source_analysis_span_plan(
    *,
    event_plan_payload: Mapping[str, Any],
    events: np.ndarray,
    sampling_rate_hz: Any,
    n_times: int,
    first_samp: int,
    event_map: Mapping[str, int],
    protocol: FrequencyProtocol,
) -> dict[str, Any]:
    """Validate an exact reviewed preflight plan against the source Raw."""

    plan = validate_source_analysis_span_context(
        event_plan_payload=event_plan_payload,
        event_map=event_map,
        protocol=protocol,
    )
    validate_approved_event_plan(
        event_plan_payload=event_plan_payload,
        events=events,
        sampling_rate_hz=sampling_rate_hz,
        n_times=n_times,
        first_samp=first_samp,
        event_map=event_map,
        protocol=protocol,
    )
    source_grid = plan["source_grid"]
    if float(source_grid["sfreq_hz"]) != float(sampling_rate_hz):
        raise AnalysisSpanPlanError("Source analysis-span sampling rate is stale.")
    if int(source_grid["n_times"]) != int(n_times):
        raise AnalysisSpanPlanError("Source analysis-span recording length is stale.")
    if int(source_grid["first_samp"]) != int(first_samp):
        raise AnalysisSpanPlanError("Source analysis-span sample origin is stale.")
    if str(plan["protocol_fingerprint"]) != protocol.fingerprint:
        raise AnalysisSpanPlanError("Source analysis-span protocol is stale.")
    return plan


def restrict_source_analysis_span_plan_by_condition(
    source_plan: Mapping[str, Any],
    *,
    excluded_condition_labels: Sequence[object],
    exclusion_scope: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive the exact analyzed span plan after explicit condition exclusions.

    The reviewed marker plan remains intact. This derived plan records which
    condition windows can influence signal QC, kurtosis, preprocessing cache
    identity, and epoch construction for one recording.
    """

    if not isinstance(source_plan, Mapping):
        raise AnalysisSpanPlanError("Source analysis-span plan must be an object.")
    source_core = _without_fingerprint(source_plan)
    if source_plan.get("version") != ANALYSIS_SPAN_PLAN_VERSION:
        raise AnalysisSpanPlanError("Source analysis-span plan version is not current.")
    if str(source_plan.get("fingerprint") or "") != _fingerprint(source_core):
        raise AnalysisSpanPlanError("Source analysis-span fingerprint is stale.")
    if "condition_selection" in source_plan:
        raise AnalysisSpanPlanError(
            "Condition exclusions must be derived from the reviewed source plan once."
        )
    if isinstance(excluded_condition_labels, (str, bytes, bytearray)):
        raise AnalysisSpanPlanError("Excluded condition labels must be a sequence.")

    requested: list[str] = []
    requested_keys: set[str] = set()
    for raw_label in excluded_condition_labels:
        label = str(raw_label or "").strip()
        if not label:
            raise AnalysisSpanPlanError("Excluded condition labels must not be blank.")
        key = label.casefold()
        if key in requested_keys:
            continue
        requested_keys.add(key)
        requested.append(label)
    requested.sort(key=str.casefold)

    if not isinstance(exclusion_scope, Mapping) or not exclusion_scope:
        raise AnalysisSpanPlanError("Condition-exclusion scope must be a nonempty object.")
    try:
        canonical_scope = json.loads(
            json.dumps(
                dict(exclusion_scope),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise AnalysisSpanPlanError(
            "Condition-exclusion scope must contain JSON-safe finite values."
        ) from exc
    if not isinstance(canonical_scope, dict) or not canonical_scope:
        raise AnalysisSpanPlanError("Condition-exclusion scope must be a nonempty object.")

    source_spans = _sequence_of_mappings(
        source_plan.get("spans"),
        field_name="source spans",
    )
    retained_spans = [
        dict(span)
        for span in source_spans
        if str(span.get("condition_label") or "").strip().casefold()
        not in requested_keys
    ]
    source_grid = source_plan.get("source_grid")
    if not isinstance(source_grid, Mapping):
        raise AnalysisSpanPlanError("Source analysis-span grid is malformed.")
    unique_spans = merge_relative_spans(
        [
            (
                int(span["source_coordinates"]["start_relative_sample"]),
                int(span["source_coordinates"]["stop_relative_sample"]),
            )
            for span in retained_spans
        ],
        n_times=int(source_grid.get("n_times", -1)),
    )
    selection = {
        "version": ANALYSIS_CONDITION_SELECTION_VERSION,
        "parent_source_plan_fingerprint": str(source_plan.get("fingerprint") or ""),
        "excluded_condition_labels": requested,
        "scope": canonical_scope,
    }
    restricted_core = {
        **source_core,
        "spans": retained_spans,
        "unique_relative_spans": [list(span) for span in unique_spans],
        "unique_sample_count": sum(stop - start for start, stop in unique_spans),
        "condition_selection": selection,
    }
    return {**restricted_core, "fingerprint": _fingerprint(restricted_core)}


def _v3_stim_window_index(
    source_sample: int,
    *,
    source_count: int,
    target_count: int,
) -> int:
    """Locate MNE's target stimulus window containing one source sample.

    For a single Raw segment MNE uses the realized length ratio, then window
    starts ``int(target_index / ratio)``. Binary search reproduces those float
    operations without allocating a recording-length index array. The actual
    target stimulus must also be checked: collisions can suppress an onset.
    """

    if not 0 <= source_sample < source_count:
        raise AnalysisSpanPlanError("Source marker is outside its Raw sample grid.")
    if not 0 < target_count <= source_count:
        raise AnalysisSpanPlanError(
            "V3 stimulus alignment requires a positive, non-upsampled Raw grid."
        )
    ratio = float(target_count) / source_count
    lower, upper = 0, target_count
    while lower < upper:
        midpoint = (lower + upper) // 2
        window_start = min(int(midpoint / ratio), source_count - 1)
        if window_start <= source_sample:
            lower = midpoint + 1
        else:
            upper = midpoint
    return lower - 1


def _rate_fraction(value: Any, *, field_name: str) -> Fraction:
    number = _finite_positive_float(value, field_name=field_name)
    return Fraction(str(number))


def realize_target_analysis_span_plan(
    source_plan: Mapping[str, Any],
    *,
    target_sfreq_hz: Any,
    target_n_times: int,
    target_first_samp: int,
) -> dict[str, Any]:
    """Preserve v3 stimulus-window starts and the exact approved duration.

    This mapping covers one continuous Raw segment with stimulus events and
    no upsampling. The caller must reject resampled annotation-only or
    multi-segment inputs, then verify the actual target stimulus onset;
    event collisions cannot be resolved from source coordinates alone. The
    stop is the mapped start plus the exact project duration in target samples.
    """

    if not isinstance(source_plan, Mapping):
        raise AnalysisSpanPlanError("Source analysis-span plan must be an object.")
    raw_core = _without_fingerprint(source_plan)
    if source_plan.get("version") != ANALYSIS_SPAN_PLAN_VERSION:
        raise AnalysisSpanPlanError("Source analysis-span plan version is not current.")
    if str(source_plan.get("fingerprint") or "") != _fingerprint(raw_core):
        raise AnalysisSpanPlanError("Source analysis-span fingerprint is stale.")
    source_grid = source_plan.get("source_grid")
    if not isinstance(source_grid, Mapping):
        raise AnalysisSpanPlanError("Source analysis-span grid is malformed.")
    source_rate = _rate_fraction(
        source_grid.get("sfreq_hz"),
        field_name="source_sfreq_hz",
    )
    target_rate = _rate_fraction(target_sfreq_hz, field_name="target_sfreq_hz")
    source_count = _nonnegative_int(
        source_grid.get("n_times"), field_name="source_n_times"
    )
    if source_count <= 0 or target_rate > source_rate:
        raise AnalysisSpanPlanError(
            "V3 stimulus alignment requires a positive, non-upsampled Raw grid."
        )
    target_count = _nonnegative_int(target_n_times, field_name="target_n_times")
    if target_count <= 0:
        raise AnalysisSpanPlanError("target_n_times must be positive.")
    target_origin = _integer(target_first_samp, field_name="target_first_samp")

    realized_spans: list[dict[str, Any]] = []
    for raw_span in _sequence_of_mappings(
        source_plan.get("spans"), field_name="source spans"
    ):
        source_coordinates = raw_span.get("source_coordinates")
        if not isinstance(source_coordinates, Mapping):
            raise AnalysisSpanPlanError("Source span coordinates are malformed.")
        source_start_relative = _nonnegative_int(
            source_coordinates.get("start_relative_sample"),
            field_name="source_start_relative_sample",
        )
        source_stop_relative = _nonnegative_int(
            source_coordinates.get("stop_relative_sample"),
            field_name="source_stop_relative_sample",
        )
        target_start_relative = _v3_stim_window_index(
            source_start_relative,
            source_count=source_count,
            target_count=target_count,
        )
        target_duration = (
            Fraction(source_stop_relative - source_start_relative)
            * target_rate
            / source_rate
        )
        if target_duration <= 0 or target_duration.denominator != 1:
            raise AnalysisSpanPlanError(
                "The approved analyzed duration must contain an exact whole "
                "number of target samples."
            )
        target_stop_relative = target_start_relative + int(target_duration)
        if (
            target_stop_relative <= target_start_relative
            or target_stop_relative > target_count
        ):
            raise AnalysisSpanPlanError(
                "Realized analysis span is outside the target Raw sample grid."
            )
        span_core = {
            "condition_label": str(raw_span.get("condition_label") or ""),
            "condition_code": int(raw_span.get("condition_code")),
            "repetition_index": int(raw_span.get("repetition_index")),
            "occurrence_key": str(raw_span.get("occurrence_key") or ""),
            "oddball_marker_code": _integer(
                raw_span.get("oddball_marker_code"), field_name="oddball_marker_code"
            ),
            "marker_plan_fingerprint": str(
                raw_span.get("marker_plan_fingerprint") or ""
            ),
            "approved_span_fingerprint": str(
                raw_span.get("approved_span_fingerprint") or ""
            ),
            "marker_disposition": str(raw_span.get("marker_disposition") or ""),
            "source_span_fingerprint": str(raw_span.get("fingerprint") or ""),
            "source_coordinates": dict(source_coordinates),
            "target_coordinates": {
                "first_samp": target_origin,
                "start_sample": target_origin + target_start_relative,
                "stop_sample": target_origin + target_stop_relative,
                "start_relative_sample": target_start_relative,
                "stop_relative_sample": target_stop_relative,
            },
        }
        realized_spans.append({**span_core, "fingerprint": _fingerprint(span_core)})

    if not realized_spans:
        raise AnalysisSpanPlanError("No retained analyzed occurrence spans were approved.")

    unique_spans = merge_relative_spans(
        [
            (
                span["target_coordinates"]["start_relative_sample"],
                span["target_coordinates"]["stop_relative_sample"],
            )
            for span in realized_spans
        ],
        n_times=target_count,
    )
    plan_core = {
        "version": ANALYSIS_SPAN_PLAN_VERSION,
        "coordinate_version": ANALYSIS_SPAN_COORDINATE_VERSION,
        "rounding_version": TARGET_SPAN_ROUNDING_VERSION,
        "source_plan_fingerprint": str(source_plan.get("fingerprint") or ""),
        "event_plan_fingerprint": str(
            source_plan.get("event_plan_fingerprint") or ""
        ),
        "protocol_fingerprint": str(source_plan.get("protocol_fingerprint") or ""),
        "target_grid": {
            "sfreq_hz": float(target_rate),
            "n_times": target_count,
            "first_samp": target_origin,
            "sample_origin": "raw.first_samp",
        },
        "spans": realized_spans,
        "unique_relative_spans": [list(span) for span in unique_spans],
        "unique_sample_count": sum(stop - start for start, stop in unique_spans),
    }
    condition_selection = source_plan.get("condition_selection")
    if isinstance(condition_selection, Mapping):
        plan_core["condition_selection"] = dict(condition_selection)
    return {**plan_core, "fingerprint": _fingerprint(plan_core)}


def validate_target_analysis_span_markers(
    target_plan: Mapping[str, Any],
    events: np.ndarray,
) -> None:
    """Require each mapped start to remain an actual project oddball onset.

    No nearest-event snapping is permitted. A lost or merged onset requires
    review instead of silently analyzing a different time window.
    """

    if not isinstance(target_plan, Mapping) or (
        target_plan.get("version") != ANALYSIS_SPAN_PLAN_VERSION
        or target_plan.get("rounding_version") != TARGET_SPAN_ROUNDING_VERSION
        or target_plan.get("fingerprint")
        != _fingerprint(_without_fingerprint(target_plan))
    ):
        raise AnalysisSpanPlanError("Realized analysis-span plan is missing or stale.")
    event_array = np.asarray(events)
    if event_array.ndim != 2 or event_array.shape[1] != 3:
        raise AnalysisSpanPlanError("Target marker events must have shape (n, 3).")
    marker_starts = {
        (
            _integer(row[0], field_name="target_marker_sample"),
            _integer(row[2], field_name="target_marker_code"),
        )
        for row in event_array
    }
    for span in _sequence_of_mappings(target_plan.get("spans"), field_name="target spans"):
        marker_code = _integer(
            span.get("oddball_marker_code"), field_name="oddball_marker_code"
        )
        if marker_code <= 0:
            raise AnalysisSpanPlanError("Oddball marker code must be positive.")
        coordinates = span.get("target_coordinates")
        if not isinstance(coordinates, Mapping):
            raise AnalysisSpanPlanError("Target span coordinates are malformed.")
        start = _integer(coordinates.get("start_sample"), field_name="target_start_sample")
        if (start, marker_code) not in marker_starts:
            raise AnalysisSpanPlanError(
                "The v3-aligned analyzed start no longer matches an actual "
                f"oddball marker {marker_code} after resampling "
                f"(occurrence={span.get('occurrence_key')}, sample={start}). "
                "The marker may have been lost or merged; the analysis window "
                "was not shifted."
            )


def validate_realized_target_analysis_span_plan(
    target_plan: Mapping[str, Any],
    *,
    source_plan: Mapping[str, Any],
    target_sfreq_hz: Any,
    target_n_times: int,
    target_first_samp: int,
) -> dict[str, Any]:
    """Fail closed unless cached/runtime target coordinates are exactly current."""

    if not isinstance(target_plan, Mapping):
        raise AnalysisSpanPlanError("Realized analysis-span plan must be an object.")
    expected = realize_target_analysis_span_plan(
        source_plan,
        target_sfreq_hz=target_sfreq_hz,
        target_n_times=target_n_times,
        target_first_samp=target_first_samp,
    )
    if dict(target_plan) != expected:
        raise AnalysisSpanPlanError("Realized analysis-span plan is missing or stale.")
    return expected


def relative_spans_from_plan(
    plan: Mapping[str, Any],
) -> tuple[tuple[int, int], ...]:
    """Return the validated unique half-open relative spans stored in a plan."""

    raw_spans = plan.get("unique_relative_spans")
    if not isinstance(raw_spans, Sequence) or isinstance(raw_spans, (str, bytes)):
        raise AnalysisSpanPlanError("Analysis-span union is missing or malformed.")
    grid = plan.get("target_grid", plan.get("source_grid"))
    if not isinstance(grid, Mapping):
        raise AnalysisSpanPlanError("Analysis-span grid is missing or malformed.")
    spans = merge_relative_spans(raw_spans, n_times=int(grid.get("n_times", -1)))
    if [list(span) for span in spans] != list(raw_spans):
        raise AnalysisSpanPlanError("Analysis-span union is not canonical.")
    if int(plan.get("unique_sample_count", -1)) != sum(
        stop - start for start, stop in spans
    ):
        raise AnalysisSpanPlanError("Analysis-span sample count is stale.")
    return spans


__all__ = [
    "ANALYSIS_CONDITION_SELECTION_VERSION",
    "ANALYSIS_SPAN_COORDINATE_VERSION",
    "ANALYSIS_SPAN_PLAN_VERSION",
    "AnalysisSpanPlanError",
    "TARGET_SPAN_ROUNDING_VERSION",
    "attach_source_analysis_span_plan",
    "canonical_condition_event_map",
    "event_plan_fingerprint",
    "merge_relative_spans",
    "read_source_analysis_span_plan",
    "realize_target_analysis_span_plan",
    "relative_spans_from_plan",
    "restrict_source_analysis_span_plan_by_condition",
    "validate_realized_target_analysis_span_plan",
    "validate_target_analysis_span_markers",
    "validate_source_analysis_span_context",
    "validate_source_analysis_span_plan",
]
