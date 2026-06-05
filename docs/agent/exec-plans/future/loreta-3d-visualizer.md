# LORETA 3D Source Localization Visualizer

## Status

Future plan. Not active implementation work.

## Date

Created: 2026-06-05

## Goal

Build an embedded, interactable 3D brain viewer tool in the existing Main App where:

- A transparent brain mesh is shown as the base layer.
- Users can control brain transparency.
- A second, independent volumetric/mesh layer visualizes LORETA-like heatmap activation values in the same coordinate space.
- The first release uses synthetic/dummy activation data for validation of interaction, rendering, and color scaling.

The user-facing goal is visual inspection of 3D oddball-response sources without disrupting existing preprocessing or runtime pathways.

## Scope Decision

Keep implementation isolated from active runtime behavior until fully stabilized.

- No changes to preprocessing order, project I/O formats, diagnostics, loading, or analytics contracts in early phases.
- No reactivation of legacy Source Localization/eLORETA runtime dependencies beyond this tool’s own visualization stack.
- The tool is introduced behind a dedicated feature path/flag and only wires into the app shell when explicitly enabled.
- Development remains on a separate branch (for example `codex/loreta-3d-visualizer`) until the user approves promotion.

## Proposed Boundaries

- New tool implementation should live under one dedicated package, e.g.:
  - `src/Main_App/tools/loreta_visualizer/`
- Keep shared helpers minimal and behind that package unless a truly reusable UI primitive is needed.
- Keep all new optional 3D dependencies optional at startup and gracefully degrade if missing.

## Target Areas (Planned)

- `src/Main_App/tools/loreta_visualizer/` (new package)
- Tool registration point in existing Main App tool/shell registry (single entry).
- Optional manifest/feature toggle location used to keep the tool disabled by default at launch.
- One smoke documentation path in `docs/` for manual visible verification.

## Execution Slices

### Slice 1: Tool shell + dummy 3D scene

Objective:
- Stand up a minimal embeddable view with:
  - mesh render area
  - interactive camera controls (orbit/pan/zoom)
  - brain transparency slider
  - baseline placeholder heatmap layer

DoD:
- 3D interaction works with synthetic mesh geometry.
- Transparency slider visibly updates the mesh alpha.
- No regressions in existing app startup.

### Slice 2: Independent layered rendering

Objective:
- Introduce a second layer using independent actor/data pipeline.
- Share spatial transform/coordinate frame with base mesh but independent scalar coloring.
- Add intensity scaling, color map selection, and range clamping.

DoD:
- Increasing activation increases heatmap intensity.
- Heatmap can be hidden/shown independently of base mesh visibility.
- Both layers remain aligned in the viewer.

### Slice 3: Lightweight user controls and persistence

Objective:
- Add small UI controls for:
  - threshold/scale
  - color map
  - layer opacities
  - reset/default view actions

DoD:
- Controls are persisted in tool config/session state only (no project format change).
- Viewer remains responsive.

### Slice 4: Optional data-binding seam

Objective:
- Add a deterministic adapter interface for real LORETA volumes later.
- Replace dummy dataset producer with optional external injection point.

DoD:
- Real data pathway can be connected without changing the rendering contract.

## Integration Safety

- Keep branch-local changes behind a single feature gate.
- Avoid touching existing `src/Main_App/processing/`, `diagnostics/`, `workers/`, `projects/` modules in initial implementation.
- Keep GUI updates in non-blocking patterns using existing worker model if future mesh precompute is heavy.

## Verification Plan

Run narrow checks focused on changed files.

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\tools\loreta_visualizer\*.py
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py
```

No offscreen Qt tests for local verification. Add documented visible/manual smoke path in a separate plan slice.

## Open Decisions

- Confirm preferred 3D backend (PyVista/VTK vs PyQtGraph GL vs direct Qt3D).
- Confirm where in the tool menu this visualizer should appear.
- Confirm first data source shape for the LORETA heatmap layer (point cloud vs volume grid vs cortical sheet mesh).
