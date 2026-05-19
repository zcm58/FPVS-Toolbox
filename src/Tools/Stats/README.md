# Stats Tool Overview

The Stats package is organized by function. Active code should import from `Tools.Stats.<area>`.

The package root contains only `__init__.py`, this README, and `AGENTS.md`.
Implementation files belong in the functional subpackages below.

## Active Layout

* `ui/`, `controller/`, `workers/`, and `widgets/` - PySide6 window, run coordination, worker wrappers, and widgets. `Tools.Stats.StatsWindow` is the public import; the implementation lives in `ui.stats_window`.
* `analysis/` - statistical engines and analysis helpers, including DV policies, RM-ANOVA, mixed models, post-hocs, SNR/noise helpers, and harmonics.
* `data/` - project scans, subject metadata, manifests, ROI resolution, and shared ROI settings.
* `qc/` - QC, outlier, and manual exclusion helpers.
* `reporting/` - summaries, workbook exports, formatting, and run reports.
* `common/` - shared enums, dataclasses, constants, window types, and runtime helpers.
* `io/` - Excel/dataframe I/O helpers.

## Removed Namespaces

* `Tools.Stats.PySide6` and `Tools.Stats.Legacy` are no longer supported import paths.
* Reference source for the removed CustomTkinter Stats UI remains under `src/quarantine/Tools/Stats/Legacy_UI/`.
* New code should import from the active functional packages only.

## Adding Statistical Features

Use the narrowest module that matches the behavior being changed:

* Add DV policy details to focused `analysis/dv_policy_*` modules and re-export stable functions through `analysis/dv_policies.py`.
* Keep worker/UI imports pointed at public facades, not private helper functions, unless a test intentionally targets a helper.
* Preserve existing DataFrame columns, metadata keys, workbook sheets, and log text unless the feature explicitly changes them.
* Put shared constants and lightweight data structures in `common/`; keep project scanning in `data/`, QC rules in `qc/`, and workbook/report text in `reporting/`.

Structural check:

```powershell
python .agents/scripts/audit/agent_audit.py --check stats-structure
```
