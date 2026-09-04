"""Condition-aware sample planning for preflight EEG quality checks."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
import hashlib
from typing import Any

import numpy as np

from Main_App.Shared.fft_crop_utils import compute_onbin_step
from Main_App.processing.analysis_spans import (
    attach_source_analysis_span_plan,
    canonical_condition_event_map,
)
from Main_App.processing.marker_integrity import (
    ApprovedOccurrenceSpan,
    MarkerReviewDecision,
    apply_marker_review_decision,
    approve_clean_occurrence,
    build_marker_integrity_plan,
)
from Main_App.projects.frequency_protocol import FrequencyProtocol

PREFLIGHT_QC_METHOD_NAME = "condition_aware_preflight_qc"
PREFLIGHT_QC_METHOD_VERSION = "v5_analyzed_interval_coordinates"
PREFLIGHT_QC_BLOCK_DURATION_S = 10.0
PREFLIGHT_QC_MAX_WORKERS = 4
PREFLIGHT_QC_MAX_IO_READERS = 2
PREFLIGHT_QC_MAX_SPECTRAL_WORKERS = 2
PREFLIGHT_QC_MAX_IN_MEMORY_CONDITION_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class ConditionQcSpan:
    """Time-domain and locked on-bin spectral spans for one condition occurrence."""

    condition_label: str
    condition_id: int
    repetition_index: int
    onset_sample: int
    time_start_sample: int
    time_stop_sample: int
    spectral_start_sample: int | None
    spectral_stop_sample: int | None
    oddball_id: int | None
    last_oddball_sample: int | None
    spectral_fallback_reason: str | None = None
    marker_plan_fingerprint: str | None = None
    approved_span_fingerprint: str | None = None
    marker_disposition: str | None = None

    @property
    def time_sample_count(self) -> int:
        return max(0, int(self.time_stop_sample) - int(self.time_start_sample))

    @property
    def spectral_sample_count(self) -> int:
        if self.spectral_start_sample is None or self.spectral_stop_sample is None:
            return 0
        return max(
            0,
            int(self.spectral_stop_sample) - int(self.spectral_start_sample),
        )

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreflightQcEventPlan:
    """Deterministic condition plan derived from one recording's event stream."""

    sfreq: float
    n_times: int
    first_samp: int
    event_count: int
    event_digest: str
    n_step: int | None
    spans: tuple[ConditionQcSpan, ...]
    condition_event_map: Mapping[str, int]
    warnings: tuple[str, ...] = ()
    marker_integrity_plan: Mapping[str, Any] | None = None
    approved_occurrences: tuple[Mapping[str, Any], ...] = ()
    unresolved_occurrences: tuple[Mapping[str, Any], ...] = ()

    @property
    def condition_count(self) -> int:
        return len(self.spans)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "sfreq": float(self.sfreq),
            "n_times": int(self.n_times),
            "first_samp": int(self.first_samp),
            "event_count": int(self.event_count),
            "event_digest": self.event_digest,
            "n_step": self.n_step,
            "spans": [span.to_payload() for span in self.spans],
            "condition_event_map": {
                str(label): int(code)
                for label, code in self.condition_event_map.items()
            },
            "warnings": list(self.warnings),
            "marker_integrity_plan": (
                dict(self.marker_integrity_plan)
                if self.marker_integrity_plan is not None
                else None
            ),
            "approved_occurrences": [
                dict(item) for item in self.approved_occurrences
            ],
            "unresolved_occurrences": [
                dict(item) for item in self.unresolved_occurrences
            ],
        }
        return attach_source_analysis_span_plan(payload)


def _normalized_events(events: np.ndarray) -> np.ndarray:
    array = np.asarray(events)
    if array.size == 0:
        return np.empty((0, 3), dtype=np.int64)
    if array.ndim != 2 or array.shape[1] < 3:
        raise ValueError("events must have shape (n_events, 3)")
    normalized = np.asarray(array[:, :3], dtype=np.int64)
    order = np.argsort(normalized[:, 0], kind="stable")
    return np.ascontiguousarray(normalized[order])


def _event_digest(events: np.ndarray) -> str:
    relevant = np.ascontiguousarray(events[:, (0, 2)], dtype="<i8")
    return hashlib.sha256(relevant.tobytes()).hexdigest()


def plan_preflight_qc_events(
    *,
    events: np.ndarray,
    event_map: Mapping[str, int],
    sfreq: float,
    n_times: int,
    first_samp: int = 0,
    frequency_protocol: FrequencyProtocol,
    marker_review_decisions: Mapping[str, Mapping[str, Any]] | None = None,
    marker_review_scope: Mapping[str, Any] | None = None,
) -> PreflightQcEventPlan:
    """Plan every relevant condition interval without reading EEG data.

    Time-domain and spectral QC both use the exact shared, marker-derived,
    integer-oddball-cycle FFT crop that normal processing will analyze. A
    present condition with no valid locked crop is an explicit planning error;
    preflight QC must not substitute an onset-based or fixed-duration interval.
    """

    sample_rate = float(sfreq)
    sample_count = int(n_times)
    sample_origin = int(first_samp)
    recording_stop = sample_origin + sample_count
    if not np.isfinite(sample_rate) or sample_rate <= 0.0:
        raise ValueError("sfreq must be a positive finite value")
    if sample_count <= 0:
        raise ValueError("n_times must be positive")

    labels_by_code: dict[int, list[str]] = defaultdict(list)
    for label, value in event_map.items():
        clean_label = str(label).strip()
        if not clean_label:
            continue
        labels_by_code[int(value)].append(clean_label)
    if not labels_by_code:
        raise ValueError(
            "A non-empty condition event map is required for preflight QC v4."
        )

    normalized_events = _normalized_events(events)
    onset_ids = set(labels_by_code)
    onset_rows = [row for row in normalized_events if int(row[2]) in onset_ids]
    if not onset_rows:
        raise ValueError("No configured condition onset events were found in the recording.")
    present_onset_ids = {int(row[2]) for row in onset_rows}

    marker_plan = build_marker_integrity_plan(
        events=normalized_events,
        event_map=event_map,
        sampling_rate_hz=sample_rate,
        n_times=sample_count,
        first_samp=sample_origin,
        protocol=frequency_protocol,
    )
    _, n_step, step_error = compute_onbin_step(
        fs=sample_rate,
        f_oddball=frequency_protocol.oddball_rate_hz,
    )
    warnings: list[str] = []
    if step_error:
        warnings.append(step_error)
    if not n_step:
        details = "; ".join(warnings) or "unknown"
        raise ValueError(
            "Locked FFT crop required for preflight QC but no valid N_step is "
            f"available: {details}. Fixed-duration fallback is disabled."
        )
    decisions = marker_review_decisions or {}
    approved_by_key: dict[str, ApprovedOccurrenceSpan] = {}
    unresolved_payloads: list[Mapping[str, Any]] = []
    for occurrence in marker_plan.occurrences:
        if occurrence.requires_review:
            raw_decision = decisions.get(occurrence.occurrence_key)
            if raw_decision is None:
                unresolved_payloads.append(occurrence.to_payload())
                continue
            approved = apply_marker_review_decision(
                occurrence,
                MarkerReviewDecision.from_payload(raw_decision),
                marker_plan_fingerprint=marker_plan.fingerprint,
                review_scope=marker_review_scope or {},
            )
        else:
            approved = approve_clean_occurrence(occurrence)
        approved_by_key[occurrence.occurrence_key] = approved

    planned_spans: list[ConditionQcSpan] = []
    for occurrence in marker_plan.occurrences:
        approved = approved_by_key.get(occurrence.occurrence_key)
        if approved is None or approved.is_excluded:
            continue
        onset_sample = occurrence.onset_sample
        condition_id = occurrence.condition_code
        repetition_index = occurrence.repetition_index
        if approved.start_sample is None or approved.stop_sample is None:
            raise ValueError(
                "Approved marker occurrence did not provide an analysis span."
            )
        spectral_start = int(approved.start_sample)
        spectral_stop = int(approved.stop_sample)
        if (
            spectral_start < onset_sample
            or spectral_start < sample_origin
            or spectral_stop > recording_stop
            or spectral_stop <= spectral_start
        ):
            raise ValueError(
                "Locked FFT crop bounds are invalid for preflight QC: "
                f"condition={labels_by_code[condition_id][0]}, "
                f"rep={repetition_index}, onset={onset_sample}, "
                f"start={spectral_start}, stop={spectral_stop}, "
                f"first_samp={sample_origin}, n_times={sample_count}."
            )

        labels = labels_by_code[condition_id]
        if len(labels) > 1:
            warnings.append(
                f"condition={condition_id}:duplicate_labels={','.join(labels)}"
            )
        planned_spans.append(
            ConditionQcSpan(
                condition_label=labels[0],
                condition_id=condition_id,
                repetition_index=repetition_index,
                onset_sample=onset_sample,
                time_start_sample=spectral_start,
                time_stop_sample=spectral_stop,
                spectral_start_sample=spectral_start,
                spectral_stop_sample=spectral_stop,
                oddball_id=int(occurrence.oddball_marker_code),
                last_oddball_sample=(
                    int(occurrence.retained_marker_samples[-1])
                    if occurrence.retained_marker_samples
                    else None
                ),
                spectral_fallback_reason=None,
                marker_plan_fingerprint=occurrence.fingerprint,
                approved_span_fingerprint=approved.fingerprint,
                marker_disposition=approved.disposition,
            )
        )

    missing_codes = sorted(onset_ids - present_onset_ids)
    warnings.extend(f"condition={code}:missing_onset" for code in missing_codes)
    return PreflightQcEventPlan(
        sfreq=sample_rate,
        n_times=sample_count,
        first_samp=sample_origin,
        event_count=int(len(normalized_events)),
        event_digest=_event_digest(normalized_events),
        n_step=n_step,
        spans=tuple(planned_spans),
        condition_event_map=canonical_condition_event_map(event_map),
        warnings=tuple(dict.fromkeys(warnings)),
        marker_integrity_plan=marker_plan.to_payload(),
        approved_occurrences=tuple(
            approved.to_payload()
            for approved in approved_by_key.values()
        ),
        unresolved_occurrences=tuple(unresolved_payloads),
    )


def resolve_preflight_spectral_bounds(
    settings: Mapping[str, Any],
    *,
    source_sfreq: float,
) -> tuple[float, float]:
    """Return the configured retained spectral range for preflight review.

    The configured downsample target contributes only its Nyquist bound. This
    helper never resamples data and does not alter the processing target.
    """

    source_nyquist = float(source_sfreq) / 2.0
    target_rate = settings.get("downsample_rate", settings.get("downsample", 256))
    try:
        target_rate_value = float(target_rate)
    except (TypeError, ValueError):
        target_rate_value = 256.0
    target_nyquist = (
        target_rate_value / 2.0
        if np.isfinite(target_rate_value) and target_rate_value > 0.0
        else source_nyquist
    )

    low_pass = settings.get("low_pass")
    try:
        configured_upper = float(low_pass) if low_pass is not None else source_nyquist
    except (TypeError, ValueError):
        configured_upper = source_nyquist
    if not np.isfinite(configured_upper) or configured_upper <= 0.0:
        configured_upper = source_nyquist

    high_pass = settings.get("high_pass", 0.0)
    try:
        configured_lower = float(high_pass)
    except (TypeError, ValueError):
        configured_lower = 0.0
    if not np.isfinite(configured_lower) or configured_lower < 0.0:
        configured_lower = 0.0

    upper = min(source_nyquist, target_nyquist, configured_upper)
    lower = min(max(0.0, configured_lower), upper)
    return lower, upper


__all__ = [
    "ConditionQcSpan",
    "PREFLIGHT_QC_BLOCK_DURATION_S",
    "PREFLIGHT_QC_MAX_IO_READERS",
    "PREFLIGHT_QC_MAX_IN_MEMORY_CONDITION_BYTES",
    "PREFLIGHT_QC_MAX_SPECTRAL_WORKERS",
    "PREFLIGHT_QC_MAX_WORKERS",
    "PREFLIGHT_QC_METHOD_NAME",
    "PREFLIGHT_QC_METHOD_VERSION",
    "PreflightQcEventPlan",
    "plan_preflight_qc_events",
    "resolve_preflight_spectral_bounds",
]
