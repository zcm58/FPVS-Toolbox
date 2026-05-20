# Ratio Calculator GUI Refactor

## Status

Active plan. Started on 2026-05-20.

Slice 1, project paths and condition folders, is complete. The methods listed
for that slice now live in
`src/Tools/Ratio_Calculator/gui_condition_selection.py` on
`RatioConditionSelectionMixin`, while `RatioCalculatorWindow` remains the
public PySide6 window in `src/Tools/Ratio_Calculator/gui.py`.

## Target

- `src/Tools/Ratio_Calculator/gui.py`
- `src/Tools/Ratio_Calculator/gui_condition_selection.py`

## Summary

`gui.py` currently combines project-root detection, path and condition
selection, full widget assembly, ROI table refresh/watch behavior, participant
pairing and exclusion state, advanced settings parsing, validation, QThread
worker wiring, status/log UI, completion dialogs, and button styling/icons.
The actual ratio math already lives in focused modules such as `compute.py`,
`pipeline.py`, `plots.py`, and `worker.py`, so this plan should keep the split
strictly GUI-focused.

## Behavior To Preserve

- `RatioCalculatorWindow` remains the public PySide6 window.
- Do not change ratio calculations, Excel output schemas, plot generation,
  filenames, folder layout, ROI loading semantics, or worker payloads.
- Preserve project-root resolution order: explicit `project_root`, then
  `FPVS_PROJECT_ROOT`, then parent `currentProject.project_root`.
- Preserve default input/output folder assumptions:
  `1 - Excel Data Files` and `5 - Ratio Summaries`.
- Preserve condition combo behavior, custom path behavior, A/B swap behavior,
  automatic run-label behavior, participant pairing, manual exclusion rules,
  ROI refresh timer behavior, validation messages, and completion/open-folder
  behavior.
- Keep long work in `RatioCalculatorWorker` on `QThread`; worker code must not
  touch widgets directly.

## Suggested Seams

Prefer one seam per PR. Keep `RatioCalculatorWindow` as the public facade.

1. Project paths and condition folders:
   - Move `_resolve_project_root`, `_excel_root`, `_set_default_output`,
     `_set_path_lineedit`, `_scan_condition_folders`, `_refresh_conditions`,
     `_populate_condition_combo`, `_set_condition_labels_from_folder`,
     `_apply_condition_selection`, `_on_condition_a_selected`,
     `_on_condition_b_selected`, `_swap_conditions`, `_browse_folder`, and
     `_initial_dialog_dir` to
     `src/Tools/Ratio_Calculator/gui_paths.py` or
     `src/Tools/Ratio_Calculator/gui_condition_selection.py`.
   - Preserve custom path insertion, dialog Cancel behavior, `_last_dir`, and
     auto participant reload.
   - Run project-path audit for this seam.
   - Status: Complete on 2026-05-20.
   - Implementation: moved these helpers to
     `src/Tools/Ratio_Calculator/gui_condition_selection.py`:
     `_resolve_project_root`, `_excel_root`, `_set_default_output`,
     `_set_path_lineedit`, `_scan_condition_folders`,
     `_refresh_conditions`, `_populate_condition_combo`,
     `_set_condition_labels_from_folder`, `_apply_condition_selection`,
     `_on_condition_a_selected`, `_on_condition_b_selected`,
     `_swap_conditions`, `_browse_folder`, and `_initial_dialog_dir`.

2. UI section builders:
   - Move `_build_basic_tab`, `_build_advanced_tab`, `_build_bottom_panel`,
     `_make_caption_label`, `_apply_button_styling`,
     `_apply_button_tooltips`, and `_apply_button_icons` to
     `src/Tools/Ratio_Calculator/gui_sections.py`.
   - Preserve object names, labels, tooltips, icons, tab names, table columns,
     default spinbox values, and signal connections.

3. ROI state:
   - Move `_rois_signature`, `_refresh_rois`, `_sync_rois_if_changed`, and
     `_populate_roi_table` to `src/Tools/Ratio_Calculator/gui_rois.py`.
   - Preserve timer interval, status/log behavior when no ROIs are found, and
     dynamic ROI refresh from Settings.

4. Participant/exclusion state:
   - Move `_load_participants`, `_index_folder`, `_set_all_exclusions`,
     `_confirm_exclude_all`, `_apply_participant_filter`,
     `_collect_manual_exclusions`, `_update_exclusion_status`,
     `_on_exclusion_item_changed`, `_update_participant_counts`,
     `_clear_participants`, and `_maybe_autoload_participants` to
     `src/Tools/Ratio_Calculator/gui_participants.py`.
   - Preserve paired participant intersection, invalid manual-exclusion
     handling, "show only excluded" filtering, hidden-row behavior for
     exclude-all, and "all participants excluded" run warning.

5. Settings and validation:
   - Move `_settings_from_ui`, `_parse_excluded_freqs`, `_parse_ylim`,
     `_ensure_output_dir`, `_validate_inputs`, `_set_validation_errors`,
     `_mark_label_a_dirty`, `_mark_label_b_dirty`, `_mark_run_label_dirty`,
     `_on_label_text_changed`, and `_update_run_label_default` to
     `src/Tools/Ratio_Calculator/gui_settings.py`.
   - Preserve `RatioCalculatorSettings` fields, default/auto y-limit parsing,
     invalid excluded-frequency logging, validation banner contents, and run
     button enabled rules.

6. Run workflow and status/log UX:
   - Move `_start_run`, `_handle_error`, `_handle_finished`,
     `_show_completion_dialog`, `_open_output_folder`, `_open_folder_from_edit`,
     `_copy_log`, `_append_log`, `_set_status_message`, `_update_run_state`, and
     `_toggle_log_panel` to `src/Tools/Ratio_Calculator/gui_run_workflow.py`.
   - Preserve QThread wiring, worker signal connections, progress/status/log
     behavior, output-folder opening, clipboard copying, and cleanup behavior.
   - Status: Complete on 2026-05-20.
   - Implementation: moved `_open_folder_from_edit`, `_set_status_message`,
     `_start_run`, `_handle_error`, `_handle_finished`,
     `_show_completion_dialog`, `_open_output_folder`, `_copy_log`,
     `_append_log`, `_update_run_state`, and `_show_log_dialog` to
     `src/Tools/Ratio_Calculator/gui_run_workflow.py` on
     `RatioRunWorkflowMixin`.

## Suggested Final Shape

- `src/Tools/Ratio_Calculator/gui.py` keeps `RatioCalculatorWindow` and composes
  smaller mixins/helpers.
- `src/Tools/Ratio_Calculator/gui_sections.py`
- `src/Tools/Ratio_Calculator/gui_condition_selection.py`
- `src/Tools/Ratio_Calculator/gui_rois.py`
- `src/Tools/Ratio_Calculator/gui_participants.py`
- `src/Tools/Ratio_Calculator/gui_settings.py`
- `src/Tools/Ratio_Calculator/gui_run_workflow.py`

Do not add or revive a `PySide6` subpackage for this refactor. Keep active code
in the current purpose-named Ratio Calculator modules.

## What Future Agents Should Inspect First

1. `docs/agent/architecture/statistics-tools.md`
2. `src/Tools/Ratio_Calculator/gui.py`
3. `src/Tools/Ratio_Calculator/constants.py`
4. `src/Tools/Ratio_Calculator/worker.py`
5. `src/Tools/Ratio_Calculator/pipeline.py`
6. `src/Tools/Ratio_Calculator/roi_provider.py`
7. Ratio Calculator tests under `tests/ratio_calculator/test_ratio_calculator_*`

Before editing, run:

```powershell
python .agents/scripts/audit/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

## Verification Plan

Run focused Ratio Calculator checks first:

```powershell
python -m py_compile src\Tools\Ratio_Calculator\gui.py
python -m pytest tests\ratio_calculator\test_ratio_calculator_plots.py tests\ratio_calculator\test_ratio_calculator_roi_dynamic.py tests\ratio_calculator\test_ratio_calculator_removed_smoke.py -q
python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
```

Add pytest-qt smoke coverage for any moved signal wiring, button enabled state,
participant exclusion behavior, or dialog behavior that is not currently pinned.

## Reporting Requirements

Future agents using this plan must report:

- Which seam was activated and why.
- Exact methods moved and their old/new module paths.
- Whether `RatioCalculatorWindow` remained the public entry point.
- Project-root source and output-folder behavior verified.
- Participant pairing/exclusion and ROI refresh behavior verified when touched.
- Commands run and results.
- Any skipped GUI/path tests and residual risk.

## Manual Verification Before Activation

This plan was created from read-only inspection of the current GUI: it contains
one `RatioCalculatorWindow` class with project/path helpers, section builders,
condition selection, ROI watching, participant/exclusion state, settings parsing,
validation, QThread run workflow, status/log helpers, and button styling/icon
helpers. Recheck those symbols before activation because Ratio Calculator GUI
work may change the boundaries.
