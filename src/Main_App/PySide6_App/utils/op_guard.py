from __future__ import annotations


class OpGuard:
    """Non-blocking re-entrancy guard for long operations."""

    def __init__(self) -> None:
        self._active = False

    def start(self) -> bool:
        """Acquire guard; return False if already active."""
        if self._active:
            return False
        self._active = True
        return True

    def end(self) -> None:
        self._active = False
