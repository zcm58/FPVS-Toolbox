# Statistics And Tool Modules

Statistics and tool code is organized under one active Stats package. Old `PySide6` and `Legacy` Stats import namespaces have been removed.

Primary paths:

- `src/Tools/Stats/`: active single- and multi-group statistics GUI, controller,
  workers, analysis helpers, QC helpers, reporting, I/O, and shared helpers
  grouped by function. The root contains only package/docs files.
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
- `controller/`: run coordination, mode-specific pipeline state, cancellation,
  and worker scheduling.
- `workers/`: Qt worker wrappers and GUI-agnostic statistical job execution.
  `multigroup_workers.py` owns the prepared-data worker boundary used by both
  native modes despite its historical filename.
- `data/`: Stats-facing project scan adapters, project-root context, subject
  IDs, and missing input detection. Processed-workbook discovery, manifest
  group identity, and participant/group matching are owned by
  `Main_App.projects.dataset_index`; `stats_data_loader` preserves legacy
  return shapes only.
- `analysis/`: Summed BCA DV policy facade and helpers, statistical engines, and vectorized FullSNR/SNR/noise helpers.
- `analysis/inference_contracts.py`, `analysis/design_audit.py`, and
  `analysis/prepared_analysis.py`: locked Standard FPVS Screening settings,
  fixed named Holm families, participant-first available-observation auditing,
  and the prepared payload shared by every native worker.
- `analysis/mixed_effects_model.py`, `analysis/multigroup_model.py`, and
  `analysis/lmm_contrasts.py`: the primary Condition x ROI and exactly-two-group
  Group x Condition x ROI random-intercept LMMs, hierarchy-preserving omnibus
  block tests, and fitted-model asymptotic Wald contrasts.
- `analysis/anova_compatibility.py` and `analysis/repeated_m_anova.py`:
  automatic, nonfatal, secondary exact-balance ANOVA compatibility.
- `analysis/robust_tests.py` and `analysis/stability.py`: optional secondary
  trimmed/rank and leave-one-participant-out sensitivity engines.
- `analysis/posthoc_tests.py`, `analysis/group_comparisons.py`, and
  `analysis/resampling.py`: legacy compatibility surfaces. Paired post-hocs,
  standalone Welch cell tests, and complete-matrix max-|t| are not primary
  Standard FPVS Screening routes.
- `analysis/canonical_harmonics.py`: thin shared API for resolving the
  saved processing-time FPVS Toolbox significant-harmonic list and readable
  fingerprint. Processing remains the only active project workflow allowed to
  calculate and persist that list. Scalp Maps and the default Individual
  Detectability workflow consume this API and fail clearly when the saved
  selection is missing or stale instead of recalculating it.
- `qc/`: outlier, manual exclusion, QC exclusion, and QC report helpers.
  QC screening keeps the shared dataset-index subject/condition mapping as its
  file source. For `.xlsx` workbooks it reads only the `BCA (uV)` harmonic
  columns and union of ROI electrodes through the selected-column reader, then
  vectorizes the per-ROI harmonic means. Non-`.xlsx` inputs retain the
  serialized full-reader fallback. Missing mappings/files, QC thresholds, and
  exclusion/reporting semantics are unchanged.
- `reporting/`: plain-language summaries, workbook formatting, run reports, and logging.
- The in-app Run log retains the complete workflow audit trail. Routine
  pipeline, worker, model, QC, and export messages are DEBUG-only in the IDE
  console; missing-file diagnostics, genuine warnings, and errors remain
  visible at the default application logging level.
- `reporting/inference/`: the mode-neutral native report bundle, including
  At a Glance, detailed methods/checks, the complete test inventory, named
  correction families, limitations, and additive source-result sheets.
- `reporting/summary/`: focused rule-based summary builders split by models,
  frame/file loading, ANOVA compatibility, legacy post-hoc language, and
  mixed-model language. `reporting/summary_utils.py` is a compatibility facade
  only.
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
- The Stats page may link users to
  `Settings > Preprocessing > Harmonic Selection`, but it must not clear the
  saved selection, claim that the next Stats run will recalculate it, or start
  a second recalculation workflow. FFT-grid review, background calculation,
  persistence verification, and success/failure feedback remain owned by the
  canonical Settings workflow.
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
  participant/electrode exclusions, and the normalized
  participant-condition exclusion cohort, but not
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
- Managed project participant-condition exclusions are applied by the shared
  dataset index before that header preflight, so an explicitly excluded
  workbook cannot block harmonic selection while its file remains on disk for
  audit. The Settings review reads only FullFFT headers, identifies each grid
  by the exact 1.2-Hz bin index (the integer oddball-cycle count), and flags
  shorter or longer grids that differ from a unique strict project majority.
  Its reference uses the same completed, frequency-domain-active participant
  cohort as harmonic selection. If valid grids tie, it presents every cohort
  without guessing and does not start recalculation until the proposed included
  workbooks share one valid grid. It does not change Stats' exact-column or
  neighboring-noise rules.
- After group-level harmonics are selected, the `BCA (uV)` sheet must also
  contain exact included harmonic columns such as `1.2000_Hz`. Do not use
  tolerance matching, nearest-column matching, or policy fallbacks for selected
  group harmonics; missing exact selected columns are hard failures.
- Stats folder scans consume the shared project dataset index and may rebind
  the window to the manifest-owning project root
  only when the selected Excel folder belongs to that manifest-defined Excel
  subfolder. When rebinding, clear project-bound scan/results/export state so
  stale subjects, conditions, groups, and output paths do not survive.
- Standard FPVS Screening is a locked first-round workflow, not a general
  statistical model builder and not a substitute for a study-specific final
  analysis. Covariates, random slopes, longitudinal or nested structure, more
  than two groups, and other confirmatory questions require a planned custom
  model.
- Analysis mode is manifest-owned. A normal single-group project uses the
  single pipeline. Standard multi-group screening requires exactly two
  canonical manifest `group_id` values. Do not add an "ignore groups" or
  pair-selection shortcut; a pooled analysis requires a separately defined
  single-group project.
- Both modes freeze the QC/manual-eligible cohort, then retain every finite
  selected Summed BCA observation without imputation, provided every required
  fixed-effect cell is structurally observed. Never drop a participant to
  improve condition coverage. Export frozen and contributing participants,
  complete/partial/structurally excluded conditions, participant and model-cell
  coverage, per-cell Ns, and missing observations.
- The primary models use sum coding and a participant random intercept:
  single-group `Condition x ROI`; exactly-two-group
  `Group x Condition x ROI`. Final coefficient estimates use REML.
  Hierarchy-preserving full-versus-reduced omnibus comparisons refit under ML
  on the identical finite row set and use the asymptotic chi-square reference.
  These are not Kenward-Roger or Satterthwaite F tests.
- Positive-response screening is prespecified one-sided `greater than zero`.
  The single `response_core_cells` family spans retained Condition x ROI cells.
  Multi-group `group_response_cells` spans Group x Condition x ROI cells.
  Factorial and fitted-model contrast questions remain two-sided.
- Standard screening fixes Holm family-wise correction for the named
  `response_core_cells`, `group_response_cells`, `group_core_cells`,
  `planned_contrasts`, `omnibus_effects_strict`, and
  `anova_compatibility_effects` families. Family ID, label, size, raw p-value,
  adjusted p-value, and decision must travel together into reporting.
- There is no user-selectable analysis profile, missing-data scope, response
  direction, correction method, or strict-omnibus toggle. Compatibility
  widgets may remain hidden for API stability but cannot alter worker or report
  configuration.
- In single-group screening, the Holm-corrected LMM Condition x ROI interaction
  controls whether automatic interaction explanation is reported. Condition
  differences within ROI and ROI differences within Condition come from the
  accepted fitted LMM and must be labelled
  `LMM-derived model-estimated contrast` with asymptotic Wald inference.
  Legacy paired-t post-hocs do not control or replace this explanation.
- The exactly-two-group LMM retains the four accurately labelled
  hierarchy-preserving group-related ML likelihood-ratio block tests. "Any
  group-related effect" is a joint block test of every Group-containing term,
  not a pure Group main effect. Its decomposition rows must retain their actual
  nested formulas.
- Prespecified Group A minus Group B contrasts run from the accepted fitted LMM
  in every estimable Condition x ROI cell, even when the broader group-pattern
  family is nonsignificant. They are signed `group_a - group_b`, two-sided,
  report estimates, SEs, intervals, Wald statistics, coverage, and varying cell
  Ns, and use one global `group_core_cells` Holm family. Never infer a group
  difference by comparing within-group response significance.
- ANOVA is automatic, nonfatal, secondary compatibility evidence only. The
  single check requires one finite, unique observation in every declared
  participant x Condition x ROI cell and retains canonical
  Greenhouse-Geisser/sphericity-aware `p_reported` handling. The multi check
  additionally requires equal group sizes and uses a combined
  `response_cell = Condition x ROI` within factor. It is a broad
  `Group x response-cell` compatibility check, not a decomposition of separate
  Group x Condition x ROI components. ANOVA never gates, validates, replaces,
  or enters the primary LMM conclusion.
- Shapiro-Wilk, finite-value, sample-size, variance, residual-tail,
  convergence, and singularity checks are diagnostics. They do not select or
  replace the primary model. Robust and leave-one-participant-out results are
  optional secondary sensitivities and must not be promoted to a primary
  conclusion.
- Available-observation likelihood inference assumes ignorable/MAR missingness
  after conditioning on modeled variables. Reports must state the assumption,
  absence of imputation, and risk that MNAR exclusions can bias estimates and
  p-values. Partial repeated measures do not prove missingness is harmless.
- The participant-level sign-flip/group-label max-|t| implementation requires a
  complete participant-by-cell matrix. It is unavailable in the locked
  available-observation screening route. `analysis/resampling.py` remains a
  compatibility/test surface, not a queued optional method.
- `analysis/posthoc_tests.py` and `analysis/group_comparisons.py` likewise
  preserve legacy paired-test and Welch APIs for compatibility or detailed
  historical exports. New primary work must use `analysis/lmm_contrasts.py`.
- Harmonic-selection provenance remains part of the inference contract. A
  same-sample adaptive significant-harmonic list makes positive-response
  p-values exploratory post-selection evidence. A fixed list is treated as
  independently selected only when its provenance is explicitly attested and
  documented; there is no profile control that can change this fact.
- At a Glance keeps positive-response evidence, Condition/ROI pattern,
  supported interaction explanation, direct two-group cell differences, and
  broader group pattern separate. It uses canonical Holm-adjusted reportable
  decisions without printing a dense p-value inventory and never translates
  nonsignificance into equivalence, absence, causality, or model validation.
  Keep it short, omit inapplicable questions, name at most two positive primary
  examples, and show only concise coverage plus the workbook filename.
  Sensitivity inventories and any sensitivity disagreement remain
  detailed-workbook evidence rather than At a Glance content. Detailed Methods
  and source sheets retain estimates, intervals, effects, formulas,
  diagnostics, corrections, exclusions, frozen/contributing Ns, per-cell Ns,
  missingness, coverage, provenance, sensitivities, and source frames.
- FullSNR helpers are vectorized for speed, but must preserve the legacy
  +/-10-bin noise window, immediate-neighbor exclusion, min-bin behavior, and
  zero-division handling exactly.
- Add new analysis logic under the functional subpackage that owns it, and expose stable caller-facing surfaces through the package facade when needed.
- Run `python .agents/scripts/audit/agent_audit.py --check stats-structure` after Stats structural changes; it flags removed namespace usage and tkinter imports in active Stats code.
- Run `python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility` after Stats reporting changes; it flags oversized reporting modules and large function/class spans.
- Use focused tests around changed data transformations and exports.

## Relationship To Published FPVS Statistics

The native methods are grounded in published FPVS practice, but "grounded in"
does not mean numerically identical to every paper:

| Published precedent | Toolbox implementation | Required interpretation |
| --- | --- | --- |
| Summed baseline-corrected amplitude as the dependent variable, with Condition/Expression and ROI as within-subject factors, Group as a between-subject factor, and a participant random intercept appears in [Vandenheever et al. (2025)](https://doi.org/10.1016/j.ijpsycho.2025.113212), [Van der Donck et al. (2020)](https://doi.org/10.1111/jcpp.13201), [Vettori et al. (2020)](https://doi.org/10.3389/fpsyt.2020.00332), and [Samaey et al. (2024)](https://doi.org/10.1186/s12916-024-03610-w). | Single-group Condition x ROI and multi-group Group x Condition x ROI mixed models use Summed BCA and participant grouping. | The dependent variable and factorial mixed-model structure have direct FPVS precedent. |
| Several cited R/lmer analyses report omnibus F tests and contrasts with Kenward-Roger denominator degrees of freedom; Van der Donck and Samaey used REML-based models, and Samaey also used selected random slopes. | `statsmodels` provides final REML estimates, while the Toolbox refits explicit nested models under ML and uses asymptotic chi-square likelihood-ratio tests. | Toolbox LRT p-values are not F tests using Kenward-Roger or Satterthwaite denominator-degree-of-freedom approximations and may differ materially, especially in small samples. Report the backend and test exactly. |
| Vandenheever, Van der Donck, and Samaey used Bonferroni-adjusted planned/post-hoc contrasts; Vettori used fitted-model `emmeans` contrasts with Tukey adjustment. | Standard screening fixes Holm family-wise correction for each named family. Explanatory and direct group-cell contrasts are model-estimated from the accepted LMM and use two-sided asymptotic Wald inference. | Holm is a defensible family-wise correction and is usually less conservative than simple Bonferroni, but neither its family definitions nor the Toolbox's asymptotic Wald contrasts numerically replicate Bonferroni-, Tukey-, `emmeans`-, or Kenward-Roger-based results. |
| FPVS work also uses repeated-measures ANOVA on summed harmonics with Greenhouse-Geisser correction and Holm correction across prespecified F tests, for example [Feuerriegel et al. (2018)](https://doi.org/10.1016/j.biopsycho.2018.09.002). | ANOVA runs only as automatic secondary compatibility evidence for an exact complete matrix; multi-group compatibility additionally requires equal group sizes. The canonical Greenhouse-Geisser-aware `p_reported` and fixed Holm family are retained when it runs. | This preserves a published-method comparison for balanced designs, but ANOVA never validates, gates, replaces, or enters the primary available-observation LMM conclusion. |
| Frequency-domain reporting guidance recommends a priori ROIs, correction when multiple ROIs are tested, and maximum-statistic permutation methods for joint high-dimensional inference ([Keil et al., 2022](https://doi.org/10.1111/psyp.14052)). | The standard route uses prespecified ROI x Condition questions and fixed named Holm families. Robust and leave-one-participant-out checks are optional detailed-workbook sensitivities; participant-level max-|t| is unavailable because the current implementation requires a complete participant-by-cell matrix. | Maximum-statistic methods remain relevant published guidance for suitable complete designs, but the legacy resampling module is not a queued Standard FPVS Screening method and no incomplete-data claim is made for it. |

The anxiety study by Vandenheever et al. fitted a separate ROI x Group model
for each facial expression in an adult sample aged 18--28. The Toolbox's
unified Group x Condition x ROI model is a deliberate generalization. It
reports hierarchy-preserving group-pattern blocks separately and always runs
the prespecified fitted-LMM Group A minus Group B contrast in every estimable
Condition x ROI cell, with one global Holm family; those direct cells are not
gated by a broader interaction. It is not an exact reimplementation of the
paper's four models, Bonferroni family, or inferential backend.

For a sample aged 13--15 years, Samaey et al.'s 12--16-year-old cohort provides
an age-relevant FPVS precedent, not a validation of this sample's group
conclusions. That study had 120 adolescents, included age and gender
covariates, considered random slopes, and used a different exposure definition.
The current covariate-unadjusted group model therefore estimates an association
within the analyzed sample. It does not establish anxiety as a cause, a
developmental mechanism, a diagnosis, or generalizability to other
adolescents. If age, gender, medication, depression, recruitment site, or
another covariate belongs to the scientific question, use a prespecified
covariate model in validated external software until that model is implemented
natively.

Focused local verification:

```powershell
python .agents/scripts/verify.py --scope stats --tier focused
```

Run the affected tool scope as well when Stats changes cross into Publication
Maps, Ratio Calculator, or Plot Generator. Stats window/layout pytest-qt tests
are CI-only by default.
