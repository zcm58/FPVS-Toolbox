from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class RatioCalcInputs:
    excel_root: Path
    cond_a: str
    cond_b: str
    roi_name: Optional[str]
    z_threshold: float
    output_path: Path


@dataclass
class RatioCalcResult:
    dataframe: pd.DataFrame
    significant_freqs_by_roi: dict[str, list[float]]
    warnings: list[str]
    output_path: Path
