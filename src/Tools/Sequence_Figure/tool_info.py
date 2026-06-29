"""Editable user-facing information for the Sequence Figure tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SEQUENCE_FIGURE_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Sequence Figure tool creates a simple FPVS stimulus-sequence illustration
from user-selected image files. It is meant for methods figures, posters, and
quick visual explanations of base and oddball presentation timing.
</p>

<h3>Typical Workflow</h3>
<p>
Choose the base images and oddball image, confirm the presentation-rate labels,
select an output folder, and export. The generated assets are table-free figure
files that can be placed into manuscripts or slides.
</p>

<h3>Output Notes</h3>
<p>
The exported figure uses the image paths and labels shown in the form. It does
not inspect EEG data or project analysis outputs.
</p>
"""

SEQUENCE_FIGURE_TOOL_INFO = ToolInfoContent(
    key="sequence_figure",
    title="About Sequence Figure",
    html=SEQUENCE_FIGURE_TOOL_INFO_HTML,
)

__all__ = ["SEQUENCE_FIGURE_TOOL_INFO", "SEQUENCE_FIGURE_TOOL_INFO_HTML"]
