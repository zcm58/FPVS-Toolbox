# Statistical Analysis

Statistical Analysis turns processed FPVS workbooks into a common Summed BCA
dependent variable and runs a native analysis appropriate to the project's
saved design. It supports both normal single-group projects and true
multi-group projects.

## The Three Questions

The results deliberately keep three questions separate:

1. **Response detection:** is Summed BCA different from zero?
2. **Within-subject effects:** does Summed BCA differ by Condition, ROI, or
   their interaction?
3. **Between-group effects:** do canonical project groups differ overall or in
   particular Condition x ROI cells?

A clear response in the pooled sample does not mean that conditions or groups
differ. Likewise, a nonsignificant test does not prove that a response or group
difference is absent.

## Before You Run

Use this tool after preprocessing and post-processing have created one Excel
workbook per participant and condition under the project's
`1 - Excel Data Files` folder. For the full factorial analyses, select at least
two conditions and two ROIs.

The tool reads the processed workbooks, project settings, ROI definitions, and
canonical participant/group assignments in `project.json`. Before a run, you
can:

- choose the requested conditions;
- review the participants and group sizes found in the project;
- apply manual participant exclusions;
- review quality-control and non-finite/outlier flags; and
- check which conditions have complete shared coverage.

The project manifest determines the analysis mode:

- a normal single-group project runs the single-group pipeline;
- a project with two or more configured groups runs the multi-group pipeline.

The tool does not offer an "ignore groups" shortcut in a multi-group project.
If pooling everyone is scientifically justified, create or use a separately
defined single-group project so that the design and provenance remain clear.

## Analysis Scope and Missing Conditions

The eligible participant cohort is always frozen after QC and manual
exclusions. You can then choose one of two explicit analysis scopes:

- **Complete core** retains a condition only when every frozen participant
  contributes exactly one finite value in every selected ROI. An incomplete
  condition is excluded for everyone; participants are not silently dropped to
  rescue it.
- **Available-case LMM** retains finite observations from a condition when
  every required fixed-effect Condition x ROI cell (and Group cell in
  multi-group mode) has data. A participant may contribute some retained
  conditions without contributing all of them.

Missing or non-finite Summed BCA cells do not automatically remove the whole
participant. Complete-core mode excludes the affected condition for everyone;
available-case mode uses the participant's other finite observations when the
condition remains structurally estimable.

Available-case mode does not fill, average over, or impute a missing response.
The report distinguishes the frozen cohort from participants who contributed at
least one usable row, lists fully complete, partially observed, and structurally
excluded conditions, and reports the observed N for each cell/result. A
condition is excluded when a required fixed-effect cell has no finite
observation, because the requested factorial model is then not estimable as
specified.

Available-case likelihood inference relies on an **ignorable missingness** or
**missing at random (MAR)** assumption after conditioning on variables in the
model. If an exclusion still depends on the unobserved Summed BCA after those
variables are considered—**missing not at random (MNAR)**—the estimates and
p-values may be biased. Missingness reasons and complete-core results should be
reviewed as sensitivity evidence rather than treating MAR as guaranteed.

For a multi-group model, every canonical group must have at least two retained
participants, and Group, Condition, and ROI must each have at least two levels.
Missing or unknown group assignments block the analysis instead of being
guessed from folder names.

## Summed BCA and Harmonic Selection

The default policy determines one common list of oddball harmonics from the
grand-averaged `FullFFT Amplitude (uV)` spectra. Detection uses the union of the
electrodes in the project's predefined ROIs and a strict `z > 1.64` threshold.
Base-rate overlaps are excluded.

For each candidate harmonic, the noise window spans +/-10 FFT bins around the
target. The target bin and its immediately adjacent bins are excluded, then the
single lowest and single highest finite noise values are removed before the
mean and population standard deviation are calculated.

Summed BCA includes every eligible non-base oddball harmonic through the
highest detected significant harmonic, even if an intervening harmonic was not
itself significant. A one-pass gap guard prevents a lone high-frequency peak
from filling a very long empty interval: if more than 10 eligible non-base
harmonics lie strictly between the two highest detected peaks, the highest peak
and all harmonics above the next-highest peak are excluded from the sum.
Base-rate overlaps do not count toward the gap, and exactly 10 intervening
eligible harmonics remains allowed. The same included list is applied to every
participant, condition, and ROI.

The processing workflow records the selection in
`Quality Check/Harmonic_Selection_Summary.xlsx` and in project metadata. A
missing or stale selection must be recalculated before the analysis proceeds;
the Stats tool does not silently invent another list. Use
**Settings > Preprocessing > Harmonic Selection > Recalculate Harmonics**.
The Statistical Analysis page provides a link to that Settings workflow; it
does not delete or recalculate the processing-time selection itself. Settings
keeps the prior saved entry while the fresh calculation runs, so a failed or
cancelled retry cannot erase the last completed selection.

### Why provenance changes interpretation

If the significant harmonics were selected from the same participants whose
response is then tested against zero, the response p-values are labelled
**exploratory post-selection**. This is the normal
**Published-style exploratory** profile. It does not invalidate condition or
group contrasts automatically, but it does prevent the response-versus-zero
test from being presented as independent confirmatory evidence.

Use **Confirmatory** only when the cohort, hypotheses, test direction,
comparison families, and fixed harmonic list were specified independently of
the analyzed responses. Selecting the profile alone cannot make an adaptive
list independent.

## Single-Group Analysis

In complete-core scope, the single-group pipeline runs:

- a Condition x ROI repeated-measures ANOVA;
- a sum-coded Condition x ROI linear mixed-effects model with participant as
  the random-effect grouping unit;
- declared paired follow-up comparisons; and
- one-sample t-tests of Summed BCA against zero in every retained
  Condition x ROI cell.

The response tests are two-sided by default. Choose "greater than zero" only
when that directional hypothesis was justified before examining the data. The
default `response_core_cells` family uses one Holm correction across all
retained Condition x ROI cells.

The ANOVA reports the Greenhouse-Geisser p-value when sphericity requires it.
If a required correction cannot be calculated, the raw result stays in the
detailed workbook but is not used as the primary conclusion.

By default, the canonical ANOVA effect p-values are also adjusted together in
the `omnibus_effects_strict` family using the selected correction (Holm by
default). This multiplicity correction is separate from the
Greenhouse-Geisser sphericity correction; either, both, or neither may apply to
a given effect.

When strict interaction gating is enabled, omnibus-triggered paired follow-ups
run only when that canonical RM-ANOVA Condition x ROI interaction is
significant after any required Greenhouse-Geisser and strict-family handling.
Planned or manually requested exploratory follow-ups keep their declared
provenance and correction family; they are not presented as if the omnibus
interaction triggered them.

If strict omnibus-family control is disabled, the ANOVA effect rows and
manually requested follow-ups remain exploratory/detailed and are not
headlined as an unadjusted primary family.

The mixed model reports final REML coefficient estimates. Its omnibus
Condition/ROI comparisons refit explicit nested models under maximum
likelihood and use asymptotic likelihood-ratio tests. These tests are useful
cross-checks, but they are not Kenward-Roger or Satterthwaite F tests.

In available-case scope, the factorial primary analysis is the Condition x ROI
mixed model fitted to all usable retained observations. Its explicit ML
likelihood-ratio rows may support the primary headline after the selected
omnibus-family correction. Raw coefficient-level Wald p-values remain
detailed-only. Repeated-measures ANOVA and paired post-hoc tests are
intentionally omitted because those procedures require complete
within-participant cells; they are not made "available case" by silently
discarding incomplete participants.

## Multi-Group Analysis

The primary multi-group pipeline runs:

- a sum-coded `Group x Condition x ROI` linear mixed-effects model;
- explicit omnibus likelihood-ratio comparisons for the joint group-related
  block and its Condition/ROI-dependent components;
- two-sided Welch group comparisons in every retained Condition x ROI cell;
  and
- requested robust, resampling, and leave-one-participant-out sensitivity
  checks.

The model includes all retained canonical groups and uses a participant random
intercept by default. Final coefficient estimates use REML. The omnibus tests
compare hierarchy-preserving full and reduced models fitted with maximum
likelihood and use an asymptotic chi-square reference. In available-case scope,
every nested comparison is fitted to the same finite observed row set; no
missing response is imputed.

The broad result called **Any group-related effect** jointly tests every model
term containing Group. It is not a pure average Group main effect. The
Group x Condition x ROI, Group x Condition-related, and Group x ROI-related
rows help decompose that broad question.

With the default strict omnibus-family option enabled, the four likelihood-
ratio rows are adjusted together in `omnibus_effects_strict` using the selected
correction (Holm by default), and the adjusted decisions control primary
omnibus interpretation. The direct group-cell tests retain their own separately
adjusted family. If strict control is disabled,
**Any group-related effect** is the sole primary omnibus test; the three
decomposition rows remain exploratory details, not extra unadjusted primary
claims.

The direct cell comparisons answer the practical question, "does the selected
group pair differ in any Condition x ROI pair?" They use Welch's independent
t-test, so equal group variances are not assumed. Each row reports the signed
mean difference (`group A - group B`), a 95% confidence interval, and
small-sample-corrected Hedges g. In available-case scope, group Ns may vary
across cells and are reported on each row. By default, one global Holm
correction is applied across every estimable retained cell in the
`group_core_cells` family.

If the project contains more than two groups, choose the exact pair for the
cell comparisons. The full mixed model still includes all groups. The pair
selector changes only the direct two-group cell contrasts.

## Assumptions, Normality, and Sensitivity Checks

The report records finite-value checks, sample sizes, variance, Shapiro-Wilk
normality diagnostics, repeated-measures sphericity, mixed-model convergence
and singularity, and extreme residuals where available.

For available-case runs, also inspect the participant-coverage, model-cell
coverage, and missing-observation tables. The mixed model uses partial repeated
measures under MAR; it does not make informative exclusions harmless.

Normality diagnostics are **report-only**. A Shapiro-Wilk result does not
automatically replace the planned test with a different test. This avoids
choosing a method after seeing which result is more favorable.

Sensitivity analyses can include:

- 20% trimmed-mean tests and rank-based checks;
- participant-level sign-flip or group-label max-|t| resampling, which adjusts
  a complete family jointly; and
- leave-one-participant-out stability.

These are supporting checks, not extra opportunities to declare significance.
Agreement can increase confidence in a primary finding. A sensitivity-only
finding remains labelled as such.

## Multiple-Comparison Choices

- **Holm** is the default for a family-wise "at least one result" claim. It
  controls the family-wise error rate across the declared family.
- **Benjamini-Hochberg FDR** is an explicitly exploratory discovery option.
- **Max-|t|** appears separately as a participant-level resampling
  sensitivity, not as a relabelled Holm result.

Under the default strict setting, `omnibus_effects_strict` adjusts the
canonical ANOVA effects in single-group mode or the four group-related
likelihood-ratio rows in multi-group mode. It is separate from the
`response_core_cells`, `group_core_cells`, and paired-follow-up families.

Published FPVS studies have often used Bonferroni or Tukey adjustments. Holm
also controls family-wise error, but it is not numerically identical to either
method and may define a different comparison family. Report the exact method
shown in the exported workbook.

## Reading the Results

Start with **At a glance**:

- only questions relevant to the project mode are shown;
- primary conclusions are translated into plain language without p-values or
  test-inventory terminology;
- nonsignificant test families are described as finding no clear difference,
  without displaying a technical significant/total count;
- positive primary findings may name up to two relevant tests; and
- significant secondary checks are collapsed into one cautionary sentence
  rather than listed individually.

At a glance also gives one short data-coverage line and the detailed workbook
filename. It intentionally omits repeated nonsignificant cells, raw and
adjusted p-values, estimates, confidence intervals, effect sizes, omnibus
decompositions, and the full export path. **Run log** contains processing,
cancellation, and export messages. Use the exported results workbook for
sample coverage, formulas, assumptions, correction families, harmonic
provenance, limitations, and detailed numeric results.

For available-case runs, verify the frozen N, contributing N, per-cell Ns,
partially observed conditions, no-imputation statement, and MAR/MNAR caveat
before interpreting a p-value.

## Adolescent Samples

FPVS mixed-model work has been published in adolescents aged 12--16, so a
13--15-year-old sample is age-relevant to that literature. This does not remove
the limitations of a small observational sample. In particular, the native
group model does not currently adjust for age, gender, medication, depression,
recruitment source, or other possible confounders.

Describe group results as **associations in this analyzed sample**, not as
evidence that anxiety caused the neural difference or that the result is
diagnostic. If covariates are part of the scientific question, specify them in
advance and use the Stats-Ready export with validated external software.

## Outputs

Results are written under `3 - Statistical Analysis Results` in the active
project. The native report workbook is named
`Native Single-Group Inference Results.xlsx` or
`Native Multi-Group Inference Results.xlsx` and includes:

- At a Glance and Detailed Methods;
- the complete test inventory and correction families;
- estimates, confidence intervals, effect sizes, and p-value provenance;
- design coverage, exclusions, group assignments, and analysis settings;
- diagnostics, sensitivities, warnings, and limitations; and
- the underlying source result tables.

If narrative assembly fails after the statistical steps finish, the tool
attempts to preserve the numeric frames in a fallback workbook and labels the
report failure explicitly.

**Export Stats-Ready Workbook** remains available for JASP, R/RStudio, SAS, or
another package. It writes `Stats_Ready_Summed_BCA.xlsx` with long and wide
data, subject and group identifiers, and harmonic-selection evidence. Use it
for prespecified covariates, alternative random-effects structures,
Kenward-Roger/Satterthwaite inference, equivalence tests, or another model not
offered natively.

## Published-Method Validation

The core approach has direct FPVS precedent:

- [Vandenheever et al. (2025)](https://doi.org/10.1016/j.ijpsycho.2025.113212)
  analyzed summed BCA in an adult sample aged 18--28 using a separate ROI x
  Anxiety Group model for each emotional expression, a participant random
  intercept, and Bonferroni-adjusted planned contrasts.
- [Van der Donck et al. (2020)](https://doi.org/10.1111/jcpp.13201) used
  REML mixed models of expression, ROI, and group with a participant random
  intercept, Kenward-Roger degrees of freedom, Bonferroni post-hoc correction,
  and residual-assumption checks.
- [Vettori et al. (2020)](https://doi.org/10.3389/fpsyt.2020.00332) used a
  Group x Stimulus x ROI mixed model, a participant random intercept, and
  fitted-model post-hoc tests with Tukey correction.
- [Samaey et al. (2024)](https://doi.org/10.1186/s12916-024-03610-w) analyzed
  FPVS baseline-corrected amplitudes in 120 adolescents aged 12--16 using
  mixed models, participant random effects, age/gender covariates,
  Kenward-Roger degrees of freedom, and Bonferroni contrasts.
- [Feuerriegel et al. (2018)](https://doi.org/10.1016/j.biopsycho.2018.09.002)
  provides FPVS precedent for repeated-measures ANOVA on summed harmonics with
  Greenhouse-Geisser handling and Holm correction across prespecified F tests.
- [Keil et al. (2022)](https://doi.org/10.1111/psyp.14052) recommend a priori
  ROIs, multiplicity control across multiple ROIs, and maximum-statistic
  permutation methods for joint frequency-domain inference.

The Toolbox adapts these practices; it does not claim an exact reanalysis of
any paper. In particular, `statsmodels` ML likelihood-ratio tests plus REML
estimates are not the same as F tests using Kenward-Roger-adjusted denominator
degrees of freedom, Holm is not the same calculation as Bonferroni or Tukey,
and the robust/max-|t|/stability analyses are supplementary Toolbox
sensitivities rather than a universal FPVS standard. The unified Group x
Condition x ROI model also generalizes the four separate expression models used
in the anxiety paper rather than reproducing them.

See the [statistical methods reporting checklist](../reference/methods-reporting-checklist.md#statistical-analysis)
before writing a manuscript or preregistration.
