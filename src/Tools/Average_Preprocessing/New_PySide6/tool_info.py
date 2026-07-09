"""Editable user-facing information for the Epoch Averaging tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

EPOCH_AVERAGING_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
Epoch Averaging is a beta tool that starts from raw BDF files, applies the
active project preprocessing settings, and combines selected event-ID epochs
before FFT, SNR, BCA, and z-score calculations. Use it only when those event
IDs are scientifically justified as measurements of the same response.
</p>

<h3>Typical Workflow</h3>
<p>
Select the raw BDF files, create an averaging group with the event IDs to
combine, choose Pool Trials or Average of Averages, and start processing. The
combined response is passed through the normal FPVS post-processing stage.
</p>

<h3>Interpretation Notes</h3>
<p>
Only combine files when the conditions are scientifically appropriate to treat
as one response family. Pool Trials weights event sets by accepted trial count;
Average of Averages gives each available event set equal weight. Record the
chosen rule and keep the original conditions auditable.
</p>
"""

EPOCH_AVERAGING_TOOL_INFO = ToolInfoContent(
    key="epoch_averaging",
    title="About Epoch Averaging",
    html=EPOCH_AVERAGING_TOOL_INFO_HTML,
)

__all__ = ["EPOCH_AVERAGING_TOOL_INFO", "EPOCH_AVERAGING_TOOL_INFO_HTML"]
