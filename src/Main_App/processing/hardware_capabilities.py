"""Tool availability where a method still has a fixed BioSemi64 spatial model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Main_App.projects.hardware import resolve_hardware

_BIOSEMI_SPATIAL_TOOLS = frozenset({
    "LORETA Visualizer", "Free Harmonic Clustering Analysis", "Scalp Maps",
})


def spatial_tool_unavailable_reason(project: Any, tool_name: str) -> str:
    """Return an actionable limitation, leaving nonspatial processing available."""
    if tool_name not in _BIOSEMI_SPATIAL_TOOLS:
        return ""
    settings = getattr(project, "preprocessing", None)
    if settings is None and isinstance(project, Mapping):
        settings = project.get("preprocessing", project)
    if resolve_hardware(settings).platform == "biosemi":
        return ""
    return (
        f"{tool_name} currently requires the validated BioSemi64 spatial model. "
        "It is unavailable for this project's Brain Products montage. "
        "EEG processing, spectral outputs and compatible statistical tables remain available."
    )
