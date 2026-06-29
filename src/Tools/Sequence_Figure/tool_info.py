"""Editable user-facing information for the Sequence Figure tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SEQUENCE_FIGURE_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Sequence Figure tool creates a simple FPVS stimulus-sequence illustration
from your FPVS experiments. You can use this tool to create a high resolution figure for posters, 
reports, publications, etc. This is certainly not the only way to generate a figure like this - powerpoint or Canva
may be your preference, but this option was built in as a backup. 
</p>
</p>

<h3>Typical Workflow</h3>
<p>
Choose four images that represent the base images from one of your FPVS conditions. The fifth image
will be displayed as the oddball image in the figure. 
</p>

"""

SEQUENCE_FIGURE_TOOL_INFO = ToolInfoContent(
    key="sequence_figure",
    title="About Sequence Figure",
    html=SEQUENCE_FIGURE_TOOL_INFO_HTML,
)

__all__ = ["SEQUENCE_FIGURE_TOOL_INFO", "SEQUENCE_FIGURE_TOOL_INFO_HTML"]
