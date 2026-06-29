"""Editable user-facing information for the Individual Detectability tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

INDIVIDUAL_DETECTABILITY_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Individual Detectability tool estimates whether each participant shows a
detectable FPVS response for selected conditions. It produces participant-first
summaries, electrode-level outputs, and optional figures for reviewing
individual response reliability.
</p>

<h3>Typical Workflow</h3>
<p>
Choose the processed Excel root, select conditions and participants, confirm
output options, then run the analysis. Advanced settings control harmonic
selection, thresholds, ROI behavior, and correction options.
</p>

<h3>Interpretation Notes</h3>
<p>
Individual-level detectability is a review and reporting aid. Check the chosen
harmonics, FDR settings, and excluded participants before comparing results
across conditions or projects.
</p>
"""

INDIVIDUAL_DETECTABILITY_TOOL_INFO = ToolInfoContent(
    key="individual_detectability",
    title="About Individual Detectability",
    html=INDIVIDUAL_DETECTABILITY_TOOL_INFO_HTML,
)

__all__ = [
    "INDIVIDUAL_DETECTABILITY_TOOL_INFO",
    "INDIVIDUAL_DETECTABILITY_TOOL_INFO_HTML",
]
