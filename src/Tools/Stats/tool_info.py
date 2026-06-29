"""Editable user-facing information for the Stats tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

STATS_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Statistical Analysis tool gathers processed FPVS condition workbooks and
turns them into group-level analysis tables. It helps you choose included
conditions, manage participant exclusions, define the Summed BCA response, and
export analysis-ready results.
</p>

<h3>Typical Workflow</h3>
<p>
Select the Excel results folder, choose the conditions to analyze, confirm
participant inclusion, and run the single-group analysis. The tool then writes
Stats outputs under the active project and keeps export helpers available for
review, reporting, and downstream publication tools.
</p>

<h3>Interpretation Notes</h3>
<p>
The default Summed BCA harmonic selection follows the toolbox's locked
group-level significant-harmonics method. Review exclusions and ROI definitions
before treating exported results as manuscript-ready.
</p>
"""

STATS_TOOL_INFO = ToolInfoContent(
    key="stats",
    title="About Statistical Analysis",
    html=STATS_TOOL_INFO_HTML,
)

__all__ = ["STATS_TOOL_INFO", "STATS_TOOL_INFO_HTML"]
