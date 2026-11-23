---
name: fpvs-repeated-measures
description: Analyze FPVS visits, conditions, and ROIs measured within participants. Use for paired contrasts, linear mixed-effects models, ROI associations, or test–retest reliability.
---

# FPVS repeated measures

Use [fpvs-analysis](../fpvs-analysis/SKILL.md) to audit identity, response measures
and visit coverage. Decide whether the requested outcome is a mean difference,
a difference in change, an association, or agreement across visits.

| Design and question | Analysis |
| --- | --- |
| Two matched visits, conditions, or ROIs for one outcome | Form one signed difference per complete participant pair. Use a paired t-test and CI on the differences for a mean contrast. Consider a participant-pair bootstrap for a sensitivity when supported by sample size. |
| Several visits, conditions or ROIs, with or without groups | Use a participant-aware LMM with the targeted interactions. Use a signed paired ROI difference for amplitude asymmetry, and Visit × ROI for change in that asymmetry. Use a prespecified normalized response if the question is about relative scalp distribution. Model visit as categorical unless the question and timing support a specified trajectory. |
| Do people with a larger response in A also have a larger response in B? | For one matched ROI pair per person, inspect paired values and estimate a between-person association with uncertainty. With repeat pairs per participant, separate between-person average association from within-person covariation using participant means and within-person-centered predictors, or a suitable repeated-measures correlation. Verify matching conditions and visits and account for shared visit or condition trends when they could explain the association. |
| Will the same measurement agree on another visit? | For a test–retest question, specify ICC model, absolute agreement vs consistency, and single vs averaged recordings, with a CI. Inspect paired scatter, systematic change, and limits of agreement when appropriate. A correlation or a paired mean test measures a different property. |

- Read the [mixed-model and contrast guide](references/mixed-models.md) for
  fitting, diagnostics, and examples. Repeated-measures ANOVA is a reasonable
  option for a suitable complete design and a matching estimand. Check
  assumptions such as sphericity for within-subject effects with more than
  two levels and report Greenhouse–Geisser correction as applicable.
- Preserve visit IDs and planned order. If condition or phase always occurs
  at the same visit, report a session/phase-at-visit difference. Time,
  repetition, habituation, and practice cannot be separated from phase by
  adding a collinear variable. Likewise, a same-person pre/post change on its
  own may not identify an intervention effect.
- Report complete pairs for each paired endpoint and observations per
  participant and per design cell for LMMs. Treat pairwise complete and
  available-observation estimates as different targets when missingness
  changes their populations. Keep ROI association and amplitude contrasts
  separate, especially for overlapping ROIs or normalization with a shared
  denominator, which can induce association.
