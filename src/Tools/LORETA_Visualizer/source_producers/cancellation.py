"""Cooperative cancellation at source-build boundaries before publication."""

from __future__ import annotations

from threading import Event


class SourceBuildCancelled(Exception):
    """The caller cancelled a build before its output publication began."""


class SourceBuildCancellation:
    """Thread-safe token; checking must never interrupt output publication."""

    def __init__(self) -> None:
        self._requested = Event()

    def request(self) -> None:
        self._requested.set()

    @property
    def requested(self) -> bool:
        return self._requested.is_set()

    def check(self) -> None:
        if self.requested:
            raise SourceBuildCancelled("Source-map build cancelled.")
