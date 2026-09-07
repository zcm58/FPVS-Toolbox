"""Presentation metadata for signal-review items; original evidence stays intact."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from functools import cached_property
import json
import math


@dataclass(frozen=True)
class SignalReviewItem:
    """Pair a complete workbook row with concise, structured display fields."""

    export_row: tuple[str, ...]
    kind: str
    title: str
    condition: str = ""
    occurrence: str = ""
    channels: str = ""
    source_path: str = ""
    time_spans_s: tuple[tuple[float, float], ...] = ()
    time_scope: str = "unlocalized"
    evidence: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if len(self.export_row) not in (4, 7):
            raise ValueError("Signal review rows require four or seven columns.")
        if self.evidence is not None:
            object.__setattr__(self, "evidence", deepcopy(dict(self.evidence)))

    @property
    def participant(self) -> str:
        return self.export_row[0]

    @property
    def recording(self) -> str:
        return self.export_row[1] if len(self.export_row) == 7 else ""

    @property
    def session(self) -> str:
        return self.export_row[2] if len(self.export_row) == 7 else ""

    @property
    def visit(self) -> str:
        return self.export_row[3] if len(self.export_row) == 7 else ""

    @property
    def group(self) -> str:
        return self.export_row[-3]

    @property
    def source_file(self) -> str:
        return self.export_row[-2]

    @property
    def details(self) -> str:
        return self.export_row[-1]

    @property
    def recording_key(self) -> tuple[str, ...]:
        return (*self.export_row[:-1], self.source_path) if self.source_path else self.export_row[:-1]

    @property
    def recording_label(self) -> str:
        parts = [self.participant, self.group, self.source_file]
        if self.recording:
            parts.extend((self.recording, f"{self.session} / visit {self.visit}"))
        return " · ".join(parts)

    @cached_property
    def evidence_text(self) -> str:
        if not self.evidence:
            return self.details
        return self.details + "\n\nStructured source evidence:\n" + json.dumps(
            dict(self.evidence), indent=2, ensure_ascii=False, default=str,
        )

    @cached_property
    def search_text(self) -> str:
        return " ".join(
            (*self.export_row, self.kind, self.title, self.condition,
             self.occurrence, self.channels, self.source_path, self.evidence_text)
        ).casefold()


def review_time_scope(
    finding: Mapping[str, object],
    event_plan: Mapping[str, object] | None,
) -> tuple[tuple[tuple[float, float], ...], str]:
    """Convert explicit source-sample evidence to recording-relative seconds.

    A complete source timebase is required. Durations, occurrence labels and
    diagnostic-window counts cannot establish a time interval by themselves.
    """
    if not isinstance(event_plan, Mapping):
        return (), "unlocalized"
    try:
        sfreq = float(event_plan["sfreq"])
        first_samp = _sample_index(event_plan["first_samp"])
        n_times = _sample_index(event_plan["n_times"])
        if (isinstance(event_plan["sfreq"], bool) or not math.isfinite(sfreq)
                or sfreq <= 0 or first_samp < 0 or n_times <= 0):
            return (), "unlocalized"
        if "flagged_window_union_spans" in finding:
            sample_spans = finding["flagged_window_union_spans"]
            scope = "diagnostic_windows"
        else:
            sample_spans = ((finding["start_sample"], finding["stop_sample"]),)
            scope = "occurrence"
        if (not isinstance(sample_spans, Sequence)
                or isinstance(sample_spans, (str, bytes)) or not sample_spans):
            return (), "unlocalized"
        spans = []
        for span in sample_spans:
            if not isinstance(span, Sequence) or isinstance(span, (str, bytes)) or len(span) != 2:
                return (), "unlocalized"
            start, stop = (_sample_index(value) for value in span)
            if not first_samp <= start < stop <= first_samp + n_times:
                return (), "unlocalized"
            spans.append(((start - first_samp) / sfreq, (stop - first_samp) / sfreq))
        return tuple(sorted(set(spans))), scope
    except (KeyError, TypeError, ValueError, OverflowError):
        return (), "unlocalized"


def _sample_index(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("Source-sample indices must be integers.")
    integer = int(value)
    if integer != float(value):
        raise ValueError("Source-sample indices must be integers.")
    return integer


def episode_view_context(
    episode: object,
    event_plan: Mapping[str, object] | None,
) -> tuple[tuple[tuple[float, float], ...], tuple[str, ...], float | None, int]:
    """Open an episode in its uniquely identified analyzed occurrence.

    Episode intervals already use seconds from source recording start. Only an
    explicit source timebase and one containing event-plan span may expand that
    view. Otherwise the original intervals remain labelled as review intervals.
    """
    try:
        raw_spans = getattr(episode, "time_spans_s", ())
        if not isinstance(raw_spans, Sequence) or isinstance(raw_spans, (str, bytes)):
            return (), (), None, 0
        spans = []
        for span in raw_spans:
            if not isinstance(span, Sequence) or isinstance(span, (str, bytes)) or len(span) != 2:
                return (), (), None, 0
            start, stop = (float(value) for value in span)
            if (any(isinstance(value, bool) for value in span)
                    or not math.isfinite(start) or not math.isfinite(stop)
                    or not 0 <= start < stop):
                return (), (), None, 0
            spans.append((start, stop))
    except (TypeError, ValueError, OverflowError):
        return (), (), None, 0
    intervals = tuple(spans)
    fallback = (
        intervals, tuple(f"Review interval {index + 1}" for index in range(len(intervals))),
        intervals[0][0] if intervals else None, 0,
    )
    if not intervals or not isinstance(event_plan, Mapping):
        return fallback
    event_spans = event_plan.get("spans", ())
    if not isinstance(event_spans, Sequence) or isinstance(event_spans, (str, bytes)):
        return fallback
    condition = str(getattr(episode, "condition", "") or "").strip()
    occurrence = getattr(episode, "occurrence", "")
    try:
        occurrence_index = None if occurrence in (None, "") else _sample_index(occurrence) - 1
        if occurrence_index is not None and occurrence_index < 0:
            return fallback
    except (TypeError, ValueError, OverflowError):
        return fallback

    matches = []
    for span in event_spans:
        if not isinstance(span, Mapping):
            continue
        span_condition = str(span.get("condition_label") or "").strip()
        if not span_condition or (condition and span_condition != condition):
            continue
        try:
            repetition = _sample_index(span.get("repetition_index"))
        except (TypeError, ValueError, OverflowError):
            continue
        if repetition < 0 or (occurrence_index is not None and repetition != occurrence_index):
            continue
        bounds, _scope = review_time_scope({
            "start_sample": span.get("time_start_sample"),
            "stop_sample": span.get("time_stop_sample"),
        }, event_plan)
        if len(bounds) != 1:
            continue
        start, stop = bounds[0]
        if all(start <= interval_start < interval_stop <= stop for interval_start, interval_stop in intervals):
            matches.append((bounds, f"{span_condition} · occurrence {repetition + 1}"))
    if len(matches) != 1:
        return fallback
    bounds, label = matches[0]
    start_seconds = max(bounds[0][0], min(start for start, _stop in intervals) - 1.0)
    return bounds, (label,), start_seconds, 0
