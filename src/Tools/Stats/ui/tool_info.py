"""Editable user-facing information for Standard FPVS Screening."""

from __future__ import annotations

from Main_App.gui.components import SurfaceSize, ToolInfoContent, ToolInfoTab

WORKFLOW_HTML = """
<h2>Workflow</h2>
<ol>
  <li><b>Choose the processed Excel folder.</b> The toolbox reads participant,
      condition, ROI, and canonical project-group information.</li>
  <li><b>Review Analysis Design.</b> Confirm the mode, group sizes, selected
      conditions, available data coverage, and manual exclusions.</li>
  <li><b>Use Advanced only when needed.</b> Scientific provenance and optional
      robust or leave-one-out sensitivity checks remain available; the primary
      statistical method is fixed.</li>
  <li><b>Run Standard Screening.</b> Single-group projects screen positive
      responses and Condition/ROI patterns. Projects with exactly two canonical
      groups additionally screen direct group differences and broader group
      patterns.</li>
  <li><b>Read At a glance first.</b> Run log records processing and export
      messages. The exported results workbook retains the technical audit
      trail.</li>
</ol>

<h3>How incomplete observations are handled</h3>
<p>
The screening freezes the eligible participant cohort, then uses each finite
selected observation in the participant-random-intercept LMM. Missing values
are not imputed. This likelihood analysis relies on the stated
missing-at-random assumption; missingness related to unobserved responses can
still bias results. When every declared cell is complete and unique, a
secondary ANOVA compatibility check also runs automatically.
</p>

<h3>What runs in the background</h3>
<p>
Long calculations run in workers so the window stays responsive. The phase and
progress area shows structured pipeline updates. Cancel requests stop at a safe
checkpoint; cancellation is reported separately from failure.
</p>
"""

STANDARD_METHODS_HTML = """
<h2>Standard screening methods</h2>
<h3>One locked first-round workflow</h3>
<p>
The primary factorial analysis is a participant-random-intercept linear mixed
model. Positive-response tests use the prespecified one-sided
<b>greater than zero</b> question. Primary named test families use Holm
family-wise correction. Finite observations are used without imputation, and
ANOVA is secondary compatibility evidence only for exactly balanced data.
</p>

<h3>Harmonic provenance remains visible</h3>
<p>
Same-sample adaptive harmonic selection keeps response evidence visibly
exploratory post-selection. A fixed list is treated as independently selected
only when that provenance is explicitly attested and documented. Changing a
label cannot create independence.
</p>

<h3>Screening is not the final custom model</h3>
<p>
Standard FPVS Screening is a transparent first-round screen. Covariates,
additional groups, random slopes, longitudinal structure, and other
study-specific questions require a planned custom analysis.
</p>
"""

# Backward-compatible name retained for callers of the former profile page.
ANALYSIS_PROFILES_HTML = STANDARD_METHODS_HTML

INTERPRETATION_HTML = """
<h2>How to interpret results</h2>
<h3>Keep the scientific questions separate</h3>
<ul>
  <li><b>Positive response:</b> is Summed BCA greater than zero?</li>
  <li><b>Within-participant pattern:</b> do mean responses differ by Condition,
      ROI, or their interaction?</li>
  <li><b>Between-group pattern:</b> for exactly two groups, where do
      model-estimated group differences occur and is there a broader group
      pattern?</li>
</ul>
<p>
A reliable pooled response is not evidence that conditions or groups differ.
At a glance translates the primary conclusions into a few plain-language
lines. The workbook retains estimates, intervals, p-values, and the complete
test inventory.
</p>

<h3>Read corrected evidence first</h3>
<p>
The Holm-adjusted value is used for each declared family claim. An unadjusted
p-value can be descriptive but should not replace the corrected result. A
nonsignificant result means the screen did not establish a difference; it does
<b>not</b> prove equivalence or no effect. Group results are associations, not
causal effects.
</p>

<h3>Assumptions and sensitivity analyses</h3>
<p>
The workbook records mixed-model convergence and singularity checks,
normality diagnostics, missingness, sample sizes, corrections, and harmonic
provenance. Robust and leave-one-out results are secondary sensitivity
evidence; they do not silently replace the primary LMM.
</p>

<h3>Detailed exports</h3>
<p>
The saved workbook contains the complete test inventory, LMM-derived
model-estimated contrasts, confidence intervals, effect sizes, assumptions,
correction families, exclusions, coverage, and methods needed for review or
manuscript reporting.
</p>
"""

# Backward-compatible name retained for callers that imported the previous
# single-page content.
STATS_TOOL_INFO_HTML = WORKFLOW_HTML

STATS_TOOL_INFO = ToolInfoContent(
    key="stats",
    title="About Standard FPVS Screening",
    html="",
    size=SurfaceSize(width=760, height=600, min_width=600, min_height=460),
    tabs=(
        ToolInfoTab("workflow", "Workflow", WORKFLOW_HTML),
        ToolInfoTab(
            "analysis_profiles",
            "Standard methods",
            ANALYSIS_PROFILES_HTML,
        ),
        ToolInfoTab(
            "interpretation",
            "How to interpret results",
            INTERPRETATION_HTML,
        ),
    ),
)

__all__ = [
    "ANALYSIS_PROFILES_HTML",
    "INTERPRETATION_HTML",
    "STATS_TOOL_INFO",
    "STATS_TOOL_INFO_HTML",
    "STANDARD_METHODS_HTML",
    "WORKFLOW_HTML",
]
