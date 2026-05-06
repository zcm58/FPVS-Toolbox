# Main App Folder Retirement Plan

## Goal

Retire the historical `Legacy_App` and `PySide6_App` package designations by moving active code into purpose-based `src/Main_App/` folders. The end state should make Main App ownership obvious to future agents and humans without changing FPVS processing behavior.

This plan governs package ownership and file moves only. The existing `docs/exec-plans/active/main-app-refactor.md` remains the broader Main App refactor record.

## Current Status

- Phase: canonical import surfaces exist; implementation-owner retirement is active.
- Scope: behavior-preserving package ownership moves and old-folder deletion gates.
- Canonical import surfaces now exist for `Main_App.gui`, `Main_App.processing`, `Main_App.io`, `Main_App.projects`, `Main_App.workers`, and `Main_App.diagnostics`.
- `Legacy_App` is mostly compatibility wrappers or inactive legacy code.
- `PySide6_App` still owns many implementation modules, but reusable widgets and theme helpers have moved to canonical GUI ownership.
- Next work is moving implementations into purpose-based packages and deleting wrappers only after import and test gates pass.

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
- `Legacy_App` references in active code are already mostly wrappers, inactive legacy modules, docs, or smoke-test stubs.
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
| `AGENTS.md`, `__init__.py` | Scoped guidance/package marker | Delete when `Legacy_App` is empty; carry any still-relevant guidance into top-level docs first | `python scripts/agent_audit.py`; grep for `Main_App.Legacy_App` |
| `debug_utils.py` | Developer/runtime logging helper with stale script reference | Move only if still needed to `Main_App.diagnostics.debug_utils`; otherwise delete after script cleanup | compile affected scripts; `git grep -n "debug_utils" -- src tests scripts` |
| `eeg_preprocessing.py` | Replaced legacy code; high-risk inactive pipeline implementation | Delete only after active preprocessing owner remains `Main_App.processing.preprocess` and no imports remain | preprocessing contract tests; `git grep -n "Legacy_App.eeg_preprocessing" -- src tests scripts` |
| `fft_crop_utils.py` | Compatibility wrapper | Delete after all callers use `Main_App.Shared.fft_crop_utils` or a future `Main_App.exports` owner | FFT crop tests; post-processing/export tests |
| `file_selection.py` | Replaced legacy GUI mixin | Delete after grep confirms no active callers | GUI smoke tests; `git grep -n "FileSelectionMixin\\|file_selection" -- src tests scripts` |
| `load_utils.py` | Compatibility wrapper | Delete after all callers use `Main_App.io.load_utils` | loader tests; process-runner tests |
| `post_process.py` | Compatibility wrapper | Move final ownership toward `Main_App.exports`; delete wrapper after callers migrate | post-processing/export tests; workbook tests |
| `post_process_excel.py` | Compatibility wrapper | Move final ownership toward `Main_App.exports`; delete wrapper after callers migrate | FFT-neighbor workbook tests; Excel payload tests |
| `processing_utils.py` | Compatibility wrapper | Delete after all callers use `Main_App.Shared.processing_mixin` or a future purpose-based owner | main-window processing tests; single-file mode tests |
| `settings_manager.py` | Replaced legacy settings implementation | Delete after confirming `Main_App.Shared.settings_manager` is canonical and no legacy imports remain | project settings roundtrip; settings/status tests |

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

- `Legacy_App` imports in active source are already mostly removed; remaining direct references are documentation strings, compatibility wrappers, and a GUI smoke script stub.
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
- `Legacy_App` is no longer a permanent protected black box; targeted edits or deletion are allowed only when documented and pipeline-preserving.
- `PySide6_App` is the current implementation source for many modules, but the package name should not remain the long-term architecture boundary.
- `main_window.py` has already been appropriately downsized. It may move to a new package path as part of folder retirement, but it should not be the target of another internal refactor unless explicitly requested.

## Execution Queue

1. Move reusable GUI widgets and theme helpers into `Main_App.gui.widgets` and `Main_App.gui.theme`. Status: complete.
2. Move GUI/runtime utilities such as `op_guard` and path helpers to canonical GUI or shared homes. Status: complete.
3. Move post-export adapter implementation to `Main_App.exports`. Status: complete.
4. Move backend processing and project implementations behind the existing canonical packages.
5. Move remaining GUI implementation modules, including `main_window.py`, after wrapper dependencies are thin.
6. Delete `Legacy_App` wrappers after grep and focused tests prove no active imports remain.
7. Delete `PySide6_App` package markers after all implementation ownership has moved.

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

Next executable slice:

- Move remaining backend processing coordination modules in small slices. Prefer `Backend/processing.py` before `processing_controller.py`; do not move `preprocess.py` until preprocessing behavior coverage is explicitly reviewed again.
