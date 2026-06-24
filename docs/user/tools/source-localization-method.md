# Source Estimation

Use this page when you need to understand what the LORETA Visualizer's current
real-project source maps mean, how they are generated, and what limitations
apply.

## Quick summary

The source estimation tool builds two beta source-map families from the
project's frequency-domain FPVS EEG outputs:

- **L2-MNE surface maps**, the default cortical-surface method for
  publication-style split-hemisphere views.
- **eLORETA volume maps**, a beta template-volume method for transparent brain
  mesh and orthogonal MRI-slice inspection.

Both methods read the Stats-selected oddball harmonics, estimate each
participant's target and neighboring-bin activity, convert each participant's
source map into a source-space z-score, and then write group summaries of those
participant maps such as the raw mean, median, and 20% trimmed mean.

The cluster mask is the group-level statistical display mask for these maps. In
simple terms, it looks for connected source regions where participant
source-space z-scores are consistently positive, then tests whether a cluster
that strong would be expected by chance if participant signs were randomly
flipped. Clusters that survive the corrected group test are retained for the
publication-style display. This makes the masked view more robust than coloring
every high source point independently, but it is still limited by sample size,
participant outliers, the EEG-only template model, and the fact that the current
mask tests positive effects only.

## Current methods

The current real-project source-map path builds a default source-map set with:

- **beta Hauk-style L2-MNE cortical-surface source-space z-score** maps;
- **beta eLORETA volume source-space z-score** maps.

The L2-MNE surface method is modeled after the FPVS EEG/MEG
source-estimation approach described in Hauk et al. (2021) and Hauk et al.
(2025), where frequency-domain FPVS topographies are source-estimated with L2
minimum-norm estimation. The 2021 paper applies this to face-selective FPVS
responses, and the 2025 paper applies the same general approach to
word-selective FPVS responses.

Important limitation: this toolbox implementation is not a perfect reproduction
of those studies. The published studies used combined EEG/MEG recordings and
individual MRI/head models. The current toolbox path is EEG-only, uses
BioSemi64/fsaverage template source spaces, and is intended for beta method
review before scientific interpretation.

The current project Hauk-style path uses MNE-native L2-MNE inverse settings:
loose orientation `0.2`, no depth weighting, no dSPM/sLORETA/eLORETA noise
normalization, and `lambda2 = 1 / 9` for SNR = 3.

The beta eLORETA volume path uses MNE-Python's eLORETA inverse machinery on an
fsaverage/template volume source space. It follows the same participant-first
FPVS target/noise-bin z-score contract as the L2-MNE path, but the source
points are distributed through a 3D volume grid rather than on a cortical
surface. Treat this as a beta visualization and method-review output, not as
precise subject-specific deep-source localization.

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

## Shared calculation outline

For each method and condition:

1. Read the exact Stats-selected oddball harmonics.
2. For each included participant, read the 64-channel target topography at each
   selected harmonic.
3. For each included participant, read neighboring frequency-bin topographies
   around each selected harmonic.
4. Apply the method's inverse model to each participant target and
   neighboring-bin topography. L2-MNE uses `method="MNE"`, `loose=0.2`,
   `depth=None`, `fixed=False`, no depth weighting, no dSPM/sLORETA/eLORETA
   noise normalization, and `lambda2 = 1 / 9`. eLORETA volume maps use
   `method="eLORETA"` on the template volume source grid with method settings
   recorded in payload metadata and the validation report.
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
10. For L2-MNE surface maps, compute descriptive source-space lateralization
    summaries for each participant and group summary map, including the
    Hauk-style Desikan-Killiany temporal ROI. eLORETA volume maps do not yet
    write volume laterality or ROI summaries.
11. Write prepared group-summary source JSON payloads plus a manifest and a
    participant-level sidecar for future individual viewing.

The default neighboring-bin policy uses offsets `-10..-2` and `+2..+10`,
excluding the target bin and immediately adjacent bins. This mirrors the
project's FPVS neighboring-bin style while moving the correction into source
space.

The default viewer condition entries are group summaries of participant-level
source-space z-scores. The export writes raw mean, median, and 20% trimmed mean
summaries for each condition. The same participant-level maps are also used to
compute a positive-tail source-space cluster-permutation mask against zero. The
visualizer shows each condition once in the condition selector, then uses the
separate summary selector to choose raw mean, median, or 20% trimmed mean
z-score maps.

The normal **Source Map Options** rebuild path builds the participant-first
default method set: L2-MNE surface maps and eLORETA volume maps. The older
group-first beta producer, which averages target and neighboring-bin
topographies before source estimation, remains in the codebase only for
developer/method-review runs and is not exposed as a standard GUI rebuild
option.

## What the viewer displays

The generated JSON stores the full signed source-space z-score field. The
method selector chooses which loaded source-map family is shown. Conditions
remain grouped by method, and the summary selector chooses the raw mean,
median, or 20% trimmed mean group summary for the selected condition.

The default L2-MNE cortical-surface display uses an opaque publication-style
split view of the left and right fsaverage hemispheres and paints source-space
z-scores on those surfaces. The split view uses inflated fsaverage hemispheres
when they are available and topology-compatible with the pial/source surface,
which makes the cortex flatter and easier to inspect. The split view also uses
FreeSurfer `curv` gray-white shading when available, `sulc` as a fallback, and
a simple geometry-derived underlay if neither morph file is available. The same
payload can also be shown on a single pial surface or in the transparent mesh
view.

The default eLORETA volume display uses the transparent brain mesh. Volume
source points are smoothed into a display overlay inside the template brain
surface. eLORETA volume maps can also be shown as orthogonal MRI slices:
axial, coronal, and sagittal panels use a LORETA-visualizer-only 0.5 mm display
underlay derived from `fsaverage/mri/brain.mgz` and cached outside the source
tree under `.fpvs_cache`. The MRI underlay is for display/export only and does
not replace the fsaverage anatomy used by source producers or other toolbox
modules.
When the generated payload contains a source-space cluster mask, that mask is
the primary publication-style display: vertices outside significant clusters
are shown as shaded cortex rather than activation colors. Older unmasked
payloads fall back to the selected display threshold. The default cutoff is
`z >= 1.64`; Source Map Options > Display also offers `z >= 1.96`,
`z >= 2.58`, `z >= 3.29`, and `z >= 3.89` presets. Displayed values use the
same heatmap color scale as the transparent source-map view. For very small
participant counts, exact sign-flip permutation resolution can make the
minimum possible corrected p-value larger than the selected cluster alpha. In
that case, the visualizer warns that the cluster mask is underpowered, treats
the cortical render as not group-masked, and uses the selected exploratory
display threshold instead of showing an empty publication mask.

The color legend is in z-score units for these payloads. With auto-scaling on,
cluster-masked maps use the retained source z-score range. Manual color limits
change only the display scale; they do not change the generated source values
or statistical mask.

The paint projection is display-only interpolation from the prepared source
mesh to pial/source-space projection coordinates. In split-hemisphere view, the
same display-only projection is applied separately to the left and right
hemispheres, then drawn on the inflated display canvas with curvature/sulcal
underlay shading when available. It should be interpreted as a clearer
visualization of the same beta source map, not as extra spatial precision in
the source calculation.

The MRI slice projection is also display-only. The slice planes are chosen from
a standard eLORETA volume reference so changing conditions updates the overlay
while keeping the anatomical planes stable. The three-panel MRI figure export
writes matched PDF and PNG files for method review and beta figure drafts.

The display threshold is not the source-space cluster-permutation test. It is
kept for exploratory/unmasked payloads. For current regenerated
participant-first maps, the cluster mask is computed before rendering and saved
in the source JSON metadata. The renderer only obeys that prepared mask, except
when the saved empty mask is mathematically unable to reach the selected alpha
because of exact small-sample permutation resolution; that case is explicitly
labeled exploratory in the visualizer. You can also temporarily disable the
saved mask in **Source Map Options > Display** for exploratory viewing with the
selected z-score cutoff. This changes only the viewer and exported figure
appearance; it does not change the saved source values, cluster statistics, or
source-lateralization sidecars.

## Cluster-permutation mask

The cluster mask asks whether a connected source region is reliably positive
across participants. L2-MNE surface maps use fsaverage cortical-surface
adjacency. eLORETA volume maps use adjacency from the volume source grid.

The toolbox currently uses a one-sample, positive-tail sign-flip permutation
test:

- compute a one-sample t statistic against zero at each source vertex from the
  participant z-score maps;
- form positive candidate clusters from neighboring source vertices that pass
  the cluster-forming threshold;
- randomly flip participant signs to build a null distribution of the largest
  positive cluster mass expected by chance;
- keep clusters whose mass survives cluster-level correction.

Default settings are cluster-forming `p = 1e-5`, corrected cluster
`alpha = .05`, deterministic seed `20260609`, and up to `10000` sign-flip
permutations. For small participant counts, the exact available sign flips are
used. The resulting cluster p-value applies to the cluster as a whole, not to
each individual vertex inside the cluster.

## Source-space lateralization summary

The L2-MNE surface source-map builder also writes a descriptive lateralization
summary. This is a source-space companion to the sensor-space BCA lateralization
tests. It does not replace those BCA tests. The beta eLORETA volume builder does
not yet write volume ROI or lateralization summaries.

In simple terms, the summary asks:

`How much positive source activation is on the right side of the cortical source surface compared with the left side?`

The main source lateralization index is:

`(Right source activation - Left source activation) / (Right source activation + Left source activation)`

Interpretation:

- Positive values mean the source map is more right-lateralized.
- Negative values mean the source map is more left-lateralized.
- Values near zero mean the source map is roughly balanced.

For current cluster-masked participant-first L2-MNE maps, the summary uses the
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
estimated from condition-specific frequency-domain EEG topographies using
fsaverage-template source spaces. The default L2-MNE surface method uses
MNE-native L2 minimum-norm estimation on a cortical surface (`method="MNE"`,
loose orientation `0.2`, no depth weighting, no dSPM/sLORETA/eLORETA noise
normalization, `lambda2 = 1 / 9`). The beta eLORETA volume method uses
MNE-native eLORETA estimation on an fsaverage/template volume source grid. For
each included participant and method, target oddball harmonic topographies and
neighboring-bin topographies are projected through the same inverse model.
Source estimates are summed across the Stats-selected significant oddball
harmonics, then each source point is converted to a z-score relative to
neighboring-bin source activity after excluding the minimum and maximum
neighboring values. Participant z-score maps are combined into group raw mean,
median, and 20% trimmed-mean maps. Publication-style displays use a one-sample
positive-tail source-space sign-flip cluster-permutation mask against zero with
a cluster-forming threshold of `p = 1e-5`, corrected cluster `alpha = .05`, and
up to 10,000 permutations. For L2-MNE surface maps, source-space laterality is
summarized descriptively by collapsing positive cluster-masked z-score
magnitudes within the fsaverage Desikan-Killiany inferior, middle, and superior
temporal labels in the left and right hemispheres and computing
`(Right - Left) / (Right + Left)`, where positive values indicate greater
right-hemisphere source activation.

## What this method is not

These methods are not:

- final validated LORETA, eLORETA, sLORETA, or deep-volume workflows;
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

The default L2-MNE surface output folder is:

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

The builder also writes a project-local validation report:

`source_validation_report.md`

and:

`source_validation_report.json`

The Markdown report is meant for quick review. It summarizes the manifest,
payload validation status, selected harmonics, cluster-mask availability,
Desikan-Killiany temporal lateralization highlights, generated files, beta
limitations, and recommended manual checks. The JSON report carries the same
information in a machine-readable form for later validation tooling.

The visualizer automatically loads this manifest when it is present. If it is
missing and the required FullFFT data are available, the visualizer can build it
in the background.

The default eLORETA volume output folder is:

`6 - Source Localization/eLORETA Volume Beta/`

The main manifest is:

`project_eloreta_volume_hauk_zscore_beta_manifest.json`

The manifest contains one group-summary entry per condition and aggregation:
raw mean, median, and 20% trimmed mean participant z-score maps. The same
folder also contains:

`participant_eloreta_volume_hauk_zscore_maps.json`

That sidecar stores participant-level eLORETA volume z-score maps for future
individual-viewer support. The eLORETA folder also receives
`source_validation_report.md` and `source_validation_report.json`, including
method settings, source-grid details, payload validation, cluster-mask
coverage, generated files, beta limitations, and recommended manual checks.

When the LORETA Visualizer prepares missing default project maps, it builds the
L2-MNE surface and eLORETA volume manifests together. The method selector then
chooses which already-loaded source-map family is displayed.

The diagnostic arbitrary-amplitude exporter writes to:

`6 - Source Localization/L2-MNE Cortical Surface Beta/`

It remains available as a developer/method-review producer, but it is no longer
exposed as a normal Source Map Options rebuild action. The default project
display is the Hauk-style z-score manifest above.
