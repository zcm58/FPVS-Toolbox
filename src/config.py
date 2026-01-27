"""
FPVS Toolbox configuration (PySide6-safe) with legacy CTk shims.

Exposes:
- FPVS_TOOLBOX_VERSION
- frequency helpers: update_target_frequencies(), TARGET_FREQUENCIES
- UI sizing tokens
- Legacy symbols: init_fonts(), FONT_MAIN/FONT_BOLD/FONT_HEADING (no-op/None)
- Jan 10 Checkpoint: Save before merging low pass filter fix into Fix Single File Mode

"""

from __future__ import annotations

import numpy as np

# — Version & repo —
FPVS_TOOLBOX_VERSION: str = "1.6.0"
FPVS_TOOLBOX_UPDATE_API: str = (
    "https://api.github.com/repos/zcm58/FPVS-Toolbox-Repo/releases/latest"
)
FPVS_TOOLBOX_REPO_PAGE: str = "https://github.com/zcm58/FPVS-Toolbox-Repo/releases"

# — Defaults for analysis —
DEFAULT_ODDBALL_FREQ: float = 1.2
DEFAULT_BCA_UPPER_LIMIT: float = 16.8

def _load_frequency_settings() -> tuple[float, float]:
    """Return oddball frequency and upper limit from saved settings."""
    from Main_App import SettingsManager  # lazy to avoid cycles
    mgr = SettingsManager()
    try:
        odd = float(mgr.get("analysis", "oddball_freq", str(DEFAULT_ODDBALL_FREQ)))
    except ValueError:
        odd = DEFAULT_ODDBALL_FREQ
    try:
        upper = float(mgr.get("analysis", "bca_upper_limit", str(DEFAULT_BCA_UPPER_LIMIT)))
    except ValueError:
        upper = DEFAULT_BCA_UPPER_LIMIT
    return odd, upper

def _compute_freqs(odd: float, upper: float) -> np.ndarray:
    if odd <= 0:
        odd = DEFAULT_ODDBALL_FREQ
    if upper < odd:
        upper = DEFAULT_BCA_UPPER_LIMIT
    steps = int(round(upper / odd))
    return np.array([odd * i for i in range(1, steps + 1)], dtype=float)

def update_target_frequencies(odd: float | None = None, upper: float | None = None) -> np.ndarray:
    """Update and return the global TARGET_FREQUENCIES array."""
    global TARGET_FREQUENCIES
    if odd is None or upper is None:
        odd, upper = _load_frequency_settings()
    TARGET_FREQUENCIES = _compute_freqs(float(odd), float(upper))
    return TARGET_FREQUENCIES

# Precompute defaults without touching SettingsManager at import time.
TARGET_FREQUENCIES: np.ndarray = _compute_freqs(DEFAULT_ODDBALL_FREQ, DEFAULT_BCA_UPPER_LIMIT)

# — Channels and electrodes —
DEFAULT_ELECTRODE_NAMES_64 = [
    "Fp1","AF7","AF3","F1","F3","F5","F7","FT7","FC5","FC3","FC1","C1","C3","C5","T7","TP7",
    "CP5","CP3","CP1","P1","P3","P5","P7","P9","PO7","PO3","O1","Iz","Oz","POz","Pz","CPz",
    "Fpz","Fp2","AF8","AF4","AFz","Fz","F2","F4","F6","F8","FT8","FC6","FC4","FC2","FCz","Cz",
    "C2","C4","C6","T8","TP8","CP6","CP4","CP2","P2","P4","P6","P8","P10","PO8","PO4","O2"
]
DEFAULT_STIM_CHANNEL = "Status"

# — UI sizing tokens (no CTk) —
CORNER_RADIUS         = 8
PAD_X                 = 5
PAD_Y                 = 5
ENTRY_WIDTH           = 100
LABEL_ID_ENTRY_WIDTH  = 120
BUTTON_WIDTH          = 180
ADV_ENTRY_WIDTH          = ENTRY_WIDTH
ADV_LABEL_ID_ENTRY_WIDTH = int(ENTRY_WIDTH * 1.5)
ADV_ID_ENTRY_WIDTH       = int(ENTRY_WIDTH * 0.5)

def get_ui_constants() -> tuple[int, int, int, int, int]:
    """Return common UI dimension constants used throughout the app."""
    return PAD_X, PAD_Y, CORNER_RADIUS, ENTRY_WIDTH, LABEL_ID_ENTRY_WIDTH

# — Legacy CustomTkinter compatibility shims (do not import CTk) —
FONT_FAMILY = "Segoe UI"
FONT_MAIN = None
FONT_BOLD = None
FONT_HEADING = None

def init_fonts() -> None:
    """No-op in PySide6 build. Kept so Legacy_App imports succeed."""
    return None
