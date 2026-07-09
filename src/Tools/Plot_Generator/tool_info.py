"""Editable user-facing information for the SNR Plots tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SNR_PLOTS_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
SNR Plots reads the FullSNR sheets created during processing and generates
participant-averaged spectra for the selected regions of interest. You can edit
titles, legend labels, colors, and axis ranges. Every figure is exported as a
matching 600-DPI PNG and PDF.
</p>

<h3>Typical Workflow</h3>
<ol>
  <li>Confirm the processed Excel root and output folder.</li>
  <li>Select a condition and one or all ROIs.</li>
  <li>Optionally adjust labels, colors, axis ranges, and spectral QC.</li>
  <li>Generate and review the PNG/PDF figure pairs.</li>
</ol>

<h3>Comparison Modes</h3>
<p>
Single-group projects can overlay two conditions. Multi-group projects use a
one-condition group overlay based on participant assignments in project.json;
workbooks without a matching assignment are omitted from group curves and
reported in the log.
</p>

"""

SNR_PLOTS_TOOL_INFO = ToolInfoContent(
    key="snr_plots",
    title="About SNR Plots",
    html=SNR_PLOTS_TOOL_INFO_HTML,
)

__all__ = ["SNR_PLOTS_TOOL_INFO", "SNR_PLOTS_TOOL_INFO_HTML"]
