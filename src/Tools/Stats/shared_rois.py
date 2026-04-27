"""Shared ROI settings helpers for Stats-related PySide6 tools."""

from __future__ import annotations

import sys
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
    """Propagate ROI definitions to loaded stats modules without pulling in legacy UI."""
    from Tools.Stats.Legacy import stats_analysis as analysis_mod

    analysis_mod.set_rois(rois_dict)

    for module_name in (
        "Tools.Stats.Legacy.stats_runners",
        "Tools.Stats.Legacy.stats",
    ):
        module = sys.modules.get(module_name)
        if module is not None:
            setattr(module, "ROIS", rois_dict)
