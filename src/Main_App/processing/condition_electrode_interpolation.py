"""Experimental condition-local EEG repair at the existing interpolation stage.

Inputs are the prepared, un-interpolated EEG and approved integer sample spans.
No spectral values, event times, filters, or recording-wide bad decisions are
changed here. Unaffected samples are left to the ordinary preprocessing path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any

import mne
import numpy as np

from Main_App.io.eeg_geometry import validate_raw_biosemi64_geometry
from Main_App.processing.analysis_spans import validate_realized_target_analysis_span_plan


CONDITION_INTERPOLATION_VERSION = "condition_electrode_interpolation_v1"


def normalize_condition_interpolation_requests(value: Any, *, excluded_condition_labels: Any = ()) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("Condition interpolation requests must be a condition-to-electrodes mapping.")
    excluded = {str(label).casefold() for label in excluded_condition_labels}
    result: dict[str, list[str]] = {}
    for condition, channels in value.items():
        if not isinstance(condition, str) or not condition.strip():
            raise ValueError("Condition interpolation requires a named condition.")
        if not isinstance(channels, (list, tuple)) or any(
            not isinstance(channel, str) or not channel.strip() for channel in channels
        ):
            raise ValueError("Condition interpolation requires a list of electrode names.")
        if channels and condition.casefold() not in excluded:
            result[condition] = sorted(set(channels))
    return dict(sorted(result.items()))


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class PreparedConditionRepairs:
    """Completed branches awaiting replacement after the normal final reference."""

    replacements: tuple[tuple[int, int, np.ndarray], ...]
    eeg_picks: np.ndarray
    provenance: dict[str, Any]


def prepare_condition_repairs(raw: Any, params: Mapping[str, Any]) -> PreparedConditionRepairs | None:
    requests = normalize_condition_interpolation_requests(
        params.get("_fpvs_condition_interpolation_requests"),
        excluded_condition_labels=params.get("_fpvs_excluded_condition_labels", ()),
    )
    if not requests:
        return None
    plan = params.get("_fpvs_realized_analysis_span_plan")
    if not isinstance(plan, Mapping) or not plan.get("fingerprint") or not isinstance(plan.get("spans"), list):
        raise ValueError("Condition interpolation requires the exact approved analysis-span plan.")
    source_plan = params.get("_fpvs_source_analysis_span_plan")
    if not isinstance(source_plan, Mapping):
        raise ValueError("Condition interpolation requires the approved source analysis-span plan.")
    validate_realized_target_analysis_span_plan(
        plan, source_plan=source_plan, target_sfreq_hz=raw.info["sfreq"],
        target_n_times=raw.n_times, target_first_samp=raw.first_samp,
    )
    geometry = validate_raw_biosemi64_geometry(raw)
    retained = set(geometry["retained_scalp_channels"])
    global_bads = list(dict.fromkeys(raw.info["bads"]))
    if not set(global_bads).issubset(retained):
        raise ValueError("Condition interpolation has an unsupported recording-wide bad electrode.")
    eeg_picks = mne.pick_types(raw.info, eeg=True, exclude=[])
    eeg_names = {raw.ch_names[int(pick)] for pick in eeg_picks}
    requested = {channel for channels in requests.values() for channel in channels}
    if not requested.issubset(retained & eeg_names):
        raise ValueError("Condition interpolation requested a missing or unsupported scalp electrode.")

    spans: list[tuple[int, int, frozenset[str], Mapping[str, Any]]] = []
    found: set[str] = set()
    for span in plan["spans"]:
        if not isinstance(span, Mapping):
            raise ValueError("Condition interpolation received a malformed analyzed span.")
        condition = str(span.get("condition_label") or "")
        coordinates = span.get("target_coordinates")
        if not isinstance(coordinates, Mapping):
            raise ValueError("Condition interpolation requires target-grid sample coordinates.")
        start = coordinates.get("start_relative_sample")
        stop = coordinates.get("stop_relative_sample")
        if (type(start) is not int or type(stop) is not int
                or not 0 <= start < stop <= raw.n_times
                or coordinates.get("start_sample") != raw.first_samp + start
                or coordinates.get("stop_sample") != raw.first_samp + stop):
            raise ValueError("Condition interpolation cannot change or infer analyzed sample timing.")
        local = requests.get(condition, [])
        if local:
            found.add(condition)
        effective = frozenset([*global_bads, *local])
        spans.append((start, stop, effective, span))
    if found != set(requests):
        raise ValueError("Condition interpolation requested a condition with no retained analyzed interval.")
    ordered = sorted(spans, key=lambda item: (item[0], item[1]))
    for index, (start, stop, effective, _span) in enumerate(ordered):
        for next_start, _next_stop, next_effective, _ in ordered[index + 1:]:
            if next_start >= stop:
                break
            if effective != next_effective:
                raise ValueError("Overlapping analyzed intervals require incompatible electrode repairs.")

    replacements: list[tuple[int, int, np.ndarray]] = []
    completed: list[dict[str, Any]] = []
    for start, stop, effective, span in spans:
        condition = str(span["condition_label"])
        if condition not in requests:
            continue
        data = raw.get_data(start=start, stop=stop)
        donors = [int(pick) for pick in eeg_picks if raw.ch_names[int(pick)] not in effective]
        if not donors or not np.isfinite(data[donors]).all():
            raise ValueError("Condition interpolation requires finite scalp donor electrodes.")
        branch = mne.io.RawArray(data, raw.info.copy(), first_samp=raw.first_samp + start, verbose=False)
        branch.info["bads"] = [name for name in raw.ch_names if name in effective]
        branch.interpolate_bads(reset_bads=True, mode="accurate", verbose=False)
        if branch.info["bads"]:
            raise RuntimeError("Condition interpolation left unresolved bad electrodes.")
        branch.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
        branch.apply_proj(verbose=False)
        repaired = branch.get_data(picks=eeg_picks)
        if not np.isfinite(repaired).all():
            raise RuntimeError("Condition interpolation produced nonfinite EEG samples.")
        replacements.append((start, stop, repaired))
        completed.append({
            "condition_label": condition,
            "occurrence_key": str(span.get("occurrence_key") or ""),
            "requested_channels": requests[condition],
            "interpolated_channels": [name for name in raw.ch_names if name in effective],
            "target_coordinates": dict(span["target_coordinates"]),
            "source_coordinates": dict(span.get("source_coordinates") or {}),
            "span_fingerprint": str(span.get("fingerprint") or ""),
        })
    provenance = {
        "version": CONDITION_INTERPOLATION_VERSION,
        "status": "completed",
        "requests": requests,
        "recording_wide_interpolated_channels": global_bads,
        "analysis_span_fingerprint": str(plan["fingerprint"]),
        "geometry_fingerprint": str(geometry.get("coordinate_fingerprint") or ""),
        "retained_scalp_set_fingerprint": str(geometry["retained_scalp_set_fingerprint"]),
        "spans": completed,
    }
    provenance["fingerprint"] = _fingerprint(provenance)
    return PreparedConditionRepairs(tuple(replacements), eeg_picks, provenance)


def apply_condition_repairs(raw: Any, repairs: PreparedConditionRepairs | None) -> dict[str, Any] | None:
    if repairs is None:
        return None
    for start, stop, values in repairs.replacements:
        raw._data[repairs.eeg_picks, start:stop] = values
    return repairs.provenance


def validate_condition_interpolation_provenance(
    value: Any, *, requests: Any, analysis_span_plan: Any, geometry: Mapping[str, Any],
) -> dict[str, Any] | None:
    expected = normalize_condition_interpolation_requests(requests)
    if not expected:
        if value:
            raise ValueError("Cached condition repairs do not match the current requests.")
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Completed condition interpolation provenance is missing.")
    core = {key: item for key, item in value.items() if key != "fingerprint"}
    if (value.get("version") != CONDITION_INTERPOLATION_VERSION
            or value.get("status") != "completed"
            or value.get("requests") != expected
            or not isinstance(analysis_span_plan, Mapping)
            or value.get("analysis_span_fingerprint") != analysis_span_plan.get("fingerprint")
            or value.get("geometry_fingerprint") != geometry.get("coordinate_fingerprint")
            or value.get("retained_scalp_set_fingerprint") != geometry.get("retained_scalp_set_fingerprint")
            or value.get("fingerprint") != _fingerprint(core)):
        raise ValueError("Completed condition interpolation provenance is stale or invalid.")
    global_bads = value.get("recording_wide_interpolated_channels")
    if not isinstance(global_bads, list) or not set(global_bads).issubset(geometry["retained_scalp_channels"]):
        raise ValueError("Completed condition interpolation has invalid recording-wide electrode provenance.")
    recorded_spans = value.get("spans")
    expected_spans = [span for span in analysis_span_plan.get("spans", [])
                      if span.get("condition_label") in expected]
    if (not isinstance(recorded_spans, list) or len(recorded_spans) != len(expected_spans)
            or {span["condition_label"] for span in expected_spans} != set(expected)):
        raise ValueError("Completed condition interpolation does not cover every requested occurrence.")
    retained = set(geometry["retained_scalp_channels"])
    for recorded, span in zip(recorded_spans, expected_spans):
        condition = span["condition_label"]
        union = set(global_bads) | set(expected[condition])
        if (not isinstance(recorded, Mapping) or not union.issubset(retained)
                or recorded.get("condition_label") != condition
                or recorded.get("occurrence_key") != str(span.get("occurrence_key") or "")
                or recorded.get("requested_channels") != expected[condition]
                or not isinstance(recorded.get("interpolated_channels"), list)
                or set(recorded["interpolated_channels"]) != union
                or recorded.get("target_coordinates") != span.get("target_coordinates")
                or recorded.get("source_coordinates") != span.get("source_coordinates")
                or recorded.get("span_fingerprint") != str(span.get("fingerprint") or "")):
            raise ValueError("Completed condition interpolation has invalid occurrence repair evidence.")
    return dict(value)


def condition_interpolation_export_provenance(settings: Mapping[str, Any], condition: str) -> dict[str, Any]:
    provenance = settings.get("_fpvs_condition_interpolation_provenance")
    if not isinstance(provenance, Mapping) or provenance.get("status") != "completed":
        return {}
    if condition not in provenance.get("requests", {}):
        return {}
    return {
        "version": CONDITION_INTERPOLATION_VERSION,
        "status": "completed",
        "fingerprint": provenance["fingerprint"],
        "requested_channels": list(provenance["requests"][condition]),
        "recording_wide_interpolated_channels": list(provenance["recording_wide_interpolated_channels"]),
        "interpolated_channels": sorted(set(provenance["recording_wide_interpolated_channels"]) | set(provenance["requests"][condition])),
        "analysis_span_fingerprint": provenance["analysis_span_fingerprint"],
        "spans": [dict(span) for span in provenance["spans"] if span["condition_label"] == condition],
    }
