from __future__ import annotations

import logging
from collections.abc import Iterable

from Main_App import SettingsManager

logger = logging.getLogger(__name__)


def load_ratio_rois() -> dict[str, list[str]]:
    """Load ROI definitions from the shared SettingsManager ROI store.

    This uses the same runtime source the Stats workflow relies on: ``get_roi_pairs``.
    Invalid rows are dropped (blank ROI names or blank electrodes).
    """

    try:
        manager = SettingsManager()
        get_roi_pairs = getattr(manager, "get_roi_pairs", None)
        pairs: Iterable[tuple[object, object]]
        if not callable(get_roi_pairs):
            return {}
        raw_pairs = get_roi_pairs() or []
        if isinstance(raw_pairs, dict):
            pairs = raw_pairs.items()
        else:
            pairs = raw_pairs
    except Exception:
        logger.exception("Failed to load ROI pairs from SettingsManager")
        return {}

    rois: dict[str, list[str]] = {}
    for raw_name, raw_electrodes in pairs:
        name = str(raw_name).strip()
        if not name:
            continue
        if not isinstance(raw_electrodes, (list, tuple)):
            continue
        electrodes = [str(e).strip() for e in raw_electrodes if str(e).strip()]
        if not electrodes:
            continue
        rois[name] = electrodes
    return rois

