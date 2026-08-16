"""Neutral ROI settings shared by processing and descriptive tools."""

from __future__ import annotations

from typing import Any

ALL_ROIS_OPTION = "(All ROIs)"


def load_rois_from_settings(manager: Any = None) -> dict[str, list[str]]:
    """Return current ROI definitions, cleaned for runtime use."""

    if manager is None:
        from Main_App.Shared.settings_manager import SettingsManager

        mgr = SettingsManager()
    else:
        mgr = manager
    rois_from_settings = None

    try:
        get_roi_pairs = getattr(mgr, "get_roi_pairs", None)
        if callable(get_roi_pairs):
            pairs = get_roi_pairs() or []
            if isinstance(pairs, dict):
                rois_from_settings = dict(pairs)
            else:
                rois_from_settings = {
                    name: electrodes for name, electrodes in pairs
                }
    except Exception:  # noqa: BLE001 - settings-provider compatibility boundary
        rois_from_settings = None

    if rois_from_settings is None:
        return {}

    cleaned: dict[str, list[str]] = {}
    for raw_name, raw_values in rois_from_settings.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_values, (list, tuple)):
            continue
        cleaned[name] = [
            str(electrode).strip()
            for electrode in raw_values
            if str(electrode).strip()
        ]
    return cleaned


__all__ = ["ALL_ROIS_OPTION", "load_rois_from_settings"]
