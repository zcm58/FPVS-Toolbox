"""Editable user-facing information for the Stats tool."""

from __future__ import annotations

from Main_App.gui.components import SurfaceSize, ToolInfoContent, ToolInfoTab

WORKFLOW_HTML = """
<h2>Workflow</h2>
<ol>
  <li><b>Choose the processed Excel folder.</b> The toolbox reads participant,
      condition, ROI, and canonical project-group information.</li>
  <li><b>Review Analysis Design.</b> Confirm the mode, group sizes, selected
      conditions, and which conditions form the primary complete core.</li>
  <li><b>Choose Advanced settings only when needed.</b> The defaults keep
      related tests in declared correction families and run useful sensitivity
      checks.</li>
  <li><b>Run the mode-aware analysis.</b> Single-group projects assess response
      detection and within-subject Condition/ROI effects. Multi-group projects
      additionally test overall and Condition/ROI-dependent group effects.</li>
  <li><b>Read At a glance first.</b> Run log records processing and export
      messages. The exported results workbook retains the technical audit
      trail.</li>
</ol>

<h3>Why some conditions may be excluded</h3>
<p>
The primary analysis freezes the eligible participant cohort first. It then
retains only conditions for which every included participant contributes one
finite response in every selected ROI. This “complete core” prevents the
question from changing because different people contributed to different
conditions. An available-case model would be a separately labelled secondary
analysis. The current native pipeline does not run that model, so its scope
control remains locked to the primary complete core.
</p>

<h3>What runs in the background</h3>
<p>
Long calculations run in workers so the window stays responsive. The phase and
progress area shows structured pipeline updates. Cancel requests stop at a safe
checkpoint; cancellation is reported separately from failure.
</p>
"""

ANALYSIS_PROFILES_HTML = """
<h2>Analysis profiles</h2>
<h3>Published-style exploratory</h3>
<p>
This is the normal default when the response harmonics were selected
adaptively from the same sample. It supports conventional FPVS summaries,
explicit multiple-comparison correction, and robust or resampling sensitivity
analyses. Response-versus-zero p-values are labelled
<b>exploratory post-selection</b>.
</p>

<h3>Confirmatory</h3>
<p>
Use this profile only when the participant cohort, hypotheses, direction,
follow-up families, and harmonic list were specified independently of the
analyzed responses. The default family-wise correction is Holm. A one-sided
“greater than zero” response test is appropriate only when that directional
hypothesis was justified in advance.
</p>

<h3>Harmonic provenance cannot be changed by a label</h3>
<p>
Selecting Confirmatory does not make a same-sample harmonic range independent.
A user-entered fixed list also remains unverified unless its independent
selection is explicitly attested and documented. The persistent warning below
the setup tabs states the interpretation that applies to the current choice.
</p>

<h3>Correction choices</h3>
<ul>
  <li><b>Holm:</b> controls the family-wise error rate for an “any result”
      claim.</li>
  <li><b>Benjamini-Hochberg FDR:</b> supports an explicitly exploratory
      discovery screen.</li>
  <li><b>Max-|t|:</b> a participant-level resampling sensitivity that controls
      a declared family jointly when that analysis is estimable.</li>
</ul>
"""

INTERPRETATION_HTML = """
<h2>How to interpret results</h2>
<h3>Keep the scientific questions separate</h3>
<ul>
  <li><b>Response detection:</b> is Summed BCA different from zero?</li>
  <li><b>Within-subject effects:</b> do mean responses differ by Condition,
      ROI, or their interaction?</li>
  <li><b>Between-group effects:</b> do group means differ overall or depending
      on Condition/ROI?</li>
</ul>
<p>
A reliable pooled response is not evidence that conditions or groups differ.
The At a glance summary translates the primary conclusions into a few
plain-language lines. It separates primary findings from secondary checks and
leaves p-values, effect sizes, uncertainty intervals, and test inventories in
the exported workbook.
</p>

<h3>Read corrected evidence first</h3>
<p>
When an adjusted p-value is available, it is the value used for the family
claim. An unadjusted p-value can be descriptive but should not replace the
corrected result. A nonsignificant result means the analysis did not establish
a difference; it does <b>not</b> prove equivalence or no effect.
</p>

<h3>Assumptions and sensitivity analyses</h3>
<p>
The exported results workbook records normality diagnostics, sphericity or
Greenhouse-Geisser handling, mixed-model convergence/singularity, missingness,
sample sizes, corrections, and harmonic provenance. Robust, resampling, and
leave-one-out results are sensitivity evidence. Agreement strengthens
confidence; a sensitivity-only finding is not silently promoted to the primary
conclusion.
</p>

<h3>Detailed exports</h3>
<p>
The saved workbook contains the complete test inventory, estimates, confidence
intervals, effect sizes, assumptions, correction families, exclusions,
coverage, and methods needed for review or manuscript reporting.
</p>
"""

# Backward-compatible name retained for callers that imported the previous
# single-page content.
STATS_TOOL_INFO_HTML = WORKFLOW_HTML

STATS_TOOL_INFO = ToolInfoContent(
    key="stats",
    title="About Statistical Analysis",
    html="",
    size=SurfaceSize(width=760, height=600, min_width=600, min_height=460),
    tabs=(
        ToolInfoTab("workflow", "Workflow", WORKFLOW_HTML),
        ToolInfoTab(
            "analysis_profiles",
            "Analysis profiles",
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
    "WORKFLOW_HTML",
]
