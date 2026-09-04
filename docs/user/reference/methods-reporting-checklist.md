# Methods and Reporting Checklists

## Standard FPVS Screening

Use this checklist for a manuscript, preregistration, report, or shared analysis
that relies on Standard FPVS Screening. The native screen is a transparent
first round of common FPVS checks, not a universal final statistical model.
Use a planned custom model when the question requires covariates, random
slopes, longitudinal or nested structure, more than two groups, equivalence
testing, or another specialized estimand.

### Design and population

- Report the FPVS Toolbox release or commit and whether the project ran in
  native **single-group** or **two-group** mode.
- Identify the primary outcome as Summed baseline-corrected amplitude (Summed
  BCA, in microvolts) and state which screening questions were relevant:
  positive response, Condition/ROI pattern, interaction explanation, and/or
  two-group differences.
- Report participant age range, recruitment population, inclusion/exclusion
  rules, every canonical group definition, and N per group.
- Report QC and manual exclusions before the analysis. State that the eligible
  participant cohort was frozen before the model used its finite available
  observations.
- Report frozen N, contributing N, fully complete and partially observed
  conditions, structurally empty/excluded cells, missing or non-finite cell
  counts, and observed N per model or comparison cell.
- State that missing responses were not imputed. Explain that likelihood-based
  available-observation inference assumes ignorable/missing-at-random (MAR)
  missingness conditional on modeled variables, while missing-not-at-random
  (MNAR) exclusions can bias estimates and p-values.
- For a multi-group project, state that group assignments came from canonical
  `project.json` `group_id` values rather than folder-name inference. Standard
  screening supports exactly two groups; use a planned custom model for three
  or more groups.

### Sensor geometry and interpolation

- Report the project-owned electrode montage as MNE `biosemi64`, the Toolbox
  geometry version/fingerprint, and the retained canonical scalp set. State
  whether all 64 sensors were retained or an explicit channel limit produced a
  reduced analysis, and identify the coordinates as a standard cap template
  rather than participant-specific digitization.
- Report the channel-label profile. `anatomical_labels` means the BDF carried
  the canonical anatomical names. `biosemi64_1020_ab_v1` means the explicit
  standard BioSemi 64-channel 10/20 A1-A32/B1-B32 wiring; it must not be
  described as support for BioSemi ABC/equiradial or custom caps.
- State that the complete acquisition header was checked before any reduced
  load, that selected EXG mastoid references remained coordinate-free until
  initial reference, and that CMS/DRL were not treated as recorded scalp/data
  channels.
- Report bad-channel decision sources separately, the requested interpolation
  channels, successful interpolation channels, and the recorded interpolation
  status for each recording. A failed or unavailable interpolation is not zero
  interpolated channels and must not enter downstream analysis as a completed
  recording.
- Do not pool outputs with missing, legacy `standard_1005`, or mixed geometry
  provenance. Reprocess historical recordings before new analysis or
  publication when any channel was interpolated or a geometry-based rule
  informed channel decisions. Regenerate legacy scalp maps even when no
  interpolation occurred because the sensor plotting positions changed.
- If the QC-15 synthetic sensitivity run is cited, label it as a deterministic
  geometry-isolation test. It showed identical signal-derived metrics in its
  no-bad-channel control and changed interpolation/downstream near-threshold
  results in its fixed-bad scenarios; it did not estimate prevalence or effect
  size in representative lab recordings. Retain the representative-data rerun
  and reprocessing inventory when those become available.

### Preprocessing signal QC

- Report that signal-based QC used the exact marker-reviewed analyzed
  condition-occurrence spans, with project presentation rate, oddball rule,
  expected oddball cycles, and actual analyzed duration. State which
  occurrences were not evaluated and why; do not count them as clean or as an
  unflagged denominator.
- Report 5-second transient windows with a nominal 2.5-second hop, actual
  rounded sample counts, and the full tail-aligned or short-unpadded edge
  policy. Treat the union of flagged-window coverage as review provenance, not
  measured artifact duration or independent events.
- Report the experimental removed-electrode detector mode and version. Separate
  persistent low-variance suggestions and manual targets from high-amplitude,
  rare-burst, spatial, condition/occurrence, and transient review evidence.
- Report severe raw amplitude and candidate count, fraction, hemisphere, and
  BioSemi64 cluster crossings as review flags, along with the user's explicit
  recording- or participant-scope inclusion/exclusion decision. These
  provisional thresholds do not prove that a recording is usable or unusable.
- If detector performance is reported, identify the labeled dataset, equipment,
  participant-level development/holdout split, denominators, and uncertainty.
  Describe current percentages as in-lab validation until an independent
  dataset or lab reproduces them.

### Summed BCA and selection provenance

- Report the named harmonic-selection profile, stable method ID/version,
  canonical selection fingerprint, configured search ceiling, and whether the
  project inherited Legacy behavior or explicitly saved a new-project profile.
- Report evaluated, detected, and included oddball harmonics as separate lists,
  plus exact BCA columns, base-rate-overlap exclusions, stopping/cutoff reason,
  and any candidates that were not evaluated after stopping. Do not call every
  included fill-through harmonic significant.
- For either adaptive non-legacy profile, report the all-scalp or frozen
  a-priori selection mask; participant Ns within every declared group x
  condition cell; equal group weights within condition; condition-specific Z
  calculation; and equal condition weights. State that entirely missing
  declared cells block adaptive selection rather than being silently
  renormalized. Explain that equal group weighting defines the common-selector
  estimand and gives members of a smaller group more influence.
- For an adaptive non-Legacy repeated-session project, report that workbooks
  and frequency-domain
  exclusions were recording-scoped while participants remained the pairing
  unit. Report recording-to-participant, stable-group, session, visit, and
  source assignments; observed and missing visits; participant N within every
  declared group x session x task-condition selector cell; equal group weights;
  session- and task-condition-specific local Z calculations; and equal weighting
  of all session x task-condition Z scores. State that one common harmonic list
  was applied across sessions, that individual missing visits were not imputed,
  and that an entirely empty declared cell blocked adaptive selection. For a
  fixed/preregistered profile, state that every available recording was checked
  against the same fixed domain without adaptive pooling.
- For adaptive profiles, report strict `z > 1.64` and the neighboring-bin rule:
  +/-10 FFT bins, excluding target - 1, target, and target + 1, then removing
  one finite minimum and maximum before the mean and population SD. For the
  Dzhelyova/Poncet profile, report the two consecutive eligible failures and
  preceding cutoff; state whether the search ceiling was sufficient to observe
  the stop. For Significant-only, state that only local threshold detections
  were included and that this is not across-harmonic error correction.
- For Fixed/preregistered, report whether the input was an exact Hz list, upper
  oddball-harmonic index, or upper frequency, plus every dynamic base-overlap
  exclusion and the independent source/preregistration for that domain. State
  that dynamic base-overlap exclusion was mandatory, not user-selectable.
- For Legacy, report its saved electrode scope, equal-available-workbook
  pooling, fill-through-highest rule, and whether the one-pass isolated-highest
  guard changed the sum. The guard drops the isolated highest detected peak
  only when more than 10 eligible non-base harmonics lie strictly between the
  two highest detections; exactly 10 remains allowed and the upper peak stays
  recorded as detected.
- State whether the harmonic list was selected independently, was a fixed but
  unverified list, or was selected adaptively from the same sample.
- If the list was selected from the analyzed sample, label
  response-versus-zero p-values **exploratory post-selection**.
- State that one common included list was applied uniformly across
  participants, groups, conditions, electrodes, and ROIs. If the profile was
  changed, report whether the Stats-ready and full-audit workbooks and the
  canonical L2-MNE/eLORETA Hauk source-PSD map directories were current for the
  same fingerprint; retain older reports with their original fingerprint
  rather than silently relabeling them.
- For exported multi-group data, retain and report the stable canonical
  `group_id` used for pooling/inference separately from the human-readable
  `group_label`. Display labels are not identifiers and need not be unique.
- State that the standard response question is prespecified as one-sided:
  `H1: mean Summed BCA > 0`. A negative response cannot satisfy that
  directional hypothesis.

### External full-audit dataset

- When analyzing `Analysis_Ready_Summed_BCA_Full_Audit.xlsx`, state that the
  workbook retains all available processed participant, condition, ROI, and
  electrode values. Toolbox QC decisions are flags, not automatic exclusions
  in this file.
- Report which flagged observations, if any, the external analysis excluded
  and give the prespecified rule. Do not describe the full-audit row count as
  the inferential sample size if the external model used a subset.
- State that raw ROI Summed BCA is the mean, across available ROI electrodes,
  of each electrode's BCA summed over the accepted processing-time harmonics.
  RMS normalization is harmonic-specific: at each accepted harmonic, divide
  every electrode BCA by the scalp vector length
  `sqrt(sum(electrode_bca**2))`, then sum the normalized electrode values over
  harmonics and average them within ROI (Dzhelyova et al., 2017; McCarthy &
  Wood, 1985). Note that this published "RMS" formula is root-sum-square, not
  conventional root mean square. Signed-mean normalization instead divides
  each electrode's raw post-harmonic sum by the whole-scalp signed mean before
  ROI averaging.
- Retain the workbook's ROI definitions and harmonic-selection sheets with the
  analysis record. Missing conditions are blank and must not be recoded as
  zero.

### Primary statistical model

The standard contract is fixed at alpha 0.05, finite available observations,
a participant random intercept, one-sided positive-response tests, two-sided
model-derived contrasts, and Holm family-wise correction. These are not
selectable analysis profiles.

For a single-group analysis, report:

- the conceptual sum-coded model
  `Summed BCA ~ Condition * ROI + (1 | Participant)`;
- the finite observed row set, participant grouping, accepted
  random-intercept structure, optimizer, convergence, and singularity status;
- that the accepted final coefficient model used REML;
- that Condition, ROI, and Condition x ROI were tested with explicit
  hierarchy-preserving full-versus-reduced models fitted with maximum
  likelihood on the same rows, using asymptotic chi-square likelihood-ratio
  tests;
- that the three primary LMM block tests were Holm-corrected together in
  `omnibus_effects_strict`, and that their exported hierarchy-preserving labels
  should not be relabelled as pure Type-III effects;
- the one-sided positive-response one-sample t-tests across all estimable
  Condition x ROI cells and their single Holm family,
  `response_core_cells`; and
- when the corrected Condition x ROI interaction was supported, the two-sided
  `LMM-derived model-estimated contrast` comparisons of conditions within ROI
  and ROIs within condition, Holm-corrected in `planned_contrasts`. State that
  these automatic explanations were gated by the corrected primary
  interaction.

For a two-group analysis, report:

- the conceptual sum-coded model
  `Summed BCA ~ Group * Condition * ROI + (1 | Participant)`;
- that exactly two canonical groups were present, with at least two retained
  participants contributing observations in each group and finite data in
  every required fixed-effect cell;
- the finite observed row set, participant grouping, accepted
  random-intercept structure, optimizer, convergence, and singularity status;
- that final coefficient estimates used REML and hierarchy-preserving
  full-versus-reduced omnibus models used ML on the same rows with asymptotic
  chi-square likelihood-ratio tests;
- the four Holm-corrected rows in `omnibus_effects_strict`: Any group-related
  effect, Group x Condition x ROI, Group x Condition-related block, and
  Group x ROI-related block. Explain that "Any group-related effect" jointly
  tests all fixed terms containing Group and is not a pure average Group main
  effect;
- the one-sided response-versus-zero one-sample t-tests within every estimable
  Group x Condition x ROI cell, Holm-corrected once in
  `group_response_cells`; and
- the prespecified two-sided Group A minus Group B
  `LMM-derived model-estimated contrast` in every estimable Condition x ROI
  cell. Report signed estimates, standard errors, 95% confidence intervals,
  asymptotic Wald z statistics, raw and Holm-adjusted p-values, and observed
  coverage. These rows form `group_core_cells` and run independently of the
  joint omnibus decision.

Do not infer a group difference by comparing whether the two within-group
response tests are individually significant. Do not describe a localized
group-cell contrast as conditional on a significant joint group test; the
direct contrast family is intentionally ungated.

### Balanced-only ANOVA compatibility

- Describe repeated-measures or mixed ANOVA as a secondary compatibility
  check, never as the primary analysis.
- For single-group mode, state that ANOVA ran only if every included
  participant had exactly one finite value in every Condition x ROI cell.
- For two-group mode, state that ANOVA additionally required exactly two
  equal-sized groups. Its Group x response-cell result is a broad collapsed
  compatibility check and does not separately decompose Group x Condition,
  Group x ROI, or Group x Condition x ROI.
- Report the balance audit and why ANOVA ran or was skipped. When it ran,
  report degrees of freedom, F statistics, partial eta squared, sphericity and
  Greenhouse-Geisser handling where applicable, and Holm adjustment in
  `anova_compatibility_effects`.
- State that compatibility ANOVA never gated, replaced, or changed the primary
  LMM conclusion.

Do not describe the Toolbox's `statsmodels` ML likelihood-ratio p-values as
Kenward-Roger or Satterthwaite results. They are also not numerical replicas of
the F tests with Kenward-Roger-adjusted denominator degrees of freedom reported
in the cited R/lmer FPVS analyses. This distinction is especially important for
small samples.

### Diagnostics and multiple comparisons

- Report finite-value, per-cell N, variance, Shapiro-Wilk, residual-tail,
  convergence, and singularity diagnostics that were estimable.
- State that normality checks were diagnostic only and did not automatically
  select or replace the prespecified primary test.
- Name every comparison family, its family ID and size, alpha, raw p-value,
  adjusted p-value, and adjustment method. The fixed Holm families are
  `response_core_cells`, `group_response_cells`, `group_core_cells`,
  `planned_contrasts`, `omnibus_effects_strict`, and
  `anova_compatibility_effects`, as applicable to the mode and estimable tests.
- Distinguish Greenhouse-Geisser correction for an ANOVA sphericity problem
  from Holm multiplicity adjustment across a named family. They address
  different problems and are not interchangeable.
- State that the standard available-observation route did not queue max-|t|
  resampling because the current implementation requires a complete
  participant-by-cell matrix. If a legacy or custom complete-design max-|t|
  result is reported separately, give its permutation/sign-flip scheme, seed,
  exact-enumeration status or draw count, and exchangeability assumption.
- Do not call Holm "Bonferroni" or "Tukey." Published FPVS studies use all
  three in different settings, but their adjusted p-values and contrast-family
  definitions are not interchangeable.

### Sensitivity and interpretation

- List every robust, rank-based, and leave-one-participant-out sensitivity
  requested, including the trim fraction and other applicable settings.
- Keep sensitivity-only findings labelled as sensitivity evidence. Do not
  promote a result because one of several methods happened to be significant.
- Report estimates, confidence intervals, effect sizes, N, exact p-values, and
  the correction used; do not report only "significant" or "not significant."
- State that mixed-model likelihood-ratio and Wald p-values use asymptotic
  reference distributions and deserve particular caution in small samples.
- Translate a nonsignificant result as "the analysis did not provide evidence
  of a difference." Do not infer equivalence or absence without a prespecified
  equivalence test.
- For an observational 13--15-year-old sample, describe group differences as
  associations in the analyzed sample. Do not infer that anxiety caused the
  response or that the measure is diagnostic.
- State which covariates were and were not modeled. The native model does not
  currently adjust for age, gender, depression, medication, recruitment site,
  or other possible confounders. Use a prespecified external model when those
  variables are part of the research question.

### Records to retain

Keep the following with the analysis record:

- the native workbook,
  `Native Single-Group Available-Case LMM Results.xlsx` or
  `Native Multi-Group Available-Case LMM Results.xlsx`, including At a Glance,
  Detailed Methods, Test Inventory, Correction Families, Limitations, source
  result frames, coverage, exclusions, group assignments, and the ANOVA
  compatibility audit;
- `Stats_Ready_Summed_BCA.xlsx` if external analyses were run;
- `Quality Check/Harmonic_Selection_Summary.xlsx` and the corresponding
  project metadata;
- the processing ledger, preflight/QC report, canonical geometry identity, and
  per-recording interpolation outcomes used to establish current BioSemi64
  inputs;
- model warnings, sensitivity settings, random seed, and the FPVS Toolbox
  release/commit; and
- the analysis plan or preregistration that establishes ROI, harmonic,
  direction, model, covariate, and multiplicity decisions.

The core Summed BCA factorial models have direct FPVS precedent in
[Vandenheever et al. (2025)](https://doi.org/10.1016/j.ijpsycho.2025.113212),
[Van der Donck et al. (2020)](https://doi.org/10.1111/jcpp.13201),
[Vettori et al. (2020)](https://doi.org/10.3389/fpsyt.2020.00332), and
[Samaey et al. (2024)](https://doi.org/10.1186/s12916-024-03610-w).
[Feuerriegel et al. (2018)](https://doi.org/10.1016/j.biopsycho.2018.09.002)
provides an FPVS repeated-measures ANOVA/Greenhouse-Geisser/Holm precedent.
[Keil et al. (2022)](https://doi.org/10.1111/psyp.14052) provide broader
frequency-domain guidance for a priori ROIs, multiplicity correction, and
maximum-statistic resampling. These sources support the method family; they do
not make the Toolbox an exact reproduction of any one published pipeline.

## Repeated-Session Change Analysis

Use this checklist when the native v1 repeated-session workflow is used rather
than Standard FPVS Screening.

### Design and identity

- Report exactly two stable between-participant groups and exactly two ordered
  within-participant sessions. Retain canonical participant, recording, group,
  session, source, and visit IDs from `project.json`.
- Report the session labels, visit indices, acquisition interval or
  `days_from_baseline` when available, N recordings, N unique participants, N
  complete pairs per group, every missing visit, duplicate/conflicting source
  finding, and each recording- or recording-condition exclusion.
- State that one participant may contribute at most one recording per session,
  group is stable across sessions, and missing visits were not imputed.
- If phase order was fixed, state explicitly that phase is perfectly
  confounded with visit order, elapsed time, repetition, practice, and
  habituation. Describe the estimand as session/phase-at-visit or, for example,
  `session 2 (follicular) - session 1 (luteal)`. Do not claim an isolated
  physiological phase effect.

### Outcomes and inference

- List every prespecified Condition x ROI outcome selected in the GUI before
  the run. The primary family must include every declared outcome, including a
  declared outcome that proved non-estimable.
- Define the participant delta as visit 2 minus visit 1. Define the primary
  estimand as Group A minus Group B in those participant deltas and report the
  group order used for the sign.
- Report the two-sided Welch test of participant deltas, complete-pair N per
  group, mean and SD of group deltas, difference in change, SE, 95% CI, Welch
  statistic and degrees of freedom, raw and Holm-adjusted p-values, family ID
  and size, Hedges g, and inferential status code.
- Label paired within-group changes as secondary. Report their two-sided
  one-sample t-test of participant deltas, N, visit means, mean change, 95% CI,
  Cohen's dz, and the separate Holm family spanning both groups and every
  declared outcome.
- State that inference was complete-pair separately by outcome, with no
  imputation, no cross-outcome complete-case deletion, and no automatic
  fallback. Do not replace this contract after seeing convergence or p-values
  with a full four-way model or a legacy backup test.
- Interpret a nonsignificant result as failure to establish a difference, not
  proof of equivalence or no change. In an observational group comparison, do
  not make causal or diagnostic claims.

### Records to retain

- `Repeated_Session_Change_Analysis.xlsx`, including primary, secondary,
  participant deltas, participant-session audit, outcome-pair audit, pair
  coverage, method metadata, canonical long data, and schema;
- `Analysis_Ready_Summed_BCA_Full_Audit.xlsx`, retaining Recording ID, Session
  ID and label, Visit Index, Days From Baseline, Group ID, QC flags, and
  exclusion reasons;
- `Quality Check/Harmonic_Selection_Summary.xlsx`, the one common harmonic
  list and fingerprint used across both sessions, and recording-aware pooling
  cell Ns/weights; and
- the source preflight report or correction log for any identity conflict,
  missing visit, filename/source mismatch, or renamed/reassigned raw file.

## Free Harmonic Clustering Analysis

Use this checklist for embedded Free Harmonic Clustering Analysis. It
is a clean-room implementation of the sensor x harmonic method described by
[Hermann et al.](https://doi.org/10.1111/psyp.70361) and informed by their
[public implementation](https://github.com/oliver-hermann1/FPVS_Multiharmonic),
not a claim of numerical identity with the authors' unpublished normalized
tensors, spatial adjacency, dependency version, or expected outputs.

### Design and inputs

- State whether the run used a paired condition contrast or an independent
  two-group contrast. For independent groups, report canonical `group_id`
  values and N per group. For paired conditions, report complete paired N.
- Report the one declared contrast and its direction (`arm A - arm B`). A set
  of separate condition runs is not automatically corrected across conditions.
- For a repeated-session batch, report the two canonical group IDs, the two
  canonical session IDs/labels and visit indices, all declared conditions, and
  the four prespecified families: session-averaged groups, Visit 2 minus Visit
  1 within each group, and the between-group difference in participant session
  change. State that all primary families used complete phase-balanced pairs;
  report complete-pair and missing-visit N by group and condition.
- When session/phase is aligned with visit order, call the contrast
  `session/phase-at-visit` and state that phase cannot be separated from visit
  order, elapsed time, repetition, habituation, or other retest effects.
- Report all ledger, participant-condition, whole-participant, and frequency-
  domain QC exclusions. Missing nodes were not zero-filled or omitted with
  varying degrees of freedom.
- Report the BioSemi64 channel set/order, FFT duration/bin width, base and
  oddball frequencies, ceiling, and complete +/-0.1-Hz window preflight.
- State that project metadata, participant/group assignments, QC decisions,
  and source workbooks were read without modification and that the completed
  output was published as a new additive run.
- Retain the neutral FullFFT provenance method version plus source, cohort,
  frequency-QC, processing/export, and grid fingerprints. State that this
  processing-owned record, not the standard Stats harmonic cache, validated
  the inputs. A standard Summed-BCA profile/list change does not define or
  invalidate the clustering domain; a FullFFT/cohort/QC/rate/grid change does.

### Harmonics and normalization

- State that raw amplitude came from original `FullFFT Amplitude (uV)`
  workbooks. Saved Toolbox SNR, z-score, BCA, and Stats-ready Summed BCA were
  not used as substitutes.
- State whether Hermann automatic selection or a preregistered fixed highest
  harmonic was used. For automatic selection, report the per-arm
  grand-spectrum selector, sample-SD convention, exact `z > 3.29` detections,
  and highest detection. In either mode, report the fill-through-highest
  retained list and every dynamically derived base-rate-overlap exclusion.
- Report the SNR rule: target amplitude divided by mean surrounding amplitude
  within +/-0.1 Hz after excluding the target and immediately adjacent FFT
  bins, without min/max trimming.
- State that each participant/arm sensor x harmonic tensor was L2-normalized.
  Inference concerns the relative spatial/harmonic distribution, not total
  response magnitude.
- State whether the analyzed sample selected the harmonic domain. The paper-
  faithful default is adaptive/same-data selection, not an independently fixed
  confirmatory domain.
- For a repeated batch, report the one shared-domain fingerprint and selection
  provenance across all group x session x condition cells. Describe the exact
  tensor rules: normalize the within-participant two-session mean once for the
  session-averaged group family; normalize each session separately before
  paired Visit 2 minus Visit 1; and do not renormalize that difference before
  the between-group change comparison.

### Cluster inference

- Report paired t or pooled independent t, degrees of freedom, two-sided entry
  alpha `.01`, exact t threshold, and signed summed-t cluster mass.
- Report the version and hash of the fixed 197-edge FieldTrip-style BioSemi64
  spatial reconstruction, and state that it is an independent Toolbox graph,
  not the authors' adjacency matrix. Every retained harmonic at one sensor was
  adjacent to every other retained harmonic; spatial neighbors connected only
  at the same harmonic; singleton clusters were allowed.
- Report whole-participant sign flips/swaps or group-label permutations with
  group sizes preserved, assignment count, RNG/seed, and assignment hash.
- Report separate maximum-positive/minimum-negative nulls, strict Monte Carlo
  comparison, `+1` p correction, and Monte Carlo confidence intervals.
- State that raw cluster p-values were sign-specific and evaluated at `.025`
  per direction for a two-tailed family alpha `.05`; report doubled p-values
  when included in the export.
- Report every observed cluster, membership, mass, cluster-level p/interval,
  and descriptive cluster-average Cohen's d. Effect sizes are post-selection
  and shape-dependent.
- State the weak/global FWER limitation: significant clusters do not make
  individual sensors, harmonics, cells, or boundaries pointwise significant.
- State that cluster-level control is conditional on the declared candidate
  domain, adjacency, cluster-entry threshold, contrast family, and valid whole-
  participant exchangeability. It favors spatially or harmonically extended
  effects and does not correct a collection of separately run contrasts.
- For a repeated batch, report the global two-sided run p-value, Holm p-value
  across conditions within each of the four family IDs, and conservative Holm
  p-value across all condition x family runs. These are run-level corrections;
  do not label a cluster's raw sign-specific p-value as Holm-adjusted.
- For Hermann automatic selection, state that the domain was selected from the
  observed arms and then held fixed during permutation. Conditional cluster
  correction alone does not establish unconditional error control for the
  combined workflow.
- State the validation layer and status accurately. The deterministic
  24-replicate x 199-assignment, at-most-five-rejection harness is software
  regression smoke only and must not be reported as calibrated FWER evidence.
- If relying on the reviewed powered-calibration receipt, cite its
  Toolbox commit, frozen configuration/generator and adjacency identities,
  paired and independent designs, regimes, 4,000 replicate count, 10,000
  assignments per replicate, seeds, rejection definition, rejection counts,
  and exact Clopper-Pearson bounds. The frozen v1 run recorded 111/2,000
  independent-group rejections (`.0555`; one-sided 97.5% upper bound `.06645`)
  and 91/2,000 paired-condition rejections (`.0455`; upper bound `.05557`),
  with every design-by-regime guardrail passing. Do not generalize this bounded
  simulation evidence beyond its frozen regimes, present it as universal proof
  or power, or imply that it validates the truth of a real-data finding.
- State explicitly that the reviewed powered receipt covers the frozen legacy
  paired-condition and independent-group workflows only. It does not validate
  the repeated-session shared selector, composite tensors, group-by-session
  interaction contrast, or cross-condition Holm layers.

Retain `Free_Harmonic_Clustering_Results.xlsx`, the run manifest, compressed
arrays, machine-readable result tables, source-workbook provenance, exact
adjacency edges, null extrema or hash, Toolbox commit, and analysis
plan/preregistration.

For repeated batches, also retain the complete-pair cohort/coverage audit,
analysis-only recording exclusions and their required reasons, shared-domain
tables/fingerprint, per-run derived seeds, both Holm layers, and the fixed-order
confounding statement. Analysis-specific exclusions are source-immutable and
must not be presented as changes to project QC.

## Hauk-Informed Source-PSD Workflow

This page describes the current source-localization workflow in FPVS
Toolbox. It prepares signed time-domain EEG during normal processing and later
uses MNE to estimate independent L2 minimum-norm cortical and eLORETA volume
source amplitudes. The default current method identifiers are
`l2_mne_hauk_source_psd_cortical_normal_v1` and
`eloreta_volume_hauk_source_psd_vector_norm_v1`.

The workflow is informed by the source-spectrum approach used by Hauk et al.
(2021) and by the public
[`olafhauk/FPVS_sweep`](https://github.com/olafhauk/FPVS_sweep) scripts. It is a
documented FPVS Toolbox adaptation, not a claim that the Toolbox exactly
reproduces that study's combined EEG/MEG, individual-MRI, preprocessing, or
neighboring-bin pipeline.

### Processing-Time Derivative

After the normal condition epochs have been created and the Excel export has
succeeded, FPVS Toolbox writes one source-ready derivative for each processed
participant and condition. It selects EEG channels only and takes the
sample-by-sample arithmetic mean across repetitions while the values are still
signed volts. Thus, responses with opposite polarity can cancel; the Toolbox
does not rectify the signal, average magnitudes, or average repetition PSDs.

The derivative reuses the processed epoch's exact sample count (`N`), sampling
frequency, `55_onbin` crop/bin provenance, montage, channel order, bad-channel
state, and final average-reference state. It contains no FFT, source estimate,
or neighboring-bin statistic.

The generated layout is:

```text
6 - Source Localization/
  Source-Ready Time Domain v1/
    <condition label>/
      [<group>/]
        <participant>_<condition_id>_avg_raw.fif
        <participant>_<condition_id>_avg_raw.json
    manifests/
      [<group>/]
        <participant>.json
```

The condition folder comes first and the optional group folder comes second.
`condition_id` is the stable project event ID. The JSON beside each FIF records
provenance and checksums; the participant manifest is written last as the commit
marker after every expected condition pair succeeds. Missing, stale,
checksum-mismatched, or incompatible derivatives are rejected rather than
silently replaced with amplitude workbooks.

If derivative publication fails, the completed Excel export is preserved. The
processing ledger records the source-readiness warning and treats the missing
source output as work that must be rescheduled; it does not label a missing
derivative as reusable.

Source-map generation uses the versioned
`available_case_by_group_condition_v1` cohort policy. Saved whole-participant
QC exclusions remove that participant from every source cohort. A completed
participant with an explicitly missing or saved-QC-excluded condition is
omitted only from that participant-condition cell and can still contribute to
other conditions with valid derivatives. A participant with unknown source
availability, no remaining source condition, or a globally incomplete source
derivative is omitted from every source condition. Source-only omissions do
not alter available Excel outputs or automatically enter the project's general
exclusion workbook. The prepared manifest, participant sidecar, validation
report identify every omitted participant-condition and reason; the processing
log and LORETA status may summarize large omission sets by scope and reason.
Files that claim to be retained but fail checksum, compatibility, or manifest
validation still stop the source build.

These signed FIF/JSON derivatives are sufficient input for the source-method
orientation changes described below. If they are already present and valid,
you can rebuild the source maps without reprocessing the participant EEG.

### Current Source Calculations

The normal source build is intentionally EEG-only and generates both current
methods. They use the same signed FIF derivatives, available-case
group-condition source cohorts,
saved oddball harmonics, exact FPVS frequency bins, and neighboring-bin z-score
algorithm. They do not share source values: each inverse produces and caches
its own participant source-amplitude and z-score arrays.

Both methods use the Toolbox BioSemi64 channel geometry with the `fsaverage`
template rather than individual MRI/coregistration, MEG, or EEG/MEG fusion. The
cortical inverse is MNE-native
L2-MNE with `method="MNE"`, `loose=0.2`, `depth=None`, `fixed=False`, and
`lambda2=1/9`; it does not apply dSPM, sLORETA, or eLORETA normalization. By
default it uses `pick_ori="normal"` to select the cortical surface-normal
component and records method identity
`l2_mne_hauk_source_psd_cortical_normal_v1`. This is closer to the Hauk source
estimator than the older pooled-orientation implementation. Source Map Options
can instead select "Legacy MNE pooled orientation" to reproduce older
`l2_mne_hauk_source_psd_v1` maps; the two results use separate method labels,
provenance, and caches.
Both L2 variants are cortical source models: candidate sources and displayed
values live on the reconstructed cortical sheet. They do not estimate arbitrary
interior, cerebellar, brainstem, or other non-cortical volume locations.

The independent volume inverse uses `method="eLORETA"`, a 10 mm fsaverage
volume grid, `loose=1.0`, `depth=None`, `fixed=False`, and `lambda2=1/9`. Its
current method identity is `eloreta_volume_hauk_source_psd_vector_norm_v1`.
It preserves complex exact-bin coefficients through a vector inverse rather
than accepting a basis-dependent scalar pooling of free orientations.
This eLORETA method is the separate FPVS Toolbox volumetric extension. Its
candidate sources lie on the inner-skull-BEM-bounded fsaverage volume grid, so
a prepared location need not lie inside either cerebral pial surface and grid
membership alone does not assign a tissue label. Pial and whole-brain meshes in
the viewer are anatomical context only; they do not define or clip the volume
source space and do not remove values from automatic color-scale calculations.
Because the Toolbox workflow does not require a separate resting/noise
recording, it builds MNE's ad-hoc diagonal EEG noise covariance. This is an
intentional Toolbox adaptation of the Hauk reference pipeline, which used a
recorded resting covariance, and must be reported with the inverse settings.

For each participant and condition, the producer:

1. loads the exact canonical included oddball harmonics already selected and
   saved for the project during post-processing. It does not reconstruct the
   profile's stopping or fill rule from the detected list;
2. requires every selected harmonic and every required neighboring position to
   fall on an exact FFT bin for the derivative's `N` and sampling frequency;
3. for default L2-MNE, calls `mne.minimum_norm.compute_source_psd` on the
   complete repetition-averaged Raw time series with `n_fft=N`, zero overlap,
   the Hann setting, and `pick_ori="normal"`, then validates nonnegative source
   power and takes its square root to obtain cortical-normal source amplitude;
4. for current eLORETA, mean-removes the signed sensor time series, computes
   complex periodic-Hann coefficients at only the exact required FFT bins,
   calls `mne.minimum_norm.apply_inverse(..., pick_ori="vector")`, and computes
   the rotation-invariant amplitude
   `sqrt(abs(Cx)^2 + abs(Cy)^2 + abs(Cz)^2)` at each volume source and bin;
5. sums corresponding target and neighboring-bin amplitudes across the selected
   harmonics in source space; and
6. converts that summed target to a neighboring-bin z score at each source.

Nearest-bin substitution is forbidden. If a nominal harmonic is off-grid, a
required bin is absent, or the complete neighboring window would cross the FFT
range, the source build stops with a prerequisite/error message. It does not
round the requested frequency to a nearby result.

The current source calculations consume the saved harmonic-selection record
and committed time-domain derivatives, not `FullFFT Amplitude (uV)` or the
Stats-ready workbook. Stats-ready export and source generation are sibling
consumers after harmonic selection, so failure of the Stats-ready export alone
does not invalidate otherwise complete source inputs.

The eLORETA calculation is a Hauk-informed extension of the published
source-spectrum sequence, not a claim that Hauk et al. implemented this exact
EEG-only fsaverage eLORETA volume workflow. In particular, an L2-MNE z-score
array is never transformed or relabeled as eLORETA. The historical method ID
`eloreta_volume_hauk_source_psd_v1` identifies older signed-FIF eLORETA maps
whose free-orientation scalar pooling was basis-dependent; those maps remain
loadable but are not relabeled as corrected vector-norm results.

All orientation selection, inverse calculation, vector pooling, harmonic
aggregation, and z scoring happen in source producers before the visualizer
loads a payload. Cortical-surface, 3D-volume, and MRI-slice
choices change only the display of saved values.

For volumetric results, orthogonal MRI slices are the preferred view for
approximate anatomical localization. The interactive 3D view interpolates the
retained volume-grid values into a readable contour. That interpolation is
display-only: its triangles and intermediate colored locations were not
separately tested, the contour is not an anatomical structure, and its visible
extent is not an inferential cluster boundary. A cerebral pial mesh or
skull-stripped whole-brain shell may provide spatial context, but neither
performs an additional source filter. Report anatomical descriptions cautiously
because the estimates use EEG-only template anatomy rather than individual MRI
and coregistration.

For projects with more than one canonical participant group, the Toolbox
creates a separate source summary and cluster-inference input for each group and
condition. It does not silently pool experimental groups into one source map.
Single-group and ungrouped projects retain the condition labels used elsewhere
in the project.

A one-participant group can support a descriptive source-space summary but not
the one-sample cluster-permutation inference used for the saved display mask.
In that case the Toolbox exports the descriptive L2-MNE/eLORETA map, records
the mask as unavailable because of insufficient participants, and treats the
unmasked display as exploratory. Do not report that map as a group-level
cluster-permutation result.

### Toolbox Neighboring-Bin Rule

For every selected harmonic, the target uses offset `0`. Noise candidates use
offsets `-10..-2` and `+2..+10`, giving nine bins on each side and excluding
offsets `-1`, `0`, and `+1`. Corresponding offsets are first summed across all
selected harmonics. At each source point, the Toolbox then pools the 18 summed
noise values, removes exactly one global minimum and one global maximum, and
computes the mean and population standard deviation over the remaining 16
values (`ddof=0`). The saved value is:

```text
z = (summed target amplitude - trimmed noise mean) / trimmed noise population SD
```

This exact offset and trimming policy is an intentional Toolbox rule. Report it
explicitly rather than describing the output only as a generic Hauk z score.

### Legacy And Deferred Paths

Existing amplitude-derived L2-MNE Hauk z-score and eLORETA prepared manifests
remain importable in the visualizer and are labeled legacy/exploratory. They do
not serve as fallback inputs for either current source-PSD workflow. Normal
manual and post-processing rebuilds create both time-domain methods. The signed-
FIF IDs `l2_mne_hauk_source_psd_v1` and
`eloreta_volume_hauk_source_psd_v1` are also historical: the former remains an
explicit GUI-selectable reproduction mode, while the latter remains loadable
but records a basis-dependent orientation result. MEG fusion, individual-MRI
modeling, and alternative phase-sensitive estimators beyond the current
exact-bin vector eLORETA route remain possible later additions.

### Manuscript Or Preregistration Checklist

Report at least:

- the FPVS Toolbox release or commit and both method identifiers,
  normally `l2_mne_hauk_source_psd_cortical_normal_v1` and
  `eloreta_volume_hauk_source_psd_vector_norm_v1`; if the L2 legacy toggle was
  used, report `l2_mne_hauk_source_psd_v1` and the pooled-orientation choice;
- that source inputs were EEG-only, signed, sample-wise repetition averages in
  volts, and the number of repetitions contributing to each derivative;
- preprocessing, reference, montage/channel, epoch crop, `N`, sampling
  frequency, and resulting frequency resolution;
- that the saved project harmonic-selection profile and fingerprint were
  reused, with exact detected and included frequencies, stopping reason,
  selection electrode mask, and any profile-specific exclusions or Legacy gap-
  guard decision;
- the EEG-only `fsaverage` BioSemi64 template limitation and the absence of
  individual MRI/coregistration, MEG, and modality fusion;
- the MNE version, cortical spacing, volume-grid spacing, each method's
  independent inverse settings, ad-hoc diagonal EEG noise covariance, and
  source settings;
- that L2-MNE used a cortical-sheet source domain while eLORETA used the
  independent 10 mm volumetric source domain; pial or whole-brain display
  anatomy did not clip the prepared volume estimates;
- L2 `pick_ori="normal"` and square-root PSD amplitude conversion, plus eLORETA
  exact-bin complex periodic-Hann coefficients, `pick_ori="vector"`, and
  `sqrt(sum(abs(Cxyz)^2))` orientation pooling;
- the exact-bin/no-nearest-bin requirement;
- amplitude conversion, harmonic aggregation, offsets `-10..-2` and `+2..+10`,
  one global minimum/maximum removal, and population SD (`ddof=0`);
- participant exclusions, flagged-participant policy, group summary, and each
  method's source-space cluster inference, plus L2-MNE ROI/lateralization
  settings, saved whole-participant and participant-condition QC exclusions,
  and every source-only available-case omission and its reason;
- whether a reported volume figure used MRI slices or the 3D contour, and that
  slice/contour interpolation was display-only rather than additional tested
  locations or inferential extent; and
- that cortical-normal L2 follows the Hauk estimator more closely but remains
  Toolbox-adapted, and that vector-norm eLORETA is a Toolbox extension, citing
  both the study and public code reference below.

Retain the source-ready FIF/JSON pairs, participant commit manifests, harmonic
selection record, and prepared source-output manifest with the analysis record.
Together they provide the provenance needed to audit the source figures.

### References

- Hauk, O., Rice, G. E., Volfart, A., Magnabosco, F., Lambon Ralph, M. A., &
  Rossion, B. (2021). [Face-selective responses in combined EEG/MEG recordings
  with fast periodic visual stimulation
  (FPVS)](https://doi.org/10.1016/j.neuroimage.2021.118460). *NeuroImage, 242*,
  118460.
- Hauk, O. [`olafhauk/FPVS_sweep`: Python scripts for an FPVS frequency-sweep
  experiment](https://github.com/olafhauk/FPVS_sweep), including the public
  `FPVS_PSD_Source_sweep.py` source-spectrum script.
