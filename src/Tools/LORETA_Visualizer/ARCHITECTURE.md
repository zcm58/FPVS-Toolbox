# LORETA Visualizer Architecture

This page is the tool-local architecture contract for agents working in
`src/Tools/LORETA_Visualizer/`.

## Purpose

The LORETA Visualizer is an embedded PySide6 tool for interactive 3D display of
a transparent anatomical brain mesh plus prepared source-activation payloads.
It is a new source-localization visualization branch. It is not a revival,
refactor, or design continuation of the removed `Tools.SourceLocalization`
implementation.

The first durable goal is rendering:

- real-time orbit, zoom, reset, and opacity controls;
- an external fsaverage-derived anatomical mesh when available;
- a synthetic fallback mesh when fsaverage is unavailable;
- synthetic scalar source maps for surface/deep rendering validation;
- a payload contract that future real source-localization producers can feed
  without changing renderer internals.

## Non-Goals

This directory must not own:

- LORETA, sLORETA, eLORETA, beamformer, MNE inverse, or other source-estimation
  calculations;
- FPVS frequency-domain statistics, harmonic selection, or condition effects;
- preprocessing, BDF loading, Stats methods, project manifests, diagnostics, or
  project-output discovery;
- retired `Tools.SourceLocalization`, `src/quarantine/**`,
  `src/Main_App/Legacy_App/**`, or `src/Main_App/PySide6_App/**` behavior;
- bundled fsaverage or MRI template data in source, quarantine, docs, or package
  data.

## Ownership

Tool implementation lives inside `src/Tools/LORETA_Visualizer/`.

Allowed outside this directory are narrow shell integrations already described
in the active execution plan: Main App sidebar/page/icon wiring, project-page
cleanup, focused tests, and documentation.

## Data Flow

The renderer consumes display-ready objects. Calculation outputs must be
prepared before they reach `renderer.py`.

```text
External future source calculation
        |
        | coordinates, scalar values, source metadata
        v
Tool-local bridge helpers
source_payloads.py + transforms.py + scalar_fields.py
        |
        | SourcePayload in renderer display space
        v
renderer.py
        |
        | PyVista actors and camera controls
        v
Embedded 3D viewport
```

The anatomical side follows a parallel path:

```text
External MNE/user fsaverage cache or synthetic fallback
        |
        v
fsaverage_mesh.py / synthetic_brain.py
        |
        | BrainMesh + MeshDisplayTransform
        v
renderer.py
```

Demo conditions are local validation data only:

```text
conditions.py + dummy_activation.py
        |
        | synthetic SourcePayload values
        v
renderer.py
```

## File Responsibilities

- `gui.py`: embedded page, controls, status text, fsaverage worker wiring, and
  user-triggered renderer updates.
- `renderer.py`: PyVista/VTK scene adapter. It displays base meshes, smooth
  visual mesh duplicates, prepared source payloads, opacity, scalar ranges, and
  camera controls. It must not calculate source estimates.
- `fsaverage_mesh.py`: external fsaverage discovery/fetch/read/decimation and
  construction of the anatomical display transform. It must not calculate
  source estimates.
- `synthetic_brain.py`: deterministic fallback brain mesh and `BrainMesh`
  dataclass.
- `conditions.py`: synthetic demo condition metadata.
- `dummy_activation.py`: deterministic demo-only scalar source maps.
- `prepared_source_fixture.py`: in-memory fixture that is shaped like a
  prepared source-map handoff from a future real calculation path. It validates
  and adapts coordinates/scalars but does not calculate source estimates.
- `prepared_payload_importer.py`: controlled JSON importer for prepared source
  payloads and source-payload manifests. Payload files include coordinates,
  scalar values, faces, coordinate-space labels, and metadata; manifest files map
  condition labels to relative payload JSON files. This is user-selected file
  input only, not project-output discovery.
- `examples/`: checked-in synthetic JSON payload and manifest fixtures that show
  the expected output shape for future source-localization producers. They are
  format examples only and are not source estimates.
- `source_payloads.py`: renderer-facing `SourcePayload` validation,
  finite-value filtering, metadata preservation, and payload conversion to
  display space.
- `transforms.py`: `MeshDisplayTransform` and coordinate-space constants.
- `scalar_fields.py`: visual scalar color stops and auto/manual color-limit
  resolution.

When the current mesh exposes a non-identity native/display transform, the GUI
demo payloads intentionally round-trip through native coordinates and
`source_payload_to_display(...)`. This exercises the same bridge that future
real source payloads should use, while keeping the values synthetic.

## Bridge Contract

The bridge helpers are the only place where future calculation outputs should be
normalized for rendering.

Allowed bridge behavior:

- validate `N x 3` coordinates and one scalar value per point;
- preserve faces, labels, source model metadata, and value labels;
- reject mismatched coordinate-space labels;
- convert native anatomical/source coordinates into renderer display space;
- normalize or bound values for visual color mapping;
- adapt future real data into `SourcePayload`.

Disallowed bridge behavior:

- compute inverse solutions or LORETA values;
- choose source-localization methods;
- compute FFT, SNR, BCA, harmonic significance, or condition effects;
- discover or write project source-localization outputs unless a future plan
  explicitly scopes project integration;
- copy design or code from removed Source Localization/eLORETA modules.

## Source Payload Contract

Future real source-localization producers should hand this tool a prepared
payload with:

- `format`: `fpvs-loreta-source-payload-v1`;
- `label`: human-readable source-map label;
- `points`: finite `N x 3` coordinates;
- `values`: finite scalar values aligned one-to-one with `points`;
- `coordinate_space`: explicit native/display/source coordinate-space label;
- `kind`: surface points, surface mesh, volume points, volume mesh, or ROI mesh;
- `source_model`: method/model description such as `volume_grid`,
  `cortical_surface`, or a future method-specific label;
- optional VTK-style `faces` for mesh payloads;
- optional metadata that describes provenance without changing renderer logic.

If a future method changes from LORETA to another inverse model, the renderer
should stay unchanged. The adapter/bridge should map the method output into this
payload contract.

Checked-in examples live in `examples/`. The fsaverage-native example is the
preferred reference shape for future calculations that produce coordinates in
the same source space as the anatomical mesh. The display-space examples and
manifest are intended for importer and GUI validation without requiring an
fsaverage cache.

## Verification

Use `.venv1` when available; in local checkouts without it, use the equivalent
`.venv\Scripts\python.exe` and report the substitution.

Focused checks for this tool:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Tools\LORETA_Visualizer\*.py
.\.venv1\Scripts\python.exe -m ruff check src\Tools\LORETA_Visualizer tests\loreta
.\.venv1\Scripts\python.exe -m pytest tests\loreta -q
.\.venv1\Scripts\python.exe .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check source-localization-refs
```

Do not run offscreen Qt workflows in this repo. For viewport behavior, document
a visible/manual smoke path instead.
