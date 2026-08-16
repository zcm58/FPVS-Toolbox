"""Lazy public surface for embedded Free Harmonic Clustering Analysis."""

from __future__ import annotations

from typing import Any

from .operation_registry import (
    cancel_all_active_operations,
    has_active_operations,
)

__all__ = [
    "FreeHarmonicBackend",
    "FreeHarmonicBackendAdapter",
    "FreeHarmonicClusteringPage",
    "FreeHarmonicClusteringWindow",
    "ProjectFrequencySnapshot",
    "cancel_all_active_operations",
    "has_active_operations",
]


def __getattr__(name: str) -> Any:
    """Keep adapter/model imports free of an eager PySide6 dependency."""

    if name in {"FreeHarmonicClusteringPage", "FreeHarmonicClusteringWindow"}:
        from . import page

        return getattr(page, name)
    if name in {"FreeHarmonicBackend", "FreeHarmonicBackendAdapter"}:
        from . import backend_adapter

        return getattr(backend_adapter, name)
    if name == "ProjectFrequencySnapshot":
        from .models import ProjectFrequencySnapshot

        return ProjectFrequencySnapshot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
