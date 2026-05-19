"""Build summary input frames from in-memory Stats results."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from Tools.Stats.common.stats_core import PipelineId
from Tools.Stats.reporting.summary.models import StatsSummaryFrames


def to_dataframe(data) -> Optional[pd.DataFrame]:
    """Coerce common result payloads into a DataFrame when possible."""

    if isinstance(data, pd.DataFrame):
        return data
    if isinstance(data, list) and data:
        try:
            df = pd.DataFrame(data)
            return df if not df.empty else None
        except Exception:
            return None
    if isinstance(data, dict) and data:
        try:
            df = pd.DataFrame(data)
            if not df.empty:
                return df
        except Exception:
            pass
        try:
            flattened: list = []
            for value in data.values():
                if isinstance(value, dict):
                    flattened.extend(value.values())
                else:
                    flattened.append(value)
            if flattened:
                df = pd.DataFrame(flattened)
                return df if not df.empty else None
        except Exception:
            return None
    return None


def build_summary_frames_from_results(
    pipeline_id: PipelineId,
    *,
    single_posthoc: Optional[pd.DataFrame] = None,
    rm_anova_results: Optional[pd.DataFrame] = None,
    mixed_model_results: Optional[pd.DataFrame] = None,
    harmonic_results: Optional[pd.DataFrame | list[dict]] = None,
) -> StatsSummaryFrames:
    """Build summary frames from worker/controller result payloads."""

    frames = StatsSummaryFrames(pipeline_id=pipeline_id)
    if pipeline_id is PipelineId.SINGLE:
        frames.single_posthoc = to_dataframe(single_posthoc)
        frames.anova_terms = to_dataframe(rm_anova_results)
        frames.mixed_model_terms = to_dataframe(mixed_model_results)
    frames.harmonic_results = to_dataframe(harmonic_results)
    return frames
