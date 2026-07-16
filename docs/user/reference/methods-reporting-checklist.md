# Reporting the Hauk-Informed Source-PSD Workflow

This page describes the current Option 1 source-localization workflow in FPVS
Toolbox. It prepares signed time-domain EEG during normal processing and later
uses MNE to estimate independent L2 minimum-norm cortical and eLORETA volume
source power spectra. The current method identifiers are
`l2_mne_hauk_source_psd_v1` and `eloreta_volume_hauk_source_psd_v1`.

The workflow is informed by the source-spectrum approach used by Hauk et al.
(2021) and by the public
[`olafhauk/FPVS_sweep`](https://github.com/olafhauk/FPVS_sweep) scripts. It is a
documented FPVS Toolbox adaptation, not a claim that the Toolbox exactly
reproduces that study's combined EEG/MEG, individual-MRI, preprocessing, or
neighboring-bin pipeline.

## Processing-Time Derivative

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

## Current Source Calculations

The normal source build is intentionally EEG-only and generates both methods.
They use the same signed FIF derivatives, complete-case source cohort, saved
oddball harmonics, exact FPVS frequency bins, and neighboring-bin z-score
algorithm. They do not share source values: each inverse produces and caches
its own participant source-power and z-score arrays.

Both methods use the Toolbox
BioSemi64 channel geometry with the `fsaverage` template rather than individual
MRI/coregistration, MEG, or EEG/MEG fusion. The cortical inverse is MNE-native
L2-MNE with `method="MNE"`, `loose=0.2`, `depth=None`, `fixed=False`, and
`lambda2=1/9`; it does not apply dSPM, sLORETA, or eLORETA normalization. The
independent volume inverse uses `method="eLORETA"`, a 10 mm fsaverage volume
grid, `loose=1.0`, `depth=None`, `fixed=False`, and `lambda2=1/9`.
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
3. calls MNE's `mne.minimum_norm.compute_source_psd` independently for each
   method on the complete
   repetition-averaged Raw time series, using `n_fft=N`, zero overlap, the Hann
   setting, and the method's own L2-MNE cortical or eLORETA volume inverse;
4. validates nonnegative source power and takes its square root to obtain source
   amplitude;
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
array is never transformed or relabeled as eLORETA.

For projects with more than one canonical participant group, the Toolbox
creates a separate source summary and cluster-inference input for each group and
condition. It does not silently pool experimental groups into one source map.
Single-group and ungrouped projects retain the condition labels used elsewhere
in the project.

## Toolbox Neighboring-Bin Rule

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

## Legacy And Deferred Paths

Existing amplitude-derived L2-MNE Hauk z-score and eLORETA prepared manifests
remain importable in the visualizer and are labeled legacy/exploratory. They do
not serve as fallback inputs for either current source-PSD workflow. Normal
manual and post-processing rebuilds create both time-domain methods. MEG
fusion, individual-MRI modeling, and the phase-preserving complex-Fourier
Option 2 remain possible later additions, not current behavior.

## Manuscript Or Preregistration Checklist

Report at least:

- the FPVS Toolbox release or commit and both method identifiers,
  `l2_mne_hauk_source_psd_v1` and
  `eloreta_volume_hauk_source_psd_v1`;
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
  source-PSD settings;
- the exact-bin/no-nearest-bin requirement;
- amplitude conversion, harmonic aggregation, offsets `-10..-2` and `+2..+10`,
  one global minimum/maximum removal, and population SD (`ddof=0`);
- participant exclusions, flagged-participant policy, group summary, and each
  method's source-space cluster inference, plus L2-MNE ROI/lateralization
  settings and every source-only complete-case omission and its reason; and
- that the method was Hauk-informed but Toolbox-adapted, citing both the study
  and public code reference below.

Retain the source-ready FIF/JSON pairs, participant commit manifests, harmonic
selection record, and prepared source-output manifest with the analysis record.
Together they provide the provenance needed to audit the source figures.

## References

- Hauk, O., Rice, G. E., Volfart, A., Magnabosco, F., Lambon Ralph, M. A., &
  Rossion, B. (2021). [Face-selective responses in combined EEG/MEG recordings
  with fast periodic visual stimulation
  (FPVS)](https://doi.org/10.1016/j.neuroimage.2021.118460). *NeuroImage, 242*,
  118460.
- Hauk, O. [`olafhauk/FPVS_sweep`: Python scripts for an FPVS frequency-sweep
  experiment](https://github.com/olafhauk/FPVS_sweep), including the public
  `FPVS_PSD_Source_sweep.py` source-spectrum script.
