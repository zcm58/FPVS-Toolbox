"""Group overlapping QC review windows without changing detector evidence.

Groups are presentation intervals, not artifact events or independent votes.
Whole-occurrence summaries never connect otherwise separate transient windows.
Every input finding retains its original index, including duplicate findings and
findings covering more than one disjoint episode. This module has no GUI or I/O.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
import math
from typing import Protocol


class EpisodeFinding(Protocol):
    recording_key: tuple[str, ...]
    source_path: str
    condition: str
    occurrence: str
    time_spans_s: tuple[tuple[float, float], ...]
    time_scope: str


@dataclass(frozen=True)
class QcReviewEpisode:
    recording_key: tuple[str, ...]
    source_path: str
    condition: str
    occurrence: str
    item_indices: tuple[int, ...]
    time_spans_s: tuple[tuple[float, float], ...] = ()
    time_scope: str = "unlocalized"

    @property
    def start_seconds(self) -> float | None:
        return self.time_spans_s[0][0] if self.time_spans_s else None

    @property
    def end_seconds(self) -> float | None:
        return self.time_spans_s[-1][1] if self.time_spans_s else None

    @property
    def title(self) -> str:
        if self.time_scope == "diagnostic_windows" and self.time_spans_s:
            return f"Review episode · {self.start_seconds:g}–{self.end_seconds:g} s"
        if self.time_scope == "occurrence" and self.time_spans_s:
            return f"Occurrence summary · {self.start_seconds:g}–{self.end_seconds:g} s"
        return "Finding without a localized interval"

    @property
    def timing_note(self) -> str:
        if self.time_scope == "diagnostic_windows":
            return (
                "Times are flagged review-interval coverage from recording start, "
                "not validated artifact duration. Linked findings may describe the "
                "same signal; they are not independent confirmations."
            )
        if self.time_scope == "occurrence":
            return (
                "Times identify the full analyzed occurrence from recording start. "
                "These findings do not locate an artifact within that occurrence."
            )
        return "No localized interval is available for this finding."


def _valid_spans(value: object) -> tuple[tuple[float, float], ...]:
    """Keep unknown or malformed time evidence visible without inventing bounds."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    spans = []
    for span in value:
        if not isinstance(span, Sequence) or isinstance(span, (str, bytes)) or len(span) != 2:
            return ()
        try:
            if any(isinstance(item, bool) for item in span):
                return ()
            start, stop = (float(item) for item in span)
        except (TypeError, ValueError, OverflowError):
            return ()
        if not math.isfinite(start) or not math.isfinite(stop) or not 0 <= start < stop:
            return ()
        spans.append((start, stop))
    return tuple(sorted(set(spans)))


def group_review_episodes(items: Sequence[EpisodeFinding]) -> tuple[QcReviewEpisode, ...]:
    """Connect overlapping half-open windows within one recording/occurrence.

    Adjacent or disjoint windows stay separate. One aggregate finding can link
    to multiple episodes; consumers should count unique input indices rather
    than treating each appearance as another finding.
    """
    localized: OrderedDict[tuple, list[tuple[float, float, int]]] = OrderedDict()
    occurrences: OrderedDict[tuple, list[int]] = OrderedDict()
    episodes: list[QcReviewEpisode] = []
    for index, item in enumerate(items):
        spans = _valid_spans(item.time_spans_s)
        key = (item.recording_key, item.source_path, item.condition, item.occurrence)
        if spans and item.time_scope == "diagnostic_windows":
            localized.setdefault(key, []).extend((start, stop, index) for start, stop in spans)
        elif spans and item.time_scope == "occurrence":
            occurrences.setdefault((*key, spans), []).append(index)
        else:
            episodes.append(QcReviewEpisode(*key, (index,)))

    for (recording_key, source_path, condition, occurrence, spans), indices in occurrences.items():
        episodes.append(QcReviewEpisode(
            recording_key, source_path, condition, occurrence, tuple(indices), spans, "occurrence",
        ))

    for key, windows in localized.items():
        start = stop = None
        indices: set[int] = set()
        for window_start, window_stop, index in sorted(windows):
            if stop is not None and window_start >= stop:
                episodes.append(QcReviewEpisode(
                    *key, tuple(sorted(indices)), ((start, stop),), "diagnostic_windows",
                ))
                start = stop = None
                indices = set()
            start = window_start if start is None else start
            stop = window_stop if stop is None else max(stop, window_stop)
            indices.add(index)
        if stop is not None:
            episodes.append(QcReviewEpisode(
                *key, tuple(sorted(indices)), ((start, stop),), "diagnostic_windows",
            ))
    return tuple(sorted(episodes, key=lambda episode: (
        min(episode.item_indices),
        episode.start_seconds if episode.start_seconds is not None else float("inf"),
    )))


__all__ = ["QcReviewEpisode", "group_review_episodes"]
