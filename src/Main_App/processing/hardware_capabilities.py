"""Tool availability based on upstream scientific qualification metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from Main_App.io.acquisition_metadata import resolve_spatial_tool_capability

_TEMPLATE_SPATIAL_TOOLS = frozenset({
    "LORETA Visualizer", "Free Harmonic Clustering Analysis", "Scalp Maps",
})


def spatial_tool_unavailable_reason(project: Any, tool_name: str) -> str:
    """Return an actionable limitation, leaving nonspatial processing available."""
    if tool_name not in _TEMPLATE_SPATIAL_TOOLS:
        return ""
    settings = getattr(project, "preprocessing", None)
    if settings is None and isinstance(project, Mapping):
        settings = project.get("preprocessing", project)
    supported, model_label, acquisition_label = resolve_spatial_tool_capability(settings)
    if supported:
        return ""
    return (
        f"{tool_name} currently requires the validated {model_label} spatial model. "
        f"It is unavailable for this project's {acquisition_label} montage. "
        "EEG processing, spectral outputs and compatible statistical tables remain available."
    )
