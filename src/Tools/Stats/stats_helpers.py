# Helper methods extracted from stats.py

import logging
from Main_App.settings_manager import SettingsManager
from . import stats_analysis

logger = logging.getLogger(__name__)

# Default ROI definitions used when no user configuration exists
DEFAULT_ROIS = {
    "Frontal Lobe": ["F3", "F4", "Fz"],
    "Occipital Lobe": ["O1", "O2", "Oz"],
    "Parietal Lobe": ["P3", "P4", "Pz"],
    "Central Lobe": ["C3", "C4", "Cz"],
}


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


def _validate_numeric(self, P):
    if P in ("", "-"): return True
    try:
        float(P)
        return True
    except ValueError:
        return False


def _get_included_freqs(self, all_col_names):
    return stats_analysis.get_included_freqs(
        self.base_freq, all_col_names, self.log_to_main_app
    )


def aggregate_bca_sum(self, file_path, roi_name):
    return stats_analysis.aggregate_bca_sum(
        file_path, roi_name, self.base_freq, self.log_to_main_app
    )


def prepare_all_subject_summed_bca_data(self):
    self.log_to_main_app("Preparing summed BCA data...")
    self.all_subject_data = stats_analysis.prepare_all_subject_summed_bca_data(
        self.subjects,
        self.conditions,
        self.subject_data,
        self.base_freq,
        self.log_to_main_app,
    ) or {}
    return bool(self.all_subject_data)


def load_rois_from_settings(manager=None):
    """Return ROI dictionary from settings, ensuring defaults exist."""
    mgr = manager or SettingsManager()
    pairs = mgr.get_roi_pairs() if hasattr(mgr, "get_roi_pairs") else []
    rois = {}
    for name, electrodes in pairs:
        if name and electrodes:
            rois[name] = [e.upper() for e in electrodes]
    for name, default_chans in DEFAULT_ROIS.items():
        rois.setdefault(name, default_chans)
    return rois


def apply_rois_to_modules(rois_dict):
    """Update ROI dictionaries in related stats modules."""
    import Tools.Stats.stats as stats_mod
    import Tools.Stats.stats_analysis as analysis_mod
    import Tools.Stats.stats_runners as runners_mod

    stats_mod.ROIS = rois_dict
    analysis_mod.set_rois(rois_dict)
    runners_mod.ROIS = rois_dict
