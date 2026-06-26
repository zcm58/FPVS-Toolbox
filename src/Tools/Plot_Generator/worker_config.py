"""Configuration payload for Plot Generator workers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence


@dataclass(frozen=True)
class PlotWorkerConfig:
    """Constructor-compatible configuration for the Plot Generator worker."""

    folder: str
    condition: str
    roi_map: Dict[str, List[str]]
    selected_roi: str
    title: str
    xlabel: str
    ylabel: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    out_dir: str
    stem_color: str = "red"
    condition_b: str | None = None
    stem_color_b: str = "blue"
    oddballs: Sequence[float] | None = None
    use_matlab_style: bool = False
    overlay: bool = False
    subject_groups: Dict[str, str | None] | None = None
    selected_groups: Sequence[str] | None = None
    enable_group_overlay: bool = False
    multi_group_mode: bool = False
    legend_custom_enabled: bool = False
    legend_condition_a: str | None = None
    legend_condition_b: str | None = None
    legend_a_peaks: str | None = None
    legend_b_peaks: str | None = None
    project_root: str | None = None
    spectral_qc_enabled: bool = True
