# Main App Refactor Plan

## Goal

Prepare `Main_App` for behavior-preserving refactors by keeping agent guidance, architecture docs, and mechanical checks synchronized with each change. The long-term target is to retire the confusing `Legacy_App` designation after runtime-used behavior has been migrated, wrapped, or renamed behind clearer current-app modules.

## Current Status

- Phase: refactor slices.
- Scope: behavior-preserving Main App organization.
- Behavior changes: eLORETA/Source Localization has been removed from active runtime; FPVS preprocessing, post-processing, FFT/SNR outputs, project paths, and exports remain behavior-preserving.
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
- Passed: `python -m py_compile src\Main_App\processing\__init__.py src\Main_App\processing\preprocess.py src\Main_App\PySide6_App\Backend\preprocess.py src\Main_App\Shared\processing_mixin.py src\Main_App\PySide6_App\Backend\processing_controller.py src\Main_App\Performance\process_runner.py src\Main_App\PySide6_App\GUI\main_window.py src\Main_App\__init__.py src\debug\audit_missing_results.py`
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

Next refactor slice candidate:

- Continue package-layout migration with another import-surface-only slice, likely `Main_App/diagnostics/` for audit/debug/reporting helpers or begin splitting `Main_App.gui.main_window` only after GUI import paths are stable. Keep wrappers until imports are stable.

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
