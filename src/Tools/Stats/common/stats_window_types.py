"""Small shared types for the Stats PySide6 window."""
from __future__ import annotations

from typing import NamedTuple


class HarmonicConfig(NamedTuple):
    """Settings for the harmonic significance check."""

    metric: str
    threshold: float
