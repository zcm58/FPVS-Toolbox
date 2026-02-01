# RM-ANOVA details (Summed BCA)

## Plain-language overview

Repeated-measures ANOVA (RM-ANOVA) is a standard way to test whether an
outcome changes across **multiple conditions** and/or **multiple ROIs**
when the **same participants** contribute data in every cell.

In FPVS terms, RM-ANOVA asks questions like:

- Do Summed BCA values differ across **conditions** (on average)?
- Do Summed BCA values differ across **ROIs** (on average)?
- Does the size of the condition effect **depend on ROI**
  (Condition × ROI interaction)?

RM-ANOVA is useful when your dataset is **complete and balanced**:
every participant must have a Summed BCA value for every required
condition × ROI combination. If that’s true, RM-ANOVA provides a clean,
familiar summary test of within-subject effects.

Important practical notes:

- RM-ANOVA tests **differences among factor levels** (condition/ROI).
  It does **not** directly test whether Summed BCA is different from zero.
- RM-ANOVA relies on assumptions about the covariance structure of
  repeated measures (often discussed as “sphericity”). When correction
  options are available, the toolbox reports corrected p-values to
  reduce false positives if those assumptions are violated.

---

## Manuscript-ready description

ROI-averaged Summed BCA values were analyzed using repeated-measures
ANOVA to evaluate within-subject effects of Condition, ROI, and their
interaction (Condition × ROI). RM-ANOVA was implemented using
Pingouin. Results were normalized into a
consistent reporting table containing the F statistic, numerator and
denominator degrees of freedom, and p-values for each effect. When
available from the underlying library, Greenhouse–Geisser and
Huynh–Feldt corrected p-values were additionally reported to address
potential violations of repeated-measures assumptions. Effect sizes were
reported as partial eta squared; when not provided directly by the
library, partial eta squared was computed from the F statistic and its
associated degrees of freedom. Because RM-ANOVA requires a balanced
within-subject table, analyses were only performed when each participant
contributed observations for all required condition × ROI combinations;
otherwise, the analysis halted and reported the missing cells.

---

## Not found in code (documentation transparency)

The following detail was not found in the current workflow:

- A user-facing option to manually select which sphericity correction
  method to report (corrected columns are reported only when provided by
  the library).
