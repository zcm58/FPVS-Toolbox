"""Editable user-facing information for the Epoch Averaging tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

EPOCH_AVERAGING_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
The Epoch Averaging tool combines compatible FPVS EEG files before downstream
FFT, SNR, BCA, and Z-score calculations. It is intended for projects where
multiple conditions are expected to measure the same underlying response and
should be pooled or averaged together. For example, if you included two FPVS conditions
with base images as neutral faces and oddball images as happy faces, but you pulled the images from two separate
datasets, you might want to merge both conditions to consider them as part of one singular response measure.

This tool averages the time domain epochs of both conditions together across each participant before continuing
with the data processing pipeline.

Note: This tool is experimental. Ideally, rather than averaging two conditions together, this type of question
would be addressed in the experimental design phase. This tool will likely be removed in a future update.
</p>

<h3>Typical Workflow</h3>
<p>
Select the data files you'd like to average. Define which groups you're going to average, choose the averaging method,
and start processing. The tool writes averaged outputs that can then be used by the
rest of the FPVS workflow.
</p>

<h3>Interpretation Notes</h3>
<p>
Only combine files when the conditions are scientifically appropriate to treat
as one response family. Keep the group definitions clear so later analysis and
reporting remain understandable.
</p>
"""

EPOCH_AVERAGING_TOOL_INFO = ToolInfoContent(
    key="epoch_averaging",
    title="About Epoch Averaging",
    html=EPOCH_AVERAGING_TOOL_INFO_HTML,
)

__all__ = ["EPOCH_AVERAGING_TOOL_INFO", "EPOCH_AVERAGING_TOOL_INFO_HTML"]
