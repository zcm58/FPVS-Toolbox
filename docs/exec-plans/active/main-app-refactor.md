# Main App Refactor Plan

## Goal

Prepare `Main_App` for behavior-preserving refactors by keeping agent guidance, architecture docs, and mechanical checks synchronized with each change. The long-term target is to retire the confusing `Legacy_App` designation after runtime-used behavior has been migrated, wrapped, or renamed behind clearer current-app modules.

## Current Status

- Phase: refactor slices.
- Scope: behavior-preserving Main App organization.
- Behavior changes: none.
- `Legacy_App` is a temporary migration boundary, not a permanent architecture. Targeted edits are allowed for active refactors only when they preserve the processing pipeline, processing order, data formats, and exports.

## PR Contract

- Keep code changes surgical and behavior-preserving unless the task explicitly changes behavior.
- Read `ARCHITECTURE.md`, `docs/agent-index.md`, and this plan before non-trivial `Main_App` refactors.
- Update `ARCHITECTURE.md`, the relevant `docs/architecture/*.md`, or the nearest scoped `AGENTS.md` when structure, ownership, boundaries, workflows, or verification expectations change.
- If no architecture or agent doc update is needed, record why in this plan or the handoff.
- Include targeted tests or a documented manual smoke path for each refactor PR.
- Convert repeated review feedback into a low-noise `scripts/agent_audit.py` check when it can be enforced mechanically.

## Phases

1. Harness setup
   - Add this active plan and execution-plan directory map.
   - Link execution plans from `ARCHITECTURE.md`, `AGENTS.md`, and `docs/agent-index.md`.
   - Add low-noise audit coverage so the plan scaffold remains discoverable.
   - Status: complete.

2. Main app map refresh
   - Update focused architecture docs only after inspecting the current `Main_App` structure.
   - Identify small behavior-preserving refactor slices with clear tests or smoke checks.
   - Inventory which `Legacy_App` behaviors are still runtime-used and which have current `PySide6_App`, `Shared`, `Performance`, or adapter replacements.
   - Allow targeted `Legacy_App` edits only when they directly support migration and do not alter the processing pipeline.
   - Status: complete.

3. Refactor slices
   - Move one responsibility at a time.
   - Preserve processing order, output formats, project paths, and existing workflows.
   - Prefer migrating callers to current-app modules or thin adapters before renaming or deleting legacy modules.
   - Update this plan with completed slices, decisions, and verification results.
   - Status: active.

4. Completion
   - Confirm `python scripts/agent_audit.py` and relevant targeted checks pass.
   - Move this file to `docs/exec-plans/completed/` when the tracked refactor work is done.

## Verification

- `python scripts/agent_audit.py`
- Relevant skill-local audit scripts from `docs/agent-index.md`
- Targeted pytest or pytest-qt smoke tests for changed behavior
- `git diff --name-only` to identify any `Legacy_App` edits and confirm they were targeted, documented, and pipeline-preserving

Latest slice verification:

- Passed: `python -m py_compile src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\PySide6_App\GUI\event_map.py`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_event_map_enter.py tests\test_project_settings_roundtrip.py tests\test_main_window_layout_smoke.py -q`
- Ignored for this slice: `.venv\Scripts\python -m pytest tests\test_single_file_process_mode.py -q` currently fails before event-map code because its fixture sets low-pass `0.1` and high-pass `50.0`.

## Decisions

- Keep documentation requirements explicit, but enforce only stable, low-noise invariants in `scripts/agent_audit.py`.
- Do not add broad "docs changed with code" CI failures until the rule can be scoped narrowly enough to avoid false positives.
- `Legacy_App` is a migration boundary. Do not preserve the label for its own sake once a runtime-used behavior has a clear current-app home and equivalent tests.
- First code refactor slice completed: event-map GUI row behavior now lives in `src/Main_App/PySide6_App/GUI/event_map.py`, while `MainWindow` keeps the existing wrapper methods used by tests.
- Next refactor slice candidate: remove the direct `Legacy_App.eloreta_launcher` import from `GUI/menu_bar.py` and route Source Localization menu behavior through the current-app optional availability shim without reviving quarantined Source Localization.

## Current Findings

- `src/Main_App/PySide6_App/GUI/main_window.py` remains the largest organization hotspot, but event-map row behavior has been extracted to a focused current-app GUI module.
- Direct runtime imports still point at `Legacy_App` for post-processing, processing mixins, file selection, debug messagebox shims, FFT crop utilities, and Source Localization launcher wiring.
- `src/Main_App/Shared/post_process.py` exists, but still imports FFT crop and workbook helpers from `Legacy_App`; treat it as a migration bridge, not a completed replacement.
- `src/Main_App/Performance/process_runner.py` imports legacy FFT crop helpers, making FFT crop utilities a later migration candidate after coverage is confirmed.
