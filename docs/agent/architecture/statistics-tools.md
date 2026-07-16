# Statistics And Tool Modules

Statistics and tool code is organized under one active Stats package. Old `PySide6` and `Legacy` Stats import namespaces have been removed.

Primary paths:

- `src/Tools/Stats/`: active single-group statistics GUI, controller, workers, analysis helpers, QC helpers, reporting, I/O, and shared helpers grouped by function. The root contains only package/docs files.
- `src/Tools/Stats/data/shared_rois.py` and `src/Tools/Stats/data/roi_resolver.py`: shared ROI helpers.
- Removed CustomTkinter Stats UI source is not part of the active tree; use Git history for reference if needed.
- `src/Tools/Plot_Generator/`: plot generation GUI, QThread launch workflow,
  `_Worker` QObject shell, worker config, Excel input/data collection helpers,
  ROI/group aggregation helpers, Matplotlib rendering,
  and manifest helpers.
- `src/Tools/Ratio_Calculator/`: ratio calculator GUI, pipeline, exports,
  and plots. `gui.py` keeps the public window facade while focused GUI mixins
  own condition selection, section assembly, ROI state, participant state,
  settings/validation, and run/status/log workflow.
- `src/Tools/Individual_Detectability/`: detectability tool core, GUI, and worker.
- `src/Tools/Sensitivity_Analysis/`: standalone manual sensitivity calculator
  for minimum detectable Cohen's dz, Cohen's f, or a simulation-based
  standardized contrast for the current random-intercept FPVS mixed model. It
  uses only values entered on its embedded page and remains outside project I/O
  and the Stats pipeline. Mixed-model simulation tests sum-coded condition,
  ROI, or interaction coefficient blocks with an omnibus Wald test and reports
  Monte Carlo, convergence, failure, and singular-fit diagnostics.
- `src/Tools/Publication_Maps/`: embedded Scalp Maps tool. Current scope is
  BCA, SNR, and z-score publication scalp maps. It must load the authoritative
  processing-time significant-harmonic selection from project metadata; it must
  not calculate or silently replace that list. It then aggregates exact selected
  metric columns per electrode before condition-level averaging and
  PNG/PDF/source-data export.
  Its GUI reads base frequency and BCA upper-limit values from Settings and
  exposes low/high BCA color selectors plus an optional fixed BCA colorbar
  range for rendered palette endpoints and scaling. Rendered labels use shared
  publication figure typography from `Main_App.exports.figure_style`, and the
  BCA colorbar label is
  `Baseline-corrected amplitude (µV)`.

Publication-ready table figures:

- Use `.agents/skills/publication-table-export/` for reusable table-only
  SVG/PNG generation that writes final assets under the active project root in
  `9 - Tables`.
- Use Great Tables for report-facing table layout when the output is intended
  for manuscripts, posters, or publication supplements. Keep the data frame
  small, explicit, and ordered in manuscript reading order; do not infer values
  from prose when source workbooks are available.
- Final table figures should be table-only assets by default. Do not embed a
  table number, title, caption, prose description, source note, or methods
  explanation in the PNG/SVG unless the user explicitly asks for those elements
  in the graphic. Put that text in the manuscript, Markdown/DOCX report, source
  workbook, audit JSON, or adjacent HTML preview instead.
- Match toolbox publication-table styling through the GUI-neutral
  `Main_App.exports.table_style` owner instead of importing GUI typography or
  GUI style tokens. Keep body/header roles, borders, surfaces, and text colors
  centralized there rather than adding exporter-local values.
- Export both vector SVG and high-resolution PNG for final publication tables.
  PNG exports should be 600 DPI unless the user requests a different target.
  SVGs should keep text as text, not rasterized screenshots, when the exporter
  can do so reliably.
- Keep publication table dimensions intentional. Use the 6.5-inch journal text
  width for broad tables; use a narrower explicit width for compact tables so
  columns do not look padded out. Verify final pixel dimensions, DPI metadata,
  and that no embedded caption/title text leaked into table-only exports.

Stats grouping:

- Public entry point: `Tools.Stats.StatsWindow`; implementation lives in `ui.stats_window` and `ui.stats_main_window`.
- `ui/`: window mixins, dialogs, widget assembly, and small widgets.
- `controller/`: run coordination, pipeline state, and worker scheduling.
- `workers/`: Qt worker wrappers and GUI-agnostic statistical job execution.
- `data/`: project scans, manifest lookup, project-root context, subject IDs, and missing input detection.
- `analysis/`: Summed BCA DV policy facade and helpers, statistical engines, and vectorized FullSNR/SNR/noise helpers.
- `analysis/canonical_harmonics.py`: thin shared API for resolving the
  saved processing-time FPVS Toolbox significant-harmonic list and readable
  fingerprint. Processing remains the only active project workflow allowed to
  calculate and persist that list. Scalp Maps and the default Individual
  Detectability workflow consume this API and fail clearly when the saved
  selection is missing or stale instead of recalculating it.
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
- `Main_App.processing.harmonic_selection_qc` owns the authoritative
  project-wide significant-harmonic calculation at processing completion and
  explicit Settings recalculation. The exact fingerprinted selection in
  `project.json` is the downstream source of truth. Active project consumers
  must load it; they must not derive a condition-, participant-, ROI-, or
  tool-specific replacement. A missing or stale cache is a user-actionable
  reprocess/recalculate error.
- Stats-ready exports must stay explicit and additive. Keep
  `Export Stats-Ready Workbook` as a distinct action, reuse the active Summed
  BCA DV facade, preserve `subject_id` and group labels, and surface missing
  metadata instead of silently changing values. Group-level significant
  harmonic summation is the default and primary DV policy. Fixed/predefined
  summation remains available as an alternate policy and also requires exact
  selected `BCA (uV)` harmonic columns; do not use nearest-column matching for
  requested fixed harmonics. The default group-level significant-harmonics
  policy detects significant non-base oddball harmonics from grand-averaged
  `FullFFT Amplitude (uV)` spectra over the union of predefined ROI electrodes.
  The default summation method then includes eligible non-base oddball harmonics
  up to the highest detected significant harmonic, subject to one locked
  isolated-highest guard. If more than 10 eligible non-base harmonics lie
  strictly between the two highest detected significant peaks, base-rate
  overlaps excluded from the count, the highest peak and all intervening
  harmonics above the next-highest peak are omitted from summation. Exactly 10
  remains allowed. The upper peak remains recorded as detected, and the guard
  is applied only to the original highest/next-highest pair rather than
  recursively. The resulting included harmonic list is applied uniformly to
  every participant, selected condition, and ROI.
  The oddball frequency is locked at 1.2 Hz. The BCA harmonic upper limit is
  only the stop frequency for candidate generation: build
  `1.2, 2.4, 3.6, ...` up to that ceiling, excluding base-rate overlaps. Never
  derive oddball spacing from the base frequency, the BCA upper limit, a stale
  settings payload, or a requested max frequency. This policy expects exact
  nominal oddball-harmonic columns generated by the locked FFT crop behavior in
  `docs/agent/architecture/fft-crop-method.md`; do not add a nearest-bin
  workaround in Stats for off-grid FullFFT workbooks.
- The group-level significant-harmonics selection math is locked. Build one
  grand-averaged raw amplitude spectrum from `FullFFT Amplitude (uV)` across
  selected participants and conditions after averaging each workbook across the
  union of predefined ROI electrodes. For each non-base candidate oddball
  harmonic, compute z from that grand-average spectrum as
  `(target_amplitude - noise_mean) / noise_std`, mark harmonics with
  `z > 1.64` as detected significant, and keep one included harmonic list for
  every participant, selected condition, and ROI. The
  neighboring-noise window is also locked: use +/-10 FFT bins around the target
  bin, exclude target-1, target, and target+1, require at least four finite
  noise bins, drop the single minimum and single maximum finite amplitude
  values when more than two finite values remain, then compute the noise mean
  and population SD (`ddof=0`) from the remaining values. Do not switch this
  step to workbook `Z Score` sheets, ROI-specific Z gating, SNR values,
  nearest-bin matching, inclusive `>= 1.64`, sample SD, or a different
  neighboring-bin rule unless the user explicitly requests a statistical-method
  change.
- The project harmonic-cache fingerprint must version the isolated-highest gap
  guard. A cache written by the earlier unguarded through-highest method must
  miss and require `Recalculate Harmonics` or normal post-processing before it
  can become the downstream source of truth. This recalculates harmonic
  selection from existing FullFFT workbooks; it does not require EEG
  preprocessing.
- Processing completion and explicit Settings recalculation must verify that
  the exact current fingerprint was persisted to `project.json` before
  reporting success. An in-memory selection alone is insufficient because
  downstream tools load the durable record. If manifest persistence fails,
  report a recalculation failure instead of allowing a later source-map cache
  error; an eligible in-memory hit may first repair the missing durable entry.
- Harmonic-cache identity includes the frequency-domain QC method, thresholds,
  and participant/electrode exclusions, but not
  `frequency_domain_qc.downstream_outputs_stale`. That field is workflow status
  toggled around downstream regeneration, not a scientific input. Cache lookup
  may accept an older entry that differs only by this retired status bit; every
  scientific setting and source-workbook fingerprint must still match exactly.
- Frequency-domain QC exclusions are applied before final harmonic selection,
  Summed BCA DV aggregation, Stats-ready export, SNR Plot ROI collection, Scalp
  Maps metric collection, and source-map input preparation. Full participant
  exclusions remove the participant project-wide from downstream
  frequency-domain outputs. Automatic participant-electrode exclusions remove
  that electrode for that participant across conditions; source-map preparation
  conservatively skips participants with automatic electrode-level exclusions
  because inverse payloads require complete topographies.
- The group-level significant-harmonics policy must fail fast from workbook
  headers when exact nominal oddball-harmonic columns are missing. Header
  preflight happens in the Stats worker before QC screening, grand-average
  amplitude row loading, and `BCA (uV)` aggregation, so an off-grid FullFFT
  workbook should not trigger expensive downstream sheet reads.
- After group-level harmonics are selected, the `BCA (uV)` sheet must also
  contain exact included harmonic columns such as `1.2000_Hz`. Do not use
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

Focused local verification:

```powershell
python .agents/scripts/verify.py --scope stats --tier focused
```

Run the affected tool scope as well when Stats changes cross into Publication
Maps, Ratio Calculator, or Plot Generator. Stats window/layout pytest-qt tests
are CI-only by default.
