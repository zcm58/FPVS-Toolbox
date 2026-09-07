"""Pure presentation grouping for existing summed-BCA review findings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal


FindingSection = Literal["electrode", "roi", "other"]
ElectrodeGroupKey = tuple[str, str, str]


def finding_section(item: Mapping[str, object]) -> FindingSection:
    """Separate target identities, including prior-decision reconfirmations.

    Finding types describe evidence rather than target identity. Ambiguous or
    incomplete targets remain visible as other findings without bulk actions.
    """

    electrode = _text(item.get("electrode"))
    roi = _text(item.get("roi"))
    if electrode and not roi:
        return "electrode"
    if roi and not electrode:
        return "roi"
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
