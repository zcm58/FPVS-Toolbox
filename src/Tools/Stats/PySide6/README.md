# Stats (PySide6) overview

The PySide6 Stats layer wraps the legacy statistical routines with a Qt-based UI and worker orchestration.
This package stays thin: the view renders widgets and forwards user actions, while workers and legacy
code handle the calculations.

## Internal structure (MVC-ish)

The implementation is grouped by function. Root-level modules are limited to stable entry points and the few
remaining high-coupling compatibility shims; new internal code should import from the functional subpackages
unless it needs a documented public surface.

* **View**
  * `stats_main_window.py` - stable root `QMainWindow` class and compatibility imports.
  * `ui/stats_window_ui.py` - UI assembly for controls, splitters, status rows, and output tabs.
  * `ui/stats_window_actions.py` - button handlers, folder selection, copy/open helpers, and default folder loading.
  * `ui/stats_window_exclusions.py` - DV policy controls, outlier flagging, manual exclusions, and flagged participant dialogs.
  * `ui/stats_window_multigroup.py` - multi-group scan state, shared harmonics, fixed-harmonic DV, and missingness summaries.
  * `ui/stats_window_pipeline.py` - controller-facing methods, worker wiring, run lifecycle, summaries, and result handlers.
  * `ui/stats_window_exports.py` - result directory handling, workbook exports, metadata, and export finalization.
  * `stats_ui_pyside6.py` - thin entry point that exposes `StatsWindow` and legacy worker hooks for tests.
* **Controller**
  * `controller/stats_controller.py` - coordinates the Single and Between pipelines, run state, and worker scheduling.
* **Workers/data/services**
  * `workers/stats_workers.py` - worker runner and pure statistical job functions.
  * `data/stats_data_loader.py` - scans projects/manifests and normalizes metadata.
  * `data/stats_subjects.py`, `data/stats_multigroup_ids.py`, and `data/stats_multigroup_scan.py` - subject and group metadata helpers.
  * `data/stats_missingness.py` - missingness summaries and exports.
* **Analysis/QC/reporting**
  * `analysis/dv_policies.py` - public DV policy facade; focused `analysis/dv_policy_*` modules hold settings, fixed-K, fixed-shared, Rossion, and trace helpers.
  * `analysis/` - harmonic selection, cross-phase statistics, and group contrasts.
  * `qc/` - outlier, manual exclusion, QC exclusion, and QC report helpers.
  * `reporting/` - plain-language summaries, workbook formatting, run reports, and logging.
* **Support**
  * `common/stats_core.py` - shared enums, data classes, and constants.
  * `common/stats_window_types.py` - small shared Stats window types.
  * `ui/stats_window_support.py` - shared import surface for the window mixin modules.

## Package layout

The root package keeps stable entry points and compatibility shims. The implementation lives in:

```text
PySide6/
  stats_main_window.py  # stable StatsWindow public entry point
  stats_ui_pyside6.py   # compatibility entry point used by tests and callers
  ui/          # QMainWindow, window mixins, dialogs, widget assembly, small widgets
  controller/  # run coordination, state transitions, worker scheduling
  workers/     # Qt worker wrappers and GUI-agnostic statistical job execution
  data/        # project/manifests scans, subject IDs, group metadata, missing inputs
  analysis/    # DV policies, harmonics, cross-phase stats, group contrasts
  qc/          # outlier, manual, and QC exclusion/report helpers
  reporting/   # plain-language summaries, workbook formatting, run reports, logging
  common/      # shared dataclasses, enums, constants, and lightweight types
```

Compatibility rules:

1. Keep `stats_main_window.py`, `stats_ui_pyside6.py`, and `Tools.Stats.StatsWindow` stable.
2. Keep root-level compatibility shims only while active callers and tests still depend on old module names.
3. Prefer direct subpackage imports for new internal code.

## Adding DV or statistical analysis features

Use the narrowest module that matches the behavior being changed:

* Add new DV policy implementation details to a focused `analysis/dv_policy_*` module.
* Re-export stable policy constants/functions through `analysis/dv_policies.py`; callers should import this facade instead of helper modules.
* Keep worker/UI imports pointed at public facades, not private helper functions, unless a test is intentionally targeting a helper.
* Preserve existing DataFrame columns, metadata keys, workbook sheets, and log text unless the feature explicitly changes them.
* Put shared constants, enums, and lightweight data structures in `common/`; keep project scanning in `data/`, QC rules in `qc/`, and workbook/report text in `reporting/`.

Structural enforcement:

```powershell
python scripts/agent_audit.py --check stats-pyside6
```

This check rejects unexpected root-level Stats PySide6 modules and imports from removed root compatibility shims.

### Pipeline flow

`Analyze` button -> `StatsController` launches pipeline -> `StatsWorker` executes legacy stats code ->
DataFrames/exports -> `summary_utils` builds summaries -> `StatsWindow` displays status/log updates.

Worker logic and legacy statistical math intentionally stay GUI-agnostic to keep the view simple.
