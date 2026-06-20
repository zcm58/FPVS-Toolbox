# LORETA 3D Brain Visualizer

## Status

Phase 1, Phase 2, Phase 3, Phase 4, Phase 5A, Phase 5B, Phase 5C, Phase 5D, Phase 5E, Phase 5F, Phase 5G, Phase 5H, Phase 6A, Phase 6B, Phase 6C, Phase 6D, Phase 6E, Phase 6F, Phase 6G, Phase 6H-A(1), Phase 6H-A(2), Phase 6H-A(3), Phase 6H-A(4), and Phase 6H-A(5) are implemented on `codex/loreta-3d-visualizer`. The renderer payload contract is source-model agnostic, supports scalar-gradient source maps, preserves native-to-display coordinate transforms, includes a prepared source-map fixture, imports controlled prepared JSON payloads, supports prepared payload manifests, provides checked-in JSON examples, includes producer-facing schema/validation, has a separate beta L2-MNE cortical-surface source producer for source-ready FPVS fixtures, can assemble source-ready 64-channel condition topographies from flat or condition/group project workbooks, can write beta project source-map JSON from real project data, can write Hauk-style L2-MNE source-space z-score payloads from real FullFFT target and neighboring-bin project data, exposes method/QC controls plus user-facing method documentation, renders L2-MNE cortical-surface maps as opaque cortical paint, defaults cortical viewing to a publication-style split-hemisphere layout, uses the root-local fsaverage cache for automatic downloads, keeps transparent mesh rendering visible across tested Windows/VTK stacks by disabling depth peeling, builds real-project Hauk z-score maps through MNE-native L2-MNE with loose orientation `0.2`, no depth weighting, no dSPM/sLORETA/eLORETA noise normalization, and `lambda2 = 1 / 9`, defaults Hauk-style real-project z-score generation to participant-first source maps with raw mean, median, and 20% trimmed-mean group summaries, writes source-space cluster-permutation masks for participant-first L2-MNE publication maps, writes descriptive source-space lateralization summary sidecars, and now emits Hauk-style Desikan-Killiany inferior/middle/superior temporal ROI lateralization rows from fsaverage `aparc` labels.

This plan is the source of truth for a completely new source-localization development branch. It is not a restoration, continuation, refactor, or design descendant of the retired Source Localization/eLORETA implementation. Old Source Localization code, quarantine code, retired GUI workflows, historical settings, and legacy tests must not be used for design choices.

## Current Development Stage

The branch is currently past the beta project source-map export and method-QC
z-score implementation stage and is in post-6G hardening/validation. The
interactive renderer, anatomical mesh loading, source-layer rendering, scalar
color controls, coordinate transform bridge, single-payload importer,
multi-condition manifest importer, checked-in JSON format examples, JSON Schema
shape files, producer-facing validator, method-neutral source-producer result
contracts, beta L2-MNE cortical-surface fixture producer, and read-only project
topography input assemblers are in place. Phase 6C adds the first project-level
arbitrary-amplitude export path: real project topographies are combined with an
external MNE/fsaverage BioSemi64 template EEG forward model and written as
validated prepared JSON/manifest files for the visualizer. Phase 6D adds the
publication-aligned method/QC path: raw project `FullFFT Amplitude (uV)`
target and neighboring bins are sent through the same L2-MNE inverse model,
then source-space baseline correction and z-scoring are applied before writing
the renderer payload. Phase 6E adds method documentation, a Source Map Options
modal, flagged-participant include/exclude rebuild control, and compact IDE-log
reporting for source-map rebuilds. Phase 6F adds opaque pial cortical paint
rendering and a user-facing z-score display cutoff selector for L2-MNE cortical
surface payloads while preserving transparent overlay rendering for volume/deep
payloads. Phase 6G adds a display-mode selector and makes a publication-style
split-hemisphere cortical view the default selected cortical display. Phase
6H-A(1) updates the group-level fsaverage/template Hauk path to use
MNE-native L2-MNE inverse settings aligned with Hauk et al.: `method="MNE"`,
`loose=0.2`, `depth=None`, `fixed=False`, no dSPM/sLORETA/eLORETA noise
normalization, and `lambda2 = 1 / 9`. Phase 6H-A(2) changes the default
Hauk-style project z-score export to participant-first source-space z-scores,
then group raw mean, median, and 20% trimmed-mean summaries, while keeping the
older group-first model as a deprecated advanced fallback. Phase 6H-A(3)
computes a Hauk et al. 2025-aligned one-sample positive-tail sign-flip
source-space cluster-permutation mask from participant z-score maps and stores
the significant source vertices in prepared payload metadata for
publication-style L2-MNE display. Phase
6H-A(4) writes producer-side descriptive source-space
lateralization CSV/JSON sidecars for participant and group-summary maps.
Phase 6H-A(5) preserves fsaverage source-space vertex IDs and hemisphere
labels, maps the Desikan-Killiany inferior, middle, and superior temporal
labels onto the source mesh, and emits the Hauk-style temporal-lobe
lateralization rows as the primary source-space laterality summary.
Post-6G hardening adds durable root-local fsaverage cache behavior, skips stale
unsafe generic MNE fsaverage config paths, reads project workbooks from both
flat condition folders and condition/group subfolders, surfaces clear
preprocessing/Stats-export prerequisite messages, and disables VTK depth peeling
for transparent mesh modes.

This is still a beta, template-based method-validation stage, not a final
scientifically validated source-localization workflow. The 6C and 6D paths use
real project FPVS condition data, but they do not change preprocessing, Stats,
existing project manifests, workbook formats, source producers, or the importer.
Future LORETA, eLORETA, sLORETA, beamformer, or other source-estimation methods
should become sibling producers that target the prepared JSON/payload bridge
and stay separate from the renderer, display fsaverage loader, and project I/O
unless a new plan explicitly scopes integration.

The prepared payload contract stage is complete, Phase 6A established the first
swappable source method, Phase 6B established a read-only project-input
assembler, Phase 6C established the first real-project beta export and GUI
entry point, Phase 6D established the Hauk-style source-space z-score mode, and
Phase 6E established source-map method/QC controls and documentation, and
Phase 6F established the opaque cortical paint visualization and display
threshold selector for surface maps. Phase 6G established a source-view mode
selector with a split-hemisphere, publication-style cortical viewer alongside
the single pial surface view and transparent mesh view. Phase 6H-A(1)
established Hauk-style MNE-native inverse settings, Phase 6H-A(2) established
participant-first source-map generation and group summaries, and Phase
6H-A(3) established producer-side source-space cluster-permutation masks for
publication-style cortical display. Phase 6H-A(4) adds descriptive
whole-hemisphere and coordinate-defined LOT/ROT source-space lateralization
summaries so source maps can be compared against known sensor-space BCA
  lateralization results without changing the renderer. Phase 6H-A(5) replaces
  the coordinate-defined LOT/ROT approximation as the Hauk-style target by
  adding Desikan-Killiany temporal label masks from fsaverage `aparc`; the older
  coordinate LOT/ROT row remains as a transparent QC/fallback row. Project
  Hauk-style z-score exports also write project-local JSON/Markdown validation
  reports that summarize generated files, payload validation, cluster-mask
  coverage, source lateralization highlights, beta limitations, and recommended
  manual checks. The next recommended development slices are manual scientific
  validation of masked maps against scalp maps, unmasked maps, source-space
  lateralization summaries, and the deprecated group-first output, plus a
  source-map build performance slice that adds selected-column FullFFT parsing
  and a project-local inverse-model cache before expanding cluster controls or
  adding another source method.

## Date

Created: 2026-06-05
Updated: 2026-06-19

## Goal

Build an embedded, interactable 3D brain visualizer tool in the existing Main App, matching the current embedded-tool pattern used by Stats, SNR Plots, Scalp Maps, Publication Report, Ratio Calculator, Individual Detectability, Image Resizer, and Epoch Averaging.

The first implementation phase proves the real-time 3D viewer experience:

- Render a transparent brain mesh inside the Main App workspace.
- Keep rendering interactive in real time.
- Allow drag/orbit rotation.
- Allow zoom in and zoom out through mouse interaction and explicit controls.
- Allow camera reset/default view.
- Allow adjustable brain transparency.
- Add a dedicated sidebar entry with a visual sidebar icon/logo.

Later phases add a real anatomical mesh, dummy LORETA-like activation layers, and condition selection before real data adapters. Early slices must not depend on source-localization computation, preprocessing changes, or project-output changes.

Core design rule: rendering, fsaverage/anatomical mesh construction, display
translation, and source-localization numerical calculation are separate
concerns. This tool may render a prepared source mesh/point/volume payload in
the same 3D coordinate space as the fsaverage brain mesh, but computing the
source values belongs to a separate method producer and must not be mixed into
rendering, fsaverage mesh loading, importer, or display-translation code. The
first real producer method is implemented as beta L2-MNE cortical-surface
source maps; later LORETA/eLORETA/sLORETA/volume methods should swap in by
producing the same validated prepared payload/manifest contract.

## Current Repo State

- Tool-specific PySide6 windows and launchers currently live under `src/Tools/*/`; `src/Main_App/gui/` owns the shell, sidebar, icons, workspace stack, and page factories.
- There is no active `src/Main_App/tools/` package today. Do not create one for this tool unless the architecture docs are updated to introduce that new ownership boundary.
- Embedded tools are currently wired through:
  - `src/Main_App/gui/main_window.py` for imports, `_ensure_*_page()` factories, and `open_*()` methods.
  - `src/Main_App/gui/sidebar.py` for permanent sidebar buttons.
  - `src/Main_App/gui/icons.py` for sidebar icons.
  - `src/Main_App/gui/project_workflows.py` for retiring project-bound embedded page instances after project changes.
- `requirements.txt` already includes `pyvista`, `pyvistaqt`, `vtk`, and `nibabel`; PyVista/VTK should be the first 3D backend unless implementation testing shows it cannot embed reliably.
- The local MNE dependency exposes `mne.datasets.fetch_fsaverage(subjects_dir=None)` and `mne.read_surface(...)`, which can support an fsaverage mesh loader without bundling MRI/template data into source.
- Automatic fsaverage fetches target `.fpvs_cache/mne/MNE-fsaverage-data/`
  under the FPVS Toolbox repository root. Generic stale MNE subjects-dir config
  under `src/` or `docs/` is ignored; explicit
  `FPVS_FSAVERAGE_SUBJECTS_DIR` overrides under those paths fail fast.
- Transparent mesh rendering uses plain alpha blending because VTK depth
  peeling made translucent brain actors disappear on at least one supported
  Windows graphics stack.
- Source Localization/eLORETA is removed from active runtime. `src/Tools/SourceLocalization/**` must remain empty of source files, and this visualizer must not import from `Tools.SourceLocalization` or `src/quarantine/**`.
- This LORETA visualizer is new work. Do not use retired Source Localization/eLORETA code or quarantine code as a reference implementation for architecture, names, GUI behavior, settings, tests, rendering, or future real-data adapters.
- Future-agent local rules for this tool live in `src/Tools/LORETA_Visualizer/AGENTS.md`.

## Branch And Promotion Policy

Implementation must start on a new branch before code changes:

```powershell
git switch -c codex/loreta-3d-visualizer
```

Branch expectations:

- Keep the feature isolated on the branch until the user approves promotion.
- On the branch, the sidebar entry should be visible so the embedded tool can be manually tested like the other tools.
- The promotion decision is to keep the tool visible by default in the sidebar.
  Opening it first shows a session-scoped beta warning that users must
  acknowledge before the workspace switches to the visualizer.
- Do not use branch work as permission to touch preprocessing, Stats methods, project manifests, BDF loading, diagnostics, or active Source Localization paths.

## Proposed Boundaries

New tool implementation:

- `src/Tools/LORETA_Visualizer/`
  - `AGENTS.md`: scoped rules for keeping LORETA visualizer code self-contained and separating rendering from future LORETA computation.
  - `ARCHITECTURE.md`: tool-local architecture contract covering goals, non-goals, bridge helpers, renderer/calculation separation, and payload flow.
  - `__init__.py`: public tool surface.
  - `gui.py`: embedded PySide6 page/window class.
  - `renderer.py`: PyVista/VTK rendering adapter, lazy imports, actor/camera helpers, cortical paint, split-hemisphere display, and transparent mesh alpha blending.
  - `synthetic_brain.py`: deterministic synthetic mesh/activation placeholders used for viewer validation.
  - `fsaverage_cache.py`: root-local/configured fsaverage cache policy.
  - `fsaverage_mesh.py`: lazy fsaverage fetch/load/decimation helpers for Slice 2.
  - `dummy_activation.py`: deterministic synthetic LORETA-like condition data for Slice 3, Slice 4, and source-model-agnostic 5A demos.
  - `conditions.py`: condition list/model helpers for Slice 4.
  - `source_payloads.py`: renderer-facing payload contract for cortical surface points, cortical/deep meshes, volume/deep source representations, and future ROI meshes.
  - `scalar_fields.py`: scalar-gradient color stops and scalp-map-style auto/manual color-limit helpers.
  - `transforms.py`: native/source coordinate to renderer display coordinate transform contract.
  - `prepared_source_fixture.py`: in-memory prepared source-map fixture that validates the future adapter handoff shape without computing source estimates.
  - `prepared_payload_importer.py`: controlled JSON importer for already-prepared source payloads and source-payload manifests.
  - `prepared_payload_validator.py`: producer-facing validator and schema descriptors for prepared source payloads and manifests.
  - `examples/`: checked-in synthetic prepared payload and manifest JSON examples for future calculation producer output shape and importer validation.
  - `examples/*.schema.json`: shape-level JSON Schema files for external producer tooling.
  - `source_producers/`: source-localization calculation producers that read explicit source-ready inputs and write prepared payload/manifest JSON. These modules must not import the GUI, renderer, display importer, display bridge helpers, or display mesh loader.
    - `project_inputs.py`: read-only Phase 6B project workbook adapter that assembles source-ready 64-channel FPVS condition topographies from flat condition folders or condition/group subfolders.
    - `project_fullfft_inputs.py`: read-only Phase 6D FullFFT target/noise-bin adapter for Hauk-style source-space z-scores.
    - `project_l2_mne_export.py`: Phase 6C diagnostic arbitrary-amplitude project exporter.
    - `project_l2_mne_hauk_zscore_export.py`: Phase 6D default project z-score exporter.

Main App shell integration:

- `src/Main_App/gui/main_window.py`: add lazy import/page factory/open method for the embedded visualizer.
- `src/Main_App/gui/sidebar.py`: add a Workspace Tools sidebar button.
- `src/Main_App/gui/icons.py`: add a dedicated sidebar icon/logo key for the visualizer.
- `src/Main_App/gui/project_workflows.py`: retire any cached `_loreta_visualizer_page` if the tool becomes project-aware.

No other production module should receive LORETA-specific implementation code unless this plan is explicitly revised. Keep visualizer logic, demo payloads, mesh adapters, rendering adapters, payload validators, and source-producer adapters inside `src/Tools/LORETA_Visualizer/`. Keep method producers in `source_producers/` so L2-MNE, LORETA volume, eLORETA, or other methods can be swapped without changing renderer or translation code.

Avoid:

- `src/Main_App/tools/**` unless this plan is explicitly revised to introduce that package.
- `src/Tools/SourceLocalization/**`.
- Imports from `src/quarantine/**`.
- Restoring old legacy eLORETA launchers, settings, tests, or GUI paths.
- Adopting old Source Localization/eLORETA architecture, data contracts, GUI patterns, settings, tests, rendering decisions, or file layouts as precedent.
- Writing LORETA settings into `project.json` in Phase 1.
- Bundling `fsaverage` MRI/template data in `src/`, `docs/`,
  `src/quarantine/`, or package data. Automatic fetches should install into the
  untracked FPVS Toolbox root cache at
  `.fpvs_cache/mne/MNE-fsaverage-data/`. Explicit
  `FPVS_FSAVERAGE_SUBJECTS_DIR` overrides may point elsewhere only if they do
  not target source or docs paths; stale generic MNE config candidates that do
  target those forbidden paths are ignored.
- Re-enabling VTK depth peeling for transparent mesh modes without visible
  Windows/VTK driver testing. The current renderer deliberately uses plain
  alpha blending so opacity values below 100% still show the brain mesh.
- Computing LORETA/source-localization values inside `renderer.py`, `fsaverage_mesh.py`, `prepared_payload_importer.py`, `source_payloads.py`, `transforms.py`, `scalar_fields.py`, or GUI widget code.
- Adding LORETA-specific computation to preprocessing, Stats, diagnostics, or project I/O modules.

## Phase 1: Embedded Real-Time Brain Viewer

Status: Implemented. The embedded sidebar tool, PyVista renderer, synthetic fallback, camera controls, zoom controls, reset, and brain transparency controls are present on the LORETA branch.

Objective:

- Stand up the embedded tool as a first-class workspace page.
- Render a brain-like mesh in real time using PyVista/VTK embedded in PySide6.
- Add interaction controls:
  - orbit/drag rotation;
  - mouse-wheel or trackpad zoom;
  - reset camera/default view action in the always-visible controls;
  - transparency slider for the base brain mesh.
- Add a sidebar button and dedicated sidebar icon/logo.
- Keep the viewer responsive during interaction and app navigation.

Implementation notes:

- Use lazy imports for `pyvista`, `pyvistaqt`, and `vtk` so app startup does not fail if optional 3D packages are unavailable.
- If the backend is missing, show a non-blocking embedded status/error view with install/dependency details instead of crashing startup.
- Use existing PySide6 layout conventions and shared components where they fit, but keep the render surface visually flat and spacious.
- Keep Phase 1 data synthetic and deterministic. A generated ellipsoid/cortical-shell placeholder is acceptable only for validating rendering and controls.
- Do not add heatmap semantics, LORETA file loading, or source-localization statistics in Phase 1.

Done means:

- The Main App launches with the new sidebar entry on the branch.
- Clicking the sidebar entry embeds the visualizer in `workspace_stack`.
- The scene renders a nonblank 3D brain-like mesh.
- Drag rotation, zoom in/out, camera reset, and transparency changes are visibly effective.
- Switching away from and back to the tool does not crash or duplicate stale widgets.
- Missing 3D dependencies degrade gracefully.
- Existing app startup, project loading, and existing embedded tools still work.

## Phase 2: Real Anatomical Brain Mesh

Status: Implemented. The visualizer starts with the synthetic fallback and
loads/fetches fsaverage through MNE into the untracked FPVS Toolbox root cache
in a worker when the tool opens. A visible `Fetch/load fsaverage` button is no
longer part of the primary UI.

Objective:

- Replace the Phase 1 placeholder mesh with an actual anatomical brain surface.
- Prefer fsaverage as the first target, loaded through MNE rather than bundled into the repo.
- Use a lazy mesh loader that can:
  - locate an existing fsaverage subject directory if configured;
  - fetch fsaverage through `mne.datasets.fetch_fsaverage(...)` into
    `.fpvs_cache/mne/MNE-fsaverage-data/` under the FPVS Toolbox root when
    missing;
  - read an appropriate surface with `mne.read_surface(...)`;
  - convert vertices/faces into PyVista `PolyData`;
  - optionally decimate or use a lower-density surface for responsive interaction.
- Keep the Phase 1 camera, zoom, reset, and transparency controls working with the real mesh.
- Gracefully fall back to the synthetic placeholder mesh if fsaverage is unavailable, fetch is declined/unavailable, or the surface cannot be read.

Implementation notes:

- Do not place fsaverage files under `src/`, `src/quarantine/`, tracked docs, or package data.
- Store automatically fetched template data in the untracked FPVS Toolbox root
  cache, not in temp directories, `src/`, docs, quarantine, package data, or
  project folders.
- Ignore stale generic MNE fsaverage config candidates that point under `src/`
  or `docs/` so a bad developer-machine config does not block the root-local
  cache. Explicit `FPVS_FSAVERAGE_SUBJECTS_DIR` remains fail-fast when it points
  to a forbidden path.
- Keep mesh loading lazy. If fetching/loading is slow, move it to `QThread` or `QRunnable` and update the viewport through signals.
- Add clear inline status for "Using fsaverage", "Fetching fsaverage", and "Using synthetic fallback".
- Consider loading a pial/inflated surface pair later, but Slice 2 only needs one usable anatomical mesh.

Done means:

- The visualizer can render a real fsaverage-derived brain mesh.
- Transparency, rotate/orbit, zoom in/out, and reset view continue to work.
- Missing fsaverage does not crash app startup or the embedded page.
- No fsaverage data is added to tracked source/docs/package data or the
  quarantine tree; the durable local cache remains under ignored `.fpvs_cache`.
- Existing synthetic placeholder remains available as a fallback/debug path.
- Stale MNE config pointing at `src/` or `docs/` does not force fsaverage into
  tracked paths or prevent the root-local cache from being used.

## Phase 3: Dummy LORETA Heatmap Layer

Status: Implemented and superseded by later scalar-gradient volume-mesh demos. The visualizer renders an independent synthetic LORETA layer in the current mesh coordinate space, with independent visibility and opacity controls.

Objective:

- Add a second independent rendering layer for deterministic dummy LORETA-like activation data.
- Establish the rendering contract for future real LORETA payloads: activation data must already be transformed into the same coordinate space as the base fsaverage/anatomical mesh before it reaches the renderer.
- Keep the activation layer independent from the anatomical base mesh:
  - separate actor or scalar/color pipeline;
  - independent opacity;
  - independent visibility toggle;
  - independent scalar range/color map;
  - threshold or lower-bound control.
- Generate dummy activation values in the same coordinate space as the loaded mesh so layer alignment can be validated.
- Keep the dummy data clearly labeled as synthetic/demo-only in status/logging; do not imply computed source localization results.
- Do not calculate real LORETA/source-localization values in this slice.

Implementation options:

- Per-vertex scalar overlay on the fsaverage mesh, using PyVista scalar coloring and a translucent activation actor.
- Sparse source "blobs" or point-cloud spheres positioned on/near the surface for easier visual debugging.
- Start with deterministic condition-specific blobs so Slice 4 can switch conditions without introducing real data I/O.
- Future real implementations may provide a cortical mesh, sparse points, or volume sampled into fsaverage/anatomical coordinates, but that preparation is upstream of the renderer.

Done means:

- Base mesh and activation layer can be shown/hidden independently.
- Base mesh opacity and activation opacity work independently.
- Threshold/scale changes visibly alter the activation layer.
- Both layers remain aligned under rotation, zoom, transparency changes, and reset view.
- Dummy activation data does not touch preprocessing outputs, Stats methods, project manifests, or Source Localization runtime paths.
- The renderer accepts already-prepared activation coordinates/scalars and remains independent from the math that produced them.

## Phase 4: Condition Selection And Demo Data Switching

Status: Implemented with local synthetic occipital, frontal, and deep medial-temporal conditions. Switching the combo updates the dummy activation payload immediately without reading real LORETA files or changing project state.

Objective:

- Add condition-selection GUI similar in spirit to the SNR Plot Generator's condition workflow, but scoped to the LORETA visualizer.
- Provide a condition list/combo/checkable list that can switch the displayed dummy LORETA activation layer.
- Bind each demo condition to deterministic synthetic activation parameters so users can verify that condition changes update the overlay.
- Keep condition data local to the tool for this slice; do not read or write project LORETA outputs yet.
- Prepare a narrow adapter shape for future real condition-specific LORETA data.

Implementation notes:

- If a project is loaded and condition names are available from the active project event map, use those labels as demo condition names.
- If no project is loaded, expose a small fixed demo set such as `Condition A`, `Condition B`, and `Condition C`.
- Keep condition switching non-blocking. If future real data loading is expensive, use a worker and signal-driven renderer update.
- Do not add source-localization output discovery yet unless a later plan explicitly scopes real LORETA file formats and locations.

Done means:

- Selecting a condition updates the dummy activation layer visibly.
- The selected condition label/status is clear in the tool.
- Base mesh controls continue to work while switching conditions.
- No real LORETA file format, project manifest, preprocessing, Stats, or Source Localization runtime changes are introduced.

## Phase 5: Optional Real Data Adapter

Status: Split into smaller slices. Phase 5A covers a general source payload contract plus synthetic deep-source rendering. Phase 5B adds scalar-gradient color mapping and intensity bounds for source values. Phase 5C preserves the native-to-display coordinate transform for future source-localization adapters. Phase 5D adds a selectable prepared source-map fixture that looks like a future real-data handoff. Phase 5E adds controlled prepared JSON payload import. Phase 5F adds multi-condition prepared payload manifests. Phase 5G adds checked-in JSON examples for future calculation producer output. Phase 5H adds producer-facing schema and validation. Real LORETA calculation, project-output discovery, and project-output integration remain out of scope.

Objective:

- Add a deterministic adapter interface for future real LORETA/source-volume inputs.
- Keep rendering contracts independent from any future source-localization computation path.
- Consume already-computed LORETA payloads that have been mapped onto the same coordinate frame as the fsaverage/anatomical base mesh.
- Keep the actual LORETA numerical calculation in a separate producer implementation, not in renderer/fsaverage mesh construction/GUI code.

Done means:

- Real data can later be injected without changing the renderer's base actor/layer contract.
- The adapter receives condition-specific values and coordinates/scalars from an upstream computation path and only normalizes them into the visualizer payload contract.
- The adapter does not import `Tools.SourceLocalization`, retired Main App paths, or quarantine code.
- Any project-file integration is explicitly scoped in a new plan update before implementation.

### Phase 5A: General Source Payload Adapter And Deep Demo

Objective:

- Make the renderer-facing activation contract source-model agnostic before real calculations exist.
- Add a LORETA-local payload model that can represent cortical surface points, cortical/deep mesh overlays, volume/deep source representations, and future ROI/subcortical meshes.
- Keep the renderer as a display-only consumer of already-prepared coordinates and scalar values.
- Add a synthetic deep medial-temporal/hippocampal-style demo condition so the user can visually confirm that internal sources can be rendered inside the transparent anatomical shell.
- Preserve existing occipital/frontal dummy condition switching and all view controls.

Implementation notes:

- Add `src/Tools/LORETA_Visualizer/source_payloads.py` for payload dataclasses, validation, finite-value filtering, and value normalization.
- Refactor dummy activation generation to emit the general payload instead of a cortical-only activation object.
- Add `Deep medial temporal demo` as a deterministic local condition with `volume_grid` source model metadata.
- Render the deep demo as smooth internal mesh blobs rather than point glyphs; do not add real anatomical hippocampus meshes yet.
- Do not compute source localization, discover LORETA files, write project settings, or import retired/quarantine source-localization code.

Done means:

- The condition selector offers occipital, frontal, and deep medial-temporal synthetic demos.
- Switching to the deep demo updates the heatmap layer immediately and places smooth internal mesh blobs inside the transparent brain volume.
- The renderer accepts a general source payload without knowing how values were calculated.
- Existing opacity, visibility, zoom, rotate, and reset behavior still works.
- Focused non-GUI tests cover the payload contract and the synthetic deep-source payload shape.

### Phase 5B: Scalar Gradient Source Maps

Status: Implemented with local dummy scalar fields and renderer color-limit controls.

Objective:

- Treat dummy LORETA activity as continuous scalar fields rather than binary active/inactive regions.
- Use a sequential colormap with high values on the red end, following the scalp-map tool pattern of explicit color limits and auto-scaling.
- Add controls for automatic intensity scaling and manual min/max intensity bounds.
- Keep color scaling in renderer/view configuration only; do not introduce LORETA numerical computation.
- Preserve smooth internal volume-mesh rendering for occipital, frontal, and deep medial-temporal demos.

Implementation notes:

- `scalar_fields.py` owns LORETA-local color stops and `resolve_scalar_limits(...)`.
- Auto scaling uses scalp-map style nonnegative bounds: lower bound is 0 for nonnegative maps, with upper bound from finite payload values.
- Manual bounds are accepted through GUI spin boxes and corrected if max is not greater than min.
- Dummy occipital, frontal, and deep medial-temporal payloads carry continuous scalar values in the renderer payload.

Done means:

- Switching dummy conditions shows graded color variation across smooth 3D source blobs.
- The intensity auto-scale toggle changes whether payload-derived or manual min/max color bounds are used.
- High dummy values render at the red end of the colormap.
- Focused tests cover scalar-limit resolution and dummy scalar ranges.

### Phase 5C: Coordinate Transform Contract

Status: Implemented. Meshes carry the display transform used to normalize native coordinates, and source payloads can be converted into renderer display space through a narrow helper.

Objective:

- Preserve the native/anatomical-to-renderer display coordinate transform instead of discarding it during mesh loading.
- Let future source-localization methods provide coordinates in their declared source space and convert them into display space through a visualizer-local adapter boundary.
- Keep this independent from LORETA numerical computation, source-estimation method choice, and project I/O.
- Support future changes in source-localization method by keeping the rendering contract tied to explicit coordinate spaces rather than one hard-coded calculation pipeline.

Implementation notes:

- `transforms.py` owns `MeshDisplayTransform` and coordinate-space constants.
- fsaverage mesh loading builds a transform from the native fsaverage surface points, uses it to normalize the display mesh, and stores it on `BrainMesh`.
- Synthetic meshes use an identity display transform because their points are already in renderer display coordinates.
- `source_payloads.py` exposes `source_payload_to_display(...)` so future adapters can convert prepared payloads without changing renderer internals.
- `renderer.py` exposes the current mesh display transform for future adapter wiring.
- Synthetic GUI payloads round-trip through native coordinates and `source_payload_to_display(...)` when the loaded mesh has a non-identity native/display transform, so the dummy path exercises the future real-data bridge without computing source estimates.
- This does not add MNI registration, subject MRI transforms, source file import, or real source-localization computation.

Done means:

- Native fsaverage-like point arrays round-trip through display and native space.
- Payload conversion preserves scalar values, faces, labels, and source model metadata while updating coordinates into display space.
- Mismatched coordinate-space labels are rejected instead of silently rendering misaligned sources.

### Phase 5D: Prepared Source Payload Fixture

Status: Implemented. The condition selector includes a `Prepared source-map fixture` demo condition that routes prepared coordinates/scalars through the same adapter bridge future real source outputs should use.

Objective:

- Add a source-map fixture shaped like a future real calculation handoff: coordinates, scalar values, source model, coordinate-space label, faces, and metadata.
- Keep fixture generation in the visualizer only and clearly synthetic.
- Convert the fixture through `source_payload_to_display(...)` when a non-identity mesh transform is available.
- Make the fixture selectable from the existing dummy condition combo so the render can be manually inspected.
- Avoid real source-localization calculation, file discovery, project I/O, and Source Localization/eLORETA dependencies.

Implementation notes:

- `prepared_source_fixture.py` owns the in-memory prepared fixture and its adapter call.
- The fixture uses multiple asymmetric smooth volume lobes with graded scalar values so it visually resembles a thresholded source map more than the simple regional demos.
- The payload metadata marks the source as an in-memory synthetic fixture and records whether it was adapted through `source_payload_to_display(...)`.

Done means:

- Selecting `Prepared source-map fixture` immediately updates the heatmap layer.
- The payload is a volume mesh with finite scalar gradients and VTK faces.
- Focused tests prove the fixture condition exists, uses prepared fixture metadata, and preserves display alignment through a fsaverage-like native transform.

### Phase 5E: External Prepared Payload Import

Status: Implemented. The visualizer can load a user-selected prepared source payload JSON file, validate it, convert it to renderer display space, and render it through the existing activation layer.

Objective:

- Add a controlled external file format for already-prepared source payloads.
- Keep import separate from source-localization calculation and project-output discovery.
- Support source payload JSON fields for format version, label, kind, coordinate space, source model, value label, points, scalar values, optional triangle faces, and metadata.
- Convert imported coordinates through `source_payload_to_display(...)` using the current mesh display transform.
- Let users manually inspect an imported prepared payload without changing project manifests or running real LORETA math.

Implementation notes:

- `prepared_payload_importer.py` owns JSON parsing, schema validation, face conversion, metadata preservation, and display conversion.
- The GUI exposes `Load source JSON`; cancel leaves the current activation unchanged.
- Import errors are surfaced in the condition status label and logged without crashing the viewer.
- No project root is required for this importer because files are explicit user selections and no output is written.

Done means:

- Focused tests load display-space and fsaverage-like native JSON payloads and confirm display-space output.
- Invalid JSON/schema cases fail with `PreparedSourcePayloadImportError`.
- The GUI can render the imported payload through the same activation actor, opacity controls, and scalar range controls used by synthetic payloads.

### Phase 5F: Multi-Condition Prepared Payload Manifest

Status: Implemented. The visualizer can load a user-selected manifest JSON that maps condition labels to prepared source payload JSON files, then adds those imported conditions to the existing condition dropdown.

Objective:

- Load multiple prepared source payloads as a named condition set.
- Keep the manifest format separate from real LORETA calculation and project-output discovery.
- Resolve manifest payload paths relative to the manifest file and reject paths that escape the manifest folder.
- Let the condition selector switch among imported prepared source maps using the same renderer path as single-file imports.
- Preserve existing synthetic demo conditions and the single-payload JSON import.

Implementation notes:

- `prepared_payload_importer.py` owns manifest parsing, path validation, duplicate-condition-id checks, and manifest examples.
- The GUI exposes `Load manifest`; cancel leaves the current activation unchanged.
- Loading a manifest replaces the previously imported manifest conditions, then selects and renders the first imported condition.
- Switching the base brain mesh reloads the selected imported condition through the current mesh display transform.

Done means:

- Focused tests load a manifest, resolve relative payload files, load each listed payload, and reject path escapes and duplicate ids.
- Imported manifest entries appear in the condition dropdown with `Imported:` labels.
- Selecting an imported condition loads its payload, converts it to display space, and renders it through the existing activation actor.

### Phase 5G: Checked-In Prepared JSON Examples

Status: Implemented. The visualizer directory includes synthetic prepared payload and manifest JSON examples that future source-localization calculation code can use as the expected v1 output shape.

Objective:

- Provide concrete JSON examples for future LORETA/source-localization producers.
- Keep examples in the visualizer directory with the importer and payload bridge.
- Include both display-space examples that load without fsaverage and an fsaverage-native example that represents the more realistic future calculation handoff.
- Include a manifest example that maps multiple conditions to relative payload files.
- Keep all examples synthetic, small, deterministic, and clearly labeled as not computed from EEG.

Implementation notes:

- `src/Tools/LORETA_Visualizer/examples/source_payload_v1_fsaverage_native_example.json` is the reference shape for future source-localization outputs in fsaverage coordinates.
- `src/Tools/LORETA_Visualizer/examples/source_payload_v1_occipital_display_example.json` and `source_payload_v1_frontal_display_example.json` are normalized display-space examples for importer/GUI validation.
- `src/Tools/LORETA_Visualizer/examples/source_manifest_v1_display_conditions_example.json` demonstrates a multi-condition manifest with relative payload paths.
- Focused tests load the checked-in examples through `prepared_payload_importer.py` so the examples stay aligned with the importer contract.

Done means:

- Checked-in examples use `fpvs-loreta-source-payload-v1` and `fpvs-loreta-source-manifest-v1`.
- The examples can be loaded by the importer and converted into renderer display space.
- The examples remain format fixtures only and do not introduce LORETA calculation, project-output discovery, or project I/O.

### Phase 5H: Prepared Payload Schema And Producer Validation

Status: Implemented. The tool includes JSON Schema files plus a Python validator for prepared payload and manifest producer preflight checks.

Objective:

- Add a machine-checkable contract for `fpvs-loreta-source-payload-v1` and
  `fpvs-loreta-source-manifest-v1`.
- Let future source-localization calculation code validate its JSON outputs
  before handing them to the visualizer.
- Keep validation independent from renderer internals, project-output discovery,
  and LORETA numerical computation.
- Keep the checked-in Phase 5G examples as schema fixtures.

Implementation notes:

- `prepared_payload_validator.py` owns the v1 format constants, lightweight
  schema descriptors, file/mapping validators, and cross-field validation rules.
- `examples/source_payload_v1.schema.json` and
  `examples/source_manifest_v1.schema.json` provide shape-level JSON Schema
  files for external producer tooling.
- The importer delegates raw-shape validation to the producer validator before
  converting payloads into renderer display space.
- Tests validate checked-in examples plus invalid producer outputs such as
  mismatched point/value counts, bad source kinds, invalid face indices,
  duplicate condition ids, absolute paths, path escapes, and missing manifest
  payload files.
- The schema/validator is for producer-side confidence and does not introduce a
  real calculation path.

Done means:

- Future calculation producers have a concrete validation target for payload and
  manifest JSON.
- The checked-in examples are validated against that target in tests.
- No real LORETA calculation, project-output discovery, or project I/O is added.

## Phase 6: Real Source-Localization Producers

Status: Started. Phase 6A, Phase 6B, Phase 6C, and Phase 6D are implemented. Additional source methods and scientific-validation controls remain future work.

Objective:

- Start real source-localization work in separate producer paths that output
  `fpvs-loreta-source-payload-v1` payload JSON and, when multiple conditions
  are produced, `fpvs-loreta-source-manifest-v1` manifest JSON.
- Preserve the renderer/importer boundary: the visualizer should continue to
  consume prepared payloads only.
- Keep method choice, forward model assumptions, montage handling, FPVS
  frequency-domain inputs, and condition/contrast calculations outside
  renderer, fsaverage mesh loading, and GUI rendering code.
- Treat each source-localization method as a swappable producer. A method may be
  L2-MNE cortical surface, a later LORETA/eLORETA volume model, a mixed
  cortical-volume model, or another explicitly scoped approach, but each method
  must hand off through the same prepared payload validator and importer path.

### Phase 6A: Beta L2-MNE Cortical-Surface Producer

Status: Implemented. The tool now includes a separate source-ready beta L2-MNE cortical-surface producer under `src/Tools/LORETA_Visualizer/source_producers/`.

Objective:

- Implement the first real calculation method as a beta L2 minimum-norm
  estimate (L2-MNE) cortical-surface producer, following the published FPVS
  EEG/MEG source-estimation pattern as closely as practical for the toolbox's
  current data model.
- Scope the method to BioSemi ActiveTwo 64-channel / 10-10 montage assumptions
  first, group-level condition maps first, and oddball-response source maps
  per condition.
- Use the Stats-locked group significant oddball harmonic list exactly. The
  method should respect the FPVS convention that the oddball response is
  distributed across selected harmonics and should produce condition-level source
  maps from the same harmonic set used for scalp-map quantification.
- Keep the producer separate from display code. The L2-MNE producer may use MNE
  source-estimation APIs and explicit source-ready inputs, but it must not import
  or call `renderer.py`, `gui.py`, `fsaverage_mesh.py`,
  `prepared_payload_importer.py`, `source_payloads.py`, `transforms.py`, or
  `scalar_fields.py`.
- Emit fsaverage-aligned cortical surface payloads, likely `surface_mesh` or
  `surface_points` with `source_model` metadata such as
  `l2_mne_cortical_surface_beta`, `coordinate_space` set to the declared
  fsaverage/source coordinate label, and scalar values representing the chosen
  source metric.
- Validate every emitted payload/manifest through `prepared_payload_validator.py`
  before any GUI import or manual rendering inspection.
- Document all beta assumptions, especially montage template use, reference
  assumptions, no subject MRI, group averaging strategy, harmonic summation or
  source-space baseline correction, and that cortical-surface L2-MNE does not
  claim deep/hippocampal localization.

Implementation notes:

- `source_producers/contracts.py` owns method-neutral emitted-payload and
  producer-run result dataclasses. These describe output files and validation
  status, not renderer objects.
- `source_producers/l2_mne_cortical.py` owns the Phase 6A beta implementation:
  explicit source-ready forward model arrays, FPVS condition harmonic
  topographies, optional estimator-backed L2 minimum-norm source calculation,
  prepared payload/manifest writing, and a deterministic BioSemi64/10-10
  fixture writer. The deterministic fixture remains a lightweight manual
  inverse; real project exports can attach an MNE-native estimator.
- The beta producer applies an average-reference step by default, uses
  `lambda2 = 1 / 9` by default, records the harmonic strategy in payload
  metadata, and defaults to summing selected sensor harmonic topographies before
  inversion.
- The deterministic fixture exposes occipital and frontal oddball conditions
  over the same selected harmonic list and writes two cortical `surface_mesh`
  payloads plus a manifest. It is source-ready validation data, not a
  participant or project result.
- The fixture can be written with:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m Tools.LORETA_Visualizer.source_producers.l2_mne_cortical --output .codex-tmp\l2_mne_phase6a_fixture
```

- A future volume LORETA/eLORETA method should be able to implement the same
  producer contract and emit `volume_points`, `volume_mesh`, or ROI mesh
  payloads without changing the renderer, importer, or bridge helpers.
- The calculation producer should use MNE/fsaverage/source-space resources for
  computation independently from `fsaverage_mesh.py`, which remains a display
  mesh loader only.
- Phase 6B confirmed that existing compact project workbooks can provide
  source-ready BCA or FFT-amplitude topographies for the beta path. Do not
  change preprocessing, Stats, workbook formats, or project manifests without
  revising this plan.

Done means:

- The L2-MNE cortical-surface producer path is clearly separate from
  `renderer.py`, `gui.py`, `fsaverage_mesh.py`, importer/display bridge helpers,
  and existing project outputs.
- The producer emits validated cortical-surface payloads and a manifest from a
  deterministic source-ready fixture.
- The output validates with `prepared_payload_validator.py` and can be loaded
  through the existing importer without renderer changes.
- The method boundary is explicit enough that a later LORETA/eLORETA volume
  producer can be added as a second method rather than refactoring the L2-MNE
  path into the renderer.
- No retired Source Localization/eLORETA code, quarantine code, preprocessing
  behavior changes, Stats method changes, or project-manifest integration is
  introduced without a new scoped plan.

### Phase 6B: Read-Only Project Topography Inputs

Status: Implemented. The tool now includes a read-only project input assembler
under `src/Tools/LORETA_Visualizer/source_producers/project_inputs.py`.

Objective:

- Inspect a real FPVS project output layout and determine how to build
  source-ready condition topographies without changing preprocessing or Stats.
- Use the same Stats-selected significant harmonic list that drives the
  condition-level FPVS DV and scalp-map quantification.
- Assemble one 64-channel topography per selected harmonic per condition, ready
  for the Phase 6A L2-MNE producer.
- Preserve the renderer/importer boundary and avoid project writes.
- Surface participant QC flags rather than silently dropping flagged data.

Implementation notes:

- `project_inputs.py` reads `3 - Statistical Analysis Results/Stats_Ready_Summed_BCA.xlsx`
  for the selected harmonic list and the real selected condition names.
- It reads compact per-participant workbook sheets under
  `1 - Excel Data Files/<Condition>/` and
  `1 - Excel Data Files/<Condition>/<Group>/` and supports both:
  - `BCA (uV)` via `metric="bca"`; and
  - `FFT Amplitude (uV)` via `metric="fft_amplitude"`.
- It returns `L2MNEFPVSCondition` objects whose harmonic topographies are
  group means across included participants, preserving a separate topography for
  each selected harmonic so the L2-MNE producer can apply its harmonic strategy.
- It reads `Excluded Participants.xlsx` and `Flagged Participants.xlsx`.
  Excluded participants are skipped. Participants listed in
  `Flagged Participants.xlsx` are excluded by default for source-map generation,
  but callers can set `include_flagged_subjects=True` for diagnostic/source-map
  comparisons.
- It performs no writes to the project and does not import renderer, GUI,
  importer, display transform, preprocessing, or Stats implementation modules.

Semantic Categories 6B validation findings:

- A real project was inspected read-only without writing project files.
- The observed layout is single-group with 27 participants and five selected
  analysis conditions: `Fruit vs Veg`, `Green Fruit vs Green Veg`,
  `Green Veg vs Red Veg`, `Red Fruit vs Green Fruit`, and `Veg vs Fruit`.
- The all-condition Stats-ready selected harmonics are:
  `2.4`, `4.8`, `7.2`, `9.6`, `13.2`, and `20.4` Hz.
- All 135 selected condition/participant workbooks read cleanly from the compact
  `BCA (uV)` and `FFT Amplitude (uV)` sheets in the condition/group workbook
  layout, contain the exact selected harmonic columns, and match the expected
  64-channel BioSemi ordering.
- `Publication_Scalp_Maps_Source_Data.xlsx` is useful for paired scalp-map
  auditing when present, but it may cover only a subset of conditions or use a
  pair-specific harmonic list. It should not be the primary input for
  all-condition source maps.
- `Stats_Ready_Summed_BCA.xlsx` carries the correct all-condition harmonic list
  but is ROI-level, not electrode-level; the source topography assembler should
  use it for the selected harmonics and use per-participant workbooks for
  electrode-level values.
- Existing QC output flags `study-participant`, `study-participant`, and `study-participant`; none are excluded by Stats.
  Including flagged participants in source-map generation can strongly
  dominate specific condition maps. The source workflow defaults to excluding
  flagged participants and exposes an explicit include choice before users
  interpret maps.

Recommendation:

- For the first project-connected beta source maps, use `BCA (uV)` topographies
  by default because they match the current FPVS quantification pipeline and
  produce interpretable occipital response patterns from Semantic Categories.
- Keep `FFT Amplitude (uV)` supported for method exploration. Raw FFT amplitude
  is closer to the published L2-MNE wording of summed frequency-domain
  topographies, but in Semantic Categories it carries more broad/frontal
  amplitude structure and lacks source-space baseline correction by itself.
- Do not require complex Fourier coefficients for the immediate beta. If later
  validation shows phase/polarity is needed, add a separate source-ready complex
  coefficient export rather than changing preprocessing silently.
- Phase 6D is the explicit Hauk-style implementation target: source-space
  baseline correction and z-scoring from target and neighboring-bin
  topographies. That remains a source-producer change, not a renderer change.

Done means:

- Semantic Categories can be inspected read-only and converted into
  source-ready 64-channel condition topographies for all selected conditions.
- The selected harmonic list matches the all-condition Stats-ready harmonic
  list exactly.
- Excluded and flagged participant files are read, and flagged participants are
  excluded by default while remaining deliberately includable for comparison.
- Focused tests cover the assembler without depending on local `D:\` project
  paths.
- No project files, preprocessing outputs, Stats behavior, renderer code, GUI
  code, importer code, or project manifests are changed.

### Phase 6C: Project Beta L2-MNE Source-Map Export

Status: Implemented. The tool can now write beta L2-MNE cortical-surface source
maps from an existing project and load those maps through the existing prepared
manifest importer.

Objective:

- Make real project data viewable in the LORETA Visualizer without changing the
  renderer or importer contract.
- Combine Phase 6B project condition topographies with a BioSemi64/fsaverage
  template EEG forward model.
- Write one prepared source payload JSON per project condition plus one
  manifest JSON under the active project root.
- Keep source-map generation in `source_producers/`, separate from rendering,
  display mesh loading, payload import, and display transforms.
- Make the GUI import dialog project-root-aware so loading prepared JSON starts
  from the selected project's source-map output folder when available.

Implementation notes:

- `source_producers/project_l2_mne_export.py` owns the 6C export orchestration.
  It reads project topographies through `project_inputs.py`, builds a
  MNE/fsaverage BioSemi64 EEG model, calls the 6A L2-MNE producer, and writes
  validated payload/manifest JSON. After Phase 6H-A(1), the default
  project-built model carries an MNE-native loose-orientation source estimator
  for real project exports.
- The default output folder is project-local:
  `6 - Source Localization/L2-MNE Cortical Surface Beta/`.
- The default source metric is `BCA (uV)` to match the current FPVS
  quantification path. `FFT Amplitude (uV)` remains supported by the assembler
  and producer path for method exploration.
- The default source-space spacing is MNE `ico3`, yielding 1,284 cortical
  source points and 2,560 triangular faces. Points are emitted in FreeSurfer
  fsaverage millimeter coordinates with `coordinate_space: fsaverage_surface`.
- The diagnostic arbitrary-amplitude exporter remains available from Source Map
  Options. It runs in a `QThread`, writes the project-local files, then loads
  the emitted manifest through the existing importer. The worker orchestrates
  the calculation but does not put source math into the renderer or importer.
- The `Load source JSON` and `Load manifest` dialogs now prefer the last import
  folder, then the active project's 6D z-score output folder, then the 6C
  diagnostic amplitude output folder, then the active project root.
- The diagnostic amplitude exporter remains available from Source Map Options.
  When run, its project-local manifest path is
  `6 - Source Localization/L2-MNE Cortical Surface Beta/project_l2_mne_cortical_surface_beta_manifest.json`.
  The current default project path is the Phase 6D Hauk-style z-score export;
  a diagnostic amplitude manifest is not required for the viewer to display the
  default maps.

Done means:

- A real single-group project with compact per-participant workbooks can produce
  a validated prepared manifest plus condition payloads without changing
  project manifests, preprocessing outputs, Stats behavior, or workbook formats.
- The generated manifest can be loaded through the existing visualizer importer
  and condition dropdown.
- Generated output stays under the project root by default and rejects output
  directories outside the project root.
- The GUI remains responsive while source JSON generation runs.
  No offscreen Qt workflow is required for local verification.

### Phase 6D: Hauk-Style Source-Space Z-Score Mode

Status: Implemented. Phase 6D adds a dedicated Hauk-style L2-MNE
source-space z-score producer, a read-only FullFFT target/noise-bin project
input adapter, a project-local z-score export orchestrator, and automatic GUI
loading/building of the generated z-score manifest without putting source math
in the renderer or importer.

Objective:

- Replace the current arbitrary-unit beta display path, or add a selectable
  mode beside it, with source-space z-scored L2-MNE maps modeled on the
  frequency-domain FPVS source-estimation procedure used by Hauk, Rice, Volfart
  et al. (NeuroImage, 2021).
- Make the renderer-visible scale meaningful and publication-aligned:
  `value_label` should be `source-space z-score`, `source_value_unit` should be
  `z-score`, and the visualizer legend should display z-score min/max values.
- Keep all calculation work inside `source_producers/`. The renderer, importer,
  payload bridge, fsaverage display mesh loader, and GUI must not compute FFT
  bins, baseline correction, inverse estimates, or z-scores.

Hauk 2021 methodological target:

- Work in the FPVS frequency domain, not the time-domain evoked path.
- For each condition/frequency family, use topographies around the target
  oddball/base frequency harmonics and sum across the selected harmonics.
- Use L2 minimum-norm source estimation for those harmonic topographies.
- Apply the same baseline/noise correction and z-scoring logic in source space
  that Hauk 2021 describes for frequency-domain results: target-bin source
  amplitude should be baseline corrected against neighboring frequency bins,
  then divided by neighboring-bin source-space noise SD.
- Render the resulting source-space z-score map on the cortical surface.

Important equivalence boundary:

- The target is exact alignment with the Hauk-style **source-space z-score
  transformation** and payload semantics, not an unsupported claim that the
  current toolbox has the same acquisition model as Hauk 2021.
- Hauk 2021 used combined EEG/MEG, individual MRIs, individual head/source
  models, whitening across sensor types, loose orientation constraints, no
  depth weighting or noise normalization, and SNR=3 regularization. After Phase
  6H-A(1), the current beta project path uses MNE-native L2-MNE with
  `loose=0.2`, `depth=None`, `fixed=False`, `method="MNE"`, and
  `lambda2 = 1 / 9`, but it is still BioSemi64 EEG-only with an
  fsaverage/template head model and group-level topographies. Those differences
  must remain explicit in payload metadata and user-facing documentation until
  the toolbox actually supports them.
- The finished Phase 6D mode must therefore be named clearly, for example
  `l2_mne_cortical_surface_hauk_zscore_beta`, and metadata must state
  `hauk_2021_frequency_domain_zscore_aligned: true` plus the remaining
  limitations such as `sensor_modalities: EEG only`,
  `head_model: fsaverage template`, and `subject_mri: none`.

Implementation notes:

- Add a dedicated source producer module or focused extension under
  `src/Tools/LORETA_Visualizer/source_producers/`, such as
  `l2_mne_hauk_zscore.py` or a clearly named sibling orchestration function.
- Extend the project input layer so it can assemble both target harmonic
  topographies and neighboring-bin topographies for each selected harmonic.
  Do not change preprocessing or Stats harmonic-selection behavior silently.
- Prefer reading existing per-participant frequency-domain workbook sheets if
  they contain the required neighboring frequency bins. If current compact
  outputs do not contain enough neighboring-bin detail, Phase 6D must stop and
  document the missing upstream export rather than fabricating z-scores from
  BCA-only summaries.
- Use the same selected harmonic list as the Stats group-significant harmonic
  policy unless the user explicitly scopes a different Hauk-style harmonic
  policy for this source mode.
- Compute source estimates for target and neighboring-bin topographies using
  the same forward model, inverse settings, harmonic strategy, and reference
  assumptions within a run.
- Compute source-space baseline and z-score per source point from the
  neighboring-bin source estimates. The z-score map is the renderer payload;
  arbitrary L2-MNE amplitude remains diagnostic metadata, not the displayed
  primary scalar.
- Preserve the current project-local output discipline. Suggested output folder:
  `6 - Source Localization/L2-MNE Hauk Z-Score Beta/`.
- The visualizer should auto-scale or manually scale z-scores, and the legend
  should make it obvious when the displayed unit is z-score. A useful manual
  scale preset may include 1.64 to 1.96 or a user-selected positive z-score
  range. Display thresholds should remain user-facing renderer masks, not
  source-estimation calculations.

Definitions of done:

- A source-space z-score producer emits validated prepared payloads with:
  - `source_model: l2_mne_cortical_surface_hauk_zscore_beta`;
  - `value_label: source-space z-score`;
  - `metadata.source_value_unit: z-score`;
  - metadata listing selected harmonics, neighboring-bin policy, baseline
    correction rule, z-score denominator rule, forward model, inverse settings,
    sensor modality, and Hauk-alignment limitations.
- The source-space z-score mode uses target and neighboring-bin source estimates
  from the same inverse model. It does not derive z-scores from already summed
  BCA values alone.
- If the current project workbooks lack the neighboring-bin data needed for a
  legitimate Hauk-style source-space z-score, the producer raises a clear,
  tested error explaining the missing input and the required upstream export.
- The generated manifest contains all selected project conditions and can be
  loaded through the existing prepared-manifest importer without renderer
  changes.
- The control-panel legend displays z-score min/max values and the unit readout
  says `source-space z-score; unit: z-score` for these payloads.
- Focused tests cover:
  - neighboring-bin project input assembly;
  - z-score calculation on deterministic source-ready fixtures;
  - rejection when only BCA summaries are available;
  - payload metadata/format validation;
  - manifest import compatibility.
- Semantic Categories can be run through the mode only if the required
  neighboring-bin frequency-domain inputs are present. Otherwise the documented
  result is a precise upstream-data requirement, not a fake z-score map.
- No source-space z-score calculation is added to `renderer.py`, `gui.py`,
  `prepared_payload_importer.py`, `source_payloads.py`, `transforms.py`,
  `scalar_fields.py`, preprocessing, Stats, or project manifests.

Implementation notes completed:

- New calculation modules:
  - `source_producers/l2_mne_hauk_zscore.py`;
  - `source_producers/project_fullfft_inputs.py`;
  - `source_producers/project_l2_mne_hauk_zscore_export.py`.
- `project_fullfft_inputs.py` reuses the condition workbook discovery helper
  from `project_inputs.py`, so Hauk-style z-score generation reads both flat
  `Condition/*.xlsx` and grouped `Condition/Group/*.xlsx` workbook layouts.
- Hauk-style z-score maps are now the default project behavior: after
  fsaverage loads, the GUI auto-loads the existing project-local z-score
  manifest, or auto-builds it once in a worker when the manifest is missing.
  Reset view remains always visible. Manual z-score rebuilds,
  arbitrary-amplitude exports, and prepared JSON imports live in Source Map
  Options.
- The generated payloads preserve the full signed source-space z-score field
  for QC. Phase 6F changed the default L2-MNE cortical surface display from
  positive-only point filtering to opaque cortical paint where z-scores below
  the selected display cutoff are shown as the neutral gray cortex color. The
  default display cutoff is `z >= 1.64`.
- The z-score path reads `FullFFT Amplitude (uV)` only. It refuses BCA-only or
  compact-summary-only workbooks with a clear Phase 6D input error.
- After Phase 6H-A(1), the default project-built Hauk z-score model uses an
  MNE-native inverse operator and stores method metadata including
  `inverse_backend: mne_python`, `orientation_constraint: loose`,
  `loose_orientation: 0.2`, `fixed_orientation: false`,
  `depth_weighting: none`, `noise_normalization: none`, and `lambda2: 1 / 9`.
  Existing generated project manifests must be rebuilt to pick up these
  settings; the prepared payload/manifest schema is unchanged.
- GUI failure text now maps missing Stats-ready workbooks, missing selected
  harmonics, missing FullFFT sheets, and missing included FullFFT workbooks to
  a user-facing prerequisite message: re-run preprocessing, then open Stats and
  run `Export Stats-Ready Workbook` before returning to LORETA Visualizer.
- A real Semantic Categories validation run exported successfully under the
  active project root at
  `6 - Source Localization/L2-MNE Hauk Z-Score Beta/project_l2_mne_hauk_zscore_beta_manifest.json`.
  The manifest contains `Fruit vs Veg`, `Green Fruit vs Green Veg`,
  `Green Veg vs Red Veg`, `Red Fruit vs Green Fruit`, and `Veg vs Fruit`.
  The first payload reports `source_model:
  l2_mne_cortical_surface_hauk_zscore_beta`, `value_label:
  source-space z-score`, `source_value_unit: z-score`, and selected harmonics
  `[2.4, 4.8, 7.2, 9.6, 13.2, 20.4]`.
- After Phase 6E default-QC behavior was updated, Semantic Categories was
  regenerated with `include_flagged_subjects: false`, excluding `study-participant`, `study-participant`,
  and `study-participant` from source-map generation. The first regenerated payload reports
  24 included participants.

### Phase 6E: Source-Map Method QC And User Controls

Status: Implemented. Phase 6E adds user-facing method documentation and replaces
the inline Advanced control group with a small Source Map Options modal.

Objective:

- Keep detailed method explanation out of the compact tool panel and place it
  in a dedicated MkDocs page.
- Cite the FPVS EEG/MEG L2-MNE source-estimation publications that motivate the
  beta Hauk-style path:
  - Hauk et al. (2021), DOI `10.1016/j.neuroimage.2021.118460`;
  - Hauk et al. (2025), DOI `10.1162/imag_a_00414`.
- Expose the existing producer-side flagged-participant include/exclude option
  in the GUI so maps can be rebuilt with or without participants listed in
  `Flagged Participants.xlsx`.
- Keep source-map rebuild progress compact in the GUI and structured IDE logs.
  The later project-local validation report artifact summarizes completed
  source outputs after payloads and sidecars have been written.
- Do not change renderer behavior or move source-estimation logic into GUI,
  renderer, importer, bridge helpers, preprocessing, Stats, or project
  manifests.

Implementation notes completed:

- Added `docs/user/tools/source-localization-method.md` and wired it into
  `mkdocs.yml`.
- Updated `docs/user/tools/loreta-visualizer.md` to link to the method page and
  describe Source Map Options.
- Replaced the collapsed Advanced checkbox/inline controls with a
  `Source Map Options...` modal. The modal contains:
  - a short method summary;
  - `Include Stats QC flagged participants in source-map calculations`;
  - `Rebuild z-score maps`;
  - `Build diagnostic amplitude maps`;
  - `Load source JSON`;
  - `Load manifest`.
- `ProjectSourceMapExportWorker` now carries `include_flagged_subjects` to both
  the Hauk-style z-score producer and the diagnostic amplitude producer.
- The GUI logs one compact start line and one compact completion/failure line
  for project source-map rebuilds, including method/export mode, manifest path
  when available, condition count, and flagged/excluded participant counts.
- The renderer and display bridge were intentionally unchanged.
- Source-map rebuild defaults were updated after initial Phase 6E completion:
  participants listed in `Flagged Participants.xlsx` are excluded by default;
  the modal checkbox is an opt-in to include them.
- Project Hauk-style z-score rebuilds now write
  `source_validation_report.json` and `source_validation_report.md` beside the
  generated manifest. The report is produced from existing emitted files and
  does not compute source estimates or renderer-derived facts.

Done means:

- The MkDocs user nav includes a dedicated source-localization method page.
- The method page explains current beta status, inputs, z-score calculation,
  thresholded z-score display behavior, participant QC behavior, output files, and
  limitations.
- The visualizer offers a modal source-map options workflow instead of an
  inline Advanced section.
- Rebuilds exclude flagged participants by default and can include them on
  request without changing Stats behavior, preprocessing, or project manifests.
- Focused non-GUI checks cover changed helper behavior and the LORETA test suite
  still passes. GUI behavior is covered by a visible/manual smoke path because
  offscreen Qt is not run locally.

### Phase 6F: Opaque Cortical Surface Paint Mode

Status: Implemented. Phase 6F renders L2-MNE cortical-surface payloads as an
opaque pial brain with source values painted onto the cortex.

Objective:

- Make the current Hauk-style L2-MNE cortical surface maps easier to interpret
  by removing transparent brain/source opacity from this method's default view.
- Keep opacity controls and transparent-shell rendering available for
  volume/deep payloads and future LORETA/eLORETA methods.
- Preserve the signed source-space z-score payloads while displaying
  sub-threshold z-scores as a neutral gray cortex color and retained z-scores
  with the same heatmap ramp used by the transparent visualizer.
- Keep source estimation, z-score calculation, and project export logic
  unchanged.

Implementation notes completed:

- Added a display-only cortical paint helper that projects prepared L2-MNE
  cortical source values onto the higher-resolution pial display mesh using
  inverse-distance interpolation through `scipy.spatial.cKDTree`.
- The renderer automatically uses cortical paint for L2-MNE `surface_mesh`
  payloads and keeps the existing separate activation actor for volume, ROI,
  point, and deep-style payloads.
- The GUI hides brain/source opacity controls while cortical paint is active,
  keeps condition/scale/legend/show/reset/options controls, and exposes a
  Source Map Options > Display cutoff selector. Presets include `z >= 1.64`,
  `z >= 1.96`, `z >= 2.58`, `z >= 3.29`, and `z >= 3.89`.
- User docs and tool-local agent/architecture docs describe cortical paint as
  visualization interpolation only, not extra source-estimation precision.
- Publication-ready split-hemisphere layout, inflated display surfaces, and
  curvature/sulcal shading belong to Phase 6G and later view-mode slices;
  Phase 6F targets the current single pial display surface only.

Done means:

- L2-MNE cortical surface z-score maps render as an opaque pial cortical map.
- Z-scores below the selected display cutoff are visually indistinguishable
  from the gray base cortex; retained z-scores use the shared transparent-view
  heatmap colors.
- Existing volume/deep dummy payloads still use transparency and source opacity.
- Focused tests cover projection, non-mutation of payload values, and the
  cortical-vs-non-surface z-score display split.
- The display cutoff is documented as a renderer mask only. Hauk-style
  cluster-permutation significance masking remains future method work.

### Phase 6G: View Mode Selector And Split-Hemisphere Publication Viewer

Status: Implemented.

Objective:

- Add a right-panel display mode selector so users can switch between:
  - publication-style split-hemisphere cortical view;
  - fsaverage pial cortical surface map;
  - transparent brain mesh view for volume/deep and future LORETA/eLORETA
    payloads.
- Keep all modes reading the same prepared payload and scalar-range controls
  wherever scientifically appropriate.
- Preserve renderer/source-producer separation: view modes may transform or
  project already-computed display values, but must not compute source
  localization, z-scores, or statistical masks.

Implemented scope:

- The publication split-hemisphere mode is the default selected display mode.
- The split view uses fsaverage inflated hemisphere meshes when available,
  with pial hemisphere fallback if the inflated topology is unavailable or does
  not match the pial/source surface.
- The renderer preserves left/right fsaverage hemisphere surfaces at anatomical
  mesh load time, projects already-computed cortical values through pial/source
  coordinates, draws them on the split-view display surface, and places them
  side-by-side in a publication-oriented camera layout.
- The split view reads FreeSurfer `curv` morph data from the external
  fsaverage cache for gray-white curvature underlay shading, falls back to
  `sulc` if needed, and finally falls back to geometry-derived shading if no
  morph underlay is available.
- Split-view RGB colors combine the underlay and the existing heatmap ramp:
  sub-threshold/hidden source values show shaded cortex, while thresholded
  positive z-scores paint over that cortex.
- Left and right hemispheres can be rotated independently from the right panel.
  The existing Reset button restores the desired publication layout and camera.
- Switching conditions in publication split mode preserves the current camera,
  zoom, and hemisphere rotations; Reset is the explicit control for returning
  to the standard publication layout.
- The single cortical surface mode keeps the Phase 6F opaque cortical paint
  behavior.
- The transparent mesh mode remains available and keeps opacity controls. It is
  still the fallback-compatible path for volume/deep payloads and future
  LORETA/eLORETA volume methods.
- The side-panel figure exports are consolidated behind an Export Figures modal.
  The modal exposes only currently working export actions and reserves future
  figure export expansion for current-view, transparent-mesh, brain-mesh, and
  batch workflows.
- Publication figure exports follow `docs/agent/quality/figure-generation.md`:
  matching 600 DPI PNG/PDF outputs and shared Arial figure typography from
  `Main_App.exports.figure_style`.
- Transparent mesh mode uses normal alpha blending with depth peeling disabled
  because depth peeling caused the brain actor to disappear at opacity values
  below 100% on at least one Windows/VTK machine. Revisit only with visible
  cross-machine rendering checks.
- This is display-only shading. It is not a cluster-permutation mask and does
  not modify source values.
- Mode switching is immediate for the active condition and does not rebuild
  source JSON.
- All modes consume the same prepared payload. View-mode geometry transforms
  are display-only and do not compute source localization, z-scores, or
  statistical masks.

### Phase 6H: Manual Scientific Validation And Comparison

Status: Started. Phase 6H-A(1), Phase 6H-A(2), Phase 6H-A(3), Phase 6H-A(4),
and Phase 6H-A(5) are implemented.

Objective:

- Compare Semantic Categories source maps against condition scalp maps and
  expected posterior/anterior response patterns.
- Rebuild and compare maps with flagged participants included vs excluded.
- Record validation observations and unresolved scientific assumptions before
  adding another source-localization method.
- Decide whether the next method should be eLORETA/sLORETA volume, a mixed
  cortical-volume source space, or a more subject-specific forward model.

#### Phase 6H-A(1): Hauk-Style MNE-Native Group-Level Inverse Settings

Status: Implemented.

Objective:

- Update the existing group-level fsaverage/template Hauk z-score producer to
  use MNE-native L2-MNE settings that more closely match Hauk et al. while
  preserving the current prepared payload/manifest contract.
- Keep this as a group-level source-map export. Do not add participant-level
  source maps or cluster-permutation masking in this slice.

Implemented scope:

- `project_l2_mne_export.py` now builds an MNE-native inverse operator for real
  project exports using:
  - `method="MNE"` through `mne.minimum_norm.apply_inverse`;
  - `loose=0.2`;
  - `depth=None`;
  - `fixed=False`;
  - no dSPM/sLORETA/eLORETA noise normalization;
  - `lambda2 = 1 / 9`.
- The project-built model adds an EEG average-reference projection, uses an
  MNE ad hoc diagonal EEG covariance for the EEG-only template inverse, and
  converts project topographies from uV to V before MNE inverse application.
- `l2_mne_cortical.py` now supports estimator-backed forward models, while the
  deterministic fixture path can keep using the lightweight manual inverse for
  fast tests.
- `l2_mne_hauk_zscore.py` routes target and neighboring-bin topographies
  through the model's estimator when present, so target and noise bins use the
  same MNE-native inverse.
- Payload metadata now records the inverse backend, orientation constraint,
  loose-orientation value, depth weighting, noise-normalization choice, and
  remaining Hauk-alignment limitations.

Done means:

- Focused tests verify estimator-backed source estimation and metadata.
- Existing renderer, importer, payload schema, GUI, project workbooks, Stats,
  and preprocessing remain unchanged.
- Existing generated source JSON remains loadable but should be rebuilt for
  manual review because older payloads do not contain the 6H-A(1) method
  settings.

#### Phase 6H-A(2): Participant-Level Source Maps And Group Combination

Status: Implemented.

Objective:

- Compute source-space z-score maps per participant before group aggregation,
  then emit group-level prepared payloads that the existing renderer can load.
- Preserve the renderer/importer contract. Participant-level source estimation
  should live in `source_producers/`, and group combination should emit the same
  prepared payload/manifest shape the viewer already understands.
- Save participant-level source maps for a future individual-viewer workflow,
  while keeping the current viewer focused on group summary maps.

Implemented scope:

- `project_fullfft_inputs.py` now has a participant-preserving FullFFT adapter
  that keeps target/noise-bin topographies per participant instead of reducing
  them to group means.
- `l2_mne_hauk_zscore.py` computes source-space z-score maps per participant,
  writes group raw mean, median, and 20% trimmed-mean summary payloads, and
  writes a participant-level sidecar JSON for a future individual viewer.
- `project_l2_mne_hauk_zscore_export.py` defaults real-project z-score exports
  to the participant-first model and retains the old group-first export as
  `deprecated_group_first`.
- The Source Map Options dialog exposes the participant-first default and the
  deprecated group-first model selector without moving calculation logic into
  the GUI.
- User and agent docs describe the participant-first calculation order,
  summary outputs, deprecated fallback, Stats-QC inclusion rule, and
  pre-cluster-mask limitation addressed by Phase 6H-A(3).

Locked decisions:

- Participant inclusion follows the current project source-map default:
  Stats-QC-excluded participants are excluded unless the advanced option to
  include them is enabled.
- Harmonic selection uses the exact condition-level significant harmonic list
  from the Stats workflow. Do not add manual harmonic overrides in this slice.
- Neighboring-bin source-space z-scores use the same FPVS window policy as
  Stats: offsets `-10..-2` and `+2..+10`, excluding target and immediately
  adjacent bins, dropping the single finite min and max noise values, then
  computing the neighboring-bin mean and population SD.
- The first participant-level calculation order is:
  1. read each participant's sensor FFT amplitude topography for each selected
     harmonic and neighboring noise bin;
  2. estimate source values for each participant target and noise topography;
  3. sum source estimates across the selected significant harmonics;
  4. compute each participant's source-space z-score map from summed target
     source values against summed neighboring-bin noise source values;
  5. combine participant z-score maps into group summaries.
- Provide raw mean, median, and trimmed-mean group summaries immediately. The
  viewer should default to the mean participant z-score map unless the user
  selects a different summary.
- Keep the existing group-first Hauk z-score producer for now as a deprecated
  model available only through advanced settings. Mark it as intended for
  eventual removal once participant-first output is validated.
- Label the new method metadata explicitly, for example
  `l2_mne_fsaverage_participant_zscore_mean`,
  `l2_mne_fsaverage_participant_zscore_median`, and
  `l2_mne_fsaverage_participant_zscore_trimmed_mean`.
- Cluster-permutation masking is intentionally deferred to Phase 6H-A(3). The
  Phase 6H-A(2) participant sidecar is the required input for that later
  inferential mask.
- Keep the fsaverage-template source space for all participants in this phase.
  Subject-specific MRIs, subject-specific forward models, and mixed
  surface/volume source spaces remain future method work.

Documentation requirements:

- Update user-facing source-localization docs to explain the participant-first
  source-space z-score workflow, the available group summaries, the deprecated
  group-first fallback, the Stats-QC inclusion rule, and the absence of
  cluster-permutation masking.
- Update agent-facing LORETA Visualizer docs so future agents preserve the
  calculation/rendering separation and do not reintroduce group-first maps as
  the default method.
- Document that the renderer displays prepared payloads only; participant
  source estimation, z-score computation, and group aggregation belong in
  `source_producers/` and project export helpers.

Done means:

- Real-project export can build participant-first source-space z-score maps for
  each condition and write mean, median, and trimmed-mean group payloads plus a
  participant-level sidecar or equivalent project-local artifact for future
  individual viewing.
- Existing viewer condition selection can load the new group-summary payloads
  without renderer changes.
- Advanced settings can still opt into the deprecated group-first model, with
  clear labeling and low-noise status/log messages.
- JSON metadata distinguishes participant-first summaries from deprecated
  group-first exports and records the aggregation method, participant inclusion
  rule, harmonic list, neighboring-bin policy, and inverse settings.
- Focused tests prove that participant source z-score maps are computed before
  group aggregation, that all three aggregation summaries are deterministic,
  that deprecated group-first generation remains explicitly opt-in, and that
  the renderer-facing payload contract is unchanged.
- Compile, ruff, focused `tests/loreta`, GUI import audit, project-path audit,
  protected-edit/source-localization audits, and a documented visible manual
  smoke path pass. Do not run offscreen Qt tests locally.

#### Phase 6H-A(3): Source-Space Cluster-Permutation Masking

Status: Implemented.

Objective:

- Make publication-style L2-MNE cortical maps use an inferential source-space
  cluster mask as their primary display mask, matching the Hauk-style figure
  interpretation more closely than a crude display-only z cutoff.
- Preserve full signed source-space z-score values in the JSON payload for QC.
- Keep cluster statistics in `source_producers/`; the renderer must only obey
  a prepared mask and must not compute statistics.

Implemented scope:

- `l2_mne_hauk_zscore.py` computes one-sample, positive-tail sign-flip
  source-space cluster-permutation masks from participant z-score maps.
- Candidate clusters are formed from source vertices whose one-sample t
  statistic against zero passes the Hauk et al. 2025 publication-code
  positive-tail cluster-forming threshold. Mesh adjacency comes from the
  fsaverage/source-space surface faces.
- Cluster-level correction uses the maximum sign-corrected cluster mass from
  sign-flipped participant maps. Defaults are cluster-forming `p = .00001`,
  corrected cluster `alpha = .05`, deterministic seed `20260609`, and up to
  `10000` permutations, with exact sign flips when the participant count is
  small enough.
- Participant-first group-summary payloads now store
  `cluster_mask=source_space_cluster_permutation`,
  `cluster_mask_vertex_indices`, cluster settings, and significant-cluster
  summaries in metadata. Payload `values` remain unchanged.
- The participant sidecar records condition-level cluster-mask summaries for
  future individual/QC tooling.
- `cortical_paint.py` treats a non-empty producer-provided cluster mask as
  primary for L2-MNE cortical paint. Older unmasked payloads and empty Hauk
  masks fall back to the manual exploratory z-score display cutoff.
- `gui.py` labels masked maps as Hauk et al. (2025) cluster masked, warns when
  no vertices survive the cluster mask, and uses retained signed source z-score
  ranges for non-empty cluster-masked cortical displays.

Locked decisions:

- Cluster masking is enabled by default only for participant-first Hauk-style
  L2-MNE source-space z-score exports. The deprecated group-first model cannot
  produce this inferential mask.
- The cluster test is positive-tail against zero to match the Hauk et al. 2025
  source-space publication code. Negative source-space clusters are not part of
  the default Hauk mask.
- The manual z-score display cutoff remains available in Source Map Options
  for exploratory/unmasked payloads, underpowered masks, empty Hauk masks, and
  future display modes, but it is not the primary publication mask when a
  non-empty cluster mask is present.
- Cluster masks are source-space statistical results, not renderer filters.
  Future LORETA/eLORETA volume methods must add their own method-appropriate
  statistical masks rather than reusing cortical surface assumptions blindly.

Done means:

- Regenerated participant-first project payloads include cluster-mask metadata
  and retain full signed source values.
- Publication split-hemisphere and single cortical-surface paint views use the
  cluster mask automatically when it is present.
- Older unmasked source JSON remains loadable and falls back to the visual
  z-score threshold behavior.
- Focused tests prove cluster formation/correction, payload metadata, and
  cluster-mask display precedence over the old threshold fallback.
- Compile, ruff, focused `tests/loreta`, GUI import audit, project-path audit,
  protected-edit/source-localization audits, and a documented visible manual
  smoke path pass. Do not run offscreen Qt tests locally.

#### Phase 6H-A(4): Source-Space Lateralization Summary

Status: Implemented.

Objective:

- Add a descriptive source-space lateralization summary that can be compared
  against sensor-space BCA lateralization statistics.
- Keep this in the source producer/reporting layer. Do not compute
  lateralization from renderer actors, colors, camera views, or screenshots.

Implemented scope:

- `source_lateralization.py` computes participant and group-summary right/left
  source activation rows from already-computed source z-score maps.
- Participant-first Hauk-style exports write
  `source_lateralization_summary.json` and
  `source_lateralization_summary.csv` next to the source-map manifest and
  participant sidecar.
- The summary emits both whole-hemisphere rows and
  `occipitotemporal_lot_rot` rows. The initial LOT/ROT ROI is a transparent
  coordinate-defined posterior lateral source mask:
  `abs(x) >= 20 mm`, `y <= -35 mm`, and `z <= 35 mm`.
- The summary uses the producer source-space cluster mask when present. If no
  cluster mask exists, it falls back to positive z-score source values.
- The primary descriptive index is
  `(right_sum_positive_z - left_sum_positive_z) /
  (right_sum_positive_z + left_sum_positive_z)`, where positive values indicate
  right-lateralized source activation and negative values indicate
  left-lateralized source activation.

Locked decisions:

- This is a companion validation metric, not a replacement for the existing
  sensor-space BCA lateralization tests.
- The current hemisphere split uses source-space x coordinates:
  x < 0 is left, x > 0 is right, and midline sources are ignored.
- The current LOT/ROT source ROI is coordinate-defined because prepared
  payloads do not yet store stable original FreeSurfer source vertex IDs for
  label-based fsaverage ROI extraction.
- Values are positive z-score magnitudes so the summary tracks positive FPVS
  activation in the same direction as the current publication-style maps.
- The summary is descriptive. Formal source-space condition/lateralization
  inference is a future phase.

Done means:

- Participant-first project rebuilds emit JSON and CSV lateralization
  summaries under the project-local source localization output folder.
- Result metadata and user docs explain the formula, sign convention, value
  policy, and relationship to BCA lateralization.
- Focused tests prove helper math, JSON/CSV output, and project export path
  propagation.
- Compile, ruff, focused `tests/loreta`, GUI import audit, project-path audit,
  protected-edit/source-localization audits, and a documented visible manual
  smoke path pass. Do not run offscreen Qt tests locally.

#### Phase 6H-A(5): Hauk-Style Desikan-Killiany Temporal Laterality

Status: Implemented.

Objective:

- Replace the coordinate-defined LOT/ROT approximation as the Hauk-style
  source laterality target with a Desikan-Killiany temporal-lobe ROI matching
  the published description: inferior, middle, and superior temporal labels in
  the left and right hemispheres.
- Preserve the calculation/rendering boundary. Anatomical ROI masking belongs
  in `source_producers/`, and the renderer must not infer laterality from
  display actors, colors, camera orientation, screenshots, or interpolated
  display meshes.

Implemented scope:

- `project_l2_mne_export.py` preserves the MNE/fsaverage source-space vertex
  IDs and hemisphere labels when building the template cortical source space.
- `l2_mne_cortical.py` stores optional source vertex identity metadata in
  prepared source payload metadata without changing source values.
- `source_rois.py` reads fsaverage `aparc` labels through MNE/FreeSurfer and
  maps the `inferiortemporal`, `middletemporal`, and `superiortemporal` labels
  onto the current source-space vertices for each hemisphere.
- `source_lateralization.py` can prepend precomputed anatomical ROI rows before
  the existing coordinate-defined QC rows.
- `l2_mne_hauk_zscore.py` builds the Desikan-Killiany temporal ROI once per
  source model and includes `desikan_killiany_temporal_hauk` rows in the JSON
  and CSV source lateralization sidecars.
- Semantic Categories source maps were regenerated so the project-local
  sidecars include the new Hauk-style temporal ROI rows.

Locked decisions:

- The Hauk-style source laterality row is
  `desikan_killiany_temporal_hauk`.
- The coordinate-defined `occipitotemporal_lot_rot` row remains available only
  as a transparent QC/fallback comparison and should not be described as the
  Hauk-style manuscript method.
- Values remain positive z-score magnitudes within the producer's source-space
  cluster mask, matching the current publication-style positive-response map
  interpretation.
- The ROI is fsaverage-template based. Subject-specific anatomical ROIs remain
  future work because this workflow does not yet use individual MRIs.

Done means:

- Regenerated project source outputs include `desikan_killiany_temporal_hauk`
  rows in `source_lateralization_summary.csv` and
  `source_lateralization_summary.json`.
- Focused tests verify source vertex identity propagation, label-to-source
  mask construction, and Hauk-style ROI row emission.
- User and agent docs explain the ROI labels, source of the anatomical
  parcellation, formula/sign convention, value policy, and relationship to the
  older coordinate LOT/ROT QC row.
- Compile, ruff, focused `tests/loreta`, GUI import audit, project-path audit,
  protected-edit/source-localization audits, and a documented visible/manual
  smoke path pass. Do not run offscreen Qt tests locally.

#### Phase 6H-A(6): Source-Map Build Performance

Status: Planned.

Objective:

- Speed up first-time and manual real-project source-map builds without
  changing source-localization math, project input formats, or renderer
  behavior.
- Preserve the calculation/rendering boundary. Excel parsing, inverse-model
  cache management, source estimation, and performance logging belong in
  `source_producers/` and project export orchestration; the renderer and
  importer continue to consume prepared payloads only.
- Prefer project-local source-model caches over a global inverse cache so future
  projects can vary by acquisition format, montage, channel set, BIDS metadata,
  covariance policy, source method, or head/source model without silently
  reusing the wrong inverse model.

Planned scope:

- Replace the Hauk z-score FullFFT `openpyxl.load_workbook(..., read_only=True)`
  hot path in `project_fullfft_inputs.py` with an exact selected-column `.xlsx`
  XML reader, reusing `Tools.Stats.io.xlsx_selected_reader` where practical.
  The reader must load only `Electrode` plus the target and neighboring-bin
  columns required by `ProjectFullFftBinPlan`.
- Keep the existing FullFFT validation unchanged: exact selected harmonic
  columns, target/noise-bin plan consistency, BioSemi64 electrode count/order,
  finite numeric source topography values, flagged/excluded participant policy,
  and flat or condition/group workbook layouts.
- Add structured timing for source-map builds so logs separate FullFFT workbook
  parsing, input assembly, fsaverage/inverse-model preparation, participant
  source estimation, cluster-mask computation, payload writing, manifest
  validation, and validation-report generation.
- Add a project-local inverse-model cache under the source-localization output
  area, for example
  `6 - Source Localization/.inverse_cache/<method_signature>/`, with cache
  metadata that records the exact scientific/model inputs used to build it.
- Cache entries must be keyed by a strict model signature, not by project name
  alone. The signature should include method ID, MNE version, source spacing,
  channel names and order, montage/sensor-coordinate source, reference and
  projection policy, covariance policy or covariance hash, inverse settings
  (`method`, `lambda2`, `loose`, `depth`, `fixed`), fsaverage/template identity
  or path/hash, and any future project-specific acquisition/source-model inputs
  such as BIDS metadata, subject/head model identifiers, bad-channel policy, or
  source method.
- A cache hit may reuse only the inverse/model components. It must still read
  current project FullFFT inputs and regenerate z-score payloads, masks,
  lateralization summaries, manifests, and validation reports from the current
  project data and user options.
- A cache miss, missing/corrupt cache file, MNE version/signature mismatch, or
  method-setting mismatch must rebuild the inverse model and overwrite or
  create a new signature-specific project-local cache entry. It must not fall
  back to a stale global cache silently.
- The initial implementation may support only the current fsaverage BioSemi64
  `ico3` Hauk-style L2-MNE path. It should be structured so future BioSemi,
  BIDS, montage-varying, subject-specific, or alternate inverse-method projects
  can add their own signature fields and cache builders.
- Keep disk usage transparent in metadata and logs. Current `ico3` expectations
  are about 30-50 MiB per project cache entry; higher source spacings may be
  substantially larger and should remain opt-in.
- Consider a second optimization that batches all participant target/noise
  topographies for a condition through the estimator in one call, then splits
  results back into participant z-score maps. This must be guarded by focused
  equivalence tests because it changes execution shape while preserving
  numerical results.

Locked decisions:

- The root `.fpvs_cache/mne/MNE-fsaverage-data/` remains the shared fsaverage
  template data cache and is not duplicated per project.
- The inverse-model cache is project-local by default. A future global
  deduplication layer may be added only if it is signature-safe and never
  obscures which inverse model a project used.
- Cached inverse models are reusable model/preparation artifacts, not cached
  source-map results. They must not cache participant z-score values,
  condition maps, cluster masks, lateralization rows, validation reports, or
  renderer payloads as substitutes for rebuilding from current project inputs.
- Cache invalidation is scientific and structural: if any signature field
  changes, rebuild the inverse model rather than adapting the old cache.
- Manual rebuild and first-time automatic build must use the same optimized
  input reader and cache validation path.

Done means:

- First-time source-map builds and manual rebuilds use the selected-column
  FullFFT reader and continue to pass existing focused LORETA input and export
  tests.
- Rebuilding the same project with an unchanged inverse-model signature uses
  the project-local inverse cache and logs a clear cache hit. Changing spacing,
  channel order, inverse settings, MNE version, covariance policy, or other
  signature inputs causes a clear cache miss and rebuild.
- Cache metadata is written beside the project-local cache and includes enough
  information to audit the model used for generated source maps.
- Focused tests prove reader equivalence to the previous FullFFT adapter,
  missing-sheet/column diagnostics, cache hit/miss behavior, signature
  invalidation, corrupt-cache fallback, and optional batched-estimator numerical
  equivalence if batching is implemented.
- Compile, ruff, focused `tests/loreta`, protected-edit/source-localization
  audits, project-path audit, and a documented visible/manual smoke path pass.
  Do not run offscreen Qt tests locally.

## Integration Safety

- Preserve preprocessing order, project I/O formats, diagnostics, loading, analytics, Stats behavior, and export formats.
- Keep GUI changes PySide6-only.
- Import `QAction` only from `PySide6.QtGui` if actions are needed.
- Do not block the UI thread. If future mesh generation or real data loading becomes heavy, move it to `QThread` or `QRunnable` and communicate through signals.
- Workers must not touch widgets directly.
- Use structured logging for production diagnostics.
- Do not run offscreen Qt workflows locally.

## Verification Plan

Run narrow checks focused on changed files. Use `.venv1` when available; if the local checkout only has `.venv`, use the equivalent `.venv\Scripts\python.exe` path and report that substitution.

```powershell
.\.venv1\Scripts\python.exe -m compileall -q src\Tools\LORETA_Visualizer
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\gui\main_window.py src\Main_App\gui\sidebar.py src\Main_App\gui\icons.py src\Main_App\gui\project_workflows.py
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check gui
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check source-localization
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check source-localization-refs
.\.venv1\Scripts\python.exe -m pytest tests\loreta -q
.\.venv1\Scripts\ruff.exe check src\Tools\LORETA_Visualizer tests\loreta src\Main_App\gui\main_window.py src\Main_App\gui\sidebar.py src\Main_App\gui\icons.py src\Main_App\gui\project_workflows.py
```

Do not run pytest-qt/offscreen GUI tests locally. Add or update focused GUI smoke coverage definitions when useful, but document that local execution was skipped unless the user approves a safe visible GUI test environment.

Manual visible smoke path for Phase 1:

1. Launch the app visibly with the repo environment.
2. Confirm the LORETA Visualizer sidebar icon/logo appears under Workspace Tools.
3. Open the visualizer from the sidebar and confirm the beta warning appears:
   `Warning: the source localization tool is currently in beta. Features are subject to change.`
4. Click OK and confirm the workspace switches to the visualizer.
5. Confirm reopening the visualizer in the same app session does not repeat the
   warning.
6. Confirm the embedded viewport renders a nonblank 3D brain-like mesh.
7. Drag to rotate; use mouse-wheel/trackpad to zoom.
8. Switch to transparent mesh mode, move the transparency slider below 100%,
   and confirm the brain mesh remains visible while alpha changes immediately.
9. Use reset camera/default view.
10. Switch Home -> LORETA Visualizer -> another embedded tool -> LORETA Visualizer and confirm no crash, stale state, or duplicate widget behavior.
11. Confirm existing tools still open.

Additional visible smoke path for current and future slices:

1. Slice 2: confirm the status indicates fsaverage/anatomical mesh when available, and synthetic fallback when unavailable.
2. Slice 2: confirm no `src/fsaverage`, `src/quarantine/Tools/LORETA/fsaverage`, or other tracked fsaverage data appears in `git status`.
3. Slice 3: toggle activation visibility, base visibility, activation opacity, and base opacity independently.
4. Slice 3: adjust threshold/range controls and confirm the activation layer changes while the base mesh remains stable.
5. Slice 4: select multiple demo/project condition labels and confirm the activation pattern changes for each.
6. Phase 6D/6G: with a processed project, confirm the viewer auto-loads
   `6 - Source Localization/L2-MNE Hauk Z-Score Beta/project_l2_mne_hauk_zscore_beta_manifest.json`
   when present; if it is missing, confirm the visible status explains that the
   project must be reprocessed and the Stats-ready workbook exported when
   required inputs are absent.
7. Phase 6G: confirm publication split view, single cortical surface view, and
   transparent mesh view all render the same selected condition without
   rebuilding source JSON.

## Open Decisions

- Whether future source methods need an alternate harmonic strategy. Phase 6D
  chose Hauk-style summed sensor topographies before inversion: target
  topographies are summed across selected harmonics, matching-offset
  neighboring-bin topographies are summed across selected harmonics, and the
  source-space z-score is computed from those target/noise source estimates.
- Future method target after beta L2-MNE: LORETA/eLORETA volume, mixed
  cortical-volume source space, subject-specific forward models, or another
  explicitly scoped model.
