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
  `analysis/prepared_analysis.py`: immutable run settings, named
  multiple-comparison families, participant-first complete-core auditing, and
  the prepared payload shared by every native worker.
- `analysis/multigroup_model.py` and `analysis/group_comparisons.py`: the
  native Group x Condition x ROI mixed model and the selected two-group
  Condition x ROI Welch contrasts.
- `analysis/robust_tests.py`, `analysis/resampling.py`, and
  `analysis/stability.py`: explicitly secondary trimmed/rank, max-|t|
  resampling, and leave-one-participant-out sensitivity engines.
- `analysis/canonical_harmonics.py`: thin shared API for resolving the
  saved processing-time FPVS Toolbox significant-harmonic list and readable
  fingerprint. Processing remains the only active project workflow allowed to
  calculate and persist that list. Scalp Maps and the default Individual
  Detectability workflow consume this API and fail clearly when the saved
  selection is missing or stale instead of recalculating it.
- `qc/`: outlier, manual exclusion, QC exclusion, and QC report helpers.
- `reporting/`: plain-language summaries, workbook formatting, run reports, and logging.
- The in-app Run log retains the complete workflow audit trail. Routine
  pipeline, worker, model, QC, and export messages are DEBUG-only in the IDE
  console; missing-file diagnostics, genuine warnings, and errors remain
  visible at the default application logging level.
- `reporting/inference/`: the mode-neutral native report bundle, including
  At a Glance, detailed methods/checks, the complete test inventory, named
  correction families, limitations, and additive source-result sheets.
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
- Native analysis mode is locked to the project manifest. A normal
  single-group project runs the single-group pipeline. A true multi-group
  project runs the multi-group pipeline with canonical manifest `group_id`
  values. Do not add an "ignore groups" or pooled-single-group shortcut to a
  multi-group project; a scientifically pooled analysis must be a separately
  defined single-group project.
- Both native modes freeze the QC/manual-eligible participant cohort before
  applying one explicit analysis scope. `complete_core` retains a requested
  condition only when every frozen participant has exactly one finite
  dependent value in every selected ROI. `available_case` retains finite
  observations from a condition only when every required fixed-effect
  Condition x ROI cell (and Group cell in multi-group mode) is structurally
  observed. Never drop participants silently to improve condition coverage,
  never impute missing responses, and always export frozen versus contributing
  participants, complete/partial/excluded conditions, participant coverage,
  model-cell coverage, and missing observations. Missing or non-finite Summed
  BCA cells are passed to this scope audit; they must not trigger a
  participant-wide DV exclusion before the audit.
- The complete-core single-group pipeline runs a Condition x ROI
  repeated-measures ANOVA, a sum-coded Condition x ROI `statsmodels` mixed
  model, gated/declared paired follow-ups, and one-sample
  response-versus-zero tests for each retained Condition x ROI cell. The
  available-case single-group pipeline uses the mixed model for factorial
  inference and intentionally omits RM-ANOVA and paired post-hoc steps. Its
  explicitly eligible canonical ML likelihood-ratio rows may enter the
  headline after the selected omnibus-family adjustment; coefficient-level
  Wald rows remain detailed-only. Main mixed-model estimates use REML and
  hierarchy-preserving omnibus comparisons refit nested models with ML on the
  same observed rows. The default response alternative is two-sided; allow
  "greater than zero" only as an explicitly chosen, prospectively justified
  direction.
- With strict interaction gating enabled, omnibus-triggered single-group
  follow-ups run only when the canonical RM-ANOVA Condition x ROI interaction
  is significant. The gate uses the same Greenhouse-Geisser-aware
  `p_reported` decision described below. Planned or manually requested
  exploratory follow-ups retain their declared provenance and multiplicity
  family rather than being relabelled as omnibus-triggered tests.
- Repeated-measures ANOVA must use the canonical `p_reported` decision. A
  two-level effect may use its uncorrected p-value. A higher-order effect may
  use an uncorrected p-value only when sphericity is known to hold; otherwise
  use the Greenhouse-Geisser p-value. If that correction is required but not
  available from the backend, retain the raw result for audit but block it from
  the primary interpretation.
- With the default strict omnibus-family option enabled, the canonical
  RM-ANOVA effect p-values form the `omnibus_effects_strict` family and use the
  selected multiplicity adjustment (Holm by default). Omnibus-triggered
  follow-ups must use the adjusted canonical interaction decision, not the raw
  or an uncorrected substitute. If strict control is disabled, the RM-ANOVA
  omnibus rows and manually requested follow-ups are exploratory/detailed; do
  not headline them as an unadjusted primary family.
- The native multi-group model is the sum-coded
  `Group x Condition x ROI` mixed model with participant as the random-effect
  grouping unit. The default is a random intercept. If a requested random-slope
  model is singular or does not converge, its explicit random-intercept
  fallback and reason must remain in diagnostics. Final coefficient estimates
  use REML; hierarchy-preserving full-versus-reduced omnibus comparisons use ML
  likelihood-ratio tests against an asymptotic chi-square reference. In
  available-case scope, every full/reduced comparison must use the identical
  finite observed row set.
- The multi-group omnibus result labelled "Any group-related effect" is a joint
  block test of every term containing Group; it is not a pure Group main-effect
  test. The Group x Condition x ROI, Group x Condition-related, and Group x
  ROI-related rows decompose that question with explicit nested formulas. Their
  asymptotic p-values are not Kenward-Roger or Satterthwaite results and must
  not be described as such.
- With the default strict omnibus-family option enabled, those four
  multi-group ML likelihood-ratio rows form the `omnibus_effects_strict`
  family and use the selected multiplicity adjustment (Holm by default).
  Primary omnibus interpretation uses the adjusted decisions. The direct
  group-cell family remains a separately adjusted analysis rather than being
  silently gated by those model tests. If the user disables strict
  omnibus-family control, "Any group-related effect" remains the sole primary
  omnibus question; the three decomposition rows are exploratory/detailed
  results and must not be presented as additional unadjusted primary tests.
- The direct "does either group differ in any Condition x ROI cell?" analysis
  uses two-sided Welch independent-samples t-tests, signed as selected
  `group_a - group_b`, with mean differences, 95% confidence intervals, and
  small-sample-corrected Hedges g. The default `group_core_cells` family applies
  one global Holm correction across every estimable retained cell.
  Benjamini-Hochberg is an explicitly exploratory FDR option. Available-case
  cell comparisons use the finite observations in that cell and report the
  resulting N for each group; Ns may vary across cells. When more than two
  canonical groups are present, the full omnibus model includes all groups but
  the user must choose the exact pair used for cell contrasts.
- The single-group response family is `response_core_cells`, and its default is
  one global Holm correction across retained Condition x ROI cells. Declared
  interaction follow-ups use their own named family. A correction label,
  family ID, family size, raw p-value, adjusted p-value, and decision must
  travel together into reporting; never relabel Holm as FDR or treat a
  within-slice adjustment as a global family. `omnibus_effects_strict` is a
  separate family from response, group-cell, and paired-follow-up tests.
- Shapiro-Wilk, finite-value, sample-size, variance, residual-tail,
  convergence, and singularity checks are diagnostics. They do not
  automatically choose or replace a primary test. A normality flag belongs in
  Methods & Checks and should be considered together with the prespecified
  robust/resampling sensitivities, not used as a data-driven test-selection
  switch.
- Available-case likelihood inference assumes missingness is ignorable/MAR
  after conditioning on modeled variables. Reports must state this assumption,
  the absence of imputation, and the risk that MNAR exclusions can bias
  estimates and p-values. The LMM's ability to fit partial repeated measures
  must never be described as proof that missingness is harmless.
- Trimmed-mean or rank tests, participant-level sign-flip/group-label max-|t|
  resampling, and leave-one-participant-out stability are sensitivity
  analyses. They must retain the `sensitivity` interpretation role and must
  never be promoted silently to the primary result because they agree with a
  preferred conclusion.
- Harmonic-selection provenance is part of the inference contract. A
  same-sample adaptive significant-harmonic list makes response-versus-zero
  p-values exploratory post-selection evidence. Selecting a "confirmatory"
  profile does not make that list independent. A fixed list is confirmatory
  only when its independent selection is explicitly attested and documented.
- The native report must keep three scientific questions separate: evidence of
  a response, within-subject Condition/ROI effects, and between-group effects.
  At a Glance uses only canonical/adjusted reportable p-values and says "did not
  provide evidence" for a nonsignificant test; it must never translate
  nonsignificance into equivalence or proof of no response. Detailed Methods
  and the workbook retain all estimates, intervals, effects, formulas,
  diagnostics, corrections, exclusions, frozen and contributing Ns,
  complete/partial/structurally excluded conditions, per-cell Ns, missingness
  caveats, coverage, provenance, and source frames.
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
| Vandenheever, Van der Donck, and Samaey used Bonferroni-adjusted planned/post-hoc contrasts; Vettori used fitted-model `emmeans` contrasts with Tukey adjustment. | The primary cross-cell families default to Holm; BH FDR is an exploratory option. | Holm controls family-wise error and is usually less conservative than simple Bonferroni, but it is not a numerical replication of Bonferroni or Tukey and does not define the same contrast family automatically. |
| FPVS work also uses repeated-measures ANOVA on summed harmonics with Greenhouse-Geisser correction and Holm correction across prespecified F tests, for example [Feuerriegel et al. (2018)](https://doi.org/10.1016/j.biopsycho.2018.09.002). | Single-group RM-ANOVA selects a Greenhouse-Geisser p-value when sphericity requires it and refuses to headline an unavailable required correction. | This is a close methods precedent, provided the reported effect, correction, and multiplicity family are retained. |
| Frequency-domain reporting guidance recommends a priori ROIs, correction when multiple ROIs are tested, and maximum-statistic permutation methods for joint high-dimensional inference ([Keil et al., 2022](https://doi.org/10.1111/psyp.14052)). | Named ROI x Condition families and participant-level max-|t| resampling are explicit. | Max-|t|, robust tests, and leave-one-out stability are supplementary sensitivity evidence here; they are not claimed to be the universal core analysis in published FPVS studies. |

The anxiety study by Vandenheever et al. fitted a separate ROI x Group model
for each facial expression in an adult sample aged 18--28. The Toolbox's
unified Group x Condition x ROI model is a deliberate generalization that tests
whether the group difference changes across conditions before examining the
global Holm-corrected cell family. It is not an exact reimplementation of the
paper's four models or Bonferroni family.

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
