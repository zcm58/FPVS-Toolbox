"""Compatibility facade for Stats summary reporting.

New code should import from `Tools.Stats.reporting.summary`. This module keeps
the historical `summary_utils` import path stable for existing callers and
focused tests.
"""

from __future__ import annotations

from Tools.Stats.reporting.summary import (
    StatsSummaryFrames,
    SummaryConfig,
    build_rm_anova_output,
    build_summary_frames_from_results,
    build_summary_from_files,
    build_summary_from_frames,
    format_mixed_model_plain_language,
    format_rm_anova_summary,
    to_dataframe,
)
from Tools.Stats.reporting.summary.anova import (
    _fmt_p,
    _normalize_effect_name,
    _select_rm_anova_p,
    _summarize_interactions,
    _summarize_rm_anova,
)
from Tools.Stats.reporting.summary.helpers import _pick_column
from Tools.Stats.reporting.summary.mixed_model import (
    _direction_word,
    _extract_sum_coded_label,
    _format_p_value,
    _is_condition_main_effect,
    _is_interaction_term,
    _is_intercept,
    _is_roi_main_effect,
    _summarize_mixed_model,
)
from Tools.Stats.reporting.summary.posthoc import (
    _summarize_posthocs,
    _summarize_single_posthocs_by_direction,
)

__all__ = [
    "StatsSummaryFrames",
    "SummaryConfig",
    "_direction_word",
    "_extract_sum_coded_label",
    "_fmt_p",
    "_format_p_value",
    "_is_condition_main_effect",
    "_is_interaction_term",
    "_is_intercept",
    "_is_roi_main_effect",
    "_normalize_effect_name",
    "_pick_column",
    "_select_rm_anova_p",
    "_summarize_interactions",
    "_summarize_mixed_model",
    "_summarize_posthocs",
    "_summarize_rm_anova",
    "_summarize_single_posthocs_by_direction",
    "build_rm_anova_output",
    "build_summary_frames_from_results",
    "build_summary_from_files",
    "build_summary_from_frames",
    "format_mixed_model_plain_language",
    "format_rm_anova_summary",
    "to_dataframe",
]
