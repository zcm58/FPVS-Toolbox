"""User-facing context for the Sensitivity Analysis tool."""

from __future__ import annotations

from Main_App.gui.components import SurfaceSize, ToolInfoContent, ToolInfoTab

QUICK_GUIDE_HTML = """
<h2>What This Tool Answers</h2>
<p>
Given a sample size, alpha level, desired power, and design assumptions, this
tool estimates the <b>minimum detectable standardized effect</b>. A smaller
number means the design is sensitive to smaller effects.
</p>
<p>
The tool does not read project data, count participants, inspect an observed
effect, or calculate “observed power.” It does not save or export anything.
</p>

<h3>Quick Workflow</h3>
<ol>
  <li>Enter the number of complete, analyzable participants.</li>
  <li>Select a paired test or repeated-measures ANOVA.</li>
  <li>For ANOVA, describe the conditions, ROIs, and effect being evaluated.</li>
  <li>Review power, alpha, correlation, and epsilon.</li>
  <li>Select <b>Calculate</b> and read the plain-language result.</li>
</ol>

<h3>Reading the Result</h3>
<p>
“Cohen's dz = 0.60” means the model reaches the requested power at an effect of
approximately 0.60 under the stated assumptions. Smaller effects are not ruled
out; they have less than the requested power in this model.
</p>
"""

FPVS_DESIGN_HTML = """
<h2>Participants and Repeated Measurements</h2>
<p>
<b>Sample size (N)</b> is the number of participants expected to contribute
complete data to the analysis. Repeated measurements are the outcome values
contributed by each participant to the specific within-participant effect.
They are not trials, electrodes, harmonics, or EEG samples.
</p>

<h3>How the Count Is Derived</h3>
<ul>
  <li><b>Condition effect:</b> measurements = number of conditions. ROIs are
  assumed averaged or otherwise outside this one-way effect.</li>
  <li><b>ROI effect:</b> measurements = number of ROIs. Conditions are assumed
  averaged or otherwise outside this one-way effect.</li>
  <li><b>Omnibus condition × ROI cells:</b> measurements = conditions × ROIs.</li>
</ul>
<p>
Example: 4 conditions and 3 ROIs produce 4 measurements for a condition effect,
3 for an ROI effect, or 12 cell means for the omnibus option.
</p>

<h3>Important Design Limit</h3>
<p>
The omnibus option treats all condition × ROI cells as levels of one factor and
tests whether any cell means differ. It does <b>not</b> isolate the condition
effect, ROI effect, or condition × ROI interaction. The current calculator also
does not model between-participant groups. Factorial interactions and mixed
within/between designs require a different power model.
</p>
"""

ASSUMPTIONS_HTML = """
<h2>Core Assumptions</h2>
<ul>
  <li><b>Analyzable N:</b> use the number expected to have complete observations
  for the planned test, after anticipated exclusions or attrition.</li>
  <li><b>Balanced repeated measures:</b> the ANOVA calculation assumes the same
  participant count at every measurement.</li>
  <li><b>Average correlation:</b> the expected average association among the
  repeated outcomes used by the selected effect.</li>
  <li><b>Epsilon:</b> the nonsphericity correction. A value of 1.00 represents
  sphericity; the mathematical lower bound depends on the measurement count.</li>
  <li><b>Alpha:</b> the Type I error rate for this test. The tool does not apply
  a multiple-comparison correction automatically.</li>
  <li><b>One-sided tests:</b> appropriate only for a directional hypothesis
  chosen before examining the data. An effect in the opposite direction does
  not support that one-sided test.</li>
</ul>

<h3>Why Assumptions Matter</h3>
<p>
Sample size, correlation, epsilon, alpha, and desired power all affect the
detectable effect. A precise result is conditional on these inputs; it is not a
guarantee about the observed study outcome.
</p>
"""

INTERPRETATION_HTML = """
<h2>Interpretation</h2>
<p>
The estimate is a detection threshold under the entered assumptions, not an
expected effect and not evidence that smaller effects are absent. Compare it
with prior FPVS evidence and the smallest effect that would matter for the
research question.
</p>

<h3>Conventional Magnitude Labels</h3>
<p>
The displayed small, medium, and large labels are conventional descriptive
benchmarks. They do not establish theoretical, clinical, or practical
importance.
</p>

<h3>Reporting Template</h3>
<p>
“A sensitivity analysis indicated that, with N = [participants], α = [alpha],
and [power]% power, the design could detect a minimum standardized effect of
[metric] = [value], under the stated design assumptions.”
</p>

<h3>Avoid These Conclusions</h3>
<ul>
  <li>Do not say the study is guaranteed to detect every effect above the value.</li>
  <li>Do not say effects below the value are absent or unimportant.</li>
  <li>Do not describe the omnibus cell calculation as interaction power.</li>
</ul>
"""

METHODS_HTML = """
<h2>Calculation Details</h2>
<p>
The paired/one-sample calculation solves for Cohen's dz using the number of
complete pairs, alpha, desired power, and test sidedness.
</p>
<p>
The repeated-measures calculation is a balanced one-way repeated-measures
ANOVA. It uses sample size, repeated-measure count, average correlation, and
epsilon to solve for eta-squared, then converts to Cohen's f using
<b>f = sqrt(η² / (1 − η²))</b>.
</p>

<h3>Implementation References</h3>
<ul>
  <li><a href="https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestPower.solve_power.html">Statsmodels TTestPower documentation</a></li>
  <li><a href="https://pingouin-stats.org/generated/pingouin.power_rm_anova.html">Pingouin repeated-measures power documentation</a></li>
  <li><a href="https://doi.org/10.1525/collabra.33267">Lakens (2022), Sample Size Justification</a></li>
</ul>
"""

SENSITIVITY_ANALYSIS_TOOL_INFO = ToolInfoContent(
    key="sensitivity_analysis",
    title="About Sensitivity Analysis",
    html="",
    size=SurfaceSize(width=760, height=600, min_width=600, min_height=460),
    tabs=(
        ToolInfoTab("quick_guide", "Quick Guide", QUICK_GUIDE_HTML),
        ToolInfoTab("fpvs_design", "FPVS Design", FPVS_DESIGN_HTML),
        ToolInfoTab("assumptions", "Assumptions", ASSUMPTIONS_HTML),
        ToolInfoTab("interpretation", "Interpretation", INTERPRETATION_HTML),
        ToolInfoTab("methods", "Methods", METHODS_HTML),
    ),
)

__all__ = [
    "ASSUMPTIONS_HTML",
    "FPVS_DESIGN_HTML",
    "INTERPRETATION_HTML",
    "METHODS_HTML",
    "QUICK_GUIDE_HTML",
    "SENSITIVITY_ANALYSIS_TOOL_INFO",
]
