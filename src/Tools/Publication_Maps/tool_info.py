"""Editable user-facing information for the Scalp Maps tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SCALP_MAPS_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Scalp Maps tool exports publication-ready topographic figures from
processed FPVS workbooks. It can render BCA, SNR, and Z-score maps for selected
conditions using the current analysis settings and ROI context.
</p>

<h3>Typical Workflow</h3>
<p>
Select the Excel root folder, choose one or more conditions, confirm metric and
color-scale options, and run the export. When two conditions are selected, the
paired condition figure option creates side-by-side maps for easier visual
comparison.
</p>

<h3>Output Notes</h3>
<p>
The tool writes matching high-resolution PNG and PDF figure assets plus a
source workbook. Fixed color ranges are useful when comparing conditions across
the same manuscript figure set.
</p>
"""

SCALP_MAPS_TOOL_INFO = ToolInfoContent(
    key="scalp_maps",
    title="About Scalp Maps",
    html=SCALP_MAPS_TOOL_INFO_HTML,
)

__all__ = ["SCALP_MAPS_TOOL_INFO", "SCALP_MAPS_TOOL_INFO_HTML"]
