"""Editable user-facing information for the Publication Report tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

PUBLICATION_REPORT_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Publication Report tool builds a project-level report bundle from processed
FPVS results. It collects selected conditions, ROI definitions, participant
inclusion details, source tables, QC summaries, and draft narrative outputs in
one reproducible folder.
</p>

<h3>Typical Workflow</h3>
<p>
Choose the processed Excel root, select the conditions to include, review the
report labels and ROIs, choose output formats, and generate the bundle. The
tool writes Markdown, Word, workbook, audit, and log artifacts when those
outputs are enabled.
</p>

<h3>Interpretation Notes</h3>
<p>
This tool is designed as a manuscript-drafting aid. Review all generated text,
warnings, participant inclusion details, and statistical assumptions before
using the output in a final report.
</p>
"""

PUBLICATION_REPORT_TOOL_INFO = ToolInfoContent(
    key="publication_report",
    title="About Publication Report",
    html=PUBLICATION_REPORT_TOOL_INFO_HTML,
)

__all__ = ["PUBLICATION_REPORT_TOOL_INFO", "PUBLICATION_REPORT_TOOL_INFO_HTML"]
