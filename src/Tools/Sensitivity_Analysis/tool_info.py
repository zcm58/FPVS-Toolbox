"""User-facing context for the Sensitivity Analysis tool."""

from __future__ import annotations

from Main_App.gui.components import ToolInfoContent

SENSITIVITY_ANALYSIS_TOOL_INFO_HTML = """
<h2>What This Tool Does</h2>
<p>
Sensitivity Analysis estimates the smallest standardized effect detectable
under assumptions you enter manually. It does not read project data, count
participants, or save results.
</p>

<h2>Participants and Repeated Measurements</h2>
<p>
<b>Sample size (N)</b> is the number of participants. <b>Repeated
measurements</b> are the outcome values contributed by each participant to the
specific within-participant effect being evaluated. They are not the number of
trials, electrodes, harmonics, or EEG samples.
</p>

<h3>How the Count Is Derived</h3>
<ul>
  <li><b>Condition effect:</b> repeated measurements = number of conditions;
  ROIs are assumed averaged or otherwise outside the one-way effect.</li>
  <li><b>ROI effect:</b> repeated measurements = number of ROIs; conditions are
  assumed averaged or otherwise outside the one-way effect.</li>
  <li><b>Omnibus condition × ROI cells:</b> repeated measurements = conditions × ROIs.</li>
</ul>
<p>
For example, 4 conditions and 3 ROIs produce 4 measurements for a condition
effect, 3 for an ROI effect, or 12 condition × ROI cells for the omnibus option.
</p>

<h3>Important Interaction Limitation</h3>
<p>
The omnibus cell option treats all condition × ROI cells as levels of one
within-participant factor. It does <b>not</b> specifically estimate power for a
condition × ROI interaction. A factorial interaction requires a more advanced
power model.
</p>

<h3>Correlation and Epsilon</h3>
<p>
Average correlation describes the expected association among the repeated
outcomes used by the selected effect. Epsilon is the nonsphericity correction;
1.00 represents sphericity. These assumptions can materially change the
detectable effect estimate.
</p>
"""

SENSITIVITY_ANALYSIS_TOOL_INFO = ToolInfoContent(
    key="sensitivity_analysis",
    title="About Sensitivity Analysis",
    html=SENSITIVITY_ANALYSIS_TOOL_INFO_HTML,
)

__all__ = [
    "SENSITIVITY_ANALYSIS_TOOL_INFO",
    "SENSITIVITY_ANALYSIS_TOOL_INFO_HTML",
]
