# Main App Folder Retirement Plan

## Goal

Retire the historical `Legacy_App` and `PySide6_App` package designations by moving active code into purpose-based `src/Main_App/` folders. The end state should make Main App ownership obvious to future agents and humans without changing FPVS processing behavior.

This plan governs package ownership and file moves only. The existing `docs/exec-plans/active/main-app-refactor.md` remains the broader Main App refactor record.

## Current Status

- Phase: inventory complete; ready for first low-risk movement slice.
- Scope: documentation and future behavior-preserving package moves.
- Latest slice: classified tracked files under `src/Main_App/Legacy_App/` and `src/Main_App/PySide6_App/`.
- No code movement has started under this plan.

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

Temporary compatibility wrappers are allowed only when needed to keep a slice behavior-preserving. The final goal is to remove active imports of `Main_App.Legacy_App` and `Main_App.PySide6_App`.

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
| `Backend/preprocessing_settings.py` | Active project/settings implementation | Move to `Main_App.projects.preprocessing_settings` | preprocessing settings and persistence tests |
| `Backend/processing.py`, `Backend/processing_controller.py` | Active processing orchestration | Move to `Main_App.processing` | main-window processing, process-runner, worker integration tests |
| `Backend/project.py`, `Backend/project_manager.py`, `Backend/project_metadata.py`, `config/projects_root.py` | Active project implementation | Move to `Main_App.projects` | project settings, project scan, project paths tests |
| `adapters/post_export_adapter.py` | Active export adapter | Move to `Main_App.exports.post_export_adapter` | post-export adapter and worker Excel payload tests |
| `diagnostics/event_time_lock_report.py`, `utils/audit.py` | Active runtime diagnostics | Move to `Main_App.diagnostics` | event-time lock and audit field/json tests |
| `utils/op_guard.py`, `utils/paths.py`, `utils/theme.py` | Active shared GUI/runtime utilities | Move to `Main_App.gui` or `Main_App.gui.utils` by usage | GUI smoke, settings/status, tool smoke tests |
| `GUI/event_map.py`, `GUI/file_menu.py`, `GUI/header_bar.py`, `GUI/icons.py`, `GUI/menu_bar.py`, `GUI/roi_settings_editor.py`, `GUI/settings_panel.py`, `GUI/sidebar.py`, `GUI/style_tokens.py`, `GUI/ui_main.py`, `GUI/update_manager.py` | Active GUI implementation | Move to `Main_App.gui`; keep wrappers only during the migration slice | main-window layout, settings/status, startup import, focused GUI tests |
| `GUI/main_window.py` | Active GUI shell; already downsized | Move path to `Main_App.gui.main_window` without new internal refactor | main-window layout/processing/startup tests |
| `GUI/icons/snr_plots.svg` | GUI asset | Move with the GUI module that loads it, likely under `Main_App.gui/icons/` | GUI smoke tests that load icons |
| `widgets/brain_pulse.py`, `widgets/busy_spinner.py`, `widgets/buttons.py`, `widgets/cards.py`, `widgets/forms.py`, `widgets/status.py`, `widgets/__init__.py` | Active reusable GUI widgets | Move to `Main_App.gui.widgets`; this is the likely first code-move slice | widget smoke tests; tool GUI smoke tests |
| `workers/mp_runner_bridge.py`, `workers/processing_worker.py` | Active Qt worker implementations | Move to `Main_App.workers` after lower-risk GUI moves | worker integration, postprocess worker, multiprocessing smoke tests |

## Current Import Findings

- `Legacy_App` imports in active source are already mostly removed; remaining direct references are documentation strings, compatibility wrappers, and a GUI smoke script stub.
- `PySide6_App` still owns many active implementations. Current top-level packages such as `Main_App.gui`, `Main_App.projects`, `Main_App.workers`, `Main_App.processing`, and `Main_App.diagnostics` often delegate into `PySide6_App`.
- Tool packages and tests still import `Main_App.PySide6_App.widgets` and `Main_App.PySide6_App.utils.theme`; moving widgets/theme utilities to `Main_App.gui` should be the first code-move slice because it is low-risk and reduces many stale imports.

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

## Next Slice Candidate

Move reusable PySide6 GUI widgets and theme helpers into the canonical GUI package:

- `src/Main_App/PySide6_App/widgets/*` to `src/Main_App/gui/widgets/`
- `src/Main_App/PySide6_App/utils/theme.py` to `src/Main_App/gui/theme.py` or `src/Main_App/gui/utils/theme.py`

Preserve widget behavior and keep temporary wrappers until active source, tools, and tests import the canonical paths.
