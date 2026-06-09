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

The current project Hauk-style path uses MNE-native L2-MNE inverse settings:
loose orientation `0.2`, no depth weighting, no dSPM/sLORETA/eLORETA noise
normalization, and `lambda2 = 1 / 9` for SNR = 3.

## References

- Hauk et al. (2021), *Face-selective responses in combined EEG/MEG recordings
  with fast periodic visual stimulation (FPVS)*, NeuroImage, 242, 118460.
  DOI: [10.1016/j.neuroimage.2021.118460](https://doi.org/10.1016/j.neuroimage.2021.118460)
- Hauk et al. (2025), *Word-selective EEG/MEG responses in the English language
  obtained with fast periodic visual stimulation (FPVS)*, Imaging Neuroscience,
  3, imag_a_00414.
  DOI: [10.1162/imag_a_00414](https://doi.org/10.1162/imag_a_00414)
- FreeSurfer Desikan-Killiany cortical parcellation reference:
  [CorticalParcellation](https://surfer.nmr.mgh.harvard.edu/fswiki/CorticalParcellation)

## Inputs

The source-map builder reads existing project outputs. It does not rerun
preprocessing or change Stats behavior.

Required inputs:

- `Stats_Ready_Summed_BCA.xlsx`, exported from the Stats tool, for the
  project-wide selected oddball harmonic list.
- Per-participant condition workbooks under `1 - Excel Data Files/<Condition>/`
  or `1 - Excel Data Files/<Condition>/<Group>/`.
- The `FullFFT Amplitude (uV)` sheet in those workbooks, including target
  harmonic bins and neighboring frequency bins.
- The existing participant QC files:
  `Excluded Participants.xlsx` and `Flagged Participants.xlsx`.

If these files are missing, re-run preprocessing for the project, then open
Stats and run **Export Stats-Ready Workbook** before building source maps. The
z-score workflow requires the raw FullFFT target and neighboring bins; it stops
with an input error rather than deriving source z-scores from BCA-only summary
workbooks.

Excluded participants are always skipped. Participants listed in
`Flagged Participants.xlsx` are excluded by default for source-map generation.
The LORETA Visualizer's **Source Map Options** dialog can include flagged
participants for QC comparison.

## Calculation outline

For each condition:

1. Read the exact Stats-selected oddball harmonics.
2. For each included participant, read the 64-channel target topography at each
   selected harmonic.
3. For each included participant, read neighboring frequency-bin topographies
   around each selected harmonic.
4. Apply the same MNE-native L2-MNE inverse model to each participant target
   and neighboring-bin topography. The current settings are `method="MNE"`,
   `loose=0.2`, `depth=None`, `fixed=False`, no depth weighting, no
   dSPM/sLORETA/eLORETA noise normalization, and `lambda2 = 1 / 9`.
5. For each participant, sum source estimates across the selected significant
   harmonics.
6. For each participant and source point, compute a neighboring-bin baseline
   mean and population standard deviation after dropping the minimum and
   maximum neighboring source amplitudes.
7. For each participant, compute a source-space z-score:
   `(target source amplitude - neighboring-bin mean) / neighboring-bin SD`.
8. Combine participant source-space z-score maps into group summaries.
9. Compute a source-space cluster-permutation mask from participant z-score
   maps.
10. Compute descriptive source-space lateralization summaries for each
    participant and group summary map, including the Hauk-style
    Desikan-Killiany temporal ROI.
11. Write prepared group-summary source JSON payloads plus a manifest and a
   participant-level sidecar for future individual viewing.

The default neighboring-bin policy uses offsets `-10..-2` and `+2..+10`,
excluding the target bin and immediately adjacent bins. This mirrors the
project's FPVS neighboring-bin style while moving the correction into source
space.

The default viewer condition entries are group summaries of participant-level
source-space z-scores. The export writes raw mean, median, and 20% trimmed mean
summaries for each condition. The same participant-level maps are also used to
compute a one-sided positive source-space cluster-permutation mask against
zero. The visualizer loads the raw mean entries by default when the manifest
order is unchanged, and the other summaries are available from the condition
selector.

Source Map Options can still build the older group-first beta model for
comparison. That deprecated model averages target and neighboring-bin
topographies before source estimation. It is retained only as an advanced
fallback and is intended to be removed after participant-first maps are
validated.

## What the viewer displays

The generated JSON stores the full signed source-space z-score field. The
default cortical-surface display uses an opaque publication-style split view of
the left and right fsaverage hemispheres and paints source-space z-scores on
those surfaces. The split view uses inflated fsaverage hemispheres when they
are available and topology-compatible with the pial/source surface, which makes
the cortex flatter and easier to inspect. The split view also uses FreeSurfer
`curv` gray-white shading when available, `sulc` as a fallback, and a simple
geometry-derived underlay if neither morph file is available. The same payload
can also be shown on a single pial surface or in the transparent mesh view.
When the generated payload contains a source-space cluster mask, that mask is
the primary publication-style display: vertices outside significant clusters
are shown as shaded cortex rather than activation colors. Older unmasked
payloads fall back to the selected display threshold. The default cutoff is
`z >= 1.64`; Source Map Options > Display also offers `z >= 1.96`,
`z >= 2.58`, `z >= 3.29`, and `z >= 3.89` presets. Displayed values use the
same heatmap color scale as the transparent source-map view.

The color legend is in z-score units for these payloads. With auto-scaling on,
cluster-masked maps use `0` as the lower color bound and the largest retained
positive z-score in the current condition as the upper bound. Manual color
limits change only the display scale; they do not change the generated source
values or statistical mask.

The paint projection is display-only interpolation from the prepared source
mesh to pial/source-space projection coordinates. In split-hemisphere view, the
same display-only projection is applied separately to the left and right
hemispheres, then drawn on the inflated display canvas with curvature/sulcal
underlay shading when available. It should be interpreted as a clearer
visualization of the same beta source map, not as extra spatial precision in
the source calculation.

The display threshold is not the source-space cluster-permutation test. It is
kept for exploratory/unmasked payloads. For current regenerated
participant-first maps, the cluster mask is computed before rendering and saved
in the source JSON metadata. The renderer only obeys that prepared mask.

## Cluster-permutation mask

The cluster mask asks whether a connected region of the fsaverage cortical
source surface is reliably above zero across participants.

The toolbox currently uses a one-sample, positive-tail sign-flip permutation
test:

- compute a one-sample t statistic against zero at each source vertex from the
  participant z-score maps;
- form candidate clusters from neighboring source vertices that pass the
  cluster-forming threshold;
- randomly flip participant signs to build a null distribution of the largest
  cluster mass expected by chance;
- keep clusters whose mass survives cluster-level correction.

Default settings are cluster-forming `p = .05`, corrected cluster
`alpha = .05`, deterministic seed `20260609`, and up to `2048` sign-flip
permutations. For small participant counts, the exact available sign flips are
used. The resulting cluster p-value applies to the cluster as a whole, not to
each individual vertex inside the cluster.

## Source-space lateralization summary

The source-map builder also writes a descriptive lateralization summary. This
is a source-space companion to the sensor-space BCA lateralization tests. It
does not replace those BCA tests.

In simple terms, the summary asks:

`How much positive source activation is on the right side of the cortical source surface compared with the left side?`

The main source lateralization index is:

`(Right source activation - Left source activation) / (Right source activation + Left source activation)`

Interpretation:

- Positive values mean the source map is more right-lateralized.
- Negative values mean the source map is more left-lateralized.
- Values near zero mean the source map is roughly balanced.

For current cluster-masked participant-first maps, the summary uses the
producer's source-space cluster mask first, then sums positive z-score
magnitudes within left and right source vertices. Vertices outside the
significant source cluster are not counted. If an older unmasked payload is
summarized, the fallback is positive z-score source values.

The primary Hauk-style source-lateralization ROI is:

- `desikan_killiany_temporal_hauk`: the FreeSurfer/fsaverage
  Desikan-Killiany `aparc` temporal labels used for the Hauk-style check:
  `inferiortemporal`, `middletemporal`, and `superiortemporal`, combined
  separately in the left and right hemispheres.

The project exporter preserves the MNE/fsaverage source-space vertex IDs and
hemisphere labels, reads the fsaverage `aparc` annotation, maps those label
vertices onto the current source mesh, and then collapses positive
cluster-masked source z-score magnitudes within the left and right temporal
ROIs. This follows the Hauk-style idea of collapsing z-scores across most of
the temporal lobe, while still using this toolbox's EEG-only fsaverage-template
model.

The summary also writes two QC/fallback ROI scopes:

- `whole_hemisphere`: all source vertices split by source-space x coordinate.
- `occipitotemporal_lot_rot`: the earlier approximate LOT/ROT source ROI using
  posterior lateral occipito-temporal source coordinates:
  `abs(x) >= 20 mm`, `y <= -35 mm`, and `z <= 35 mm`.

For the coordinate-defined fallback scopes, x < 0 is left, x > 0 is right, and
midline source points are ignored. Prefer the Desikan-Killiany temporal ROI for
Hauk-style source-space laterality reporting; use coordinate LOT/ROT rows only
as a transparent QC comparison.

This is a descriptive source-estimate check, not a formal source-space
lateralization statistical test.

## Methods summary for reporting

For the current beta source-localization workflow, FPVS source maps are
estimated from condition-specific frequency-domain EEG topographies using an
fsaverage-template cortical surface and MNE-native L2 minimum-norm estimation
(`method="MNE"`, loose orientation `0.2`, no depth weighting, no
dSPM/sLORETA/eLORETA noise normalization, `lambda2 = 1 / 9`). For each
included participant, target oddball harmonic topographies and neighboring-bin
topographies are projected through the same inverse model. Source estimates
are summed across the Stats-selected significant oddball harmonics, then each
source vertex is converted to a z-score relative to neighboring-bin source
activity after excluding the minimum and maximum neighboring values.
Participant z-score maps are combined into group raw mean, median, and 20%
trimmed-mean maps. Publication-style displays use a one-sample positive-tail
source-space sign-flip cluster-permutation mask against zero. Source-space
laterality is summarized descriptively by collapsing positive cluster-masked
z-score magnitudes within the fsaverage Desikan-Killiany inferior, middle, and
superior temporal labels in the left and right hemispheres and computing
`(Right - Left) / (Right + Left)`, where positive values indicate greater
right-hemisphere source activation.

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

The manifest contains one group-summary entry per condition and aggregation:
raw mean, median, and 20% trimmed mean participant z-score maps. The same
folder also contains:

`participant_l2_mne_hauk_zscore_maps.json`

That sidecar stores participant-level z-score maps for future individual-viewer
support. The current viewer loads the group-summary payloads, not the sidecar.

The source-map builder also writes:

`source_lateralization_summary.csv`

and:

`source_lateralization_summary.json`

These files summarize left/right source activation for each condition,
participant, and group-summary map. A positive lateralization index means the
source estimate is more right-lateralized; a negative index means it is more
left-lateralized.

The visualizer automatically loads this manifest when it is present. If it is
missing and the required FullFFT data are available, the visualizer can build it
in the background.

The diagnostic arbitrary-amplitude exporter writes to:

`6 - Source Localization/L2-MNE Cortical Surface Beta/`

It is available from Source Map Options for method review, but the default
project display is the Hauk-style z-score manifest above.
