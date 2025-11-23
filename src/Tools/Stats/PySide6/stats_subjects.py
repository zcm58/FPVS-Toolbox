"""Subject ID utilities for the Stats tool."""
from __future__ import annotations

import re

_CANONICAL_SUBJECT_PATTERN = re.compile(r"^(P\d+|Sub\d+|S\d+)", re.IGNORECASE)


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
