# Publication Report Workflow

## Status

Active implementation.

Implemented in `codex/publication-report-workflow` initial slice:

- `src/Tools/Publication_Report/` package with typed request/result models,
  project/workbook discovery, a GUI-agnostic report runner, source workbook and
  audit writers, Markdown and dependency-free DOCX narrative writers, a Qt
  worker, and an embedded PySide6 page.
- Main sidebar entry: `Publication Report`, manually run after processing.
- Multiple selected condition folders, editable report/target labels, editable
  LOT/ROT/Central/base-rate ROI electrode lists, Markdown/Excel/DOCX outputs, and
  default figure-family options recorded in the manifest.
- Initial audit/inclusion workflow that mirrors active Stats manual exclusions
  and required non-finite exclusions when an embedded Stats page has that state;
  headless requests can pass the same exclusion sets directly.
- Additive source tables for Stats-selected harmonic selection, ROI harmonic
  values/summaries, summed-BCA baseline-vs-zero summaries, existing Stats
  RM-ANOVA and exploratory posthoc source outputs, direct condition-pair comparisons within
  ROI, comparison agreement, participant-first individual
  detectability/electrode counts, electrode-level summed-harmonic Z scores,
  manuscript-facing Z-score inventories, semantic/color ratio summaries,
  planned ROI test diagnostics, Holm-corrected manuscript comparison decisions,
  lateralization contrasts, and base-rate summaries.
- Focused headless tests for generated Markdown, DOCX, workbook, audit JSON,
  missing selected conditions, and single-group enforcement.

Initial scope decisions captured from user discussion:

- v1 supports multiple selected conditions in one report.
- The user selects which processed conditions are included.
- The semantic-categories use case is a user-editable report label, not a
  hard-coded named preset.
- LOT, ROT, and Central are built-in report ROI options for the first semantic
  report workflow. The embedded report page reads the Settings-menu ROI list so
  project-specific ROIs remain selectable.
- LOT electrodes default to `P7, P9, PO7, PO3, O1`.
- ROT electrodes default to `P8, P10, PO8, PO4, O2`.
- Central electrodes default to `FCz, Cz, CPz, CP1, C1, FC1`.
- LOT and ROT are selected as primary ROIs by default. Central is selected as
  a supporting/exploratory ROI by default.
- The default base-rate ROI is bilateral occipito-temporal.
- Bilateral occipito-temporal electrodes default to
  `P7, P9, PO7, PO3, O1, P8, P10, PO8, PO4, O2`.
- LOT, ROT, and Central are reported separately by default; LOT+Central is not
  a built-in v1 ROI.
- When Stats supports within-subject condition comparisons for selected
  conditions, include those comparisons in the draft report.
- Condition comparisons should include both the supported RM-ANOVA/post-hoc
  workflow and separate condition-pair comparisons within each ROI, then report
  whether the two approaches agree.
- The report mirrors active Stats manual and QC exclusions for analyzed
  participant sets and surfaces those inclusions/exclusions clearly to the
  user.
- Baseline-vs-zero tests are included by default for each selected
  condition x ROI.
- Base-rate reporting summarizes amplitude, SNR, and Z score.
- Base-rate harmonics use the same BCA upper limit used by the project/report.
- Base-rate detectability is reported as a group-level QC statement, with
  source data retained in the workbook rather than narrative participant-level
  base-rate significance language.
- Default Z thresholds are 1.64, 2.32, and 3.1, with corresponding one-tailed
  positive-direction p-values reported.
- Spectra, scalp maps, and individual detectability figure families are checked
  by default in the GUI, but the current implementation records those requests
  in `Figure_Manifest` and warnings while automated figure export remains a
  future slice.
- The narrative uses APA-style manuscript formatting from v1.
- Individual-level detectability uses the Stats-selected group harmonic list.
- Individual-level significance defaults to BH-FDR enabled.
- Significant-electrode summaries should use participant-first electrode
  significance, then summarize or average Z values afterward.
- v1 includes Markdown, Excel, and Word `.docx` outputs.
- Publication Report is an embedded manually-run tool after processing is
  complete, not an automatic post-processing step.
- The embedded Publication Report tool lives in the main sidebar.

## Goal

Build a modular embedded workflow that turns a processed single-group FPVS
project into publication-oriented outputs after the user selects report options
and runs the tool:

- a readable Results information pack for manuscript drafting;
- a source-data workbook containing every reported value;
- manifest entries for requested ROI spectra, scalp-map, and optional
  individual-level figure families, with automated figure export still deferred;
- optional individual-level detectability figures;
- an audit trail that records settings, included participants, exclusions,
  harmonic policy, thresholds, and source workbooks.

The first target use case is a semantic-categories condition with a 1.2 Hz
oddball response and a 6 Hz base-rate response, but the implementation should
remain condition-label agnostic and reusable for other single-group projects.

## Non-Goals

- Do not change the locked preprocessing order or FFT crop contract.
- Do not change the locked 1.2 Hz oddball harmonic-selection policy.
- Do not add native multi-group inferential reporting in this plan.
- Do not replace the existing Stats, Scalp Maps, Plot Generator, or Individual
  Detectability tools.
- Do not make GUI execution depend on offscreen Qt tests.

## Current Assumptions

- The project has already produced per-participant condition workbooks under
  the project Excel root, usually `1 - Excel Data Files`.
- The active oddball response is 1.2 Hz, read from the locked Toolbox settings
  and code paths.
- The active base rate is read from project settings, usually 6 Hz.
- The default dependent variable remains Summed BCA from the Stats
  group-level significant-harmonics policy.
- The report workflow is single-group only. If project metadata contains more
  than one configured group, the workflow should stop with a clear message.
- The report mirrors the active Stats participant set after manual exclusions
  and QC exclusions. The audit workbook should list included participants,
  manually excluded participants, QC-excluded participants, and the reason or
  source for each exclusion.
- Condition roles, report labels, ROI choices, thresholds, and optional
  exploratory sections should be project-level configuration, not hard-coded
  into the report engine.

## Current Package Layout

Active package:

`src/Tools/Publication_Report/`

Implemented modules:

- `models.py`: typed request/result contracts, output options, ROI defaults,
  output folder and artifact names, and workbook sheet-name constants.
- `discovery.py`: project-root and Excel-folder discovery, participant/workbook
  matching, selected condition validation, single-group guard, and exclusion
  handling.
- `analysis_tables.py`: additive source tables for harmonic selection, ROI
  harmonic values/summaries, response summaries, Stats comparison outputs,
  condition-pair comparisons, agreement summaries, lateralization contrasts,
  electrode/significance inventories, Z-score report tables, and base-rate
  summaries.
- `statistical_tests.py`: Publication Report-specific Shapiro-Wilk,
  t-test/Wilcoxon diagnostics, selected-test decisions, and Holm/Bonferroni
  correction helpers used by manuscript-review workbook sheets.
- `narrative.py`: rule-based Markdown and dependency-free DOCX writing from the
  typed request plus generated source tables.
- `workbook.py`: `Publication_Report_Data.xlsx` writer plus audit JSON writer.
- `runner.py`: GUI-agnostic orchestration entry point for tests and the GUI
  worker. It may read workbooks and write artifacts but must not import or touch
  widgets.
- `worker.py`: Qt worker wrapper for the embedded page, using signals only.
- `gui.py`: embedded PySide6 page for manual sidebar execution.
- `AGENTS.md`: package-local agent guidance and focused checks.

Built-in ROI helpers stay data-driven and reusable. Semantic-report defaults
include LOT, ROT, Central, and bilateral OT, but the report runner accepts
arbitrary project ROI definitions for other single-group studies.

v1 semantic-report defaults:

- LOT: `P7, P9, PO7, PO3, O1`
- ROT: `P8, P10, PO8, PO4, O2`
- Central: `FCz, Cz, CPz, CP1, C1, FC1`
- Bilateral OT: `P7, P9, PO7, PO3, O1, P8, P10, PO8, PO4, O2`

LOT, ROT, and Central are separate report ROIs. LOT+Central may be added later
as a project-specific custom ROI, but it is not a built-in v1 default.

LOT and ROT are default primary ROIs for the semantic report label. Central is
checked by default as a supporting/exploratory ROI, and the generated narrative
should label it that way unless the user changes the role.

## Output Folder

Default project output folder:

`5 - Publication Report`

Expected files:

- `Publication_Report.md`: readable information-pack narrative.
- `Publication_Report.docx`: Word version of the information-pack narrative.
- `Publication_Report_Data.xlsx`: source workbook for all reported numbers.
- `Publication_Report_Audit.json`: machine-readable settings and provenance.
- `Figure_Manifest` workbook sheet and warning entries for requested spectra,
  scalp-map, and optional individual-detectability figure families. Automated
  figure file export is deferred.
- `logs/`: readable run log and warnings.

## Report Sections

The initial draft should generate these sections when the relevant options are
enabled:

1. Dataset and analysis summary
2. Group-level target/oddball response
3. ROI-level harmonic response table
4. Scalp topography and significant electrodes
5. Individual-level detectability
6. General visual base-rate response
7. Optional response across repetitions/sequences, if source data support it
8. Reproducibility notes and warnings

The text should use configurable labels. For the semantic-categories project,
the target response label might be "semantic categorization response"; for a
different project it might be "face discrimination response" or "condition
response".

For v1, all selected conditions should be reported in the same output. The
report should include within-subject condition comparisons when the selected
condition/ROI design is supported by the existing single-group Stats workflow.
When a comparison cannot be run because of missing cells or unsupported design,
the report should say that clearly in the audit and omit comparison language.
For supported designs, v1 should run the existing RM-ANOVA plus post-hoc path
and also run direct condition-pair comparisons within each ROI as a separate
analysis. The narrative and workbook should report whether the two approaches
agree in significance and direction for each comparison.

## Workbook Sheets

Initial workbook sheets:

- `Run_Summary`: project root, selected conditions, included participants,
  exclusions, settings, package version, and warnings.
- `Participant_Inclusion`: all discovered participants, final included
  participants, manual exclusions, QC exclusions, and exclusion reasons.
- `Condition_Roles`: condition names, user-facing labels, and role tags.
- `ROI_Definitions`: ROI names, role tags, and electrodes.
- `Harmonic_Selection`: selected oddball harmonics and group-selection
  diagnostics reused from Stats where possible.
- `ROI_Harmonic_Summary`: condition x ROI x harmonic summary values.
- `ROI_Response_Summary`: condition x ROI participant-level Summed BCA, mean,
  SD, median, range, baseline-vs-zero tests, and effect sizes.
- `Semantic_Color_Ratio_Values`: participant x ROI Semantic Response divided by
  Color Response ratio values using the same participant-level Summed BCA values
  and selected harmonic list.
- `Semantic_Color_Ratio_Summary`: ROI-level semantic/color ratio summaries
  reporting min, max, mean, median, and SD before and after dropping the single
  minimum and single maximum valid ratio, plus participant-level stability
  diagnostics.
- `Condition_Comparisons`: supported within-subject condition comparisons from
  existing Stats outputs, including test statistics, p-values, corrected
  p-values, and effect sizes.
- `Stats_RM_ANOVA`: direct table returned by the existing Stats RM-ANOVA
  workflow for the selected conditions and report ROIs.
- `Stats_Posthoc`: direct table returned by the existing Stats posthoc workflow,
  retained as an exploratory source table where available; planned manuscript
  ROI comparisons use the dedicated Holm-corrected Publication Report sheets.
- `Stats_Workflow_Summary`: run status, participant-set, exclusion, and
  backend notes from the embedded Stats workflow calls.
- `Condition_Pairs_By_ROI`: direct condition-pair comparisons within each ROI,
  generated as a separate analysis from the RM-ANOVA/post-hoc workflow.
- `Comparison_Agreement`: whether RM-ANOVA/post-hoc conclusions and direct
  ROI-wise condition-pair comparisons agree on significance and direction.
- `Planned_Lateralization`: planned LOT/ROT semantic and low-level color
  lateralization contrasts plus the direct asymmetry-difference contrast
  testing whether `(ROT - LOT)` differs between the semantic and color
  responses.
- `Normality_Checks`: Shapiro-Wilk diagnostics for planned manuscript ROI
  tests, including condition x ROI responses, paired condition differences,
  planned lateralization differences, and direct asymmetry-difference contrasts.
- `Parametric_vs_Nonparametric_Tests`: side-by-side t-test and Wilcoxon
  signed-rank results for planned manuscript ROI tests, with selected-test
  decisions and decision reasons.
- `Planned_ROI_Comparisons_Holm`: selected planned manuscript ROI p-values
  corrected with Holm by planned family; Bonferroni reference p-values may be
  exported for auditability, but Holm is the manuscript-facing correction.
- `Statistical_Test_Decisions`: compact selected-test, normality, and Holm
  decision table for manuscript review.
- `Group_Electrode_Significance`: threshold x condition x electrode summaries.
- `Individual_Detectability`: participant x condition x ROI or whole-head
  detectability flags and significant-electrode counts.
- `Individual_Detectability_Counts`: condition x ROI participant counts and
  proportions with at least one BH-FDR significant electrode.
- `Individual_ROI_Summed_Z`: participant x condition x ROI ROI-averaged
  summed-harmonic Z scores and one-tailed p-values.
- `Individual_Electrode_Summed_Z`: participant x condition x electrode
  summed-harmonic Z scores and one-tailed p-values.
- `Individual_Electrode_FDR`: participant x condition x electrode
  summed-harmonic Z scores, one-tailed p-values, BH-FDR q-values, and
  threshold flags.
- `Old_vs_New_Detectability_Comparison`: legacy Stouffer values labeled
  `Legacy_Stouffer` for validation only.
- `Z_Score_Report`: consolidated report-facing Z scores and one-tailed p-values
  from harmonic selection, ROI harmonic summaries, and base-rate summaries.
- `Base_Rate_Summary`: 6 Hz and harmonic summaries by condition and base-rate
  ROI.
- `Figure_Manifest`: requested figure families, status, and source parameters.
- `Warnings`: missing sheets, missing electrodes, skipped files, and
  non-fatal assumptions.

## Core Computations

### Group-Level Oddball Harmonics

Reuse the existing Stats group-level significant-harmonic selector. Preserve:

- selection from grand-averaged `FullFFT Amplitude (uV)`;
- z > 1.64 threshold;
- all-scalp electrode scope;
- +/-10 FFT-bin noise window;
- immediate-neighbor exclusion;
- min/max finite noise exclusion;
- population SD;
- exact-column matching;
- common harmonic list applied uniformly across participants, conditions, and
  ROIs.

### ROI-Level Harmonic Summaries

Add report-specific summaries that do not alter the Stats DV policy:

- per condition x ROI x harmonic mean and SD for BCA, SNR, and Z where
  available;
- group-level ROI-mean Z at each tested harmonic;
- threshold flags for z > 1.64, z > 2.32, and z > 3.1;
- exact one-tailed positive-direction p-values and p-labels derived from each
  reported Z value.

These summaries are descriptive/reporting outputs only unless explicitly wired
to a statistical test.

### Planned Manuscript ROI Tests

Publication Report planned manuscript ROI tests keep the existing participant-
level Summed BCA dependent values unchanged, then add diagnostics and
correction labels around those values:

- condition x ROI one-sample response tests run Shapiro-Wilk on participant-
  level summed BCA, a one-sample t-test against zero, and a Wilcoxon
  signed-rank sensitivity/fallback test against zero;
- direct condition-pair comparisons run Shapiro-Wilk on paired difference
  scores, paired t-tests, and Wilcoxon signed-rank tests on the same
  differences;
- planned LOT/ROT lateralization tests use right-minus-left difference scores
  for each condition, plus the direct asymmetry-difference contrast;
- planned manuscript ROI p-values are selected from the parametric test when
  Shapiro-Wilk supports the normality assumption and from Wilcoxon when
  Shapiro-Wilk indicates non-normality;
- planned manuscript ROI comparison families use Holm correction on selected
  p-values, while BH-FDR remains reserved for electrode-level individual
  detectability maps/counts.

### Semantic/Color Ratio Summaries

For semantic-category reports with both Semantic Response and Color Response
conditions, add a descriptive participant-level ratio output:

- compute `Semantic Response summed BCA / Color Response summed BCA` for each
  participant x ROI after Summed BCA has already been calculated over the
  selected significant harmonics;
- keep the numerator, denominator, ratio, validity flag, invalid-denominator
  reason, and deviation from the ROI median in the participant-level sheet;
- summarize each ROI with valid-ratio min, max, mean, median, and SD;
- repeat the same min, max, mean, median, and SD after dropping the single
  minimum and single maximum valid ratio;
- export descriptive stability diagnostics such as CV, IQR, MAD, and the
  percentage of participant ratios within 10% and 20% of the ROI median.

### Significant Electrodes

Add threshold-based summaries for manuscript language:

- participant-first significant electrodes for selected target harmonics or
  combined harmonic response;
- count, electrode labels, and scalp cluster-friendly source table;
- expected-by-chance count based on electrode count and p threshold;
- optional binomial/chance-level p-value;
- individual-level significant-electrode counts with BH-FDR enabled by default.

To stay aligned with the David-style individual-level reporting target, compute
electrode significance at the participant x condition level first. Average or
summarize Z scores only after the individual-level significance masks and
counts have been computed. Do not use a group-averaged Z map to decide whether
an individual participant has significant electrodes. Any separate group-level
electrode map should be clearly labeled as group-level descriptive topography.

### Individual Detectability

Use the David/Rossion-compatible summed-harmonic Z logic:

- use raw participant `FullFFT Amplitude (uV)` spectra and the Stats-selected
  group harmonic list;
- compute ROI-level participant detectability from ROI-averaged amplitude
  spectra before calculating summed-harmonic Z;
- compute electrode-level summed-harmonic Z for significant-electrode maps;
- apply BH-FDR across electrodes within participant x condition;
- keep legacy Stouffer values only in explicitly labeled `Legacy_Stouffer`
  comparison outputs.

Add table exports so the figures are not the only source of individual-level
results.

### Base-Rate Response

Add a base-rate summary that is separate from the oddball response:

- base-rate harmonic list: 6, 12, 18 Hz, etc. up to the same BCA upper limit
  used for the oddball/report workflow;
- base-rate ROI, defaulting to bilateral occipito-temporal or a project-defined
  visual ROI override;
- group-level amplitude, SNR, and Z summaries;
- "significant until nth harmonic" language where supported;
- group-level base-rate detectability/QC statement. Participant-level
  base-rate values can remain in source-data sheets but should not be narrated
  by default.

### Figures

Prefer reusing existing figure systems:

- ROI spectra from Plot Generator data-loading/rendering helpers;
- BCA and SNR scalp maps from Publication Maps;
- individual-level grids from Individual Detectability.

Figure generation should be optional and independently skippable if a figure
path fails while table/report data still complete.

Default v1 GUI state selects spectra, scalp maps, and individual detectability
figure families, records them in the manifest, and warns that automated figure
export is deferred. Each figure family should remain controlled by a checkbox
so users can skip expensive or unnecessary outputs when export is implemented.

## GUI Workflow

Initial embedded tool surface:

`Generate Publication Report`

Possible placement:

- Main app sidebar.

Current v1 direction: make this an embedded tool/page with options and a manual
Run action. It should not auto-run after processing completes.

The GUI action should:

1. Resolve the active project root.
2. Validate the project is single-group.
3. Discover processed condition folders and let the user select which
   conditions to include.
4. Load project report settings and ROI presets.
5. Let the user choose report ROIs and output options.
6. Run the report worker on a background thread.
7. Stream progress, warnings, and completion path through signals.
8. Offer to open the output folder after success.

## Project Settings

Add a project-level `publication_report` settings block after the report schema
is stable. Candidate fields:

- `report_label`
- `target_response_label`
- `primary_condition`
- `conditions_to_include`
- `condition_role_map`
- `primary_rois`
- `exploratory_rois`
- `base_rate_roi`, defaulting to bilateral occipito-temporal
- `base_rate_harmonic_limit_hz`, defaulting to the BCA upper limit
- `oddball_harmonic_limit_hz`
- `z_thresholds`
- `z_p_value_tail`, defaulting to one-tailed positive direction
- `use_individual_fdr`
- `individual_fdr_alpha`
- `generate_spectra`
- `generate_scalp_maps`
- `generate_individual_figures`
- `output_markdown`
- `output_docx`

Settings should have sensible defaults but must be explicit in the audit output.

## Phased Implementation

Current status: the implementation slice has landed with the headless runner,
core source tables, semantic/color ratio outputs, planned manuscript statistical
diagnostics, Markdown/DOCX narrative output, audit/workbook/log artifacts, and
the embedded manual sidebar page. Automated figure export, persisted
project-level report settings, and semantic convenience presets remain future
slices.

### Phase 1: Headless Skeleton

- Create `Publication_Report` package.
- Add dataclasses and a GUI-agnostic runner.
- Discover project Excel files and validate single-group state.
- Support multiple selected conditions in one report request.
- Write `Publication_Report_Audit.json` and an initial
  `Publication_Report_Data.xlsx` with `Run_Summary`, `Condition_Roles`, and
  `ROI_Definitions`.
- Add unit tests using synthetic Excel workbooks and `tmp_path`.

### Phase 2: Core Tables

- Add harmonic-selection reuse and export.
- Add ROI harmonic summaries.
- Add Summed BCA response summaries.
- Add base-rate response summaries.
- Add individual detectability table exports.
- Add baseline-vs-zero tests by default for each selected condition x ROI.
- Add RM-ANOVA/post-hoc condition-comparison exports where Stats can run them.
- Add direct condition-pair comparisons within each ROI as a separate analysis.
- Add comparison-agreement summaries that state whether the RM-ANOVA/post-hoc
  path and direct ROI-wise pairwise path agree in significance and direction.
- Keep outputs additive and avoid changing existing Stats schemas.

### Phase 3: Narrative Draft

- Generate `Publication_Report.md`.
- Generate `Publication_Report.docx` from the same narrative model.
- Build conservative text templates with clear "not available" or "not run"
  language when optional sections are missing.
- Format test statistics, means, SDs, effect sizes, confidence intervals, and
  p-values using APA-style manuscript conventions.
- Include exact values from workbook frames, not repeated ad hoc calculations.

### Phase 4: Figures

- Programmatically call existing figure builders where reusable.
- Record every generated figure in `Figure_Manifest`.
- Keep figure failures non-fatal when data tables still succeed.

### Phase 5: GUI Integration

- Add a background worker and one-click button.
- Embed the tool as a manually-run page with condition, ROI, and output
  options.
- Add progress/status/error UX.
- Add a visible/manual smoke path.
- Run non-GUI checks locally; do not run offscreen Qt tests.

### Phase 6: Polish And Presets

- Add semantic-categories convenience presets after the generic settings path
  is stable.
- Keep `.md` and `.xlsx` as canonical reviewable outputs even when `.docx` is
  generated.

## Verification Gates

Use the repo standard environment activation where available:

```powershell
.\.venv1\Scripts\Activate.ps1
```

If a checkout only has `.venv`, document that fallback in the handoff.

Focused checks as the plan progresses:

```powershell
python .agents/scripts/audit/agent_audit.py --check stats-structure
python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python -m pytest tests/stats/io/test_stats_ready_export.py -q
python -m pytest tests/publication_maps/test_bca_publication_maps.py -q
python -m pytest tests/publication_report/test_publication_report_runner.py -q
python -m pytest tests/processing/test_individual_detectability_core.py -q
```

Add new focused tests under:

- `tests/publication_report/`
- `tests/stats/analysis/` only if shared Stats helpers change
- `tests/gui/` for smoke definitions, but do not run offscreen Qt locally

## Open Questions

### Report Scope

1. Should the first version generate only one primary condition report, or
   should it handle multiple selected conditions in one report?

   Decision: v1 handles multiple selected conditions in one report.

2. Should "semantic categories" be treated as a report label only, or should
   the workflow have a named semantic-categories preset?

   Decision: user-editable report label only.

3. Should the report include all processed participants by default, or mirror
   current Stats manual/QC exclusions?

   Decision: mirror current Stats manual/QC exclusions in the analyzed sample
   and show included/excluded participant information to the user.

### ROIs

4. Which ROIs should be required defaults for the first semantic report?

   Decision: LOT, ROT, and Central are built-in options for the first semantic
   report workflow. LOT defaults to `P7, P9, PO7, PO3, O1`. ROT defaults to
   `P8, P10, PO8, PO4, O2`. Central defaults to
   `FCz, Cz, CPz, CP1, C1, FC1`.

5. Should LOT be the primary target ROI by default?

   Decision: yes. LOT and ROT are default primary ROIs. Central is selected by
   default as a supporting/exploratory ROI.

6. Should central ROI and combined LOT+central ROI be built in as optional
   exploratory ROIs?

   Decision: report LOT, ROT, and Central separately by default. Do not add
   LOT+Central as a built-in v1 ROI.

7. What should the default base-rate visual ROI be?

   Decision: bilateral occipito-temporal, defaulting to
   `P7, P9, PO7, PO3, O1, P8, P10, PO8, PO4, O2`.

### Harmonics And Thresholds

8. Should report tables show every candidate oddball harmonic up to the BCA
   upper limit, or only the selected significant harmonics plus nearby
   manuscript-relevant harmonics?
9. Should individual-level detectability use the Stats-selected group harmonics
   or a fixed list such as 1.2, 2.4, 3.6, 4.8, 7.2 Hz?

   Decision: use the Stats-selected group harmonic list.

10. Should individual-level significance default to BH-FDR on, matching the
    current Individual Detectability tool?

    Decision: yes.

11. Should group-level significant-electrode counts use combined harmonic Z,
    summed selected-harmonic Z, or per-harmonic thresholds?

    Decision: adjust toward participant-first significant-electrode reporting:
    compute significance at the participant x condition x electrode level
    first, then calculate average/summarized Z values afterward. Group-level
    descriptive maps may still be produced if clearly labeled.

12. Should report tables use Z > 1.64, Z > 2.32, and Z > 3.1 by default?

    Decision: yes, include these thresholds and corresponding one-tailed
    positive-direction p-values.

### Base Rate

13. Should base-rate reporting use amplitude, SNR, Z score, or all three?

    Decision: all three.

14. Should the report test base-rate harmonics until the BCA upper limit, a
    separate base-rate limit, or the full exported target columns?

    Decision: use the same BCA upper limit.

15. Should base-rate detectability be reported for each participant or only as
    a group-level QC statement?

    Decision: group-level QC statement. Keep source values in the workbook, but
    do not narrate participant-level base-rate significance by default.

### Narrative And Outputs

16. Should the generated Results draft be conservative and descriptive, or
    should it include stronger interpretation language when thresholds are met?
17. Should the first deliverable be Markdown plus Excel only, or should Word
    `.docx` be part of the first implementation phase?

    Decision: include `.docx` in v1.

18. Do you want APA-style p-value formatting and exact manuscript prose rules
    built in from the start?

    Decision: yes.

### GUI And Automation

19. Where should the one-click button live: main sidebar, Tools menu, Stats
    window, or a dedicated Publication Report page?

    Decision: embedded manually-run tool/page in the main sidebar.

20. Should report generation automatically run after processing completes, or
    remain a separate explicit user action?

    Decision: explicit manual action after processing completes.

21. Should figure generation be enabled by default, or should the first click
    produce tables/text first and figures only when requested?

    Decision: enable spectra, scalp maps, and individual detectability figures
    by default, with checkboxes to disable each family.

## Design Decisions To Lock After User Answers

- Initial report output format.
- Decision: generate Markdown, Excel, and `.docx` in v1.
- Default condition-role model.
- Report preset/label model.
- Decision: semantic categories is a user-editable report label, not a
  hard-coded named preset.
- Participant inclusion/exclusion policy.
- Decision: mirror Stats manual/QC exclusions for analysis and show
  inclusion/exclusion details to the user.
- Default ROI roles and electrodes.
- Decision: include LOT, ROT, and Central options, plus bilateral OT for base-rate
  defaults.
- Decision: LOT and ROT are default primary ROIs; Central is default
  supporting/exploratory ROI.
- Decision: LOT = `P7, P9, PO7, PO3, O1`; ROT =
  `P8, P10, PO8, PO4, O2`; Central =
  `FCz, Cz, CPz, CP1, C1, FC1`; bilateral OT =
  `P7, P9, PO7, PO3, O1, P8, P10, PO8, PO4, O2`.
- Default individual-level harmonic source.
- Decision: use Stats-selected group harmonic list.
- Individual-level significance correction.
- Decision: BH-FDR enabled by default.
- Significant-electrode method.
- Decision: use participant-first electrode significance, then average or
  summarize Z values afterward; label any group-level maps separately.
- Default base-rate ROI and metric.
- Decision: base-rate ROI is bilateral OT; metrics are amplitude, SNR, and Z.
- Default base-rate harmonic limit.
- Decision: use the same BCA upper limit.
- Default base-rate detectability narrative.
- Decision: group-level QC statement only by default, with source values kept
  in the workbook.
- Whether central/combined ROIs are first-class presets or project-specific
  report settings.
- Decision: LOT, ROT, and Central are first-class separate presets; LOT+Central is
  not built in for v1.
- GUI entry point.
- Decision: manually-run embedded tool/page in the main sidebar.
- Decision: include baseline-vs-zero tests by default.
- Decision: include supported within-subject condition comparisons when Stats
  can run them.
- Decision: run RM-ANOVA/post-hoc and direct condition-pair comparisons within
  each ROI as separate analyses, then report agreement in significance and
  direction.
- Decision: use APA-style narrative formatting.
- Decision: generate spectra, scalp maps, and individual detectability figures
  by default, with per-family checkboxes.
