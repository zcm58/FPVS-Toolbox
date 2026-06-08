# Source Localization Method

Use this page when you need to understand what the LORETA Visualizer's current
real-project source maps mean, how they are generated, and what limitations
apply.

## Current method

The current real-project source-map path is a **beta Hauk-style L2-MNE
cortical-surface source-space z-score** workflow.

It is modeled after the FPVS EEG/MEG source-estimation approach described in
Hauk et al. (2021) and Hauk et al. (2025), where frequency-domain FPVS
topographies are source-estimated with L2 minimum-norm estimation. The 2021
paper applies this to face-selective FPVS responses, and the 2025 paper applies
the same general approach to word-selective FPVS responses.

Important limitation: this toolbox implementation is not a perfect reproduction
of those studies. The published studies used combined EEG/MEG recordings and
individual MRI/head models. The current toolbox path is EEG-only, uses a
BioSemi64/fsaverage template cortical surface, and is intended for beta method
review before scientific interpretation.

## References

- Hauk et al. (2021), *Face-selective responses in combined EEG/MEG recordings
  with fast periodic visual stimulation (FPVS)*, NeuroImage, 242, 118460.
  DOI: [10.1016/j.neuroimage.2021.118460](https://doi.org/10.1016/j.neuroimage.2021.118460)
- Hauk et al. (2025), *Word-selective EEG/MEG responses in the English language
  obtained with fast periodic visual stimulation (FPVS)*, Imaging Neuroscience,
  3, imag_a_00414.
  DOI: [10.1162/imag_a_00414](https://doi.org/10.1162/imag_a_00414)

## Inputs

The source-map builder reads existing project outputs. It does not rerun
preprocessing or change Stats behavior.

Required inputs:

- `Stats_Ready_Summed_BCA.xlsx`, for the project-wide selected oddball
  harmonic list.
- Per-participant condition workbooks under `1 - Excel Data Files/<Condition>/`.
- The `FullFFT Amplitude (uV)` sheet in those workbooks, including target
  harmonic bins and neighboring frequency bins.
- The existing participant QC files:
  `Excluded Participants.xlsx` and `Flagged Participants.xlsx`.

Excluded participants are always skipped. Participants listed in
`Flagged Participants.xlsx` are excluded by default for source-map generation.
The LORETA Visualizer's **Source Map Options** dialog can include flagged
participants for QC comparison.

## Calculation outline

For each condition:

1. Read the exact Stats-selected oddball harmonics.
2. Read the 64-channel target topography at each selected harmonic.
3. Read neighboring frequency-bin topographies around each selected harmonic.
4. Average included participants at each target and neighboring bin.
5. Sum target topographies across selected harmonics.
6. Sum matching-offset neighboring-bin topographies across selected harmonics.
7. Apply the same L2-MNE inverse model to the summed target topography and each
   summed neighboring-bin topography.
8. For each source point, compute a neighboring-bin baseline mean and population
   standard deviation after dropping the minimum and maximum neighboring source
   amplitudes.
9. Compute a source-space z-score:
   `(target source amplitude - neighboring-bin mean) / neighboring-bin SD`.
10. Write one prepared source JSON payload per condition plus a manifest.

The default neighboring-bin policy uses offsets `-10..-2` and `+2..+10`,
excluding the target bin and immediately adjacent bins. This mirrors the
project's FPVS neighboring-bin style while moving the correction into source
space.

## What the viewer displays

The generated JSON stores the full signed source-space z-score field. The
default activation view displays only positive z-scores (`z > 0`) so the map
focuses on above-baseline source estimates.

The color legend is in z-score units for these payloads. With auto-scaling on,
the upper color limit is the largest displayed positive z-score in the current
condition. Manual color limits change only the display scale; they do not
change the generated source values.

## What this method is not

This method is not:

- eLORETA, sLORETA, or a deep-volume LORETA solution;
- a subject-specific MRI/head-model workflow;
- calibrated current density, dipole moment, or microvolts at the source;
- a renderer calculation;
- a replacement for method validation.

The renderer only displays prepared source payloads. Source estimation happens
in the visualizer's `source_producers` modules, and future methods should be
added as sibling producers that emit the same prepared JSON/manifest contract.

## Participant QC and outliers

The source-map rebuild options follow the same practical distinction used by
the Stats tool:

- **Excluded participants** are excluded from source-map generation.
- **Flagged participants** are excluded by default.
- Check **Include Stats QC flagged participants in source-map calculations** to
  regenerate maps with flagged participants included.

The generated payload metadata records whether flagged participants were
included, which participants were flagged, which participants were excluded,
and the project-input diagnostics used for the build. The app also writes a
compact start/completion line to the IDE log when source maps are rebuilt.

## Output files

The default project-local output folder is:

`6 - Source Localization/L2-MNE Hauk Z-Score Beta/`

The main manifest is:

`project_l2_mne_hauk_zscore_beta_manifest.json`

The visualizer automatically loads this manifest when it is present. If it is
missing and the required FullFFT data are available, the visualizer can build it
in the background.
