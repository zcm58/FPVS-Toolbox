# src/Tools/SourceLocalization/progress.py
""""Utilities for reporting progress to callbacks."""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def update_progress(step: int, total: int, cb: Optional[Callable[[float], None]]) -> None:
    """Invoke ``cb`` with the fractional progress ``step / total``.

    - Safely handles ``total <= 0``.
    - Clamps fraction to [0.0, 1.0].
    - Logs (does not raise) if the callback errors.
    """
    if cb is None:
        return

    if total <= 0:
        logger.warning("progress_total_nonpositive", extra={"step": step, "total": total})
        return

    frac = step / total
    if frac < 0.0:
        frac = 0.0
    elif frac > 1.0:
        frac = 1.0

    try:
        cb(frac)
    except Exception:
        logger.error("progress_callback_error", extra={"step": step, "total": total, "frac": frac}, exc_info=True)


__all__ = ["update_progress"]
