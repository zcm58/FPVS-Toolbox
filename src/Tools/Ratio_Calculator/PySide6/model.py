from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from Tools.Stats.roi_resolver import ROI


@dataclass(frozen=True)
class RatioCalcInputs:
    excel_root: Path
    cond_a: str
    cond_b: str
    roi_name: Optional[str]
    z_threshold: float
    output_path: Path
    significance_mode: str
    rois: list[ROI]
    metric: str
    outlier_enabled: bool
    outlier_method: str
    outlier_threshold: float
    outlier_action: str
    bca_negative_mode: str


@dataclass
class RatioCalcResult:
    dataframe: pd.DataFrame
    significant_freqs_by_roi: dict[str, list[float]]
    significant_freqs_by_roi_by_pid: Optional[dict[str, dict[str, list[float]]]]
    warnings: list[str]
    summary_counts: dict[str, object]
    output_path: Path
    output_folder: Path
