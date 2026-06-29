"""Editable user-facing information for the SNR Plots tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SNR_PLOTS_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The SNR Plots tool creates publication-oriented spectra from processed FPVS
Excel files. It lets you select conditions and ROIs, compare conditions when
needed, customize labels and axis ranges, and save repeatable plot defaults.
</p>

<h3>Typical Workflow</h3>
<p>
Choose the folder containing processed condition workbooks, select the output
folder, pick the condition and ROI, then generate the spectra. Optional
comparison overlays and legend labels help prepare figures for review or
publication drafts.
</p>

<h3>Output Notes</h3>
<p>
Plots are generated from existing processed outputs. Changing labels, colors,
or axis limits affects the figure presentation only; it does not alter the
source workbook values.
</p>
"""

SNR_PLOTS_TOOL_INFO = ToolInfoContent(
    key="snr_plots",
    title="About SNR Plots",
    html=SNR_PLOTS_TOOL_INFO_HTML,
)

__all__ = ["SNR_PLOTS_TOOL_INFO", "SNR_PLOTS_TOOL_INFO_HTML"]
