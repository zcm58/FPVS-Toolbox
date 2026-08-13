"""Process-local lifecycle registry for background GUI operations.

This module intentionally has no Qt import. Retired project pages can disappear
from MainWindow while their cooperative cancellation finishes, so app-close
coordination must track operation handles independently of widget ownership.
"""

from __future__ import annotations

from threading import RLock

import logging


logger = logging.getLogger(__name__)

_LOCK = RLock()
_ACTIVE_OPERATIONS: dict[object, object] = {}


def register_active_operation(token: object, worker: object) -> None:
    """Retain one worker until its operation thread emits ``finished``."""

    with _LOCK:
        _ACTIVE_OPERATIONS[token] = worker


def release_active_operation(token: object) -> None:
    """Release a completed operation; repeated release is harmless."""

    with _LOCK:
        _ACTIVE_OPERATIONS.pop(token, None)


def has_active_operations() -> bool:
    """Return whether any current or retired page still owns live work."""

    with _LOCK:
        return bool(_ACTIVE_OPERATIONS)


def cancel_all_active_operations() -> int:
    """Request cooperative cancellation for every retained operation.

    Returns the number of workers that accepted a cancellation request. The
    registry remains populated until each operation actually finishes.
    """

    with _LOCK:
        workers = tuple(_ACTIVE_OPERATIONS.values())
    requested = 0
    for worker in workers:
        cancel = getattr(worker, "cancel", None)
        if not callable(cancel):
            continue
        try:
            cancel()
        except RuntimeError:
            logger.debug(
                "free_harmonic_active_worker_already_released",
                exc_info=True,
            )
        else:
            requested += 1
    return requested


__all__ = ["cancel_all_active_operations", "has_active_operations"]
