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
- Switch among synthetic occipital, frontal, and deep medial temporal
  conditions.
- Auto-scale the source intensity map or set manual minimum/maximum intensity
  bounds.

Higher synthetic values are mapped toward red. Lower values appear lighter or
less intense depending on the current color range.

## Inputs

No real EEG source-localization files are read yet.

The fsaverage brain mesh is loaded through MNE from an external user/cache
location. The toolbox does not store fsaverage MRI template data in the source
tree or project folders.

## Interpreting the demo maps

Treat every current source activation as a rendering test only. The maps are not
estimated from EEG data, are not tied to FPVS statistics, and should not be used
for reporting neural source results.

The deep medial temporal demo shows that the renderer can display a smooth
internal 3D source blob inside the transparent brain. It is not a hippocampal
source-localization result.

## Future real-data direction

Future source-localization calculations should be implemented separately from
the renderer. A calculation step will need to produce coordinates, scalar
values, source-model metadata, and a coordinate-space label. The visualizer's
helper layer will then adapt that prepared payload into the 3D renderer.

This separation lets the visualization support different future source methods
without hard-coding one calculation pipeline into the display layer.
