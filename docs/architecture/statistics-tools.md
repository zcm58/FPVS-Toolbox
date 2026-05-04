# Statistics And Tool Modules

Statistics and tool code is organized under one active Stats package, with old `PySide6` and `Legacy` namespaces retained only for compatibility.

Primary paths:

- `src/Tools/Stats/`: active statistics GUI, controller, workers, analysis helpers, QC helpers, reporting, I/O, CLI, and shared helpers grouped by function.
- `src/Tools/Stats/PySide6/`: temporary compatibility aliases for old PySide6 import paths.
- `src/Tools/Stats/Legacy/`: temporary compatibility aliases for moved statistical engines plus fail-fast stubs for the removed CustomTkinter UI.
- `src/Tools/Stats/shared_rois.py` and `src/Tools/Stats/roi_resolver.py`: shared ROI helpers.
- `src/Tools/Plot_Generator/`: plot generation GUI, workers, and manifest helpers.
- `src/Tools/Ratio_Calculator/`: ratio calculator GUI, pipeline, exports, and plots.
- `src/Tools/Individual_Detectability/`: detectability tool core, GUI, and worker.

Stats grouping:

- Root entry points: `stats_main_window.py`, `stats_ui_pyside6.py`, and `Tools.Stats.StatsWindow`.
- `ui/`: window mixins, dialogs, widget assembly, and small widgets.
- `controller/`: run coordination, pipeline state, and worker scheduling.
- `workers/`: Qt worker wrappers and GUI-agnostic statistical job execution.
- `data/`: project scans, manifests, subject IDs, group metadata, and missing input detection.
- `analysis/`: DV policy facade and focused helpers, statistical engines, harmonics, cross-phase statistics, SNR/noise helpers, and group contrasts.
- `qc/`: outlier, manual exclusion, QC exclusion, and QC report helpers.
- `reporting/`: plain-language summaries, workbook formatting, run reports, and logging.
- `common/`: shared dataclasses, enums, constants, and lightweight window types.
- `io/`: Excel/dataframe I/O helpers.
- `cli/`: command-line and out-of-process job entry points.

Rules:

- Preserve statistical output schemas and plain-language reporting unless explicitly changing them.
- Keep GUI imports PySide6-only.
- Keep public Stats entry points stable while compatibility shims exist.
- New active code should import from `Tools.Stats.<functional area>`, not `Tools.Stats.Legacy` or `Tools.Stats.PySide6`.
- Add new analysis logic under the functional subpackage that owns it, and expose stable caller-facing surfaces through the package facade when needed.
- Run `python scripts/agent_audit.py --check stats-pyside6` after Stats structural changes; it flags unexpected compatibility usage and tkinter imports in active Stats code.
- Use focused tests around changed data transformations and exports.

Useful tests:

```powershell
python -m pytest tests/test_stats_pipeline_smoke.py tests/test_stats_layout_smoke.py -q
python -m pytest tests/test_ratio_calculator_plots.py tests/test_plot_generator_gui.py -q
```
