# LORETA Visualizer

Use this page when you want to inspect the experimental 3D LORETA/source
visualization tool.

The LORETA Visualizer opens from the main app sidebar as **LORETA Visualizer**.
Its current implementation is a visualization prototype: it renders a brain
mesh and synthetic source maps so the 3D display layer can be tested before real
source-localization calculations are added.

## Current status

The tool does not currently calculate real LORETA, eLORETA, sLORETA, MNE inverse
solutions, or deep-source estimates from EEG data. The visible occipital,
frontal, and deep medial temporal activations are synthetic demo maps.

Use the current version to verify rendering behavior, transparency, camera
controls, source-layer opacity, color scaling, and whether source maps can be
drawn inside the transparent anatomical shell.

## What you can do now

- Rotate the 3D scene by dragging in the viewport.
- Zoom with mouse or trackpad interaction, or with the explicit zoom buttons.
- Reset the camera to the default view.
- Adjust brain transparency.
- Load an external fsaverage mesh through MNE when an fsaverage cache is
  available, or use the synthetic fallback mesh.
- Toggle a smoothed visual duplicate of the brain surface.
- Show or hide the dummy source heatmap independently from the brain mesh.
- Adjust dummy source-map opacity.
- Switch among synthetic occipital, frontal, deep medial temporal, and prepared
  source-map fixture conditions.
- Auto-scale the source intensity map or set manual minimum/maximum intensity
  bounds.
- Load a prepared source payload JSON file from disk and render it through the
  same display adapter used by the synthetic fixture.
- Load a prepared source manifest JSON file so several prepared source payloads
  appear in the condition dropdown.
- Use checked-in example payload and manifest JSON files as references for the
  expected future calculation output shape.

Higher synthetic values are mapped toward red. Lower values appear lighter or
less intense depending on the current color range.

## Inputs

No real EEG source-localization files are read yet.

The fsaverage brain mesh is loaded through MNE from an external user/cache
location. The toolbox does not store fsaverage MRI template data in the source
tree or project folders.

Checked-in JSON examples live in
`src/Tools/LORETA_Visualizer/examples/`. These are synthetic examples for
format validation and manual importer checks; they are not real source maps.

## Interpreting the demo maps

Treat every current source activation as a rendering test only. The maps are not
estimated from EEG data, are not tied to FPVS statistics, and should not be used
for reporting neural source results.

The deep medial temporal demo shows that the renderer can display a smooth
internal 3D source blob inside the transparent brain. It is not a hippocampal
source-localization result.

The prepared source-map fixture is shaped like a future real-data handoff with
coordinates, scalar values, faces, source-model metadata, and coordinate-space
conversion. It is still synthetic and should be used only to inspect rendering.

The **Load source JSON** button accepts controlled prepared-payload files with
points, values, optional triangle faces, a source-model label, metadata, and a
coordinate-space label. The tool validates the file and converts coordinates
into the current display mesh space before rendering.

The **Load manifest** button accepts a controlled manifest file that lists
condition labels and relative prepared-payload JSON files. After loading a
manifest, those imported conditions appear in the same condition dropdown as the
synthetic demos. Selecting one loads and renders its prepared payload.

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
