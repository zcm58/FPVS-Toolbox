# AGENTS.md

## Scope

This directory owns the embedded LORETA 3D visualizer only. Keep LORETA visualizer code, demo data, rendering adapters, fsaverage mesh loading helpers, and future visualizer-local adapters inside `src/Tools/LORETA_Visualizer/` unless a plan explicitly scopes shell integration.

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
- Demo heatmap data must stay clearly synthetic and local to this tool.

## Boundary Rules

- Do not import from `Tools.SourceLocalization` or `src/quarantine/**`.
- Do not recreate `src/Tools/SourceLocalization/**`, `src/Main_App/Legacy_App/**`, or `src/Main_App/PySide6_App/**`.
- Do not bundle fsaverage MRI/template data in `src/`, `src/quarantine/`, or package data. Fetch or locate fsaverage outside the repo through MNE/user cache paths only.
- Do not change preprocessing order, Stats methods, BDF loading, project manifests, exports, diagnostics, or app-wide project I/O for visualizer-only work.
- Do not write LORETA visualizer settings into `project.json` unless a future plan explicitly scopes project-level real-data integration.

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
