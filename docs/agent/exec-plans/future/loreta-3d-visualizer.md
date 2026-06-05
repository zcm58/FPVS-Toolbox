# LORETA 3D Brain Visualizer

## Status

Phase 1, Phase 2, and Phase 3 implemented on `codex/loreta-3d-visualizer`. Future slices below should stay on that branch until merge-back into `codex/publication-report-workflow`.

## Date

Created: 2026-06-05
Updated: 2026-06-05

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

Core design rule: rendering, fsaverage/anatomical mesh construction, and LORETA numerical calculation are separate concerns. This tool may render a prepared LORETA mesh/point/volume payload in the same 3D coordinate space as the fsaverage brain mesh, but computing the LORETA values belongs to a separate future implementation and should not be mixed into rendering or fsaverage mesh loading code.

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
- Source Localization/eLORETA is removed from active runtime. `src/Tools/SourceLocalization/**` must remain empty of source files, and this visualizer must not import from `Tools.SourceLocalization` or `src/quarantine/**`.
- Future-agent local rules for this tool live in `src/Tools/LORETA_Visualizer/AGENTS.md`.

## Branch And Promotion Policy

Implementation must start on a new branch before code changes:

```powershell
git switch -c codex/loreta-3d-visualizer
```

Branch expectations:

- Keep the feature isolated on the branch until the user approves promotion.
- On the branch, the sidebar entry should be visible so the embedded tool can be manually tested like the other tools.
- Before merging into a release branch or mainline, decide whether the tool remains visible by default or moves behind an explicit feature flag.
- Do not use branch work as permission to touch preprocessing, Stats methods, project manifests, BDF loading, diagnostics, or active Source Localization paths.

## Proposed Boundaries

New tool implementation:

- `src/Tools/LORETA_Visualizer/`
  - `AGENTS.md`: scoped rules for keeping LORETA visualizer code self-contained and separating rendering from future LORETA computation.
  - `__init__.py`: public tool surface.
  - `gui.py`: embedded PySide6 page/window class.
  - `renderer.py`: PyVista/VTK rendering adapter, lazy imports, actor/camera helpers.
  - `synthetic_brain.py`: deterministic synthetic mesh/activation placeholders used for viewer validation.
  - `fsaverage_mesh.py`: lazy fsaverage fetch/load/decimation helpers for Slice 2.
  - `dummy_activation.py`: deterministic synthetic LORETA-like condition data for Slice 3 and Slice 4.
  - `conditions.py`: condition list/model helpers for Slice 4.
  - `settings.py` or `state.py`: tool-local viewer settings/session defaults if needed.

Main App shell integration:

- `src/Main_App/gui/main_window.py`: add lazy import/page factory/open method for the embedded visualizer.
- `src/Main_App/gui/sidebar.py`: add a Workspace Tools sidebar button.
- `src/Main_App/gui/icons.py`: add a dedicated sidebar icon/logo key for the visualizer.
- `src/Main_App/gui/project_workflows.py`: retire any cached `_loreta_visualizer_page` if the tool becomes project-aware.

No other production module should receive LORETA-specific implementation code unless this plan is explicitly revised. Keep visualizer logic, demo payloads, mesh adapters, rendering adapters, and future narrow real-data adapters inside `src/Tools/LORETA_Visualizer/`.

Avoid:

- `src/Main_App/tools/**` unless this plan is explicitly revised to introduce that package.
- `src/Tools/SourceLocalization/**`.
- Imports from `src/quarantine/**`.
- Restoring old legacy eLORETA launchers, settings, tests, or GUI paths.
- Writing LORETA settings into `project.json` in Phase 1.
- Bundling `fsaverage` MRI/template data in `src/`, `src/quarantine/`, or package data. Fetch or locate fsaverage outside the repo only.
- Computing LORETA/source-localization values inside `renderer.py`, `fsaverage_mesh.py`, or GUI widget code.
- Adding LORETA-specific computation to preprocessing, Stats, diagnostics, or project I/O modules.

## Phase 1: Embedded Real-Time Brain Viewer

Objective:

- Stand up the embedded tool as a first-class workspace page.
- Render a brain-like mesh in real time using PyVista/VTK embedded in PySide6.
- Add interaction controls:
  - orbit/drag rotation;
  - mouse-wheel or trackpad zoom;
  - explicit zoom in and zoom out buttons;
  - reset camera/default view button;
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

Status: Implemented. The visualizer starts with the synthetic fallback, checks for an existing external fsaverage cache without fetching, and provides a `Fetch/load fsaverage` control that loads fsaverage through MNE outside the repo.

Objective:

- Replace the Phase 1 placeholder mesh with an actual anatomical brain surface.
- Prefer fsaverage as the first target, loaded through MNE rather than bundled into the repo.
- Use a lazy mesh loader that can:
  - locate an existing fsaverage subject directory if configured;
  - fetch fsaverage through `mne.datasets.fetch_fsaverage(...)` into an external user/cache location when missing;
  - read an appropriate surface with `mne.read_surface(...)`;
  - convert vertices/faces into PyVista `PolyData`;
  - optionally decimate or use a lower-density surface for responsive interaction.
- Keep the Phase 1 camera, zoom, reset, and transparency controls working with the real mesh.
- Gracefully fall back to the synthetic placeholder mesh if fsaverage is unavailable, fetch is declined/unavailable, or the surface cannot be read.

Implementation notes:

- Do not place fsaverage files under `src/`, `src/quarantine/`, tracked docs, or package data.
- Store any fetched template data in the standard MNE/user cache or another user-writable cache path outside the repo.
- Keep mesh loading lazy. If fetching/loading is slow, move it to `QThread` or `QRunnable` and update the viewport through signals.
- Add clear inline status for "Using fsaverage", "Fetching fsaverage", and "Using synthetic fallback".
- Consider loading a pial/inflated surface pair later, but Slice 2 only needs one usable anatomical mesh.

Done means:

- The visualizer can render a real fsaverage-derived brain mesh.
- Transparency, rotate/orbit, zoom in/out, and reset view continue to work.
- Missing fsaverage does not crash app startup or the embedded page.
- No fsaverage data is added to the repo or quarantine tree.
- Existing synthetic placeholder remains available as a fallback/debug path.

## Phase 3: Dummy LORETA Heatmap Layer

Status: Implemented. The visualizer renders a synthetic posterior/occipital activation point-cloud layer in the current mesh coordinate space, with independent visibility and opacity controls. Higher dummy values use the red end of the `Reds` colormap.

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
.\.venv1\Scripts\python.exe -m py_compile src\Tools\LORETA_Visualizer\*.py
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\gui\main_window.py src\Main_App\gui\sidebar.py src\Main_App\gui\icons.py src\Main_App\gui\project_workflows.py
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check gui
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check source-localization
.\.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check source-localization-refs
ruff check src\Tools\LORETA_Visualizer src\Main_App\gui\main_window.py src\Main_App\gui\sidebar.py src\Main_App\gui\icons.py src\Main_App\gui\project_workflows.py
```

Do not run pytest-qt/offscreen GUI tests locally. Add or update focused GUI smoke coverage definitions when useful, but document that local execution was skipped unless the user approves a safe visible GUI test environment.

Manual visible smoke path for Phase 1:

1. Launch the app visibly with the repo environment.
2. Confirm the LORETA Visualizer sidebar icon/logo appears under Workspace Tools.
3. Open the visualizer from the sidebar.
4. Confirm the embedded viewport renders a nonblank 3D brain-like mesh.
5. Drag to rotate; use mouse-wheel/trackpad and explicit zoom in/out buttons.
6. Move the transparency slider and confirm mesh alpha changes immediately.
7. Use reset camera/default view.
8. Switch Home -> LORETA Visualizer -> another embedded tool -> LORETA Visualizer and confirm no crash, stale state, or duplicate widget behavior.
9. Confirm existing tools still open.

Additional visible smoke path for future slices:

1. Slice 2: confirm the status indicates fsaverage/anatomical mesh when available, and synthetic fallback when unavailable.
2. Slice 2: confirm no `src/fsaverage`, `src/quarantine/Tools/LORETA/fsaverage`, or other tracked fsaverage data appears in `git status`.
3. Slice 3: toggle activation visibility, base visibility, activation opacity, and base opacity independently.
4. Slice 3: adjust threshold/range controls and confirm the activation layer changes while the base mesh remains stable.
5. Slice 4: select multiple demo/project condition labels and confirm the activation pattern changes for each.

## Open Decisions

- Final sidebar label: likely `LORETA Visualizer` unless the user prefers `Brain Visualizer`.
- Final icon direction: dedicated brain/source icon in `Main_App.gui.icons.sidebar_icon`, not an image asset unless the current icon system changes.
- Whether the branch-visible sidebar entry should remain default-visible after promotion or be hidden behind a release feature flag.
- Preferred fsaverage surface for the base layer: pial, inflated, white, or another surface.
- First real-data shape after demo conditions: point cloud, volume grid, cortical sheet mesh, or another source-space representation.
