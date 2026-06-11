# LORETA Visualizer

Use this page when you want to inspect the experimental 3D LORETA/source
visualization tool.

The LORETA Visualizer opens from the main app sidebar as **LORETA Visualizer**.
The first time you open it in an app session, FPVS Toolbox shows a beta warning
that must be acknowledged before the workspace switches to the visualizer. Its
current implementation is an experimental visualization and beta source-map
viewer: it renders a brain mesh, synthetic source maps, prepared JSON payloads,
and early real-project cortical L2-MNE maps.

## Current status

The embedded visualizer can now display real project data through beta
Hauk-style L2-MNE cortical-surface source-space z-score maps. This is an early
method-validation path, not a final validated LORETA, eLORETA, sLORETA,
deep-source, or subject-MRI workflow.

For details about the current source-localization method, assumptions,
citations, z-score calculation, and participant QC behavior, see
[Source Localization Method](source-localization-method.md).

The visible occipital, frontal, and deep medial temporal demo activations are
still synthetic. The real-project path is separate: it reads existing project
workbooks, uses the oddball harmonic list exported by the Stats tool, builds a
template BioSemi64/fsaverage cortical forward model through MNE, writes
prepared z-score source JSON files when needed, and loads them through the same
manifest importer used by the demo fixtures.

Use the current version to verify rendering behavior, camera controls, color
scaling, and whether source maps can be drawn in the intended mode. Current
L2-MNE cortical-surface project maps default to an opaque publication-style
split-hemisphere cortical paint view. The split view uses fsaverage inflated
hemispheres when available so the cortical map is flatter and easier to read.
It also uses FreeSurfer curvature/sulcal gray-white shading when available to
make folds and surface depth easier to interpret.
Volume, ROI, and deep-style maps keep the transparent anatomical shell
behavior.

## What you can do now

- Rotate the 3D scene by dragging in the viewport.
- Zoom with mouse or trackpad interaction.
- Switch between publication split hemispheres, a single fsaverage cortical
  surface, and the transparent brain mesh view.
- Rotate the left and right hemispheres independently in the publication split
  view.
- Reset the camera, and in publication split view reset both hemispheres to the
  intended publication layout.
- Adjust brain transparency for transparent-shell volume/deep views.
- Use an fsaverage mesh loaded through MNE from the toolbox cache or a
  configured subjects directory, with synthetic fallback when the mesh is
  unavailable.
- Show or hide the source map independently from the brain mesh.
- Adjust source-map opacity for transparent overlay views.
- Switch among project source-map conditions when available, or synthetic
  demonstration conditions otherwise.
- Auto-scale the source intensity map or set manual minimum/maximum intensity
  bounds.
- Read the source color scale from the control-panel color ramp and min/max
  labels.
- Open **Export Figures** to export the current publication split-hemisphere
  SVG or launch the condition-stack SVG export. Future figure exports for other
  displays will live in the same dialog.
- Open **Source Map Options** to rebuild project maps with Stats/QC-flagged
  participants excluded by default or explicitly included for comparison, load a
  prepared source payload JSON file, load a prepared source manifest, or choose
  the deprecated group-first z-score model for comparison.
- Use checked-in example payload and manifest JSON files as references for the
  expected future calculation output shape.

Higher synthetic values are mapped toward red. Lower values appear lighter or
less intense depending on the current color range.

For beta L2-MNE project maps, the color scale shows the actual scalar range
used for the current source map. When auto-scale is on, the min/max labels
update from the loaded payload values after cortical paint masking. For
regenerated participant-first maps, the primary mask is the producer-computed
source-space cluster-permutation mask. Older unmasked maps fall back to the
selected display cutoff. Hidden vertices are shown as the neutral gray cortex
color.

## Inputs

The fsaverage brain mesh is loaded through MNE from the FPVS Toolbox root-local
cache by default:

`C:\...\FPVS-Toolbox-Repo\.fpvs_cache\mne\MNE-fsaverage-data\fsaverage`

MNE may still stage downloaded zip files in the Windows temporary directory
while extracting them, but the durable fsaverage install is under
`.fpvs_cache`. The toolbox does not store fsaverage MRI template data in the
source tree, docs tree, quarantine tree, package data, or project folders.
If an old generic MNE subjects-dir setting points into `src` or `docs`, the
visualizer ignores that unsafe candidate and uses the toolbox cache instead.
An explicit `FPVS_FSAVERAGE_SUBJECTS_DIR` override must point to another
untracked subjects directory.

Checked-in JSON examples live in
`src/Tools/LORETA_Visualizer/examples/`. These are synthetic examples for
format validation and manual importer checks; they are not real source maps.

The beta L2-MNE producer can generate a source-ready fixture manifest into a
local output folder. Those fixture files are useful for checking that the
producer writes the same prepared JSON format the visualizer already imports.

For real project inputs, first process the project, then open the Stats tool and
run **Export Stats-Ready Workbook**. The source-ready assemblers read the
selected harmonics from
`3 - Statistical Analysis Results/Stats_Ready_Summed_BCA.xlsx` and
per-participant Excel outputs under `1 - Excel Data Files`. Workbooks may be
directly inside each condition folder or inside condition/group subfolders.

The default Hauk-style z-score exporter requires each included participant
workbook to contain a `FullFFT Amplitude (uV)` sheet with the exact selected
harmonic columns and neighboring frequency bins. Its project-local output is:

`6 - Source Localization/L2-MNE Hauk Z-Score Beta/`

The main file loaded by default is:

`project_l2_mne_hauk_zscore_beta_manifest.json`

That manifest contains participant-first source-space z-score group summaries:
raw mean, median, and 20% trimmed mean entries for each condition. The same
folder also stores `participant_l2_mne_hauk_zscore_maps.json`, a participant
sidecar reserved for future individual-viewer support.

Each project rebuild also writes `source_validation_report.md` and
`source_validation_report.json` in the same folder. Use the Markdown report as
the quick review artifact for payload validation status, cluster-mask coverage,
source lateralization highlights, beta limitations, and the manual comparison
checks that should be completed before treating maps as validated.

The older 6C diagnostic amplitude exporter remains available in Source Map
Options and writes project-local output under:

`6 - Source Localization/L2-MNE Cortical Surface Beta/`

The main file to load manually is:

`project_l2_mne_cortical_surface_beta_manifest.json`

The source JSON and manifest load actions live in **Source Map Options**. Their
dialogs start in the last import folder when possible. Otherwise, they open to
the active project's source-map output folder when it exists, then the active
project root.

## Interpreting the demo maps

Treat synthetic demo activations as rendering tests only. Beta project source
maps are estimated from project EEG-derived topographies, but they are still
exploratory and should not be used as final reportable source-localization
results until the method is validated for your study.

The deep medial temporal demo shows that the renderer can display a smooth
internal 3D source blob inside the transparent brain. It is not a hippocampal
source-localization result.

The prepared source-map fixture is shaped like a future real-data handoff with
coordinates, scalar values, faces, source-model metadata, and coordinate-space
conversion. It is still synthetic and should be used only to inspect rendering.

When the tool opens inside a project, it automatically prepares fsaverage and
then prefers the project-local Hauk-style source-space z-score manifest. If the
manifest is missing and the required `FullFFT Amplitude (uV)` target/noise-bin
data are present, the tool builds the z-score source maps in the background and
loads the generated manifest.

If the project has not been reprocessed or the Stats-ready workbook has not
been exported, the visualizer cannot build project source maps. Re-run
preprocessing for the project, then open Stats and run **Export Stats-Ready
Workbook** before returning to the LORETA Visualizer. If FullFFT sheets or exact
selected-frequency columns are missing, the z-score path stops instead of
fabricating source z-scores from BCA-only summaries.

Source Map Options can still load a controlled prepared-payload JSON file or a
prepared source manifest manually. Manual payloads need points, values,
optional triangle faces, a source-model label, metadata, and a coordinate-space
label. The tool validates the file and converts coordinates into the current
display mesh space before rendering.

## Prepared source JSON format

Future LORETA/source-localization calculation code should output a prepared
source payload JSON object rather than talking directly to the renderer.

Payload files use this v1 shape:

- `format`: `fpvs-loreta-source-payload-v1`
- `label`: display label for the source map
- `kind`: source display type, such as `volume_mesh`
- `coordinate_space`: coordinate-space label, such as `fsaverage_surface` or
  `normalized_display`
- `source_model`: upstream method or model label
- `value_label`: scalar value label
- `points`: finite `N x 3` coordinates
- `values`: finite scalar values with one value per point
- `faces`: optional triangle rows for mesh payloads
- `metadata`: optional provenance and notes

The most useful template for future fsaverage-aligned calculations is
`src/Tools/LORETA_Visualizer/examples/source_payload_v1_fsaverage_native_example.json`.
The importer converts that coordinate space into renderer display space through
the visualizer helper layer.

Manifest files use `fpvs-loreta-source-manifest-v1` and list condition entries
with `id`, `label`, relative `file`, and optional `metadata`. See
`src/Tools/LORETA_Visualizer/examples/source_manifest_v1_display_conditions_example.json`.

The examples directory also includes shape-level JSON Schema files:

- `source_payload_v1.schema.json`
- `source_manifest_v1.schema.json`

For future calculation code, the stricter in-repo validator is
`Tools.LORETA_Visualizer.prepared_payload_validator`. It can check payload and
manifest JSON before the files are loaded into the GUI. The validator catches
cross-field issues such as mismatched point/value counts, invalid face indices,
duplicate manifest condition ids, and manifest paths that escape the manifest
folder.

## Future real-data direction

Future source-localization calculations should be implemented separately from
the renderer. A calculation step will need to produce coordinates, scalar
values, source-model metadata, and a coordinate-space label. The visualizer's
helper layer will then adapt that prepared payload into the 3D renderer.

This separation lets the visualization support different future source methods
without hard-coding one calculation pipeline into the display layer.

The first calculation direction is a beta L2-MNE cortical-surface method for
FPVS oddball-response maps. That method is intended for fsaverage cortical
surface source maps, not deep volume localization. It produces the same
prepared JSON payload shape as the current examples, so a later LORETA,
eLORETA, or mixed volume method can be added as a different calculation method
without changing how the 3D renderer works.

The current real-data path is cortical-surface only and uses a template
fsaverage model. Hauk-style L2-MNE source-space z-score maps are the default
project view. This mode reads raw `FullFFT Amplitude (uV)` target and
neighboring frequency bins for each included participant, sends each
participant's target and noise topographies through the same inverse model,
computes participant source-space z-score maps, and then displays group raw
mean, median, or 20% trimmed mean z-score summaries.

By default, z-score maps use an opaque cortical paint view in the
publication-style split-hemisphere layout. That split layout uses inflated
fsaverage hemispheres when they are available and topology-compatible with the
pial/source surface; otherwise it falls back to pial split hemispheres. It uses
FreeSurfer `curv` shading when available, `sulc` as a fallback, and a simple
geometry-derived underlay if neither file is available. The same payload can
also be shown on a single fsaverage pial surface or in the transparent mesh
view. The signed z-score payload is still preserved in the generated JSON for
QC. Regenerated participant-first payloads include a source-space
two-tailed cluster-permutation mask, and opaque cortical paint mode uses that
mask as the primary publication-style display. Source vertices outside
significant clusters show the gray-white shaded cortex rather than activation
colors. Significant positive and negative retained source z-scores can both be
painted. Older unmasked payloads fall back to the selected display threshold.
The default threshold is `z >= 1.64`. Source Map Options > Display provides
preset cutoffs for `z >= 1.64`, `z >= 1.96`, `z >= 2.58`, `z >= 3.29`, and
`z >= 3.89`. Values retained by either the cluster mask or fallback cutoff are
painted on top with the same heatmap color ramp used by the transparent
visualizer.

The threshold is a display mask only. The cluster-permutation mask is the
statistical mask for current participant-first Hauk-style L2-MNE maps, and it
is computed by the source producer before rendering.

The cortical paint projection is display-only interpolation from the prepared
source mesh onto pial/source-space projection coordinates. In the split
publication view, the resulting display values are drawn on the inflated
hemisphere canvas when available. This does not improve or change the
underlying source-estimation precision.

The older arbitrary-amplitude L2-MNE cortical-surface export remains available
in Source Map Options as a diagnostic action. Those values are
arbitrary/template-scaled source amplitudes proportional to the sensor
topographies used as input
(`summed BCA uV` by default). They are not calibrated current density, dipole
moment, or microvolts at the source.

The z-score mode is better aligned with FPVS source-localization publications,
but it is still a beta template-based workflow. It is EEG-only, uses fsaverage
instead of individual MRIs, and is intended for method review before treating
the maps as analysis-ready.
