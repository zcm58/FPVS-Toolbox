# Statistical Analysis

Use this page when you want a high-level map of the Statistics tool before choosing a specific test.

This page summarizes the statistical methods used by the FPVS Toolbox
**Statistical Analysis** module for end users. It focuses on the primary
output measure (**Summed BCA**) and how to interpret results in the
currently supported single-group workflow.

---

## How the methods work together (high-level)

1. **Summed BCA DV is defined** from the ROI-aggregated spectral outputs.
2. **Harmonics are selected** using the default fixed/predefined list or
   the optional group-level significant-harmonics policy.
3. A **subject x condition x ROI table** of Summed BCA values is built.
4. **RM-ANOVA** and/or a **linear mixed-effects model** summarize
   condition, ROI, and interaction effects.
5. **Post-hoc paired t-tests** (within each ROI) follow a significant
   interaction to explain which condition pairs differ.

Interpretation guide (single-group):

- **Overall response present:** Summed BCA values are consistently above
  zero and/or the mixed-model intercept is positive. Note that RM-ANOVA
  tests differences among conditions and ROIs; it does not directly test
  DV vs 0 (Not found in code: an explicit one-sample test on Summed BCA
  within the main RM-ANOVA pipeline). See "Not found in code" notes below.
- **Condition main effect:** responses differ across experimental
  conditions (averaged across ROIs).
- **ROI main effect:** responses differ across ROIs (averaged across
  conditions).
- **Condition x ROI interaction:** the condition effect depends on which
  ROI is considered.

Cautions:

- **Multiple comparisons:** post-hoc tests are corrected for false
  discovery rate; still interpret effect sizes and confidence intervals.
- **Harmonic policy matters:** the default fixed/predefined list and the
  optional group-level significant-harmonics policy both apply one common
  harmonic list across ROIs, so ROI differences are not driven by different
  harmonic lists.
- **Assumptions:** check normality and sphericity (RM-ANOVA) and residual
  diagnostics (mixed model) as part of reporting.

---

## Summed BCA DV and harmonic selection

The DV used for statistical analysis is the **Summed baseline-corrected
oddball amplitude (Summed BCA)**. It is computed per
**subject x condition x ROI** by summing BCA across selected oddball
harmonics and then averaging across ROI channels.

- **Source data:** The DV is computed from the **"BCA (uV)"** sheet in the
  spectral/ROI output file. The optional group-level policy computes
  selection z-scores from the grand-averaged **"FullFFT Amplitude (uV)"**
  spectrum.
- **ROI aggregation:** The ROI mean is computed after summing selected
  harmonics for each channel within the ROI.

For detailed harmonic selection rules, see:
**[Harmonic selection](../statistics/rossion-harmonic-selection.md)**.

---

## Single-group analyses

### Repeated-measures ANOVA (RM-ANOVA)

- **Within-subject factors:** Condition and ROI (plus their interaction).
- **Implementation:**
  - Primary path: **Pingouin** `rm_anova` (detailed table when available,
    including Greenhouse-Geisser and Huynh-Feldt corrections).
  - Fallback: **statsmodels** `AnovaRM` if Pingouin is not available.
- **Outputs:** F statistic, numerator/denominator degrees of freedom,
  p-values, and **partial eta-squared** effect sizes.

Interpretation:

- **F statistic:** ratio of variance explained by the effect to residual
  variance (larger F -> stronger evidence for an effect).
- **df1/df2:** numerator/denominator degrees of freedom for the effect.
- **GG/HF corrections:** appear when Pingouin can compute sphericity
  corrections.

For more details, see: **[RM-ANOVA details](../statistics/rm-anova.md)**.

### Post-hoc tests (interaction breakdown)

- **Paired t-tests** between **all condition pairs**, run **separately
  within each ROI**.
- **Correction:** Benjamini-Hochberg FDR **within each ROI** (i.e., each
  ROI's condition-pair family is corrected independently).
- **Effect size:** **Cohen's dz** for paired samples, based on the
  subject-wise condition differences.

For more details, see: **[Post-hoc tests](../statistics/posthoc-tests.md)**.

### Linear mixed-effects model (single group)

- **Library:** statsmodels `MixedLM`.
- **Fixed effects:** condition, ROI, and condition x ROI interaction.
- **Random effects:** **random intercept for subject**.
- **Coding:** condition and ROI are **sum-coded** by default when present
  (no explicit coding is set for other factors).

For more details, see: **[Mixed model details](../statistics/mixed-model.md)**.

---

## Outliers, QC flags, and manual exclusions

The Stats tool can generate **QC and DV flags** and separate them from
**manual exclusions**. See
**[Outliers and QC](../statistics/outliers-and-qc.md)** for details.

---

## Output files

- Results are written to the project's **"3 - Statistical Analysis
  Results"** folder.
- Common exports include:
  - RM-ANOVA tables (single-group workflow).
  - Mixed-model fixed-effects tables.
  - Post-hoc tables with raw and FDR-adjusted p-values plus effect sizes.
  - Summed BCA DV definition export.
  - Flagged and excluded participant reports (if QC/outlier checks are
    enabled).

---

## Not found in code (documentation transparency)

The following details were **not found in code** while preparing this
page:

- An explicit one-sample test against zero as part of the RM-ANOVA
  pipeline. (Searched in `src/Tools/Stats/workers/stats_workers.py`,
  `src/Tools/Stats/analysis/stats_analysis.py`, and
  `src/Tools/Stats/analysis/repeated_m_anova.py`.)
