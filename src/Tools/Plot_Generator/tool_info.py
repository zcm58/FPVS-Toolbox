"""Editable user-facing information for the SNR Plots tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SNR_PLOTS_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The SNR Plot tool lets you quickly generate SNR plots from your data after processing. You can
overlay two conditions on the same figure for comparison, and change your x and y axis titles
and ranges.

The tool outputs figures in 600dpi .png and .pdf formats, which should be acceptable for most publications.

</p>

<h3>Typical Workflow</h3>
<ol>
  <li>Choose the conditions you'd like to plot</li>
  <li>Select colors for each figures</li>
  <li>Set your axis ranges</li>
  <li>Set titles for your legend</li>
  <li>Generate Plots!</li>
</ol>


"""

SNR_PLOTS_TOOL_INFO = ToolInfoContent(
    key="snr_plots",
    title="About SNR Plots",
    html=SNR_PLOTS_TOOL_INFO_HTML,
)

__all__ = ["SNR_PLOTS_TOOL_INFO", "SNR_PLOTS_TOOL_INFO_HTML"]
