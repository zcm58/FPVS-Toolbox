# Standard FPVS Screening

Standard FPVS Screening turns processed FPVS workbooks into a common Summed
baseline-corrected amplitude (Summed BCA) outcome and runs a transparent first
round of statistical checks. It is designed to answer a small set of common
FPVS questions consistently. It is not the final project-specific statistical
model for every study.

Use a planned custom analysis when the scientific question requires covariates,
random slopes, longitudinal or nested structure, more than two groups,
equivalence testing, a different response scale, or another specialized
estimand.

## Questions Answered

The screen keeps four questions separate:

1. **Positive oddball response:** is mean Summed BCA greater than zero in a
   Condition x ROI cell?
2. **Condition/ROI pattern:** does the primary linear mixed model (LMM) support
   variation by Condition, ROI, or their interaction?
3. **Interaction explanation:** when the corrected Condition x ROI interaction
   is supported, which fitted-model comparisons help explain it?
4. **Two-group pattern:** in a project with exactly two canonical groups, do
   Group A and Group B differ in particular Condition x ROI cells, and is there
   a broader joint group-related pattern?

A positive response within a group is not evidence that two groups differ.
Likewise, a nonsignificant result does not prove absence or equivalence.

## Before You Run

Use this tool after preprocessing and post-processing have created one Excel
workbook per participant and condition under the project's
`1 - Excel Data Files` folder. For factorial screening, select at least two
conditions and two ROIs.

The tool reads processed workbooks, project settings, ROI definitions, and
canonical participant/group assignments from `project.json`. Before a run, you
can:

- choose conditions and ROIs;
- review participants, group sizes, and data coverage;
- apply manual participant exclusions;
- review quality-control and non-finite/outlier flags; and
- choose optional robustness or leave-one-out sensitivity checks.

Project metadata determines the mode:

- a single-group project runs single-group screening;
- a project with exactly two canonical groups runs two-group screening; and
- a project with three or more canonical groups is stopped with a message to
  use a planned custom model.

The screen does not offer an "ignore groups" shortcut. If pooling participants
is scientifically justified, create a separately defined single-group project
so the design and provenance remain explicit.

## Available Observations and Missing Conditions

The eligible cohort is frozen after QC and manual exclusions. The primary LMM
then uses every finite retained observation from that cohort. A participant who
is missing one condition can still contribute all other usable conditions.

Missing or non-finite Summed BCA values are not filled, averaged over, or
imputed. The report distinguishes:

- frozen participants;
- participants contributing at least one finite retained observation;
- fully complete and partially observed conditions;
- missing participant-condition-ROI cells;
- per-cell sample sizes; and
- conditions excluded because a required fixed-effect cell had no finite data.

A structurally empty fixed-effect cell blocks the requested factorial model;
the Toolbox does not invent that cell or silently change the scientific
question.

Likelihood-based use of available observations assumes missingness is
ignorable, commonly described as **missing at random (MAR)** after conditioning
on variables in the model. If exclusion still depends on an unobserved response
after accounting for modeled variables - **missing not at random (MNAR)** -
estimates and p-values may be biased. Review missingness reasons and coverage
tables rather than treating MAR as guaranteed.

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
missing or stale selection must be recalculated before screening proceeds; the
Stats tool does not silently invent another list. Use
**Settings > Preprocessing > Harmonic Selection > Recalculate Harmonics**.
The screening page links to that Settings workflow but does not delete or
recalculate the processing-time selection itself. Settings keeps the prior
saved entry while a fresh calculation runs, so a failed or cancelled retry
cannot erase the last completed selection.

### Why provenance changes response interpretation

When significant harmonics are selected from the same participants whose
response is tested against zero, the response p-values are labelled
**exploratory post-selection**. At a Glance still reports the response evidence
but identifies it as exploratory and says that the harmonics were selected from
this sample.

A response test can be described as independently selected only when the fixed
harmonic list was specified independently of the analyzed responses and that
provenance is documented. Changing a label cannot make an adaptive selection
independent.

Harmonic-selection provenance affects the response-versus-zero interpretation.
It does not automatically invalidate the Condition, ROI, or group contrasts,
which answer different questions.

## Locked Standard Methods

The screen fixes the main statistical choices so they cannot be changed after
seeing the data:

| Question | Standard method | Holm family |
| --- | --- | --- |
| Positive response, single group | One-sample t-test of mean Summed BCA greater than zero in each Condition x ROI cell | `response_core_cells` |
| Positive response, two groups | The same one-sided t-test within every Group x Condition x ROI cell | `group_response_cells` |
| Primary factorial pattern | Participant-random-intercept LMM with hierarchy-preserving likelihood-ratio block tests | `omnibus_effects_strict` |
| Single-group interaction explanation | Two-sided `LMM-derived model-estimated contrast` comparisons | `planned_contrasts` |
| Direct Group A - Group B cells | Two-sided `LMM-derived model-estimated contrast` in every estimable Condition x ROI cell | `group_core_cells` |
| Balanced ANOVA compatibility | Secondary ANOVA effects, only when exact balance requirements are met | `anova_compatibility_effects` |

The nominal alpha is 0.05. Holm family-wise correction is applied separately
within each named family. A result in one family does not change which tests
belong to another family.

Normality and other diagnostics do not automatically select or replace the
primary test.

## Single-Group Screening

The scientific formula is:

```text
Summed BCA ~ Condition * ROI + (1 | Participant)
```

Condition and ROI use sum coding. The accepted final model is fitted with REML
to estimate coefficients. The primary Condition, ROI, and Condition x ROI
questions use explicit hierarchy-preserving full-versus-reduced models refitted
with maximum likelihood and asymptotic chi-square likelihood-ratio tests. These
block tests must be reported using their exported labels; they are not
Kenward-Roger or Satterthwaite F tests and should not be relabelled as pure
Type-III effects.

The three primary LMM block p-values are corrected together with Holm in
`omnibus_effects_strict`.

Positive-response one-sample t-tests are prespecified as one-sided:

```text
H1: mean Summed BCA > 0
```

All estimable Condition x ROI response cells are corrected together with Holm
in `response_core_cells`. A negative response cannot satisfy this directional
hypothesis.

When the corrected primary Condition x ROI interaction is supported, the tool
uses two-sided `LMM-derived model-estimated contrast` comparisons to explain the
pattern:

- Condition differences within each ROI; and
- ROI differences within each Condition.

These fitted-model Wald contrasts report signed estimates, standard errors,
95% confidence intervals, asymptotic z statistics, and two-sided p-values. The
`planned_contrasts` family is Holm-corrected. Automatic interaction
explanations are not shown when the corrected primary interaction is
unsupported.

### Single-group ANOVA compatibility

Repeated-measures ANOVA is a secondary compatibility check, not the primary
analysis. It runs automatically only when every included participant has
exactly one finite value in every declared Condition x ROI cell. Missing,
duplicate, or non-finite cells skip ANOVA without failing the LMM screen.

When it runs, the ANOVA reports its canonical sphericity and
Greenhouse-Geisser handling. Its effects are Holm-corrected in
`anova_compatibility_effects`. Compatibility results never gate, replace, or
change the primary LMM conclusion.

## Two-Group Screening

Standard two-group screening requires exactly two canonical groups with valid
`project.json` assignments, at least two retained participants contributing
data in each group, and finite observations in every required fixed-effect
cell. Missing or unknown group assignments are not guessed from folders.

The scientific formula is:

```text
Summed BCA ~ Group * Condition * ROI + (1 | Participant)
```

Group, Condition, and ROI use sum coding. Final estimates use REML. The
hierarchy-preserving omnibus comparisons refit full and reduced models with
maximum likelihood on the same finite observed row set and use an asymptotic
chi-square reference.

Four group-related LMM rows are Holm-corrected together in
`omnibus_effects_strict`:

- **Any group-related effect**, a joint test of all fixed terms containing
  Group, not a pure average Group main effect;
- **Group x Condition x ROI interaction**, the three-way term;
- **Group x Condition-related block**, which jointly includes the
  Group x Condition and three-way terms; and
- **Group x ROI-related block**, which jointly includes the Group x ROI and
  three-way terms.

Positive responses are also tested with a one-sample t-test within every
Group x Condition x ROI cell using the one-sided greater-than-zero question.
Holm correction is applied once across the complete `group_response_cells`
family. Comparing whether one group is significant and another is not is not a
test of a group difference.

### Direct group-cell differences

The direct prespecified comparison is Group A minus Group B in every estimable
Condition x ROI cell. Each is a two-sided
`LMM-derived model-estimated contrast` from the same accepted LMM used for the
omnibus inference. Rows report the signed estimate, standard error, 95%
confidence interval, asymptotic Wald z statistic, two-sided p-value, and
observed coverage. Missing responses are not imputed.

All estimable cells are Holm-corrected together in `group_core_cells`. This
family always runs when its cells are estimable. It is **not gated** by the
joint group-related test. A localized cell difference and a nonsignificant
joint group pattern can therefore coexist; neither result proves equivalence,
causation, or diagnostic value.

### Two-group ANOVA compatibility

The secondary multi-group ANOVA check requires:

- exactly two groups;
- equal group sizes; and
- one finite, unique value for every participant x Condition x ROI cell.

It collapses each declared Condition x ROI combination into a within-participant
`response-cell` factor and tests a broad Group x response-cell mixed-ANOVA
compatibility question. It does **not** separately decompose
Group x Condition, Group x ROI, or Group x Condition x ROI. Failure to meet
these balance requirements skips the compatibility check without changing the
primary LMM screen.

## Diagnostics and Sensitivity Checks

The detailed workbook records finite-value and per-cell N checks, variance and
normality diagnostics, residual tails, LMM convergence and singularity, exact
coverage, and ANOVA sphericity when compatibility ANOVA runs.

Shapiro-Wilk and other normality checks are diagnostic only. They do not
automatically switch the primary analysis.

Optional supporting checks can include robust or rank-based summaries and
leave-one-participant-out stability. These remain labelled as sensitivity
evidence. A sensitivity-only finding is not promoted to a primary conclusion.

The standard available-observation route does not queue the current max-|t|
resampling procedure because that implementation requires a complete
participant-by-cell matrix. Treat any max-|t| result from a legacy or separate
custom complete-design analysis as additional sensitivity evidence, not part
of Standard FPVS Screening.

Mixed-model likelihood-ratio and Wald p-values use asymptotic reference
distributions. This deserves particular caution in small samples. Inspect
estimates, confidence intervals, model warnings, and stability rather than
reducing the analysis to significant/nonsignificant labels.

## Reading At a Glance

At a Glance answers the screening questions in this order:

1. positive oddball-response evidence;
2. the primary LMM Condition/ROI pattern;
3. `LMM-derived model-estimated contrast` explanations when the corrected
   interaction supports them; and
4. in two-group mode, direct Group A - Group B cell differences followed by
   the broader joint group-related pattern.

It names at most two supported rows and does not reproduce p-values or the test
inventory. Balanced-only compatibility ANOVA never enters the headline.

At a Glance also states the first-round/custom-model boundary. A nonsignificant
group result does not prove equivalence, and group results describe
associations in the analyzed sample, not causes or diagnoses.

Use the workbook for exact estimates, intervals, p-values, formulas,
correction-family membership, coverage, assumptions, diagnostics, and
limitations.

## Adolescent and Observational Samples

For a sample of 13--15-year-old students, report the exact age range,
recruitment population, group definitions, and exclusions. The standard model
does not adjust for age, gender, medication, depression, recruitment source, or
other potential confounders.

Describe group results as associations in this analyzed student sample. Do not
claim that anxiety caused a neural difference or that an FPVS response is
diagnostic. If covariates are part of the scientific question, specify them in
advance and use the Stats-Ready export with a validated custom model.

## Outputs

Results are written under `3 - Statistical Analysis Results` in the active
project. The current standard report is named:

- `Native Single-Group Available-Case LMM Results.xlsx`; or
- `Native Multi-Group Available-Case LMM Results.xlsx`.

It includes:

- At a Glance and Detailed Methods;
- the complete test inventory and correction families;
- LMM estimates, confidence intervals, Wald contrasts, and p-value provenance;
- design coverage, exclusions, group assignments, and analysis settings;
- ANOVA compatibility status, balance audit, and numeric results when eligible;
- diagnostics, sensitivities, warnings, and limitations; and
- the underlying source result tables.

If narrative assembly fails after the statistical steps finish, the tool
attempts to preserve numeric frames in a fallback workbook and labels the
report failure explicitly.

**Export Stats-Ready Workbook** writes `Stats_Ready_Summed_BCA.xlsx` for JASP,
R/RStudio, SAS, or another package. It contains long and wide Summed BCA data,
participant and canonical group identifiers, and harmonic-selection evidence.
Use it for covariates, other random-effects structures, more than two groups,
Kenward-Roger/Satterthwaite inference, equivalence tests, or another final
model not offered by Standard FPVS Screening.

Retain `Quality Check/Harmonic_Selection_Summary.xlsx` and the corresponding
project metadata with the analysis record.

## Published-Method Context

The core approach has direct FPVS precedent:

- [Vandenheever et al. (2025)](https://doi.org/10.1016/j.ijpsycho.2025.113212)
  analyzed summed BCA with ROI and anxiety-group models, a participant random
  intercept, and multiplicity-adjusted planned contrasts.
- [Van der Donck et al. (2020)](https://doi.org/10.1111/jcpp.13201) used REML
  mixed models of expression, ROI, and group with participant random
  intercepts and residual-assumption checks.
- [Vettori et al. (2020)](https://doi.org/10.3389/fpsyt.2020.00332) used a
  Group x Stimulus x ROI mixed model, participant random intercepts, and
  fitted-model post-hoc tests.
- [Samaey et al. (2024)](https://doi.org/10.1186/s12916-024-03610-w) analyzed
  FPVS amplitudes in adolescents aged 12--16 using mixed models, participant
  random effects, covariates, and multiplicity-adjusted contrasts.
- [Feuerriegel et al. (2018)](https://doi.org/10.1016/j.biopsycho.2018.09.002)
  provides FPVS precedent for repeated-measures ANOVA on summed harmonics with
  Greenhouse-Geisser handling and Holm correction.
- [Keil et al. (2022)](https://doi.org/10.1111/psyp.14052) recommend a priori
  ROIs, multiplicity control across ROIs, and maximum-statistic permutation
  methods for joint frequency-domain inference.

The Toolbox adapts these practices; it does not exactly reproduce any one
paper. In particular, `statsmodels` asymptotic ML likelihood-ratio tests and
Wald contrasts are not Kenward-Roger or Satterthwaite F tests. Holm is not
numerically identical to Bonferroni or Tukey. Compatibility ANOVA and optional
sensitivity checks remain secondary to the primary LMM.

See the
[statistical methods reporting checklist](../reference/methods-reporting-checklist.md#standard-fpvs-screening)
before writing a manuscript or preregistration.
