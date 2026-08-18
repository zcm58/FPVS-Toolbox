"""Editable user-facing information for the SNR Plots tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SNR_PLOTS_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
SNR Plots reads the FullSNR sheets created during processing and generates
participant-averaged spectra for the selected regions of interest. You can edit
legend labels, colors, axis labels, and axis ranges. Every figure is exported
directly to the selected plot folder as a matching 600-DPI PNG and PDF pair.
</p>

<h3>Typical Workflow</h3>
<ol>
  <li>Confirm the processed Excel root and output folder.</li>
  <li>Select a condition and one or all ROIs.</li>
  <li>Optionally adjust labels, colors, axis ranges, and spectral QC.</li>
  <li>Select <b>Generate SNR Plots</b>, then review the PNG/PDF pairs in the
  plot folder.</li>
</ol>

<p>
SNR Plots creates figures only. It does not create source-data spreadsheets,
spectral-QC workbooks, JSON manifests, or per-run subfolders.
Detailed run messages and workbook warnings are available through
<b>View Log</b>.
</p>

<h3>Comparison Modes</h3>
<p>
Single-group projects can overlay two conditions. Multi-group projects use a
one-condition group overlay based on participant assignments in project.json;
workbooks without a matching assignment are omitted from group curves and
reported in the log. Each group legend shows the number of participants that
contributed usable data to that ROI. Selected groups without usable data are
flagged and omitted; the tool never substitutes a pooled curve for an empty
group overlay.
</p>
<p>
Group-overlay exports add <code>_group_overlay</code> to the filename so they
remain separate from ordinary single-condition figures. The first two groups
use the editable colors and labels; additional groups receive automatic,
distinct colors, markers, and project labels.
</p>
<p>
Repeated-session projects explicitly choose either one session for the normal
condition workflow or two sessions for a descriptive session comparison.
Session figures stack stable groups vertically at the normal SNR plot width,
overlay both sessions within each group, and label each phase with its visit
index and participant n. Missing canonical recording/session identity blocks the run.
When all participants completed phases in one fixed order, phase remains
confounded with visit order and elapsed time; the page and figure state this
interpretation limit.
</p>

"""

SNR_PLOTS_TOOL_INFO = ToolInfoContent(
    key="snr_plots",
    title="About SNR Plots",
    html=SNR_PLOTS_TOOL_INFO_HTML,
)

__all__ = ["SNR_PLOTS_TOOL_INFO", "SNR_PLOTS_TOOL_INFO_HTML"]
