# AGENTS.md

## Scope

This directory owns the embedded LORETA 3D visualizer only. Keep LORETA visualizer code, demo data, rendering adapters, fsaverage mesh loading helpers, and future visualizer-local adapters inside `src/Tools/LORETA_Visualizer/` unless a plan explicitly scopes shell integration.

This is a completely new source-localization development branch. Retired Source Localization/eLORETA code, quarantine code, legacy launchers, historical settings, and old GUI workflows are not design inputs for this tool. Future design choices should be made from the current visualizer payload contract, current Main App embedding patterns, current scientific requirements, and current library capabilities only.

The goal of this tool is to render anatomical context and source-activation
payloads in real time. It is not the source-localization calculation engine.
Future real LORETA, sLORETA, eLORETA, beamformer, MNE, or other inverse-method
implementations should prepare coordinates and scalar values elsewhere, then
hand them to this directory through the helper/payload bridge.

The first implemented source-ready method is a beta L2-MNE cortical-surface
source-map producer for FPVS oddball responses. Treat it as one swappable
calculation method, not as the renderer's native model. Later LORETA/eLORETA
volume or mixed source-space methods should be able to emit the same prepared
payload/manifest contract without changing renderer or display-translation
logic.

The first project-connected export path is Phase 6C. It writes beta L2-MNE
cortical-surface prepared JSON from real project topographies under the active
project root. Phase 6D adds a separate Hauk-style L2-MNE source-space z-score
export path that reads raw `FullFFT Amplitude (uV)` target and neighboring-bin
topographies, applies the same inverse model to target and noise bins, then
writes z-score payloads. Both paths are calculation-side orchestration; they
must remain in `source_producers/` and must not move source-estimation logic
into the GUI, renderer, importer, fsaverage display mesh loader, or bridge
helpers.

Phase 6E adds user-facing source-method documentation and GUI source-map
options only. Source-map generation excludes participants listed in
`Flagged Participants.xlsx` by default; the Source Map Options modal may
explicitly include them for comparison, then pass that choice to the project
source producer. It must not calculate source values or change renderer
behavior.

Phase 6F adds opaque cortical surface paint rendering for L2-MNE cortical
surface payloads. This is a display-only renderer mode: it may interpolate
already-computed source values onto the higher-resolution pial display mesh,
and apply a user-selected z-score display cutoff, but it must not compute or
alter source-localization values.

Phase 6G adds a display-mode selector and makes the publication-style
split-hemisphere cortical view the default selected cortical display. This mode
uses inflated left/right display meshes when fsaverage provides topology-matched
inflated surfaces, falls back to pial split surfaces otherwise, projects the
same prepared cortical payload values through pial/source coordinates, and lets
the user rotate each hemisphere for inspection. Reset must restore the intended
publication layout. The split view may use FreeSurfer `curv` or `sulc` morph
data as a gray-white curvature underlay beneath the heatmap. It is still a
display-only renderer mode, not a new source-localization method or
statistical mask.

Post-6G hardening keeps automatic fsaverage installs in the repository-root
`.fpvs_cache/mne/MNE-fsaverage-data/` cache, supports flat and
condition/group workbook layouts for project source-map inputs, gives users a
clear preprocessing/Stats-export prerequisite message when source-map inputs
are missing, and uses driver-tolerant alpha blending instead of VTK depth
peeling for transparent mesh modes.

Phase 6H-A(1) updates the real-project Hauk-style L2-MNE path to use an
MNE-native inverse estimator with `method="MNE"`, `loose=0.2`, `depth=None`,
`fixed=False`, no dSPM/sLORETA/eLORETA noise normalization, and
`lambda2 = 1 / 9`. Keep that estimator inside `source_producers/`; renderer,
GUI, importer, display transforms, and fsaverage display mesh helpers must
remain unaware of inverse-operator details.

Phase 6H-A(2) makes participant-first Hauk-style source-space z-score maps the
default real-project z-score model. The project adapter must preserve each
included participant's FullFFT target/noise-bin topographies, source-estimate
each participant independently, compute participant source-space z-score maps,
and only then aggregate those z-score maps into group raw mean, median, and 20%
trimmed-mean payloads. The participant sidecar is for future individual viewing;
the renderer still loads the group prepared payloads. The older group-first
model is a deprecated advanced fallback only and must not be treated as the
default design precedent.

Phase 6H-A(3) adds source-space cluster-permutation masks for participant-first
Hauk-style L2-MNE z-score maps. The mask is computed only in
`source_producers/` from participant source maps, saved as prepared payload
metadata, and used as the primary publication-style display mask when present.
The renderer and cortical paint helpers may obey `cluster_mask_vertex_indices`,
but they must not compute t statistics, sign flips, clusters, or p-values. The
manual z-score display cutoff is a fallback/exploratory display setting for
unmasked payloads and must not be described as inferential.

Phase 6H-A(4) adds a descriptive source-space lateralization summary for
participant-first Hauk-style L2-MNE z-score maps. It is computed only in
`source_producers/` from already-computed participant and group source maps,
using the producer cluster mask when present. It writes CSV/JSON sidecars for
right-minus-left source activation and a source lateralization index. It emits
both whole-hemisphere and coordinate-defined LOT/ROT occipito-temporal ROI
rows. It is a companion validation metric and must not replace the existing
sensor-space BCA lateralization statistics.

Phase 6H-A(5) makes the Hauk-style source laterality target
Desikan-Killiany temporal label based instead of coordinate-box based. Project
exports preserve fsaverage source vertex IDs and hemisphere labels, read
fsaverage `aparc` labels, and emit a primary
`desikan_killiany_temporal_hauk` ROI row from the combined inferior, middle,
and superior temporal labels in each hemisphere. The coordinate LOT/ROT row
remains only as a transparent QC/fallback row. Keep label reading and ROI
masking in `source_producers/`; renderer, GUI, importer, and display helpers
must not infer anatomical ROIs from actors, colors, screenshots, or display
coordinates.

Project Hauk-style z-score exports also write
`source_validation_report.json` and `source_validation_report.md` beside the
manifest. The report is generated in `source_producers/` from already-emitted
manifest, payload, participant-sidecar, and lateralization files. It is a
review artifact only and must not compute inverse estimates, cluster masks,
lateralization statistics, or renderer-derived facts.

Allowed outside this directory:

- `src/Main_App/gui/main_window.py` for the embedded page factory/open method.
- `src/Main_App/gui/sidebar.py` for the sidebar entry.
- `src/Main_App/gui/icons.py` for the sidebar icon.
- `src/Main_App/gui/project_workflows.py` for cached page cleanup.
- Agent docs and focused tests.

Do not spread LORETA implementation code into unrelated `Main_App`, `Tools`, Stats, preprocessing, project I/O, diagnostics, or worker modules.

## Architecture Rules

- Rendering is independent from LORETA numerical computation.
- fsaverage/anatomical mesh loading is independent from LORETA numerical computation.
- Future LORETA-value calculation should produce a prepared mesh/point/volume payload in the same coordinate space as the anatomical mesh, then pass that payload into this visualizer through a narrow adapter.
- The renderer should only know how to display base meshes and activation payloads; it should not compute source-localization values.
- The fsaverage loader should only locate/fetch/read anatomical surfaces; it should not compute source-localization values or condition statistics.
- Helper modules are the bridge between future calculation outputs and
  rendering:
  - `source_payloads.py` validates prepared coordinates/scalars, stores source
    metadata, filters renderer-facing display values when explicitly scoped
    such as positive-only non-surface z-score display, and converts payloads
    into display space.
  - `transforms.py` owns native/source coordinate to display-coordinate
    transforms.
  - `scalar_fields.py` owns visual color limits and color stops.
  - `cortical_paint.py` owns display-only projection from prepared L2-MNE
    cortical source meshes onto the pial display mesh.
  - `fsaverage_mesh.py` owns anatomical mesh loading and display transforms.
- Helper modules may adapt, validate, normalize for display, and transform
  already-computed values. They must not compute inverse solutions, frequency
  statistics, source estimates, or condition effects.
- Calculation producers live in the separate `source_producers/` subpackage and
  should write prepared payload JSON/manifest JSON that validates before import.
  Producers may use MNE or other scientific libraries, but they must not import
  `gui.py`, `renderer.py`, `fsaverage_mesh.py`,
  `prepared_payload_importer.py`, `source_payloads.py`, `transforms.py`, or
  `scalar_fields.py`.
- The L2-MNE producer should stay labeled beta, cortical-surface only, and
  method-specific in metadata, for example `l2_mne_cortical_surface_beta`.
  The Hauk-style z-score producer should stay labeled beta and method-specific,
  for example `l2_mne_cortical_surface_hauk_zscore_beta`, with
  `source_value_unit: z-score`.
  Future LORETA/eLORETA volume methods should become sibling producers rather
  than edits to renderer or bridge helpers.
- Never derive source-space z-scores from already summed BCA values or compact
  selected-harmonic summaries. The z-score path needs raw target and
  neighboring frequency-bin source estimates from the same inverse model. If
  the required FullFFT bins are unavailable, raise a clear producer/input error.
- Demo heatmap data must stay clearly synthetic and local to this tool.

## File Responsibilities

- `gui.py`: embedded PySide6 page, controls, worker wiring, and status text.
- `renderer.py`: PyVista/VTK scene adapter, actors, camera, opacity where
  relevant, scalar map, cortical paint display, split-hemisphere publication
  display, and mesh display. It explicitly disables depth peeling so
  transparent meshes remain visible across supported Windows/VTK driver stacks.
  No LORETA math.
- `fsaverage_cache.py`: shared root-local/configured fsaverage cache path
  helpers. Automatic fetches use `.fpvs_cache/mne/MNE-fsaverage-data/`;
  explicit `FPVS_FSAVERAGE_SUBJECTS_DIR` overrides are rejected if they point
  under `src/` or `docs/`, while stale generic MNE config candidates there are
  ignored so the root-local cache can still be used.
- `fsaverage_mesh.py`: MNE fsaverage discovery/fetch/read/decimation and
  anatomical display transform construction, including display-only
  topology-matched hemisphere meshes for publication layout. The combined mesh
  remains pial for existing single-surface and transparent views; inflated
  surfaces and optional `curv`/`sulc` underlay values are only a split-view
  display canvas. No source estimates.
- `synthetic_brain.py`: fallback/demo mesh model.
- `conditions.py` and `dummy_activation.py`: deterministic synthetic conditions
  and demo-only source maps.
- `prepared_source_fixture.py`: in-memory source-map fixture shaped like a
  future real-data handoff, with coordinates/scalars/faces/metadata adapted
  through the payload bridge and no inverse-solution math.
- `prepared_payload_importer.py`: controlled JSON importer for already-prepared
  source payloads and source-payload manifests. It validates file content and
  adapts into renderer payloads; it must not discover project outputs or
  calculate source estimates.
- `prepared_payload_validator.py`: producer-facing payload/manifest validation,
  format constants, schema descriptors, and cross-field rules. It must not
  render, inspect projects, or calculate source estimates.
- `examples/`: checked-in synthetic JSON payload and manifest examples for the
  prepared source-map contract. Keep examples small, deterministic, and clearly
  marked as not computed from EEG. Keep JSON Schema files here aligned with the
  Python validator and checked-in examples.
- `source_payloads.py`, `transforms.py`, `scalar_fields.py`, and
  `cortical_paint.py`: bridge helpers that adapt prepared source payloads to
  the renderer. Z-score payloads should keep signed values in JSON. L2-MNE
  cortical-surface z-score payloads render as opaque cortical paint with
  producer-provided cluster masks shown as activation and unmasked vertices
  shown as gray cortex. If no producer mask is present, the manual z-score
  display cutoff remains the fallback behavior. Empty exact small-sample masks
  whose minimum possible corrected p-value is above the selected alpha are
  underpowered display masks: warn the user and fall back to the exploratory
  manual cutoff without changing saved source values or computing statistics in
  the renderer. Non-surface z-score payloads may still use positive-only
  display filtering.
- `source_producers/`: source-localization calculation methods that convert
  explicit source-ready inputs into validated prepared JSON payloads/manifests.
  They are calculation code, not display code, and should not depend on renderer
  classes or display mesh helpers. Phase 6A includes
  `source_producers/l2_mne_cortical.py` for source-ready beta L2-MNE cortical
  surface payloads and `source_producers/contracts.py` for method-neutral
  producer result types. Phase 6B includes
  `source_producers/project_inputs.py`, a read-only project workbook adapter
  that assembles 64-channel condition topographies from flat condition folders
  or condition/group folders for source producers. Phase 6C includes
  `source_producers/project_l2_mne_export.py`, which combines those
  project topographies with an external MNE/fsaverage BioSemi64 template
  forward model and writes project-local prepared source JSON. Phase 6D includes
  `source_producers/l2_mne_hauk_zscore.py`,
  `source_producers/project_fullfft_inputs.py`, and
  `source_producers/project_l2_mne_hauk_zscore_export.py`; together they read
  project FullFFT target/noise bins from the same flat or grouped workbook
  layouts, compute Hauk-style source-space z-scores, compute participant-first
  source-space cluster-permutation masks, write source-space lateralization
  summary sidecars, preserve fsaverage source vertex identity for anatomical
  ROI summaries, and write project-local z-score prepared source JSON.
  `source_rois.py` maps named fsaverage anatomical label definitions, including
  the Hauk-style Desikan-Killiany temporal ROI, onto already-computed source
  spaces. `source_lateralization.py` computes descriptive right/left source
  summaries from already-computed source values; it must not estimate sources,
  perform lateralization statistics, or inspect renderer state.
  `source_validation_report.py` summarizes already-written source output files
  into project-local JSON/Markdown review artifacts; it must not calculate
  source values, run statistics, or inspect renderer state.

## Boundary Rules

- Do not import from `Tools.SourceLocalization` or `src/quarantine/**`.
- Do not consult or copy old Source Localization/eLORETA implementation code for architecture, naming, data flow, GUI design, settings, tests, or rendering choices.
- Do not recreate `src/Tools/SourceLocalization/**`, `src/Main_App/Legacy_App/**`, or `src/Main_App/PySide6_App/**`.
- Do not bundle fsaverage MRI/template data in `src/`, `docs/`,
  `src/quarantine/`, or package data. Automatic fetches should install into the
  untracked FPVS Toolbox root cache at
  `.fpvs_cache/mne/MNE-fsaverage-data/`. Explicit
  `FPVS_FSAVERAGE_SUBJECTS_DIR` overrides may point elsewhere only if they do
  not target source or docs paths; stale generic MNE config candidates that do
  target those forbidden paths are ignored.
- Do not re-enable VTK depth peeling for transparent mesh modes unless the
  target Windows/VTK driver behavior has been visibly retested. The current
  renderer deliberately uses plain alpha blending because depth peeling made
  translucent brain meshes disappear on at least one supported machine.
- Do not change preprocessing order, Stats methods, BDF loading, project manifests, exports, diagnostics, or app-wide project I/O for visualizer-only work.
- Do not write LORETA visualizer settings into `project.json` unless a future plan explicitly scopes project-level real-data integration.
- Do not add real-data file discovery, project-output integration, source
  calculation, or method selection without updating the active exec plan and
  this local architecture guidance.
- Do not treat the beta L2-MNE cortical-surface method as a required design
  choice for future LORETA/eLORETA volume methods. The shared design choice is
  the prepared payload/manifest contract, not the inverse method.
- Do not extend Phase 6A into project workbook discovery, participant looping,
  preprocessing exports, Stats harmonic-selection changes, or project manifests
  without updating the active exec plan first.
- Project input assembly may read existing project workbooks and QC summaries
  through `source_producers/project_inputs.py`, but it must not write project
  files, update Stats metadata, alter workbooks, change participant exclusions,
  or use local real-project paths in tests.
- Project source-map export may write generated payload/manifest JSON under
  the active project root through `source_producers/project_l2_mne_export.py`.
  Keep the default output project-local, reject silent output escapes, and do
  not write to `project.json` unless a future plan explicitly scopes that.
- Project Hauk-style z-score export may write generated payload/manifest JSON
  under the active project root through
  `source_producers/project_l2_mne_hauk_zscore_export.py`. Keep the default
  output project-local, reject silent output escapes, and do not write to
  `project.json` unless a future plan explicitly scopes that.
- Do not change the checked-in prepared JSON examples in a way that implies
  renderer ownership of LORETA math. They are output-format examples for future
  calculation producers and importer tests only.
- Keep producer validation separate from display conversion. If a future source
  method needs new coordinate metadata, extend the prepared payload contract
  deliberately; do not let renderer internals leak into validation.

## GUI And Worker Rules

- Use PySide6 only.
- Keep long or network-backed work, including fsaverage fetch/load and future real data loading, off the UI thread with `QThread` or `QRunnable`.
- Workers must not touch widgets directly; use signals.
- Keep startup resilient: missing PyVista/VTK/MNE/fsaverage should show inline status and synthetic fallback rather than crashing the Main App.
- Do not run offscreen Qt workflows in this repo; use non-GUI checks plus visible/manual smoke paths.
- Keep source-map rebuild/import controls in the Source Map Options modal unless
  a future plan explicitly scopes a different interaction model.
- Keep figure export actions in the Export Figures modal. The side panel should
  expose a single Export Figures entry point; individual export formats or
  display-specific figure actions should be added inside that modal as they
  become real, enabled workflows.
- Publication figure exports should follow
  `docs/agent/quality/figure-generation.md`: write matching 600 DPI PNG/PDF
  outputs and use `Main_App.exports.figure_style` for Arial figure typography.

## Verification

Use the narrowest checks first:

```powershell
.\.venv1\Scripts\python.exe -m compileall -q src\Tools\LORETA_Visualizer
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check source-localization-refs
ruff check src\Tools\LORETA_Visualizer
```

If `.venv1` is unavailable in the checkout, use the local equivalent `.venv\Scripts\python.exe` and report the substitution.
