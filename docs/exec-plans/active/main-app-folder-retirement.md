# Main App Folder Retirement Plan

## Goal

Retire the historical `Legacy_App` and `PySide6_App` package designations by moving active code into purpose-based `src/Main_App/` folders. The end state should make Main App ownership obvious to future agents and humans without changing FPVS processing behavior.

This plan governs package ownership and file moves only. The existing `docs/exec-plans/active/main-app-refactor.md` remains the broader Main App refactor record.

## Current Status

- Phase: Legacy_App retirement complete; PySide6_App implementation-owner retirement can resume.
- Scope: behavior-preserving old-folder deletion gates and remaining PySide6_App package ownership moves.
- Canonical import surfaces now exist for `Main_App.gui`, `Main_App.processing`, `Main_App.io`, `Main_App.projects`, `Main_App.workers`, and `Main_App.diagnostics`.
- `Legacy_App` has been deleted from tracked Main App source.
- `PySide6_App` still owns many implementation modules, but reusable widgets and theme helpers have moved to canonical GUI ownership.
- Next work is resuming PySide6_App implementation moves, starting with processing-controller ownership.

## Target Layout

Active Main App code should land in purpose-based folders:

- `Main_App.gui`
- `Main_App.gui.widgets`
- `Main_App.processing`
- `Main_App.io`
- `Main_App.projects`
- `Main_App.workers`
- `Main_App.diagnostics`
- `Main_App.exports`
- `Main_App.shared`

Canonical packages should become implementation owners, not only forwarding wrappers. Temporary compatibility wrappers are allowed only when needed to keep a slice behavior-preserving, and each slice should reduce active dependence on `Main_App.Legacy_App` or `Main_App.PySide6_App`. The final goal is to remove active imports of both historical package names.

## Progress Snapshot

- `Main_App.processing`, `Main_App.io`, `Main_App.projects`, `Main_App.workers`, `Main_App.diagnostics`, and `Main_App.gui` are present.
- Several canonical modules still wrap or delegate to old implementation paths under `PySide6_App`.
- `Legacy_App` has no tracked Main App source files and must not be recreated.
- Active imports still remain for backend processing/project modules and GUI implementation wrappers.

## Classification Categories

Each tracked file under `src/Main_App/Legacy_App/` and `src/Main_App/PySide6_App/` must be classified before movement:

- Active implementation to move to a purpose-based package.
- Compatibility wrapper to delete after canonical imports are migrated.
- Replaced legacy code that should stay inactive until deletion is explicitly scoped.
- Dead code to remove after grep and focused checks prove it is unused.
- High-risk pipeline code that needs focused tests and contract docs before movement.

Record the chosen destination package, preservation checks, and any deletion rationale in this plan before implementing each move.

## Preservation Rules

Folder retirement must not change:

- preprocessing math, order, references, interpolation, filtering, event handling, or output formats
- BDF loading behavior, EXG typing, montage policy, memmap behavior, diagnostics, or unsupported-file behavior
- worker routing, signal payloads, queue behavior, cancellation, or threading
- project schema, project root behavior, generated paths, manifests, or dialogs
- post-processing math, Excel workbook names, sheet names, columns, formatting, FFT-neighbor rows, or export success behavior

Do not add new `Main_App.Legacy_App` or `Main_App.PySide6_App` imports. Existing compatibility imports should be migrated toward canonical purpose-based packages before old folders are removed.

## Deletion Gates

Before deleting any old-folder wrapper, implementation module, package marker, or scoped `AGENTS.md` file:

- `git grep` must show no active imports from the old package being deleted, except docs or intentionally retained compatibility tests.
- Focused tests for the touched domain must pass.
- `python scripts/agent_audit.py` must pass.
- `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` must pass.
- Useful scoped guidance from old `AGENTS.md` files must be moved to top-level guidance or focused architecture docs before the old folders are removed.

## Initial Inventory Slice

The first slice under this plan is documentation-only and now complete:

1. Classify every tracked file under `src/Main_App/Legacy_App/`.
2. Classify every tracked file under `src/Main_App/PySide6_App/`.
3. Identify the canonical destination package for each active implementation.
4. Identify focused tests required before each high-risk move.
5. Record the next executable slice, likely low-risk GUI/widget implementation moves.

## Legacy_App Inventory

| Files | Classification | Destination or disposition | Required checks before move/delete |
| --- | --- | --- | --- |
| `AGENTS.md`, `__init__.py` | Deleted scoped guidance/package marker | Deleted after relevant guidance moved to top-level and focused docs | `python scripts/agent_audit.py`; grep for `Main_App.Legacy_App` |
| `debug_utils.py` | Deleted stale developer/runtime logging helper | Deleted after script cleanup; no active callers remain | compile affected scripts; `git grep -n "debug_utils" -- src tests scripts` |
| `eeg_preprocessing.py` | Deleted replaced legacy code | Deleted after active preprocessing owner remained `Main_App.processing.preprocess` and no imports remained | preprocessing contract tests; `git grep -n "Legacy_App.eeg_preprocessing" -- src tests scripts` |
| `fft_crop_utils.py` | Deleted compatibility wrapper | Deleted after all callers used `Main_App.Shared.fft_crop_utils` | FFT crop tests; post-processing/export tests |
| `file_selection.py` | Deleted replaced legacy GUI mixin | Deleted after grep confirmed no active callers | GUI smoke tests; `git grep -n "FileSelectionMixin\\|file_selection" -- src tests scripts` |
| `load_utils.py` | Deleted compatibility wrapper | Deleted after all callers used `Main_App.io.load_utils` | loader tests; process-runner tests |
| `post_process.py` | Deleted compatibility wrapper | Deleted after all callers used `Main_App.Shared.post_process` | post-processing/export tests; workbook tests |
| `post_process_excel.py` | Deleted compatibility wrapper | Deleted after all callers used `Main_App.Shared.post_process_excel` | FFT-neighbor workbook tests; Excel payload tests |
| `processing_utils.py` | Deleted compatibility wrapper | Deleted after all callers used `Main_App.Shared.processing_mixin` | main-window processing tests; single-file mode tests |
| `settings_manager.py` | Deleted replaced legacy settings implementation | Deleted after confirming `Main_App.Shared.settings_manager` is canonical and no legacy imports remain | project settings roundtrip; settings/status tests |

## PySide6_App Inventory

| Files | Classification | Destination or disposition | Required checks before move/delete |
| --- | --- | --- | --- |
| `__init__.py`, package `__init__.py` files | Package markers | Delete when old package folders are empty | grep for `Main_App.PySide6_App`; import smoke tests |
| `Backend/AGENTS.md`, `GUI/AGENTS.md` | Scoped guidance | Merge any still-relevant guidance into `AGENTS.md` or architecture docs before deleting folders | `python scripts/agent_audit.py` |
| `Backend/loader.py` | Compatibility wrapper | Delete after all imports use `Main_App.io.load_utils` | loader warning/suppression tests |
| `Backend/preprocess.py` | Active implementation; high-risk pipeline code | Move to `Main_App.processing.preprocess` only with contract tests proving identical behavior | preprocessing audit/FIF/process-runner tests |
| `Backend/preprocessing_settings.py` | Compatibility wrapper | Delete after stale callers migrate to `Main_App.projects.preprocessing_settings` | preprocessing settings and persistence tests |
| `Backend/processing.py`, `Backend/processing_controller.py` | Active processing orchestration | Move to `Main_App.processing` | main-window processing, process-runner, worker integration tests |
| `Backend/project_metadata.py`, `config/projects_root.py` | Compatibility wrappers | Delete after stale callers migrate to `Main_App.projects.project_metadata` and `Main_App.projects.projects_root` | project enumeration, project settings, project paths tests |
| `Backend/project.py`, `Backend/project_manager.py` | Compatibility wrappers | Delete after stale callers migrate to `Main_App.projects.project` and `Main_App.projects.project_manager` | project settings, project scan, project paths tests |
| `adapters/post_export_adapter.py` | Compatibility wrapper | Delete after stale callers migrate to `Main_App.exports.post_export_adapter` | post-export adapter and worker Excel payload tests |
| `diagnostics/event_time_lock_report.py`, `utils/audit.py` | Active runtime diagnostics | Move to `Main_App.diagnostics` | event-time lock and audit field/json tests |
| `utils/op_guard.py`, `utils/paths.py` | Compatibility wrappers | Delete after stale callers migrate to `Main_App.gui.op_guard` and `Main_App.Shared.paths` | GUI smoke, settings/status, tool smoke tests |
| `utils/theme.py` | Compatibility wrapper | Delete after stale callers migrate to `Main_App.gui.theme` | GUI smoke, settings/status, tool smoke tests |
| `GUI/event_map.py`, `GUI/file_menu.py`, `GUI/header_bar.py`, `GUI/icons.py`, `GUI/menu_bar.py`, `GUI/roi_settings_editor.py`, `GUI/settings_panel.py`, `GUI/sidebar.py`, `GUI/style_tokens.py`, `GUI/ui_main.py`, `GUI/update_manager.py` | Active GUI implementation | Move to `Main_App.gui`; keep wrappers only during the migration slice | main-window layout, settings/status, startup import, focused GUI tests |
| `GUI/main_window.py` | Active GUI shell; already downsized | Move path to `Main_App.gui.main_window` without new internal refactor | main-window layout/processing/startup tests |
| `GUI/icons/snr_plots.svg` | GUI asset | Move with the GUI module that loads it, likely under `Main_App.gui/icons/` | GUI smoke tests that load icons |
| `widgets/brain_pulse.py`, `widgets/busy_spinner.py`, `widgets/buttons.py`, `widgets/cards.py`, `widgets/forms.py`, `widgets/status.py`, `widgets/__init__.py` | Compatibility wrappers | Delete after stale callers migrate to `Main_App.gui.widgets` | widget smoke tests; tool GUI smoke tests |
| `workers/mp_runner_bridge.py`, `workers/processing_worker.py` | Active Qt worker implementations | Move to `Main_App.workers` after lower-risk GUI moves | worker integration, postprocess worker, multiprocessing smoke tests |

## Current Import Findings

- `Legacy_App` imports in active source are removed; remaining direct references should be docs, audits, or historical plan notes only.
- `PySide6_App` still owns many active implementations. Current top-level packages such as `Main_App.gui`, `Main_App.projects`, `Main_App.workers`, `Main_App.processing`, and `Main_App.diagnostics` often delegate into `PySide6_App`.
- Tool packages, tests, and active source now import reusable widgets/theme helpers from `Main_App.gui.widgets` and `Main_App.gui.theme`. The old `PySide6_App` widget/theme paths are temporary wrappers only.

## Verification

For this documentation-only setup:

- `git diff --check`
- `python scripts/agent_audit.py`
- `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py`

For future movement slices, also run the focused tests for the touched domain and the relevant skill-local audits from `docs/agent-index.md`.

## Decisions

- Retiring the old folder names is a package-ownership refactor, not a behavior rewrite.
- `Legacy_App` has been retired; do not recreate it.
- `PySide6_App` is the current implementation source for many modules, but the package name should not remain the long-term architecture boundary.
- `main_window.py` has already been appropriately downsized. It may move to a new package path as part of folder retirement, but it should not be the target of another internal refactor unless explicitly requested.

## Execution Queue

1. Move reusable GUI widgets and theme helpers into `Main_App.gui.widgets` and `Main_App.gui.theme`. Status: complete.
2. Move GUI/runtime utilities such as `op_guard` and path helpers to canonical GUI or shared homes. Status: complete.
3. Move post-export adapter implementation to `Main_App.exports`. Status: complete.
4. Move backend processing and project implementations behind the existing canonical packages. Status: active; project implementations and `Backend/processing.py` are complete, `processing_controller.py` remains.
5. Delete stale `Legacy_App` GUI/debug compatibility after grep and focused tests prove no active imports remain. Status: complete.
6. Delete `Legacy_App` wrappers after grep and focused tests prove no active imports remain. Status: complete.
7. Delete inactive `Legacy_App/eeg_preprocessing.py` only after preprocessing ownership and contract checks pass. Status: complete.
8. Resume PySide6_App implementation moves, starting with `processing_controller.py`. Status: next.
9. Delete `PySide6_App` package markers after all implementation ownership has moved.

Latest executable slice:

- Moved reusable widget implementations to `src/Main_App/gui/widgets/`.
- Moved theme implementation to `src/Main_App/gui/theme.py`.
- Replaced old `src/Main_App/PySide6_App/widgets/` and `src/Main_App/PySide6_App/utils/theme.py` modules with temporary compatibility wrappers.
- Updated active source, tools, tests, and scripts to import `Main_App.gui.widgets` and `Main_App.gui.theme`.
- Passed focused widget/theme, main-window, and selected tool smoke tests.
- Passed `python scripts/agent_audit.py`, GUI import audit, legacy-boundary audit, and `git diff --check` with line-ending warnings only.

Latest executable slice:

- Moved `src/Main_App/PySide6_App/utils/op_guard.py` to `src/Main_App/gui/op_guard.py`.
- Moved `src/Main_App/PySide6_App/utils/paths.py` to `src/Main_App/Shared/paths.py`.
- Replaced old PySide6 utility modules with temporary compatibility wrappers.
- Updated active imports to use `Main_App.gui.op_guard`.
- Passed compile, project, main-window, and Stats focused checks.
- Passed grep for old active utility imports.

Latest executable slice:

- Move `src/Main_App/PySide6_App/adapters/post_export_adapter.py` to `Main_App.exports.post_export_adapter`.
- Replaced the old PySide6 adapter module with a temporary compatibility wrapper.
- Updated active process-runner, worker, and tests to import `Main_App.exports.post_export_adapter`.
- Passed compile, post-export adapter, worker, main-window export, process-runner contract, and source-local FFT crop process-runner checks.
- Passed grep for old active adapter imports.

Latest project helper slice:

- Moved `src/Main_App/PySide6_App/Backend/preprocessing_settings.py` to `src/Main_App/projects/preprocessing_settings.py`.
- Moved `src/Main_App/PySide6_App/Backend/project_metadata.py` to `src/Main_App/projects/project_metadata.py`.
- Moved `src/Main_App/PySide6_App/config/projects_root.py` to `src/Main_App/projects/projects_root.py`.
- Replaced the old PySide6 backend/config modules with temporary compatibility wrappers.
- Active source, tests, and scripts already use the canonical `Main_App.projects` imports for these helpers.
- Passed compile, preprocessing settings, project persistence, project enumeration, project scan, project open-dialog, main-window processing, worker integration, Plot Generator project, and Stats project-path checks.
- Passed grep for old active project-helper imports.

Latest executable slice:

- Move `src/Main_App/PySide6_App/Backend/project.py` and then `project_manager.py` behind `Main_App.projects`, keeping wrappers and project I/O checks.
- Replaced the old PySide6 backend modules with temporary compatibility wrappers.
- Updated the remaining direct project-manager test import to use `Main_App.projects`.
- Converted moved project warning `print` calls to structured logging to preserve repo production-code audit rules.
- Passed compile, project settings, project results layout, project enumeration, project scan, open-project dialog, preprocessing settings, project bandpass migration, main-window processing, worker integration, Plot Generator multigroup, Stats multigroup, and Stats project-path checks.
- Passed agent audit, project-path audit, legacy-boundary audit, old project import grep, and `git diff --check` with line-ending warnings only.

Latest executable slice:

- Moved `src/Main_App/PySide6_App/Backend/processing.py` to `src/Main_App/processing/processing.py`.
- Replaced the old PySide6 backend module with a temporary compatibility wrapper.
- Updated the active processing controller and focused main-window processing test to import `Main_App.processing.processing`.
- Behavior-preservation rule: no processing implementation, preprocessing route, worker routing, project I/O, post-processing, export format, or GUI workflow changed; `process_data` remains the same no-op coordinator.
- Passed: `python -m py_compile src\Main_App\processing\processing.py src\Main_App\PySide6_App\Backend\processing.py src\Main_App\processing\__init__.py src\Main_App\PySide6_App\Backend\processing_controller.py tests\test_main_window_processing.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_worker_integration.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_process_runner_epoch_contract.py tests\test_postprocess_worker_excel_payload.py -q`
- Passed: `git grep -n "PySide6_App.Backend.processing import process_data\|Main_App.PySide6_App.Backend import processing\|import Main_App.PySide6_App.Backend.processing" -- src tests scripts` found no matches.
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `git diff --check` with line-ending warnings only.

Current Legacy_App executable slice:

- Remove stale top-level lazy exports for missing/quarantined Legacy GUI modules from `src/Main_App/__init__.py`.
- Remove the obsolete GUI smoke stub for `Main_App.Legacy_App.debug_utils`.
- Delete `src/Main_App/Legacy_App/debug_utils.py` and `src/Main_App/Legacy_App/file_selection.py` after grep confirms no active callers.
- Behavior-preservation rule: no preprocessing, BDF loading, worker routing, processing order, project I/O, post-processing, exports, or active GUI workflows may change.
- Status: complete.
- Passed: `python -m py_compile src\Main_App\__init__.py src\Main_App\PySide6_App\GUI\main_window.py scripts\gui_wave3_smoke.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_startup_imports_no_customtkinter.py tests\test_main_window_layout_smoke.py tests\test_main_window_processing.py -q`
- Passed: `git grep -n "Main_App.Legacy_App.debug_utils\|Main_App.Legacy_App.file_selection\|from Main_App.Legacy_App import debug_utils\|from Main_App.Legacy_App import file_selection" -- src tests scripts` found no matches.
- Passed: `git grep -n "SettingsWindow\|RelevantPublicationsWindow\|AppMenuBar\|SetupPanelManager\|EventMapManager\|EventMapMixin\|FileSelectionMixin\|EventDetectionMixin\|ValidationMixin\|_lazy_import" -- src tests scripts` found no matches.
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with line-ending warnings only.
- Skipped: `python scripts\gui_wave3_smoke.py`; after the stale debug stub was removed, this developer smoke script hung and was intentionally not used as a blocker for this Legacy_App cleanup slice.

Next executable slice after this Legacy cleanup:

- Delete inactive `Legacy_App/eeg_preprocessing.py` with preprocessing ownership checks, then remove `Legacy_App/AGENTS.md` and package markers if no files remain.

Latest Legacy_App wrapper deletion slice:

- Deleted `src/Main_App/Legacy_App/settings_manager.py`, `src/Main_App/Legacy_App/load_utils.py`, and `src/Main_App/Legacy_App/processing_utils.py`.
- Updated shared owner docstrings and focused docs so `Main_App.Shared.settings_manager`, `Main_App.io.load_utils`, `Main_App.Shared.load_utils`, and `Main_App.Shared.processing_mixin` are the only documented active owners.
- Behavior-preservation rule: no settings behavior, BDF loading behavior, preprocessing, processing order, worker routing, project I/O, post-processing, exports, or GUI workflows changed.
- Passed: `python -m py_compile src\Main_App\Shared\settings_manager.py src\Main_App\Shared\load_utils.py src\Main_App\Shared\processing_mixin.py src\Main_App\io\load_utils.py src\Main_App\__init__.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_shared_load_utils.py tests\test_loader_warning_suppression.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_project_settings_roundtrip.py tests\test_settings_and_status.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_single_file_process_mode.py -q`
- Passed: `git grep -n "Main_App.Legacy_App.settings_manager\|Main_App.Legacy_App.load_utils\|Main_App.Legacy_App.processing_utils\|from Main_App.Legacy_App import settings_manager\|from Main_App.Legacy_App import load_utils\|from Main_App.Legacy_App import processing_utils" -- src tests scripts` found no matches.
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with line-ending warnings only.

Final Legacy_App retirement slice:

- Confirmed no active runtime, test, or script imports use `Main_App.Legacy_App.eeg_preprocessing` before deletion.
- Deleted `src/Main_App/Legacy_App/eeg_preprocessing.py`, `src/Main_App/Legacy_App/AGENTS.md`, and `src/Main_App/Legacy_App/__init__.py`.
- Added an agent-audit guard so recreated files under `src/Main_App/Legacy_App/**` fail the harness check.
- Updated top-level agent, architecture, quality, and legacy-boundary docs to state that `Legacy_App` is retired, not an editable migration boundary.
- Behavior-preservation rule: no preprocessing implementation, preprocessing math/order, BDF loading, worker routing, project I/O, post-processing, exports, or GUI workflows changed.
- Passed: `python -m py_compile scripts\agent_audit.py src\Main_App\processing\preprocess.py src\Main_App\PySide6_App\Backend\preprocess.py src\Main_App\Shared\processing_mixin.py src\Main_App\Performance\process_runner.py src\Main_App\PySide6_App\Backend\processing_controller.py src\Main_App\__init__.py src\Main_App\Shared\post_process.py src\config.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_preproc_audit.py tests\test_fif_flag_audit.py tests\test_process_runner_epoch_contract.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_main_window_processing.py tests\test_single_file_process_mode.py -q`
- Passed: `git grep -n "Main_App.Legacy_App.eeg_preprocessing\|from Main_App.Legacy_App import eeg_preprocessing\|Legacy_App.*perform_preprocessing\|eeg_preprocessing" -- src tests scripts` found no matches.
- Passed: `git grep -n "from Main_App.Legacy_App\|import Main_App.Legacy_App" -- src tests scripts` found no matches.
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with line-ending warnings only.
- Next executable slice: resume `PySide6_App` retirement by moving `processing_controller.py` behind `Main_App.processing` with wrappers and focused processing tests.

Latest Legacy_App wrapper deletion slice:

- Deleted `src/Main_App/Legacy_App/fft_crop_utils.py`, `src/Main_App/Legacy_App/post_process.py`, and `src/Main_App/Legacy_App/post_process_excel.py`.
- Updated FFT crop, post-processing export, module-map, and legacy quarantine docs so no `Legacy_App` compatibility wrappers are described as active.
- Behavior-preservation rule: no FFT crop behavior, post-processing math, workbook generation, sheet names, columns, formatting, worker routing, project I/O, preprocessing, or exports changed.
- Passed: `python -m py_compile src\Main_App\Shared\fft_crop_utils.py src\Main_App\Shared\post_process.py src\Main_App\Shared\post_process_excel.py src\Main_App\Performance\process_runner.py src\Main_App\exports\post_export_adapter.py`
- Passed: `.venv\Scripts\python -m pytest tests\test_fft_crop_utils.py tests\test_fft_neighbors_sheet.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_post_export_adapter_no_fif.py tests\test_post_process_target_freqs.py tests\test_postprocess_worker_excel_payload.py -q`
- Passed: `.venv\Scripts\python -m pytest tests\test_process_runner_epoch_contract.py tests\test_postprocess_worker_qt.py tests\test_main_window_excel_popup_logic.py -q`
- Passed: `git grep -n "Main_App.Legacy_App.fft_crop_utils\|Main_App.Legacy_App.post_process\|Main_App.Legacy_App.post_process_excel\|from Main_App.Legacy_App import fft_crop_utils\|from Main_App.Legacy_App import post_process\|from Main_App.Legacy_App import post_process_excel" -- src tests scripts` found no matches.
- Passed: `python scripts\agent_audit.py`
- Passed: `python .agents\skills\legacy-boundary-review\scripts\audit_protected_edits.py`
- Passed: `python .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py`
- Passed: `git diff --check` with line-ending warnings only.
