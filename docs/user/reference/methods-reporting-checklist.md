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

### Summed BCA and selection provenance

- Report the exact detected and included oddball harmonics, base-rate-overlap
  exclusions, upper limit, `z > 1.64` rule, ROI-electrode union, neighboring-bin
  rule, and whether the isolated-highest gap guard changed the included list.
  The neighboring window is +/-10 FFT bins; target - 1, target, and target + 1
  are excluded, followed by the single minimum and maximum finite noise
  values. Summation fills eligible non-base harmonics through the highest
  detection unless more than 10 eligible harmonics lie strictly between the
  two highest detections; exactly 10 remains allowed.
- State whether the harmonic list was selected independently, was a fixed but
  unverified list, or was selected adaptively from the same sample.
- If the list was selected from the analyzed sample, label
  response-versus-zero p-values **exploratory post-selection**.
- State that the standard response question is prespecified as one-sided:
  `H1: mean Summed BCA > 0`. A negative response cannot satisfy that
  directional hypothesis.

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

Source-map generation uses a complete-case source cohort. If a completed
participant is missing any canonical condition, or its ledger explicitly says
the source derivative is incomplete, that participant is omitted from every
source condition rather than aborting maps for all other participants. This is
a source-only omission: it does not alter the participant's available Excel
outputs or automatically add the participant to the project's general
exclusion workbook. The prepared manifest, participant sidecar, validation
report, processing log, and LORETA status identify every omitted participant
and reason. Files that claim to be complete but fail checksum, compatibility,
or manifest validation still stop the source build.

These signed FIF/JSON derivatives are sufficient input for the source-method
orientation changes described below. If they are already present and valid,
you can rebuild the source maps without reprocessing the participant EEG.

### Current Source Calculations

The normal source build is intentionally EEG-only and generates both current
methods. They use the same signed FIF derivatives, complete-case source cohort,
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

The independent volume inverse uses `method="eLORETA"`, a 10 mm fsaverage
volume grid, `loose=1.0`, `depth=None`, `fixed=False`, and `lambda2=1/9`. Its
current method identity is `eloreta_volume_hauk_source_psd_vector_norm_v1`.
It preserves complex exact-bin coefficients through a vector inverse rather
than accepting a basis-dependent scalar pooling of free orientations.
Because the Toolbox workflow does not require a separate resting/noise
recording, it builds MNE's ad-hoc diagonal EEG noise covariance. This is an
intentional Toolbox adaptation of the Hauk reference pipeline, which used a
recorded resting covariance, and must be reported with the inverse settings.

For each participant and condition, the producer:

1. loads the significant oddball harmonics already selected and saved for the
   project during post-processing. Under the default through-highest rule, an
   isolated highest detection is excluded from the selected list when more than
   10 eligible non-base harmonics lie strictly between it and the next-highest
   significant detection; base-rate overlaps do not count and exactly 10 is
   allowed;
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
loads a payload. Mesh, split-hemisphere, transparent-volume, and MRI-slice
choices change only the display of saved values.

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
- that the saved project significant-harmonic selection was reused, with the
  exact detected and selected harmonic frequencies, whether the isolated-highest
  gap guard was applied, its eligible-gap count, and any excluded upper peak;
- the EEG-only `fsaverage` BioSemi64 template limitation and the absence of
  individual MRI/coregistration, MEG, and modality fusion;
- the MNE version, cortical spacing, volume-grid spacing, each method's
  independent inverse settings, ad-hoc diagonal EEG noise covariance, and
  source settings;
- L2 `pick_ori="normal"` and square-root PSD amplitude conversion, plus eLORETA
  exact-bin complex periodic-Hann coefficients, `pick_ori="vector"`, and
  `sqrt(sum(abs(Cxyz)^2))` orientation pooling;
- the exact-bin/no-nearest-bin requirement;
- amplitude conversion, harmonic aggregation, offsets `-10..-2` and `+2..+10`,
  one global minimum/maximum removal, and population SD (`ddof=0`);
- participant exclusions, flagged-participant policy, group summary, and each
  method's source-space cluster inference, plus L2-MNE ROI/lateralization
  settings and every source-only complete-case omission and its reason; and
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
