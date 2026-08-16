"""Stats compatibility helpers for neutral ROI settings."""

from __future__ import annotations

from Main_App.processing.roi_settings import (
    ALL_ROIS_OPTION,
    load_rois_from_settings,
)


def apply_rois_to_modules(rois_dict: dict[str, list[str]]) -> None:
    """Propagate ROI definitions to active Stats analysis modules."""
    from Tools.Stats.analysis import stats_analysis as analysis_mod

    analysis_mod.set_rois(rois_dict)


__all__ = [
    "ALL_ROIS_OPTION",
    "apply_rois_to_modules",
    "load_rois_from_settings",
]
