"""Editable user-facing information for the Sequence Figure tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SEQUENCE_FIGURE_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Sequence Figure tool creates a simple FPVS stimulus-sequence illustration
from five stimulus images. It center-crops the images, marks the fifth image as
the oddball, and adds timing traces for the presentation and oddball rates.
</p>

<h3>Typical Workflow</h3>
<p>
Choose four representative base images and one oddball image, enter the rate
labels, select an output folder, and export the figure. Every export writes a
600-DPI PNG plus matching PDF and SVG files.
</p>

<h3>Review Before Use</h3>
<p>
The rate fields are figure labels and are not checked against project triggers.
Compare the exported schematic with the actual experiment before using it in a
manuscript or study material.
</p>
"""

SEQUENCE_FIGURE_TOOL_INFO = ToolInfoContent(
    key="sequence_figure",
    title="About Sequence Figure",
    html=SEQUENCE_FIGURE_TOOL_INFO_HTML,
)

__all__ = ["SEQUENCE_FIGURE_TOOL_INFO", "SEQUENCE_FIGURE_TOOL_INFO_HTML"]
