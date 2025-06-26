"""Utilities for reporting progress to callbacks."""

from __future__ import annotations

from typing import Callable, Optional


def update_progress(step: int, total: int, cb: Optional[Callable[[float], None]]) -> None:
    """Invoke ``cb`` with the fractional progress ``step / total``."""

    if cb:
        cb(step / total)

__all__ = ["update_progress"]
