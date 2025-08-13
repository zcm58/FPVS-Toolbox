"""FPVS Toolbox configuration and helper utilities.

This module defines global constants used across the application such as
version identifiers, default GUI dimensions and font configuration.  It also
provides helper functions for loading frequency settings, computing the target
frequency array and initialising ``customtkinter`` fonts once a Tk root window
exists.
"""

import numpy as np
import customtkinter as ctk


# — FPVS Toolbox version & update API —

FPVS_TOOLBOX_VERSION       = "1.3.0"

FPVS_TOOLBOX_UPDATE_API    = "https://api.github.com/repos/zcm58/FPVS-Toolbox-Repo/releases/latest"
FPVS_TOOLBOX_REPO_PAGE     = "https://github.com/zcm58/FPVS-Toolbox-Repo/releases"

# Default frequency values used when settings are unavailable. These match the
# values provided in :mod:`Main_App.Legacy_App.settings_manager`.
DEFAULT_ODDBALL_FREQ = 1.2
DEFAULT_BCA_UPPER_LIMIT = 16.8

# — metrics —

def _load_frequency_settings():
    """Return oddball frequency and upper limit from saved settings."""
    from Main_App import SettingsManager  # Imported lazily to avoid circular deps

    mgr = SettingsManager()
    try:
        odd = float(mgr.get('analysis', 'oddball_freq', str(DEFAULT_ODDBALL_FREQ)))
    except ValueError:
        odd = DEFAULT_ODDBALL_FREQ
    try:
        upper = float(mgr.get('analysis', 'bca_upper_limit', str(DEFAULT_BCA_UPPER_LIMIT)))
    except ValueError:
        upper = DEFAULT_BCA_UPPER_LIMIT
    return odd, upper


def _compute_freqs(odd: float, upper: float) -> np.ndarray:
    if odd <= 0:
        odd = DEFAULT_ODDBALL_FREQ
    if upper < odd:
        upper = DEFAULT_BCA_UPPER_LIMIT
    steps = int(round(upper / odd))
    return np.array([odd * i for i in range(1, steps + 1)])


def update_target_frequencies(odd: float = None, upper: float = None) -> np.ndarray:
    """Update the global TARGET_FREQUENCIES array."""
    global TARGET_FREQUENCIES
    if odd is None or upper is None:
        odd, upper = _load_frequency_settings()
    TARGET_FREQUENCIES = _compute_freqs(float(odd), float(upper))
    return TARGET_FREQUENCIES


# Pre-compute default frequencies without accessing SettingsManager to avoid
# circular imports during initialisation.
TARGET_FREQUENCIES = _compute_freqs(DEFAULT_ODDBALL_FREQ, DEFAULT_BCA_UPPER_LIMIT)
DEFAULT_ELECTRODE_NAMES_64 = [
    'Fp1','AF7','AF3','F1','F3','F5','F7','FT7','FC5','FC3','FC1','C1','C3','C5','T7','TP7',
    'CP5','CP3','CP1','P1','P3','P5','P7','P9','PO7','PO3','O1','Iz','Oz','POz','Pz','CPz',
    'Fpz','Fp2','AF8','AF4','AFz','Fz','F2','F4','F6','F8','FT8','FC6','FC4','FC2','FCz','Cz',
    'C2','C4','C6','T8','TP8','CP6','CP4','CP2','P2','P4','P6','P8','P10','PO8','PO4','O2'
]
DEFAULT_STIM_CHANNEL = 'Status'

# — GUI defaults —
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")
CORNER_RADIUS         = 8
PAD_X                 = 5
PAD_Y                 = 5
ENTRY_WIDTH           = 100
LABEL_ID_ENTRY_WIDTH  = 120

# Additional GUI dimensions used in advanced processing windows.
# Modify these to adjust default control sizes.
BUTTON_WIDTH             = 180
ADV_ENTRY_WIDTH          = ENTRY_WIDTH
ADV_LABEL_ID_ENTRY_WIDTH = int(ENTRY_WIDTH * 1.5)
ADV_ID_ENTRY_WIDTH       = int(ENTRY_WIDTH * 0.5)

# --- Fonts ---
FONT_FAMILY = "Segoe UI"

# Font variables are initialised after a Tk root exists.  They are set to
# ``None`` here and configured via :func:`init_fonts` which should be called
# once a ``ctk.CTk`` instance has been created.
FONT_MAIN = None
FONT_BOLD = None
FONT_HEADING = None


def init_fonts() -> None:
    """Initialise global ``customtkinter`` fonts.

    ``customtkinter.CTkFont`` requires a default Tk root window. Importing this
    module before a root exists would raise ``RuntimeError: Too early to use
    font``.  Call this function after creating the main application window to
    populate the global font variables.
    """
    global FONT_MAIN, FONT_BOLD, FONT_HEADING

    if FONT_MAIN is None:
        FONT_MAIN = ctk.CTkFont(family=FONT_FAMILY, size=12)
    if FONT_BOLD is None:
        FONT_BOLD = ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold")
    if FONT_HEADING is None:
        FONT_HEADING = ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold")


def get_ui_constants() -> tuple[int, int, int, int, int]:
    """Return the common UI dimension constants used throughout the app."""
    return PAD_X, PAD_Y, CORNER_RADIUS, ENTRY_WIDTH, LABEL_ID_ENTRY_WIDTH

