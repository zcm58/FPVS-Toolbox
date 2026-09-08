"""Pure presentation grouping for existing summed-BCA review findings."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from Main_App.processing.frequency_domain_qc import (
    DECISION_EXCLUDE_CONDITION,
    DECISION_EXCLUDE_PARTICIPANT,
    DECISION_EXCLUDE_RECORDING,
    DECISION_INTERPOLATE_CONDITION_ELECTRODE,
    DECISION_RETAIN,
    REVIEW_DECISIONS,
    is_roi_frequency_qc_entry,
    validate_frequency_domain_qc_review_decisions,
)


FindingSection = Literal["electrode", "other"] | None
ElectrodeGroupKey = tuple[str, str, str]


@dataclass(frozen=True)
class ReviewIssue:
    index: int
    kind: Literal["choice", "confirmation", "conflict", "invalid"]
    message: str


def review_attention(
    findings: Sequence[Mapping[str, object]],
    decisions: Mapping[str, Mapping[str, object]],
    identity_scope: str,
    interpolation_enabled: object,
    *,
    report: Mapping[str, object] | None = None,
) -> tuple[ReviewIssue, ...]:
    """Describe attention targets without changing choices or granting authority.

    The backend validator still owns submission. These presentation checks use
    its normalized identities and consistency rules; parity tests cover both.
    """
    issues: list[ReviewIssue] = []
    identity_scope = _text(identity_scope).casefold()
    selected: dict[int, str] = {}
    groups: dict[tuple[str, ...], list[int]] = {}
    fingerprints = [_text(item.get("finding_fingerprint")) for item in findings]
    duplicates = {key for key, count in Counter(fingerprints).items() if count > 1}
    for index, item in enumerate(findings):
        key = fingerprints[index]
        choice = decisions.get(key, {})
        decision = _text(choice.get("decision")).casefold()
        selected[index] = decision
        participant = _text(item.get("participant_id")).upper()
        recording = _text(item.get("recording_id")).upper()
        condition = _text(item.get("condition"))
        electrode = _text(item.get("electrode")).upper()
        if (not key or key in duplicates or not participant or not condition or not electrode
                or (identity_scope == "recording" and not recording)):
            issues.append(ReviewIssue(index, "invalid", "Finding identity is incomplete or duplicated; regenerate the review."))
        elif not decision:
            issues.append(ReviewIssue(index, "choice", "Choose a decision for this finding."))
        elif decision not in REVIEW_DECISIONS or (
            decision == DECISION_EXCLUDE_RECORDING and identity_scope != "recording"
        ):
            issues.append(ReviewIssue(index, "invalid", "Choose an available decision for this finding."))
        elif decision == DECISION_INTERPOLATE_CONDITION_ELECTRODE:
            if not can_interpolate_finding(item, identity_scope, interpolation_enabled):
                issues.append(ReviewIssue(index, "invalid", "This finding is not eligible for the enabled condition-electrode repair."))
            elif choice.get("artifact_confirmed") is not True:
                issues.append(ReviewIssue(index, "confirmation", "Confirm an artifact from the signal or independent evidence before requesting repair."))
        identity = recording or participant
        for group in (("participant", participant), ("recording", recording),
                      ("condition", identity, condition), ("electrode", identity, condition, electrode)):
            if group[1]:
                groups.setdefault(group, []).append(index)
    broad_choices = {
        "participant": DECISION_EXCLUDE_PARTICIPANT,
        "recording": DECISION_EXCLUDE_RECORDING,
        "condition": DECISION_EXCLUDE_CONDITION,
        "electrode": DECISION_INTERPOLATE_CONDITION_ELECTRODE,
    }
    conflicting: set[int] = set()
    for group, indices in groups.items():
        values = {selected[index] for index in indices if selected[index]}
        if broad_choices[group[0]] not in values or len(values) < 2:
            continue
        scope = " / ".join(group[1:])
        message = f"Conflicting {group[0]} choices for {scope}. Review each finding in this scope; choices must agree."
        for index in indices:
            if selected[index] and index not in conflicting:
                issues.append(ReviewIssue(index, "conflict", message))
                conflicting.add(index)
    if not issues and report is not None:
        # Only claim ready after the same I/O-free submission validator accepts
        # the complete report. Unexpected report-level failures have no row to
        # edit; retain their actual diagnostic instead of promising readiness.
        try:
            validate_frequency_domain_qc_review_decisions(report, decisions)
        except ValueError as exc:
            issues.append(ReviewIssue(-1, "invalid", str(exc)))
    return tuple(sorted(issues, key=lambda issue: issue.index))


def decision_consequence(item: Mapping[str, object], decision: str) -> str:
    """Explain the existing scientific scope, including unflagged outputs."""
    participant = _text(item.get("participant_id"))
    recording = _text(item.get("recording_id"))
    identity = f"participant {participant}" + (f", recording {recording}" if recording else "")
    condition = _text(item.get("condition"))
    if decision == DECISION_RETAIN:
        return "Retain adds no exclusion from this finding. Independent exclusions remain active; this does not certify artifact-free data."
    if decision == DECISION_EXCLUDE_CONDITION:
        return f"Exclude all electrodes in condition {condition} for {identity}, including unflagged data. Original processed files stay unchanged."
    if decision == DECISION_EXCLUDE_RECORDING:
        return f"Exclude every condition in {identity}, including unflagged data. Original processed files stay unchanged."
    if decision == DECISION_EXCLUDE_PARTICIPANT:
        return f"Exclude every recording and condition for participant {participant}, including unflagged data. Original processed files stay unchanged."
    if decision == DECISION_INTERPOLATE_CONDITION_ELECTRODE:
        return (
            f"Repair electrode {_text(item.get('electrode'))} in condition {condition} for {identity}. "
            "Reapply average reference, which can change other channels in those intervals, then regenerate outputs and review QC again."
        )
    return "Choose a decision to see its effect. A large response alone does not establish an artifact."


def can_interpolate_finding(
    item: Mapping[str, object], identity_scope: str, enabled: object,
) -> bool:
    """Offer repair only for an explicitly enabled, complete electrode target."""

    return enabled is True and electrode_group_key(item, identity_scope) is not None


def finding_section(item: Mapping[str, object]) -> FindingSection:
    """Separate target identities, including prior-decision reconfirmations.

    Retired ROI findings are omitted, including historical decisions. Other
    incomplete targets remain visible without electrode bulk actions.
    """

    if is_roi_frequency_qc_entry(item):
        return None
    if _text(item.get("electrode")):
        return "electrode"
    return "other"


def electrode_group_key(
    item: Mapping[str, object], identity_scope: str,
) -> ElectrodeGroupKey | None:
    """Identify one participant's electrode within its exact recording.

    Conditions intentionally do not form part of this presentation key. Every
    member must still identify an existing condition and evidence fingerprint;
    callers apply choices to those original findings, never to new conditions.
    Report identities retain their canonical spelling and case.
    """

    scope = _text(identity_scope).casefold()
    if scope not in {"participant", "recording"}:
        return None
    if finding_section(item) != "electrode":
        return None
    participant_id = _text(item.get("participant_id"))
    recording_id = _text(item.get("recording_id"))
    if not participant_id or (scope == "recording" and not recording_id):
        return None
    if not _text(item.get("condition")) or not _text(item.get("finding_fingerprint")):
        return None
    return participant_id, recording_id, _text(item.get("electrode"))


def electrode_groups(
    findings: Sequence[Mapping[str, object]], identity_scope: str,
) -> dict[ElectrodeGroupKey, tuple[int, ...]]:
    """Return original finding indices grouped in first-seen order."""

    grouped: dict[ElectrodeGroupKey, list[int]] = {}
    for index, item in enumerate(findings):
        key = electrode_group_key(item, identity_scope)
        if key is not None:
            grouped.setdefault(key, []).append(index)
    return {key: tuple(indices) for key, indices in grouped.items()}


def _text(value: object) -> str:
    return str(value or "").strip()
