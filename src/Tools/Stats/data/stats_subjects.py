"""Subject ID utilities for the Stats tool."""

from __future__ import annotations

import re

# Preserve legacy behavior for IDs that start with P#, Sub#, or S#.
_CANONICAL_SUBJECT_PATTERN = re.compile(r"^(P\d+|Sub\d+|S\d+)", re.IGNORECASE)

# Detect an uppercase/lowercase 'P' followed immediately by digits anywhere in
# the string, e.g. "SCP7_Fruit vs Veg_Results" -> "P7".
_FALLBACK_P_SUBJECT_PATTERN = re.compile(r"[Pp]\d+")


def canonical_subject_id(raw_id: str | None) -> str:
    """Derive a stable Stats subject ID from a raw file or manifest ID."""
    if not isinstance(raw_id, str):
        return ""
    raw_id = raw_id.strip()
    if not raw_id:
        return ""

    match = _CANONICAL_SUBJECT_PATTERN.match(raw_id)
    if match:
        return match.group(1)

    fallback = _FALLBACK_P_SUBJECT_PATTERN.search(raw_id)
    if fallback:
        return fallback.group(0).upper()

    return raw_id


__all__ = ["canonical_subject_id"]
