"""GUI-neutral QC-07 review collection and decision application."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Main_App.processing.interpolation_burden import (
    INTERPOLATION_BURDEN_DECISION_EXCLUDE,
    INTERPOLATION_BURDEN_DECISION_RETAIN,
    INTERPOLATION_BURDEN_SCOPE_PARTICIPANT,
    INTERPOLATION_BURDEN_SCOPE_RECORDING,
    InterpolationBurdenError,
    InterpolationBurdenReviewDecision,
    InterpolationBurdenReviewFinding,
    build_interpolation_burden_review_decision,
    interpolation_burden_decision_is_current,
    interpolation_burden_review_finding,
    normalize_interpolation_burden,
    normalize_interpolation_burden_review_decision,
)
from Main_App.processing.processing_ledger import load_ledger
from Main_App.projects.preprocessing_settings import (
    INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY,
    normalize_manual_excluded_participants,
    normalize_manual_excluded_recordings,
)
from Main_App.projects.recordings import project_recording_context


class InterpolationBurdenReviewError(RuntimeError):
    """Raised when QC-07 review evidence or choices cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class InterpolationBurdenReviewItem:
    """One current above-threshold finding that needs an explicit decision."""

    finding: InterpolationBurdenReviewFinding
    participant_id: str
    recording_id: str | None
    session_id: str | None
    session_label: str | None
    visit_index: int | None
    group_label: str | None
    default_scope: str
    evidence_status: str

    @property
    def processing_id(self) -> str:
        return self.finding.recording_id


@dataclass(frozen=True, slots=True)
class InterpolationBurdenReviewBatch:
    """Current ledger findings split into pending and already reviewed rows."""

    items: tuple[InterpolationBurdenReviewItem, ...]
    flagged_recording_count: int
    current_decision_count: int
    stale_decision_count: int
    is_repeated_session: bool

    @property
    def requires_review(self) -> bool:
        return bool(self.items)


@dataclass(frozen=True, slots=True)
class InterpolationBurdenReviewChoice:
    """One explicit GUI choice; an empty decision is never valid."""

    decision: str
    reason: str
    exclusion_scope: str

    def __post_init__(self) -> None:
        if self.decision not in {
            INTERPOLATION_BURDEN_DECISION_RETAIN,
            INTERPOLATION_BURDEN_DECISION_EXCLUDE,
        }:
            raise InterpolationBurdenReviewError(
                "Choose Retain or Exclude for every interpolation-burden finding."
            )
        if not str(self.reason or "").strip():
            object.__setattr__(self, "reason", "No reason provided")
        if self.exclusion_scope not in {
            INTERPOLATION_BURDEN_SCOPE_PARTICIPANT,
            INTERPOLATION_BURDEN_SCOPE_RECORDING,
        }:
            raise InterpolationBurdenReviewError(
                "Interpolation-burden decision scope is invalid."
            )


@dataclass(frozen=True, slots=True)
class InterpolationBurdenReviewApplication:
    """Persisted decision result and the canonical downstream exclusions."""

    decisions: tuple[InterpolationBurdenReviewDecision, ...]
    excluded_participants: tuple[str, ...]
    excluded_recordings: tuple[str, ...]


def _decision_lookup(
    value: object,
) -> tuple[dict[str, InterpolationBurdenReviewDecision], set[str]]:
    if value in (None, ""):
        return {}, set()
    if not isinstance(value, Mapping):
        raise InterpolationBurdenReviewError(
            "Interpolation-burden decisions must be a recording-to-decision map."
        )
    decisions: dict[str, InterpolationBurdenReviewDecision] = {}
    invalid_keys: set[str] = set()
    for raw_key, raw_decision in value.items():
        key = str(raw_key or "").strip()
        if not key:
            raise InterpolationBurdenReviewError(
                "Interpolation-burden decision history is malformed."
            )
        if not isinstance(raw_decision, Mapping):
            invalid_keys.add(key.casefold())
            continue
        try:
            decision = normalize_interpolation_burden_review_decision(raw_decision)
        except InterpolationBurdenError:
            # A malformed receipt associated with current evidence must be shown
            # again instead of being accepted as a completed review.
            invalid_keys.add(key.casefold())
            continue
        if key.casefold() != decision.processing_id.casefold():
            invalid_keys.add(key.casefold())
            continue
        decisions[key.casefold()] = decision
    return decisions, invalid_keys


def _canonical_identity(
    *,
    processing_id: str,
    entry: Mapping[str, Any],
    repeated_session: bool,
    recordings_by_id: Mapping[str, Any],
) -> tuple[str, str | None, str | None, str | None, int | None]:
    participant_id = str(entry.get("participant_id") or "").strip()
    if not participant_id:
        raise InterpolationBurdenReviewError(
            f"QC-07 ledger entry '{processing_id}' has no participant identity."
        )
    if not repeated_session:
        if processing_id.casefold() != participant_id.casefold():
            raise InterpolationBurdenReviewError(
                "Ordinary-project interpolation burden is not keyed by its canonical "
                f"participant identity: {processing_id}."
            )
        return participant_id, None, None, None, None

    recording_id = str(entry.get("recording_id") or processing_id).strip()
    recording = recordings_by_id.get(recording_id.casefold())
    if recording is None:
        raise InterpolationBurdenReviewError(
            f"QC-07 ledger recording '{recording_id}' is not registered in project.json."
        )
    if processing_id.casefold() != recording.recording_id.casefold():
        raise InterpolationBurdenReviewError(
            f"QC-07 ledger key '{processing_id}' does not match recording "
            f"'{recording.recording_id}'."
        )
    if participant_id.casefold() != recording.participant_id.casefold():
        raise InterpolationBurdenReviewError(
            f"QC-07 ledger participant for '{recording_id}' does not match project.json."
        )
    return (
        recording.participant_id,
        recording.recording_id,
        recording.session_id,
        None,
        recording.visit_index,
    )


def _decision_matches_application_state(
    decision: InterpolationBurdenReviewDecision,
    *,
    item_participant_id: str,
    item_recording_id: str | None,
    is_repeated_session: bool,
    excluded_participants: set[str],
    excluded_recordings: set[str],
) -> bool:
    if decision.participant_id.casefold() != item_participant_id.casefold():
        return False
    if not is_repeated_session:
        if decision.exclusion_scope != INTERPOLATION_BURDEN_SCOPE_PARTICIPANT:
            return False
    elif (
        decision.exclusion_scope == INTERPOLATION_BURDEN_SCOPE_RECORDING
        and item_recording_id is None
    ):
        return False
    if decision.decision != INTERPOLATION_BURDEN_DECISION_EXCLUDE:
        return True
    if decision.exclusion_scope == INTERPOLATION_BURDEN_SCOPE_PARTICIPANT:
        return decision.participant_id.casefold() in excluded_participants
    return (
        item_recording_id is not None
        and item_recording_id.casefold() in excluded_recordings
    )


def collect_interpolation_burden_review(
    project: Any,
    *,
    ledger: Mapping[str, Any] | None = None,
) -> InterpolationBurdenReviewBatch:
    """Collect current strict->5% findings that lack a current applied decision."""

    project_root = Path(getattr(project, "project_root")).resolve(strict=False)
    ledger_payload = load_ledger(project_root) if ledger is None else ledger
    entries = ledger_payload.get("entries") if isinstance(ledger_payload, Mapping) else None
    if not isinstance(entries, Mapping):
        raise InterpolationBurdenReviewError(
            "The processing ledger does not contain a valid entries map."
        )

    context = project_recording_context(project)
    repeated_session = context.is_repeated_session
    recordings_by_id = {
        recording.recording_id.casefold(): recording
        for recording in context.recordings
    }
    sessions_by_id = {
        session.session_id.casefold(): session for session in context.sessions
    }
    group_labels = {group.group_id.casefold(): group.label for group in context.groups}
    participant_groups = {
        participant.participant_id.casefold(): (
            group_labels.get(participant.group_id.casefold())
            if participant.group_id is not None
            else None
        )
        for participant in context.participants
    }

    preprocessing = getattr(project, "preprocessing", {}) or {}
    decisions, invalid_decision_keys = _decision_lookup(
        preprocessing.get(INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY)
        if isinstance(preprocessing, Mapping)
        else None
    )
    excluded_participants = {
        value.casefold()
        for value in normalize_manual_excluded_participants(
            preprocessing.get("manual_excluded_participants")
            if isinstance(preprocessing, Mapping)
            else None
        )
    }
    excluded_recordings = {
        value.casefold()
        for value in normalize_manual_excluded_recordings(
            preprocessing.get("manual_excluded_recordings")
            if isinstance(preprocessing, Mapping)
            else None
        )
    }

    pending: list[InterpolationBurdenReviewItem] = []
    flagged_count = 0
    current_count = 0
    stale_count = 0
    for raw_processing_id, raw_entry in sorted(
        entries.items(), key=lambda item: str(item[0]).casefold()
    ):
        processing_id = str(raw_processing_id or "").strip()
        if not processing_id or not isinstance(raw_entry, Mapping):
            continue
        if str(raw_entry.get("status") or "").strip().casefold() != "completed":
            continue
        raw_burden = raw_entry.get("interpolation_burden")
        if raw_burden is None:
            continue
        if not isinstance(raw_burden, Mapping):
            raise InterpolationBurdenReviewError(
                f"QC-07 burden evidence for '{processing_id}' is malformed."
            )
        try:
            burden = normalize_interpolation_burden(raw_burden)
            finding = interpolation_burden_review_finding(processing_id, burden)
        except InterpolationBurdenError as exc:
            raise InterpolationBurdenReviewError(
                f"QC-07 burden evidence for '{processing_id}' is invalid: {exc}"
            ) from exc
        if finding is None:
            continue
        flagged_count += 1
        (
            participant_id,
            recording_id,
            session_id,
            _session_label,
            visit_index,
        ) = _canonical_identity(
            processing_id=processing_id,
            entry=raw_entry,
            repeated_session=repeated_session,
            recordings_by_id=recordings_by_id,
        )
        session = (
            sessions_by_id.get(str(session_id).casefold())
            if session_id is not None
            else None
        )
        session_label = session.label if session is not None else None
        current = decisions.get(processing_id.casefold())
        decision_current = bool(
            current is not None
            and interpolation_burden_decision_is_current(finding, current)
            and _decision_matches_application_state(
                current,
                item_participant_id=participant_id,
                item_recording_id=recording_id,
                is_repeated_session=repeated_session,
                excluded_participants=excluded_participants,
                excluded_recordings=excluded_recordings,
            )
        )
        if decision_current:
            current_count += 1
            continue
        evidence_status = (
            "stale"
            if current is not None
            or processing_id.casefold() in invalid_decision_keys
            else "new"
        )
        stale_count += int(evidence_status == "stale")
        pending.append(
            InterpolationBurdenReviewItem(
                finding=finding,
                participant_id=participant_id,
                recording_id=recording_id,
                session_id=session_id,
                session_label=session_label,
                visit_index=visit_index,
                group_label=participant_groups.get(participant_id.casefold()),
                default_scope=(
                    INTERPOLATION_BURDEN_SCOPE_RECORDING
                    if repeated_session
                    else INTERPOLATION_BURDEN_SCOPE_PARTICIPANT
                ),
                evidence_status=evidence_status,
            )
        )

    return InterpolationBurdenReviewBatch(
        items=tuple(pending),
        flagged_recording_count=flagged_count,
        current_decision_count=current_count,
        stale_decision_count=stale_count,
        is_repeated_session=repeated_session,
    )


def _decision_target(
    decision: InterpolationBurdenReviewDecision,
) -> tuple[str, str]:
    if decision.exclusion_scope == INTERPOLATION_BURDEN_SCOPE_PARTICIPANT:
        return (INTERPOLATION_BURDEN_SCOPE_PARTICIPANT, decision.participant_id)
    return (INTERPOLATION_BURDEN_SCOPE_RECORDING, decision.processing_id)


def apply_interpolation_burden_review(
    project: Any,
    batch: InterpolationBurdenReviewBatch,
    choices: Mapping[str, InterpolationBurdenReviewChoice],
) -> InterpolationBurdenReviewApplication:
    """Persist all pending receipts and update canonical downstream exclusions."""

    expected = {item.processing_id.casefold(): item for item in batch.items}
    supplied = {str(key).strip().casefold(): value for key, value in choices.items()}
    if set(supplied) != set(expected):
        raise InterpolationBurdenReviewError(
            "Every pending interpolation-burden finding requires one explicit decision."
        )
    if any(not isinstance(choice, InterpolationBurdenReviewChoice) for choice in supplied.values()):
        raise InterpolationBurdenReviewError(
            "Interpolation-burden choices are malformed."
        )

    raw_preprocessing = getattr(project, "preprocessing", {}) or {}
    preprocessing = dict(raw_preprocessing) if isinstance(raw_preprocessing, Mapping) else {}
    existing_decisions, invalid_decision_keys = _decision_lookup(
        preprocessing.get(INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY)
    )
    unresolved_invalid = invalid_decision_keys.difference(expected)
    if unresolved_invalid:
        raise InterpolationBurdenReviewError(
            "Interpolation-burden decision history contains an invalid receipt "
            "that is not part of the current review."
        )
    excluded_participants = normalize_manual_excluded_participants(
        preprocessing.get("manual_excluded_participants")
    )
    excluded_recordings = normalize_manual_excluded_recordings(
        preprocessing.get("manual_excluded_recordings")
    )
    participant_lookup = {value.casefold(): value for value in excluded_participants}
    recording_lookup = {value.casefold(): value for value in excluded_recordings}

    prior_owned_targets = {
        (scope, target.casefold())
        for decision in existing_decisions.values()
        if decision.decision == INTERPOLATION_BURDEN_DECISION_EXCLUDE
        and decision.owns_canonical_exclusion
        for scope, target in (_decision_target(decision),)
    }
    externally_owned_targets = {
        (INTERPOLATION_BURDEN_SCOPE_PARTICIPANT, key)
        for key in participant_lookup
        if (INTERPOLATION_BURDEN_SCOPE_PARTICIPANT, key)
        not in prior_owned_targets
    } | {
        (INTERPOLATION_BURDEN_SCOPE_RECORDING, key)
        for key in recording_lookup
        if (INTERPOLATION_BURDEN_SCOPE_RECORDING, key)
        not in prior_owned_targets
    }

    reviewed: list[InterpolationBurdenReviewDecision] = []
    for key, item in expected.items():
        choice = supplied[key]
        scope = choice.exclusion_scope
        if not batch.is_repeated_session:
            if scope != INTERPOLATION_BURDEN_SCOPE_PARTICIPANT:
                raise InterpolationBurdenReviewError(
                    "Ordinary projects require participant-scoped QC-07 decisions."
                )
        elif scope == INTERPOLATION_BURDEN_SCOPE_RECORDING and item.recording_id is None:
            raise InterpolationBurdenReviewError(
                f"Recording scope is unavailable for '{item.processing_id}'."
            )
        target = (
            item.participant_id
            if scope == INTERPOLATION_BURDEN_SCOPE_PARTICIPANT
            else str(item.recording_id)
        )
        owns_exclusion = bool(
            choice.decision == INTERPOLATION_BURDEN_DECISION_EXCLUDE
            and (scope, target.casefold()) not in externally_owned_targets
        )
        decision = build_interpolation_burden_review_decision(
            item.finding,
            participant_id=item.participant_id,
            decision=choice.decision,
            reason=choice.reason,
            exclusion_scope=scope,
            owns_canonical_exclusion=owns_exclusion,
        )
        existing_decisions[key] = decision
        reviewed.append(decision)

    final_owned_targets = {
        (scope, target.casefold())
        for decision in existing_decisions.values()
        if decision.decision == INTERPOLATION_BURDEN_DECISION_EXCLUDE
        and decision.owns_canonical_exclusion
        for scope, target in (_decision_target(decision),)
    }
    for scope, target_key in prior_owned_targets - final_owned_targets:
        if scope == INTERPOLATION_BURDEN_SCOPE_PARTICIPANT:
            participant_lookup.pop(target_key, None)
        else:
            recording_lookup.pop(target_key, None)
    for decision in existing_decisions.values():
        if (
            decision.decision != INTERPOLATION_BURDEN_DECISION_EXCLUDE
            or not decision.owns_canonical_exclusion
        ):
            continue
        scope, target = _decision_target(decision)
        if scope == INTERPOLATION_BURDEN_SCOPE_PARTICIPANT:
            participant_lookup.setdefault(target.casefold(), target)
        else:
            recording_lookup.setdefault(target.casefold(), target)

    preprocessing[INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY] = {
        decision.processing_id: decision.to_payload()
        for decision in sorted(
            existing_decisions.values(), key=lambda item: item.processing_id.casefold()
        )
    }
    preprocessing["manual_excluded_participants"] = list(participant_lookup.values())
    preprocessing["manual_excluded_recordings"] = list(recording_lookup.values())

    old_preprocessing = copy.deepcopy(getattr(project, "preprocessing", {}))
    old_manifest = copy.deepcopy(getattr(project, "manifest", {}))
    try:
        normalized = project.update_preprocessing(preprocessing)
        project.save()
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        project.preprocessing = old_preprocessing
        project.manifest = old_manifest
        raise InterpolationBurdenReviewError(
            f"Could not save interpolation-burden decisions: {exc}"
        ) from exc

    return InterpolationBurdenReviewApplication(
        decisions=tuple(reviewed),
        excluded_participants=tuple(
            normalize_manual_excluded_participants(
                normalized.get("manual_excluded_participants")
            )
        ),
        excluded_recordings=tuple(
            normalize_manual_excluded_recordings(
                normalized.get("manual_excluded_recordings")
            )
        ),
    )


__all__ = [
    "InterpolationBurdenReviewApplication",
    "InterpolationBurdenReviewBatch",
    "InterpolationBurdenReviewChoice",
    "InterpolationBurdenReviewError",
    "InterpolationBurdenReviewItem",
    "apply_interpolation_burden_review",
    "collect_interpolation_burden_review",
]
