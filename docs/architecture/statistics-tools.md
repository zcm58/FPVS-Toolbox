# Statistics And Tool Modules

Statistics and tool code is split between active PySide6 surfaces, shared logic, and legacy compatibility modules.

Primary paths:

- `src/Tools/Stats/PySide6/`: active statistics GUI, controller, workers, analysis helpers, QC helpers, and reporting. The implementation is grouped by function; root modules are limited to stable entry points and intentionally retained high-coupling shims.
- `src/Tools/Stats/Legacy/`: legacy statistical routines and compatibility modules.
- `src/Tools/Stats/shared_rois.py` and `src/Tools/Stats/roi_resolver.py`: shared ROI helpers.
- `src/Tools/Plot_Generator/`: plot generation GUI, workers, and manifest helpers.
- `src/Tools/Ratio_Calculator/`: ratio calculator GUI, pipeline, exports, and plots.
- `src/Tools/Individual_Detectability/`: detectability tool core, GUI, and worker.

Stats PySide6 grouping:

- Root entry points: `stats_main_window.py`, `stats_ui_pyside6.py`, and `Tools.Stats.StatsWindow`.
- Root compatibility shims: old module names such as `stats_workers.py` re-export moved implementation modules while high-coupling callers are migrated.
- `ui/`: window mixins, dialogs, widget assembly, and small widgets.
- `controller/`: run coordination, pipeline state, and worker scheduling.
- `workers/`: Qt worker wrappers and GUI-agnostic statistical job execution.
- `data/`: project scans, manifests, subject IDs, group metadata, and missing input detection.
- `analysis/`: DV policy facade and focused helpers, harmonics, cross-phase statistics, and group contrasts.
- `qc/`: outlier, manual exclusion, QC exclusion, and QC report helpers.
- `reporting/`: plain-language summaries, workbook formatting, run reports, and logging.
- `common/`: shared dataclasses, enums, constants, and lightweight window types.

Rules:

- Preserve statistical output schemas and plain-language reporting unless explicitly changing them.
- Keep GUI imports PySide6-only.
- Keep public Stats entry points stable while compatibility shims exist.
- Add new analysis logic under the functional subpackage that owns it, and expose stable caller-facing surfaces through the package facade when needed.
- Run `python scripts/agent_audit.py --check stats-pyside6` after Stats PySide6 structural changes; it flags unexpected root modules and imports from removed root shims.
- Use focused tests around changed data transformations and exports.

Useful tests:

```powershell
python -m pytest tests/test_stats_pipeline_smoke.py tests/test_stats_layout_smoke.py -q
python -m pytest tests/test_ratio_calculator_plots.py tests/test_plot_generator_gui.py -q
```
