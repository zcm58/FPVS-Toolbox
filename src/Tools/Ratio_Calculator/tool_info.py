"""Editable user-facing information for the Ratio Calculator tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

RATIO_CALCULATOR_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Ratio Calculator tool is an experimental tool designed to allow you to explore the ratio
between two of your FPVS conditions. This exploratory measure might be useful in cases where you'd like to conduct
between participant analysis. By dividing two conditions together, you get a normalized ratio that makes comparison
more simple. However, there are some caveats.

The ratio tool uses BCA values in the numerator and denominator. Numbers very close to zero can significantly inflate
or deflate this ratio, so use this sparingly.
</p>

<h3>Typical Workflow</h3>
<p>
Pick condition A and condition B, confirm the paired participant set, review
optional participant exclusions, and run the calculation. The tool writes
tables, plots, and logs to your selected output folder.
</p>


"""

RATIO_CALCULATOR_TOOL_INFO = ToolInfoContent(
    key="ratio_calculator",
    title="About Ratio Calculator",
    html=RATIO_CALCULATOR_TOOL_INFO_HTML,
)

__all__ = ["RATIO_CALCULATOR_TOOL_INFO", "RATIO_CALCULATOR_TOOL_INFO_HTML"]
