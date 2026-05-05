# Main App Refactor Plan

## Goal

Prepare `Main_App` for behavior-preserving refactors by keeping agent guidance, architecture docs, and mechanical checks synchronized with each change. The long-term target is to retire the confusing `Legacy_App` designation after runtime-used behavior has been migrated, wrapped, or renamed behind clearer current-app modules.

## Current Status

- Phase: refactor slices.
- Scope: behavior-preserving Main App organization.
- Behavior changes: eLORETA/Source Localization has been removed from active runtime; FPVS preprocessing, post-processing, FFT/SNR outputs, project paths, and exports remain behavior-preserving.
- `Legacy_App` is a temporary migration boundary, not a permanent architecture. Targeted edits are allowed for active refactors only when they preserve the processing pipeline, processing order, data formats, and exports.
- Folder retirement has a dedicated active plan: `docs/exec-plans/active/main-app-folder-retirement.md`.

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

Latest folder retirement planning slice:

- Added and updated `docs/exec-plans/active/main-app-folder-retirement.md` with inventory categories for every tracked `src/Main_App/Legacy_App/` and `src/Main_App/PySide6_App/` file.
- No runtime code, protected legacy modules, preprocessing, BDF loading, worker behavior, project paths, or exports changed.
- Next candidate: move reusable PySide6 GUI widgets/theme helpers into `Main_App.gui` / `Main_App.gui.widgets` with temporary wrappers.
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`

Latest folder retirement implementation slice:

- Refactor completed: reusable GUI widgets now live in `src/Main_App/gui/widgets/`, and shared theme helpers now live in `src/Main_App/gui/theme.py`.
- Temporary wrappers remain in `src/Main_App/PySide6_App/widgets/` and `src/Main_App/PySide6_App/utils/theme.py`.
- Runtime, tools, tests, and scripts now import widgets/theme helpers through `Main_App.gui.widgets` and `Main_App.gui.theme`.
- Behavior-preservation rule: no GUI workflow, signal wiring, processing path, project I/O, preprocessing, BDF loading, worker behavior, post-processing, or export behavior changed.
- Passed: `python -m py_compile src\Main_App\gui\theme.py src\Main_App\gui\widgets\__init__.py src\Main_App\gui\widgets\brain_pulse.py src\Main_App\gui\widgets\busy_spinner.py src\Main_App\gui\widgets\buttons.py src\Main_App\gui\widgets\cards.py src\Main_App\gui\widgets\forms.py src\Main_App\gui\widgets\status.py src\Main_App\PySide6_App\utils\theme.py src\Main_App\PySide6_App\widgets\__init__.py src\Main_App\PySide6_App\widgets\brain_pulse.py src\Main_App\PySide6_App\widgets\busy_spinner.py src\Main_App\PySide6_App\widgets\buttons.py src\Main_App\PySide6_App\widgets\cards.py src\Main_App\PySide6_App\widgets\forms.py src\Main_App\PySide6_App\widgets\status.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_ui_components_smoke.py tests\test_busy_spinner.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_layout_smoke.py tests\test_settings_and_status.py tests\test_startup_imports_no_customtkinter.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_average_preprocessing_gui_smoke.py tests\test_image_resizer_gui.py tests\test_individual_detectability_gui_smoke.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_stats_multigroup_layout_visibility.py -q`
- Passed: `git grep -n "Main_App.PySide6_App.widgets\|Main_App.PySide6_App.utils.theme" -- src tests scripts` found no matches.
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `git diff --check` with line-ending warnings only.
- Note: an exploratory combined run with Plot Generator and Stats multigroup smoke tests still exposes an order-sensitive Stats button-height assertion after Plot Generator runs first; the Stats multigroup test passes alone and with Stats-only layout tests.

Latest GUI utility retirement slice:

- Refactor completed: `OpGuard` now lives in `src/Main_App/gui/op_guard.py`, and bundled resource path helpers now live in `src/Main_App/Shared/paths.py`.
- Temporary wrappers remain in `src/Main_App/PySide6_App/utils/op_guard.py` and `src/Main_App/PySide6_App/utils/paths.py`.
- Runtime imports now use `Main_App.gui.op_guard` from project manager, main window, project workflows, and Stats support code.
- Behavior-preservation rule: no operation-guard behavior, project workflow, Stats workflow, GUI signal wiring, project I/O, preprocessing, BDF loading, worker behavior, post-processing, or export behavior changed.
- Passed: `python -m py_compile src\Main_App\gui\op_guard.py src\Main_App\Shared\paths.py src\Main_App\PySide6_App\utils\op_guard.py src\Main_App\PySide6_App\utils\paths.py src\Main_App\PySide6_App\Backend\project_manager.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\gui\project_workflows.py src\Tools\Stats\ui\stats_window_support.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_open_existing_project_dialog.py tests\test_project_settings_roundtrip.py tests\test_main_window_layout_smoke.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_settings_and_status.py tests\test_startup_imports_no_customtkinter.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_stats_layout_smoke.py tests\test_stats_condition_selection.py tests\test_stats_multigroup_layout_visibility.py -q`
- Passed: `git grep -n "Main_App.PySide6_App.utils.op_guard\|Main_App.PySide6_App.utils.paths" -- src tests scripts` found no matches.
- Next candidate: move post-export adapter implementation to `Main_App.exports.post_export_adapter`.

Latest slice verification:

- Passed: `python -m py_compile src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\PySide6_App\GUI\event_map.py`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_event_map_enter.py tests\test_project_settings_roundtrip.py tests\test_main_window_layout_smoke.py -q`
- Later fixed: `.venv\Scripts\python -m pytest tests\test_single_file_process_mode.py -q` now passes after the fixture was updated to canonical bandpass settings.

Latest removal slice:

- Removed eLORETA/Source Localization from active runtime, GUI menus, settings, tracked tests, and harness docs.
- Preserved FPVS preprocessing, post-processing, FFT/SNR outputs, project paths, and exports.
- Left historical output-folder ignore behavior in Stats file scanning intact so old `LORETA RESULTS` folders do not pollute active statistics inputs.
- Passed: `python -m py_compile scripts\agent_audit.py src\Main_App\PySide6_App\GUI\menu_bar.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\PySide6_App\GUI\settings_panel.py src\Main_App\PySide6_App\Backend\processing.py src\Main_App\PySide6_App\Backend\processing_controller.py src\Main_App\PySide6_App\Backend\project.py src\Main_App\PySide6_App\adapters\post_export_adapter.py src\Main_App\Legacy_App\processing_utils.py src\Main_App\Legacy_App\settings_manager.py src\Main_App\Shared\settings_manager.py`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with only line-ending warnings.
- Passed: `.venv\Scripts\python -m pytest tests\test_gui_preproc_dialog.py tests\test_project_settings_roundtrip.py tests\test_main_window_layout_smoke.py tests\test_startup_imports_no_customtkinter.py -q`
- Note: the focused pytest run printed an unrelated update-check network/proxy traceback after all selected tests passed with exit code 0.

## Decisions

- Keep documentation requirements explicit, but enforce only stable, low-noise invariants in `scripts/agent_audit.py`.
- Do not add broad "docs changed with code" CI failures until the rule can be scoped narrowly enough to avoid false positives.
- `Legacy_App` is a migration boundary. Do not preserve the label for its own sake once a runtime-used behavior has a clear current-app home and equivalent tests.
- First code refactor slice completed: event-map GUI row behavior now lives in `src/Main_App/PySide6_App/GUI/event_map.py`, while `MainWindow` keeps the existing wrapper methods used by tests.
- Latest removal slice completed: eLORETA/Source Localization was removed from the active app rather than routed through an optional availability shim.

## Current Findings

- `src/Main_App/PySide6_App/GUI/main_window.py` remains the largest organization hotspot, but event-map row behavior has been extracted to a focused current-app GUI module.
- Direct runtime imports no longer point at `Legacy_App` for GUI mixins; `MainWindow` now imports the shared processing mixin owner.
- `src/Main_App/Shared/fft_crop_utils.py` owns FFT crop behavior; `src/Main_App/Legacy_App/fft_crop_utils.py` is now only a compatibility wrapper.
- `src/Main_App/Shared/post_process.py` owns post-processing export behavior and imports workbook helpers from `src/Main_App/Shared/post_process_excel.py`.
- `src/Main_App/Shared/load_utils.py` owns BDF loader behavior; `src/Main_App/Legacy_App/load_utils.py` and `src/Main_App/PySide6_App/Backend/loader.py` are now only compatibility wrappers.

Latest post-processing export slice:

- Documentation-first requirement: `docs/architecture/post-processing-export-contract.md` records the pre-refactor export contract, output naming, sheet names, column order, metric behavior, and preservation constraints.
- Refactor completed: `src/Main_App/Shared/post_process.py` is the current-app owner; `src/Main_App/Legacy_App/post_process.py` is now a temporary compatibility wrapper.
- Runtime/test imports now use the shared owner in processing, GUI export, the post-export adapter, and target-frequency tests.
- Behavior-preservation check: the shared implementation matched the pre-refactor legacy implementation before callers were migrated.
- Passed: `python -m py_compile src\Main_App\Shared\post_process.py src\Main_App\Legacy_App\post_process.py src\Main_App\Legacy_App\processing_utils.py src\Main_App\PySide6_App\Backend\processing_controller.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\PySide6_App\adapters\post_export_adapter.py src\Main_App\PySide6_App\workers\processing_worker.py src\Main_App\__init__.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_post_export_adapter_no_fif.py tests\test_post_process_target_freqs.py tests\test_fft_neighbors_sheet.py tests\test_main_window_processing.py tests\test_main_window_excel_popup_logic.py tests\test_stats_export_finalization_release_smoke.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_postprocess_worker_qt.py tests\test_postprocess_worker_excel_payload.py tests\test_process_runner_epoch_contract.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `python -m py_compile scripts\gui_wave3_smoke.py tests\test_phase1_perf_hygiene.py`
- Skipped by existing environment guard: `.venv\Scripts\python -m pytest tests\test_phase1_perf_hygiene.py -q`
- Passed: `git diff --check` with only line-ending warnings.
- Note: focused pytest runs printed existing post-test Qt/update-check tracebacks after selected tests passed with exit code 0.

Latest preprocessing ownership slice:

- Documentation-first requirement: `docs/architecture/preprocessing-contract.md` records the active PySide6 preprocessing owner, fixed pipeline order, preservation rules, and focused verification commands.
- Refactor completed: active runtime preprocessing ownership is locked to `src/Main_App/PySide6_App/Backend/preprocess.py`.
- `src/Main_App/Shared/processing_mixin.py` and `Main_App.perform_preprocessing` now delegate to the PySide6 preprocessing owner instead of `src/Main_App/Legacy_App/eeg_preprocessing.py`.
- GUI processing no longer falls through to `ProcessingMixin.start_processing()` from `MainWindow.start_processing()`; single-file runs and internal non-process modes route through the PySide6 process runner path.
- `src/Main_App/Legacy_App/eeg_preprocessing.py` remains on disk as inactive legacy code until a later deletion or wrapper slice is explicitly scoped.
- Passed: `python -m py_compile src\Main_App\PySide6_App\Backend\preprocess.py src\Main_App\Shared\processing_mixin.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\__init__.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_single_file_process_mode.py tests\test_main_window_processing.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_preproc_audit.py tests\test_fif_flag_audit.py tests\test_process_runner_epoch_contract.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git grep -n "Main_App.Legacy_App.eeg_preprocessing" -- src tests scripts` found no matches.
- Passed: `git diff --check` with only existing line-ending normalization warnings.
- Note: preprocessing audit tests emitted expected MNE short-signal FIR warnings from synthetic test data.

Latest Main App layout slice:

- Target direction recorded: `docs/architecture/main-app-target-layout.md` defines the long-term purpose-based `Main_App` package shape without permanent `Legacy_App`/`PySide6_App` distinctions.
- Refactor completed: `src/Main_App/processing/` was added as the canonical active preprocessing import surface.
- Runtime/test imports now use `Main_App.processing.preprocess` from the process runner, processing controller, compatibility processing mixin, debug audit script, `Main_App.perform_preprocessing`, and focused preprocessing tests.
- Behavior-preservation rule: the implementation remains in `src/Main_App/PySide6_App/Backend/preprocess.py` for this slice; no preprocessing math, pipeline order, project paths, exports, or output formats are changed.
- Passed: `python -m py_compile src\Main_App\processing\__init__.py src\Main_App\processing\preprocess.py src\Main_App\PySide6_App\Backend\preprocess.py src\Main_App\Shared\processing_mixin.py src\Main_App\PySide6_App\Backend\processing_controller.py src\Main_App\Performance\process_runner.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\__init__.py scripts\manual_diagnostics\audit_missing_results.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_single_file_process_mode.py tests\test_main_window_processing.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_preproc_audit.py tests\test_fif_flag_audit.py tests\test_process_runner_epoch_contract.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with only line-ending normalization warnings.
- Note: focused GUI pytest still prints the known update-check proxy traceback after selected tests pass, and preprocessing audit tests still emit expected synthetic short-signal FIR warnings.

Latest Main App I/O layout slice:

- Refactor completed: `src/Main_App/io/` was added as the canonical active BDF loader import surface.
- Runtime/test imports now use `Main_App.io.load_utils` from the process runner, processing controller, compatibility processing mixin, debug audit script, `Main_App.load_eeg_file`, and focused loader tests.
- Behavior-preservation rule: the implementation remains in `src/Main_App/Shared/load_utils.py` for this slice; no supported file type, memmap path shape, EXG typing, montage policy, diagnostics, project paths, exports, or return behavior is changed.
- Passed: `python -m py_compile src\Main_App\io\__init__.py src\Main_App\io\load_utils.py src\Main_App\Shared\load_utils.py src\Main_App\Performance\process_runner.py src\Main_App\PySide6_App\Backend\processing_controller.py src\Main_App\Shared\processing_mixin.py src\Main_App\__init__.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_shared_load_utils.py tests\test_loader_warning_suppression.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_process_runner_epoch_contract.py tests\test_main_window_processing.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py`
- Passed: `git diff --check` with only line-ending normalization warnings.
- Passed: `git grep -n "Main_App.Shared.load_utils" -- src tests scripts` found only compatibility wrappers and wrapper-identity tests.

Latest Main App workers layout slice:

- Refactor completed: `src/Main_App/workers/` was added as the canonical active worker import surface.
- Runtime/test imports now use `Main_App.workers` for `MpRunnerBridge`, post-processing workers, process-runner module access, and multiprocessing environment helpers.
- Behavior-preservation rule: implementations remain in `src/Main_App/PySide6_App/workers/` and `src/Main_App/Performance/` for this slice; no worker signal payloads, threading behavior, process-runner scheduling, cancellation behavior, preprocessing order, project paths, exports, or output formats are changed.
- Passed: `python -m py_compile src\Main_App\workers\__init__.py src\Main_App\workers\mp_runner_bridge.py src\Main_App\workers\processing_worker.py src\Main_App\workers\process_runner.py src\Main_App\workers\mp_env.py src\Main_App\PySide6_App\workers\mp_runner_bridge.py src\Main_App\PySide6_App\workers\processing_worker.py src\Main_App\Performance\process_runner.py src\Main_App\Performance\mp_env.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\PySide6_App\GUI\settings_panel.py src\main.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_mp_runner_bridge_full_pipeline_smoke.py tests\test_worker_integration.py tests\test_postprocess_worker_excel_payload.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_process_runner_epoch_contract.py tests\test_pipeline_speed_safety.py tests\test_preproc_settings_snapshot.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_single_file_process_mode.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with only line-ending normalization warnings.
- Update-check cleanup completed: launch-time update checks are skipped under pytest, deleted Qt signal sources are ignored safely, and focused GUI pytest no longer prints the proxy traceback after selected tests pass.
- Passed: `.venv\Scripts\python -m pytest tests\test_update_manager_manual_force.py tests\test_main_window_processing.py tests\test_single_file_process_mode.py tests\test_worker_integration.py tests\test_mp_runner_bridge_full_pipeline_smoke.py tests\test_postprocess_worker_excel_payload.py -q`

Latest Main App projects layout slice:

- Refactor completed: `src/Main_App/projects/` was added as the canonical active project import surface.
- Runtime/test imports now use `Main_App.projects` for the project model, project manager, project metadata, projects-root helpers, and preprocessing-settings normalization/constants.
- Behavior-preservation rule: implementations remain in `src/Main_App/PySide6_App/Backend/` and `src/Main_App/PySide6_App/config/projects_root.py` for this slice; no project JSON schema, folder layout, settings normalization, project-root behavior, dialog behavior, preprocessing defaults, exports, or output formats are changed.
- Passed: `python -m py_compile src\Main_App\projects\__init__.py src\Main_App\projects\project.py src\Main_App\projects\project_manager.py src\Main_App\projects\project_metadata.py src\Main_App\projects\preprocessing_settings.py src\Main_App\projects\projects_root.py src\Main_App\PySide6_App\Backend\project.py src\Main_App\PySide6_App\Backend\project_manager.py src\Main_App\PySide6_App\Backend\project_metadata.py src\Main_App\PySide6_App\Backend\preprocessing_settings.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\PySide6_App\GUI\settings_panel.py src\Main_App\__init__.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_project_settings_roundtrip.py tests\test_project_results_layout.py tests\test_project_enumeration_io.py tests\test_project_scan_job.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_preprocessing_settings.py tests\test_preproc_persistence.py tests\test_project_bandpass_warning.py tests\test_project_legacy_bandpass_migration.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_worker_integration.py tests\test_open_existing_project_dialog.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_plot_generator_multigroup_smoke.py tests\test_stats_multigroup_smoke.py tests\test_stats_project_paths.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py`
- Passed: `git diff --check` with line-ending warnings only.

Latest Main App GUI layout slice:

- Refactor completed: `src/Main_App/gui/` was added as the canonical active GUI import surface.
- Runtime/test imports now use `Main_App.gui` for the main window, settings panel, update manager, sidebar, icons, style tokens, and focused GUI smoke helpers.
- Behavior-preservation rule: implementations remain in `src/Main_App/PySide6_App/GUI/` for this slice; no widget behavior, signal wiring, project workflow, update-check behavior, layout behavior, worker routing, processing order, or user-facing copy is changed.
- Test harness cleanup: `tests/test_phase1_perf_hygiene.py` now stubs the root `Main_App.post_process` export when replacing the root package and uses the PySide6 6.9-compatible `QObject.receivers("2timeout()")` signal signature.
- Passed: `python -m compileall -q src\Main_App\gui src\Main_App\PySide6_App\GUI src\Main_App\PySide6_App\utils src\Main_App\PySide6_App\widgets src\main.py scripts\gui_wave3_smoke.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_layout_smoke.py tests\test_settings_and_status.py tests\test_update_manager_manual_force.py tests\test_startup_imports_no_customtkinter.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_single_file_process_mode.py tests\test_worker_integration.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_audit_json_toggle.py tests\test_audit_surface.py tests\test_gui_preproc_dialog.py tests\test_main_window_event_map_enter.py tests\test_main_window_excel_popup_logic.py tests\test_open_existing_project_dialog.py tests\test_phase1_perf_hygiene.py tests\test_postprocess_worker_qt.py tests\test_project_settings_roundtrip.py tests\test_ratio_calculator_removed_smoke.py tests\test_stats_export_finalization_release_smoke.py tests\test_stats_no_customtkinter_import.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`

Latest Main App diagnostics layout slice:

- Refactor completed: `src/Main_App/diagnostics/` was added as the canonical runtime diagnostics import surface.
- Runtime/test imports now use `Main_App.diagnostics` for preprocessing audit helpers and event-time lock reporting.
- Repo-evaluation checks remain in `scripts/` and `.agents/skills/*/scripts/`; developer-run project/data probes moved from `src/debug/` to `scripts/manual_diagnostics/`.
- Behavior-preservation rule: diagnostics implementations remain in the existing PySide6 implementation modules for this slice; no diagnostic calculations, processing order, project files, exports, or GUI behavior are changed.
- Manual diagnostics cleanup: `audit_missing_results.py` now takes the project root from a CLI argument or `FPVS_DEBUG_PROJECT_ROOT`; no local user path is embedded.
- Passed: `python -m compileall -q src\Main_App\diagnostics scripts\manual_diagnostics`
- Passed: `.venv\Scripts\python -m pytest tests\test_event_time_lock_report.py tests\test_audit_fields.py tests\test_audit_json_toggle.py tests\test_audit_surface.py -q`
- Passed: `python scripts\manual_diagnostics\audit_missing_results.py --help`
- Passed: `python scripts\manual_diagnostics\debug_multigroup.py --help`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py`
- Passed: `git grep -n "Main_App.PySide6_App.diagnostics\|Main_App.PySide6_App.utils.audit" -- src tests scripts` found no matches.

Latest Main App project workflow split:

- Refactor completed: project open/create/load/save GUI orchestration moved from `src/Main_App/PySide6_App/GUI/main_window.py` to `src/Main_App/gui/project_workflows.py`.
- `MainWindow` keeps the existing public wrapper methods for actions, tests, and compatibility: `new_project`, `open_existing_project`, `openProjectPath`, `edit_project_settings`, `loadProject`, `saveProjectSettings`, `_sync_input_folder_display`, `update_select_button_text`, and `_update_select_button_text`.
- Behavior-preservation rule: no project JSON shape, dialog flow, event-map save behavior, input-folder display behavior, loaded project state, save-folder setup, preprocessing, BDF loading, worker routing, output folders, or export formats changed.
- Circular-import rule: `project_workflows.py` does not import `main_window.py`; `MainWindow.loadProject()` passes `_QtEntryAdapter` into the helper.
- Passed: `python -m py_compile src\Main_App\gui\project_workflows.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\PySide6_App\GUI\file_menu.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_open_existing_project_dialog.py tests\test_project_settings_roundtrip.py tests\test_gui_preproc_dialog.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_worker_integration.py tests\test_main_window_layout_smoke.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_single_file_process_mode.py tests\test_startup_imports_no_customtkinter.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py`
- Passed: `git diff --check` with line-ending warnings only.

Latest Main App post-export workflow split:

- Refactor completed: GUI-side post-processing/export completion handling moved from `src/Main_App/PySide6_App/GUI/main_window.py` to `src/Main_App/gui/post_export_workflows.py`.
- `MainWindow` keeps the existing compatibility wrappers and helper exports used by tests: `_on_post_finished`, `_refresh_run_excel_success_from_disk`, `_export_with_post_process`, `_excel_snapshot`, and `_should_show_no_excel_popup`.
- Behavior-preservation rule: no workbook generation, Excel filenames, sheet names, column order, formatting, FFT-neighbor rows, post-processing math, project paths, worker payloads, dialogs, or export success classification changed.
- Passed: `python -m py_compile src\Main_App\gui\post_export_workflows.py src\Main_App\PySide6_App\GUI\main_window.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_excel_popup_logic.py tests\test_postprocess_worker_qt.py tests\test_stats_export_finalization_release_smoke.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_main_window_layout_smoke.py tests\test_startup_imports_no_customtkinter.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with line-ending warnings only.

Latest Main App processing workflow split:

- Refactor completed: processing run GUI orchestration moved from `src/Main_App/PySide6_App/GUI/main_window.py` to `src/Main_App/gui/processing_workflows.py`.
- `MainWindow` keeps the existing compatibility wrappers and signal targets: `start_processing`, `stop_processing`, `_on_start_stop_clicked`, `_on_processing_finished`, `_on_processing_error`, `_periodic_queue_check`, and `_finalize_processing`.
- Behavior-preservation rule: no preprocessing math, BDF loading, multiprocessing implementation, worker signal payloads, post-processing export behavior, project paths, output formats, processing order, or GUI user flow changed.
- Passed: `python -m py_compile src\Main_App\gui\processing_workflows.py src\Main_App\PySide6_App\GUI\main_window.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_single_file_process_mode.py tests\test_worker_integration.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_layout_smoke.py tests\test_startup_imports_no_customtkinter.py tests\test_postprocess_worker_qt.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with line-ending warnings only.

Latest Main App processing input workflow split:

- Refactor completed: processing input GUI orchestration moved from `src/Main_App/PySide6_App/GUI/main_window.py` to `src/Main_App/gui/processing_inputs.py`.
- `MainWindow` keeps the existing compatibility wrappers used by UI wiring and tests: `_validate_inputs`, `_build_validated_params`, `_on_mode_changed`, `_set_controls_enabled`, `detect_trigger_ids`, `_update_start_enabled`, and `select_single_file`.
- Behavior-preservation rule: no `validated_params` shape, single-file `.bdf` restrictions, batch file discovery, warning/dialog text, log message, `parallel_mode` behavior, start-button behavior, preprocessing, BDF loading, worker routing, project schema, output folder, post-processing, or Excel export behavior changed.
- Passed: `python -m py_compile src\Main_App\gui\processing_inputs.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\gui\processing_workflows.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_gui_preproc_dialog.py tests\test_single_file_process_mode.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_main_window_layout_smoke.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check`

Latest Main App tool workflow split:

- Refactor completed: settings, update-check, tool-launcher, help/about, and auxiliary-window GUI orchestration moved from `src/Main_App/PySide6_App/GUI/main_window.py` to `src/Main_App/gui/tool_workflows.py`.
- `MainWindow` keeps the existing compatibility wrappers used by menus, actions, and tests: `open_settings_window`, `check_for_updates`, `open_stats_analyzer`, `open_image_resizer`, `open_plot_generator`, `open_epoch_averaging`, `open_advanced_analysis_window`, `show_relevant_publications`, and `show_about_dialog`.
- Behavior-preservation rule: no tool command path, project-root environment forwarding, Stats warning flow, child-window retention, settings dialog behavior, update-check behavior, project schema, processing route, output path, preprocessing, BDF loading, post-processing, or export behavior changed.
- Passed: `python -m py_compile src\Main_App\gui\tool_workflows.py src\Main_App\PySide6_App\GUI\main_window.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_stats_no_customtkinter_import.py tests\test_update_manager_manual_force.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_layout_smoke.py tests\test_settings_and_status.py tests\test_startup_imports_no_customtkinter.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with line-ending warnings only.

Latest Main App shell/status workflow split:

- Refactor completed: launch reveal, status bar, busy indicator, GUI log routing, and processing-start notice behavior moved from `src/Main_App/PySide6_App/GUI/main_window.py` to `src/Main_App/gui/shell_status.py`.
- `MainWindow` keeps the existing compatibility wrappers used by Qt lifecycle hooks, processing workflows, and tests: `_launch_reveal_widget`, `_start_launch_reveal`, `_finish_launch_reveal`, `_emit_backend_log`, `log`, `_show_processing_started_notice`, `_busy_start`, `_busy_stop`, and `_tick_busy`.
- Behavior-preservation rule: no status-bar text, landing version text, busy frame set, timer interval, busy label styling, processing-start notice text/title/modality/auto-close timing, log timestamp format, debug filtering, processing route, project I/O, worker behavior, post-processing, or export behavior changed.
- Passed: `python -m py_compile src\Main_App\gui\shell_status.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\gui\processing_workflows.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_layout_smoke.py tests\test_main_window_processing.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_single_file_process_mode.py tests\test_settings_and_status.py tests\test_startup_imports_no_customtkinter.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with line-ending warnings only.

Latest Main App post-worker launcher split:

- Refactor completed: GUI-side post-processing worker launch and worker error routing moved from `src/Main_App/PySide6_App/GUI/main_window.py` to `src/Main_App/gui/post_export_workflows.py`.
- `MainWindow` keeps the existing compatibility wrappers used by processing workflows and tests: `_start_post_worker` and `_on_worker_error`.
- Behavior-preservation rule: no post-processing worker class, thread wiring, queue/backlog behavior, worker signal routing, save-folder resolution, worker payload, log routing, finalization, project I/O, processing route, post-processing math, or export behavior changed.
- Passed: `python -m py_compile src\Main_App\gui\post_export_workflows.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\gui\processing_workflows.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_postprocess_worker_qt.py tests\test_postprocess_worker_excel_payload.py tests\test_main_window_excel_popup_logic.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_main_window_layout_smoke.py tests\test_single_file_process_mode.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with line-ending warnings only.

Next refactor slice candidate:

- Continue splitting `Main_App.gui.main_window` by workflow only if it improves clarity. The next candidate is reassessing event-map wrappers or Qt lifecycle/timer compatibility helpers; otherwise pause extraction and evaluate whether `main_window.py` is simple enough for this phase.

Latest processing mixin slice:

- Documentation-first requirement: `docs/architecture/processing-mixin-contract.md` records the current `ProcessingMixin` host contract, processing order, queue message behavior, finalization behavior, and preservation rules.
- Refactor completed: `src/Main_App/Shared/processing_mixin.py` is the current-app owner; `src/Main_App/Legacy_App/processing_utils.py` is now a temporary compatibility wrapper.
- Runtime/test/smoke imports now use the shared owner in `MainWindow`, main-window processing tests, single-file mode tests, `Main_App.__init__`, and GUI smoke stubs.
- Intentional non-behavioral cleanup: production debug `print` calls in `start_processing()` became structured debug logging to satisfy repo audit rules.
- Passed: `python -m py_compile src\Main_App\Shared\processing_mixin.py src\Main_App\Legacy_App\processing_utils.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\__init__.py scripts\gui_wave3_smoke.py tests\test_main_window_processing.py tests\test_single_file_process_mode.py`
- Passed: `git grep -n "from Main_App.Legacy_App.processing_utils\|import Main_App.Legacy_App.processing_utils" -- src tests scripts` found no matches.
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_main_window_layout_smoke.py tests\test_startup_imports_no_customtkinter.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_post_export_adapter_no_fif.py tests\test_post_process_target_freqs.py tests\test_postprocess_worker_excel_payload.py tests\test_process_runner_epoch_contract.py -q`
- Note: the focused GUI pytest run printed the existing update-check network/proxy traceback after selected tests passed with exit code 0.
- Later fixed: `.venv\Scripts\python -m pytest tests\test_single_file_process_mode.py -q` now passes after the fixture was updated to canonical bandpass settings.

Latest BDF loader contract slice:

- Documentation-first requirement: `docs/architecture/eeg-loading-contract.md` records the BDF-only contract, memmap path shape, reference/stim resolution, EXG typing, `standard_1005` 10-10 coverage, `on_missing="warn"`, logging, and return semantics.
- Refactor completed: `src/Main_App/Shared/load_utils.py` is the current-app owner; `src/Main_App/Legacy_App/load_utils.py` is now a temporary compatibility wrapper.
- Runtime imports now use the shared owner from `src/Main_App/Shared/processing_mixin.py` and `src/Main_App/__init__.py`.
- Duplicate implementation removed: `src/Main_App/PySide6_App/Backend/loader.py` is now a thin wrapper around `src/Main_App/Shared/load_utils.py`.
- Runtime imports now use the shared owner from the processing mixin, PySide6 processing controller, performance runner, debug audit script, and `Main_App.__init__`.
- `.set`/EEGLAB loading is intentionally unsupported unless restored as a new explicitly scoped feature.
- Online verification added: BioSemi's cap table lists 64-channel caps as `1020`, Brainstorm maps BioSemi 16/32/64 cap labels one-to-one to standard 10-10, and MNE `standard_1005` is used as the 10-10-covering dense standard montage.
- Bandpass cleanup completed: `tests/test_single_file_process_mode.py` now uses canonical `low_pass=50.0` and `high_pass=0.1`, and `tests/test_project_bandpass_warning.py` now asserts the current one-time legacy inversion warning.
- Passed: `python -m py_compile src\Main_App\Shared\load_utils.py src\Main_App\PySide6_App\Backend\loader.py src\Main_App\Legacy_App\load_utils.py src\Main_App\PySide6_App\Backend\processing_controller.py src\Main_App\Performance\process_runner.py tests\test_shared_load_utils.py tests\test_loader_warning_suppression.py`
- Passed: `git grep -n "from Main_App.Legacy_App.load_utils\|import Main_App.Legacy_App.load_utils" -- src tests scripts` found no matches.
- Passed: `git grep -n "PySide6_App.Backend.loader import load_eeg_file" -- src tests scripts` found no active imports.
- Passed: stale loader string grep found no EEGLAB reader, old unsupported-file message, old montage, or `ignore` montage policy matches in `src`, `tests`, or `docs`.
- Passed: `.venv\Scripts\python -m pytest tests\test_shared_load_utils.py tests\test_loader_warning_suppression.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_shared_load_utils.py tests\test_single_file_process_mode.py tests\test_preprocessing_settings.py tests\test_preproc_persistence.py tests\test_project_legacy_bandpass_migration.py tests\test_project_bandpass_warning.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_loader_warning_suppression.py tests\test_process_runner_epoch_contract.py tests\test_postprocess_worker_excel_payload.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_main_window_layout_smoke.py tests\test_startup_imports_no_customtkinter.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py`
- Passed: `git diff --check` with only line-ending warnings.
- Note: the focused GUI pytest run printed the existing update-check network/proxy traceback after selected tests passed with exit code 0.

Latest PySide6-only GUI toolkit slice:

- Documentation-first requirement: `docs/architecture/project-io.md` records PySide6 file-selection behavior and the rule that user-facing warnings/errors use PySide6-safe message helpers.
- Refactor completed: `MainWindow` no longer inherits `FileSelectionMixin`, and active Main App paths no longer install or import Tk messagebox/filedialog shims.
- Added `src/Main_App/Shared/user_messages.py` so legacy-boundary processing and loader code can surface messages through PySide6 when safe, or log without blocking in worker/background contexts.
- Removed tracked CustomTkinter/Tk legacy Average Preprocessing UI files and removed `customtkinter`, `CTkMessagebox`, and `darkdetect` from `requirements.txt`; the PySide6 Average Preprocessing tool still uses the UI-agnostic `advanced_analysis_core.py`.
- Strengthened `scripts/agent_audit.py --check gui` so repo code cannot import Tkinter, CustomTkinter, or CTkMessagebox.
- Passed: `python -m py_compile scripts\agent_audit.py src\Main_App\Shared\user_messages.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\Legacy_App\processing_utils.py src\Main_App\Legacy_App\file_selection.py src\Main_App\Legacy_App\load_utils.py src\Main_App\Legacy_App\debug_utils.py src\Main_App\PySide6_App\Backend\loader.py src\Main_App\Performance\process_runner.py src\Tools\Average_Preprocessing\__init__.py src\Tools\Average_Preprocessing\New_PySide6\advanced_analysis_group_ops.py src\config.py`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `python .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_layout_smoke.py tests\test_project_settings_roundtrip.py tests\test_main_window_processing.py tests\test_startup_imports_no_customtkinter.py tests\test_average_preprocessing_gui_smoke.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_stats_no_customtkinter_import.py tests\test_stats_shared_rois.py tests\test_fpvs_app_quarantine.py -q`
- Passed: `git grep -n -E "^\s*(import tkinter|from tkinter|import customtkinter|from customtkinter|import CTkMessagebox|from CTkMessagebox)" -- src tests scripts` found no matches.
- Later fixed: `.venv\Scripts\python -m pytest tests\test_single_file_process_mode.py -q` now passes after the fixture was updated to canonical bandpass settings.

Latest workbook-helper slice:

- Documentation-first requirement: `docs/architecture/post-processing-export-contract.md` now records `build_fft_neighbors_rows` and `write_results_workbook` behavior, including FFT-neighbor metadata, workbook formatting, freeze panes, column sizing, and optional sheet creation.
- Refactor completed: `src/Main_App/Shared/post_process_excel.py` is the current-app owner; `src/Main_App/Legacy_App/post_process_excel.py` is now a temporary compatibility wrapper.
- Runtime/test imports now use the shared owner in shared post-processing and FFT-neighbor workbook tests.
- Behavior-preservation check: the shared implementation matched the legacy implementation before callers were migrated.
- Passed: `cmd /c fc /N src\Main_App\Legacy_App\post_process_excel.py src\Main_App\Shared\post_process_excel.py`
- Passed: `python -m py_compile src\Main_App\Shared\post_process_excel.py src\Main_App\Legacy_App\post_process_excel.py src\Main_App\Shared\post_process.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_fft_neighbors_sheet.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_post_export_adapter_no_fif.py tests\test_post_process_target_freqs.py tests\test_postprocess_worker_excel_payload.py -q`
- Passed: `git grep -n "Main_App.Legacy_App.post_process_excel" -- src tests scripts` found no matches.
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`

Latest FFT crop slice:

- Documentation-first requirement: `docs/architecture/fft-crop-method.md` records the pre-refactor FFT crop method, constants, fallback reasons, warnings, result fields, and preservation constraints.
- Refactor completed: `src/Main_App/Shared/fft_crop_utils.py` is the current-app owner; `src/Main_App/Legacy_App/fft_crop_utils.py` is now a temporary compatibility wrapper.
- Runtime/test imports now use the shared owner in processing, performance runner, post-processing, and FFT crop tests.
- Behavior-preservation check: the shared implementation matched the pre-refactor legacy implementation before imports were migrated.
- Passed: `python -m py_compile src\Main_App\Shared\fft_crop_utils.py src\Main_App\Legacy_App\fft_crop_utils.py src\Main_App\Legacy_App\processing_utils.py src\Main_App\Legacy_App\post_process.py src\Main_App\Shared\post_process.py src\Main_App\Performance\process_runner.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_fft_crop_utils.py tests\test_process_runner_epoch_contract.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_postprocess_worker_qt.py tests\test_postprocess_worker_excel_payload.py tests\test_process_runner_epoch_contract.py tests\test_fft_crop_utils.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_post_export_adapter_no_fif.py tests\test_post_process_target_freqs.py tests\test_fft_neighbors_sheet.py tests\test_main_window_processing.py -q`
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Note: one pytest run printed the existing update-check network/proxy traceback after all selected tests passed with exit code 0.
