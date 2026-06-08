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

The first implemented source-ready method is a beta L2-MNE cortical surface
producer for FPVS oddball-response maps. It is one method that emits the same
prepared payload/manifest format expected from any later LORETA/eLORETA volume
or mixed source-space producer.

Phase 6C adds the first project-connected beta export path. It uses real
project condition topographies, an external MNE/fsaverage BioSemi64 template
EEG forward model, and the existing prepared payload/manifest bridge so real
project data can be viewed without changing renderer internals.

## Non-Goals

Outside the dedicated `source_producers/` subpackage, this directory must not
own:

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
prepared and validated before they reach `renderer.py`.

```text
Swappable source calculation producer
L2-MNE cortical surface beta, future LORETA volume, etc.
        |
        | prepared payload JSON / manifest JSON
        v
prepared_payload_validator.py
        |
        | validated coordinates, scalar values, source metadata
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

## Source Producer Boundary

Real source-localization methods should be implemented as calculation
producers, separate from display code. A producer owns method assumptions,
forward/inverse model construction, montage assumptions, FPVS harmonic handling,
condition aggregation, and scalar source metrics. Its output is a prepared
payload JSON file or a prepared manifest plus payload files.

Producer code may use scientific libraries such as MNE, but it must not import
or call `gui.py`, `renderer.py`, `fsaverage_mesh.py`,
`prepared_payload_importer.py`, `source_payloads.py`, `transforms.py`, or
`scalar_fields.py`. The importer and bridge helpers remain the display-side
translation layer.

Phase 6A added the first method as a beta L2-MNE cortical-surface producer:

- target BioSemi ActiveTwo 64-channel / 10-10 montage assumptions first;
- target group-level condition maps first, with individual maps later;
- use the Stats-locked group significant oddball harmonic list exactly;
- emit fsaverage-aligned cortical surface payloads with method metadata such as
  `l2_mne_cortical_surface_beta`;
- document that this method is cortical-surface source estimation and does not
  claim hippocampal or other deep localization.

Later LORETA/eLORETA volume methods should become sibling producers that emit
`volume_points`, `volume_mesh`, or ROI mesh payloads. They should not require
renderer, importer, or bridge-helper rewrites.

Phase 6C adds `project_l2_mne_export.py` as calculation-side orchestration. It
is allowed to read existing project workbooks through `project_inputs.py`, use
MNE to build an fsaverage/BioSemi64 template forward model, and write generated
payload/manifest JSON under the active project root. It must not update
`project.json`, change Stats outputs, modify preprocessing data, or teach the
renderer how L2-MNE works.

Phase 6D adds `l2_mne_hauk_zscore.py`,
`project_fullfft_inputs.py`, and
`project_l2_mne_hauk_zscore_export.py` as a separate Hauk-style
source-space z-score path. It reads raw project `FullFFT Amplitude (uV)` target
and neighboring frequency-bin topographies, sums selected harmonics in sensor
space, estimates target/noise source amplitudes through the same inverse model,
and writes `source_value_unit: z-score` payloads. It must not derive z-scores
from already summed BCA values or compact selected-harmonic summaries.

## File Responsibilities

- `gui.py`: embedded page, controls, status text, fsaverage worker wiring, and
  user-triggered renderer updates.
- `renderer.py`: PyVista/VTK scene adapter. It displays base meshes,
  prepared source payloads, opacity, scalar ranges, and
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
- `prepared_payload_validator.py`: producer-facing validation for prepared
  payload and manifest JSON. It owns format constants, schema descriptors, and
  cross-field checks. It does not render, calculate source estimates, or inspect
  project outputs.
- `source_producers/`: swappable source-localization calculation methods that
  read explicit source-ready inputs and write validated prepared
  payload/manifest JSON. Phase 6A includes method-neutral producer result
  contracts and `l2_mne_cortical.py`, a beta fixed-orientation L2-MNE cortical
  surface producer with a deterministic BioSemi64/10-10 source-ready fixture.
  Phase 6B includes `project_inputs.py`, a read-only adapter that assembles
  source-ready condition topographies from existing project workbooks. Phase 6C
  includes `project_l2_mne_export.py`, a project-local beta export that combines
  those topographies with an external MNE/fsaverage BioSemi64 template forward
  model and writes prepared source-map JSON. Phase 6D includes
  `l2_mne_hauk_zscore.py`, `project_fullfft_inputs.py`, and
  `project_l2_mne_hauk_zscore_export.py`, which produce project-local
  source-space z-score payloads from FullFFT target/noise-bin data. Later
  producers may use LORETA/eLORETA volume or mixed source-space models.
- `examples/`: checked-in synthetic JSON payload and manifest fixtures that show
  the expected output shape for future source-localization producers. They are
  format examples only and are not source estimates. This directory also holds
  the shape-level JSON Schema files for external tooling.
- `source_payloads.py`: renderer-facing `SourcePayload` validation,
  finite-value filtering, metadata preservation, positive-z display filtering,
  and payload conversion to display space.
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

For the beta L2-MNE cortical-surface method, expected payloads should identify
the method in `source_model`/metadata, use a cortical surface payload kind, and
describe the source metric clearly. A later volume LORETA method should use the
same outer payload shape but a volume or ROI payload kind and method-specific
metadata.

The current beta L2-MNE producer accepts source-ready arrays: channel names,
selected harmonic topographies, cortical source coordinates/faces, and a
channel-by-source leadfield. It writes payloads and manifests after validation.
`project_inputs.py` can assemble the selected harmonic topographies from
existing project workbooks, but it still does not compute Stats harmonic
selections, export preprocessing data, write project files, or build
subject-specific MRI forward models.

The project-input adapter reads the all-condition selected harmonics from the
Stats-ready workbook, reads compact per-participant electrode-level sheets
(`BCA (uV)` or `FFT Amplitude (uV)`), applies existing exclusion files, records
flagged participant status, and returns `L2MNEFPVSCondition` objects for
calculation producers.

The project L2-MNE exporter writes generated files under
`6 - Source Localization/L2-MNE Cortical Surface Beta/` by default. The manifest
can be loaded by the GUI's prepared-manifest importer. The GUI may trigger this
export in a worker thread and then load the resulting manifest, but all inverse
model construction and source-value calculation remain in `source_producers/`.

The project Hauk-style z-score exporter writes generated files under
`6 - Source Localization/L2-MNE Hauk Z-Score Beta/` by default. It uses the
same prepared-manifest importer as every other source payload. Its displayed
values are source-space z-scores, not arbitrary L2-MNE amplitude. The generated
payloads preserve the signed z-score field for QC, but the default activation
view renders only `z > 0` values so below-baseline troughs are not drawn as the
primary heatmap. The
neighboring-bin policy mirrors the Stats-style FPVS neighboring-bin window by
using offsets `-10..-2` and `+2..+10`, dropping the minimum and maximum
neighboring source amplitude per source point before computing the source-space
noise mean and population SD.

Checked-in examples live in `examples/`. The fsaverage-native example is the
preferred reference shape for future calculations that produce coordinates in
the same source space as the anatomical mesh. The display-space examples and
manifest are intended for importer and GUI validation without requiring an
fsaverage cache.

Future calculation producers should use `prepared_payload_validator.py` for
preflight validation before handing JSON to the GUI importer. The JSON Schema
files provide an external-tooling shape contract, while the Python validator
adds cross-field checks that the schema intentionally does not own.

## Verification

Use `.venv1` when available; in local checkouts without it, use the equivalent
`.venv\Scripts\python.exe` and report the substitution.

Focused checks for this tool:

```powershell
.\.venv1\Scripts\python.exe -m compileall -q src\Tools\LORETA_Visualizer
.\.venv1\Scripts\python.exe -m ruff check src\Tools\LORETA_Visualizer tests\loreta
.\.venv1\Scripts\python.exe -m pytest tests\loreta -q
.\.venv1\Scripts\python.exe .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check source-localization-refs
```

Do not run offscreen Qt workflows in this repo. For viewport behavior, document
a visible/manual smoke path instead.
