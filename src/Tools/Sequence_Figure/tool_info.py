"""Editable user-facing information for the Sequence Figure tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SEQUENCE_FIGURE_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Sequence Figure tool illustrates one to four FPVS conditions, with three
condition rows selected by default. Each row uses four base images and one
oddball image, repeated across two oddball cycles. Timing traces show the
presentation and oddball rates.
</p>

<h3>Typical Workflow</h3>
<p>
Choose the condition count and use each condition tab to select five images
and enter a label (up to 24 characters). Enter the rate labels, choose optional
grayscale-safe line/frame styling or a transparent PDF background, and select
an output folder. Every export writes a 600-DPI PNG plus matching PDF and SVG
files. PNG and SVG backgrounds stay white; grayscale-safe styling does not
convert the stimulus images themselves to grayscale.
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
