# Stats Tool Overview

The Stats package is organized by function. `Legacy/` and `PySide6/` are compatibility namespaces only; active code should import from `Tools.Stats.<area>`.

## Active Layout

* `ui/`, `controller/`, `workers/`, and `widgets/` - PySide6 window, run coordination, worker wrappers, and widgets.
* `analysis/` - statistical engines and analysis helpers, including DV policies, RM-ANOVA, mixed models, post-hocs, group contrasts, cross-phase LMM, SNR/noise helpers, and harmonics.
* `data/` - project scans, subject/group metadata, manifests, and missingness.
* `qc/` - QC, outlier, and manual exclusion helpers.
* `reporting/` - summaries, workbook exports, formatting, and run reports.
* `common/` - shared enums, dataclasses, constants, window types, and runtime helpers.
* `io/` - Excel/dataframe I/O helpers.
* `cli/` - out-of-process and command-line entry points.

## Compatibility Namespaces

* `PySide6/` keeps temporary aliases for old GUI import paths.
* `Legacy/` keeps temporary aliases for moved statistical engines plus fail-fast stubs for the removed CustomTkinter UI.
* New code should not import either namespace unless it is maintaining a compatibility shim or a quarantine test.

## Adding Statistical Features

Use the narrowest module that matches the behavior being changed:

* Add DV policy details to focused `analysis/dv_policy_*` modules and re-export stable functions through `analysis/dv_policies.py`.
* Keep worker/UI imports pointed at public facades, not private helper functions, unless a test intentionally targets a helper.
* Preserve existing DataFrame columns, metadata keys, workbook sheets, and log text unless the feature explicitly changes them.
* Put shared constants and lightweight data structures in `common/`; keep project scanning in `data/`, QC rules in `qc/`, and workbook/report text in `reporting/`.

Structural check:

```powershell
python scripts/agent_audit.py --check stats-pyside6
```
