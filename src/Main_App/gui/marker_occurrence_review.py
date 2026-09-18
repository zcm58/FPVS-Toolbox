"""GUI-neutral adapters for occurrence-level marker review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from Main_App.processing.marker_integrity import (
    MARKER_DECISION_EXCLUDE,
    MARKER_DECISION_RETAIN_FULL,
    MARKER_DECISION_USE_CONTIGUOUS,
    MARKER_INTEGRITY_METHOD_VERSION,
    MARKER_REVIEW_DECISION_SCHEMA_VERSION,
    MARKER_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED,
    MARKER_REVIEWER_STATE_EXPLICIT_GUI,
)


class MarkerOccurrenceReviewError(ValueError):
    """Raised when marker-review evidence or a GUI decision is malformed."""


@dataclass(frozen=True, slots=True)
class MarkerOccurrenceReviewItem:
    """One unresolved marker occurrence and its review evidence."""

    path: Path
    participant_id: str
    recording_id: str | None
    session_id: str | None
    session_label: str | None
    condition_label: str
    condition_code: int
    repetition_index: int
    occurrence_key: str
    marker_plan_fingerprint: str
    occurrence_fingerprint: str
    sampling_rate_hz: Fraction
    first_samp: int
    oddball_marker_code: int
    expected_analyzed_cycles: int
    oddball_rate_hz: Fraction
    raw_marker_samples: tuple[int, ...]
    retained_marker_samples: tuple[int, ...]
    exact_duplicate_count: int
    missing_gap_count: int
    estimated_missing_markers: int
    early_or_extra_count: int
    maximum_phase_residual_cycles: Fraction
    interval_evidence: tuple[str, ...]
    proposed_start_sample: int | None
    proposed_stop_sample: int | None
    contiguous_candidate_spans: tuple[tuple[int, int], ...]
    review_reasons: tuple[str, ...]


def resolved_path_text(path: str | Path) -> str:
    """Return the stable absolute path key used by preflight and the runner."""

    try:
        return str(Path(path).resolve())
    except (OSError, RuntimeError, ValueError) as exc:
        raise MarkerOccurrenceReviewError(
            f"Could not resolve marker-review file path {path!s}."
        ) from exc


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _required_int(payload: Mapping[str, Any], key: str) -> int:
    try:
        return int(payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise MarkerOccurrenceReviewError(
            f"Marker-review occurrence has no valid {key}."
        ) from exc


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise MarkerOccurrenceReviewError(
            f"Marker-review occurrence has no valid {key}."
        )
    return value


def _required_sha256(payload: Mapping[str, Any], key: str) -> str:
    value = _required_text(payload, key)
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise MarkerOccurrenceReviewError(
            f"Marker-review occurrence has no valid {key}."
        )
    return value


def _optional_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise MarkerOccurrenceReviewError(
            f"Marker-review occurrence has no valid {key}."
        ) from exc


def _fraction(value: object, *, field_name: str) -> Fraction:
    try:
        parsed = Fraction(str(value).strip())
    except (ValueError, ZeroDivisionError) as exc:
        raise MarkerOccurrenceReviewError(
            f"Marker-review occurrence has no valid {field_name}."
        ) from exc
    return parsed


def _sample_values(payload: Mapping[str, Any], key: str) -> tuple[int, ...]:
    raw_values = payload.get(key)
    if not _is_sequence(raw_values):
        raise MarkerOccurrenceReviewError(
            f"Marker-review occurrence has no valid {key}."
        )
    try:
        return tuple(int(value) for value in raw_values)
    except (TypeError, ValueError) as exc:
        raise MarkerOccurrenceReviewError(
            f"Marker-review occurrence has no valid {key}."
        ) from exc


def _candidate_spans(payload: Mapping[str, Any]) -> tuple[tuple[int, int], ...]:
    raw_spans = payload.get("contiguous_candidate_spans")
    if not _is_sequence(raw_spans):
        raise MarkerOccurrenceReviewError(
            "Marker-review occurrence has no contiguous-candidate list."
        )
    spans: list[tuple[int, int]] = []
    for raw_span in raw_spans:
        if not _is_sequence(raw_span) or len(raw_span) != 2:
            raise MarkerOccurrenceReviewError(
                "Marker-review occurrence contains a malformed candidate span."
            )
        try:
            start, stop = (int(raw_span[0]), int(raw_span[1]))
        except (TypeError, ValueError) as exc:
            raise MarkerOccurrenceReviewError(
                "Marker-review occurrence contains a malformed candidate span."
            ) from exc
        if stop <= start:
            raise MarkerOccurrenceReviewError(
                "Marker-review occurrence contains an empty candidate span."
            )
        spans.append((start, stop))
    return tuple(spans)


def _interval_summary(
    payload: Mapping[str, Any],
    *,
    sampling_rate_hz: Fraction,
    first_samp: int,
) -> tuple[int, int, int, Fraction, tuple[str, ...]]:
    raw_intervals = payload.get("intervals")
    if not _is_sequence(raw_intervals):
        raise MarkerOccurrenceReviewError(
            "Marker-review occurrence has no valid interval evidence."
        )
    missing_gap_count = 0
    estimated_missing = 0
    early_or_extra_count = 0
    maximum_residual = Fraction(0)
    evidence: list[str] = []
    for raw_interval in raw_intervals:
        if not isinstance(raw_interval, Mapping):
            raise MarkerOccurrenceReviewError(
                "Marker-review occurrence contains malformed interval evidence."
            )
        start = _required_int(raw_interval, "start_sample")
        stop = _required_int(raw_interval, "stop_sample")
        residual = _fraction(
            raw_interval.get("phase_residual_cycles"),
            field_name="phase_residual_cycles",
        )
        maximum_residual = max(maximum_residual, abs(residual))
        is_gap = bool(raw_interval.get("missing_marker_gap"))
        is_extra = bool(raw_interval.get("early_or_extra_marker"))
        missing = _required_int(raw_interval, "estimated_missing_markers")
        missing_gap_count += int(is_gap)
        early_or_extra_count += int(is_extra)
        estimated_missing += max(0, missing)
        classifications: list[str] = []
        if is_gap:
            classifications.append(f"gap; about {max(0, missing)} marker(s) missing")
        if is_extra:
            classifications.append("early/extra marker")
        if not classifications and residual:
            classifications.append("off-phase interval")
        if classifications:
            interval_cycles = str(raw_interval.get("interval_cycles") or "unknown")
            interval_seconds = _fraction(
                raw_interval.get("interval_seconds"),
                field_name="interval_seconds",
            )
            start_seconds = Fraction(start - first_samp) / sampling_rate_hz
            stop_seconds = Fraction(stop - first_samp) / sampling_rate_hz
            evidence.append(
                f"samples {start}-{stop} ({_fraction_display(start_seconds)} to "
                f"{_fraction_display(stop_seconds)} seconds from recording start): "
                f"{_fraction_display(interval_seconds)} seconds, "
                f"{interval_cycles} cycle(s), "
                f"phase residual {residual} cycle(s), "
                + "; ".join(classifications)
            )
    return (
        missing_gap_count,
        estimated_missing,
        early_or_extra_count,
        maximum_residual,
        tuple(evidence),
    )


def _duplicate_count(
    payload: Mapping[str, Any],
    *,
    raw_count: int,
    retained_count: int,
) -> int:
    raw_groups = payload.get("duplicate_groups")
    if _is_sequence(raw_groups) and raw_groups:
        total = 0
        for group in raw_groups:
            if not isinstance(group, Mapping):
                raise MarkerOccurrenceReviewError(
                    "Marker-review occurrence contains malformed duplicate evidence."
                )
            total += max(0, _required_int(group, "collapsed_count"))
        return total
    return max(0, raw_count - retained_count)


def _review_item(result: Any, event_plan: Mapping[str, Any], payload: object) -> MarkerOccurrenceReviewItem:
    if not isinstance(payload, Mapping):
        raise MarkerOccurrenceReviewError(
            "Marker-review occurrence payload must be an object."
        )
    condition_code = _required_int(payload, "condition_code")
    repetition_index = _required_int(payload, "repetition_index")
    occurrence_key = f"{condition_code}:{repetition_index}"
    raw_samples = _sample_values(payload, "raw_marker_samples")
    retained_samples = _sample_values(payload, "retained_marker_samples")
    interval = _fraction(
        payload.get("expected_interval_samples"),
        field_name="expected_interval_samples",
    )
    if interval <= 0:
        raise MarkerOccurrenceReviewError(
            "Marker-review expected marker interval must be positive."
        )
    marker_plan = event_plan.get("marker_integrity_plan")
    marker_plan = marker_plan if isinstance(marker_plan, Mapping) else {}
    if marker_plan.get("method_version") != MARKER_INTEGRITY_METHOD_VERSION:
        raise MarkerOccurrenceReviewError(
            "Marker-review evidence uses an obsolete marker policy and must be rescanned."
        )
    sampling_rate = _fraction(
        event_plan.get("sfreq", marker_plan.get("sampling_rate_hz")),
        field_name="sampling_rate_hz",
    )
    if sampling_rate <= 0:
        raise MarkerOccurrenceReviewError(
            "Marker-review sampling rate must be positive."
        )
    first_samp = _required_int(event_plan, "first_samp")
    reasons_value = payload.get("review_reasons")
    if not _is_sequence(reasons_value):
        raise MarkerOccurrenceReviewError(
            "Marker-review occurrence has no review-reason list."
        )
    reasons = tuple(str(value).strip() for value in reasons_value if str(value).strip())
    (
        missing_gap_count,
        estimated_missing,
        early_or_extra_count,
        maximum_residual,
        interval_evidence,
    ) = _interval_summary(
        payload,
        sampling_rate_hz=sampling_rate,
        first_samp=first_samp,
    )
    return MarkerOccurrenceReviewItem(
        path=Path(result.path),
        participant_id=str(result.participant_id).strip(),
        recording_id=(
            str(result.recording_id).strip()
            if getattr(result, "recording_id", None)
            else None
        ),
        session_id=(
            str(result.session_id).strip()
            if getattr(result, "session_id", None)
            else None
        ),
        session_label=(
            str(result.session_label).strip()
            if getattr(result, "session_label", None)
            else None
        ),
        condition_label=str(payload.get("condition_label") or condition_code).strip(),
        condition_code=condition_code,
        repetition_index=repetition_index,
        occurrence_key=occurrence_key,
        marker_plan_fingerprint=_required_sha256(marker_plan, "fingerprint"),
        occurrence_fingerprint=_required_sha256(payload, "fingerprint"),
        sampling_rate_hz=sampling_rate,
        first_samp=first_samp,
        oddball_marker_code=_required_int(payload, "oddball_marker_code"),
        expected_analyzed_cycles=_required_int(payload, "expected_analyzed_cycles"),
        oddball_rate_hz=sampling_rate / interval,
        raw_marker_samples=raw_samples,
        retained_marker_samples=retained_samples,
        exact_duplicate_count=_duplicate_count(
            payload,
            raw_count=len(raw_samples),
            retained_count=len(retained_samples),
        ),
        missing_gap_count=missing_gap_count,
        estimated_missing_markers=estimated_missing,
        early_or_extra_count=early_or_extra_count,
        maximum_phase_residual_cycles=maximum_residual,
        interval_evidence=interval_evidence,
        proposed_start_sample=_optional_int(payload, "proposed_start_sample"),
        proposed_stop_sample=_optional_int(payload, "proposed_stop_sample"),
        contiguous_candidate_spans=_candidate_spans(payload),
        review_reasons=reasons,
    )


def collect_marker_occurrence_reviews(scan: Any) -> tuple[MarkerOccurrenceReviewItem, ...]:
    """Collect unresolved occurrences from a preflight scan, preserving scan order."""

    items: list[MarkerOccurrenceReviewItem] = []
    seen: set[tuple[str, str]] = set()
    for result in getattr(scan, "results", ()):
        condition_qc = getattr(result, "condition_qc", None)
        if not isinstance(condition_qc, Mapping):
            continue
        event_plan = condition_qc.get("event_plan")
        if not isinstance(event_plan, Mapping):
            continue
        unresolved = event_plan.get("unresolved_occurrences", ())
        if not _is_sequence(unresolved):
            raise MarkerOccurrenceReviewError(
                "Preflight event plan has no valid unresolved-occurrence list."
            )
        for payload in unresolved:
            item = _review_item(result, event_plan, payload)
            identity = (resolved_path_text(item.path).casefold(), item.occurrence_key)
            if identity in seen:
                raise MarkerOccurrenceReviewError(
                    "Preflight returned a duplicate unresolved marker occurrence."
                )
            seen.add(identity)
            items.append(item)
    return tuple(items)


def build_marker_review_decision(
    item: MarkerOccurrenceReviewItem,
    decision: str,
    *,
    evidence_type: str = "",
    evidence_note: str = "",
    evidence_reference: str = "",
    selected_span: tuple[int, int] | None = None,
    reason: str = "",
    reviewed_at_utc: str | None = None,
) -> dict[str, object]:
    """Validate and serialize one user decision for the marker planner."""

    normalized = str(decision).strip()
    review_time = _normalized_review_time(reviewed_at_utc)
    if normalized == MARKER_DECISION_RETAIN_FULL:
        evidence_type = evidence_type.strip()
        evidence_note = evidence_note.strip()
        evidence_reference = evidence_reference.strip()
        if not evidence_type or not (evidence_note or evidence_reference):
            raise MarkerOccurrenceReviewError(
                "Retaining the full occurrence requires an evidence type and a "
                "note or log reference."
            )
        if item.proposed_start_sample is None or item.proposed_stop_sample is None:
            raise MarkerOccurrenceReviewError(
                "This occurrence is too short for the declared analyzed cycles and "
                "cannot be retained without padding."
            )
        return {
            **_decision_receipt(
                item,
                decision=MARKER_DECISION_RETAIN_FULL,
                reason=reason,
                reviewed_at_utc=review_time,
            ),
            "evidence_type": evidence_type,
            "evidence_note": evidence_note or None,
            "evidence_reference": evidence_reference or None,
        }
    if normalized == MARKER_DECISION_USE_CONTIGUOUS:
        if selected_span is None:
            raise MarkerOccurrenceReviewError(
                "Choose one verified contiguous span supplied by the marker check."
            )
        try:
            span = (int(selected_span[0]), int(selected_span[1]))
        except (IndexError, TypeError, ValueError) as exc:
            raise MarkerOccurrenceReviewError(
                "The selected contiguous span is malformed."
            ) from exc
        if span not in item.contiguous_candidate_spans:
            raise MarkerOccurrenceReviewError(
                "The selected span was not supplied as a verified contiguous candidate."
            )
        return {
            **_decision_receipt(
                item,
                decision=MARKER_DECISION_USE_CONTIGUOUS,
                reason=reason,
                reviewed_at_utc=review_time,
            ),
            "verified_start_sample": span[0],
            "verified_stop_sample": span[1],
        }
    if normalized == MARKER_DECISION_EXCLUDE:
        return _decision_receipt(
            item,
            decision=MARKER_DECISION_EXCLUDE,
            reason=reason,
            reviewed_at_utc=review_time,
        )
    raise MarkerOccurrenceReviewError(
        f"Unsupported marker-review decision {normalized!r}."
    )


def _normalized_review_time(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    normalized = str(value).strip()
    if not normalized.endswith("Z"):
        raise MarkerOccurrenceReviewError(
            "Marker review time must be an ISO-8601 UTC timestamp ending in Z."
        )
    try:
        parsed = datetime.fromisoformat(normalized[:-1] + "+00:00")
    except ValueError as exc:
        raise MarkerOccurrenceReviewError(
            "Marker review time must be a valid ISO-8601 UTC timestamp."
        ) from exc
    if parsed.utcoffset() != timedelta(0):
        raise MarkerOccurrenceReviewError("Marker review time must be in UTC.")
    return normalized


def _decision_receipt(
    item: MarkerOccurrenceReviewItem,
    *,
    decision: str,
    reason: str,
    reviewed_at_utc: str,
) -> dict[str, object]:
    return {
        "schema_version": MARKER_REVIEW_DECISION_SCHEMA_VERSION,
        "decision": decision,
        "reason": str(reason or "").strip() or "No reason provided",
        "reviewed_at_utc": reviewed_at_utc,
        "reviewer_state": MARKER_REVIEWER_STATE_EXPLICIT_GUI,
        "reviewer_identity": None,
        "reviewer_identity_status": (
            MARKER_REVIEWER_IDENTITY_STATUS_NOT_COLLECTED
        ),
        "source_file_path": resolved_path_text(item.path),
        "participant_id": item.participant_id,
        "recording_id": item.recording_id,
        "session_id": item.session_id,
        "session_label": item.session_label,
        "condition_label": item.condition_label,
        "condition_code": item.condition_code,
        "repetition_index": item.repetition_index,
        "occurrence_key": item.occurrence_key,
        "reviewed_marker_plan_fingerprint": item.marker_plan_fingerprint,
        "reviewed_occurrence_fingerprint": item.occurrence_fingerprint,
    }


def merge_marker_review_decision(
    existing: object,
    *,
    file_path: str | Path,
    occurrence_key: str,
    decision: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Return decisions keyed by resolved file path and occurrence key."""

    merged: dict[str, dict[str, object]] = {}
    if isinstance(existing, Mapping):
        for raw_path, raw_decisions in existing.items():
            if not isinstance(raw_decisions, Mapping):
                continue
            path_key = resolved_path_text(str(raw_path))
            destination = merged.setdefault(path_key, {})
            for raw_key, raw_decision in raw_decisions.items():
                if isinstance(raw_decision, Mapping):
                    destination[str(raw_key)] = deepcopy(dict(raw_decision))
    path_key = resolved_path_text(file_path)
    current: dict[str, object] = {}
    for candidate in tuple(merged):
        if candidate.casefold() == path_key.casefold():
            current.update(merged.pop(candidate))
    current[str(occurrence_key)] = deepcopy(dict(decision))
    merged[path_key] = current
    return merged


def merge_rescanned_results(
    original_results: Sequence[Any],
    rescanned_results: Sequence[Any],
    *,
    affected_paths: Sequence[str | Path],
) -> tuple[Any, ...]:
    """Replace only affected file results while preserving the original order."""

    affected = {resolved_path_text(path).casefold() for path in affected_paths}
    replacements = {
        resolved_path_text(result.path).casefold(): result for result in rescanned_results
    }
    missing = affected - set(replacements)
    if missing:
        raise MarkerOccurrenceReviewError(
            "The marker-review rescan did not return every affected file."
        )
    return tuple(
        replacements[resolved_path_text(result.path).casefold()]
        if resolved_path_text(result.path).casefold() in affected
        else result
        for result in original_results
    )


def canonical_event_plans_by_file(scan: Any) -> dict[str, dict[str, object]]:
    """Extract one fully resolved canonical event plan for every scanned file."""

    plans: dict[str, dict[str, object]] = {}
    path_keys: set[str] = set()
    for result in getattr(scan, "results", ()):
        path = Path(result.path)
        condition_qc = getattr(result, "condition_qc", None)
        event_plan = (
            condition_qc.get("event_plan")
            if isinstance(condition_qc, Mapping)
            else None
        )
        if not isinstance(event_plan, Mapping):
            raise MarkerOccurrenceReviewError(
                f"No canonical preflight event plan is available for {path.name}."
            )
        unresolved = event_plan.get("unresolved_occurrences")
        if not _is_sequence(unresolved):
            raise MarkerOccurrenceReviewError(
                f"The preflight event plan for {path.name} is malformed."
            )
        if unresolved:
            raise MarkerOccurrenceReviewError(
                f"Marker review is still unresolved for {path.name}."
            )
        path_key = resolved_path_text(path)
        folded = path_key.casefold()
        if folded in path_keys:
            raise MarkerOccurrenceReviewError(
                f"Preflight returned duplicate event plans for {path.name}."
            )
        path_keys.add(folded)
        plans[path_key] = deepcopy(dict(event_plan))
    return plans


def _fraction_display(value: Fraction) -> str:
    numeric = float(value)
    return f"{numeric:.6g}"


def _sample_seconds(item: MarkerOccurrenceReviewItem, sample: int) -> Fraction:
    return Fraction(int(sample) - item.first_samp) / item.sampling_rate_hz


def _sample_times_display(
    item: MarkerOccurrenceReviewItem,
    samples: Sequence[int],
) -> str:
    if not samples:
        return "None"
    return ", ".join(
        f"{_fraction_display(_sample_seconds(item, sample))} s"
        for sample in samples
    )


def _span_display(
    item: MarkerOccurrenceReviewItem,
    start: int,
    stop: int,
) -> str:
    start_seconds = _sample_seconds(item, start)
    stop_seconds = _sample_seconds(item, stop)
    duration_seconds = Fraction(stop - start) / item.sampling_rate_hz
    return (
        f"[{start}, {stop}) samples; {_fraction_display(start_seconds)} to "
        f"{_fraction_display(stop_seconds)} s from recording start "
        f"({_fraction_display(duration_seconds)} s duration)"
    )


@dataclass(frozen=True, slots=True)
class MarkerReviewChoice:
    decision: str
    label: str
    description: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class MarkerOccurrenceReviewSummary:
    context: str
    source: str
    finding: str
    required_analysis: str
    choices: tuple[MarkerReviewChoice, ...]


def marker_occurrence_review_summary(
    item: MarkerOccurrenceReviewItem,
) -> MarkerOccurrenceReviewSummary:
    """Explain existing evidence and choices without selecting or changing data."""
    duration = _fraction_display(Fraction(item.expected_analyzed_cycles) / item.oddball_rate_hz)
    findings: list[str] = []
    reasons = set(item.review_reasons)
    if "insufficient_project_oddball_markers" in reasons:
        findings.append(f"Fewer than two distinct markers with the project's code {item.oddball_marker_code} were found.")
    if "shorter_than_expected_analyzed_cycles" in reasons:
        findings.append(f"The markers cover less than the required {duration} seconds of data.")
    if item.missing_gap_count:
        gaps = "gap" if item.missing_gap_count == 1 else "gaps"
        missing = "marker" if item.estimated_missing_markers == 1 else "markers"
        findings.append(
            f"Long marker {gaps}: {item.missing_gap_count}; about "
            f"{item.estimated_missing_markers} {missing} may be missing."
        )
    if item.early_or_extra_count:
        intervals = "interval was" if item.early_or_extra_count == 1 else "intervals were"
        findings.append(f"{item.early_or_extra_count} marker {intervals} unusually short.")
    if not findings:
        findings.append("The marker timing needs review before this repetition can be analyzed.")
    findings.append("Markers alone cannot tell whether the visual stimulation was interrupted.")

    candidate_count = len(item.contiguous_candidate_spans)
    windows = "window" if candidate_count == 1 else "windows"
    verified = (
        f"{candidate_count} {windows} passed the marker-spacing check. "
        f"Use {duration} seconds; data outside that window will not enter this repetition's analysis."
        if candidate_count else
        f"Unavailable: no uninterrupted marker sequence provides the required {duration} seconds."
    )
    full_available = item.proposed_start_sample is not None and item.proposed_stop_sample is not None
    planned = (
        f"Keep the planned {duration}-second window despite the marker finding. "
        "Requires a log, photodiode trace or other independent evidence that stimulation stayed continuous and correctly timed."
        if full_available else
        "Unavailable: the markers do not define a long enough planned analysis window."
    )
    context = " · ".join(value for value in (
        item.participant_id or "Unknown participant", item.session_label or item.session_id,
        item.condition_label, f"Repetition {item.repetition_index + 1}",
    ) if value)
    source = " · ".join(dict.fromkeys(value for value in (item.path.name, item.recording_id) if value))
    return MarkerOccurrenceReviewSummary(
        context=context,
        source=source,
        finding=" ".join(findings),
        required_analysis=f"Each retained window must contain {item.expected_analyzed_cycles} oddball cycles ({duration} seconds).",
        choices=(
            MarkerReviewChoice(MARKER_DECISION_USE_CONTIGUOUS, "Use verified window…", verified, bool(candidate_count)),
            MarkerReviewChoice(MARKER_DECISION_RETAIN_FULL, "Keep planned window…", planned, full_available),
            MarkerReviewChoice(
                MARKER_DECISION_EXCLUDE, "Exclude this repetition…",
                "Leave this condition repetition out of analysis. Other repetitions remain eligible; the raw file is kept.",
                True,
            ),
        ),
    )


def marker_occurrence_review_rows(
    item: MarkerOccurrenceReviewItem,
) -> tuple[tuple[str, str], ...]:
    """Return the complete, user-facing evidence rows for one occurrence."""

    proposed = (
        _span_display(
            item,
            item.proposed_start_sample,
            item.proposed_stop_sample,
        )
        if item.proposed_start_sample is not None
        and item.proposed_stop_sample is not None
        else "Unavailable; occurrence is shorter than the required analysis"
    )
    candidates = (
        " | ".join(
            _span_display(item, start, stop)
            for start, stop in item.contiguous_candidate_spans
        )
        if item.contiguous_candidate_spans
        else "None"
    )
    interval_evidence = (
        " | ".join(item.interval_evidence)
        if item.interval_evidence
        else "No interval was classified as a gap, early/extra, or off phase"
    )
    reasons = ", ".join(reason.replace("_", " ") for reason in item.review_reasons)
    return (
        ("Participant", item.participant_id or "Unknown"),
        ("Recording", item.recording_id or "Legacy participant-level recording"),
        ("Session / phase-at-visit", item.session_label or "Not registered"),
        ("Source file", item.path.name),
        (
            "Condition occurrence",
            f"{item.condition_label} (code {item.condition_code}), repetition "
            f"{item.repetition_index + 1} (index {item.repetition_index})",
        ),
        ("Oddball marker code", str(item.oddball_marker_code)),
        (
            "Expected analysis",
            f"{item.expected_analyzed_cycles} oddball cycles at "
            f"{_fraction_display(item.oddball_rate_hz)} Hz",
        ),
        (
            "Marker counts",
            f"{len(item.raw_marker_samples)} raw; "
            f"{len(item.retained_marker_samples)} retained",
        ),
        ("Exact same-sample duplicates collapsed", str(item.exact_duplicate_count)),
        (
            "Gaps and early/extra markers",
            f"{item.missing_gap_count} gap(s), about "
            f"{item.estimated_missing_markers} missing marker(s); "
            f"{item.early_or_extra_count} early/extra interval(s)",
        ),
        (
            "Maximum phase residual",
            f"{_fraction_display(item.maximum_phase_residual_cycles)} oddball cycles",
        ),
        ("Proposed full crop", proposed),
        ("Verified contiguous candidates", candidates),
        ("Review reasons", reasons or "Unspecified marker-integrity finding"),
        ("Raw marker samples", ", ".join(map(str, item.raw_marker_samples)) or "None"),
        (
            "Raw marker times from recording start",
            _sample_times_display(item, item.raw_marker_samples),
        ),
        (
            "Retained marker samples",
            ", ".join(map(str, item.retained_marker_samples)) or "None",
        ),
        (
            "Retained marker times from recording start",
            _sample_times_display(item, item.retained_marker_samples),
        ),
        ("Flagged interval evidence", interval_evidence),
    )


__all__ = [
    "MARKER_DECISION_EXCLUDE",
    "MARKER_DECISION_RETAIN_FULL",
    "MARKER_DECISION_USE_CONTIGUOUS",
    "MarkerOccurrenceReviewError",
    "MarkerOccurrenceReviewItem",
    "MarkerOccurrenceReviewSummary",
    "MarkerReviewChoice",
    "build_marker_review_decision",
    "canonical_event_plans_by_file",
    "collect_marker_occurrence_reviews",
    "marker_occurrence_review_rows",
    "marker_occurrence_review_summary",
    "merge_marker_review_decision",
    "merge_rescanned_results",
    "resolved_path_text",
]
