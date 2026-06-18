# Statistics And Tool Modules

Statistics and tool code is organized under one active Stats package. Old `PySide6` and `Legacy` Stats import namespaces have been removed.

Primary paths:

- `src/Tools/Stats/`: active single-group statistics GUI, controller, workers, analysis helpers, QC helpers, reporting, I/O, and shared helpers grouped by function. The root contains only package/docs files.
- `src/Tools/Stats/data/shared_rois.py` and `src/Tools/Stats/data/roi_resolver.py`: shared ROI helpers.
- Removed CustomTkinter Stats UI source is not part of the active tree; use Git history for reference if needed.
- `src/Tools/Plot_Generator/`: plot generation GUI, QThread launch workflow,
  `_Worker` QObject shell, worker config, Excel input/data collection helpers,
  ROI/group aggregation helpers, scalp rendering helpers, Matplotlib rendering,
  and manifest helpers.
- `src/Tools/Ratio_Calculator/`: ratio calculator GUI, pipeline, exports,
  and plots. `gui.py` keeps the public window facade while focused GUI mixins
  own condition selection, section assembly, ROI state, participant state,
  settings/validation, and run/status/log workflow.
- `src/Tools/Individual_Detectability/`: detectability tool core, GUI, and worker.
- `src/Tools/Publication_Maps/`: embedded Scalp Maps tool. Current scope is
  BCA-only publication scalp maps. It calls the Stats group-significant harmonic
  selection builder so significant harmonics and cache reuse stay aligned with
  the locked Stats method, then sums exact selected `BCA (uV)` columns per
  electrode before condition-level averaging and PNG/PDF/source-data export.
  Its GUI reads base frequency and BCA upper-limit values from Settings and
  exposes low/high BCA color selectors plus an optional fixed BCA colorbar
  range for rendered palette endpoints and scaling. Rendered labels use shared
  component typography roles and the BCA colorbar label is
  `Baseline-corrected amplitude (µV)`.

- `src/Tools/Publication_Report/`: embedded single-group publication report
  workflow. It turns processed condition workbooks into Markdown, DOCX,
  `Publication_Report_Data.xlsx`, audit JSON, logs, and a figure manifest under
  `5 - Publication Report`. `runner.py` is GUI-agnostic, `gui.py` owns the
  manually-run sidebar page, `worker.py` wraps the runner for QThread use, and
  `analysis_tables.py` owns additive source tables that reuse the locked Stats
  group-significant harmonic selector. `statistical_tests.py` owns the
  Publication Report-specific Shapiro-Wilk, parametric/nonparametric selected
  test, and Holm/Bonferroni diagnostics exported in the manuscript-review
  sheets; do not move those helpers into Stats unless they become shared Stats
  behavior. The workbook includes semantic/color ratio outputs, planned ROI
  comparison decisions, lateralization diagnostics, participant-first
  individual-detectability tables, Z-score report tables, and base-rate
  summaries. Keep figure generation optional and independently skippable; the
  current implementation records figure requests in the manifest while
  automated figure export is deferred.

Stats grouping:

- Public entry point: `Tools.Stats.StatsWindow`; implementation lives in `ui.stats_window` and `ui.stats_main_window`.
- `ui/`: window mixins, dialogs, widget assembly, and small widgets.
- `controller/`: run coordination, pipeline state, and worker scheduling.
- `workers/`: Qt worker wrappers and GUI-agnostic statistical job execution.
- `data/`: project scans, manifest lookup, project-root context, subject IDs, and missing input detection.
- `analysis/`: Summed BCA DV policy facade and helpers, statistical engines, and vectorized FullSNR/SNR/noise helpers.
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
  BCA DV facade, preserve `subject_id` and group labels, and surface missing
  metadata instead of silently changing values. Group-level significant
  harmonic summation (Volfart/Retter/Rossion style) is the default and primary
  DV policy. Fixed/predefined summation remains available as an alternate
  policy and also requires exact selected `BCA (uV)` harmonic columns; do not
  use nearest-column matching for requested fixed harmonics. The default
  group-level significant-harmonics policy selects one common non-base oddball
  harmonic list from grand-averaged `FullFFT Amplitude (uV)` spectra, then
  applies that common list uniformly to every participant, selected condition,
  and ROI. The oddball frequency is locked at 1.2 Hz. The BCA harmonic upper
  limit is only the stop frequency for candidate generation: build
  `1.2, 2.4, 3.6, ...` up to that ceiling, excluding base-rate overlaps. Never
  derive oddball spacing from the base frequency, the BCA upper limit, a stale
  settings payload, or a requested max frequency. This policy expects exact
  nominal oddball-harmonic columns generated by the locked FFT crop behavior in
  `docs/agent/architecture/fft-crop-method.md`; do not add a nearest-bin
  workaround in Stats for off-grid FullFFT workbooks.
- The group-level significant-harmonics selection math is locked. Build one
  grand-averaged raw amplitude spectrum from `FullFFT Amplitude (uV)` across
  selected participants and conditions after averaging each workbook across
  all scalp electrodes. For each non-base candidate oddball harmonic, compute
  z from that grand-average spectrum as `(target_amplitude - noise_mean) /
  noise_std`, select only harmonics with `z > 1.64`, and keep the same
  selected list for every participant, selected condition, and ROI. The
  neighboring-noise window is also locked: use +/-10 FFT bins around the target
  bin, exclude target-1, target, and target+1, require at least four finite
  noise bins, drop the single minimum and single maximum finite amplitude
  values when more than two finite values remain, then compute the noise mean
  and population SD (`ddof=0`) from the remaining values. Do not switch this
  step to workbook `Z Score` sheets, ROI-specific Z gating, SNR values,
  nearest-bin matching, inclusive `>= 1.64`, sample SD, or a different
  neighboring-bin rule unless the user explicitly requests a statistical-method
  change.
- The group-level significant-harmonics policy must fail fast from workbook
  headers when exact nominal oddball-harmonic columns are missing. Header
  preflight happens in the Stats worker before QC screening, grand-average
  amplitude row loading, and `BCA (uV)` aggregation, so an off-grid FullFFT
  workbook should not trigger expensive downstream sheet reads.
- After group-level harmonics are selected, the `BCA (uV)` sheet must also
  contain exact selected harmonic columns such as `1.2000_Hz`. Do not use
  tolerance matching, nearest-column matching, or policy fallbacks for selected
  group harmonics; missing exact selected columns are hard failures.
- Stats folder scans may rebind the window to the manifest-owning project root
  only when the selected Excel folder belongs to that manifest-defined Excel
  subfolder. When rebinding, clear project-bound scan/results/export state so
  stale subjects, conditions, groups, and output paths do not survive.
- The built-in RM-ANOVA, mixed-model, post-hoc, and baseline-vs-zero pipeline
  is a single-group workflow. For projects whose manifest contains two or more
  configured `groups`, keep single-group analysis controls disabled and guard
  programmatic single-group runs. Multi-group projects should use
  `Export Stats-Ready Workbook` and analyze `group_id` as a between-subjects
  factor in external statistics software until a native multi-group Stats
  model is explicitly scoped.
- FullSNR helpers are vectorized for speed, but must preserve the legacy
  +/-10-bin noise window, immediate-neighbor exclusion, min-bin behavior, and
  zero-division handling exactly.
- Add new analysis logic under the functional subpackage that owns it, and expose stable caller-facing surfaces through the package facade when needed.
- Run `python .agents/scripts/audit/agent_audit.py --check stats-structure` after Stats structural changes; it flags removed namespace usage and tkinter imports in active Stats code.
- Run `python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility` after Stats reporting changes; it flags oversized reporting modules and large function/class spans.
- Use focused tests around changed data transformations and exports.

Useful tests:

```powershell
python -m pytest tests/stats/pipeline/test_stats_pipeline_smoke.py tests/stats/gui/test_stats_layout_smoke.py -q
python -m pytest tests/stats/analysis/test_full_snr_reference_equivalence.py tests/stats/data/test_stats_project_context.py -q
python -m pytest tests/stats/io/test_stats_ready_export.py -q
python -m pytest tests/publication_maps/test_bca_publication_maps.py -q
python -m pytest tests/publication_report/test_publication_report_runner.py -q
python -m pytest tests/stats/analysis/test_summary_utils_mixed_model.py tests/stats/analysis/test_summary_utils_posthoc_directions.py tests/stats/reporting/test_lmm_reporting_exports.py -q
python -m pytest tests/ratio_calculator/test_ratio_calculator_plots.py tests/plot_generator/test_plot_generator_gui.py -q
```
