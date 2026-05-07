# Plot Generator GUI Refactor

## Status

Future plan. This work has not started.

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

## Suggested Seams

Prefer one seam per PR. Keep `PlotGeneratorWindow` as the public entry point.

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
