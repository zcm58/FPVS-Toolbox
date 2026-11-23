---
name: fpvs-analysis
description: Prepare, audit, and report an agent-run FPVS EEG analysis from Toolbox exports or supplied data. Use for response definition, cohort and visit validation, method selection, and reproducibility.
---

# FPVS analysis

Use this workflow for an authorized study analysis outside the Toolbox desktop. The
[Stats contract](../../../docs/agent/architecture/statistics-tools.md) describes
the built-in screening and repeated-session modes when replicating their results.

1. **Define the scientific question.** Specify the participant population,
   response measure, group or within-participant factors, primary contrasts and
   their directions, and the tests that form each multiplicity family. Say which
   choices were fixed independently and which were informed by the current data.
   An exploratory request can proceed on stated assumptions. Resolve ambiguities
   that change the estimand, such as unidentified visits or unknown group labels.
2. **Audit and freeze inputs.** Use the reviewed Toolbox export and verify the
   observation grain, coverage, eligibility, and response definition using
   [Toolbox analysis inputs](references/toolbox-inputs.md). For an external study
   table, establish the equivalent provenance from its data dictionary and
   acquisition or analysis records. Keep the original input, QC decisions and
   processing settings intact.
3. **Match the method to the design.** Use
   [fpvs-group-comparisons](../fpvs-group-comparisons/SKILL.md) for independent
   groups or group differences in within-participant contrasts. Use
   [fpvs-repeated-measures](../fpvs-repeated-measures/SKILL.md) for visits,
   conditions, ROI differences, ROI associations, or reliability measured in
   the same participants. Use both for mixed designs and fit one model for
   the prespecified shared contrasts when the model is identifiable.
4. **Report a reproducible analysis.** Save the analysis script or notebook
   used to generate the requested outputs, with software versions and seeds
   where applicable. Record source artifact and cohort/selection fingerprints
   when available, row and participant counts by cell, missing and excluded
   observations by reason, estimands, contrasts, and method or model fit
   diagnostics. Report signed estimates in interpretable units with 95% CIs
   (or the prespecified confidence level), raw and adjusted p-values with
   named families where applicable, and the denominator behind each result.
   Indicate whether intervals are marginal or simultaneous. Write derived
   outputs to the requested analysis destination.

The [published-methods review](references/published-methods.md) gives examples
of response definitions, paired and group inference, mixed effects, reliability,
and whole-scalp exploratory analyses. Consult it when selecting or justifying a
method. The Toolbox [figure standard](../../../docs/agent/quality/figure-generation.md)
applies when the requested deliverable includes publication figures.
