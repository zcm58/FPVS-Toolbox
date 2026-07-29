# Standard FPVS Screening With LMM-First Inference

## Status

Active on branch `codex/stats-screening-lmm-default`.

Started 2026-07-29. This plan must be updated after every phase with the
verification result and phase commit hash.

## Goal

Reframe native Stats as a transparent first-round FPVS screening workflow:

1. determine whether positive oddball responses are supported;
2. determine whether responses vary with Condition, ROI, or their interaction;
3. explain supported factorial patterns with model-estimated contrasts; and
4. in a two-group project, directly test Group A versus Group B in every
   Condition x ROI cell while separately describing the broader group pattern.

The linear mixed model (LMM) is the primary factorial analysis in balanced and
partially observed datasets. ANOVA is secondary compatibility evidence only
when its stricter balance requirements are met. The module must state that it
does not replace a project-specific final model.

## Current Repository Context

The branch starts from commit `122768d0` (`fix(stats): preserve cohort with
missing conditions`) and inherits verified but uncommitted work from the
preceding Stats iterations:

- canonical harmonic-cache identity and faster selected-column QC reads;
- removal of routine IDE noise and the dense Methods & Checks GUI tab;
- a shorter At a Glance summary in
  `reporting/inference/at_a_glance.py`; and
- related Stats, processing, GUI-contract, reporting, and documentation tests.

The current inference foundation already provides:

- manifest-owned participant/group identity;
- frozen-cohort design audits;
- complete-core and available-case preparation without imputation;
- random-intercept, sum-coded single and multi-group LMMs;
- hierarchy-preserving ML likelihood-ratio block tests with final REML
  estimates;
- named Holm correction families;
- response-versus-zero tests;
- same-sample harmonic-selection provenance warnings;
- convergence, singularity, normality, resampling, robust, and leave-one-out
  diagnostics; and
- detailed workbook exports.

The current workflow still needs these behavioral changes:

- complete-core and RM-ANOVA are currently the single-group default;
- the response alternative defaults to two-sided;
- single follow-ups are paired t-tests gated by RM-ANOVA;
- multi-group response-versus-zero screening is absent;
- direct group-cell tests are standalone Welch tests instead of fitted-LMM
  contrasts;
- projects with more than two groups can enter the current model;
- method-selection controls expose decisions now locked by this standard
  screening contract; and
- reporting still describes a general inference suite rather than a
  first-round screening/custom-model boundary.

## Locked Scientific and Product Decisions

- Summed BCA remains the dependent variable and the locked harmonic-selection
  policy is unchanged.
- Positive-response tests use the prespecified one-sided alternative
  `greater than zero`.
- Factorial and Group A minus Group B contrasts remain two-sided.
- The primary model uses a participant random intercept:
  - single: `Summed BCA ~ Condition * ROI + (1 | Participant)`;
  - multi: `Summed BCA ~ Group * Condition * ROI + (1 | Participant)`.
- Finite available observations are used without imputation. Missing-data
  reporting retains the MAR assumption and MNAR limitation.
- Multi-group standard screening supports exactly two canonical groups.
  Three-or-more-group projects require a future feature or custom analysis.
- Group A minus Group B contrasts run for every estimable Condition x ROI cell
  as a prespecified family. They are not gated by a global group-pattern test.
- Holm family-wise correction is fixed for primary named families.
- Interaction explanations and group-cell comparisons are explicitly labelled
  `LMM-derived model-estimated contrast` and the detailed method identifies the
  asymptotic Wald inference.
- Existing hierarchy-preserving LRT rows retain accurate block labels. They
  must not be relabelled as pure Type-III main effects.
- Single-group repeated-measures ANOVA runs only on a perfectly complete,
  unique participant x Condition x ROI matrix and is compatibility-only.
- A balanced multi-group compatibility check may use a combined
  `response_cell = Condition x ROI` within factor with Group as the
  between-subject factor. It requires complete unique coverage and equal group
  sizes, and must be labelled as a broad `Group x response-cell` check that
  does not validate separate three-way components.
- Diagnostics do not select or replace the primary test automatically.
- The headline is a short standard-screening summary; complete methods,
  estimates, intervals, correction metadata, diagnostics, and limitations stay
  in the workbook.

## Non-Goals

- Do not change preprocessing, harmonic detection, neighboring-noise, BCA
  summation, ROI, or workbook-discovery rules.
- Do not add covariates, trial/item-level models, longitudinal models, nested
  designs, three-group inference, or automated random-slope selection.
- Do not claim Kenward-Roger or Satterthwaite inference.
- Do not infer a group difference by comparing within-group significance.
- Do not make ANOVA a fallback primary analysis when the LMM fails.
- Do not run local offscreen Qt or pytest-qt workflows.

## Phase 0 — Preserve and Verify the Inherited Baseline

### Work

- Review the inherited dirty changes and separate them into coherent baseline
  commits for cache identity, QC performance, and result-summary cleanup.
- Keep this active plan with the baseline checkpoint.
- Run the Stats focused gate and the processing tests affected by harmonic/QC
  changes.

### Definition of Done

- [x] Inherited changes are committed without mixing in new screening logic.
- [x] The untracked At a Glance module is tracked.
- [x] Stats structure, reporting-legibility, and GUI-import audits pass.
- [x] Focused Stats verification passes.
- [x] Focused harmonic/QC processing tests pass.
- [x] The worktree is clean before Phase 1 begins.

### Verification

- `python .agents/scripts/verify.py --scope stats --tier focused`
- focused harmonic-cache/QC processing tests selected by changed-file scope
- `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`

### Commits

- `9fe0f180` — `fix(stats): stabilize harmonic cache identity`
- `24b0702b` — `perf(stats): speed QC workbook screening`
- `4f59a583` — `refactor(stats): simplify in-app result summary`

## Phase 1 — Screening Contracts and Shared LMM Contrasts

### Work

- Add a GUI-neutral fitted-LMM contrast engine using the fitted fixed-effect
  design and covariance.
- Support equal-weight estimated marginal contrasts for:
  - Condition differences within ROI;
  - ROI differences within Condition;
  - Group A minus Group B within Condition x ROI;
  - group contrasts averaged across ROI or Condition when explaining
    lower-order group-pattern blocks.
- Attach estimate, standard error, confidence interval, Wald statistic,
  two-sided p-value, sign, estimand, coverage, and method metadata.
- Add deterministic synthetic screening fixtures and analytical contrast
  tests.
- Fix the standard inference contract to Holm families, one-sided positive
  response tests, two-sided model contrasts, available finite observations,
  and a random-intercept LMM.

### Definition of Done

- [x] Contrast estimates and signs match known synthetic fixed effects.
- [x] Reversing Group A and Group B reverses estimates and confidence bounds
      without changing two-sided p-values.
- [x] Missing participant cells are not imputed and do not prevent estimable
      contrasts.
- [x] Structurally empty cells are explicitly non-estimable.
- [x] Every row says `LMM-derived model-estimated contrast` and identifies the
      asymptotic Wald method.
- [x] Existing ML-LRT formulas and final REML estimation remain intact.
- [x] Focused Stats verification passes.

### Verification

- focused contrast, mixed-model, design-audit, and multiplicity tests
- `python .agents/scripts/verify.py --scope stats --tier focused`

### Commit

- Phase commit recorded below after this plan update.

## Phase 2 — Single-Group Standard Screening

### Work

- Make the audited available-observation random-intercept LMM the primary
  factorial route for both complete and incomplete datasets.
- Run one-sided positive-response tests across the global Condition x ROI Holm
  family.
- Make corrected LMM block/interaction results—not ANOVA—drive the factorial
  summary and interaction explanation.
- Replace paired-t follow-ups with LMM-derived Condition-within-ROI and
  ROI-within-Condition contrasts.
- Emphasize automatic simple contrasts only when the corrected LMM interaction
  supports explanation; preserve explicitly planned exploratory provenance.
- Preserve same-sample harmonic-selection results as visibly exploratory
  positive-response evidence instead of treating them as independent
  confirmation.

### Definition of Done

- [ ] Balanced and incomplete data both enter the same primary LMM route.
- [ ] A participant missing one condition contributes every remaining finite
      observation.
- [ ] Positive-response tests are one-sided and Holm-corrected as one family.
- [ ] A strong negative cell is never called a positive response.
- [ ] Corrected LMM interaction evidence controls automatic interaction
      explanation.
- [ ] Primary follow-ups are model-estimated contrasts, not paired t-tests.
- [ ] ANOVA results cannot enter the primary single-group conclusion.
- [ ] Focused Stats verification passes.

### Verification

- focused baseline, single-LMM, worker, controller, pipeline, and reporting
  tests
- `python .agents/scripts/verify.py --scope stats --tier focused`

### Commit

- Pending.

## Phase 3 — Two-Group Standard Screening

### Work

- Require exactly two canonical project groups and use them consistently in
  preparation, the full LMM, response tests, contrasts, and reporting.
- Add one-sided within-group response tests across one
  Group x Condition x ROI Holm family.
- Replace primary Welch cell tests with two-sided LMM-derived Group A minus
  Group B contrasts in every estimable Condition x ROI cell.
- Always run the direct cell family; do not gate it on a global group-pattern
  result.
- Retain and accurately label the four hierarchy-preserving group-related LRT
  blocks as a separately corrected explanatory family.
- Report localized-cell/global-pattern disagreement without treating either as
  equivalence or a causal result.

### Definition of Done

- [ ] A third canonical group blocks standard multi-group screening with a
      custom-analysis message.
- [ ] Within-group response evidence never substitutes for a direct group
      comparison.
- [ ] Group-cell estimates come from the same fitted LMM used for omnibus
      inference.
- [ ] Group-cell Holm correction covers every estimable retained cell.
- [ ] Cell contrasts run even when the joint group-pattern test is
      nonsignificant.
- [ ] Sparse participants retain all usable observations without imputation.
- [ ] Empty fixed-effect cells block inference clearly.
- [ ] Focused Stats verification passes.

### Verification

- focused multi-LMM, group contrast, response, worker, controller, pipeline,
  and reporting tests
- `python .agents/scripts/verify.py --scope stats --tier focused`

### Commit

- Pending.

## Phase 4 — Balanced-Only ANOVA Compatibility

### Work

- Add an explicit exact-balance audit for compatibility checks.
- Run the existing two-way repeated-measures ANOVA in single-group mode only
  when every included participant has exactly one finite value in every
  Condition x ROI cell.
- For exactly two equal-sized, complete groups, run a broad
  `Group x response-cell` mixed ANOVA where `response-cell` is the declared
  Condition x ROI combination.
- Label all ANOVA output secondary and compatibility-only.
- If requirements or the supported backend are unavailable, return a concise
  reason without affecting the primary LMM.
- Compare compatibility direction/decisions with the corresponding broad LMM
  questions without presenting numerical identity as a requirement.

### Definition of Done

- [ ] Missing, duplicate, or non-finite cells skip ANOVA without failing the
      LMM screen.
- [ ] Single compatibility output retains canonical GG/sphericity handling.
- [ ] Multi compatibility requires two groups, complete cells, and equal group
      sizes.
- [ ] Multi compatibility is labelled `Group x response-cell mixed-ANOVA
      compatibility check`.
- [ ] Multi compatibility explicitly says it does not decompose separate
      Group x Condition x ROI terms.
- [ ] ANOVA never changes, gates, or replaces a primary LMM conclusion.
- [ ] Focused Stats verification passes.

### Verification

- focused balance-audit, RM-ANOVA, mixed-ANOVA compatibility, worker,
  reporting, and export tests
- `python .agents/scripts/verify.py --scope stats --tier focused`

### Commit

- Pending.

## Phase 5 — GUI and Plain-Language Screening Report

### Work

- Recast the tool and action label as `Standard FPVS Screening`.
- Replace method-choice controls that conflict with locked defaults with a
  read-only method summary:
  - primary random-intercept LMM;
  - one-sided positive-response question;
  - finite observations without imputation;
  - Holm family-wise correction; and
  - automatic balanced-only ANOVA compatibility.
- Keep scientific selections such as conditions, ROIs, manual exclusions, and
  the two group labels.
- Keep optional robustness checks secondary/advanced.
- Make At a Glance answer only:
  - positive-response evidence;
  - Condition/ROI response pattern;
  - model-estimated interaction explanation when supported; and
  - direct group-cell differences plus broader group pattern in multi mode.
- Add explicit first-round/custom-model, same-sample harmonics, missingness,
  association-not-causation, and non-equivalence boundaries.
- Preserve detailed workbook auditability and the concise Run log.
- Update CI-only GUI smoke definitions and document a visible Windows smoke
  path.

### Definition of Done

- [ ] The GUI no longer suggests that ANOVA, direction, correction, or
      missing-data scope are competing primary choices.
- [ ] The main action says `Run Standard Screening`.
- [ ] At a Glance is short, plain-language, and contains no dense inventory or
      p-value dump.
- [ ] LMM-derived contrasts are named as such wherever interpreted.
- [ ] Same-sample response evidence remains visible but exploratory.
- [ ] Custom-model triggers are clear and non-alarming.
- [ ] No long work is moved onto the UI thread.
- [ ] GUI import and reporting-legibility audits pass.
- [ ] Focused Stats verification passes; Qt tests remain CI-only.

### Verification

- `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`
- `python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility`
- focused GUI-contract, reporting, pipeline, and export tests
- `python .agents/scripts/verify.py --scope stats --tier focused`

### Commit

- Pending.

## Phase 6 — Documentation, Verification Registry, and Handoff

### Work

- Update the Stats package contract, architecture guide, user guide, tool
  information, methods/export language, and verification registry.
- Remove stale claims that Welch/paired t-tests or RM-ANOVA are primary while
  retaining explicitly named legacy exports only where compatibility requires
  them.
- Document the exact estimands, test direction, correction families, LMM
  assumptions, asymptotic inference limitation, available-data behavior,
  ANOVA compatibility scope, and custom-model boundary.
- Run the full Stats gate and repository precommit gate.
- Complete this plan with commit hashes, verification evidence, residual
  risks, and the visible manual smoke procedure.

### Definition of Done

- [ ] Architecture, Stats AGENTS, user documentation, and implementation agree.
- [ ] The Stats verification registry includes all new screening contracts.
- [ ] All focused non-Qt tests and audits pass.
- [ ] Repository precommit verification passes.
- [ ] `git diff --check` is clean.
- [ ] The worktree is clean and every phase has a dedicated commit.
- [ ] The plan records the final manual visible smoke path and residual risk.

### Final Visible Smoke Path

Run in a normal visible Windows session, never offscreen:

1. Open a balanced single-group project and confirm LMM-first results plus an
   ANOVA compatibility line.
2. Open a single-group project with one participant-condition exclusion and
   confirm the LMM completes, the observation remains missing, and ANOVA is
   skipped.
3. Open a balanced two-group project and confirm within-group response,
   direct Group A minus Group B cell contrasts, group-pattern results, and the
   broad ANOVA compatibility line.
4. Open a two-group project with partial participant coverage and confirm the
   LMM retains available rows, cell Ns/coverage vary, and ANOVA is skipped.
5. Confirm a project with three canonical groups stops with a concise
   custom-analysis message.
6. Confirm cancellation, progress, export, Run log, and project switching
   remain responsive and do not retain stale results.

### Commit

- Pending.

## Progress Log

- 2026-07-29: Branch created. Initial repository, Stats architecture, testing,
  reporting, and GUI audits completed. No screening implementation changes made
  before this plan was written.
- 2026-07-29: Phase 0 baseline verified: harmonic/cache tests 19 passed, QC
  tests 4 passed, Stats focused verification 306 passed, and GUI import audit
  passed. Cache identity and QC performance were committed separately; the
  simplified result-summary baseline and this plan form the closing Phase 0
  commit.
- 2026-07-29: Phase 1 added the locked standard-screening contract and a
  GUI-neutral fitted-LMM estimated-marginal-contrast engine. New contrast and
  contract tests passed (13), focused model/design/multiplicity tests passed
  (48), Stats focused verification passed (307), Ruff/compile passed, and
  `git diff --check` found no whitespace errors.
