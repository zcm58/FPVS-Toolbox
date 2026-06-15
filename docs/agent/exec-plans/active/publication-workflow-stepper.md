# Publication Workflow Stepper

## Status

Active implementation.

Initial executable slice implemented on `codex/publication-workflow-stepper`:

- `src/Tools/Publication_Workflow/` package with project-local workflow state,
  QC decision JSON persistence, and an embedded PySide6 `Publication Workflow`
  sidebar page.
- Main sidebar entry: `Publication Workflow`, living beside the existing
  direct `Publication Report` tool.
- Stepper status table for Data Ready, QC Review, Outlier Decisions, Freeze
  Analysis Set, Publication Report, Figures, and Export Package.
- QC run action that reuses `PublicationReportWorker` with report narrative
  outputs disabled and QC figures enabled, preserving all participants.
- Summed-BCA IQR candidate table populated from the report workbook's
  `QC_Outlier_Values` sheet.
- Manual participant-level decision freezing through `QC_Decisions.json`, with
  required reasons for `exclude` decisions.
- Publication Report action that reuses `PublicationReportWorker` with frozen
  participant-level QC exclusions applied.
- Figure handoff buttons for Publication Report, Scalp Maps, and LORETA
  Visualizer; deeper automated figure orchestration remains a later slice.

This plan defines a guided post-processing workflow that starts immediately
after data processing is complete and walks the user through QC, manual
outlier decisions, publication-report generation, and downstream figure
generation.

It is a companion to `publication-report-workflow.md`. The Publication Report
package remains the owner of report tables, narrative, audit exports, and
report-local QC figures. This plan owns the higher-level stepper that makes the
recommended order visible and records project-level QC decisions before the
report is generated.

## Problem

The current workflow is powerful but too implicit:

- users must know to run QC before interpreting report-level participant
  detectability;
- report generation, scalp-map figure generation, and LORETA Visualizer handoff
  are separate manual actions;
- outlier flags are currently descriptive report outputs, not a first-class
  review step;
- publication report calculations can be rerun with exclusions, but the
  decision trail is not yet guided, frozen, or surfaced as a workflow state;
- unexpected condition differences, such as stronger individual-level
  detectability for the semantic condition than the color condition, need a
  fast way to inspect whether the explanation is harmonic selection, sample
  exclusions, non-normal participant distributions, or participant-level
  outliers.

## Goals

- Add a PySide6 stepper surface that guides users through the expected
  post-processing order.
- Make QC the first recommended step after data processing.
- Generate and surface boxplots, histograms, Q-Q plots, normality diagnostics,
  and outlier tables before publication calculations are finalized.
- Automatically flag candidate outliers using IQR fences while requiring manual
  confirmation before any exclusion affects analysis.
- Freeze the confirmed analysis set in a project-local audit artifact that the
  Publication Report can consume.
- Generate the Publication Report using the frozen inclusion/exclusion state.
- Then guide the user to downstream figure generation, including scalp maps and
  LORETA Visualizer payload/viewing steps where supported.
- Preserve existing statistical-method contracts unless a separate
  statistical-method change is explicitly approved.

## Non-Goals

- Do not change preprocessing order, FFT export behavior, Stats significant
  harmonic selection, or Publication Report statistical methods as part of the
  stepper shell.
- Do not automatically exclude participants based only on IQR, normality, or
  any other automated diagnostic.
- Do not implement condition x ROI cell-level exclusions in v1 unless the
  statistical reporting policy is explicitly updated. The current Publication
  Report exclusion contract is participant-level, so v1 should freeze
  participant-level exclusions.
- Do not revive retired Source Localization or eLORETA runtime code. LORETA
  Visualizer integration must remain within the prepared-payload boundary under
  `src/Tools/LORETA_Visualizer/`.
- Do not run offscreen Qt tests locally.

## User Experience

Create a main-sidebar entry named `Publication Workflow`. The page is a
stepper, not a static form. Keep the label isolated in the sidebar/action
registration so it can be renamed later without changing workflow state,
artifact names, or processing code.

Stepper steps:

1. `Data Ready`
   - Resolve the active project root.
   - Validate that processing outputs and report-source workbooks exist.
   - Show condition folders, groups, participant count, and missing prerequisites.

2. `QC Review`
   - Run the existing Publication Report QC computations without applying
     exclusions.
   - Generate summed-BCA boxplots, histograms, Q-Q plots, and normality tables
     for each selected condition and ROI.
   - Surface candidate IQR outliers with participant IDs, condition, ROI,
     metric, value, fence, and high/low direction.
   - Surface harmonic-selection inputs so the user can distinguish outlier
     effects from significant-harmonic-selection effects.

3. `Outlier Decisions`
   - Present candidate flags in a review table.
   - Allow `include`, `watch`, or `exclude` decisions.
   - Require a reason for confirmed exclusions.
   - Allow manually adding a participant to the review table when visual
     inspection finds an issue not caught by IQR.
   - Keep automated flags as candidates until the user confirms the decision.

4. `Freeze Analysis Set`
   - Write a project-local QC decision artifact and a frozen participant set.
   - Record selected conditions, ROIs, harmonic settings, candidate flags,
     confirmed decisions, reasons, timestamps, and source workbook fingerprints.
   - Mark downstream report and figure steps as needing refresh whenever inputs
     or decisions change.

5. `Publication Report`
   - Generate the report using the frozen participant-level exclusion set.
   - Include the QC decision summary and before/after sensitivity context in
     the report audit outputs.
   - Show an easy-to-read sensitivity panel that compares full-sample results
     with included-participant results and labels each key conclusion as
     unchanged, weaker but same conclusion, stronger but same conclusion, or
     changed conclusion.
   - Keep the report runnable directly for advanced/manual workflows, but guide
     normal users through the stepper.

6. `Figures`
   - Generate or open report figures, spectra, scalp maps, and individual
     detectability figures.
   - Launch or hand off to Publication Maps for BCA/SNR scalp maps where
     needed.
   - Hand off to the LORETA Visualizer only through prepared source-map payloads
     or existing visualizer project outputs. The stepper may show payload
     readiness and open the visualizer, but source-estimation calculations need
     their own explicit plan.

7. `Export Package`
   - Show final report, workbook, audit JSON, QC figures, figure manifest, and
     generated figure folders.
   - Provide a single project-local handoff folder view and warnings for stale
     or skipped artifacts.

## State And Artifacts

All workflow state should be project-root local. Do not store analysis-critical
decisions only in transient app settings.

Candidate artifacts:

- `5 - Publication Report/Workflow_State.json`
- `5 - Publication Report/QC_Decisions.json`
- `5 - Publication Report/QC_Decisions.xlsx`
- `5 - Publication Report/Sensitivity_Summary.xlsx`
- `5 - Publication Report/figures/qc/`
- `5 - Publication Report/Publication_Report_Audit.json`

`QC_Decisions` should include:

- project identifier and source workbook fingerprints;
- selected conditions and ROIs;
- metric source, initially summed BCA in uV plus any normality diagnostics used
  for review;
- participant ID;
- condition;
- ROI;
- observed value;
- IQR lower and upper fences;
- automated flag direction;
- reviewer decision: `include`, `watch`, or `exclude`;
- reviewer reason;
- timestamp;
- version of the stepper and QC schema.

`Workflow_State` should include:

- step statuses: blocked, ready, running, complete, stale, or warning;
- artifact paths relative to the active project root;
- last-run timestamps;
- source fingerprints used for stale-state detection;
- frozen participant exclusion list consumed by Publication Report v1;
- warning summaries surfaced in the UI.

`Sensitivity_Summary` should include:

- one row per key manuscript-facing condition x ROI comparison;
- full-sample N, included N, and excluded participant IDs;
- full-sample estimate, included-sample estimate, and absolute/percent change;
- full-sample p-value or decision and included-sample p-value or decision;
- plain-language outcome label: `unchanged`, `weaker_same_conclusion`,
  `stronger_same_conclusion`, or `changed_conclusion`;
- a short end-user message such as "Excluding flagged participants did not
  change the conclusion for this ROI."

## Method Policy

The stepper validates the publication pipeline without silently changing it.

- IQR outlier flags are candidate review flags only.
- Confirmed exclusions are user decisions and must be auditable.
- Publication Report v1 should consume a participant-level exclusion list,
  because that matches the existing report request model and avoids silent
  condition x ROI sample changes.
- Condition x ROI outlier rows can still be recorded as evidence for excluding
  or watching a participant.
- If future work supports condition-specific or ROI-specific exclusions, it
  needs an explicit methods decision and report language update first.
- Full-sample versus included-sample comparisons are sensitivity checks, not a
  second exclusion decision rule. The user decides exclusions first; the
  sensitivity output then reports whether those confirmed exclusions materially
  changed the publication-facing conclusions.
- Sensitivity outputs should be readable by non-expert users first, with
  detailed p-values, effect sizes, confidence intervals, and bootstrap or
  jackknife diagnostics available in the workbook for reviewers.
- Significant-harmonic selection remains the locked Stats default unless a
  separate statistical-method plan changes it. The stepper should expose the
  selected harmonics and their source parameters so users can diagnose whether
  detectability differences arise from harmonic selection versus participant
  distributions.

## Architecture Direction

Keep orchestration separate from report computation:

- New workflow package candidate:
  `src/Main_App/gui/workflows/publication_stepper/` for the PySide6 page,
  step status model, and controller.
- Reuse shared GUI components from `src/Main_App/gui/components/`.
- Keep long-running QC, report, and figure generation in workers under active
  worker patterns. Widgets must communicate with workers through signals.
- Keep project-root path resolution in active project APIs under
  `src/Main_App/projects/`.
- Reuse `src/Tools/Publication_Report/qc.py` for QC computations and figures.
- Reuse `src/Tools/Publication_Report/runner.py` for report generation.
- Reuse Publication Maps and Individual Detectability figure helpers where
  possible rather than adding duplicate renderers.
- LORETA Visualizer integration should launch or consume prepared payloads only
  and must preserve the visualizer/calculation boundary.

The stepper can start as a sidebar page that orchestrates existing tools.
Existing standalone sidebar entries can remain available for advanced users
while the stepper becomes the recommended path.

## Phased Implementation

### Phase 1: Workflow State Model

- Define workflow step statuses and project-local JSON schema.
- Add load/save helpers with project-root-relative paths.
- Add stale-state detection based on source workbook fingerprints and QC
  decision timestamps.
- Add focused tests using `tmp_path`.

### Phase 2: Stepper Shell

- Add the PySide6 stepper page to the active main sidebar.
- Show the seven-step sequence, prerequisites, current status, and artifact
  links.
- Keep the visual design flat and consistent with active GUI components.
- Add a visible/manual smoke path instead of offscreen Qt execution.

### Phase 3: QC Review Step

- Wire the stepper to run Publication Report QC computations and figures in a
  background worker.
- Surface summed-BCA boxplots as the primary review figure.
- Add secondary Q-Q and histogram views for normality and distribution checks.
- Show candidate outliers in a sortable/filterable table.

### Phase 4: Outlier Decisions And Freeze

- Add include/watch/exclude decisions and required exclusion reasons.
- Write `QC_Decisions.json` and optional workbook export.
- Derive the v1 participant-level exclusion set.
- Mark Publication Report and figure steps stale whenever decisions change.

### Phase 5: Publication Report Integration

- Feed frozen participant exclusions into Publication Report generation.
- Add audit rows that distinguish manual exclusions, QC-confirmed exclusions,
  and non-finite required exclusions.
- Add sensitivity summaries for all participants versus frozen exclusions.
  The first user-facing slice should cover summed-BCA condition x ROI outputs,
  manuscript-facing condition comparisons, and participant-level detectability
  counts.
- Present sensitivity results in a plain-language report panel and workbook
  sheet. The panel should emphasize conclusion stability before showing
  p-value changes.
- Where feasible, include bootstrap or jackknife uncertainty for the change in
  estimate, but keep this secondary to the plain-language conclusion label.

### Phase 6: Figure Step Integration

- Show generated report figures and figure manifest status.
- Add launch/generate handoff for scalp maps and individual detectability
  figures.
- Add LORETA Visualizer readiness checks for existing prepared payloads.
- Keep skipped or failed figure families non-fatal when report outputs succeed.

### Phase 7: Polish And Guardrails

- Add status banners and warnings for stale artifacts, missing workbooks,
  incomplete decisions, failed workers, and empty exclusions.
- Add clear audit output for the final report sample.
- Update user-facing docs once the workflow is implemented.

## Verification Plan

Use non-GUI checks locally:

- `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`
- `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py`
- `python .agents/scripts/audit/agent_audit.py`
- focused `py_compile` for changed modules;
- focused `ruff check` for changed modules;
- focused Publication Report and workflow-state tests;
- project I/O tests when project-root state helpers change.

For GUI behavior, do not run offscreen Qt locally. Document a visible/manual
smoke path that covers:

- opening a project with processed data;
- running QC from the stepper;
- reviewing and freezing an outlier decision;
- generating a Publication Report using the frozen exclusion set;
- confirming the sensitivity panel labels whether conclusions changed after
  exclusions;
- verifying stale-state warnings after changing decisions;
- opening generated QC/report/figure artifacts.

## Open Questions

- Final icon and sidebar ordering for the `Publication Workflow` entry.
- Should QC be a required gate before report generation, or a recommended gate
  that can be bypassed with an explicit audit warning?
- Should v1 store only JSON decisions, or also write an Excel decision workbook
  for easier manual review?
- Should the stepper live beside the current `Publication Report` sidebar entry
  at first, or eventually replace it as the default entry point?
- Which additional sensitivity outputs belong after v1: individual electrode
  FDR summaries, scalp-map source values, or LORETA/source-map payload metrics?
- What should count as a source fingerprint for stale-state detection:
  workbook modified time and size, content hash, or both?
