from __future__ import annotations

class OpGuard:
    """Simple re-entrancy guard for start/stop operations."""

    def __init__(self) -> None:
        self._active = False

    def start(self) -> bool:
        """Attempt to start the guarded operation.

        Returns True if the guard was previously inactive and is now active.
        Returns False if an operation is already active.
        """
        if self._active:
            return False
        self._active = True
        return True

    def end(self) -> None:
        """Mark the guarded operation as finished."""
        self._active = False
