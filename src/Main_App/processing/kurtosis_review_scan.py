"""Synchronous, GUI-neutral orchestration for QC-16 manual review evidence.

The scanner is intentionally suitable for invocation from a ``QThread``: it
does no widget work, reports progress through a callback, and cooperatively
checks a cancellation callback between file-level stages.  Numerical evidence
remains owned by :func:`prepare_kurtosis_review_evidence`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
import logging
import math
import os
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event
from time import perf_counter
from typing import TYPE_CHECKING, Any

import mne
import numpy as np
import psutil

if TYPE_CHECKING:
    from Main_App.processing.qc_source_prefetch import QcSourcePrefetch

from Main_App.Performance.mp_env import compute_effective_max_workers
from Main_App.io import load_utils
from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    BIOSEMI64_MONTAGE_ID,
    validate_raw_biosemi64_geometry,
)
from Main_App.processing.analysis_spans import (
    relative_spans_from_plan,
    restrict_source_analysis_span_plan_by_condition,
    validate_source_analysis_span_context,
    validate_source_analysis_span_plan,
)
from Main_App.processing.kurtosis_qc import (
    CHANNEL_DECISION_REVIEW_REQUIRED,
    KurtosisQCError,
    validate_kurtosis_review_decision_payload,
)
from Main_App.processing.preprocess import prepare_kurtosis_review_evidence
from Main_App.processing.raw_channel_qc import evaluate_raw_channel_qc
from Main_App.processing.removed_electrode_detection import (
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
    manual_removed_electrodes_for_recording,
    normalize_removed_electrode_detection_mode,
)
from Main_App.projects import (
    is_participant_condition_excluded,
    is_recording_condition_excluded,
    normalize_frequency_protocol,
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_participants,
    normalize_manual_excluded_recording_conditions,
    normalize_manual_excluded_recordings,
)

logger = logging.getLogger(__name__)

KURTOSIS_REVIEW_FILE_STATUS_CLEAR = "complete_no_review"
KURTOSIS_REVIEW_FILE_STATUS_REVIEW_REQUIRED = "review_required"
KURTOSIS_REVIEW_FILE_STATUS_SKIPPED = "skipped"
KURTOSIS_REVIEW_FILE_STATUS_ERROR = "error"

KURTOSIS_REVIEW_SKIP_RECORDING_EXCLUDED = "recording_excluded"
KURTOSIS_REVIEW_SKIP_ALL_CONDITIONS_EXCLUDED = "all_analyzed_conditions_excluded"
KURTOSIS_REVIEW_SKIP_RAW_QC_EXCLUDED = "raw_channel_qc_excluded"

KURTOSIS_REVIEW_PENDING_NEW = "new"
KURTOSIS_REVIEW_PENDING_STALE = "stale"

ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]


class KurtosisReviewScanError(ValueError):
    """Raised when the batch-level scan contract is invalid."""


@dataclass(frozen=True, slots=True)
class KurtosisAnalyzedOccurrence:
    """One analyzed condition occurrence represented by QC-16 evidence."""

    condition_label: str
    repetition_index: int
    occurrence_key: str


@dataclass(frozen=True, slots=True)
class KurtosisCorroboratorState:
    """Presentation-safe summary of one approved-registry assessment."""

    method_id: str
    method_version: str
    authority: str
    eligible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class KurtosisReviewItem:
    """One electrode whose current QC-16 evidence requires explicit review."""

    path: Path
    participant_id: str
    recording_id: str
    session_id: str | None
    session_label: str | None
    visit_index: int | None
    channel: str
    analyzed_conditions: tuple[str, ...]
    analyzed_occurrences: tuple[KurtosisAnalyzedOccurrence, ...]
    raw_kurtosis: float | None
    signed_normalized_score: float | None
    threshold: float
    validity: str
    validity_reason: str | None
    corroborator_registry_version: str
    corroborator_states: tuple[KurtosisCorroboratorState, ...]
    display_only_channel_health: tuple[str, ...]
    signal_unit: str
    signal_source_sample_count: int
    signal_preview: tuple[float | None, ...]
    evidence: Mapping[str, object]
    review_status: str = KURTOSIS_REVIEW_PENDING_NEW
    signal_view: Mapping[str, object] = field(default_factory=dict)
    review_diagnostics: Mapping[str, object] = field(default_factory=dict)

    @property
    def review_scope(self) -> dict[str, object]:
        """Return the exact recording identity consumed by receipt validation."""

        return {
            "source_file_path": str(self.path.resolve()),
            "participant_id": self.participant_id,
            "recording_id": self.recording_id,
            "session_id": self.session_id,
            "session_label": self.session_label,
        }

    @property
    def occurrence_summary(self) -> str:
        """Format analyzed conditions and occurrence indices without losing scope."""

        repetitions_by_condition: dict[str, list[int]] = {}
        for occurrence in self.analyzed_occurrences:
            repetitions_by_condition.setdefault(occurrence.condition_label, []).append(occurrence.repetition_index + 1)
        parts: list[str] = []
        for condition in self.analyzed_conditions:
            repetitions = repetitions_by_condition.get(condition, [])
            label = "occurrence" if len(repetitions) == 1 else "occurrences"
            values = ", ".join(str(value) for value in repetitions)
            parts.append(f"{condition} ({label} {values})")
        return "; ".join(parts)

    @property
    def corroborator_summary(self) -> str:
        """State whether an independently approved corroborator authorized repair."""

        approved = [state for state in self.corroborator_states if state.eligible]
        if approved:
            methods = ", ".join(f"{state.method_id} {state.method_version}" for state in approved)
            return f"Approved: {methods}"
        if not self.corroborator_states:
            return f"None approved ({self.corroborator_registry_version or 'registry unavailable'})"
        details = "; ".join(
            f"{state.method_id} {state.method_version}: {state.reason}" for state in self.corroborator_states
        )
        return f"None approved; {details}"

    @property
    def display_only_channel_health_summary(self) -> str:
        """Format other raw-channel findings without granting them authority."""

        diagnostic_rows = [event for event in self.review_diagnostics.get("localized_events", ())
                           if event.get("channel") == self.channel]
        extra = (f"{len(diagnostic_rows)} raw signal-pattern cue(s); open Inspect signal for exact timing. "
                 "Provisional review only, not an approved corroborator.") if diagnostic_rows else ""
        if not self.display_only_channel_health:
            return extra or "None reported"
        return "; ".join((*self.display_only_channel_health, extra) if extra else self.display_only_channel_health) + " — review-only; not an approved corroborator"


@dataclass(frozen=True, slots=True)
class KurtosisReviewFileResult:
    """Truthful scan result for one requested raw recording."""

    path: Path
    participant_id: str
    recording_id: str
    session_id: str | None
    session_label: str | None
    visit_index: int | None
    status: str
    analyzed_conditions: tuple[str, ...] = ()
    review_items: tuple[KurtosisReviewItem, ...] = ()
    evidence: Mapping[str, object] | None = None
    decision_plan: Mapping[str, object] | None = None
    error: str | None = None
    skip_reason: str | None = None
    review_diagnostics: Mapping[str, object] = field(default_factory=dict)
    source_identity: Mapping[str, object] = field(default_factory=dict)

    @property
    def review_required_channels(self) -> tuple[str, ...]:
        return tuple(item.channel for item in self.review_items)


@dataclass(frozen=True, slots=True)
class KurtosisReviewProgress:
    """Separate completed eligible work from confirmed recording exclusions."""

    eligible_total: int
    completed_eligible: int
    excluded_count: int
    failed_count: int = 0


StatusProgressCallback = Callable[[KurtosisReviewProgress], None]


@dataclass(frozen=True, slots=True)
class KurtosisReviewScan:
    """Completed or cooperatively cancelled QC-16 review scan."""

    results: tuple[KurtosisReviewFileResult, ...]
    cancelled: bool = False

    @property
    def review_items(self) -> tuple[KurtosisReviewItem, ...]:
        return tuple(item for result in self.results for item in result.review_items)

    @property
    def errors(self) -> tuple[KurtosisReviewFileResult, ...]:
        return tuple(result for result in self.results if result.status == KURTOSIS_REVIEW_FILE_STATUS_ERROR)

    @property
    def can_continue(self) -> bool:
        """Return false until cancellation, errors, and pending reviews are resolved."""

        return not self.cancelled and not self.errors and not self.review_items


@dataclass(frozen=True, slots=True)
class KurtosisReviewDecisionReconciliation:
    """Current receipts and the remaining new or stale review findings."""

    scan: KurtosisReviewScan
    current_receipts: Mapping[str, Mapping[str, Mapping[str, object]]]
    pending_status_by_recording: Mapping[str, Mapping[str, str]]

    @property
    def pending_items(self) -> tuple[KurtosisReviewItem, ...]:
        return self.scan.review_items

    @property
    def processing_decisions_by_recording(
        self,
    ) -> dict[str, dict[str, dict[str, object]]]:
        """Return only receipts proven current for the evidence in this scan."""

        return {
            recording: {channel: dict(receipt) for channel, receipt in channels.items()}
            for recording, channels in self.current_receipts.items()
        }


class _LoaderLogAdapter:
    """Give the active loader its logging protocol without a GUI dependency."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def log(self, message: str) -> None:
        logger.debug(
            "kurtosis_review_loader file=%s message=%s",
            self._path.name,
            message,
        )


def _normalized_optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _log_scan_timing(path: Path, stage: str, started: float) -> None:
    logger.info(
        "kurtosis_review_timing file=%s stage=%s elapsed_ms=%.3f",
        path.name,
        stage,
        (perf_counter() - started) * 1_000.0,
    )


def _review_worker_count(raw_file_infos: Sequence[Any], max_workers: int | None) -> int:
    """Allow at most two full-recording jobs within a conservative RAM budget."""

    if len(raw_file_infos) < 2 or max_workers == 1:
        return 1
    try:
        paths = [Path(info.path) for info in raw_file_infos]
        # The active loader uses a per-process <stem>_raw.dat memmap. Equal
        # stems must never be loaded simultaneously, even from different dirs.
        if len({path.stem.casefold() for path in paths}) != len(paths):
            return 1
        memory = psutil.virtual_memory()
        cap = compute_effective_max_workers(int(memory.total), os.cpu_count() or 1, min(2, max_workers or 2))
        # Packed BDF samples expand into float64 arrays plus FIR/resampling
        # scratch arrays. Reserve 24x source bytes and at least 1 GiB per file;
        # leave half of currently available RAM for the GUI and other work.
        estimates = sorted(
            (max(1024**3, path.stat().st_size * 24) for path in paths),
            reverse=True,
        )
        if cap < 2 or sum(estimates[:2]) > int(memory.available) // 2:
            return 1
    except (AttributeError, OSError, TypeError, ValueError):
        return 1
    return 2


def _scan_review_parallel(
    raw_file_infos: Sequence[Any],
    settings: Mapping[str, Any],
    *,
    event_map: Mapping[str, int],
    reviewed_event_plans_by_file: Mapping[str, Any] | None,
    raw_channel_qc_by_recording: Mapping[str, Mapping[str, object]] | None,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
    max_workers: int,
    source_prefetch: QcSourcePrefetch | None = None,
    result_progress: Callable[[int, tuple[KurtosisReviewFileResult, ...]], None] | None = None,
) -> KurtosisReviewScan:
    """Run independent serial scans, relaying progress on the calling thread."""

    total = len(raw_file_infos)
    pending_index = 0
    completed = 0
    stop = Event()
    messages: SimpleQueue[str] = SimpleQueue()
    indexed_results: dict[int, tuple[KurtosisReviewFileResult, ...]] = {}
    futures = {}

    def submit_available(executor: ThreadPoolExecutor) -> None:
        nonlocal pending_index
        while not stop.is_set() and pending_index < total and len(futures) < max_workers:
            index = pending_index
            pending_index += 1
            futures[
                executor.submit(
                    _scan_kurtosis_review_serial,
                    [raw_file_infos[index]],
                    settings,
                    event_map=event_map,
                    reviewed_event_plans_by_file=reviewed_event_plans_by_file,
                    raw_channel_qc_by_recording=raw_channel_qc_by_recording,
                    progress=lambda message, _completed, _total: messages.put(message),
                    should_cancel=stop.is_set,
                    source_prefetch=source_prefetch,
                )
            ] = index

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fpvs_kurtosis_review") as executor:
        if should_cancel and should_cancel():
            stop.set()
        submit_available(executor)
        while futures:
            if should_cancel and should_cancel():
                stop.set()
            while True:
                try:
                    message = messages.get_nowait()
                except Empty:
                    break
                if progress:
                    progress(message, completed, total)
            done, _pending = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                index = futures.pop(future)
                scan = future.result()
                indexed_results[index] = scan.results
                if result_progress is not None:
                    result_progress(index, scan.results)
                if scan.cancelled:
                    stop.set()
                completed += len(scan.results)
                if progress and scan.results:
                    progress(f"Finished kurtosis review scan for {scan.results[0].path.name}", completed, total)
            submit_available(executor)
    if stop.is_set() and progress:
        progress("Kurtosis review scan cancelled", completed, total)
    return KurtosisReviewScan(
        tuple(result for index in sorted(indexed_results) for result in indexed_results[index]),
        cancelled=stop.is_set(),
    )


def _identity(info: Any) -> tuple[Path, str, str, str | None, str | None, int | None]:
    try:
        path = Path(info.path).resolve()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise KurtosisReviewScanError("Raw-file scan entry has an invalid path.") from exc
    participant_id = str(getattr(info, "subject_id", "") or "").strip()
    if not participant_id:
        raise KurtosisReviewScanError(f"Raw-file scan entry {path.name!r} has no participant identity.")
    recording_id = str(getattr(info, "recording_id", None) or participant_id).strip()
    if not recording_id:
        raise KurtosisReviewScanError(f"Raw-file scan entry {path.name!r} has no recording identity.")
    session_id = _normalized_optional_text(getattr(info, "session_id", None))
    session_label = _normalized_optional_text(getattr(info, "session_label", None))
    raw_visit = getattr(info, "visit_index", None)
    visit_index = int(raw_visit) if raw_visit is not None else None
    return path, participant_id, recording_id, session_id, session_label, visit_index


def _configured_reference_pair(settings: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(settings.get("ref_channel1") or settings.get("ref_chan1") or settings.get("ref_ch1") or "EXG1"),
        str(settings.get("ref_channel2") or settings.get("ref_chan2") or settings.get("ref_ch2") or "EXG2"),
    )


def _configured_stim_channel(settings: Mapping[str, Any]) -> str:
    return str(settings.get("stim_channel") or settings.get("stim") or "Status")


def _configured_channel_limit(settings: Mapping[str, Any]) -> int:
    raw_limit = settings.get("max_idx_keep")
    if raw_limit is None:
        raw_limit = settings.get("max_chan_idx_keep")
    if raw_limit is None:
        return len(BIOSEMI64_CHANNELS)
    if isinstance(raw_limit, bool):
        raise KurtosisReviewScanError("BioSemi64 channel limit must be an integer from 1 through 64.")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise KurtosisReviewScanError("BioSemi64 channel limit must be an integer from 1 through 64.") from exc
    if isinstance(raw_limit, float) and not raw_limit.is_integer():
        raise KurtosisReviewScanError("BioSemi64 channel limit must be an integer from 1 through 64.")
    if not 1 <= limit <= len(BIOSEMI64_CHANNELS):
        raise KurtosisReviewScanError("BioSemi64 channel limit must be an integer from 1 through 64.")
    return limit


def _event_plan_for_path(
    plans: Mapping[str, Any],
    path: Path,
) -> Mapping[str, Any]:
    matches: list[Mapping[str, Any]] = []
    target = str(path.resolve()).casefold()
    for raw_path, raw_plan in plans.items():
        try:
            candidate = str(Path(str(raw_path)).resolve()).casefold()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if candidate == target and isinstance(raw_plan, Mapping):
            matches.append(raw_plan)
    if len(matches) != 1:
        qualifier = "duplicate" if len(matches) > 1 else "no"
        raise KurtosisReviewScanError(f"There is {qualifier} reviewed event plan for {path.name}.")
    return matches[0]


def _find_raw_events(raw: Any, *, stim_channel: str) -> tuple[np.ndarray, str]:
    """Use the event-discovery behavior shared by preflight and final processing."""

    try:
        events = mne.find_events(
            raw,
            stim_channel=stim_channel,
            shortest_event=1,
            verbose=False,
        )
        source = "stim"
    except (RuntimeError, ValueError):
        events, _event_ids = mne.events_from_annotations(raw, verbose=False)
        source = "annotations"
    result = np.asarray(events, dtype=np.int64)
    if result.size == 0:
        raise KurtosisReviewScanError(f"No events found (source={source!r}, stim={stim_channel!r}).")
    return result, source


def _condition_labels(source_plan: Mapping[str, Any]) -> tuple[str, ...]:
    raw_spans = source_plan.get("spans")
    if not isinstance(raw_spans, Sequence) or isinstance(raw_spans, (str, bytes, bytearray)):
        raise KurtosisReviewScanError("Reviewed analysis spans are malformed.")
    labels: list[str] = []
    seen: set[str] = set()
    for raw_span in raw_spans:
        if not isinstance(raw_span, Mapping):
            raise KurtosisReviewScanError("Reviewed analysis span is malformed.")
        label = str(raw_span.get("condition_label") or "").strip()
        if not label:
            raise KurtosisReviewScanError("Reviewed analysis span has no condition label.")
        if label.casefold() not in seen:
            seen.add(label.casefold())
            labels.append(label)
    return tuple(labels)


def _optional_finite(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise KurtosisReviewScanError(f"{field_name} must be finite or unavailable.") from exc
    if not math.isfinite(result):
        raise KurtosisReviewScanError(f"{field_name} must be finite or unavailable.")
    return result


def _positive_finite(value: object, *, field_name: str) -> float:
    result = _optional_finite(value, field_name=field_name)
    if result is None or result <= 0.0:
        raise KurtosisReviewScanError(f"{field_name} must be positive and finite.")
    return result


def _occurrences(evidence: Mapping[str, object]) -> tuple[KurtosisAnalyzedOccurrence, ...]:
    scope = evidence.get("scoring_scope")
    if not isinstance(scope, Mapping):
        raise KurtosisReviewScanError("Kurtosis evidence has no analyzed scope.")
    raw_occurrences = scope.get("occurrences")
    if (
        not isinstance(raw_occurrences, Sequence)
        or isinstance(raw_occurrences, (str, bytes, bytearray))
        or not raw_occurrences
    ):
        raise KurtosisReviewScanError("Kurtosis evidence has no analyzed occurrences.")
    rows: list[KurtosisAnalyzedOccurrence] = []
    for raw_occurrence in raw_occurrences:
        if not isinstance(raw_occurrence, Mapping):
            raise KurtosisReviewScanError("Kurtosis occurrence evidence is malformed.")
        label = str(raw_occurrence.get("condition_label") or "").strip()
        key = str(raw_occurrence.get("occurrence_key") or "").strip()
        try:
            repetition = int(raw_occurrence.get("repetition_index"))
        except (TypeError, ValueError) as exc:
            raise KurtosisReviewScanError("Kurtosis occurrence repetition is malformed.") from exc
        if not label or not key or repetition < 0:
            raise KurtosisReviewScanError("Kurtosis occurrence evidence is malformed.")
        rows.append(KurtosisAnalyzedOccurrence(label, repetition, key))
    return tuple(rows)


def _corroborator_states(
    channel_decision: Mapping[str, object],
) -> tuple[KurtosisCorroboratorState, ...]:
    raw_assessments = channel_decision.get("corroborator_assessments", ())
    if not isinstance(raw_assessments, Sequence) or isinstance(raw_assessments, (str, bytes, bytearray)):
        raise KurtosisReviewScanError("Kurtosis corroborator assessments are malformed.")
    states: list[KurtosisCorroboratorState] = []
    for raw_assessment in raw_assessments:
        if not isinstance(raw_assessment, Mapping):
            raise KurtosisReviewScanError("Kurtosis corroborator assessment is malformed.")
        finding = raw_assessment.get("finding")
        if not isinstance(finding, Mapping):
            raise KurtosisReviewScanError("Kurtosis corroborator finding is malformed.")
        states.append(
            KurtosisCorroboratorState(
                method_id=str(finding.get("method_id") or "").strip(),
                method_version=str(finding.get("method_version") or "").strip(),
                authority=str(finding.get("authority") or "").strip(),
                eligible=bool(raw_assessment.get("eligible", False)),
                reason=str(raw_assessment.get("reason") or "").strip(),
            )
        )
    return tuple(states)


def _signal_preview(
    payload: Mapping[str, object],
    *,
    channel: str,
) -> tuple[str, int, tuple[float | None, ...]]:
    unit = str(payload.get("unit") or "uV").strip() or "uV"
    try:
        source_count = int(payload.get("source_sample_count") or 0)
    except (TypeError, ValueError) as exc:
        raise KurtosisReviewScanError("Kurtosis signal preview sample count is invalid.") from exc
    channels = payload.get("channels")
    if not isinstance(channels, Mapping):
        raise KurtosisReviewScanError("Kurtosis signal preview channels are malformed.")
    raw_values = channels.get(channel)
    if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes, bytearray)) or not raw_values:
        raise KurtosisReviewScanError(f"Kurtosis signal preview is missing for {channel}.")
    values = tuple(_optional_finite(value, field_name="signal preview value") for value in raw_values)
    return unit, source_count, values


_DISPLAY_ONLY_CHANNEL_FLAG_FIELDS = (
    ("low_variance_channels", "persistent low variance"),
    ("high_amplitude_channels", "persistent high amplitude"),
    ("rare_burst_channels", "persistent rare burst"),
    ("spatial_outlier_channels", "persistent spatial outlier"),
    ("transient_low_variance_channels", "transient low variance"),
    ("transient_high_amplitude_channels", "transient high amplitude"),
    ("transient_rare_burst_channels", "transient rare burst"),
)


def _sequence_contains_channel(value: object, channel: str) -> bool:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return False
    target = channel.casefold()
    return any(str(item or "").strip().casefold() == target for item in value)


def _finding_location(row: Mapping[object, object]) -> str:
    condition = str(row.get("condition_label") or "").strip()
    raw_occurrence = row.get("occurrence_display")
    if raw_occurrence is None and row.get("occurrence") is not None:
        try:
            raw_occurrence = int(row["occurrence"]) + 1
        except (TypeError, ValueError):
            raw_occurrence = None
    if condition and raw_occurrence is not None:
        return f" in {condition} occurrence {raw_occurrence}"
    if condition:
        return f" in {condition}"
    return ""


def _display_only_channel_health(
    raw_channel_qc: Mapping[object, object] | None,
    *,
    channel: str,
) -> tuple[str, ...]:
    """Extract same-channel raw-QC context for display only.

    This helper deliberately returns presentation strings.  The payload is
    never passed to kurtosis evidence preparation or corroborator assessment.
    """

    if not raw_channel_qc:
        return ()

    details: list[str] = []
    candidate_sources = raw_channel_qc.get("candidate_sources")
    if isinstance(candidate_sources, Mapping):
        found, raw_sources = _casefold_mapping_entry(
            candidate_sources,
            channel,
            field_name="Raw-channel QC candidate sources",
        )
        if (
            found
            and isinstance(raw_sources, Sequence)
            and not isinstance(
                raw_sources,
                (str, bytes, bytearray),
            )
        ):
            sources = tuple(
                dict.fromkeys(
                    str(source or "").strip().replace("_", " ") for source in raw_sources if str(source or "").strip()
                )
            )
            if sources:
                details.append("Candidate sources: " + ", ".join(sources))

    flags = [
        label
        for field_name, label in _DISPLAY_ONLY_CHANNEL_FLAG_FIELDS
        if _sequence_contains_channel(raw_channel_qc.get(field_name), channel)
    ]
    if flags:
        details.append("Channel flags: " + ", ".join(dict.fromkeys(flags)))

    finding_fields = (
        ("occurrence_review_findings", "Occurrence flag"),
        ("transient_review_findings", "Transient flag"),
        ("raw_amplitude_review_findings", "Amplitude flag"),
    )
    target = channel.casefold()
    for field_name, label in finding_fields:
        raw_findings = raw_channel_qc.get(field_name)
        if not isinstance(raw_findings, Sequence) or isinstance(
            raw_findings,
            (str, bytes, bytearray),
        ):
            continue
        for raw_finding in raw_findings:
            if not isinstance(raw_finding, Mapping):
                continue
            finding_channel = str(raw_finding.get("channel") or "").strip()
            if finding_channel.casefold() != target:
                continue
            raw_categories = raw_finding.get("categories")
            if isinstance(raw_categories, Sequence) and not isinstance(
                raw_categories,
                (str, bytes, bytearray),
            ):
                categories = [
                    str(value or "").strip().replace("_", " ") for value in raw_categories if str(value or "").strip()
                ]
            else:
                category = str(raw_finding.get("category") or raw_finding.get("severity") or "reported").strip()
                categories = [category.replace("_", " ")] if category else []
            category_text = ", ".join(categories) if categories else "reported"
            details.append(f"{label}: {category_text}{_finding_location(raw_finding)}")

    return tuple(dict.fromkeys(details))


def _review_items_from_prepared(
    prepared: Mapping[str, object],
    *,
    path: Path,
    participant_id: str,
    recording_id: str,
    session_id: str | None,
    session_label: str | None,
    visit_index: int | None,
    raw_channel_qc: Mapping[object, object] | None = None,
) -> tuple[KurtosisReviewItem, ...]:
    evidence = prepared.get("evidence")
    decision_plan = prepared.get("decision_plan")
    preview = prepared.get("signal_preview")
    if not isinstance(evidence, Mapping) or not isinstance(decision_plan, Mapping):
        raise KurtosisReviewScanError("Shared preprocessing returned incomplete QC-16 evidence.")
    if not isinstance(preview, Mapping):
        raise KurtosisReviewScanError("Shared preprocessing returned malformed signal evidence.")

    analyzed_occurrences = _occurrences(evidence)
    analyzed_conditions = tuple(dict.fromkeys(item.condition_label for item in analyzed_occurrences))
    raw_channel_rows = evidence.get("channels")
    raw_decisions = decision_plan.get("channel_decisions")
    if not isinstance(raw_channel_rows, Sequence) or isinstance(raw_channel_rows, str):
        raise KurtosisReviewScanError("Kurtosis channel evidence is malformed.")
    if not isinstance(raw_decisions, Sequence) or isinstance(raw_decisions, str):
        raise KurtosisReviewScanError("Kurtosis channel decisions are malformed.")
    evidence_by_channel = {
        str(row.get("channel") or "").strip(): row for row in raw_channel_rows if isinstance(row, Mapping)
    }
    items: list[KurtosisReviewItem] = []
    seen: set[str] = set()
    for raw_decision in raw_decisions:
        if not isinstance(raw_decision, Mapping):
            raise KurtosisReviewScanError("Kurtosis channel decision is malformed.")
        if raw_decision.get("state") != CHANNEL_DECISION_REVIEW_REQUIRED:
            continue
        channel = str(raw_decision.get("channel") or "").strip()
        if not channel or channel in seen:
            raise KurtosisReviewScanError("Review-required kurtosis channels are blank or duplicated.")
        seen.add(channel)
        channel_evidence = evidence_by_channel.get(channel)
        if not isinstance(channel_evidence, Mapping):
            raise KurtosisReviewScanError(f"Review-required channel evidence is missing for {channel}.")
        signal_unit, signal_count, signal_values = _signal_preview(
            preview,
            channel=channel,
        )
        items.append(
            KurtosisReviewItem(
                path=path,
                participant_id=participant_id,
                recording_id=recording_id,
                session_id=session_id,
                session_label=session_label,
                visit_index=visit_index,
                channel=channel,
                analyzed_conditions=analyzed_conditions,
                analyzed_occurrences=analyzed_occurrences,
                raw_kurtosis=_optional_finite(
                    channel_evidence.get("raw_kurtosis"),
                    field_name="raw kurtosis",
                ),
                signed_normalized_score=_optional_finite(
                    channel_evidence.get("signed_z"),
                    field_name="signed normalized score",
                ),
                threshold=_positive_finite(
                    channel_evidence.get("threshold"),
                    field_name="kurtosis threshold",
                ),
                validity=str(channel_evidence.get("validity") or "").strip(),
                validity_reason=_normalized_optional_text(channel_evidence.get("validity_reason")),
                corroborator_registry_version=str(evidence.get("corroborator_registry_version") or "").strip(),
                corroborator_states=_corroborator_states(raw_decision),
                display_only_channel_health=_display_only_channel_health(
                    raw_channel_qc,
                    channel=channel,
                ),
                signal_unit=signal_unit,
                signal_source_sample_count=signal_count,
                signal_preview=signal_values,
                evidence=dict(evidence),
                signal_view=dict(preview.get("signal_view") or {}),
                review_diagnostics=dict(prepared.get("review_diagnostics") or {}),
            )
        )
    return tuple(items)


def _skipped_result(
    identity: tuple[Path, str, str, str | None, str | None, int | None],
    *,
    reason: str,
    analyzed_conditions: tuple[str, ...] = (),
) -> KurtosisReviewFileResult:
    path, participant, recording, session_id, session_label, visit_index = identity
    return KurtosisReviewFileResult(
        path=path,
        participant_id=participant,
        recording_id=recording,
        session_id=session_id,
        session_label=session_label,
        visit_index=visit_index,
        status=KURTOSIS_REVIEW_FILE_STATUS_SKIPPED,
        analyzed_conditions=analyzed_conditions,
        skip_reason=reason,
    )


def _error_result(
    identity: tuple[Path, str, str, str | None, str | None, int | None],
    exc: Exception,
) -> KurtosisReviewFileResult:
    path, participant, recording, session_id, session_label, visit_index = identity
    message = str(exc).strip() or type(exc).__name__
    return KurtosisReviewFileResult(
        path=path,
        participant_id=participant,
        recording_id=recording,
        session_id=session_id,
        session_label=session_label,
        visit_index=visit_index,
        status=KURTOSIS_REVIEW_FILE_STATUS_ERROR,
        error=message,
    )


def _casefold_mapping_entry(
    values: Mapping[object, Any],
    key: str,
    *,
    field_name: str,
) -> tuple[bool, Any]:
    matches = [value for raw_key, value in values.items() if str(raw_key or "").strip().casefold() == key.casefold()]
    if len(matches) > 1:
        raise KurtosisReviewScanError(f"{field_name} contains duplicate case-insensitive key {key!r}.")
    return (bool(matches), matches[0] if matches else None)


def reconcile_kurtosis_review_decisions(
    scan: KurtosisReviewScan,
    kurtosis_review_decisions_by_recording: object,
    *,
    kurtosis_auto_interpolate_all: bool = False,
) -> KurtosisReviewDecisionReconciliation:
    """Reuse only fingerprint-current receipts and reprompt new or stale items.

    Saved rows that have no current review-required finding are intentionally
    omitted from ``current_receipts`` so a caller cannot feed obsolete or extra
    decisions into final preprocessing.
    """

    if not isinstance(scan, KurtosisReviewScan):
        raise KurtosisReviewScanError("Kurtosis decision reconciliation requires a scan.")
    if kurtosis_review_decisions_by_recording in (None, ""):
        raw_decisions: Mapping[object, Any] = {}
    elif isinstance(kurtosis_review_decisions_by_recording, Mapping):
        raw_decisions = kurtosis_review_decisions_by_recording
    else:
        raise KurtosisReviewScanError("Kurtosis review decisions must be a recording-to-channel map.")

    current: dict[str, dict[str, dict[str, object]]] = {}
    pending_status: dict[str, dict[str, str]] = {}
    transformed_results: list[KurtosisReviewFileResult] = []
    for result in scan.results:
        pending: list[KurtosisReviewItem] = []
        for item in result.review_items:
            recording_found, raw_channels = _casefold_mapping_entry(
                raw_decisions,
                item.recording_id,
                field_name="Kurtosis review decisions",
            )
            channel_found = False
            raw_receipt: object = None
            if recording_found and isinstance(raw_channels, Mapping):
                channel_found, raw_receipt = _casefold_mapping_entry(
                    raw_channels,
                    item.channel,
                    field_name=f"Kurtosis review decisions for {item.recording_id}",
                )
            status = KURTOSIS_REVIEW_PENDING_NEW
            if recording_found and not isinstance(raw_channels, Mapping):
                status = KURTOSIS_REVIEW_PENDING_STALE
            elif channel_found:
                try:
                    receipt = validate_kurtosis_review_decision_payload(
                        raw_receipt,
                        evidence=item.evidence,
                        channel=item.channel,
                        review_scope=item.review_scope,
                        kurtosis_auto_interpolate_all=kurtosis_auto_interpolate_all,
                    )
                except (KurtosisQCError, TypeError, ValueError):
                    status = KURTOSIS_REVIEW_PENDING_STALE
                else:
                    current.setdefault(item.recording_id, {})[item.channel] = receipt.to_payload()
                    continue
            pending.append(replace(item, review_status=status))
            pending_status.setdefault(item.recording_id, {})[item.channel] = status

        transformed_status = result.status
        if result.status == KURTOSIS_REVIEW_FILE_STATUS_REVIEW_REQUIRED and not pending:
            transformed_status = KURTOSIS_REVIEW_FILE_STATUS_CLEAR
        transformed_results.append(
            replace(
                result,
                status=transformed_status,
                review_items=tuple(pending),
            )
        )

    reconciled_scan = KurtosisReviewScan(
        results=tuple(transformed_results),
        cancelled=scan.cancelled,
    )
    return KurtosisReviewDecisionReconciliation(
        scan=reconciled_scan,
        current_receipts=current,
        pending_status_by_recording=pending_status,
    )


def _validate_review_request(
    raw_file_infos: Sequence[Any],
    settings: Mapping[str, Any],
    event_map: Mapping[str, int],
    raw_channel_qc_by_recording: Mapping[str, Mapping[str, object]] | None,
) -> tuple[dict[str, int], Any]:
    if isinstance(raw_file_infos, (str, bytes, bytearray)):
        raise KurtosisReviewScanError("Raw-file infos must be a sequence.")
    if not isinstance(settings, Mapping):
        raise KurtosisReviewScanError("Kurtosis review settings must be an object.")
    if not isinstance(event_map, Mapping) or not event_map:
        raise KurtosisReviewScanError("Kurtosis review requires the current condition event map.")
    if raw_channel_qc_by_recording is not None and not isinstance(raw_channel_qc_by_recording, Mapping):
        raise KurtosisReviewScanError("Raw-channel QC display evidence must be a recording-to-payload map.")
    try:
        canonical_event_map = {str(label).strip(): int(code) for label, code in event_map.items() if str(label).strip()}
    except (TypeError, ValueError) as exc:
        raise KurtosisReviewScanError("Kurtosis review condition event map is malformed.") from exc
    if not canonical_event_map:
        raise KurtosisReviewScanError("Kurtosis review requires the current condition event map.")
    try:
        protocol = normalize_frequency_protocol(settings.get("frequency_protocol"))
    except Exception as exc:
        raise KurtosisReviewScanError(f"Kurtosis review requires a valid project frequency protocol: {exc}") from exc
    if not protocol.is_ready:
        raise KurtosisReviewScanError("Kurtosis review requires a confirmed project frequency protocol.")
    return canonical_event_map, protocol


def scan_kurtosis_review(
    raw_file_infos: Sequence[Any],
    settings: Mapping[str, Any],
    *,
    event_map: Mapping[str, int],
    reviewed_event_plans_by_file: Mapping[str, Any] | None = None,
    raw_channel_qc_by_recording: Mapping[str, Mapping[str, object]] | None = None,
    progress: ProgressCallback | None = None,
    status_progress: StatusProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    max_workers: int | None = None,
    source_prefetch: QcSourcePrefetch | None = None,
) -> KurtosisReviewScan:
    """Classify current exclusions before allocating numerical review workers.

    The legacy progress callback counts all requested entries, including skips.
    Structured progress counts eligible completions and exclusions separately;
    failed eligible entries count as completed, with their own failure count.
    Both callbacks and the caller's cancellation callback run on this thread.
    """

    canonical_event_map, protocol = _validate_review_request(
        raw_file_infos, settings, event_map, raw_channel_qc_by_recording,
    )
    _configured_channel_limit(settings)
    # Stop untouched speculative loads even when every requested entry is
    # excluded. An active load still reserves one of the two large-job slots.
    prefetch_loading = source_prefetch.begin_consumption() if source_prefetch is not None else False
    total = len(raw_file_infos)
    indexed_results: dict[int, KurtosisReviewFileResult] = {}
    eligible_indices: list[int] = []
    eligible_infos: list[Any] = []

    def report_status() -> None:
        if status_progress is None:
            return
        excluded = sum(result.status == KURTOSIS_REVIEW_FILE_STATUS_SKIPPED for result in indexed_results.values())
        failed = sum(result.status == KURTOSIS_REVIEW_FILE_STATUS_ERROR for result in indexed_results.values())
        status_progress(KurtosisReviewProgress(
            eligible_total=total - excluded,
            completed_eligible=len(indexed_results) - excluded,
            excluded_count=excluded,
            failed_count=failed,
        ))

    def finished_scan(*, cancelled: bool) -> KurtosisReviewScan:
        return KurtosisReviewScan(
            tuple(indexed_results[index] for index in sorted(indexed_results)),
            cancelled=cancelled,
        )

    raw_plans = (reviewed_event_plans_by_file if reviewed_event_plans_by_file is not None
                 else settings.get("_fpvs_preflight_event_plans_by_file"))
    plans = raw_plans if isinstance(raw_plans, Mapping) else {}
    excluded_participants = {value.casefold() for value in normalize_manual_excluded_participants(settings.get("manual_excluded_participants"))}
    excluded_recordings = {value.casefold() for value in normalize_manual_excluded_recordings(settings.get("manual_excluded_recordings"))}
    participant_conditions = normalize_manual_excluded_participant_conditions(settings.get("manual_excluded_participant_conditions"))
    recording_conditions = normalize_manual_excluded_recording_conditions(settings.get("manual_excluded_recording_conditions"))
    for index, info in enumerate(raw_file_infos):
        if should_cancel and should_cancel():
            report_status()
            if progress:
                progress("Kurtosis review scan cancelled", len(indexed_results), total)
            return finished_scan(cancelled=True)
        identity = _identity(info)
        path, participant, recording, *_session = identity
        known_result = None
        if participant.casefold() in excluded_participants or recording.casefold() in excluded_recordings:
            known_result = _skipped_result(identity, reason=KURTOSIS_REVIEW_SKIP_RECORDING_EXCLUDED)
        else:
            try:
                event_plan = _event_plan_for_path(plans, path)
                source_plan = validate_source_analysis_span_context(
                    event_plan_payload=event_plan,
                    event_map=canonical_event_map,
                    protocol=protocol,
                )
                conditions = _condition_labels(source_plan)
                if not conditions or all(
                    is_participant_condition_excluded(participant_conditions, participant, condition)
                    or is_recording_condition_excluded(recording_conditions, recording, condition)
                    for condition in conditions
                ):
                    known_result = _skipped_result(
                        identity, reason=KURTOSIS_REVIEW_SKIP_ALL_CONDITIONS_EXCLUDED,
                        analyzed_conditions=conditions,
                    )
            except Exception as exc:
                logger.exception("kurtosis_review_scan_failed file=%s participant_id=%s recording_id=%s", path, participant, recording)
                known_result = _error_result(identity, exc)
        if known_result is not None:
            indexed_results[index] = known_result
            if progress:
                verb = "Skipped" if known_result.status == KURTOSIS_REVIEW_FILE_STATUS_SKIPPED else "Could not review"
                progress(f"{verb} {path.name}", len(indexed_results), total)
        else:
            eligible_indices.append(index)
            eligible_infos.append(info)

    # Confirmed skips and invalid metadata never contribute source sizes or
    # duplicate memmap stems to the numerical worker estimate.
    report_status()
    if should_cancel and should_cancel():
        if progress:
            progress("Kurtosis review scan cancelled", len(indexed_results), total)
        return finished_scan(cancelled=True)
    if not eligible_infos:
        return finished_scan(cancelled=False)
    worker_count = _review_worker_count(eligible_infos, 1 if prefetch_loading else max_workers)
    completed_before_work = len(indexed_results)

    def relay_progress(message: str, completed: int, _total: int) -> None:
        if progress:
            progress(message, completed_before_work + completed, total)

    def accept_results(index: int, results: tuple[KurtosisReviewFileResult, ...]) -> None:
        if results:
            indexed_results[eligible_indices[index]] = results[0]
            report_status()

    if worker_count > 1:
        scan = _scan_review_parallel(
            eligible_infos, settings, event_map=canonical_event_map,
            reviewed_event_plans_by_file=reviewed_event_plans_by_file,
            raw_channel_qc_by_recording=raw_channel_qc_by_recording,
            progress=relay_progress, should_cancel=should_cancel,
            max_workers=worker_count, source_prefetch=source_prefetch,
            result_progress=accept_results,
        )
        return finished_scan(cancelled=scan.cancelled)

    completed = 0
    for index, info in enumerate(eligible_infos):
        scan = _scan_kurtosis_review_serial(
            [info], settings, event_map=canonical_event_map,
            reviewed_event_plans_by_file=reviewed_event_plans_by_file,
            raw_channel_qc_by_recording=raw_channel_qc_by_recording,
            progress=lambda message, current_completed, _total: relay_progress(message, completed + current_completed, total),
            should_cancel=should_cancel, source_prefetch=source_prefetch,
        )
        accept_results(index, scan.results)
        completed += len(scan.results)
        if scan.cancelled:
            return finished_scan(cancelled=True)
    return finished_scan(cancelled=False)


def _scan_kurtosis_review_serial(
    raw_file_infos: Sequence[Any],
    settings: Mapping[str, Any],
    *,
    event_map: Mapping[str, int],
    reviewed_event_plans_by_file: Mapping[str, Any] | None = None,
    raw_channel_qc_by_recording: Mapping[str, Mapping[str, object]] | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    source_prefetch: QcSourcePrefetch | None = None,
) -> KurtosisReviewScan:
    """Keep the serial numerical path independent of batch scheduling."""

    canonical_event_map, protocol = _validate_review_request(
        raw_file_infos, settings, event_map, raw_channel_qc_by_recording,
    )

    raw_plans = (
        reviewed_event_plans_by_file
        if reviewed_event_plans_by_file is not None
        else settings.get("_fpvs_preflight_event_plans_by_file")
    )
    plans = raw_plans if isinstance(raw_plans, Mapping) else {}
    excluded_participants = {
        value.casefold()
        for value in normalize_manual_excluded_participants(settings.get("manual_excluded_participants"))
    }
    excluded_recordings = {
        value.casefold() for value in normalize_manual_excluded_recordings(settings.get("manual_excluded_recordings"))
    }
    participant_condition_exclusions = normalize_manual_excluded_participant_conditions(
        settings.get("manual_excluded_participant_conditions")
    )
    recording_condition_exclusions = normalize_manual_excluded_recording_conditions(
        settings.get("manual_excluded_recording_conditions")
    )
    ref_pair = _configured_reference_pair(settings)
    stim_channel = _configured_stim_channel(settings)
    channel_limit = _configured_channel_limit(settings)
    total = len(raw_file_infos)
    results: list[KurtosisReviewFileResult] = []

    for index, info in enumerate(raw_file_infos, start=1):
        if should_cancel and should_cancel():
            if progress:
                progress("Kurtosis review scan cancelled", index - 1, total)
            return KurtosisReviewScan(tuple(results), cancelled=True)
        identity = _identity(info)
        path, participant, recording, session_id, session_label, visit_index = identity
        if progress:
            progress(f"Checking kurtosis evidence for {path.name}", index - 1, total)

        if participant.casefold() in excluded_participants or recording.casefold() in excluded_recordings:
            results.append(
                _skipped_result(
                    identity,
                    reason=KURTOSIS_REVIEW_SKIP_RECORDING_EXCLUDED,
                )
            )
            if progress:
                progress(f"Skipped excluded recording {path.name}", index, total)
            continue

        raw: Any | None = None
        prefetched = False
        try:
            event_plan = _event_plan_for_path(plans, path)
            source_plan = validate_source_analysis_span_context(
                event_plan_payload=event_plan,
                event_map=canonical_event_map,
                protocol=protocol,
            )
            all_conditions = _condition_labels(source_plan)
            if not all_conditions:
                results.append(
                    _skipped_result(
                        identity,
                        reason=KURTOSIS_REVIEW_SKIP_ALL_CONDITIONS_EXCLUDED,
                    )
                )
                if progress:
                    progress(f"Skipped {path.name}: no analyzed conditions", index, total)
                continue
            excluded_conditions = tuple(
                condition
                for condition in all_conditions
                if is_participant_condition_excluded(
                    participant_condition_exclusions,
                    participant,
                    condition,
                )
                or is_recording_condition_excluded(
                    recording_condition_exclusions,
                    recording,
                    condition,
                )
            )
            if len(excluded_conditions) == len(all_conditions):
                results.append(
                    _skipped_result(
                        identity,
                        reason=KURTOSIS_REVIEW_SKIP_ALL_CONDITIONS_EXCLUDED,
                        analyzed_conditions=all_conditions,
                    )
                )
                if progress:
                    progress(f"Skipped excluded conditions in {path.name}", index, total)
                continue

            from Main_App.processing.qc_signal_view import source_content_identity

            review_source_identity = None
            prefetched_identity = getattr(source_prefetch, "source_content_identity_for", None)
            if source_prefetch is not None and not callable(prefetched_identity):
                review_source_identity = source_content_identity(path, should_cancel=should_cancel)
            load_started = perf_counter()
            if source_prefetch is not None:
                if progress:
                    progress(f"Preparing {path.name} for kurtosis review", index - 1, total)
                raw = source_prefetch.take(path, settings=settings, should_cancel=should_cancel)
                prefetched = raw is not None
                if prefetched and callable(prefetched_identity):
                    review_source_identity = prefetched_identity(raw)
                if should_cancel and should_cancel():
                    return KurtosisReviewScan(tuple(results), cancelled=True)
            if raw is None:
                review_source_identity = source_content_identity(path, should_cancel=should_cancel)
                if progress:
                    progress(f"Loading {path.name} with BioSemi64 geometry", index - 1, total)
                raw = load_utils.load_eeg_file(
                    _LoaderLogAdapter(path),
                    str(path),
                    ref_pair=ref_pair,
                    first_n_channels=channel_limit,
                    stim_channel=stim_channel,
                    electrode_mapping_profile=settings.get("electrode_mapping_profile"),
                    electrode_montage=BIOSEMI64_MONTAGE_ID,
                )
            elif progress:
                progress(f"Using preloaded recording {path.name}", index - 1, total)
            if raw is None:
                raise KurtosisReviewScanError("The EEG loader returned no Raw data.")
            if review_source_identity is None:
                raise KurtosisReviewScanError("Source content identity is unavailable for diagnostic review.")
            validate_raw_biosemi64_geometry(
                raw,
                expected_retained_channels=BIOSEMI64_CHANNELS[:channel_limit],
                reference_channels=ref_pair,
                stim_channel=stim_channel,
                require_runtime_identity=True,
            )
            _log_scan_timing(path, "load_and_geometry", load_started)
            if should_cancel and should_cancel():
                if progress:
                    progress("Kurtosis review scan cancelled", index - 1, total)
                return KurtosisReviewScan(tuple(results), cancelled=True)

            events_started = perf_counter()
            events, event_source = _find_raw_events(raw, stim_channel=stim_channel)
            validated_plan = validate_source_analysis_span_plan(
                event_plan_payload=event_plan,
                events=events,
                sampling_rate_hz=float(raw.info["sfreq"]),
                n_times=int(raw.n_times),
                first_samp=int(raw.first_samp),
                event_map=canonical_event_map,
                protocol=protocol,
            )
            restricted_plan = restrict_source_analysis_span_plan_by_condition(
                validated_plan,
                excluded_condition_labels=excluded_conditions,
                exclusion_scope={
                    # Match the final processing runner's selection identity.
                    # Source path is independently bound by each review receipt.
                    "participant_id": participant,
                    "recording_id": recording,
                },
            )
            _log_scan_timing(path, "events_and_plan", events_started)
            analyzed_conditions = _condition_labels(restricted_plan)
            if not analyzed_conditions:
                results.append(
                    _skipped_result(
                        identity,
                        reason=KURTOSIS_REVIEW_SKIP_ALL_CONDITIONS_EXCLUDED,
                        analyzed_conditions=all_conditions,
                    )
                )
                if progress:
                    progress(f"Skipped excluded conditions in {path.name}", index, total)
                continue
            if should_cancel and should_cancel():
                if progress:
                    progress("Kurtosis review scan cancelled", index - 1, total)
                return KurtosisReviewScan(tuple(results), cancelled=True)

            file_settings = dict(settings)
            file_settings["_fpvs_kurtosis_checkpoint_should_cancel"] = should_cancel
            file_settings.update(
                {
                    "electrode_montage": BIOSEMI64_MONTAGE_ID,
                    "max_idx_keep": channel_limit,
                    "_fpvs_source_analysis_span_plan": restricted_plan,
                    "_fpvs_require_analysis_spans": True,
                    "_fpvs_source_file_path": str(path),
                    "_fpvs_participant_id": participant,
                    "_fpvs_recording_id": recording,
                    "_fpvs_session_id": session_id,
                    "_fpvs_session_label": session_label,
                }
            )
            # Scanning establishes current evidence. Persisted receipts are
            # applied only by the workflow after it compares or replaces them.
            file_settings.pop("_fpvs_kurtosis_review_decisions", None)
            direct_bad_channels = manual_removed_electrodes_for_recording(
                settings,
                participant_id=participant,
                recording_id=recording,
            )
            detector_mode = normalize_removed_electrode_detection_mode(
                settings.get("removed_electrode_detection_mode"),
                auto_detect_removed_electrodes=settings.get("auto_detect_removed_electrodes", False),
            )
            if detector_mode == REMOVED_ELECTRODE_DETECTION_MODE_AUTO:
                # Final processing marks these current, directly authorized
                # raw-QC bads before initial referencing. Recompute them here
                # on exactly the same included spans instead of promoting
                # display-only preflight findings into authority.
                file_settings["_fpvs_manual_removed_electrodes"] = list(direct_bad_channels)
                raw_qc_started = perf_counter()
                if progress:
                    progress(f"Checking removed electrodes in {path.name}", index - 1, total)
                raw_qc_result = evaluate_raw_channel_qc(
                    raw,
                    file_settings,
                    filename=path.name,
                    analysis_spans=relative_spans_from_plan(restricted_plan),
                )
                _log_scan_timing(path, "automatic_raw_channel_qc", raw_qc_started)
                if raw_qc_result.excluded:
                    results.append(
                        _skipped_result(
                            identity,
                            reason=KURTOSIS_REVIEW_SKIP_RAW_QC_EXCLUDED,
                            analyzed_conditions=analyzed_conditions,
                        )
                    )
                    if progress:
                        progress(f"Skipped {path.name}: raw channel QC excluded the recording", index, total)
                    continue
                direct_bad_channels = tuple(raw_qc_result.channels_to_interpolate)
            if progress:
                progress(f"Preprocessing {path.name} for kurtosis review", index - 1, total)
            review_diagnostics = {}
            diagnostics_started = perf_counter()
            try:
                from Main_App.processing.qc_review_diagnostics import build_raw_qc_review_diagnostics

                review_diagnostics = build_raw_qc_review_diagnostics(
                    raw,
                    occurrences=[{
                        "start_sample": span["source_coordinates"]["start_relative_sample"],
                        "stop_sample": span["source_coordinates"]["stop_relative_sample"],
                        "condition_label": span["condition_label"],
                        "occurrence": span["repetition_index"],
                        "occurrence_key": span["occurrence_key"],
                    } for span in restricted_plan["spans"]],
                    ref_channels=ref_pair, unusable_channels=direct_bad_channels,
                    should_cancel=should_cancel,
                )
            except InterruptedError:
                return KurtosisReviewScan(tuple(results), cancelled=True)
            except Exception:  # Diagnostic-only: preparation/scientific evidence still proceeds.
                if should_cancel and should_cancel():
                    return KurtosisReviewScan(tuple(results), cancelled=True)
                logger.debug("qc_review_diagnostics_unavailable file=%s", path, exc_info=True)
                review_diagnostics = {
                    "authority": "review_only", "status": "unavailable",
                    "reason": "Additional raw signal diagnostics could not be computed for this recording. Inspect the signal directly.",
                    "evaluation_scope": "all_analyzed_occurrences", "localized_events": [],
                }
            _log_scan_timing(path, "raw_review_diagnostics", diagnostics_started)
            prepare_started = perf_counter()
            prepared = prepare_kurtosis_review_evidence(
                raw,
                file_settings,
                lambda message: logger.debug(
                    "kurtosis_review_preprocess file=%s event_source=%s message=%s",
                    path.name,
                    event_source,
                    message,
                ),
                path.name,
                direct_bad_channels=direct_bad_channels,
                copy_raw=False,
            )
            _log_scan_timing(path, "preprocessing_and_evidence", prepare_started)
            preview = dict(prepared.get("signal_preview") or {})
            post_load_identity = (preview.get("signal_view") or {}).get("checkpoint_source_identity")
            if not post_load_identity:
                post_load_identity = source_content_identity(path, should_cancel=should_cancel)
            if post_load_identity != review_source_identity:
                raise KurtosisReviewScanError("Recording changed while QC evidence was prepared. Run QC again.")
            review_diagnostics = {**review_diagnostics, "source_identity": review_source_identity} if review_diagnostics else {}
            prepared = {**prepared, "review_diagnostics": review_diagnostics}
            preview["signal_view"] = {**dict(preview.get("signal_view") or {}), "source_identity": review_source_identity}
            prepared["signal_preview"] = preview
            raw_channel_qc: Mapping[object, object] | None = None
            if raw_channel_qc_by_recording is not None:
                raw_qc_found, raw_qc_payload = _casefold_mapping_entry(
                    raw_channel_qc_by_recording,
                    recording,
                    field_name="Raw-channel QC display evidence",
                )
                if raw_qc_found:
                    if not isinstance(raw_qc_payload, Mapping):
                        raise KurtosisReviewScanError(
                            f"Raw-channel QC display evidence for {recording} must be an object."
                        )
                    raw_channel_qc = raw_qc_payload
            review_items = _review_items_from_prepared(
                prepared,
                path=path,
                participant_id=participant,
                recording_id=recording,
                session_id=session_id,
                session_label=session_label,
                visit_index=visit_index,
                raw_channel_qc=raw_channel_qc,
            )
            evidence = prepared.get("evidence")
            decision_plan = prepared.get("decision_plan")
            if not isinstance(evidence, Mapping) or not isinstance(decision_plan, Mapping):
                raise KurtosisReviewScanError("Shared preprocessing returned incomplete QC-16 evidence.")
            if not review_items and not bool(decision_plan.get("ready_for_interpolation")):
                reasons = decision_plan.get("blocking_reasons")
                raise KurtosisReviewScanError(
                    "Kurtosis evidence blocks processing without a reviewable channel"
                    + (f": {reasons}" if reasons else ".")
                )
            status = KURTOSIS_REVIEW_FILE_STATUS_REVIEW_REQUIRED if review_items else KURTOSIS_REVIEW_FILE_STATUS_CLEAR
            results.append(
                KurtosisReviewFileResult(
                    path=path,
                    participant_id=participant,
                    recording_id=recording,
                    session_id=session_id,
                    session_label=session_label,
                    visit_index=visit_index,
                    status=status,
                    analyzed_conditions=analyzed_conditions,
                    review_items=review_items,
                    evidence=dict(evidence),
                    decision_plan=dict(decision_plan),
                    review_diagnostics=review_diagnostics,
                    source_identity=review_source_identity,
                )
            )
        except Exception as exc:
            if should_cancel and should_cancel():
                return KurtosisReviewScan(tuple(results), cancelled=True)
            logger.exception(
                "kurtosis_review_scan_failed file=%s participant_id=%s recording_id=%s",
                path,
                participant,
                recording,
            )
            results.append(_error_result(identity, exc))
        finally:
            if raw is not None:
                try:
                    if prefetched:
                        source_prefetch.release(raw)
                    else:
                        raw.close()
                except (AttributeError, OSError, RuntimeError, ValueError):
                    logger.warning(
                        "kurtosis_review_raw_close_failed file=%s",
                        path,
                        exc_info=True,
                    )
        if progress:
            progress(f"Finished kurtosis review scan for {path.name}", index, total)

    return KurtosisReviewScan(tuple(results), cancelled=False)


__all__ = [
    "CancelCallback",
    "KURTOSIS_REVIEW_FILE_STATUS_CLEAR",
    "KURTOSIS_REVIEW_FILE_STATUS_ERROR",
    "KURTOSIS_REVIEW_FILE_STATUS_REVIEW_REQUIRED",
    "KURTOSIS_REVIEW_FILE_STATUS_SKIPPED",
    "KURTOSIS_REVIEW_PENDING_NEW",
    "KURTOSIS_REVIEW_PENDING_STALE",
    "KURTOSIS_REVIEW_SKIP_ALL_CONDITIONS_EXCLUDED",
    "KURTOSIS_REVIEW_SKIP_RECORDING_EXCLUDED",
    "KURTOSIS_REVIEW_SKIP_RAW_QC_EXCLUDED",
    "KurtosisAnalyzedOccurrence",
    "KurtosisCorroboratorState",
    "KurtosisReviewFileResult",
    "KurtosisReviewDecisionReconciliation",
    "KurtosisReviewItem",
    "KurtosisReviewProgress",
    "KurtosisReviewScan",
    "KurtosisReviewScanError",
    "ProgressCallback",
    "StatusProgressCallback",
    "reconcile_kurtosis_review_decisions",
    "scan_kurtosis_review",
]
