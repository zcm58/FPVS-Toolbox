# Helper methods extracted from stats.py

import logging
from tkinter import messagebox

from Main_App import SettingsManager
from . import stats_analysis

logger = logging.getLogger(__name__)


def log_to_main_app(self, message):
    try:
        if hasattr(self.master_app, 'log') and callable(self.master_app.log):
            self.master_app.log(f"[Stats] {message}")
        else:
            logger.info("[Stats] %s", message)
    except Exception as e:
        logger.error("[Stats Log Error] %s | Original message: %s", e, message)


def on_close(self):
    self.log_to_main_app("Closing Stats Analysis window.")
    self.destroy()


def _load_base_freq(self):
    if hasattr(self.master_app, 'settings'):
        return self.master_app.settings.get('analysis', 'base_freq', '6.0')
    return SettingsManager().get('analysis', 'base_freq', '6.0')


def _load_alpha(self):
    if hasattr(self.master_app, 'settings'):
        return self.master_app.settings.get('analysis', 'alpha', '0.05')
    return SettingsManager().get('analysis', 'alpha', '0.05')


def _load_bca_upper_limit(self):
    if hasattr(self.master_app, 'settings'):
        return self.master_app.settings.get('analysis', 'bca_upper_limit', '16.8')
    return SettingsManager().get('analysis', 'bca_upper_limit', '16.8')


def _validate_numeric(self, P):
    if P in ("", "-"):
        return True
    try:
        float(P)
        return True
    except ValueError:
        return False


def _get_included_freqs(self, all_col_names):
    return stats_analysis.get_included_freqs(
        self.base_freq,
        all_col_names,
        self.log_to_main_app,
        max_freq=self.bca_upper_limit,
    )


def aggregate_bca_sum(self, file_path, roi_name):
    return stats_analysis.aggregate_bca_sum(
        file_path, roi_name, self.base_freq, self.log_to_main_app
    )


def prepare_all_subject_summed_bca_data(self, roi_filter=None):
    """Populate ``all_subject_data`` using current ROI settings.

    ROIs are taken from current Settings at runtime via resolve_active_rois().
    """
    self.log_to_main_app("Preparing summed BCA data...")
    try:
        self.all_subject_data = stats_analysis.prepare_all_subject_summed_bca_data(
            self.subjects,
            self.conditions,
            self.subject_data,
            self.base_freq,
            self.log_to_main_app,
            roi_filter=roi_filter,
        ) or {}
    except ValueError as e:
        self.log_to_main_app(f"ROI resolution failed: {e}")
        messagebox.showerror("ROI Error", str(e))
        self.all_subject_data = {}
    return bool(self.all_subject_data)


def load_rois_from_settings(manager=None):
    """
    Return ROIs exactly as defined in Settings (case-sensitive).
    - Trim surrounding whitespace from ROI names and electrodes
    - Drop empty ROI names and empty/whitespace-only electrodes
    - If Settings is missing/unreadable/empty: return {}
    """
    mgr = manager or SettingsManager()
    rois_from_settings = None

    try:
        get_roi_pairs = getattr(mgr, "get_roi_pairs", None)
        if callable(get_roi_pairs):
            pairs = get_roi_pairs() or []
            # get_roi_pairs may return a dict or list/tuple of (name, electrodes)
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
        # Preserve case; remove surrounding whitespace; drop empties
        vals = [str(e).strip() for e in raw_vals if str(e).strip()]
        cleaned[name] = vals

    return cleaned



def apply_rois_to_modules(rois_dict):
    """Update ROI dictionaries in related stats modules."""
    import sys

    import Tools.Stats.Legacy.stats_analysis as analysis_mod
    import Tools.Stats.Legacy.stats_runners as runners_mod

    analysis_mod.set_rois(rois_dict)
    runners_mod.ROIS = rois_dict

    stats_mod = sys.modules.get("Tools.Stats.Legacy.stats")
    if stats_mod is not None:
        setattr(stats_mod, "ROIS", rois_dict)
