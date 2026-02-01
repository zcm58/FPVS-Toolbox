# Post-hoc tests (interaction breakdown)

## Plain-language overview

Sometimes the main statistics tell you that an effect exists, but not
**where** it comes from.

If the repeated-measures ANOVA finds a **Condition × ROI interaction**,
that means the size (or even the direction) of condition differences
depends on which ROI you’re looking at.

This post-hoc module answers the practical follow-up question:

- “Within a given ROI, **which specific condition pairs** are different?”

It does this in a way that matches the repeated-measures structure of
FPVS data (the same participants contribute all conditions).

Why this is useful in FPVS-EEG research:

- It turns an interaction result into an interpretable set of
  ROI-specific comparisons you can report in Results.
- It keeps the comparisons **within-subject**, which is usually the
  appropriate design for FPVS condition contrasts.
- It produces a standardized export so post-hoc reporting is consistent
  across projects.

---

## Manuscript-ready description

Following detection of a significant Condition × ROI interaction in the
repeated-measures ANOVA, ROI-stratified post-hoc testing was performed to
identify which condition pairs differed within each ROI. For each ROI,
all pairwise comparisons between conditions were evaluated using
**paired-samples t-tests**, computed on subject-wise differences so that
each participant served as their own control. Multiple comparisons were
controlled using the **Benjamini–Hochberg false discovery rate (FDR)**
procedure (`fdr_bh`), applied **separately within each ROI** such that
the family of tests consisted of all condition-pair comparisons for that
ROI.

For each condition pair, results included the t statistic and associated
p-value (both raw and FDR-adjusted), the mean paired difference
(Condition A − Condition B) with a 95% confidence interval, and the
paired-samples effect size **Cohen’s dz**, computed as the mean of the
paired differences divided by the standard deviation of the paired
differences. As an informational diagnostic, a Shapiro–Wilk normality
test was applied to the paired differences; this value was reported but
did not alter the inferential procedure. Positive mean differences
indicate larger Summed BCA values in Condition A than Condition B within
the ROI, and larger absolute dz values indicate stronger condition
separation.

