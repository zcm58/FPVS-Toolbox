"""Editable user-facing information for the Ratio Calculator tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

RATIO_CALCULATOR_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Ratio Calculator compares two processed FPVS condition folders and exports
participant-level and group-level ratio summaries. It is useful when a project
needs a normalized response measure, such as one condition divided by another.
</p>

<h3>Typical Workflow</h3>
<p>
Pick condition A and condition B, confirm the paired participant set, review
optional participant exclusions, and run the calculation. The tool writes
tables, plots, and logs to the selected output folder.
</p>

<h3>Interpretation Notes</h3>
<p>
Ratios can be sensitive to very small denominators and participant-level
outliers. Review the exported diagnostics before using the summaries for
manuscript language.
</p>
"""

RATIO_CALCULATOR_TOOL_INFO = ToolInfoContent(
    key="ratio_calculator",
    title="About Ratio Calculator",
    html=RATIO_CALCULATOR_TOOL_INFO_HTML,
)

__all__ = ["RATIO_CALCULATOR_TOOL_INFO", "RATIO_CALCULATOR_TOOL_INFO_HTML"]
