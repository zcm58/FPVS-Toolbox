"""Compatibility helpers for the quarantined legacy Stats UI."""
from __future__ import annotations

import logging

from Main_App import SettingsManager
from Tools.Stats.Legacy import quarantined_stats_ui_message
from Tools.Stats.shared_rois import (
    apply_rois_to_modules as _shared_apply_rois_to_modules,
    load_rois_from_settings as _shared_load_rois_from_settings,
)

logger = logging.getLogger(__name__)
_QUARANTINE_MESSAGE = quarantined_stats_ui_message()


def log_to_main_app(self, message):
    """Forward old helper logging without importing tkinter."""
    try:
        if hasattr(self.master_app, "log") and callable(self.master_app.log):
            self.master_app.log(f"[Stats] {message}")
        else:
            logger.info("[Stats] %s", message)
    except Exception as exc:  # noqa: BLE001
        logger.error("[Stats Log Error] %s | Original message: %s", exc, message)


def _load_base_freq(self):
    """Load base frequency through the current settings surface."""
    if hasattr(self.master_app, "settings"):
        return self.master_app.settings.get("analysis", "base_freq", "6.0")
    return SettingsManager().get("analysis", "base_freq", "6.0")


def _load_alpha(self):
    """Load alpha through the current settings surface."""
    if hasattr(self.master_app, "settings"):
        return self.master_app.settings.get("analysis", "alpha", "0.05")
    return SettingsManager().get("analysis", "alpha", "0.05")


def _load_bca_upper_limit(self):
    """Load BCA upper limit through the current settings surface."""
    if hasattr(self.master_app, "settings"):
        return self.master_app.settings.get("analysis", "bca_upper_limit", "16.8")
    return SettingsManager().get("analysis", "bca_upper_limit", "16.8")


def _validate_numeric(_self, value):
    """Return whether an old text-field value is numeric."""
    if value in ("", "-"):
        return True
    try:
        float(value)
    except ValueError:
        return False
    return True


def load_rois_from_settings(manager=None):
    """Compatibility wrapper for the shared ROI settings helper."""
    return _shared_load_rois_from_settings(manager)


def apply_rois_to_modules(rois_dict):
    """Compatibility wrapper for the shared ROI propagation helper."""
    _shared_apply_rois_to_modules(rois_dict)


def __getattr__(name: str):
    raise RuntimeError(f"{_QUARANTINE_MESSAGE}\nUnsupported helper: {name}")
