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
    metadata, and converts payloads into display space.
  - `transforms.py` owns native/source coordinate to display-coordinate
    transforms.
  - `scalar_fields.py` owns visual color limits and color stops.
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
  Future LORETA/eLORETA volume methods should become sibling producers rather
  than edits to renderer or bridge helpers.
- Demo heatmap data must stay clearly synthetic and local to this tool.

## File Responsibilities

- `gui.py`: embedded PySide6 page, controls, worker wiring, and status text.
- `renderer.py`: PyVista/VTK scene adapter, actors, camera, opacity, scalar map,
  and mesh display. No LORETA math.
- `fsaverage_mesh.py`: external MNE fsaverage discovery/fetch/read/decimation and
  anatomical display transform construction. No source estimates.
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
- `source_payloads.py`, `transforms.py`, and `scalar_fields.py`: bridge helpers
  that adapt prepared source payloads to the renderer.
- `source_producers/`: source-localization calculation methods that convert
  explicit source-ready inputs into validated prepared JSON payloads/manifests.
  They are calculation code, not display code, and should not depend on renderer
  classes or display mesh helpers. Phase 6A includes
  `source_producers/l2_mne_cortical.py` for source-ready beta L2-MNE cortical
  surface payloads and `source_producers/contracts.py` for method-neutral
  producer result types.

## Boundary Rules

- Do not import from `Tools.SourceLocalization` or `src/quarantine/**`.
- Do not consult or copy old Source Localization/eLORETA implementation code for architecture, naming, data flow, GUI design, settings, tests, or rendering choices.
- Do not recreate `src/Tools/SourceLocalization/**`, `src/Main_App/Legacy_App/**`, or `src/Main_App/PySide6_App/**`.
- Do not bundle fsaverage MRI/template data in `src/`, `src/quarantine/`, or package data. Fetch or locate fsaverage outside the repo through MNE/user cache paths only.
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

## Verification

Use the narrowest checks first:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Tools\LORETA_Visualizer\*.py
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check source-localization-refs
ruff check src\Tools\LORETA_Visualizer
```

If `.venv1` is unavailable in the checkout, use the local equivalent `.venv\Scripts\python.exe` and report the substitution.
