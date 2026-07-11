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
  <li>Select a paired test, repeated-measures ANOVA, or mixed-model simulation.</li>
  <li>For repeated designs, describe the conditions, ROIs, and effect.</li>
  <li>Review power, alpha, correlation, and epsilon.</li>
  <li>Select <b>Calculate</b> and review the result and interpretation.</li>
</ol>

<h3>Reading the Result</h3>
<p>
“Cohen's dz = 0.60 at 80% power” means that, if the true effect were 0.60,
repeating the same study many times under the stated assumptions would be
expected to produce a statistically significant result about 80% of the time.
If the true effect were smaller, that percentage would be below 80%, but the
study could still detect it. A non-significant result does not prove that no
effect exists.
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
The one-way ANOVA omnibus option treats all condition × ROI cells as levels of
one factor and tests whether any cell means differ. It does <b>not</b> isolate
the condition effect, ROI effect, or condition × ROI interaction. The separate
mixed-model simulation supports one standardized interaction contrast but does
not model between-participant groups. Mixed within/between designs require a
different power model.
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

MIXED_MODELS_HTML = """
<h2>Linear Mixed-Model Simulation</h2>
<p>
Mixed-model power is estimated by Monte Carlo simulation. The tool repeatedly
generates balanced FPVS datasets, fits the planned model, and records how often
the selected fixed-effect block is significant. It then searches for the
standardized contrast corresponding approximately to the requested power.
</p>

<h3>Supported Model</h3>
<p>
The current simulation is deliberately limited to
<b>value ~ condition × ROI + participant random intercept</b>, matching the
toolbox's current FPVS mixed-model structure. It uses sum contrasts and an
omnibus Wald test for the selected condition, ROI, or interaction coefficient
block. It does not support between-participant groups, covariates, random
slopes, missing cells, or generalized outcomes.
</p>

<h3>Effect Definition</h3>
<ul>
  <li><b>Condition:</b> a standardized difference between two condition levels,
  embedded in the full condition factor and repeated across ROIs.</li>
  <li><b>ROI:</b> a standardized difference between two ROI levels, embedded in
  the full ROI factor and repeated across conditions.</li>
  <li><b>Interaction:</b> a standardized 2 × 2 difference-in-differences embedded
  in the full condition × ROI design.</li>
</ul>
<p>
Effects are expressed in residual-standard-deviation units. These are planned
contrast magnitudes, not Cohen's d, and conventional small/medium/large labels
are not applied.
</p>

<h3>Simulation Uncertainty</h3>
<p>
The reported Monte Carlo interval describes uncertainty caused by running a
finite number of simulations. It is not a confidence interval for the true
study effect. More simulations improve precision but increase runtime. Failed
or non-converged models count as non-detections and are reported separately.
</p>

<h3>Method Reference</h3>
<p>
The simulation workflow follows the general approach described by Green and
MacLeod (2016): define a mixed model and design, repeatedly simulate and refit
the model, and estimate power from the proportion of significant tests.
</p>
<p>
Green, P., &amp; MacLeod, C. J. (2016). SIMR: an R package for power analysis
of generalized linear mixed models by simulation. <i>Methods in Ecology and
Evolution, 7</i>(4), 493–498.
<a href="https://doi.org/10.1111/2041-210X.12504">https://doi.org/10.1111/2041-210X.12504</a>
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
<p>
The linear mixed-model option uses Statsmodels MixedLM with REML estimation and
an omnibus Wald test of the selected sum-coded fixed-effect coefficient block.
The fixed-N effect search and final power estimate use reproducible Monte Carlo
simulation.
</p>

<h3>Implementation References</h3>
<ul>
  <li><a href="https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestPower.solve_power.html">Statsmodels TTestPower documentation</a></li>
  <li><a href="https://pingouin-stats.org/generated/pingouin.power_rm_anova.html">Pingouin repeated-measures power documentation</a></li>
  <li><a href="https://doi.org/10.1525/collabra.33267">Lakens (2022), Sample Size Justification</a></li>
  <li><a href="https://doi.org/10.1111/2041-210X.12504">Green &amp; MacLeod (2016), mixed-model power by simulation</a></li>
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
        ToolInfoTab("mixed_models", "Mixed Models", MIXED_MODELS_HTML),
        ToolInfoTab("interpretation", "Interpretation", INTERPRETATION_HTML),
        ToolInfoTab("methods", "Methods", METHODS_HTML),
    ),
)

__all__ = [
    "ASSUMPTIONS_HTML",
    "FPVS_DESIGN_HTML",
    "INTERPRETATION_HTML",
    "METHODS_HTML",
    "MIXED_MODELS_HTML",
    "QUICK_GUIDE_HTML",
    "SENSITIVITY_ANALYSIS_TOOL_INFO",
]
