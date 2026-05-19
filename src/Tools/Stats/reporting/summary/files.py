"""Build Stats summaries from exported workbook files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from Tools.Stats.common.stats_core import ANOVA_XLS, LMM_XLS, POSTHOC_XLS
from Tools.Stats.reporting.summary.builder import build_summary_from_frames
from Tools.Stats.reporting.summary.models import StatsSummaryFrames, SummaryConfig


def build_summary_from_files(stats_folder: Path, config: SummaryConfig) -> str:
    """Read existing single-group Excel outputs and return a short summary."""

    def _safe_read(path: Path, sheet: str) -> Optional[pd.DataFrame]:
        if not path.is_file():
            return None
        try:
            return pd.read_excel(path, sheet_name=sheet)
        except Exception:
            return None

    def _safe_read_any(path: Path, sheets: list[str]) -> Optional[pd.DataFrame]:
        for sheet in sheets:
            df = _safe_read(path, sheet)
            if df is not None:
                return df
        return None

    frames = StatsSummaryFrames(
        single_posthoc=_safe_read_any(stats_folder / POSTHOC_XLS, ["Combined", "Post-hoc Results"]),
        anova_terms=_safe_read(stats_folder / ANOVA_XLS, "RM-ANOVA Table"),
        mixed_model_terms=_safe_read(stats_folder / LMM_XLS, "Mixed Model Results"),
    )
    return build_summary_from_frames(frames, config)
