# Statistical Analysis

This page summarizes the statistical models used by the FPVS Toolbox and
how to interpret the outputs produced by the **Statistical Analysis**
module.

All analyses are run on preprocessed FPVS data after spectral analysis
and ROI aggregation.

---

## Data analyzed

- The primary dependent variable is the **summed baseline-corrected
  oddball amplitude (Summed BCA)**.
- Analyses are performed at the level of:
  - subject × condition × ROI.

Unless otherwise noted, all sections below refer to Summed BCA.

---

## Single-group analyses

Single-group mode analyzes one experimental group at a time.

### Repeated-measures ANOVA (RM-ANOVA)

- Within-subject factors:
  - **Condition**
  - **ROI**
- Implementation:
  - When available, the toolbox uses **Pingouin’s** `rm_anova`, reporting:
    - uncorrected p-values;
    - Greenhouse–Geisser (GG) and Huynh–Feldt (HF) corrected p-values.
  - Otherwise, it falls back to **statsmodels** `AnovaRM`
    (uncorrected p-values only).
- Effects of interest typically include:
  - main effect of condition;
  - main effect of ROI;
  - condition × ROI interaction.

### Post-hoc tests

- Pairwise **paired t-tests** between conditions.
- Tests are run **separately within each ROI**.
- Multiple-comparison control:
  - p-values are corrected using the **Benjamini–Hochberg false discovery
    rate (FDR)** procedure.
  - Exports include:
    - raw p-values;
    - FDR-adjusted p-values (`p_fdr_bh`);
    - effect sizes (e.g., Cohen’s d).

### Linear mixed-effects model (single group)

- A **linear mixed-effects model** is fit to Summed BCA with:
  - fixed effects: **condition**, **ROI**, and **condition × ROI**
    interaction;
  - random effects: **random intercept for each subject**.
- No additional multiple-comparison correction is applied to individual
  coefficients in this model; interpretation focuses on the pattern and
  significance of fixed-effect terms.

---

## Multi-group analyses

Multi-group mode (often referred to as “Lela mode”) compares two or more
groups (e.g., different hormonal status, clinical vs control).

### Between-group ANOVA (mixed ANOVA)

- Factors:
  - **Group** (between-subjects)
  - **Condition** (within-subjects)
- Dependent variable:
  - Summed BCA, typically **collapsed across ROI** for this test.
- Implementation:
  - When available, the toolbox uses **Pingouin’s** `mixed_anova`.
- Key effects:
  - main effect of group;
  - main effect of condition;
  - group × condition interaction.

### Between-group mixed model

- A **linear mixed-effects model** is fit to Summed BCA with:
  - fixed effects: **group**, **condition**, **ROI**, and their
    interactions;
  - random effects: **random intercept per subject**.
- This model allows testing whether the pattern of responses across
  conditions and ROIs differs by group while accounting for repeated
  measures within subjects.

### Group contrasts

- Pairwise **group comparisons** are computed separately for each
  condition × ROI combination.
- Implementation:
  - **Welch’s t-tests** (unequal variances) between groups.
- Multiple-comparison control:
  - p-values are corrected with **Benjamini–Hochberg FDR**.
  - Exports include:
    - raw p-values;
    - FDR-adjusted p-values;
    - effect sizes (e.g., Cohen’s d).

---

## Output files and interpretation

- All model results are written to Excel in the project’s  
  **`3 - Statistical Analysis Results`** folder.
- Typical exports include:
  - ANOVA tables (F, df, p, corrected p when applicable);
  - mixed-model summaries (fixed-effect estimates, standard errors,
    t-values, p-values);
  - post-hoc and group-contrast tables with raw and FDR-adjusted p-values
    and effect sizes.

Consult these Excel tables when reporting results in manuscripts or
presentations.

---

## General notes

- Unless otherwise noted, the **default alpha level is 0.05**.
- FDR correction reduces the chance of false positives when running many
  post-hoc tests but does not guarantee that all significant findings
  will replicate.
- Users remain responsible for:
  - checking model assumptions (normality, sphericity, etc.);
  - choosing effect sizes and contrasts that match their hypotheses;
  - transparently reporting all relevant results in line with field
    standards.
