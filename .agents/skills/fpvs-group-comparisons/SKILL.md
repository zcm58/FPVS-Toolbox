---
name: fpvs-group-comparisons
description: Compare independent FPVS participant groups on amplitude or on condition, ROI, or visit differences. Use for Welch tests, group regression, and group-by-within-participant contrasts.
---

# FPVS group comparisons

Use [fpvs-analysis](../fpvs-analysis/SKILL.md) to establish the outcome, input
cohort, and coverage. State which groups are compared, the subtraction order,
and whether the target is a difference at one cell, a marginal difference, or
a difference in a within-participant contrast.

| Design and question | Analysis |
| --- | --- |
| One prespecified value per participant, two independent groups | Use a two-sided Welch test and CI for the mean difference when no adjustment is needed. With a prespecified covariate set, use regression and report the adjusted contrast and its target covariate values or averaging population. Check overlap and variance. |
| Each participant contributes Condition or ROI observations | Use a hierarchical fixed-effects model such as `BCA ~ Group * Condition * ROI` only if the scientific hypotheses and cell coverage support it. Account for participant dependence. For a specified cell, estimate Group A minus Group B from the fitted means. For a difference in selectivity, directly contrast the condition or ROI differences across groups. |
| Two visits and a prespecified outcome | A complete-pair analysis forms one Visit 2 minus Visit 1 change per person and compares the changes with Welch inference. Use a planned `Group * Visit` mixed model when repeated observations or partial coverage call for it. In an intervention study with a randomized baseline/follow-up design, consider a prespecified baseline-adjusted follow-up estimand if that matches the question. |

Use the [mixed-model and contrast guide](../fpvs-repeated-measures/references/mixed-models.md)
for model formulas, dependence structure, diagnostics, and fitted contrasts.

- Choose covariates from the design or a documented rationale before seeing
  their effects on the group p-value. Avoid adjustment for downstream
  consequences of group or intervention if estimating a total effect. If
  Group is aligned with hardware, site, or protocol with no overlap,
  adjustment cannot separate their effects. Within-person differencing can
  cancel stable additive device offsets. A Group × Visit contrast still
  cannot distinguish group change from device-by-visit effects or unequal
  scales. If the response is comparable, label such results as acquisition
  cohort differences. If comparability cannot be established, report within
  acquisition strata. Interpret observational group differences as
  associations unless the design supports a causal claim.
- A group difference in a change or ROI contrast needs the corresponding
  interaction or fitted difference of differences. A significant simple
  comparison in one group and an inconclusive one in the other do not
  establish that the effects differ.
- Keep a prespecified direct contrast distinct from a follow-up selected after
  inspecting an omnibus result. Specify the whole family, including all
  planned cells and comparisons, and document any non-estimable members.
  Holm is a reasonable default for one family of planned tests. Tukey is
  useful for all pairwise comparisons in a defined factor. Follow the
  study plan when it specifies a different method.
- Report observed group and cell Ns, missingness by group, raw or adjusted
  means with their weighting, the mean difference in µV for raw BCA, and its
  interval. If giving Hedges' g or a model-standardized contrast, define its
  denominator. Interpret precision and the range of plausible effects.
