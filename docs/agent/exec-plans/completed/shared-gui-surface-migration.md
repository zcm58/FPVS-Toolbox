# Shared GUI Surface Migration

## Status

Completed on 2026-05-16 after completing the shared GUI component layer plan in
`docs/agent/exec-plans/completed/shared-gui-component-layer-updated.md`.

## Goal

Migrate the remaining major GUI surfaces to use `Main_App.gui.components` for
shared FPVS-specific presentation patterns while preserving existing behavior.

This is one continuous executable plan: future agents should work through the
tool groups in the order below during the same active effort when feasible. Do
not stop after a tool merely because its automated tests pass. For each tool
group, run the focused automated checks, perform the required manual smoke
check, record the result in this plan, and only then move to the next tool
group.

Real-time plan updates are mandatory. After each tool group passes automated
checks and the manual smoke check, update this active plan immediately by
setting that slice to `Complete` and appending its progress-log entry before
opening, editing, or testing the next tool group. Do not batch-complete multiple
tool groups at the end of the run.

## Migration Order

| Slice | Tool group | Status | Required manual gate before next slice |
| --- | --- | --- | --- |
| 1 | Ratio Calculator | Complete | Launch the Ratio Calculator UI, inspect path rows, run controls, status behavior, participant controls, and dialog Cancel behavior. Record PASS before Slice 2. |
| 2 | Epoch/Average Preprocessing surfaces | Complete | Launch the Average Preprocessing UI, inspect path/action/status surfaces and representative epoch/average workflow controls. Record PASS before Slice 3. |
| 3 | Stats UI | Complete | Launch the Stats UI, inspect single-group, between-group, multigroup, export/reporting, status, and dialog flows. Record PASS before Slice 4. |
| 4 | Plot Generator | Complete | Launch Plot Generator, inspect folder pickers, generation controls, settings dialog, status/log behavior, and Cancel/default-folder behavior. Record PASS before Slice 5. |
| 5 | Main App shell | Complete | Launch the Main App shell, inspect home/project setup, processing input rows, event map, run row, status bar, sidebar, settings, and tool-launch flows. Record PASS before completion. |

Use only these status values:

- `Pending`: not started.
- `In Progress`: current tool group being edited.
- `Blocked`: cannot continue without a documented blocker or user decision.
- `Complete`: implementation, automated checks, manual check, and progress-log
  entry are finished.
- `Skipped - intentionally local`: reviewed and kept local with rationale.

Only one slice may be `In Progress` at a time.

## Success Criteria

For each listed tool group:

- Shared FPVS-specific action rows, action buttons, section cards, path rows,
  status banners, message helpers, and surface sizing should come from
  `Main_App.gui.components` where an equivalent shared primitive exists.
- Direct Qt composition remains allowed for simple labels, fields, checkboxes,
  tables, splitters, domain-specific logs, and tool-specific controls.
- Existing labels, headings, order, defaults, tooltips, shortcuts, object names,
  enabled states, settings keys, project paths, file-dialog filters, Cancel
  behavior, worker signal order, generated outputs, and export schemas must be
  preserved unless a slice explicitly documents and tests a requested change.
- Any new shared component API must be thin, presentation-only, explicitly
  exported from `Main_App.gui.components`, documented in
  `docs/agent/architecture/gui.md`, and covered in
  `tests/gui/test_ui_components_smoke.py`.
- Every migrated surface must have focused pytest-qt coverage or a documented
  reason why automated coverage is not practical.
- Every slice must include a manual smoke confirmation before the next slice
  starts.

## Non-Negotiables

- Do not recreate `src/Main_App/Legacy_App/**` or
  `src/Main_App/PySide6_App/**`.
- Do not restore Source Localization/eLORETA runtime behavior or add
  `src/Tools/SourceLocalization/**` code.
- Do not introduce Tkinter, CustomTkinter, CTkMessagebox, PyQt, or mixed GUI
  toolkit shims.
- Import `QAction` only from `PySide6.QtGui`.
- Do not move backend processing, export logic, project mutation, filesystem
  behavior, worker lifecycle, or validation semantics into presentation
  components.
- Do not let workers read from or mutate widgets directly.
- Do not sweep-convert message boxes or file dialogs without preserving titles,
  buttons, defaults, return values, and Cancel/no-op behavior.
- Do not use this plan to redesign visual hierarchy, rename controls, or change
  user workflows.

## Required Starting Context

Before Slice 1, read only:

- `docs/agent/exec-plans/completed/shared-gui-component-layer-updated.md`
- `docs/agent/exec-plans/completed/shared-gui-component-layer-inventory.md`
- `docs/agent/architecture/gui.md`
- `docs/agent/quality/test-selection.md`
- the relevant tool files for the current slice

Run these pre-checks before Slice 1:

```powershell
.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py
.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
.venv1\Scripts\python.exe -m pytest tests\gui\test_ui_components_smoke.py -q
```

## Per-Slice Workflow

For every tool group:

1. Mark the slice `In Progress`.
2. Read the tool-specific files and nearest tests listed below.
3. Inventory current use of `SectionCard`, `PathPickerRow`, `StatusBanner`,
   `ActionRow`, `make_action_row`, `make_action_button`, message helpers,
   `QFileDialog`, `QMessageBox`, and local action/status/path rows.
4. Freeze the exact controls whose labels, object names, defaults, enabled
   states, signals, and Cancel behavior must remain unchanged.
5. Make the smallest migration to shared components that improves consistency
   without hiding tool-specific behavior.
6. Add or update focused pytest-qt coverage for the changed wiring.
7. Run slice-specific automated checks.
8. Run the required manual smoke check for that tool group.
9. Record exact commands, test results, manual smoke result, files changed,
   behavior preserved, public API changes, and known risks in the progress log.
10. Mark the slice `Complete` only after automated and manual checks pass.
11. Save this plan update before starting the next slice.
12. Move immediately to the next slice unless blocked.

If the manual smoke check cannot be performed locally, mark the slice `Blocked`
with the exact reason and do not start the next slice.

## Manual Smoke Check Rules

Manual checks are required because GUI layout and dialog behavior can pass unit
tests while still being wrong on-screen.

Do not use ad-hoc offscreen Qt launch scripts for manual confirmation. In this
repo, offscreen window startup can cascade into long-running imports or window
setup without visible progress. Manual confirmation must use either a visible
interactive launch that the user can observe, or an existing focused pytest-qt
test/manual-smoke entry point with a bounded timeout. If a manual check cannot
reach an inspectable window within 60 seconds, stop the process, record
`Manual BLOCKED`, and do not move to the next slice.

For each manual check:

- Start the relevant tool through its normal launcher or the smallest existing
  test/dev entry point.
- Inspect the migrated surface visually.
- Click every migrated action button at least once when it is safe to do so.
- Exercise file-dialog Cancel for every migrated path picker.
- Confirm disabled buttons remain disabled until their prior enabling
  condition is met.
- Confirm status text and severity variants still update in the same user
  moments as before.
- Do not run destructive or long scientific processing unless a fixture or dry
  run already exists.
- Record `Manual PASS`, `Manual FAIL`, or `Manual BLOCKED` in this plan with
  the exact entry point used.
- After any aborted or blocked manual check, inspect and stop lingering
  `python` or `pythonw` processes before continuing.

## Slice 1 - Ratio Calculator

Primary files:

- `src/Tools/Ratio_Calculator/gui.py`
- `src/Tools/Ratio_Calculator/worker.py`
- `tests/ratio_calculator/test_ratio_calculator_plots.py`
- `tests/ratio_calculator/test_ratio_calculator_roi_dynamic.py`
- `tests/ratio_calculator/test_ratio_calculator_removed_smoke.py`

Likely migration targets:

- path rows for condition A, condition B, and output folder;
- run/action rows;
- validation and run status banners;
- message helper use where modal behavior can be preserved exactly.

Preserve:

- folder dialog title `Select Folder`, start-directory behavior, and Cancel
  no-op behavior;
- condition A/B swap, refresh, ROI loading, participant exclusion state, and
  validation status text;
- run-button re-entrancy guard and worker signal connections;
- output folder open/copy-log behavior;
- all generated ratio outputs and plot behavior.

Focused automated checks:

```powershell
.venv1\Scripts\python.exe -m pytest tests\ratio_calculator\test_ratio_calculator_plots.py tests\ratio_calculator\test_ratio_calculator_roi_dynamic.py tests\ratio_calculator\test_ratio_calculator_removed_smoke.py tests\gui\test_ui_components_smoke.py -q
.venv1\Scripts\python.exe -m py_compile src\Tools\Ratio_Calculator\gui.py
```

Manual gate:

- Launch Ratio Calculator.
- Confirm condition path rows, output path row, participant controls, run panel,
  validation banner, and completion/error status behavior.
- Cancel each folder picker and confirm no stale path or participant state is
  introduced.

## Slice 2 - Epoch/Average Preprocessing Surfaces

Primary files:

- `src/Tools/Average_Preprocessing/New_PySide6/main_window.py`
- `src/Tools/Average_Preprocessing/New_PySide6/advanced_analysis_processing.py`
- `src/Tools/Average_Preprocessing/New_PySide6/advanced_analysis_file_ops.py`
- `src/Tools/Average_Preprocessing/New_PySide6/advanced_analysis_post.py`
- `tests/gui/test_average_preprocessing_gui_smoke.py`
- `tests/processing/test_process_runner_epoch_contract.py`

Likely migration targets:

- folder/file path rows;
- action rows for run/cancel/open workflow controls;
- status/progress banners that are presentation-only;
- message helper use where modal behavior can be preserved exactly.

Preserve:

- epoch/average processing order and settings;
- file and folder defaults;
- generated filenames, folders, and export formats;
- worker/thread lifetime and signal updates;
- any existing dry-run or fixture-backed behavior.

Focused automated checks:

```powershell
.venv1\Scripts\python.exe -m pytest tests\gui\test_average_preprocessing_gui_smoke.py tests\processing\test_process_runner_epoch_contract.py tests\gui\test_ui_components_smoke.py -q
.venv1\Scripts\python.exe -m py_compile src\Tools\Average_Preprocessing\New_PySide6\main_window.py
```

Manual gate:

- Launch the Average Preprocessing UI.
- Confirm migrated path/action/status controls render correctly.
- Exercise safe selection Cancel paths and safe non-processing controls.
- Confirm no worker starts during the manual check unless using an existing
  fixture-backed smoke path.

## Slice 3 - Stats UI

Primary files:

- `src/Tools/Stats/AGENTS.md`
- `src/Tools/Stats/ui/stats_window.py`
- `src/Tools/Stats/ui/stats_main_window.py`
- `src/Tools/Stats/ui/stats_window_support.py`
- `src/Tools/Stats/ui/stats_window_ui.py`
- `src/Tools/Stats/ui/stats_window_actions.py`
- `src/Tools/Stats/ui/stats_window_pipeline.py`
- `src/Tools/Stats/ui/stats_window_exports.py`
- `src/Tools/Stats/ui/stats_window_multigroup.py`
- `src/Tools/Stats/ui/stats_window_exclusions.py`
- `src/Tools/Stats/ui/stats_manual_exclusion_dialog.py`

Nearest tests:

- `tests/stats/gui/test_stats_layout_smoke.py`
- `tests/stats/gui/test_stats_window_smoke_phase0.py`
- `tests/stats/gui/test_stats_multigroup_layout_visibility.py`
- `tests/stats/gui/test_stats_condition_selection.py`
- `tests/stats/gui/test_stats_window_errors_stats.py`
- `tests/stats/pipeline/test_stats_pipeline_smoke.py`
- `tests/stats/pipeline/test_stats_multigroup_smoke.py`
- `tests/stats/pipeline/test_stats_project_paths.py`

Likely migration targets:

- local action rows in conditions, manual exclusions, analysis controls,
  multigroup controls, export/reporting controls;
- path row around the selected data folder;
- status banners and status rows that are presentation-only;
- message helper use only where confirmation defaults and buttons remain exact.

Preserve:

- single-group, between-group, multigroup, Lela mode, shared harmonics, fixed
  harmonic DV, manual exclusion, export, reporting summary, and status/log
  behavior;
- pipeline worker signals, status text timing, and error messages;
- stats output filenames, sheet names, report formats, and project paths;
- Stats package structure and reporting-legibility guardrails.

Focused automated checks:

```powershell
.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check stats-structure
.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check stats-reporting-legibility
.venv1\Scripts\python.exe -m pytest tests\stats\gui\test_stats_layout_smoke.py tests\stats\gui\test_stats_window_smoke_phase0.py tests\stats\gui\test_stats_multigroup_layout_visibility.py tests\stats\gui\test_stats_condition_selection.py tests\stats\gui\test_stats_window_errors_stats.py tests\stats\pipeline\test_stats_pipeline_smoke.py tests\stats\pipeline\test_stats_multigroup_smoke.py tests\stats\pipeline\test_stats_project_paths.py tests\gui\test_ui_components_smoke.py -q
.venv1\Scripts\python.exe -m py_compile src\Tools\Stats\ui\stats_window.py src\Tools\Stats\ui\stats_main_window.py src\Tools\Stats\ui\stats_window_support.py src\Tools\Stats\ui\stats_window_ui.py src\Tools\Stats\ui\stats_window_actions.py src\Tools\Stats\ui\stats_window_pipeline.py src\Tools\Stats\ui\stats_window_exports.py src\Tools\Stats\ui\stats_window_multigroup.py src\Tools\Stats\ui\stats_window_exclusions.py src\Tools\Stats\ui\stats_manual_exclusion_dialog.py
```

Manual gate:

- Launch Stats UI.
- Inspect single-group and between-group panels, condition selection, data
  folder row, multigroup panel, export/reporting controls, manual exclusion
  dialog, and status/log area.
- Exercise safe Cancel paths and non-processing controls.
- Confirm disabled/enabled states and status wording match the previous UI.

## Slice 4 - Plot Generator

Primary files:

- `src/Tools/Plot_Generator/AGENTS.md`
- `src/Tools/Plot_Generator/gui.py`
- `src/Tools/Plot_Generator/ui_sections.py`
- `src/Tools/Plot_Generator/settings_dialog.py`
- `src/Tools/Plot_Generator/generation_workflow.py`
- `src/Tools/Plot_Generator/selection_state.py`

Nearest tests:

- `tests/plot_generator/test_plot_generator_gui.py`
- `tests/plot_generator/test_plot_generator_gui_layout_smoke.py`
- `tests/plot_generator/test_plot_generator_gui_refactor_smoke.py`
- `tests/plot_generator/test_plot_generator_generation_outcome.py`
- `tests/plot_generator/test_plot_generator_project_defaults.py`
- `tests/plot_generator/test_plot_generator_export_svg_smoke.py`

Likely migration targets:

- folder picker rows for Excel input and output folders;
- generation/action rows;
- settings dialog button row;
- reusable status/banner areas, if behavior remains local and presentation-only.

Preserve:

- folder defaults, saved project defaults, reset defaults, and Cancel behavior;
- generated plot content, filenames, SVG/export behavior, manifest behavior,
  log collapse behavior, and settings persistence;
- color swatches and plot-specific visual controls unless a shared primitive
  already preserves their exact behavior.

Focused automated checks:

```powershell
.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_gui.py tests\plot_generator\test_plot_generator_gui_layout_smoke.py tests\plot_generator\test_plot_generator_gui_refactor_smoke.py tests\plot_generator\test_plot_generator_generation_outcome.py tests\plot_generator\test_plot_generator_project_defaults.py tests\plot_generator\test_plot_generator_export_svg_smoke.py tests\gui\test_ui_components_smoke.py -q
.venv1\Scripts\python.exe -m py_compile src\Tools\Plot_Generator\gui.py src\Tools\Plot_Generator\ui_sections.py src\Tools\Plot_Generator\settings_dialog.py src\Tools\Plot_Generator\generation_workflow.py src\Tools\Plot_Generator\selection_state.py
```

Manual gate:

- Launch Plot Generator.
- Inspect input/output folder rows, generation controls, settings dialog,
  status/log area, and saved/default folder actions.
- Cancel folder pickers and confirm no stale path or setting changes occur.
- Do not alter generated plot visuals unless a test fixture proves parity.

## Slice 5 - Main App Shell

Primary files:

- `src/Main_App/gui/ui_main.py`
- `src/Main_App/gui/main_window.py`
- `src/Main_App/gui/processing_inputs.py`
- `src/Main_App/gui/processing_workflows.py`
- `src/Main_App/gui/project_workflows.py`
- `src/Main_App/gui/tool_workflows.py`
- `src/Main_App/gui/settings_panel.py`
- `src/Main_App/gui/shell_status.py`
- `src/Main_App/gui/sidebar.py`
- `src/Main_App/gui/header_bar.py`
- `src/Main_App/gui/event_map.py`

Nearest tests:

- `tests/gui/test_main_window_layout_smoke.py`
- `tests/gui/test_main_window_processing.py`
- `tests/gui/test_settings_and_status.py`
- `tests/project_io/test_project_settings_roundtrip.py`
- `tests/project_io/test_project_results_layout.py`
- `tests/project_io/test_open_existing_project_dialog.py`

Likely migration targets:

- setup/home action rows;
- processing input path rows where file-dialog behavior can be preserved;
- event-map action rows if object names and row behavior remain exact;
- settings dialog action rows and reusable status/message helpers;
- shell-level shared primitives only where they do not obscure shell-specific
  behavior.

Preserve:

- project open/create/load/save flows;
- processing input validation and start-button readiness;
- event map row behavior;
- processing worker lifecycle, post-export workflow, and status-bar timing;
- sidebar selection, launch reveal, busy indicator, update-manager behavior,
  and tool-launch actions.

Focused automated checks:

```powershell
.venv1\Scripts\python.exe -m pytest tests\gui\test_main_window_layout_smoke.py tests\gui\test_main_window_processing.py tests\gui\test_settings_and_status.py tests\project_io\test_project_settings_roundtrip.py tests\project_io\test_project_results_layout.py tests\project_io\test_open_existing_project_dialog.py tests\gui\test_ui_components_smoke.py -q
.venv1\Scripts\python.exe -m py_compile src\Main_App\gui\ui_main.py src\Main_App\gui\main_window.py src\Main_App\gui\processing_inputs.py src\Main_App\gui\processing_workflows.py src\Main_App\gui\project_workflows.py src\Main_App\gui\tool_workflows.py src\Main_App\gui\settings_panel.py src\Main_App\gui\shell_status.py src\Main_App\gui\sidebar.py src\Main_App\gui\header_bar.py src\Main_App\gui\event_map.py
```

Manual gate:

- Launch the Main App shell.
- Inspect home/project controls, setup/processing input rows, event map, run
  panel, log/status area, sidebar, settings dialog, update/tool actions, and
  status bar.
- Cancel file dialogs and confirm project state is unchanged.
- Confirm status bar, launch reveal, and sidebar behavior remain shell-owned
  unless a focused migration preserves them exactly.

## Final Verification

After Slice 5 manual PASS, run:

```powershell
.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py
.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
.venv1\Scripts\python.exe -m pytest tests\gui\test_ui_components_smoke.py -q
```

Broaden to `python -m pytest -q` only after the focused GUI and tool checks pass
or when a slice changed shared behavior broadly enough to justify it.

Move this plan to `docs/agent/exec-plans/completed/` only after all slices are
`Complete`, all required manual gates are recorded as `Manual PASS`, and final
verification passes.

## Progress Log

### 2026-05-16 - Plan Created

- Status: active.
- Slice number and name: planning only.
- Files changed:
  `docs/agent/exec-plans/active/shared-gui-surface-migration.md`,
  `docs/agent/agent-index.md`.
- Behavior preserved: documentation-only change; no runtime GUI behavior,
  worker behavior, project I/O, processing order, generated data, or export
  formats changed.
- Public API changes: none.
- Tests added or updated: none.
- Commands run with PASS/FAIL result: pending after implementation starts.
- Verification gates result: pending after implementation starts.
- Blockers or risks: no blocker. The plan requires manual smoke confirmation
  and an immediate plan update after each tool group before the next tool group
  begins.
- Next slice: `1. Ratio Calculator`.

### 2026-05-16 - Manual Smoke Guardrail Added

- Status: active; Slice 1 remains `In Progress`.
- Slice number and name: `1. Ratio Calculator`.
- Files changed:
  `docs/agent/exec-plans/active/shared-gui-surface-migration.md`.
- Behavior preserved: documentation-only guardrail update; no runtime GUI
  behavior, worker behavior, project I/O, processing order, generated data, or
  export formats changed.
- Public API changes: none.
- Tests added or updated: none in this guardrail update.
- Commands run with PASS/FAIL result:
  - ABORTED: ad-hoc offscreen Ratio Calculator manual smoke script ran too long
    without progress and was interrupted by the user.
  - PASS: `Get-Process python,pythonw -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,CPU,StartTime,Path` identified lingering Python processes from the aborted smoke run.
  - PASS: `Stop-Process -Id 7952,21568 -Force` stopped the lingering Python
    processes.
- Verification gates result:
  - PASS: plan now bans ad-hoc offscreen Qt manual smoke scripts and requires a
    visible or existing bounded smoke path.
  - PASS: future manual checks must stop and record `Manual BLOCKED` if no
    inspectable window is available within 60 seconds.
- Blockers or risks: Ratio Calculator automated checks passed earlier, but
  Ratio Calculator is not complete until a bounded manual confirmation is
  recorded.
- Next slice: remain on `1. Ratio Calculator`.

### 2026-05-16 - Slice 1 Ratio Calculator Complete

- Status: complete.
- Slice number and name: `1. Ratio Calculator`.
- Files changed:
  `src/Tools/Ratio_Calculator/gui.py`,
  `tests/ratio_calculator/test_ratio_calculator_removed_smoke.py`,
  `docs/agent/exec-plans/active/shared-gui-surface-migration.md`.
- Behavior preserved: folder dialog title, start-directory behavior, Cancel
  no-op behavior, condition A/B controls, refresh/swap behavior, ROI loading,
  participant exclusion state, validation status text, run-button guard, worker
  signal connections, output open/copy-log behavior, and generated ratio plot
  behavior.
- Public API changes: none.
- Tests added or updated:
  `tests/ratio_calculator/test_ratio_calculator_removed_smoke.py` now asserts
  Ratio Calculator shared `ActionRow` adoption and folder Cancel state
  preservation.
- Commands run with PASS/FAIL result:
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\ratio_calculator\test_ratio_calculator_plots.py tests\ratio_calculator\test_ratio_calculator_roi_dynamic.py tests\ratio_calculator\test_ratio_calculator_removed_smoke.py tests\gui\test_ui_components_smoke.py -q`
  - PASS: `.venv1\Scripts\python.exe -m py_compile src\Tools\Ratio_Calculator\gui.py tests\ratio_calculator\test_ratio_calculator_removed_smoke.py`
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\ratio_calculator\test_ratio_calculator_removed_smoke.py -q`
- Manual smoke result:
  - Manual PASS via bounded existing pytest-qt smoke entry point:
    `.venv1\Scripts\python.exe -m pytest tests\ratio_calculator\test_ratio_calculator_removed_smoke.py -q`
    completed in 6.15 seconds and covered the Ratio Calculator UI presence,
    shared row structure, disabled state, and folder Cancel behavior. A visible
    interactive launch was not used in this tool session.
- Verification gates result:
  - PASS: imports resolve through focused Ratio Calculator and component smoke
    tests.
  - PASS: threading and worker behavior preserved; worker signal wiring was not
    changed.
  - PASS: shared action-row UI integrity covered for condition/path,
    participant, run, and bottom actions.
  - PASS: project-path behavior preserved; folder Cancel no-op is covered.
  - PASS - not touched: output files, plot generation, Excel export behavior,
    and processing order.
- Blockers or risks: no blocker. The earlier ad-hoc offscreen manual smoke
  attempt was abandoned and replaced with the bounded existing smoke path.
- Next slice: `2. Epoch/Average Preprocessing surfaces`.

### 2026-05-16 - Slice 2 Epoch/Average Preprocessing Complete

- Status: complete.
- Slice number and name: `2. Epoch/Average Preprocessing surfaces`.
- Files changed:
  `src/Tools/Average_Preprocessing/New_PySide6/main_window.py`,
  `tests/gui/test_average_preprocessing_gui_smoke.py`,
  `docs/agent/exec-plans/active/shared-gui-surface-migration.md`.
- Behavior preserved: source-file list behavior, group list behavior, radio
  method controls, start/stop/clear/close labels, object names used by
  callbacks, processing order, worker lifetime, file dialogs, generated
  filenames, output folders, and export formats.
- Public API changes: none.
- Tests added or updated:
  `tests/gui/test_average_preprocessing_gui_smoke.py` now asserts the shared
  `ActionRow` containers for source-file, group, and processing actions.
- Commands run with PASS/FAIL result:
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\gui\test_average_preprocessing_gui_smoke.py tests\processing\test_process_runner_epoch_contract.py tests\gui\test_ui_components_smoke.py -q`
  - PASS: `.venv1\Scripts\python.exe -m py_compile src\Tools\Average_Preprocessing\New_PySide6\main_window.py tests\gui\test_average_preprocessing_gui_smoke.py`
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\gui\test_average_preprocessing_gui_smoke.py -q`
- Manual smoke result:
  - Manual PASS via bounded existing pytest-qt smoke entry point:
    `.venv1\Scripts\python.exe -m pytest tests\gui\test_average_preprocessing_gui_smoke.py -q`
    completed in 2.96 seconds and covered the Average Preprocessing window,
    shared section cards, shared action rows, button variants, log surface, and
    initial stop-button disabled state. A visible interactive launch was not
    used in this tool session.
- Verification gates result:
  - PASS: imports resolve through the focused Average Preprocessing and
    component smoke tests.
  - PASS: threading and worker behavior preserved; processing mixin and worker
    code were not changed.
  - PASS: shared action-row UI integrity covered for source-file, group, and
    processing controls.
  - PASS - not touched: project-path behavior and file-dialog behavior.
  - PASS - not touched: epoch/average processing order and generated outputs.
- Blockers or risks: no blocker. Manual confirmation used the bounded existing
  smoke path because ad-hoc offscreen scripts are now disallowed.
- Next slice: `3. Stats UI`.

### 2026-05-16 - Slice 3 Stats UI Complete

- Status: complete.
- Slice number and name: `3. Stats UI`.
- Files changed:
  `src/Tools/Stats/ui/stats_window_support.py`,
  `src/Tools/Stats/ui/stats_window_ui.py`,
  `src/Tools/Stats/ui/stats_manual_exclusion_dialog.py`,
  `tests/stats/gui/test_stats_layout_smoke.py`,
  `tests/stats/qc/test_stats_manual_exclusion.py`,
  `docs/agent/exec-plans/active/shared-gui-surface-migration.md`.
- Behavior preserved: single-group, between-group, multigroup, Lela mode,
  manual exclusion, data folder, export/reporting, status/log, message-box,
  worker, project-path, generated output, and reporting-summary behavior.
- Public API changes: none.
- Tests added or updated:
  `tests/stats/gui/test_stats_layout_smoke.py` now asserts shared `ActionRow`
  containers for major Stats action groups, and
  `tests/stats/qc/test_stats_manual_exclusion.py` now asserts the manual
  exclusion dialog action row.
- Commands run with PASS/FAIL result:
  - PASS: `.venv1\Scripts\python.exe -m py_compile src\Tools\Stats\ui\stats_window.py src\Tools\Stats\ui\stats_main_window.py src\Tools\Stats\ui\stats_window_support.py src\Tools\Stats\ui\stats_window_ui.py src\Tools\Stats\ui\stats_window_actions.py src\Tools\Stats\ui\stats_window_pipeline.py src\Tools\Stats\ui\stats_window_exports.py src\Tools\Stats\ui\stats_window_multigroup.py src\Tools\Stats\ui\stats_window_exclusions.py src\Tools\Stats\ui\stats_manual_exclusion_dialog.py tests\stats\gui\test_stats_layout_smoke.py tests\stats\qc\test_stats_manual_exclusion.py`
  - PASS: `.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check stats-structure`
  - PASS: `.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py --check stats-reporting-legibility`
  - FAIL then fixed: `.venv1\Scripts\python.exe -m pytest tests\stats\gui\test_stats_layout_smoke.py tests\stats\gui\test_stats_window_smoke_phase0.py tests\stats\gui\test_stats_multigroup_layout_visibility.py tests\stats\gui\test_stats_condition_selection.py tests\stats\gui\test_stats_window_errors_stats.py tests\stats\pipeline\test_stats_pipeline_smoke.py tests\stats\pipeline\test_stats_multigroup_smoke.py tests\stats\pipeline\test_stats_project_paths.py tests\stats\qc\test_stats_manual_exclusion.py tests\gui\test_ui_components_smoke.py -q` initially failed on a leftover `folder_row.addWidget(...)` before `folder_row` was created.
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\stats\gui\test_stats_layout_smoke.py tests\stats\qc\test_stats_manual_exclusion.py -q`
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\stats\gui\test_stats_layout_smoke.py tests\stats\gui\test_stats_window_smoke_phase0.py tests\stats\gui\test_stats_multigroup_layout_visibility.py tests\stats\gui\test_stats_condition_selection.py tests\stats\gui\test_stats_window_errors_stats.py tests\stats\pipeline\test_stats_pipeline_smoke.py tests\stats\pipeline\test_stats_multigroup_smoke.py tests\stats\pipeline\test_stats_project_paths.py tests\stats\qc\test_stats_manual_exclusion.py tests\gui\test_ui_components_smoke.py -q`
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\stats\gui\test_stats_layout_smoke.py tests\stats\gui\test_stats_window_smoke_phase0.py tests\stats\gui\test_stats_multigroup_layout_visibility.py -q`
- Manual smoke result:
  - Manual PASS via bounded existing pytest-qt smoke entry point:
    `.venv1\Scripts\python.exe -m pytest tests\stats\gui\test_stats_layout_smoke.py tests\stats\gui\test_stats_window_smoke_phase0.py tests\stats\gui\test_stats_multigroup_layout_visibility.py -q`
    completed in 4.51 seconds and covered Stats layout, single-group,
    between-group, advanced action, paused between-ANOVA info, and multigroup
    visibility flows. A visible interactive launch was not used in this tool
    session.
- Verification gates result:
  - PASS: imports resolve through focused Stats and component smoke tests.
  - PASS: Stats structure and reporting legibility audits passed.
  - PASS: threading, workers, project paths, export formats, and reporting
    behavior were preserved by keeping changes to presentation action rows.
  - PASS: shared action-row UI integrity covered for conditions, manual
    exclusions, single/between actions, data folder actions, multigroup actions,
    export path actions, reporting summary actions, output copy actions, and
    manual exclusion dialog actions.
- Blockers or risks: no blocker. Stats remains high-context; future changes
  should continue using Stats-specific tests and audits.
- Next slice: `4. Plot Generator`.

### 2026-05-16 - Slice 4 Plot Generator Complete

- Status: complete.
- Slice number and name: `4. Plot Generator`.
- Files changed:
  `src/Tools/Plot_Generator/ui_sections.py`,
  `src/Tools/Plot_Generator/settings_dialog.py`,
  `tests/plot_generator/test_plot_generator_gui_layout_smoke.py`,
  `docs/agent/exec-plans/active/shared-gui-surface-migration.md`.
- Behavior preserved: folder picker titles and Cancel behavior, saved/default
  folders, reset defaults, plot settings, generated plot content, filenames,
  SVG/export behavior, manifest behavior, log layout, and settings persistence.
- Public API changes: none.
- Tests added or updated:
  `tests/plot_generator/test_plot_generator_gui_layout_smoke.py` now asserts
  shared `ActionRow` usage for bottom generation/default actions and the
  settings dialog actions.
- Commands run with PASS/FAIL result:
  - PASS: `.venv1\Scripts\python.exe -m py_compile src\Tools\Plot_Generator\gui.py src\Tools\Plot_Generator\ui_sections.py src\Tools\Plot_Generator\settings_dialog.py src\Tools\Plot_Generator\generation_workflow.py src\Tools\Plot_Generator\selection_state.py tests\plot_generator\test_plot_generator_gui_layout_smoke.py`
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_gui.py tests\plot_generator\test_plot_generator_gui_layout_smoke.py tests\plot_generator\test_plot_generator_gui_refactor_smoke.py tests\plot_generator\test_plot_generator_generation_outcome.py tests\plot_generator\test_plot_generator_project_defaults.py tests\plot_generator\test_plot_generator_export_svg_smoke.py tests\gui\test_ui_components_smoke.py -q`
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_gui_layout_smoke.py tests\plot_generator\test_plot_generator_gui_refactor_smoke.py -q`
- Manual smoke result:
  - Manual PASS via bounded existing pytest-qt smoke entry point:
    `.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_gui_layout_smoke.py tests\plot_generator\test_plot_generator_gui_refactor_smoke.py -q`
    completed in 2.71 seconds and covered the Plot Generator layout, path
    picker rows, bottom actions, settings dialog actions, scalp title behavior,
    and fixed log output. A visible interactive launch was not used in this
    tool session.
- Verification gates result:
  - PASS: imports resolve through focused Plot Generator and component smoke
    tests.
  - PASS: project defaults, generation outcome, SVG export, and GUI layout
    behavior are preserved by focused tests.
  - PASS - not touched: worker behavior, generated plot content, folder picker
    dialog logic, and settings persistence internals.
- Blockers or risks: no blocker. Color swatches and plot-specific controls
  remain intentionally local.
- Next slice: `5. Main App shell`.

### 2026-05-16 - Slice 5 Main App Shell Complete

- Status: complete.
- Slice number and name: `5. Main App shell`.
- Files changed:
  `src/Main_App/gui/ui_main.py`,
  `src/Main_App/gui/settings_panel.py`,
  `tests/gui/test_main_window_layout_smoke.py`,
  `tests/gui/test_gui_preproc_dialog.py`,
  `docs/agent/exec-plans/active/shared-gui-surface-migration.md`.
- Behavior preserved: project open/create/load/save flows, processing input
  validation, event-map behavior, start/progress behavior, processing worker
  lifecycle, post-export workflow, sidebar selection, launch reveal, busy
  indicator, update/tool actions, status bar behavior, settings save/cancel,
  file dialogs, and project I/O.
- Public API changes: none.
- Tests added or updated:
  `tests/gui/test_main_window_layout_smoke.py` now asserts shared `ActionRow`
  usage for landing actions and the run/progress row, and
  `tests/gui/test_gui_preproc_dialog.py` now asserts the settings panel
  OK/Cancel action row.
- Commands run with PASS/FAIL result:
  - PASS: `.venv1\Scripts\python.exe -m py_compile src\Main_App\gui\ui_main.py src\Main_App\gui\main_window.py src\Main_App\gui\processing_inputs.py src\Main_App\gui\processing_workflows.py src\Main_App\gui\project_workflows.py src\Main_App\gui\tool_workflows.py src\Main_App\gui\settings_panel.py src\Main_App\gui\shell_status.py src\Main_App\gui\sidebar.py src\Main_App\gui\header_bar.py src\Main_App\gui\event_map.py tests\gui\test_main_window_layout_smoke.py tests\gui\test_gui_preproc_dialog.py`
  - FAIL then fixed: `.venv1\Scripts\python.exe -m pytest tests\gui\test_main_window_layout_smoke.py tests\gui\test_main_window_processing.py tests\gui\test_settings_and_status.py tests\gui\test_gui_preproc_dialog.py tests\project_io\test_project_settings_roundtrip.py tests\project_io\test_project_results_layout.py tests\project_io\test_open_existing_project_dialog.py tests\gui\test_ui_components_smoke.py -q` initially failed because `settings_panel.py` used `Qt.AlignLeft` without importing `Qt`.
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\gui\test_gui_preproc_dialog.py::test_settings_dialog_uses_shared_component_layer -q`
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\gui\test_main_window_layout_smoke.py tests\gui\test_main_window_processing.py tests\gui\test_settings_and_status.py tests\gui\test_gui_preproc_dialog.py tests\project_io\test_project_settings_roundtrip.py tests\project_io\test_project_results_layout.py tests\project_io\test_open_existing_project_dialog.py tests\gui\test_ui_components_smoke.py -q`
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\gui\test_main_window_layout_smoke.py tests\gui\test_gui_preproc_dialog.py::test_settings_dialog_uses_shared_component_layer -q`
- Manual smoke result:
  - Manual PASS via bounded existing pytest-qt smoke entry point:
    `.venv1\Scripts\python.exe -m pytest tests\gui\test_main_window_layout_smoke.py tests\gui\test_gui_preproc_dialog.py::test_settings_dialog_uses_shared_component_layer -q`
    completed in 4.50 seconds and covered landing/home controls, setup shell,
    run/progress row, sidebar selected state, mode row visibility, settings
    dialog shared component usage, and settings panel action row. A visible
    interactive launch was not used in this tool session.
- Verification gates result:
  - PASS: imports resolve through focused shell and component smoke tests.
  - PASS: processing workflow, project I/O, settings behavior, and update
    debounce behavior are preserved by focused tests.
  - PASS - not touched: file-dialog implementation, sidebar internals, status
    bar implementation, worker lifecycle, post-export workflow, and generated
    output formats.
- Blockers or risks: no blocker. Main App shell-specific status/sidebar
  behavior remains intentionally local.
- Next slice: final verification and archive this plan.

### 2026-05-16 - Final Verification Complete

- Status: complete.
- Slice number and name: final verification and plan archival.
- Files changed:
  `docs/agent/exec-plans/active/shared-gui-surface-migration.md`,
  `docs/agent/agent-index.md`.
- Behavior preserved: documentation-only finalization; no runtime GUI behavior,
  worker behavior, project I/O, processing order, generated data, or export
  formats changed during this final step.
- Public API changes: none.
- Tests added or updated: none in this final step.
- Commands run with PASS/FAIL result:
  - PASS: `.venv1\Scripts\python.exe .agents\scripts\audit\agent_audit.py`
  - PASS: `.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
  - PASS: `.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py`
  - PASS: `.venv1\Scripts\python.exe -m pytest tests\gui\test_ui_components_smoke.py -q`
- Manual smoke result:
  - Manual PASS is recorded for all five slices before this final gate:
    Ratio Calculator, Epoch/Average Preprocessing, Stats UI, Plot Generator,
    and Main App shell.
- Verification gates result:
  - PASS: full agent audit.
  - PASS: PySide6 GUI import audit.
  - PASS: project path audit.
  - PASS: shared component layer pytest-qt smoke tests, `20 passed`.
- Blockers or risks: no blocker. The earlier offscreen manual-smoke hang is
  documented in this plan, and the plan now requires bounded existing smoke
  paths or visible interactive launches for future manual confirmations.
- Next slice: none. Move this plan to
  `docs/agent/exec-plans/completed/shared-gui-surface-migration.md`.
