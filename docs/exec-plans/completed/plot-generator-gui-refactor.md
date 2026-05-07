# Plot Generator GUI Refactor

## Status

Completed plan. The behavior-preserving GUI refactor slices are complete.

## Target

`src/Tools/Plot_Generator/gui.py`

## Summary

`gui.py` currently combines project path discovery, project/default settings
persistence, a settings dialog, full widget assembly, condition/group selector
state, validation, logging/progress UX, and QThread worker orchestration. This
slows future Plot Generator GUI work because small UI changes require reading a
large stateful widget file.

Do not change plot generation math in this plan. The goal is a behavior-
preserving GUI organization split.

## Behavior To Preserve

- The Plot Generator remains a PySide6 tool.
- Existing object names, visible labels, tooltips, button enabled states,
  default folder behavior, condition-title behavior, legend-label persistence,
  scalp-map controls, group overlay behavior, and log/progress behavior remain
  unchanged unless explicitly scoped.
- User-selected Excel and output folders remain honored.
- Project settings continue to persist under the existing `tools.snr_plot`
  manifest keys.
- ROI definitions continue to load through the existing Stats ROI helpers.
- Long work stays in `_Worker` on `QThread`; widgets must not be mutated from
  worker code.
- The tool-local rule still applies: keep processing code modular and avoid new
  files over 500 lines where practical.

## Long-Running Execution Loop

This plan is intended for a long Codex workflow that can complete multiple
small behavior-preserving slices in one pass. Do not stop after the first slice
unless a verification failure, ambiguity, or user decision blocks safe progress.

For each slice:

1. Re-read this plan and identify the first `Pending` slice in the tracker.
2. Run the slice's pre-checks before editing.
3. Move only the methods or helpers listed for that slice.
4. Keep `PlotGeneratorWindow` as the public entry point and preserve existing
   method names as compatibility wrappers when tests or callers need them.
5. Run the slice's focused verification commands.
6. Update this plan with status, files changed, behavior preserved, commands
   run, and the next slice.
7. Continue to the next `Pending` slice until all slices are complete or a
   blocker is recorded.

If a slice reveals that the next planned move would create circular imports,
duplicate behavior, or require behavior changes, pause and record the blocker in
this plan instead of forcing the split.

## Slice Tracker

| Slice | Status | Output | Focused verification |
| --- | --- | --- | --- |
| 0. Baseline and inventory | Complete | Current behavior/test baseline recorded in this plan | `python scripts/agent_audit.py`; GUI audit; project-path audit; Plot Generator smoke tests |
| 1. Project paths and manifest helpers | Complete | `src/Tools/Plot_Generator/project_paths.py` | Project defaults, project path, and condition-title tests; project-path audit |
| 2. Settings parsing and persistence | Complete | `src/Tools/Plot_Generator/gui_settings.py` | Project defaults, legend-label, and condition-title tests |
| 3. Settings dialog | Complete | `src/Tools/Plot_Generator/settings_dialog.py` | GUI/refactor smoke tests that cover settings dialog behavior |
| 4. Selection and group state | Complete | `src/Tools/Plot_Generator/selection_state.py` | GUI/refactor, condition-title, and multigroup smoke tests |
| 5. Generation workflow | Complete | `src/Tools/Plot_Generator/generation_workflow.py` | Generation outcome, multigroup smoke, and GUI/refactor smoke tests |
| 6. UI section builders | Complete | `src/Tools/Plot_Generator/ui_sections.py` | Layout smoke, GUI/refactor smoke, and GUI import audit |
| 7. Final cleanup and completion | Complete | Thin `gui.py`, active plan updated and moved to completed | Full targeted Plot Generator verification plus agent audit |

Preferred order is the tracker order. Leave `_build_ui` / UI section extraction
late because it has the broadest visual and signal-wiring surface.

## Per-Slice Plan Update Format

After each completed slice, append a short note under `## Progress Log`:

```md
### YYYY-MM-DD - Slice N: Name

- Status: complete.
- Files changed: ...
- Behavior preserved: ...
- Verification passed: ...
- Next slice: ...
```

If verification fails, use `Status: blocked`, include the failing command and
error summary, and do not continue to the next slice until the failure is
understood.

## Baseline Commands

Run these before the first code slice and record the result in the progress log:

```powershell
python scripts/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python -m pytest tests\test_plot_generator_gui.py tests\test_plot_generator_gui_layout_smoke.py tests\test_plot_generator_gui_refactor_smoke.py -q
python -m pytest tests\test_plot_generator_project_defaults.py tests\test_plot_generator_legend_labels.py tests\test_plot_generator_condition_title_all.py -q
python -m pytest tests\test_plot_generator_generation_outcome.py tests\test_plot_generator_multigroup_smoke.py -q
```

## Suggested Seams

Prefer one seam per slice. Keep `PlotGeneratorWindow` as the public entry
point.

1. Project path and manifest helpers:
   - Move `_auto_detect_project_dir`, `_load_manifest`,
     `_resolve_results_root`, `_resolve_project_subfolder`, and
     `_project_paths` to `src/Tools/Plot_Generator/project_paths.py`.
   - Preserve relative `results_folder` handling, absolute subfolder handling,
     fallback `Excel_Results` / `SNR_Plots` behavior, and parent
     `currentProject.project_root` detection.
   - Run project-path audit before and after this slice.

2. Settings parsing and persistence:
   - Move `_settings_bool`, `_settings_float`, legend payload/default helpers,
     project plot settings payload/read/persist, scalp settings persistence,
     and legend settings load/persist logic to
     `src/Tools/Plot_Generator/gui_settings.py`.
   - Keep project manifest keys `_LEGEND_LABELS_KEY_PATH` and
     `_PLOT_SETTINGS_KEY_PATH` stable.
   - Consider a small dataclass for UI-independent payloads only after tests
     pin the current dictionary shapes.

3. Settings dialog:
   - Move `_SettingsDialog` to `src/Tools/Plot_Generator/settings_dialog.py`.
   - Preserve color button labels, color normalization, accept/reject behavior,
     and `selected_colors()` return shape.

4. UI assembly:
   - Split `_build_ui` into focused builders under
     `src/Tools/Plot_Generator/ui_sections.py` or
     `src/Tools/Plot_Generator/ui/sections.py`.
   - Suggested builders: file I/O, condition selectors, axis controls, legend
     controls, scalp controls, group overlay controls, progress/log controls,
     and action buttons.
   - Builders should receive the window or a small state object and return
     widgets/layouts without starting workers or reading files.

5. Selector and validation state:
   - Move condition/group selector helpers to
     `src/Tools/Plot_Generator/selection_state.py` if they can stay
     UI-adjacent and behavior-preserving.
   - Candidate functions: `_populate_conditions`, `_refresh_group_controls`,
     `_selected_groups`, `_group_overlay_enabled`, `_group_worker_kwargs`,
     `_worker_roi_selection`, `_overlay_toggled`,
     `_on_group_overlay_toggled`, and condition-change handlers.
   - Preserve `All Conditions`, comparison mode, group overlay, and scalp-title
     validation interactions.

6. Worker orchestration:
   - Move generation state and QThread wiring to
     `src/Tools/Plot_Generator/generation_workflow.py`.
   - Candidate methods: `_generate`, `_start_next_condition`,
     `_on_worker_finished`, `_finish_all`, `_generation_finished`,
     `_cancel_generation`, `_on_progress`, `_append_log`, and
     `_animate_progress_to`.
   - Preserve sequential condition queueing, overlay-vs-batch behavior,
     generated/failed payload handling, completion dialog behavior, cancel
     behavior, and output-folder opening.

## Suggested Final Shape

- `src/Tools/Plot_Generator/gui.py` keeps `PlotGeneratorWindow` and public
  compatibility methods.
- `src/Tools/Plot_Generator/project_paths.py`
- `src/Tools/Plot_Generator/gui_settings.py`
- `src/Tools/Plot_Generator/settings_dialog.py`
- `src/Tools/Plot_Generator/ui_sections.py` or `ui/sections.py`
- `src/Tools/Plot_Generator/selection_state.py`
- `src/Tools/Plot_Generator/generation_workflow.py`

Do not move plotting calculations out of `worker.py` as part of this GUI plan;
that is covered by the Plot Generator worker refactor plan.

## What Future Agents Should Inspect First

1. `src/Tools/Plot_Generator/AGENTS.md`
2. `docs/architecture/statistics-tools.md`
3. `src/Tools/Plot_Generator/gui.py`
4. `src/Tools/Plot_Generator/plot_settings.py`
5. `src/Tools/Plot_Generator/manifest_utils.py`
6. `src/Tools/Plot_Generator/worker.py` only for worker payload compatibility
7. Plot Generator tests under `tests/test_plot_generator_*`

Before editing, run:

```powershell
python scripts/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

## Verification Plan

Run the narrowest checks for the moved seam first:

```powershell
python -m py_compile src\Tools\Plot_Generator\gui.py
python -m pytest tests\test_plot_generator_gui.py tests\test_plot_generator_gui_layout_smoke.py tests\test_plot_generator_gui_refactor_smoke.py -q
python -m pytest tests\test_plot_generator_project_defaults.py tests\test_plot_generator_legend_labels.py tests\test_plot_generator_condition_title_all.py -q
python -m pytest tests\test_plot_generator_generation_outcome.py tests\test_plot_generator_multigroup_smoke.py -q
python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
```

Add or update pytest-qt smoke coverage for any changed signal wiring or enabled
states. If a GUI behavior cannot be asserted automatically, document the manual
smoke path.

## Completion Criteria

This plan is complete when:

- Every slice in the tracker is `Complete` or explicitly marked `Skipped` with
  a reason that preserves the goal.
- `src/Tools/Plot_Generator/gui.py` is reduced to the public window facade plus
  compatibility wrappers and direct widget composition that is not worth moving.
- Plot generation math remains outside this GUI plan.
- Worker orchestration still uses `_Worker` on `QThread`, with no widget access
  from worker code.
- Project path, manifest persistence, legend/scalp settings, condition/group
  selection, generation/cancel/completion behavior, and visible UI labels remain
  stable.
- Targeted Plot Generator tests, GUI import audit, project-path audit, and
  `python scripts/agent_audit.py` pass.
- This plan is moved to `docs/exec-plans/completed/` with the final progress log.

## Reporting Requirements

Future agents using this plan must report:

- Which seam was activated and why.
- Exact methods moved and their old/new module paths.
- Whether `PlotGeneratorWindow` stayed the public entry point.
- Project-root source used by the touched workflow.
- Any dialog Cancel, output-folder, or manifest persistence behavior verified.
- Commands run and results.
- Any skipped GUI smoke tests and residual risk.

## Manual Verification Before Activation

This plan was created from read-only inspection of the current `gui.py` symbols:
the file contains top-level project path helpers, `_SettingsDialog`,
`PlotGeneratorWindow`, settings/legend/scalp helpers, a large `_build_ui`,
selector/group helpers, and generation/QThread workflow methods. Recheck these
boundaries before activation because Plot Generator GUI work may move quickly.

## Progress Log

### 2026-05-07 - Activation

- Status: active.
- Files changed: `docs/exec-plans/active/plot-generator-gui-refactor.md`.
- Behavior preserved: documentation-only activation; no runtime code changed.
- Verification passed: `python scripts\agent_audit.py`.
- Next slice: baseline and inventory.

### 2026-05-07 - Slice 0: Baseline and inventory

- Status: complete.
- Files changed: `src/Tools/Plot_Generator/gui.py`; `src/Tools/Plot_Generator/plot_generator.py`; `tests/test_plot_generator_condition_title_all.py`; `docs/exec-plans/active/plot-generator-gui-refactor.md`.
- Behavior preserved: Plot Generator baseline behavior is unchanged; direct script imports again expose `ALL_CONDITIONS_OPTION` and patchable worker/thread hooks, and all-conditions generation now reflects the launched condition in the title field.
- Verification passed: `python scripts\agent_audit.py`; `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`; `python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py`; `.venv\Scripts\python -m pytest tests\test_plot_generator_gui.py tests\test_plot_generator_gui_layout_smoke.py tests\test_plot_generator_gui_refactor_smoke.py -q`; `.venv\Scripts\python -m pytest tests\test_plot_generator_project_defaults.py tests\test_plot_generator_legend_labels.py tests\test_plot_generator_condition_title_all.py -q`; `.venv\Scripts\python -m pytest tests\test_plot_generator_generation_outcome.py tests\test_plot_generator_multigroup_smoke.py -q`; `python -m py_compile src\Tools\Plot_Generator\gui.py src\Tools\Plot_Generator\plot_generator.py tests\test_plot_generator_condition_title_all.py`.
- Next slice: project paths and manifest helpers.

### 2026-05-07 - Slice 1: Project paths and manifest helpers

- Status: complete.
- Files changed: `src/Tools/Plot_Generator/project_paths.py`; `src/Tools/Plot_Generator/gui.py`; `docs/exec-plans/active/plot-generator-gui-refactor.md`.
- Behavior preserved: project root detection, `results_folder` handling, Excel/SNR subfolder resolution, environment project root detection, and fallback folder names remain unchanged.
- Verification passed: `python -m py_compile src\Tools\Plot_Generator\gui.py src\Tools\Plot_Generator\project_paths.py`; `.venv\Scripts\python -m pytest tests\test_plot_generator_project_defaults.py tests\test_plot_generator_legend_labels.py tests\test_plot_generator_condition_title_all.py -q`; `python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py`.
- Next slice: settings parsing and persistence.

### 2026-05-07 - Slice 2: Settings parsing and persistence

- Status: complete.
- Files changed: `src/Tools/Plot_Generator/gui_settings.py`; `src/Tools/Plot_Generator/gui.py`; `docs/exec-plans/active/plot-generator-gui-refactor.md`.
- Behavior preserved: project plot settings payloads, `tools.snr_plot.plot_settings`, `tools.snr_plot.legend_labels`, custom legend labels, scalp setting persistence, and fallback settings parsing remain unchanged.
- Verification passed: `python -m py_compile src\Tools\Plot_Generator\gui.py src\Tools\Plot_Generator\gui_settings.py`; `.venv\Scripts\python -m pytest tests\test_plot_generator_project_defaults.py tests\test_plot_generator_legend_labels.py tests\test_plot_generator_condition_title_all.py -q`.
- Next slice: settings dialog.

### 2026-05-07 - Slice 3: Settings dialog

- Status: complete.
- Files changed: `src/Tools/Plot_Generator/settings_dialog.py`; `src/Tools/Plot_Generator/gui.py`; `docs/exec-plans/active/plot-generator-gui-refactor.md`.
- Behavior preserved: settings dialog labels, custom color selection, accept/reject behavior, and `selected_colors()` return shape remain unchanged.
- Verification passed: `python -m py_compile src\Tools\Plot_Generator\gui.py src\Tools\Plot_Generator\settings_dialog.py`; `.venv\Scripts\python -m pytest tests\test_plot_generator_gui.py tests\test_plot_generator_gui_layout_smoke.py tests\test_plot_generator_gui_refactor_smoke.py -q`.
- Next slice: selection and group state.

### 2026-05-07 - Slice 4: Selection and group state

- Status: complete.
- Files changed: `src/Tools/Plot_Generator/selection_state.py`; `src/Tools/Plot_Generator/gui.py`; `docs/exec-plans/active/plot-generator-gui-refactor.md`.
- Behavior preserved: `All Conditions`, condition title behavior, condition combo population, comparison mode toggles, group overlay enablement, selected group payloads, ROI selection warnings, and multigroup worker kwargs remain unchanged.
- Verification passed: `python -m py_compile src\Tools\Plot_Generator\gui.py src\Tools\Plot_Generator\selection_state.py`; `.venv\Scripts\python -m pytest tests\test_plot_generator_gui.py tests\test_plot_generator_gui_refactor_smoke.py tests\test_plot_generator_condition_title_all.py tests\test_plot_generator_multigroup_smoke.py -q`.
- Next slice: generation workflow.

### 2026-05-07 - Slice 5: Generation workflow

- Status: complete.
- Files changed: `src/Tools/Plot_Generator/generation_workflow.py`; `src/Tools/Plot_Generator/gui.py`; `src/Tools/Plot_Generator/plot_generator.py`; `docs/exec-plans/active/plot-generator-gui-refactor.md`.
- Behavior preserved: sequential condition queueing, overlay-vs-batch worker launch, QThread signal wiring, progress aggregation, cancel behavior, generated/failed payload handling, completion dialog behavior, output-folder opening, and direct script patch hooks remain unchanged.
- Verification passed: `python -m py_compile src\Tools\Plot_Generator\gui.py src\Tools\Plot_Generator\generation_workflow.py src\Tools\Plot_Generator\plot_generator.py`; `.venv\Scripts\python -m pytest tests\test_plot_generator_generation_outcome.py tests\test_plot_generator_multigroup_smoke.py tests\test_plot_generator_gui_refactor_smoke.py tests\test_plot_generator_condition_title_all.py -q`.
- Next slice: UI section builders.

### 2026-05-07 - Slice 6: UI section builders

- Status: complete.
- Files changed: `src/Tools/Plot_Generator/ui_sections.py`; `src/Tools/Plot_Generator/gui.py`; `docs/exec-plans/active/plot-generator-gui-refactor.md`.
- Behavior preserved: widget labels, tooltips, default values, visible layout structure, object relationships, signal connections, log collapse behavior, and button enabled states remain unchanged.
- Verification passed: `python -m py_compile src\Tools\Plot_Generator\gui.py src\Tools\Plot_Generator\ui_sections.py`; `.venv\Scripts\python -m pytest tests\test_plot_generator_gui.py tests\test_plot_generator_gui_layout_smoke.py tests\test_plot_generator_gui_refactor_smoke.py -q`; `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`.
- Next slice: final cleanup and completion.

### 2026-05-07 - Slice 7: Final cleanup and completion

- Status: complete.
- Files changed: `src/Tools/Plot_Generator/gui.py`; `src/Tools/Plot_Generator/plot_generator.py`; `src/Tools/Plot_Generator/project_paths.py`; `src/Tools/Plot_Generator/gui_settings.py`; `src/Tools/Plot_Generator/settings_dialog.py`; `src/Tools/Plot_Generator/selection_state.py`; `src/Tools/Plot_Generator/generation_workflow.py`; `src/Tools/Plot_Generator/ui_sections.py`; `tests/test_plot_generator_baseline.py`; `tests/test_plot_generator_condition_title_all.py`; `tests/test_plot_generator_log_collapse.py`; `docs/exec-plans/active/plot-generator-gui-refactor.md`.
- Behavior preserved: Plot Generator remains PySide6-only; plot math and worker output behavior remain in `worker.py`; project paths, manifest persistence, legend/scalp settings, condition/group selection, generation/cancel/completion behavior, script entry-point compatibility, and visible UI behavior remain stable.
- Verification passed: `python -m py_compile src\Tools\Plot_Generator\gui.py src\Tools\Plot_Generator\project_paths.py src\Tools\Plot_Generator\gui_settings.py src\Tools\Plot_Generator\settings_dialog.py src\Tools\Plot_Generator\selection_state.py src\Tools\Plot_Generator\generation_workflow.py src\Tools\Plot_Generator\ui_sections.py src\Tools\Plot_Generator\plot_generator.py`; `.venv\Scripts\python -m pytest tests\test_plot_generator_baseline.py tests\test_plot_generator_condition_title_all.py tests\test_plot_generator_export_svg_smoke.py tests\test_plot_generator_fft_snr.py tests\test_plot_generator_full_snr_roi.py tests\test_plot_generator_generation_outcome.py tests\test_plot_generator_gridlines.py tests\test_plot_generator_gui.py tests\test_plot_generator_gui_layout_smoke.py tests\test_plot_generator_gui_refactor_smoke.py tests\test_plot_generator_ignore_fif.py tests\test_plot_generator_legend_labels.py tests\test_plot_generator_log_collapse.py tests\test_plot_generator_multigroup_smoke.py tests\test_plot_generator_oddballs_from_xmax.py tests\test_plot_generator_project_defaults.py tests\test_plot_generator_scalp_utils.py tests\test_plot_generator_title_roi.py -q`; `python scripts\agent_audit.py`; `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`; `python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py`.
- Completion note: `src/Tools/Plot_Generator/gui.py` is reduced to 362 lines, and the largest new Plot Generator GUI module is `ui_sections.py` at 439 lines.
