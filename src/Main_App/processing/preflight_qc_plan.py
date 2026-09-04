"""Condition-aware sample planning for preflight EEG quality checks."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
import hashlib
from typing import Any

import numpy as np

from Main_App.Shared.fft_crop_utils import (
    compute_fft_crop_from_events,
    plan_condition_fft_spans,
    resolve_oddball_ids_by_condition,
)

PREFLIGHT_QC_METHOD_NAME = "condition_aware_preflight_qc"
PREFLIGHT_QC_METHOD_VERSION = "v4_biosemi64_geometry"
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
    event_count: int
    event_digest: str
    n_step: int | None
    spans: tuple[ConditionQcSpan, ...]
    warnings: tuple[str, ...] = ()

    @property
    def condition_count(self) -> int:
        return len(self.spans)

    def to_payload(self) -> dict[str, Any]:
        return {
            "sfreq": float(self.sfreq),
            "n_times": int(self.n_times),
            "event_count": int(self.event_count),
            "event_digest": self.event_digest,
            "n_step": self.n_step,
            "spans": [span.to_payload() for span in self.spans],
            "warnings": list(self.warnings),
        }


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
) -> PreflightQcEventPlan:
    """Plan every relevant condition interval without reading EEG data.

    Time-domain and spectral QC both use the exact shared, marker-derived,
    integer-oddball-cycle FFT crop that normal processing will analyze. A
    present condition with no valid locked crop is an explicit planning error;
    preflight QC must not substitute an onset-based or fixed-duration interval.
    """

    sample_rate = float(sfreq)
    sample_count = int(n_times)
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

    oddball_ids = resolve_oddball_ids_by_condition(
        events=normalized_events,
        onset_ids=onset_ids,
        stream_end_sample=sample_count,
    )
    crop_results, n_step, crop_warnings = compute_fft_crop_from_events(
        events=normalized_events,
        fs=sample_rate,
        onset_ids=onset_ids,
        oddball_id=oddball_ids,
        stream_end_sample=sample_count,
    )

    warnings = list(crop_warnings)
    if not n_step:
        details = "; ".join(crop_warnings) or "unknown"
        raise ValueError(
            "Locked FFT crop required for preflight QC but no valid N_step is "
            f"available: {details}. Fixed-duration fallback is disabled."
        )

    spectral_by_key: dict[tuple[int, int], tuple[int, int]] = {}
    for condition_id in sorted(present_onset_ids):
        span_plan = plan_condition_fft_spans(
            crop_results=crop_results,
            condition_id=condition_id,
            n_step=n_step,
        )
        condition_label = labels_by_code[condition_id][0]
        if span_plan.fallback_repetition_reasons:
            raise ValueError(
                "Locked FFT crop required for preflight QC but one or more "
                f"repetitions could not be cropped on-bin for condition="
                f"{condition_label}: "
                f"{'; '.join(span_plan.fallback_repetition_reasons)}. "
                "Fixed-duration fallback is disabled."
            )
        if span_plan.n_common is None:
            raise ValueError(
                "Locked FFT crop required for preflight QC but no common on-bin "
                f"length could be computed for condition={condition_label}. "
                "Fixed-duration fallback is disabled."
            )
        if int(span_plan.n_common) % int(n_step) != 0:
            raise ValueError(
                "Locked FFT crop invariant failed during preflight planning: "
                f"N_common={span_plan.n_common}, N_step={n_step}, "
                f"condition={condition_label}."
            )
        for key, spectral_span in zip(
            span_plan.repetition_keys,
            span_plan.repetition_spans,
            strict=True,
        ):
            spectral_by_key[key] = (int(spectral_span[0]), int(spectral_span[1]))

    repetition_counts: dict[int, int] = defaultdict(int)
    planned_spans: list[ConditionQcSpan] = []
    for onset_row in onset_rows:
        onset_sample = max(0, int(onset_row[0]))
        condition_id = int(onset_row[2])
        repetition_index = repetition_counts[condition_id]
        repetition_counts[condition_id] += 1
        key = (condition_id, repetition_index)
        crop = crop_results.get(key)
        spectral_span = spectral_by_key.get(key)
        if crop is None or spectral_span is None:
            raise ValueError(
                "Locked FFT crop planning produced no span for a present condition: "
                f"condition={labels_by_code[condition_id][0]}, "
                f"rep={repetition_index}."
            )
        spectral_start, spectral_stop = spectral_span
        if (
            spectral_start < onset_sample
            or spectral_stop > sample_count
            or spectral_stop <= spectral_start
        ):
            raise ValueError(
                "Locked FFT crop bounds are invalid for preflight QC: "
                f"condition={labels_by_code[condition_id][0]}, "
                f"rep={repetition_index}, onset={onset_sample}, "
                f"start={spectral_start}, stop={spectral_stop}, "
                f"n_times={sample_count}."
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
                oddball_id=(int(crop.oddball_id) if crop and crop.oddball_id else None),
                last_oddball_sample=(
                    int(crop.last55_sample)
                    if crop is not None and crop.last55_sample is not None
                    else None
                ),
                spectral_fallback_reason=None,
            )
        )

    missing_codes = sorted(onset_ids - set(repetition_counts))
    warnings.extend(f"condition={code}:missing_onset" for code in missing_codes)
    return PreflightQcEventPlan(
        sfreq=sample_rate,
        n_times=sample_count,
        event_count=int(len(normalized_events)),
        event_digest=_event_digest(normalized_events),
        n_step=n_step,
        spans=tuple(planned_spans),
        warnings=tuple(dict.fromkeys(warnings)),
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
