"""Subject ID and group utilities for the Stats tool."""

# This file is primarily used with Lela Mode (aka the cross phase LLM)

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Tuple, Any

logger = logging.getLogger(__name__)

_CANONICAL_SUBJECT_PATTERN = re.compile(r"^(P\d+|Sub\d+|S\d+)", re.IGNORECASE)


def _coerce_str_or_empty(value: Any) -> str:
    """
    Return a stripped string if value is a string; otherwise return an empty string.

    This is used to defensively normalize metadata fields that may be None or non-string.
    """
    if isinstance(value, str):
        return value.strip()
    return ""


def _detect_phase(candidate: Any) -> str:
    """
    Best-effort inference of phase label from a free-text candidate.

    Returns:
      - "Luteal" if the text appears to reference a luteal phase
      - "Follicular" if the text appears to reference a follicular phase
      - "" if no phase can be inferred

    Handles None and non-string inputs gracefully.
    """
    if not isinstance(candidate, str):
        return ""
    text = candidate.strip().lower()
    if not text:
        return ""

    # Explicit names
    if "luteal" in text:
        return "Luteal"
    if "follicular" in text:
        return "Follicular"

    # Heuristic token-based detection (e.g., "lut", "fol", "luteal_phase", etc.)
    tokens = re.split(r"[\s._\-]+", text)
    if any(tok.startswith("lut") for tok in tokens):
        return "Luteal"
    if any(tok.startswith("fol") for tok in tokens):
        return "Follicular"

    return ""


def canonical_subject_id(raw_id: str | None) -> str:
    """
    Derive a phase-agnostic subject ID from a raw Stats subject ID.

    Examples:
      - 'P10BCF' -> 'P10'
      - 'P10BCL' -> 'P10'
      - 'P2CGF'  -> 'P2'
      - 'P2CGL'  -> 'P2'
      - 'P1'     -> 'P1'
      - 'XYZ123' -> 'XYZ123' (no change if it doesn't match the pattern)

    For None or empty inputs, returns an empty string.
    """

    if not isinstance(raw_id, str):
        return ""
    raw_id = raw_id.strip()
    if not raw_id:
        return ""

    match = _CANONICAL_SUBJECT_PATTERN.match(raw_id)
    return match.group(1) if match else raw_id


def canonical_group_and_phase_from_manifest(
    group_name: str | None,
    group_entry: Dict[str, Any] | None,
) -> Tuple[str, str]:
    """
    Given a project.json group entry, derive (base_group, phase).

    Prefer explicit 'base_group' and 'phase' keys if present.
    Otherwise, fall back to heuristics based on group_name and
    group_entry['raw_input_folder'].

    Returns:
      base_group: canonical between-subject group label (e.g. "Control", "BC")
      phase: phase label for this project (e.g. "Luteal", "Follicular")

    This helper is defensive: it tolerates None / missing fields without raising.
    """

    group_entry = group_entry or {}

    # Normalize manifest fields safely
    base_group = _coerce_str_or_empty(group_entry.get("base_group"))
    phase = _coerce_str_or_empty(group_entry.get("phase"))
    raw_input_folder = _coerce_str_or_empty(group_entry.get("raw_input_folder"))
    raw_input_name = Path(raw_input_folder).name if raw_input_folder else ""

    safe_group_name = _coerce_str_or_empty(group_name)

    # Infer phase if not explicitly set
    inferred_phase = phase or _detect_phase(safe_group_name) or _detect_phase(raw_input_name)
    phase = inferred_phase

    # Remove phase label from the group name to get a cleaner base group, if possible
    cleaned_group = safe_group_name
    if phase and cleaned_group:
        # Remove the phase word in a case-insensitive way
        cleaned_group = re.sub(re.escape(phase), "", cleaned_group, flags=re.IGNORECASE)
        cleaned_group = " ".join(cleaned_group.split())

    # Heuristic: infer a group hint from the parent folder of the raw input
    parent_group_hint = ""
    if raw_input_folder:
        parent_group_hint = Path(raw_input_folder).parent.name.strip()
        if parent_group_hint:
            lowered = parent_group_hint.lower()
            if lowered.startswith("control"):
                parent_group_hint = "Control"
            elif lowered.startswith("bc"):
                parent_group_hint = "BC"
            else:
                parent_group_hint = " ".join(parent_group_hint.split())

    # Choose the best available base_group
    if not base_group:
        base_group = cleaned_group or parent_group_hint or safe_group_name
        base_group = " ".join(base_group.split())

    if not phase:
        logger.warning("Could not infer phase for group '%s'", safe_group_name or "<unnamed>")
    if not base_group:
        logger.warning("Could not infer base group for group '%s'", safe_group_name or "<unnamed>")

    logger.debug(
        "canonical_group_phase_inferred",
        extra={
            "group_name": safe_group_name,
            "base_group": base_group,
            "phase": phase,
            "raw_input_folder": raw_input_folder,
        },
    )

    return base_group, phase


def canonical_group_label(raw_group_name: str | None, manifest_groups: dict | None) -> str:
    """
    Map a participant's group display name from project.json (e.g. 'Luteal Control')
    to a canonical base group label (e.g. 'Control').

    Uses manifest_groups[group_name] and canonical_group_and_phase_from_manifest,
    but is defensive against None / missing manifest entries.

    If metadata is incomplete, falls back to the raw group name (normalized).
    """

    manifest_groups = manifest_groups or {}
    if not isinstance(manifest_groups, dict):
        manifest_groups = {}

    safe_raw_name = _coerce_str_or_empty(raw_group_name)

    group_entry: Dict[str, Any] = {}

    # Direct lookup
    if safe_raw_name and safe_raw_name in manifest_groups:
        entry = manifest_groups.get(safe_raw_name)
        if isinstance(entry, dict):
            group_entry = entry or {}
    # Case-insensitive fallback lookup
    elif safe_raw_name:
        target = safe_raw_name.lower()
        for key, val in manifest_groups.items():
            if isinstance(key, str) and key.lower() == target and isinstance(val, dict):
                group_entry = val or {}
                break

    base_group, _phase = canonical_group_and_phase_from_manifest(safe_raw_name, group_entry)

    if not base_group:
        base_group = safe_raw_name

    logger.debug(
        "canonical_group_label_resolved",
        extra={
            "raw_group_name": safe_raw_name,
            "resolved_base_group": base_group,
        },
    )

    return base_group
