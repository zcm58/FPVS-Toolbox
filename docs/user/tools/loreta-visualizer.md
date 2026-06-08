# LORETA Visualizer

Use this page when you want to inspect the experimental 3D LORETA/source
visualization tool.

The LORETA Visualizer opens from the main app sidebar as **LORETA Visualizer**.
Its current implementation is an experimental visualization and beta
source-map viewer: it renders a brain mesh, synthetic source maps, prepared
JSON payloads, and early real-project cortical L2-MNE maps.

## Current status

The embedded visualizer can now display real project data through beta
Hauk-style L2-MNE cortical-surface source-space z-score maps. This is an early
method-validation path, not a final validated LORETA, eLORETA, sLORETA,
deep-source, or subject-MRI workflow.

The visible occipital, frontal, and deep medial temporal demo activations are
still synthetic. The real-project path is separate: it reads existing project
workbooks, uses the Stats-selected oddball harmonic list, builds a template
BioSemi64/fsaverage cortical forward model through MNE, writes prepared z-score
source JSON files when needed, and loads them through the same manifest
importer used by the demo fixtures.

Use the current version to verify rendering behavior, transparency, camera
controls, source-layer opacity, color scaling, and whether source maps can be
drawn inside the transparent anatomical shell.

## What you can do now

- Rotate the 3D scene by dragging in the viewport.
- Zoom with mouse or trackpad interaction.
- Reset the camera to the default view.
- Adjust brain transparency.
- Use an external fsaverage mesh loaded through MNE, with synthetic fallback
  when the external mesh is unavailable.
- Show or hide the source map independently from the brain mesh.
- Adjust source-map opacity.
- Switch among project source-map conditions when available, or synthetic
  demonstration conditions otherwise.
- Auto-scale the source intensity map or set manual minimum/maximum intensity
  bounds.
- Read the source color scale from the control-panel color ramp and min/max
  labels.
- Load a prepared source payload JSON file from disk and render it through the
  same display adapter used by the synthetic fixture.
- Load a prepared source manifest JSON file so several prepared source payloads
  appear in the condition dropdown.
- Build beta project source JSON from the active project and load the resulting
  manifest.
- Use checked-in example payload and manifest JSON files as references for the
  expected future calculation output shape.

Higher synthetic values are mapped toward red. Lower values appear lighter or
less intense depending on the current color range.

For beta L2-MNE project maps, the color scale shows the actual scalar range
used for the current source map. When auto-scale is on, the min/max labels
update from the loaded payload values.

## Inputs

The fsaverage brain mesh is loaded through MNE from an external user/cache
location. The toolbox does not store fsaverage MRI template data in the source
tree or project folders.

Checked-in JSON examples live in
`src/Tools/LORETA_Visualizer/examples/`. These are synthetic examples for
format validation and manual importer checks; they are not real source maps.

The beta L2-MNE producer can generate a source-ready fixture manifest into a
local output folder. Those fixture files are useful for checking that the
producer writes the same prepared JSON format the visualizer already imports.

For real project inputs, the source-ready assembler reads existing
per-participant Excel outputs under `1 - Excel Data Files` plus the selected
harmonics from `Stats_Ready_Summed_BCA.xlsx`. The 6C beta exporter writes
project-local output under:

`6 - Source Localization/L2-MNE Cortical Surface Beta/`

The main file to load manually is:

`project_l2_mne_cortical_surface_beta_manifest.json`

The **Load source JSON** and **Load manifest** dialogs start in the last import
folder when possible. Otherwise, they open to the active project's source-map
output folder when it exists, then the active project root.

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

Advanced controls can still load a controlled prepared-payload JSON file or a
prepared source manifest manually. Manual payloads need points, values, optional
triangle faces, a source-model label, metadata, and a coordinate-space label.
The tool validates the file and converts coordinates into the current display
mesh space before rendering.

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
neighboring frequency bins, sends target and noise topographies through the
same inverse model, and displays source-space z-scores.

By default, z-score maps display only positive source-space z-scores (`z > 0`).
The signed z-score payload is still preserved in the generated JSON for QC, but
negative/below-baseline values are not rendered in the normal activation view.
This keeps the visible heatmap focused on above-baseline FPVS source responses.

The older arbitrary-amplitude L2-MNE cortical-surface export remains available
as an advanced diagnostic action. Those values are arbitrary/template-scaled
source amplitudes proportional to the sensor topographies used as input
(`summed BCA uV` by default). They are not calibrated current density, dipole
moment, or microvolts at the source.

The z-score mode is better aligned with FPVS source-localization publications,
but it is still a beta template-based workflow. It is EEG-only, uses fsaverage
instead of individual MRIs, and is intended for method review before treating
the maps as analysis-ready.
