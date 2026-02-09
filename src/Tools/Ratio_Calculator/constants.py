from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


ROI_DEFS_DEFAULT: dict[str, list[str]] = {
    "Bilateral OT": ["P7", "P9", "PO7", "PO3", "O1", "Oz", "O2", "P8", "P10", "PO8", "PO4"],
    "LOT": ["P7", "P9", "PO7", "PO3", "O1"],
    "ROT": ["P8", "P10", "PO8", "O2", "PO4"],
    "Left Parietal": ["P3", "P5", "CP3", "CP5", "CP1"],
    "Right Parietal": ["P4", "P6", "CP4", "CP6", "CP2"],
}

SHEET_SNR = "SNR"
SHEET_Z = "Z Score"
SHEET_BCA = "BCA (uV)"
ELECTRODE_COL = "Electrode"

PALETTES: dict[str, dict[str, str]] = {
    "vibrant": {"Occipital": "#2E86FF", "LOT": "#FF6B2E", "Default": "#7F8C8D"},
    "muted": {"Occipital": "#4C78A8", "LOT": "#F58518", "Default": "#95A5A6"},
    "colorblind_safe": {"Occipital": "#0072B2", "LOT": "#D55E00", "Default": "#CC79A7"},
}

MANUAL_EXCLUDED_POINT_COLOR = "#4D4D4D"
MANUAL_EXCLUDED_POINT_MARKER = "x"

EXCEL_COL_PADDING_CHARS = 2
EXCEL_MIN_COL_WIDTH = 8
EXCEL_MAX_COL_WIDTH = 70

EPS = 1e-12


@dataclass
class RatioCalculatorSettings:
    oddball_base_hz: float = 1.2
    sum_up_to_hz: float = 16.8
    excluded_freqs_hz: set[float] = field(default_factory=lambda: {6.0, 12.0, 18.0, 24.0})
    palette_choice: str = "vibrant"
    png_dpi: int = 300
    use_stable_ylims: bool = True
    ylim_raw_sum_z: Optional[Tuple[float, float]] = None
    ylim_raw_sum_snr: Optional[Tuple[float, float]] = None
    ylim_raw_sum_bca: Optional[Tuple[float, float]] = None
    ylim_ratio_z: Optional[Tuple[float, float]] = None
    ylim_ratio_snr: Optional[Tuple[float, float]] = None
    ylim_ratio_bca: Optional[Tuple[float, float]] = None
