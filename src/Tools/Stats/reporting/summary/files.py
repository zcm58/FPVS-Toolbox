"""Build Stats summaries from exported workbook files."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from Tools.Stats.common.stats_core import (
    ANOVA_XLS,
    GROUP_CONTRAST_XLS,
    LMM_BETWEEN_XLS,
    LMM_XLS,
    MULTIGROUP_GROUP_CONTRAST_LEGACY_SHEETS,
    MULTIGROUP_GROUP_CONTRAST_SHEET,
    MULTIGROUP_MIXED_MODEL_SHEET,
    POSTHOC_XLS,
    PipelineId,
)
from Tools.Stats.reporting.summary.builder import build_summary_from_frames
from Tools.Stats.reporting.summary.models import StatsSummaryFrames, SummaryConfig


def build_summary_from_files(stats_folder: Path, config: SummaryConfig) -> str:
    """
    Read existing Excel outputs in `stats_folder` and return a short summary.

    The function is fail-safe: any file-read or parsing issues result in
    section-specific fallback messages rather than exceptions.
    """

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

    single_posthoc = _safe_read_any(stats_folder / POSTHOC_XLS, ["Combined", "Post-hoc Results"])
    between_contrasts = _safe_read_any(
        stats_folder / GROUP_CONTRAST_XLS,
        [MULTIGROUP_GROUP_CONTRAST_SHEET, *MULTIGROUP_GROUP_CONTRAST_LEGACY_SHEETS],
    )
    single_lmm = _safe_read(stats_folder / LMM_XLS, MULTIGROUP_MIXED_MODEL_SHEET)
    frames = StatsSummaryFrames(
        single_posthoc=single_posthoc,
        between_contrasts=between_contrasts,
        mixed_model_terms=single_lmm,
    )

    frames.anova_terms = _safe_read(stats_folder / ANOVA_XLS, "RM-ANOVA Table")

    candidate_lmm_between = _safe_read(stats_folder / LMM_BETWEEN_XLS, MULTIGROUP_MIXED_MODEL_SHEET)
    single_sources_present = any(
        df is not None for df in (frames.single_posthoc, single_lmm, frames.anova_terms)
    )
    between_sources_present = any(
        df is not None for df in (frames.between_contrasts, candidate_lmm_between)
    )
    if between_sources_present and not single_sources_present:
        frames.pipeline_id = PipelineId.BETWEEN
        frames.mixed_model_terms = candidate_lmm_between
    elif single_sources_present:
        frames.pipeline_id = PipelineId.SINGLE
        frames.mixed_model_terms = single_lmm
    elif candidate_lmm_between is not None:
        frames.mixed_model_terms = candidate_lmm_between

    return build_summary_from_frames(frames, config)
