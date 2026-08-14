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

The Toolbox saves one project-wide harmonic-selection profile and one exact
list of harmonics to include in Summed BCA. The same included list is applied
to every participant, group, condition, electrode, and ROI. Standard FPVS
Screening and the standard analysis workbooks read that saved result; they do
not silently select another list.

New projects use **Dzhelyova/Poncet — stop after two consecutive failures
(recommended)**. Existing projects that predate named profiles retain
**Legacy FPVS Toolbox — through highest with isolated-peak guard** until you
explicitly change them, so upgrading the Toolbox does not silently change old
results.

The Advanced Settings card offers four profiles:

| Profile | What defines the Summed-BCA harmonics? | Interpretation |
| --- | --- | --- |
| **Dzhelyova/Poncet — stop after two consecutive failures (recommended)** | Tests eligible oddball harmonics in order. It stops after two consecutive non-base candidates fail strict `z > 1.64` and includes every eligible harmonic through the one before that pair. | Literature-style, but still adaptive and selected from this sample. |
| **Fixed / preregistered harmonic domain** | Uses an exact Hz list, all oddball harmonics through an upper harmonic index, or all through an upper frequency; the Toolbox always removes dynamically identified base-rate overlaps. | Preferred for confirmatory work when the domain was genuinely specified independently. |
| **Significant-only (exploratory)** | Searches the bounded domain and includes only candidates with strict `z > 1.64`. | Same-sample exploratory selection; it is not across-harmonic multiplicity correction. |
| **Legacy FPVS Toolbox — through highest with isolated-peak guard** | Preserves the earlier equal-workbook grand average, fills eligible harmonics through the highest detection, and applies the one-pass isolated-highest guard described below. | Reproducibility profile for existing analyses, not a claim of exact alignment with every publication. |

For the two adaptive non-legacy profiles, the common selector is balanced in a
specific order. Participants are first averaged within every declared group x
condition cell. Groups then receive equal weight within each condition. A
local-Z spectrum is calculated separately for each condition, and the
condition Z-scores receive equal weight. This keeps a larger group or a
condition with more available workbooks from defining the common outcome just
because it has more files. It also gives each member of a smaller group more
influence, so it is an explicit estimand choice rather than a universally best
weighting rule. If an entire declared group x condition cell is missing,
adaptive selection stops with a message to complete the dataset or use a fixed
domain; it does not quietly redistribute that cell's weight.

Non-legacy adaptive profiles use all retained scalp electrodes by default. A
focal paradigm can instead save a frozen a-priori electrode mask. Later edits
to Stats ROIs cannot change either selection. The mutable union of Stats ROI
electrodes remains available only in the Legacy profile.

For each candidate harmonic, the noise window spans +/-10 FFT bins around the
target. The target bin and its immediately adjacent bins are excluded, then the
single lowest and single highest finite noise values are removed before the
mean and population standard deviation are calculated. Adaptive detection is
strictly greater than `1.64`; equality does not pass. Base-rate overlaps are
excluded from selection and summation.

For the recommended two-failure profile, a base-rate overlap is skipped and
does not count as one of the two failures. If the configured harmonic ceiling
is reached before two consecutive eligible failures occur, the Toolbox stops
instead of pretending that the stopping rule succeeded. Increase the BCA
upper limit and recalculate, or use a justified fixed domain.

Legacy alone uses the earlier fill-through rule. Its one-pass guard activates
when more than 10 eligible non-base harmonics lie strictly between the two
highest detected peaks: the isolated upper peak stays recorded as detected,
but it and all intervening harmonics above the next-highest peak are omitted
from the sum. Base overlaps do not count and exactly 10 intervening harmonics
remains allowed.

The fixed-profile overlap rule is mandatory, not an optional checkbox: a
requested frequency that coincides with the base rate or one of its harmonics
is recorded as excluded and never enters Summed BCA.

The processing workflow records the selection in
`Quality Check/Harmonic_Selection_Summary.xlsx` and in project metadata. A
missing or stale selection must be recalculated before screening proceeds; the
Stats tool does not silently invent another list. Use
**Settings > Preprocessing > Advanced Harmonic Selection and Summation >
Recalculate Harmonics**.
The screening page links to that Settings workflow but does not delete or
recalculate the processing-time selection itself. Before recalculation starts,
Settings snapshots the saved project method plus the relevant app analysis and
ROI settings. Cancelling the FFT-grid/exclusion review, or failing validation
before a replacement selection is saved, restores that snapshot and leaves
current artifacts unchanged. Starting the worker alone does not stale the old
outputs. Settings stays open and project navigation remains locked until the
worker finishes. Once a replacement selection is saved, that method becomes
the project definition; a later export failure preserves the last reproducible
files but records them as stale or failed for the newly required selection
rather than presenting them as current.

Changing participant-condition FFT-crop exclusions changes the active FullFFT
cohort. After that review is accepted, the Toolbox resumes frequency-domain QC
and neutral FullFFT provenance before recalculating selection. This remains a
post-processing-only run: raw EEG preprocessing and participant FFT export are
not repeated.

After an accepted selection changes, the Toolbox marks the Stats-ready and
full-audit workbooks plus the current L2-MNE and eLORETA Hauk source-PSD map
directories stale. It rebuilds the workbooks from the existing processed FullFFT
and BCA sheets and rebuilds the maps from durable source-ready time-domain
derivatives. It does not reload BDF files, filter or epoch EEG, or recompute
participant FFT workbooks. If the scientific selection fingerprint is
unchanged and every recorded derivative still exists and is current, no
rebuild is needed. A failed replacement keeps the preceding reproducible
artifact and records that it is not current for the new selection.

Free Harmonic Clustering is a separate analysis. It reads the original
`FullFFT Amplitude (uV)` sheets, validates neutral FullFFT provenance, and owns
its own harmonic domain. Changing a standard Summed-BCA profile does not change
or stale the clustering domain merely because the standard included list
changed.

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
participant identifiers, stable canonical `group_id` values, separate display
`group_label` values, and harmonic-selection evidence. The ID drives pooling
and inference; the label is descriptive, so two groups with the same display
label remain distinct.
Use it for covariates, other random-effects structures, more than two groups,
Kenward-Roger/Satterthwaite inference, equivalence tests, or another final
model not offered by Standard FPVS Screening.

Every completed data-processing run also writes
`Analysis_Ready_Summed_BCA_Full_Audit.xlsx` automatically. This second workbook
is designed for an outside statistician or a custom RStudio workflow. Its
primary `ROI Long` sheet contains all available processed participants and
conditions, including observations currently excluded by Toolbox QC. Those
decisions appear as `Current Toolbox Exclusion`, `QC Flag`, and `QC Notes`
fields; they do not remove values. Separate sheets provide raw, RMS-normalized,
and signed-mean-normalized wide data, electrode-level values, whole-scalp
values, harmonic-specific RMS scales, ROI definitions, and the harmonic-
selection record. Missing conditions stay missing rather than being filled
with zero.

For RMS-normalized BCA, the Toolbox follows the topographic sequence used by
Dzhelyova et al. (2017). At each selected harmonic, electrode BCA values are
divided by the whole-scalp vector length, calculated as the square root of the
sum of squared BCA values across electrodes. The normalized electrode values
are then summed across harmonics and averaged within each ROI. Although this is
called RMS normalization in that publication, the stated calculation is a
root-sum-square and does not divide by the number of electrodes. Signed-mean
normalization is separate: raw electrode BCA is first summed across harmonics,
then divided by the whole-scalp signed mean and averaged within ROI.

The full-audit workbook uses the harmonic list already accepted at processing
time. Including flagged observations does not cause the Toolbox to select a
different harmonic list. `ROI Long` is the recommended starting sheet for R;
the wide sheets are convenient for software that expects one participant per
row. Any exclusions or alternate models remain the external analyst's explicit
decision.

Retain `Quality Check/Harmonic_Selection_Summary.xlsx`, the corresponding
project metadata, method ID/version, selection fingerprint, detected and
included lists, stopping reason, electrode mask, pooling-cell Ns/weights, and
artifact-freshness record with the analysis.

## Published-Method Context

The core approach has direct FPVS precedent:

- [Dzhelyova et al. (2017)](https://academic.oup.com/cercor/article/27/8/4106/3056435)
  used condition-wise grand spectra and a two-consecutive-nonsignificant-
  harmonic stopping convention. The named Dzhelyova/Poncet profile reproduces
  that stopping concept; its balanced multi-group pooling is an explicit
  Toolbox extension.
- A fixed harmonic range is the clearest confirmatory choice when prior work or
  a preregistration justifies it independently. The Legacy isolated-highest
  greater-than-10 gap guard has no direct publication counterpart and is kept
  as a versioned reproducibility method.
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
