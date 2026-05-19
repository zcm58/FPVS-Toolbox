"""Data models for Stats summary reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from Tools.Stats.common.stats_core import PipelineId


@dataclass
class SummaryConfig:
    """Configuration for rule-based Stats result summaries."""

    alpha: float = 0.05
    min_effect: float = 0.50
    max_bullets: int = 3
    z_threshold: float = 1.64
    p_col: str = "p_fdr"
    effect_col: str = "effect_size"
    max_lines_per_direction: int = 5


@dataclass
class StatsSummaryFrames:
    """In-memory result tables used to build a Stats summary."""

    single_posthoc: Optional[pd.DataFrame] = None
    harmonic_results: Optional[pd.DataFrame] = None
    anova_terms: Optional[pd.DataFrame] = None
    mixed_model_terms: Optional[pd.DataFrame] = None
    pipeline_id: Optional[PipelineId] = None
