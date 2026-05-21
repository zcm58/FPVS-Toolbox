# Statistics And Tool Modules

Statistics and tool code is organized under one active Stats package. Old `PySide6` and `Legacy` Stats import namespaces have been removed.

Primary paths:

- `src/Tools/Stats/`: active single-group statistics GUI, controller, workers, analysis helpers, QC helpers, reporting, I/O, and shared helpers grouped by function. The root contains only package/docs files.
- `src/Tools/Stats/data/shared_rois.py` and `src/Tools/Stats/data/roi_resolver.py`: shared ROI helpers.
- `src/quarantine/Tools/Stats/Legacy_UI/`: reference-only source for the removed CustomTkinter Stats UI.
- `src/Tools/Plot_Generator/`: plot generation GUI, workers, and manifest helpers.
- `src/Tools/Ratio_Calculator/`: ratio calculator GUI, pipeline, exports, and plots.
- `src/Tools/Individual_Detectability/`: detectability tool core, GUI, and worker.

Stats grouping:

- Public entry point: `Tools.Stats.StatsWindow`; implementation lives in `ui.stats_window` and `ui.stats_main_window`.
- `ui/`: window mixins, dialogs, widget assembly, and small widgets.
- `controller/`: run coordination, pipeline state, and worker scheduling.
- `workers/`: Qt worker wrappers and GUI-agnostic statistical job execution.
- `data/`: project scans, manifests, subject IDs, and missing input detection.
- `analysis/`: DV policy facade and focused helpers, statistical engines, harmonics, and SNR/noise helpers.
- `qc/`: outlier, manual exclusion, QC exclusion, and QC report helpers.
- `reporting/`: plain-language summaries, workbook formatting, run reports, and logging.
- `reporting/summary/`: focused rule-based summary builders split by models, frame/file loading, ANOVA, posthoc, and mixed-model language. `reporting/summary_utils.py` is a compatibility facade only.
- `common/`: shared dataclasses, enums, constants, and lightweight window types.
- `io/`: Excel/dataframe I/O helpers. `stats_ready_export.py` owns the optional
  `Stats_Ready_Summed_BCA.xlsx` workbook builder/writer used for external
  JASP, R/RStudio, and SAS workflows.

Rules:

- Preserve statistical output schemas and plain-language reporting unless explicitly changing them.
- Keep GUI imports PySide6-only.
- Keep the public Stats entry point stable: `Tools.Stats.StatsWindow`.
- New active code should import from `Tools.Stats.<functional area>`, not removed `Tools.Stats.Legacy` or `Tools.Stats.PySide6` paths.
- New summary-reporting code should import from `Tools.Stats.reporting.summary`; keep `Tools.Stats.reporting.summary_utils` as a compatibility facade.
- Stats-ready exports must stay explicit and additive. Keep
  `Export Stats-Ready Workbook` as a distinct action, reuse the active Summed
  BCA DV facade, preserve group labels and `subject_uid`, and surface missing
  metadata or fallback policy instead of silently changing values.
- Add new analysis logic under the functional subpackage that owns it, and expose stable caller-facing surfaces through the package facade when needed.
- Run `python .agents/scripts/audit/agent_audit.py --check stats-structure` after Stats structural changes; it flags removed namespace usage and tkinter imports in active Stats code.
- Run `python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility` after Stats reporting changes; it flags oversized reporting modules and large function/class spans.
- Use focused tests around changed data transformations and exports.

Useful tests:

```powershell
python -m pytest tests/stats/pipeline/test_stats_pipeline_smoke.py tests/stats/gui/test_stats_layout_smoke.py -q
python -m pytest tests/stats/io/test_stats_ready_export.py -q
python -m pytest tests/stats/analysis/test_summary_utils_mixed_model.py tests/stats/analysis/test_summary_utils_posthoc_directions.py tests/stats/reporting/test_lmm_reporting_exports.py -q
python -m pytest tests/ratio_calculator/test_ratio_calculator_plots.py tests/plot_generator/test_plot_generator_gui.py -q
```
