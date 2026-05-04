"""Shared ROI settings helpers for Stats-related tools."""

from __future__ import annotations

from typing import Any

from Main_App import SettingsManager


def load_rois_from_settings(manager: Any = None) -> dict[str, list[str]]:
    """Return ROIs exactly as defined in Settings, cleaned for runtime use."""
    mgr = manager or SettingsManager()
    rois_from_settings = None

    try:
        get_roi_pairs = getattr(mgr, "get_roi_pairs", None)
        if callable(get_roi_pairs):
            pairs = get_roi_pairs() or []
            if isinstance(pairs, dict):
                rois_from_settings = dict(pairs)
            else:
                rois_from_settings = {name: electrodes for name, electrodes in pairs}
    except Exception:
        rois_from_settings = None

    if rois_from_settings is None:
        return {}

    cleaned: dict[str, list[str]] = {}
    for raw_name, raw_vals in rois_from_settings.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_vals, (list, tuple)):
            continue
        cleaned[name] = [str(e).strip() for e in raw_vals if str(e).strip()]

    return cleaned


def apply_rois_to_modules(rois_dict: dict[str, list[str]]) -> None:
    """Propagate ROI definitions to active Stats analysis modules."""
    from Tools.Stats.analysis import stats_analysis as analysis_mod

    analysis_mod.set_rois(rois_dict)
