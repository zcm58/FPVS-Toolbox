# src/Main_App/PySide6_App/utils/op_guard.py
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Optional


class OpGuard:
    """
    Non-blocking re-entrancy guard for UI-triggered operations.

    Usage:
        guard = OpGuard()
        if not guard.start():
            return
        try:
            ...  # do work
        finally:
            guard.end()

    Or as a context manager:
        with guard.scope() as ok:
            if not ok:
                return
            ...  # do work
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._started_at: Optional[float] = None

    def start(self) -> bool:
        """
        Attempt to acquire the guard without blocking.
        Returns False if already active.
        """
        if not self._lock.acquire(blocking=False):
            return False
        if self._active:
            # Should not occur with the lock held, but be defensive.
            self._lock.release()
            return False
        self._active = True
        self._started_at = time.perf_counter()
        return True

    def end(self) -> float:
        """
        Release the guard.
        Returns elapsed milliseconds for the guarded operation.
        Safe to call once per successful start().
        """
        elapsed_ms = 0.0
        if self._started_at is not None:
            elapsed_ms = (time.perf_counter() - self._started_at) * 1000.0
        self._active = False
        self._started_at = None
        try:
            self._lock.release()
        except RuntimeError:
            # Double-release guard; ignore.
            pass
        return elapsed_ms

    def is_active(self) -> bool:
        """True if the guard is currently held."""
        return self._active

    def reset(self) -> None:
        """Force-clear the guard state."""
        self._active = False
        self._started_at = None
        try:
            if self._lock.locked():
                self._lock.release()
        except RuntimeError:
            pass

    @contextmanager
    def scope(self):
        """
        Context manager that yields True if acquired, else False.
        Always releases if acquired.
        """
        ok = self.start()
        try:
            yield ok
        finally:
            if ok:
                self.end()
