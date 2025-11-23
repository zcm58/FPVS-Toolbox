"""Subject ID and group utilities for the Stats tool."""
from __future__ import annotations

import logging
import re
from pathlib import Path

_CANONICAL_SUBJECT_PATTERN = re.compile(r"^(P\d+|Sub\d+|S\d+)", re.IGNORECASE)

logger = logging.getLogger(__name__)


def canonical_subject_id(raw_id: str) -> str:
    """
    Derive a phase-agnostic subject ID from a raw Stats subject ID.

    Examples:
      - 'P10BCF' -> 'P10'
      - 'P10BCL' -> 'P10'
      - 'P2CGF'  -> 'P2'
      - 'P2CGL'  -> 'P2'
      - 'P1'     -> 'P1'
      - 'XYZ123' -> 'XYZ123' (no change if it doesn't match the pattern)
    """

    match = _CANONICAL_SUBJECT_PATTERN.match(raw_id)
    return match.group(1) if match else raw_id


def canonical_group_and_phase_from_manifest(
    group_name: str, group_entry: dict
) -> tuple[str, str]:
    """
    Given a project.json group entry, derive (base_group, phase).

    Prefer explicit 'base_group' and 'phase' keys if present.
    Otherwise, fall back to heuristics based on group_name and
    group_entry['raw_input_folder'].

    Returns:
      base_group: canonical between-subject group label (e.g. "Control", "BC")
      phase: phase label for this project (e.g. "Luteal", "Follicular")
    """

    base_group = str(group_entry.get("base_group", "")).strip()
    phase = str(group_entry.get("phase", "")).strip()

    raw_input_folder = str(group_entry.get("raw_input_folder", "") or "")
    raw_input_name = Path(raw_input_folder).name

    def _detect_phase(candidate: str) -> str:
        lowered = candidate.lower()
        if "luteal" in lowered:
            return "Luteal"
        if "follicular" in lowered:
            return "Follicular"
        return ""

    inferred_phase = phase or _detect_phase(group_name) or _detect_phase(raw_input_name)
    phase = inferred_phase

    cleaned_group = group_name
    if phase:
        cleaned_group = re.sub(phase, "", cleaned_group, flags=re.IGNORECASE)
    cleaned_group = " ".join(cleaned_group.split())

    parent_group_hint = Path(raw_input_folder).parent.name if raw_input_folder else ""
    parent_group_hint = parent_group_hint.strip()
    if parent_group_hint.lower().startswith("control"):
        parent_group_hint = "Control"
    elif parent_group_hint.upper().startswith("BC"):
        parent_group_hint = "BC"

    if not base_group:
        base_group = cleaned_group or parent_group_hint or group_name
    base_group = " ".join(str(base_group).split())

    if not phase:
        logger.warning("Could not infer phase for group '%s'", group_name)
    if not base_group:
        logger.warning("Could not infer base group for group '%s'", group_name)

    logger.debug(
        "canonical_group_phase_inferred",
        extra={
            "group_name": group_name,
            "base_group": base_group,
            "phase": phase,
            "raw_input_folder": raw_input_folder,
        },
    )

    return base_group, phase


def canonical_group_label(raw_group_name: str, manifest_groups: dict) -> str:
    """
    Map a participant's group display name from project.json (e.g. 'Luteal Control')
    to a canonical base group label (e.g. 'Control').

    Uses manifest_groups[group_name] and canonical_group_and_phase_from_manifest.
    """

    group_entry = manifest_groups.get(raw_group_name, {}) if isinstance(manifest_groups, dict) else {}
    base_group, _phase = canonical_group_and_phase_from_manifest(raw_group_name, group_entry)
    return base_group
