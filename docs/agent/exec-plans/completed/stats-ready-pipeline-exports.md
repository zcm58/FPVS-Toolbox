# Stats-Ready Pipeline Exports

## Status

Completed 2026-05-20.

Implemented as an explicit, optional Stats tool export action. The new
workbook is additive and does not run automatically as part of Analyze Single
Group. CSV mirrors were intentionally deferred because the user asked for an
additional Excel workbook and the workbook already contains program-facing
sheets for JASP, R/RStudio, and SAS.

Implementation notes:

- Added `src/Tools/Stats/io/stats_ready_export.py` as the canonical workbook
  builder/writer.
- Reused `prepare_summed_bca_data(...)` with `provenance_map` and
  `dv_metadata`; Rossion and Fixed-K summation remain owned by the existing DV
  policy layer.
- Added a `StatsWorker` entry point,
  `Tools.Stats.workers.stats_workers.run_stats_ready_export(...)`, so the GUI
  action does not run the export on the UI thread.
- Added a distinct `Export Stats-Ready Workbook` button in the existing Stats
  Comparison Exports section.
- Wrote `Stats_Ready_Summed_BCA.xlsx` to the existing Stats results folder
  resolved through `ensure_results_dir(...)`.
- Included sheets: `RStudio_Long`, `SAS_Long`, `JASP_RM_ANOVA`,
  `JASP_Long_Mixed`, `Data_Dictionary`, and `Analysis_Recipes`.
- Group labels come from project participant metadata loaded by the existing
  project scan. If some selected subjects have group labels and others do not,
  the export raises an error instead of silently mixing labeled and unlabeled
  participants. If no group metadata is present, the export uses
  `single_group`.
- Added the non-expert MkDocs page
  `docs/user/statistics/external-statistics-software.md` and linked it in
  `mkdocs.yml`.

## Summary

Add an optional, additional analysis-ready Excel workbook and optional CSV
mirrors from the data processing pipeline for SAS, JASP, R/RStudio, and
similar statistical software. These files must be additive: existing
post-processing workbooks, sheet names, formulas, processing order, BDF
loading, preprocessing, BCA math, current Stats behavior, and the Stats tool's
Analyze Single Group workflow must remain unchanged.

The purpose is to make external statistical analysis easier as FPVS Toolbox
grows, not to keep expanding the built-in Stats tool for every possible future
model. The Toolbox-side responsibility is to export the already-derived
Summed BCA dependent variable and enough metadata to reproduce how it was
created. External tools remain responsible for their own RM-ANOVA, linear
mixed model, post-hoc, and multiple-comparison workflows.

## Goals

- Produce long-format exports that are easy to analyze in R/RStudio, SAS
  PROC MIXED, JASP mixed models, Python, or spreadsheet tools.
- Produce Summed BCA long-format exports with one row per subject, condition, and ROI.
- Support one-group and multi-group FPVS projects. Between-group analysis must
  be possible from the exported files without reshaping or manually recovering
  group membership.
- Produce Summed BCA wide-format exports with one row per subject and stable
  condition/ROI columns for JASP repeated-measures ANOVA and similar
  repeated-measures-cell workflows.
- Preserve the Rossion-method harmonic selection and BCA summing behavior by reusing the existing Stats/DV logic instead of reimplementing it in a separate export path.
- Include a data dictionary sheet or file that documents column names, units, source sheets, Rossion settings, selected harmonics, and empty/fallback behavior.
- Include analysis recipe metadata or a recipe sheet that shows the intended
  model families in each tool without claiming that external software output
  has already been run or verified.

## Definitions

- Summed BCA: the participant-level dependent variable produced by the active
  Stats DV policy. It is BCA summed across selected harmonics, then averaged
  across the electrodes in the selected ROI.
- Subject cell: one subject x condition x ROI value in the Summed BCA table.
- `group_id`: the between-subject experimental group label. Single-group
  projects may use a stable value such as `single_group`; multi-group projects
  must export the real group labels and must not silently collapse them.
- `subject_id`: the original participant label shown to users.
- `subject_uid`: a stable analysis key that is unique across the exported data.
  It should equal `subject_id` when labels are globally unique and should be a
  deterministic group-safe composite when participant labels can repeat across
  experimental groups.
- Long table: one row per subject cell. This is the canonical data shape for
  R/RStudio, SAS PROC MIXED, JASP mixed models, and CSV mirrors.
- Wide table: one row per subject, with one numeric column per condition x ROI
  subject cell. This is only required for JASP repeated-measures ANOVA and
  similar repeated-measures-cell GUIs.
- Canonical value: the value returned by
  `prepare_summed_bca_data(...)` for a subject x condition x ROI cell. All
  sheets that contain that cell must contain exactly the same numeric value.
- Fallback: any policy-driven outcome where Rossion selection yields no
  harmonics and the workflow falls back to Fixed-K, sets the DV to zero, or
  errors. Fallbacks must be explicit in metadata and never hidden.
- Source workbook: the existing per-subject post-processing workbook that
  supplied the `BCA (uV)` and Z-score data used by the Stats DV policy.

## Hard Constraints

- The export is additive only. Do not alter existing per-subject workbooks,
  post-processing sheets, current Stats output files, existing formulas,
  processing order, BDF loading, preprocessing, BCA math, or current GUI
  workflows unless the active implementation task explicitly changes them.
- The current Stats statistical-analysis workflows are the compatibility
  baseline. Analyze Single Group must run the same analyses, produce the same
  existing outputs, and use the same completion/error behavior when the new
  stats-ready export is disabled or not requested.
- Multi-group metadata is part of the export contract. If the project contains
  more than one experimental group, every data sheet must preserve `group_id`
  and `subject_uid`; no export path may drop group labels or merge subjects
  with the same label across groups.
- A failure to create the additional stats-ready workbook must not corrupt,
  rewrite, delete, or relabel any existing Stats output. If the workflow treats
  the new export as optional, export failure must be surfaced as an export
  failure without making the already-completed statistical analysis look
  invalid.
- Reuse the active Stats DV facade. Do not reimplement harmonic selection or
  BCA summation in the exporter.
- No silent fallbacks. Every empty-harmonic, missing-workbook, missing-ROI,
  all-NaN, policy fallback, or user-disabled output case must be explicit in
  either row metadata, the data dictionary, the UI/status message, or the
  raised error.
- Data sheets must stay machine-readable: header row first, no merged cells,
  no explanatory prose above the table, no formula-derived values, no hidden
  dependencies between sheets, and no styling-only semantics.
- Generated paths must come from the active project/export workflow. Do not
  add hard-coded absolute paths, home-directory assumptions, or current working
  directory assumptions.
- Keep program-specific tabs as views over the same canonical data. They may
  rename/reorder columns for import convenience, but they must not compute
  different values.
- External-tool support means import-ready data plus recipes. It does not mean
  running SAS, JASP, R, or RStudio from Toolbox.
- If implementation touches GUI controls or output location selection, follow
  the GUI non-blocking rules and document a visible/manual smoke path. Do not
  run offscreen Qt tests locally.

## Feasibility

This is feasible. The active Stats workflow already prepares the exact
dependent variable needed by external tools:

- `Tools.Stats.analysis.dv_policies.prepare_summed_bca_data(...)` is the
  public facade for the Summed BCA DV.
- The Rossion policy path computes group-level, ROI-specific harmonic sets,
  then applies those harmonics to each subject x condition x ROI cell.
- The Fixed-K policy path already sums the first K eligible oddball harmonics.
- The shared BCA aggregation helper sums BCA across selected harmonic columns
  per electrode, then averages the summed values across the user's selected
  ROI electrodes.

The future export must reuse this DV facade and its metadata/provenance hooks.
Do not call the older legacy `stats_analysis.aggregate_bca_sum(...)` path for
new exports unless the active DV facade intentionally routes there for a
legacy policy.

## Format Research Notes

- JASP can open Excel workbooks and CSV/TSV files. Its repeated-measures
  ANOVA workflow is easiest when each repeated-measures cell is a separate
  column that the user assigns to repeated-measures factors. Its linear mixed
  model workflow can use a long table with subject, condition, ROI, and DV
  columns.
- R/RStudio is best served by clean long data. `readxl::read_excel()` reads
  `.xlsx` sheets into data frames with the first row as column names by
  default, and `afex` explicitly expects long data for ANOVA. `lme4::lmer()`
  and related tools use a formula plus a data frame, so stable column names
  matter more than workbook styling.
- SAS can import Excel or delimited files, but its variable names and import
  behavior are stricter than R/JASP. SAS-friendly sheets should use short
  lowercase underscore column names, avoid spaces and punctuation in headers,
  keep headers on row 1, and keep data starting on row 2. A long table is the
  best default for PROC MIXED; wide tables remain useful for PROC GLM
  repeated-measures style workflows.
- FDR correction is available in external workflows, but each tool expresses
  it differently. R uses `p.adjust(..., method = "BH" or "fdr")`, SAS exposes
  FDR-controlling adjustments through PROC MULTTEST and related multiple
  comparison options, and JASP exposes post-hoc/multiple-comparison controls
  through its GUI. The export should therefore provide clean data and recipe
  guidance, not pre-compute tool-specific p-values.

## Planned Outputs

The future implementation should write a dedicated stats-ready export set
without modifying existing per-subject workbooks, post-processing workbooks,
or existing Stats analysis outputs.

Primary workbook:

- filename: `Stats_Ready_Summed_BCA.xlsx`
- output location: the current project results/export area chosen by the
  existing Stats or processing workflow.
- data sheets must be plain rectangular tables: one header row, one record per
  row, no merged cells, no formulas, no metadata rows above the header, and no
  styled-only meaning.

- Long-format data:
  - One row per subject, group, condition, ROI, metric, and harmonic or derived DV.
  - Stable fields for `subject_uid`, `subject_id`, `group_id`, condition, ROI, metric name, harmonic frequency, value, units, and source workbook.
- Summed BCA long-format data:
  - One row per subject x condition x ROI.
  - Fields for summed BCA value, selected harmonics, harmonic count, selection policy, units, and source workbook.
- Summed BCA wide-format data:
  - One row per subject, with stable condition/ROI columns suitable for JASP repeated-measures setup.
- Data dictionary:
  - Documents field names, value meanings, units, source sheets, selected-harmonic metadata, and Rossion-method settings.

Excel should be the primary user-facing format. CSV exports should also be
produced when practical because they are simple to import into RStudio, JASP,
SAS, Python, and other statistical tools.

## Resolved Decisions

- Trigger point: Stats tool only, through the explicit
  `Export Stats-Ready Workbook` action.
- Output location: existing Stats results folder resolved by
  `ensure_results_dir(...)`.
- CSV mirrors: deferred. The initial implementation produces the requested
  additional Excel workbook only.
- `JASP_Long_Mixed`: included because it removes ambiguity for JASP users who
  want mixed models rather than wide repeated-measures ANOVA.
- Group source: project participant metadata loaded during Stats project scan.
- Single-group label: `single_group` when no group metadata is available.

## Recommended Workbook Sheets

Three program-labeled tabs are feasible, but they are not strictly necessary:
R/RStudio, SAS PROC MIXED, and JASP mixed models can all analyze the same
canonical long table. The one shape that materially differs is JASP
repeated-measures ANOVA, which is easiest with wide repeated-measures columns.

Use program-facing sheets where they reduce user effort, but avoid divergent
math or duplicated hidden behavior:

1. `RStudio_Long`
   - Long-format canonical data for R/RStudio.
   - One row per subject x condition x ROI.
   - Required columns:
     `subject_uid`, `subject_id`, `group_id`, `condition`, `roi`,
     `summed_bca_uv`, `condition_order`, `roi_order`, `dv_policy`,
     `selected_harmonics_hz`, `harmonic_count`, `empty_harmonic_policy`,
     `fallback_used`, `source_workbook`.
   - Intended examples:
     `afex::aov_ez(id = "subject_uid", dv = "summed_bca_uv",
     within = c("condition", "roi"), between = "group_id", data = df)` for
     mixed within/between RM-ANOVA when groups are present;
     `lme4::lmer(summed_bca_uv ~ group_id * condition * roi +
     (1 | subject_uid), data = df)` or the closest model matching the current
     Stats contract for LMMs; `emmeans` plus `p.adjust(method = "BH")` or
     equivalent for follow-ups.

2. `SAS_Long`
   - Same logical records as `RStudio_Long`, but all headers must be
     SAS-friendly: lowercase, underscores only, 32 characters or fewer, and
     starting with a letter.
   - Keep categorical fields as text values and the DV as numeric.
   - Required columns:
     `subject_uid`, `subject_id`, `group_id`, `condition`, `roi`,
     `summed_bca_uv`, `condition_n`, `roi_n`, `dv_policy`, `harmonics_hz`,
     `harmonic_n`, `empty_policy`, `fallback_used`, `source_file`.
   - Intended examples:
     `proc mixed` with `class subject_uid group_id condition roi; model
     summed_bca_uv = group_id|condition|roi / ddfm=satterth; random intercept
     / subject=subject_uid;` and LS-means/post-hoc/FDR handling in SAS
     procedures chosen by the user.
   - If CSV mirrors are generated, use a SAS-specific CSV mirror only if
     missing-value representation or import behavior differs from the
     R/JASP mirror.

3. `JASP_RM_ANOVA`
   - Wide-format data for JASP's repeated-measures ANOVA GUI.
   - One row per `subject_uid`, with `subject_id` and `group_id` columns, then
     one numeric column per condition x ROI cell.
   - For multi-group projects, `group_id` is intended to be assigned as a
     between-subjects factor in JASP while the condition x ROI columns are
     assigned as repeated-measures cells.
   - Column names should be stable and human-readable but import-safe, for
     example `CondA__Occipital`, `CondB__Occipital`, `CondA__Frontal`.
   - The `Data_Dictionary` sheet must map each generated wide column back to
     original condition label, ROI label, selected harmonics, and source rows.
   - Missing subject/condition/ROI cells stay blank in Excel; do not write zero
     unless the selected DV policy explicitly produced zero.

4. `JASP_Long_Mixed`
   - Optional if `RStudio_Long` is already visible and clearly documented.
   - Include only if user testing shows that JASP users benefit from a
     separately named long sheet for mixed models.
   - If included, it must be a copy of the canonical long records with no
     different math and with `subject_uid`, `subject_id`, and `group_id`
     preserved.

5. `Data_Dictionary`
   - Documents every data column, units, factor role, expected data type,
     missing-value policy, original label mapping, source workbook/sheet, and
     selected harmonic metadata.
   - Includes the DV policy snapshot: policy name, fixed K, Rossion Z
     threshold, excluded harmonic/base-harmonic flags, empty-list policy,
     max BCA frequency, selected conditions, and selected ROI definitions.
   - Documents how `subject_uid` was constructed and the source of `group_id`.

6. `Analysis_Recipes`
   - Short, plain examples for SAS, JASP, and R/RStudio.
   - Recipes should describe intended setup, not guarantee external results.
   - Keep examples generic enough to survive condition/ROI count changes.
   - Include single-group and multi-group RM-ANOVA, LMM, post-hoc, and BH-FDR
     notes that mirror the current Stats tool's model families where practical.

## Rossion Method Requirement

Summed BCA must match the current Stats implementation exactly. The export path must reuse the existing Rossion harmonic-selection and DV helpers so that:

- statistically significant harmonics are selected using the same group-level Z-score rules,
- ROI-specific harmonic selections are preserved,
- excluded or empty harmonic cases follow the same policy as the Stats workflow,
- BCA summing across selected harmonics produces the same values as the current Stats reports.

Do not introduce a second independent implementation of harmonic selection or Summed BCA calculation.

The export must make fallback behavior explicit. If the selected Rossion policy
falls back to Fixed-K for an ROI, sets the DV to zero, or errors on an empty
harmonic set, the exported row-level metadata must say so. No silent fallback
is allowed.

## External Tool Support Scope

Support means "easy to import and analyze," not "FPVS Toolbox runs SAS/JASP/R
for the user." The implementation should provide:

- Clean data sheets for the most likely model families.
- Optional CSV mirrors for users who prefer script-based import.
- Analysis recipe text for RM-ANOVA, LMM, post-hoc tests, and BH-FDR
  correction.
- Enough metadata to verify that the exported DV matches the current Stats
  tool's Summed BCA policy.

The implementation should not:

- Recreate SAS, JASP, or R statistical engines inside the Toolbox.
- Export pre-computed external-tool p-values unless those analyses were
  actually run by Toolbox's existing Stats workflow.
- Claim exact cross-software equivalence for every model option; external
  tools differ in defaults, sums of squares, degrees of freedom, corrections,
  contrast coding, and missing-data handling.

## Iteration Plan

Future agents should work this plan in slices. Do not start with GUI controls
or broad pipeline wiring; prove the data builder first.

### Phase 0 - Baseline And Ownership

Scope:

- Read this plan, `docs/agent/agent-index.md`,
  `docs/agent/architecture/statistics-tools.md`, and
  `docs/agent/architecture/post-processing-export-contract.md`.
- Run the repo audits listed under verification before changing code.
- Identify the exact current Stats inputs for subjects, conditions,
  `subject_data`, ROIs, base frequency, DV policy, group labels, and output
  directory.
- Confirm whether an active execution plan supersedes this future plan.

Verify:

- `.venv1\Scripts\python.exe .agents/scripts/audit/agent_audit.py --check stats-structure`
- `.venv1\Scripts\python.exe .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py`
- Document the chosen project-root/output-location source in the implementation
  notes.

Stop condition:

- Do not edit runtime code until the output owner and trigger point are known.

### Phase 1 - Canonical Data Builder

Scope:

- Add a focused pure data-shaping module near Stats I/O/reporting.
- Call `prepare_summed_bca_data(...)` with `provenance_map` and `dv_metadata`.
- Produce an in-memory canonical long `DataFrame` with one row per
  subject x condition x ROI.
- Include `subject_uid`, `subject_id`, and `group_id` in every canonical row.
- Preserve `NaN` for missing/invalid cells unless the selected DV policy
  explicitly produced `0.0`.

Verify:

- Unit tests with fake DV data prove one canonical row per subject cell.
- Multigroup tests prove group labels are preserved and duplicate subject IDs
  in different groups receive distinct `subject_uid` values.
- Value tests compare exported `summed_bca_uv` to the active DV helper output.
- Provenance tests prove selected harmonics, source workbook, fallback state,
  and row/column labels are carried into metadata.

Stop condition:

- Do not add workbook writing until canonical values and metadata are pinned by
  tests.

### Phase 2 - Workbook And CSV Writer

Scope:

- Write `Stats_Ready_Summed_BCA.xlsx` with the approved sheet names.
- Generate `RStudio_Long`, `SAS_Long`, `JASP_RM_ANOVA`,
  `Data_Dictionary`, and `Analysis_Recipes`.
- Add CSV mirrors only if the open decision is resolved for the implementation
  slice.
- Keep all sheets rectangular and import-safe.

Verify:

- Schema tests lock sheet names, column names, and data types where practical.
- Wide-format tests prove JASP columns map back to canonical long rows.
- SAS header tests enforce <=32 characters, lowercase underscore names, and
  leading letters.
- Round-trip tests read the workbook back and compare row counts and values.

Stop condition:

- Do not wire the writer into GUI or processing flows until file contents are
  stable.

### Phase 3 - Workflow Integration

Scope:

- Add the smallest integration point selected in Phase 0.
- Keep the new export behind a distinct optional action, setting, or explicit
  workflow step. Do not silently insert it into Analyze Single Group in a way
  that changes the existing user's expected outputs, timing, completion
  classification, or error behavior.
- Surface success, skipped, and error states in the existing Stats/process
  status conventions.
- Ensure repeated export either overwrites intentionally, timestamps, or asks
  through the existing workflow pattern. Do not invent a silent overwrite rule.
- If GUI controls are added, keep them local to the existing Stats/export
  surface and avoid new pop-out workflows unless already established there.

Verify:

- Focused worker/controller tests prove the exporter receives the expected
  subjects, conditions, ROIs, group labels, DV policy, and output path.
- Regression tests or focused fakes prove Analyze Single Group still runs and
  finishes when the new export is disabled, skipped, or unavailable.
- Path tests prove output stays under the selected project/export location.
- GUI changes use non-GUI checks plus a documented visible/manual smoke path.

Stop condition:

- Do not declare complete if a failed export can look like a successful Stats
  run.

### Phase 4 - Documentation And Release Handoff

Scope:

- Update the nearest architecture or user-facing docs only if workflow,
  ownership, output location, or user-visible behavior changed.
- Add the dedicated MkDocs user page described in
  [User-Facing MkDocs Page Requirement](#user-facing-mkdocs-page-requirement).
- Move this plan to completed only after code, tests, docs, and verification
  are done.

Verify:

- Run the final verification commands in this plan.
- Record commands, results, residual risks, and any unresolved external-tool
  assumptions in the plan before moving it to completed.

Stop condition:

- Do not move the plan to completed while `JASP_Long_Mixed`, CSV mirrors, or
  group-label handling are unresolved unless those are explicitly documented as
  deferred follow-ups.

## Likely Ownership

The data-shaping and export implementation should live near the Stats I/O or reporting layer because that area already owns DV policy, long-format transformations, and statistical reporting semantics. The Main App processing pipeline should call it only as an optional additive export step after existing processing outputs are complete.

Likely implementation shape:

- Add a focused exporter under `src/Tools/Stats/io/` or
  `src/Tools/Stats/reporting/`, for example
  `stats_ready_export.py`.
- Feed it the same subject, condition, ROI, base-frequency, DV-policy, and
  subject-data inputs that current Stats workers pass to
  `prepare_summed_bca_data(...)`.
- Use `provenance_map` and `dv_metadata` to populate harmonic and source
  fields.
- Reuse existing workbook-formatting helpers only for column widths/freeze
  panes. Formatting must not alter data values or add non-tabular header
  content.

## Test Plan For Future Implementation

- Golden-data tests prove existing post-processing workbooks and current pipeline exports are unchanged.
- Schema tests lock `RStudio_Long`, `SAS_Long`, `JASP_RM_ANOVA`,
  `Data_Dictionary`, and `Analysis_Recipes` sheet names and column names.
- Value tests prove Summed BCA outputs match the existing Stats DV helpers.
- Multigroup schema/value tests prove `group_id` is present in all data sheets,
  `subject_uid` is unique, and between-group rows are not collapsed.
- Harmonic metadata tests prove selected harmonics match the Rossion-method selection rules.
- Empty or missing harmonic tests prove fallback behavior is explicit and documented.
- Wide-format tests prove each JASP repeated-measures column maps back to the
  correct condition x ROI rows and does not reorder values.
- SAS-safety tests prove exported SAS headers are <=32 characters, use only
  letters/numbers/underscores, and do not start with a digit.
- CSV mirror tests, if implemented, prove row counts and values match workbook
  sheets.
- MkDocs tests/build checks prove the dedicated non-expert user page is linked
  in `mkdocs.yml` and has no broken local links.
- Run the relevant Stats structure/reporting checks and `python .agents/scripts/audit/agent_audit.py`.

## Definition Of Done

- Existing post-processing workbook contracts remain unchanged.
- Existing Stats analyses continue to run without requiring the new workbook.
- Analyze Single Group behavior remains compatible: same required inputs, same
  existing analysis outputs, same result semantics, and no dependency on the
  stats-ready workbook.
- `Stats_Ready_Summed_BCA.xlsx` is produced only when explicitly requested by
  the chosen workflow or when the implementation task explicitly makes it part
  of that workflow.
- Every exported subject x condition x ROI value matches the active Stats DV
  helper for the same inputs.
- Multi-group exports include `group_id` and unique `subject_uid` values in
  every data sheet needed for backend analysis.
- Every program-specific data sheet is traceable back to the canonical long
  table.
- Rossion/Fixed-K settings, selected harmonics, fallback behavior, source
  workbook, and ROI definitions are exported or documented.
- Missing values are represented consistently and are not silently converted to
  zero.
- Output paths are project/export-location derived and pass path audit checks.
- Tests cover canonical values, schema, metadata, wide reshaping, SAS-safe
  headers, missing values, fallback policy, and repeated export behavior.
- MkDocs includes a dedicated non-expert page that explains how to use the
  stats-ready export in JASP, R/RStudio, and SAS for one-group and multi-group
  projects.
- Final handoff names the exact verification commands run and any skipped
  checks with reasons.

## Final Verification Commands

Use the narrowest commands that cover the touched slice, then broaden before
completion:

```powershell
.\.venv1\Scripts\python.exe .agents/scripts/audit/agent_audit.py --check stats-structure
.\.venv1\Scripts\python.exe .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility
.\.venv1\Scripts\python.exe .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
.\.venv1\Scripts\python.exe -m pytest tests\stats\analysis tests\stats\reporting -q
.\.venv1\Scripts\python.exe -m mkdocs build --strict
.\.venv1\Scripts\python.exe .agents/scripts/audit/agent_audit.py
ruff check .
```

For GUI changes, do not run offscreen Qt tests locally. Use py_compile, import
audits, focused non-GUI tests, and a documented visible/manual smoke path.

## Completed Verification

Commands run on 2026-05-20:

- `.venv1\Scripts\python.exe -m pytest tests/stats/io/test_stats_ready_export.py -q`
  - Passed: 3 tests.
- `.venv1\Scripts\python.exe -m pytest tests/stats/reporting tests/stats/io -q`
  - Passed: 17 tests.
- `.venv1\Scripts\python.exe -m py_compile src/Tools/Stats/io/stats_ready_export.py src/Tools/Stats/workers/stats_workers.py src/Tools/Stats/ui/stats_window_exports.py src/Tools/Stats/ui/stats_window_ui.py src/Tools/Stats/ui/stats_window_actions.py src/Tools/Stats/ui/stats_main_window.py src/Tools/Stats/ui/stats_window_pipeline.py src/Tools/Stats/ui/stats_window_support.py`
  - Passed.
- `.venv1\Scripts\python.exe .agents/scripts/audit/agent_audit.py --check stats-structure`
  - Passed.
- `.venv1\Scripts\python.exe .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility`
  - Passed.
- `.venv1\Scripts\python.exe .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`
  - Passed.
- `.venv1\Scripts\python.exe .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py`
  - Passed.
- `.venv1\Scripts\python.exe .agents/scripts/audit/agent_audit.py`
  - Passed.
- `.venv1\Scripts\python.exe -m mkdocs build --strict`
  - Passed. Material for MkDocs emitted its upstream MkDocs 2.0 warning; the
    docs build completed successfully.
- `.venv1\Scripts\ruff.exe check --ignore F401,F405 src/Tools/Stats/io/stats_ready_export.py src/Tools/Stats/workers/stats_workers.py src/Tools/Stats/ui/stats_window_exports.py src/Tools/Stats/ui/stats_window_ui.py src/Tools/Stats/ui/stats_window_actions.py src/Tools/Stats/ui/stats_main_window.py src/Tools/Stats/ui/stats_window_pipeline.py src/Tools/Stats/ui/stats_window_support.py tests/stats/io/test_stats_ready_export.py`
  - Passed.
- After adding the explicit overwrite log, reran
  `.venv1\Scripts\python.exe -m py_compile src/Tools/Stats/ui/stats_window_exports.py`
  and `.venv1\Scripts\ruff.exe check --ignore F401,F405 src/Tools/Stats/ui/stats_window_exports.py`.
  - Passed.

Skipped:

- Offscreen/pytest-qt GUI tests were not run because this repo's local Windows
  instructions prohibit offscreen Qt workflows. Manual visible smoke path:
  open the Statistics tool, scan a project Excel folder, confirm conditions
  and ROIs, click `Export Stats-Ready Workbook`, confirm the Last Export path
  points to `Stats_Ready_Summed_BCA.xlsx`, and open the workbook to verify the
  expected sheets.
- Full `ruff check .` without ignores was not used as the completion gate
  because existing Stats UI mixins intentionally use the shared
  `stats_window_support` star-import pattern, which produces repo-known F405
  findings unrelated to this implementation. The focused lint command above
  used the established `F401,F405` ignore for that pattern.

## User-Facing MkDocs Page Requirement

This feature must ship with a dedicated MkDocs user page for non-expert users.
The page should be written as a practical walkthrough, not as developer
architecture notes.

Required file:

- `docs/user/statistics/external-statistics-software.md`

Required nav placement in `mkdocs.yml`:

- Add the page under `Statistics Reference`, after `Mixed Model` or after
  `Post-hoc Tests`, with a clear title such as `External Statistics Software`.

Audience and tone:

- Assume the reader understands their FPVS experiment but is not an expert in
  SAS, JASP, R, RStudio, mixed models, or repeated-measures data formats.
- Explain what the Toolbox already computed: the exported dependent variable is
  Summed BCA, already summed across selected harmonics and averaged within ROI.
- Explain that users should analyze `summed_bca_uv`, not raw harmonic columns,
  unless they intentionally want a different analysis.
- Explain that `condition` and `roi` are within-subject factors and `group_id`
  is a between-subject factor when the project has multiple experimental
  groups.
- Explain why `subject_uid` should be used as the participant ID in external
  statistics software.

The page must include these sections:

1. `What This Export Is For`
   - State that `Stats_Ready_Summed_BCA.xlsx` is an additional export and does
     not replace existing Toolbox outputs.
   - State that the built-in Stats tool remains available.
   - List the available sheets and when to use each:
     `RStudio_Long`, `SAS_Long`, `JASP_RM_ANOVA`, optional
     `JASP_Long_Mixed`, `Data_Dictionary`, and `Analysis_Recipes`.

2. `Before You Start`
   - Tell users to confirm that the export was generated after selecting the
     correct subjects, conditions, ROIs, base frequency, harmonic policy, and
     group labels.
   - Tell users to open `Data_Dictionary` first and verify `group_id`,
     `subject_uid`, selected harmonics, and missing values.
   - Explain that blank/missing values should be reviewed rather than converted
     to zero.

3. `Which Sheet Should I Use?`
   - Use `JASP_RM_ANOVA` for JASP repeated-measures ANOVA.
   - Use `JASP_Long_Mixed` or `RStudio_Long` for JASP mixed models.
   - Use `RStudio_Long` for R/RStudio RM-ANOVA, LMMs, post-hoc tests, and
     scripted FDR correction.
   - Use `SAS_Long` for SAS PROC MIXED and SAS import workflows.
   - Note that long sheets are best for mixed models and between-group
     analyses; wide sheets are mainly for repeated-measures GUI assignment.

4. `JASP: Repeated-Measures ANOVA`
   - Steps:
     - Open JASP and load `Stats_Ready_Summed_BCA.xlsx`.
     - Select the `JASP_RM_ANOVA` sheet.
     - Confirm that `subject_uid` identifies rows and `group_id` is present
       for multi-group projects.
     - Open the repeated-measures ANOVA analysis.
     - Create repeated-measures factors for `condition` and `roi`.
     - Assign each condition x ROI column to the matching repeated-measures
       cell using the names documented in `Data_Dictionary`.
     - For multi-group projects, add `group_id` as a between-subjects factor.
     - Add the main effects and interactions needed by the study:
       `condition`, `roi`, `group_id`, and their interactions when groups are
       present.
     - Enable descriptive statistics, effect sizes, assumption checks, and
       post-hoc tests as needed.
     - Apply JASP's available multiple-comparison correction options for
       post-hoc families.
   - Include a short note that different JASP settings can produce results that
     do not exactly match Toolbox defaults.

5. `JASP: Mixed Models`
   - Steps:
     - Load the long-format sheet, preferably `JASP_Long_Mixed` if present or
       `RStudio_Long` if not.
     - Set `summed_bca_uv` as the dependent variable.
     - Add `condition`, `roi`, and `group_id` as factors when applicable.
     - Use `subject_uid` for the participant/random-effect structure.
     - Include `condition x roi` for one-group projects.
     - Include `group_id x condition x roi` when testing group differences.
     - Use post-hoc and correction options appropriate for the user's planned
       comparison family.

6. `R/RStudio`
   - Setup steps:
     - Install R and RStudio.
     - Install the required packages. Suggested packages:
       `readxl`, `dplyr`, `afex`, `lme4`, `lmerTest`, `emmeans`.
     - Read `RStudio_Long` from the workbook.
     - Convert `subject_uid`, `group_id`, `condition`, and `roi` to factors.
   - Include example starter code:

     ```r
     library(readxl)
     library(dplyr)
     library(afex)
     library(lme4)
     library(lmerTest)
     library(emmeans)

     df <- read_excel("Stats_Ready_Summed_BCA.xlsx", sheet = "RStudio_Long") |>
       mutate(
         subject_uid = factor(subject_uid),
         group_id = factor(group_id),
         condition = factor(condition),
         roi = factor(roi)
       )
     ```

   - Include a one-group RM-ANOVA example:

     ```r
     aov_one_group <- afex::aov_ez(
       id = "subject_uid",
       dv = "summed_bca_uv",
       within = c("condition", "roi"),
       data = df
     )
     ```

   - Include a multi-group RM-ANOVA example:

     ```r
     aov_multi_group <- afex::aov_ez(
       id = "subject_uid",
       dv = "summed_bca_uv",
       within = c("condition", "roi"),
       between = "group_id",
       data = df
     )
     ```

   - Include a multi-group LMM starter example:

     ```r
     lmm <- lmer(
       summed_bca_uv ~ group_id * condition * roi + (1 | subject_uid),
       data = df
     )

     emm <- emmeans(lmm, ~ condition | group_id * roi)
     pairs(emm, adjust = "BH")
     ```

   - Explain that users may need a different random-effects structure depending
     on design, sample size, and convergence.

7. `SAS`
   - Setup steps:
     - Save or copy `Stats_Ready_Summed_BCA.xlsx` to a path SAS can read.
     - Import `SAS_Long`.
     - Confirm the imported variables include `subject_uid`, `group_id`,
       `condition`, `roi`, and `summed_bca_uv`.
   - Include a PROC IMPORT starter example:

     ```sas
     proc import datafile="C:\path\to\Stats_Ready_Summed_BCA.xlsx"
         out=fpvs_long
         dbms=xlsx
         replace;
         sheet="SAS_Long";
         getnames=yes;
     run;
     ```

   - Include a one-group PROC MIXED starter example:

     ```sas
     proc mixed data=fpvs_long;
         class subject_uid condition roi;
         model summed_bca_uv = condition|roi / ddfm=satterth;
         random intercept / subject=subject_uid;
         lsmeans condition*roi / diff;
     run;
     ```

   - Include a multi-group PROC MIXED starter example:

     ```sas
     proc mixed data=fpvs_long;
         class subject_uid group_id condition roi;
         model summed_bca_uv = group_id|condition|roi / ddfm=satterth;
         random intercept / subject=subject_uid;
         lsmeans group_id*condition*roi / diff;
     run;
     ```

   - Tell users that FDR-adjusted post-hoc workflows in SAS depend on the
     chosen procedure and comparison family, so the page should point them to
     the `Analysis_Recipes` sheet and to their statistician or lab standard
     operating procedure for final correction choices.

8. `Common Mistakes`
   - Do not average rows again before analysis unless the study design calls
     for it.
   - Do not treat `condition` or `roi` as between-subject factors.
   - Do not use `subject_id` instead of `subject_uid` when participant labels
     can repeat across groups.
   - Do not replace blanks with zero unless the data dictionary says the DV
     policy intentionally produced zero.
   - Do not compare external-tool results to Toolbox results without matching
     model formula, contrast coding, post-hoc family, correction method,
     missing-data handling, and included participants.

9. `How To Report The Export`
   - Tell users to cite that values are Summed BCA in microvolts, selected by
     the configured DV policy.
   - Tell users to report whether Rossion or Fixed-K was used, the selected
     harmonics, ROI definitions, group labels, and missing-value policy.
   - Link to the Rossion harmonic selection page and methods reporting
     checklist.

Documentation verification:

- Run `.\.venv1\Scripts\python.exe -m mkdocs build --strict`.
- Check the new page through the local MkDocs nav.
- Confirm the page uses only `docs/user` relative links and does not link to
  agent-only docs.
- Confirm the page does not promise that external software will reproduce
  Toolbox results unless the model settings are matched.

## Assumptions

- This feature is not part of the active Main App refactor yet.
- Existing post-processing workbook contracts remain authoritative until this plan is explicitly activated.
- New exports are optional/additive and must not become a hidden dependency for current processing or Stats workflows.
- "RStudio support" means R-friendly data and recipes for use in RStudio; the
  actual import/modeling behavior belongs to R packages such as `readxl`,
  `afex`, `lme4`, and `emmeans`.
- Program-specific tabs are a user-facing convenience. They must not contain
  different Summed BCA values for the same subject x condition x ROI cell.
