# Post-hoc tests (interaction breakdown)

Post-hoc tests are run **after** an interaction is found in RM-ANOVA.
They explain **which condition pairs** differ **within each ROI**.

---

## What is tested

- **Within each ROI**, the tool runs **paired t-tests** for every pair of
  conditions.
- The analysis is **within-subject**, so each test uses subject-wise
  differences between the two conditions.

---

## Multiple-comparison correction

- **Correction method:** Benjamini–Hochberg FDR (`fdr_bh`).
- **Correction family:** applied **within each ROI** (all condition-pair
  tests for that ROI are corrected together).

---

## Effect sizes and outputs

Each pairwise result includes:

- **t statistic** and **p-value** (raw and FDR-adjusted).
- **Cohen’s dz** (paired-samples effect size), computed as mean difference
  divided by the standard deviation of paired differences.
- **Mean difference** (Condition A − Condition B) and 95% CI.
- **Shapiro p-value** for paired differences (informational only).

Interpretation tips:

- **Direction:** a positive mean difference means Condition A > Condition
  B for Summed BCA.
- **Effect size (dz):** larger absolute values indicate stronger
  condition differences within the ROI.

---

## Not found in code (documentation transparency)

The following details were **not found in code** while preparing this
page:

- A user-facing setting to change the post-hoc correction method from
  Benjamini–Hochberg FDR to another option. (Searched in
  `src/Tools/Stats/Legacy/posthoc_tests.py` and
  `src/Tools/Stats/PySide6/stats_workers.py`.)
