"""Editable user-facing information for the Ratio Calculator tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

RATIO_CALCULATOR_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
Ratio Calculator is a beta exploratory tool that pairs participants across two
processed conditions. For each ROI, it calculates condition A divided by
condition B for summed BCA, SNR, and z-score values and exports the raw sums
alongside the ratios.
</p>

<h3>Typical Workflow</h3>
<p>
Pick condition A and condition B, confirm the paired participant set, review
optional participant exclusions, and run the calculation. The tool writes
an audit workbook, matching PNG/PDF plots, and a run log to the selected output
folder.
</p>

<h3>Interpretation Notes</h3>
<p>
Ratios are unstable when a denominator is close to zero and are not
automatically normalized or inferential outcomes. Review the underlying
condition values and use this tool only with a justified analysis plan.
</p>
"""

RATIO_CALCULATOR_TOOL_INFO = ToolInfoContent(
    key="ratio_calculator",
    title="About Ratio Calculator",
    html=RATIO_CALCULATOR_TOOL_INFO_HTML,
)

__all__ = ["RATIO_CALCULATOR_TOOL_INFO", "RATIO_CALCULATOR_TOOL_INFO_HTML"]
