"""Top-level Stats summary builder."""

from __future__ import annotations

from Tools.Stats.reporting.summary.anova import _summarize_interactions, _summarize_rm_anova
from Tools.Stats.reporting.summary.mixed_model import _summarize_mixed_model
from Tools.Stats.reporting.summary.models import StatsSummaryFrames, SummaryConfig
from Tools.Stats.reporting.summary.posthoc import _summarize_posthocs


def build_summary_from_frames(frames: StatsSummaryFrames, config: SummaryConfig) -> str:
    """
    Produce a short, human-readable single-group summary.

    Never raises; on missing/invalid data it emits no-result lines for the
    affected sections.
    """

    try:
        anova_lines = _summarize_rm_anova(frames.anova_terms, config)
    except Exception:
        anova_lines = ["- No RM-ANOVA results are available for summary."]

    try:
        posthoc_lines = _summarize_posthocs(frames.single_posthoc, config)
    except Exception:
        posthoc_lines = ["- No post-hoc results are available for summary."]

    try:
        mixed_lines = _summarize_mixed_model(frames.mixed_model_terms, config)
    except Exception:
        mixed_lines = ["- Mixed model: NOT AVAILABLE (not computed by this run)."]

    try:
        interaction_lines = _summarize_interactions(frames.anova_terms, config)
    except Exception:
        interaction_lines = []

    parts = [
        f"--- Summary (alpha = {config.alpha:.2f}, FDR correction: Benjamini-Hochberg) ---",
        "",
        "RM-ANOVA:",
        *(anova_lines or ["- No significant RM-ANOVA effects."]),
        "",
        "Post-hoc comparisons:",
        *(posthoc_lines or ["- No significant post-hoc comparisons after correction."]),
        "",
        "Mixed model:",
        *(mixed_lines or ["- Mixed model: NOT AVAILABLE (not computed by this run)."]),
        "",
        *(["Interactions:", *interaction_lines, ""] if interaction_lines else []),
        "Please see the newly generated Excel files in the '3 - Statistical Analysis' folder for complete results.",
        "Consult your favorite statistics expert (for example, ChatGPT) for help interpreting these findings.",
    ]
    return "\n".join(parts)
