# Native Single- and Multi-Group Statistical Inference

## Status

Active.

- Branch: `codex/stats-inference-overhaul`
- Started: 2026-07-29
- Last updated: 2026-07-29
- Current phase: Phase 7 - validation, documentation, and closure
- Plan owner: Codex

This plan is the explicitly approved follow-on to
`multi-group-project-foundation.md`. That foundation deliberately excluded
native multi-group statistical models. This plan adds them without changing
the shared project/dataset-index ownership established there.

## Goal

Turn the Stats tool into a publication-capable, non-expert-friendly analysis
workflow for both single-group and true multi-group FPVS projects.

The finished tool must:

- preserve the authoritative processing-time Summed BCA harmonic selection;
- distinguish response detection, within-subject Condition/ROI effects, and
  between-group effects;
- analyze only the conditions shared by the complete primary cohort by
  default;
- provide valid multiplicity control for the scientific claim being made;
- provide balanced RM-ANOVA and mixed-model routes where appropriate;
- provide robust and nonparametric sensitivity analyses without silently
  changing the estimand;
- expose native multi-group inference based on canonical manifest group IDs;
- detect and report assumption, convergence, singularity, missingness, and
  post-selection limitations;
- export detailed publication-quality tables and a complete method inventory;
- present a short, plain-English result summary to a non-expert user;
- retain detailed technical output in workbooks and reporting files rather
  than flooding the visible summary.

## User Outcomes

### Single-group project

The primary action answers:

1. Is there evidence of an FPVS response in any selected Condition x ROI cell?
2. Do responses differ by Condition, ROI, or their interaction?
3. Which prespecified or justified follow-up comparisons explain an effect?
4. Are conclusions stable under robust/nonparametric sensitivity analyses?

### Multi-group project

The primary action answers:

1. Is there an overall group difference?
2. Does the group difference depend on Condition, ROI, or both?
3. Does any complete Condition x ROI cell show a group difference after
   correction across the declared family?
4. Are conclusions stable under unequal-variance and robust sensitivity
   analyses?

### Non-expert reporting

The first visible result must say, in plain language:

- what was compared;
- whether any reliable effect was found;
- the direction and size of supported effects;
- whether the finding survived the selected correction;
- whether the result is primary, sensitivity-only, or exploratory;
- the main limitation that changes interpretation;
- where the detailed workbook/report was saved.

The visible summary must not equate a nonsignificant result with equivalence
and must not present a same-sample adaptive response-detection p-value as
independent confirmatory evidence.

## Scientific Contract

### Separate estimands

The implementation must keep these questions separate:

1. **Response detection:** whether Summed BCA differs from zero.
2. **Within-subject effects:** whether the arithmetic mean response differs
   across Conditions, ROIs, or their interaction.
3. **Between-group effects:** whether group means differ overall or as a
   function of Condition/ROI.
4. **Robust sensitivity estimands:** trimmed means, ranks/medians, or
   permutation-conditioned evidence.

A positive pooled response must never be used as evidence of a condition or
group effect.

### Harmonic-selection contract

- Preserve the current locked processing-time group-significant harmonic
  calculation, exact columns, z threshold, neighboring-bin rule, through-
  highest rule, base-overlap exclusion, one-pass gap guard, fingerprinting,
  and uniform application.
- Preserve the fixed/predefined harmonic policy.
- Do not recalculate harmonics in a new statistics module.
- Add inferential provenance separate from canonical/custom provenance:
  - `independently_selected`
  - `user_fixed_unverified`
  - `same_sample_adaptive`
  - `unknown`
- A user-entered fixed list is not automatically confirmatory: only a list
  selected independently of the analyzed sample receives
  `independently_selected`.
- A same-sample adaptive response-versus-zero test is labelled
  `exploratory_post_selection`.
- `user_fixed_unverified` and `unknown` response-versus-zero tests are not
  promoted to confirmatory evidence without an explicit independent-selection
  attestation.
- Condition, ROI, and group contrasts using one common list remain available
  but retain the adaptive-selection provenance in detailed output.
- The current isolated-highest gap guard is reported as an FPVS Toolbox
  versioned rule, not as a verbatim published standard.

### Analysis profiles

#### Confirmatory

- independently selected harmonic list, with its provenance recorded;
- frozen included participants and QC exclusions;
- complete shared-condition primary cohort;
- one-sided `BCA > 0` only when the directional response hypothesis is
  explicitly selected; otherwise two-sided;
- Holm familywise correction for "any cell differs" claims;
- balanced RM-ANOVA with Greenhouse-Geisser inference when required;
- planned follow-ups with an explicitly named family;
- multi-group omnibus model before simple cell contrasts.

#### Published-style exploratory

- current canonical group-level significant harmonics;
- explicit post-selection label for response detection;
- BH-FDR available for discovery screens;
- Holm and max-T available for familywise claims;
- robust/nonparametric sensitivities displayed separately;
- optional conditions analyzed only in a valid complete subset or a clearly
  labelled secondary available-case model.

The GUI defaults to the profile implied by harmonic provenance:

- independently selected -> Confirmatory;
- user-fixed but unverified, unknown, or canonical same-sample selection ->
  Published-style exploratory.

The user may change profiles in Advanced settings, but the software must not
remove a provenance warning merely because the profile label was changed.

### Primary data scope

- Determine the participant x Condition x ROI grain before inference.
- Reject duplicate observations at that grain.
- Freeze the cohort first: begin with every participant surviving canonical
  QC and manual exclusions.
- Retain a selected condition only when every frozen participant contributes
  exactly one finite value in every selected ROI.
- Never silently drop participants to maximize the number of retained
  conditions.
- Block the complete-core analysis with an actionable result when no condition
  is shared by the frozen cohort.
- The primary RM-ANOVA and primary multi-group model use the complete shared
  conditions.
- Show excluded optional conditions and their participant counts before a run.
- Available-case LMMs are secondary only.
- Protocol adjustment is permitted only when protocol exists as explicit
  metadata and the design matrix is full rank.
- Structurally absent Condition x Protocol cells are reported as non-estimable;
  an LMM must not be described as "solving" structural missingness.

### Multiple-comparison families

Every adjusted table stores:

- `family_id`
- `family_label`
- `family_size`
- `adjustment_method`
- `alpha`
- `p_raw`
- `p_adjusted`
- `reject_adjusted`

Required named families:

- `response_core_cells`
- `response_all_available_cells`
- `single_condition_pairwise`
- `single_roi_pairwise`
- `group_core_cells`
- `group_all_available_cells`
- `planned_contrasts`
- `omnibus_effects_strict` when the user elects to correct planned omnibus
  effects together.

Follow-up contrast provenance is explicit:

- `planned`
- `omnibus_triggered`
- `exploratory_manual`

The automatic pipeline does not run unplanned simple effects after a
nonsignificant interaction. A manually requested contrast may still run, but
is labelled `exploratory_manual` and uses its declared comparison family.

Default interpretation:

- Holm for confirmatory "at least one" claims;
- BH-FDR for explicitly exploratory discovery;
- no hidden correction within each ROI when the headline claim spans all ROIs;
- raw p-values remain exported but are not used for the plain-English headline.

### Normality and assumption handling

- Shapiro-Wilk output includes its raw p-value and, when a diagnostic family is
  declared, an adjusted p-value; it is diagnostic and never an automatic test
  switch.
- One-sample checks apply to the tested response distribution.
- Paired checks apply to paired differences.
- Group-cell checks are shown per group with sample size limits.
- RM-ANOVA reports balance, Mauchly, epsilon, and GG/HF availability.
- RM-ANOVA uses the uncorrected p-value for two-level effects or when
  sphericity is not violated, and the Greenhouse-Geisser p-value when
  sphericity is violated. If a required correction is unavailable after the
  Pingouin route fails, that effect is blocked from primary interpretation or
  clearly labelled secondary rather than silently falling back to an
  uncorrected p-value.
- LMM reports convergence, singularity, random-effects structure, residual
  normality/scale diagnostics, rows/participants used, and model warnings.
- Zero variance, tiny samples, non-finite values, and invalid confidence
  intervals produce explicit non-estimable rows rather than warnings or
  misleading infinities.

### Single-group primary methods

- Response detection:
  - one-sample t-test;
  - mean, SD, 95% mean CI, Cohen's dz;
  - declared alternative and correction family.
- Condition x ROI:
  - balanced repeated-measures ANOVA;
  - GG-corrected p-value when sphericity requires it;
  - partial eta squared;
  - clearly marked fallback limitations.
- Follow-ups:
  - paired t-tests;
  - mean-difference CI and Cohen's dz;
  - planned, omnibus-triggered, or exploratory-manual provenance;
  - correction across the declared family.

### Multi-group primary methods

- Complete-core global model:
  - `SummedBCA ~ Group * Condition * ROI`;
  - canonical group ID as the between-subject factor;
  - participant as the random-effects grouping factor;
  - sum coding for Group, Condition, and ROI;
  - REML final estimates;
  - hierarchy-preserving ML full/reduced model comparisons with these explicit
    targets:
    - `any_group_related`: `Group * Condition * ROI` versus
      `Condition * ROI`;
    - `Group:Condition:ROI`: full model versus
      `Group * Condition + Group * ROI + Condition * ROI`;
    - `Group:Condition_block`: full model versus
      `Group * ROI + Condition * ROI`;
    - `Group:ROI_block`: full model versus
      `Group * Condition + Condition * ROI`;
  - `any_group_related` is not described as a pure Group main effect;
  - an average group difference, when estimable and scientifically requested,
    is reported as an estimated marginal contrast over the declared
    Condition/ROI reference grid;
  - explicit small-sample/asymptotic LRT caveat;
  - random-intercept published-style baseline and an optional feasible
    random-slope attempt with a recorded, non-silent fallback for
    nonconvergence or singularity;
  - every random-structure attempt records requested and used structures,
    optimizer, convergence, singularity, fallback reason, and result status;
    a failed LRT remains a visible non-estimable/failed row.
- Cellwise group contrasts:
  - two-sided Welch t-test;
  - group means/SD/N;
  - mean difference and Welch CI;
  - Hedges' g with a defined sign convention;
  - global Holm correction across complete cells by default.

### Sensitivity methods

- One-sample:
  - 20% trimmed-mean test with winsorized variance;
  - Wilcoxon signed-rank with zero-method metadata;
  - deterministic participant sign-flip max-|t| across a declared cell
    family, flipping each participant's sign across their entire complete
    Condition x ROI matrix on every draw;
  - leave-one-participant-out stability summary.
- Within-subject:
  - Friedman tests for one-factor rank sensitivities when the design supports
    them.
- Between-group:
  - 20% trimmed unequal-group comparison;
  - optional deterministic studentized permutation that permutes Group labels
    at the participant level;
  - for more than two groups, max-T either spans the explicitly declared
    pairwise group contrasts or is restricted to a user-selected pair;
  - leave-one-participant-out stability summary.

Sensitivity results must not replace the primary arithmetic-mean estimand and
must be labelled with the quantity they test. Resampling output stores the
seed, requested and completed draw counts, and exact-versus-Monte-Carlo
status. It does not repair same-sample adaptive harmonic selection unless the
selection procedure itself is nested inside each resample.

### Interpretation language

Required phrases:

- significant: "The analysis found reliable evidence that..."
- nonsignificant: "The analysis did not find reliable evidence that..."
- never: "There is no effect" solely from `p >= alpha`;
- adaptive selection: "The harmonic range was selected from this sample, so
  response-versus-zero p-values are exploratory.";
- sensitivity disagreement: "The conclusion depended on the analysis method.";
- singular/non-estimable model: "This model is not suitable for a primary
  conclusion.";

## Architecture

### New GUI-neutral analysis modules

Expected ownership:

- `analysis/inference_contracts.py`
  - profiles, alternatives, family specs, provenance, result metadata;
- `analysis/design_audit.py`
  - grain validation, coverage, complete-condition cohort, group counts,
    structural-missingness and estimability inputs;
- `analysis/multiple_comparisons.py`
  - generic adjustment and named-family application;
- `analysis/diagnostics.py`
  - normality, residual, zero-variance, influence, and model diagnostic
    records;
- `analysis/robust_tests.py`
  - trimmed and rank-based sensitivity methods;
- `analysis/resampling.py`
  - participant-level sign-flip and group-label max-T methods;
- `analysis/stability.py`
  - participant-level leave-one-out sensitivity summaries;
- `analysis/sensitivity_summary.py`
  - direction-aware agreement and method-dependence language;
- `analysis/group_comparisons.py`
  - Welch contrasts, Hedges' g, CIs, group-cell diagnostics;
- `analysis/multigroup_model.py`
  - full/reduced formula construction, ML LRT blocks, REML result contract,
    random-structure attempts and estimability checks.

These modules must not import PySide6 or own workbook/project discovery.

### Existing analysis modules to extend

- `baseline_vs_zero.py`
  - consume inference/family contracts;
  - use generic correction fields;
  - preserve backward-compatible aliases where existing exports/tests require
    them;
  - harden zero-variance behavior.
- `repeated_m_anova.py`
  - retain strict balance validation;
  - expose a canonical reported-p selection field;
  - prevent an uncorrected fallback from masquerading as corrected inference.
- `posthoc_tests.py`
  - separate raw contrast construction from family adjustment;
  - correct across declared families rather than per-slice hidden families;
  - harden zero-difference/zero-variance effect sizes.
- `mixed_effects_model.py`
  - replace hard-coded term deletion with explicit nested formulas;
  - fail visibly when an omnibus comparison cannot be built;
  - retain current single-group API compatibility where practical.

Do not route new work through the older inactive ROI-specific Z-gating helper
chain in `stats_analysis.py`.

### Data and export ownership

- Continue to use `Main_App.projects.load_project_dataset_index`.
- Extend the Stats scan result with a canonical participant -> `group_id` map
  while retaining the current `participants_map` display labels and Stats-ready
  schema exactly; native inference receives the canonical-ID map separately.
- Do not infer groups from workbook folders.
- Keep the existing Stats-ready action and workbook backward compatible.
- Add analysis output workbooks/sheets rather than silently changing the
  Stats-ready interchange schema.
- Carry scientific metadata and the test inventory as explicit frames/result
  objects through the pipeline and exports; do not rely on transient
  `DataFrame.attrs` as the only source of provenance.

Expected new detailed output:

- `Analysis Design`
- `Test Inventory`
- `Response Tests`
- `RM ANOVA`
- `Single-Group Posthocs`
- `Mixed Model Estimates`
- `Mixed Model Omnibus`
- `Group Cell Contrasts`
- `Normality and Assumptions`
- `Robust Sensitivities`
- `Exclusions and Coverage`
- `Methods and Provenance`

### Worker/controller ownership

- Keep long-running statistics and export work in `QRunnable` workers.
- Capture an immutable `AnalysisRunSpec` before the first worker starts.
- Add `PipelineId.MULTI`.
- Add an explicit data-preparation/design-audit step so the Summed BCA frame,
  exclusions, and coverage are computed once per run rather than once per
  statistical method.
- Add focused multi-group step IDs rather than overloading single-group
  handlers.
- Prefer a focused `workers/multigroup_workers.py` if adding the new jobs to
  `stats_workers.py` would make it materially harder to review.
- Build the prepared long analysis frame and design audit once per pipeline
  where possible.
- Workers receive plain data/config payloads and never touch widgets.
- Progress, warnings, completion, reports, and errors flow through signals.
- Controller log section names derive from the pipeline instead of being
  hard-coded to "Single".
- Add a cancellation token checked between statistical/resampling stages.
  Cancellation is a distinct terminal state, not an analysis failure.
- Make summary/report-bundle generation an explicit pipeline step so
  "analysis complete" means the non-expert result is ready. A later optional
  file-write problem may report "analysis complete; export incomplete".

### GUI ownership

The existing Basic/Advanced flat-tab layout remains.

Basic:

- a flat `Analysis Design` card;
- project analysis mode banner: Single Group or Multi-Group;
- selected analysis profile and a short explanation;
- included conditions and complete-core coverage summary;
- primary action label changes with project mode;
- non-expert significant-results summary remains visible.

Advanced:

- harmonic/inference provenance;
- alternative and multiplicity choices;
- strict omnibus-family toggle;
- sensitivity-analysis selections;
- complete-core versus secondary available-case controls;
- technical diagnostics/report access;
- individual-step actions appropriate to the active pipeline.

Do not nest `SectionCard` inside another visible card. Reuse
`Main_App.gui.components`, `ActionRow`, `StatusBanner`, and
`SubsectionHeaderLabel`.

The result area uses a flat tab view:

- `At a glance`
- `Methods & checks`
- `Run log`

A visible status banner and phase/progress indicator sit near the run action.
Existing hidden status/log widgets may be promoted into this workflow rather
than duplicated.

### Reporting ownership

- Keep numeric/statistical engines free of prose.
- Add focused summary builders under `reporting/summary/`.
- Preserve the compatibility facade.
- Visible summary: short, significant effects or an explicit no-reliable-
  effect result, plain English, effect direction, corrected status, caveat.
- Detailed reporting summary: complete test inventory, formulae, sample sizes,
  assumptions, corrections, estimates/CIs/effect sizes, provenance and file
  paths.
- Every table/report identifies primary, sensitivity, or exploratory status.
- Convert the tool information content to the existing tabbed pattern:
  `Workflow`, `Analysis profiles`, and `How to interpret results`.

## Compatibility and Safety

- Preserve `Tools.Stats.StatsWindow`.
- Preserve existing single-group behavior where the new profile/settings do
  not intentionally change inference.
- Preserve current output filenames or add new files; do not silently rename
  established workbooks.
- Preserve current Stats-ready long/wide sheet names and columns exactly.
- Give new inferential workbooks an explicit schema version.
- Preserve current project paths and Stats results folder.
- Preserve exact harmonic math and durable cache semantics.
- Preserve current QC and manual-exclusion workflow.
- Preserve current object names where existing Qt smoke tests depend on them;
  new controls receive stable object names.
- No Qt work runs locally; pytest-qt coverage is CI-only.
- No long analysis runs on the UI thread.
- No Tkinter, PyQt, CustomTkinter, `print`, hard-coded study paths, or folder-
  inferred group membership.

## Worktree Protection

The branch began with pre-existing uncommitted changes owned by the user:

- `src/Tools/Stats/data/group_harmonic_cache.py`
- `tests/processing/test_harmonic_selection_qc.py`
- `tests/stats/data/test_group_harmonic_cache.py`

Do not stage or commit these files unless the implementation genuinely
requires an overlapping edit and the existing diff has first been isolated
and reconciled. Every phase commit must use explicit paths.

## Implementation Phases

### Phase 0 - Plan and baseline

Deliverables:

- create and switch to the feature branch;
- run the general, Stats structure, GUI import, and project-path audits;
- record scientific, architecture, compatibility, verification, and commit
  contracts in this plan;
- inventory current focused tests and current worktree changes.

Definition of done:

- [x] Feature branch exists.
- [x] GUI import audit passes.
- [x] Stats structure audit passes.
- [x] Project-path audit passes.
- [x] General agent audit passes.
- [x] Active plan reviewed against Stats engine, GUI/reporting, and
      verification architecture.
- [x] Baseline Stats focused verification passes (51 tests).
- [x] Plan committed without staging pre-existing dirty files.

Commit:

`docs(stats): add native inference overhaul execution plan`

### Phase 1 - Shared inference and design core

Deliverables:

- inference profile/provenance/family contracts;
- named multiple-comparison family helper;
- complete-design and group-coverage audit;
- generic diagnostics records and safe zero-variance handling primitives;
- canonical group-ID map exposed through the Stats scan adapter;
- immutable `AnalysisRunSpec`/prepared-design contracts that remain
  GUI-neutral;
- unit tests for contracts, families, coverage, duplicates, missingness,
  group identity, and non-estimable cases.

Definition of done:

- [x] Complete-condition intersection is deterministic and tested.
- [x] The participant cohort is frozen before condition intersection; no
      participant is silently removed to recover more conditions.
- [x] Duplicate participant x Condition x ROI cells hard-fail with a useful
      message.
- [x] Canonical group IDs come from the shared dataset index without changing
      `participants_map` display labels or the Stats-ready schema.
- [x] Holm, BH, and no-adjustment outputs match reference values.
- [x] Every adjusted row records a named family and its size.
- [x] Scientific metadata and test inventories survive explicit
      serialization without relying only on `DataFrame.attrs`.
- [x] No GUI imports exist in the new analysis modules.
- [x] `verify.py --scope stats --tier focused` passes (51 registered tests);
      33 new/direct Phase 1 tests also pass.
- [x] Plan progress is updated and committed with the implementation.

Commit:

`feat(stats): add inference contracts and design audit`

### Phase 2 - Single-group inference

Deliverables:

- configurable baseline-versus-zero alternative and correction family;
- post-selection provenance warning;
- complete-core RM-ANOVA preparation and canonical reported-p field;
- globally declared posthoc families;
- generic correction output labels with backward-compatible aliases;
- zero-variance/invalid-CI hardening;
- repaired hierarchy-preserving single-group LMM omnibus comparisons;
- focused tests and export/report compatibility coverage.

Definition of done:

- [x] Independently selected harmonic response tests default to confirmatory
      Holm; fixed-but-unverified lists do not.
- [x] Adaptive same-sample response tests are visibly marked exploratory.
- [x] The primary RM-ANOVA uses only audited complete conditions.
- [x] GG-corrected inference is selected and labelled when available/required.
- [x] A required but unavailable sphericity correction cannot silently yield
      a primary uncorrected p-value.
- [x] Posthocs do not hide separate within-ROI families for a cross-ROI claim.
- [x] Automatic posthocs are planned or omnibus-triggered; manual unplanned
      contrasts are labelled exploratory.
- [x] Holm output is never labelled BH.
- [x] `do_lrt=True` produces valid nested formulas or a visible failed-result
      row and main-table status.
- [x] Existing single-group public entry points and established exports remain
      compatible.
- [x] Focused Stats verification passes (51 registered tests); 34 direct
      Phase 2 integration tests also pass.
- [x] Plan progress is updated and committed.

Commit:

`feat(stats): harden single-group inference`

### Phase 3 - Native multi-group engines

Deliverables:

- group-cell Welch comparisons with CI and Hedges' g;
- complete-core Group x Condition x ROI mixed model;
- hierarchy-preserving Group-related omnibus tests;
- REML fixed-effect estimates and ML comparison metadata;
- random-structure/convergence/singularity reporting;
- canonical group labels plus stable IDs in detailed output;
- unit tests for unequal groups/variances, null/effect fixtures, missing cells,
  sign convention, correction family, singularity, and non-estimability.

Definition of done:

- [x] The global model includes Group, Condition, ROI, and all interactions.
- [x] Group-related omnibus tests use explicitly tested full/reduced formulas.
- [x] `any_group_related` is not reported as a pure Group main effect; an
      average Group contrast uses an explicit marginal reference grid.
- [x] Cellwise tests use Welch, are two-sided, and default to global Holm.
- [x] Hedges' g direction is documented and tested.
- [x] A missing/unknown group assignment blocks inference.
- [x] Singular/nonconverged models cannot generate a primary-success headline.
- [x] Every random-structure attempt and fallback is exported, and a failed
      LRT remains visible as a failed/non-estimable row.
- [x] Complete-core and available-case scopes are distinguishable in output;
      complete-core cell comparisons validate the retained participant-cell
      matrix instead of trusting a label.
- [x] Focused Stats verification passes (51 registered tests); 18 direct
      Phase 3 tests also pass.
- [x] Plan progress is updated and committed.

Commit:

`feat(stats): add native multigroup inference`

### Phase 4 - Robust sensitivities and diagnostics

Deliverables:

- one-sample 20% trimmed-mean and Wilcoxon tests;
- group 20% trimmed comparison;
- deterministic sign-flip max-|t| and group-label permutation helpers;
- Friedman one-factor sensitivities;
- leave-one-out stability summaries;
- normality, residual, influence, and assumption tables;
- deterministic seeds and explicit estimand/status metadata.

Definition of done:

- [x] Robust functions match frozen reference values.
- [x] Permutation/max-T results are deterministic for a fixed seed.
- [x] One-sample max-T flips participant signs across the complete cell matrix,
      and between-group permutation shuffles labels at participant level.
- [x] Resampling records seed, requested/completed draws, and
      exact-versus-Monte-Carlo status.
- [x] Same-sample harmonic selection remains flagged after fixed-matrix
      resampling; an attestation alone cannot claim nested selection.
- [x] Shapiro results never automatically replace the primary test.
- [x] Sensitivity disagreement in threshold or direction produces
      method-dependent language.
- [x] Tiny-N and all-zero inputs return explicit non-estimable records.
- [x] Focused Stats verification passes (51 registered tests); 67 direct
      Phase 4 tests also pass after two independent numerical audits.
- [x] Plan progress is updated and committed.

Commit:

`feat(stats): add robust statistical sensitivities`

### Phase 5 - Pipeline, exports, and detailed reporting

Deliverables:

- prepared-analysis payload reused across steps;
- `PipelineId.MULTI` and multi-group controller/worker orchestration;
- explicit data-preparation and report-bundle steps;
- cancellable long-running/resampling stages with a distinct cancelled state;
- additive detailed workbooks/sheets and test inventory;
- baseline, design, diagnostic, robust, omnibus, and group contrast support in
  reporting frames;
- non-expert summary rules and detailed methods report;
- export/report tests for single and multi-group runs.

Definition of done:

- [x] Single and multi pipelines run only in workers.
- [x] Pipeline log labels are not hard-coded to Single.
- [x] A full pipeline prepares the DV/design once.
- [x] Stale worker results cannot overwrite a newer run or newly opened
      project.
- [x] Cancel restores controls and does not export partial results as complete.
- [x] Partial/reporting failures do not falsify completed numeric exports.
- [x] Detailed files identify formula, N, correction, family, profile,
      provenance, estimand, CI/effect size and assumption status.
- [x] Detailed scientific metadata and the test inventory are explicit
      exported tables, not attributes attached only to data frames.
- [x] Visible summary contains no raw-p-only headline.
- [x] Nonsignificant group results are not called equivalent.
- [x] Existing Stats-ready workbook remains compatible.
- [x] Focused Stats (51 registered tests), project-I/O (71 tests), Phase 5
      pipeline/reporting (70 tests), and full reporting (31 tests)
      verification pass.
- [x] Plan progress is updated and committed.

Commit:

`feat(stats): integrate inference pipelines and reporting`

### Phase 6 - GUI and non-expert workflow

Deliverables:

- mode-aware Basic page and primary action;
- profile, scope, coverage, correction, alternative, and sensitivity controls;
- native multi-group actions replacing the export-only disabled state;
- mode-aware busy/status/error/completion behavior;
- visible analysis phase/progress and cancellable run behavior;
- flat `At a glance`, `Methods & checks`, and `Run log` result tabs;
- tool-info content explaining the methods simply;
- updated registered pytest-qt smoke definitions;
- visible/manual smoke checklist.

Definition of done:

- [x] A single-group project presents and runs the single pipeline.
- [x] A true multi-group project presents and runs the multi pipeline.
- [x] Canonical group labels and per-group N are shown before analysis.
- [x] Optional incomplete conditions are visibly excluded from the primary
      complete-core analysis.
- [x] The profile/provenance warning cannot be hidden by changing tabs.
- [x] Long work remains off the UI thread.
- [x] Visible status/progress is updated from structured worker events rather
      than inferred from free-form text.
- [x] At-a-glance language never substitutes raw p-values for available
      adjusted p-values.
- [x] Existing stable object names are preserved where required.
- [x] New pytest-qt files are registered and left for CI.
- [x] GUI import audit and focused GUI/Stats verification pass locally
      (51 registered Stats tests, 84 direct GUI-neutral integration/reporting
      tests, and the GUI audit; Qt execution remains CI-only).
- [x] Manual visible smoke path is documented.
- [x] Plan progress is updated and committed.

Commit:

`feat(stats-gui): add native multigroup analysis workflow`

### Phase 7 - Validation, documentation, and closure

Deliverables:

- known-null/effect simulations for fixed versus adaptive selection, skew,
  outliers, unequal variance, missingness, and singularity;
- golden reference outputs for SciPy/Pingouin/statsmodels and, when a stable
  reference can be stored without adding a runtime dependency, R;
- Stats architecture and user methods documentation;
- reporting checklist updates;
- final focused and precommit verification;
- `.agents/verification.toml` Stats-scope coverage updated for the new and
  currently omitted safe scientific tests;
- plan completion/closure record.

Definition of done:

- [ ] Fixed-selection null simulations show acceptable Type I behavior within
      Monte Carlo tolerance.
- [ ] Adaptive response detection is demonstrated and labelled rather than
      silently treated as confirmatory.
- [ ] Correction-family composition is covered by tests.
- [ ] All new result/export schemas have golden coverage.
- [ ] Safe baseline, RM-ANOVA, LMM, correction-family, and multigroup tests are
      present in the Stats verification registry.
- [ ] Focused scientific tests cover inference contracts, multiplicity,
      design audit, diagnostics, single- and multi-group model omnibus logic,
      group contrasts, robust methods, report export, and pipeline
      orchestration.
- [ ] `verify.py --scope stats --tier focused` passes.
- [ ] `verify.py --scope gui --tier focused` passes.
- [ ] `verify.py --scope project-io --tier focused` passes when group/export
      code changed.
- [ ] Stats structure and reporting-legibility audits pass.
- [ ] `verify.py --scope repo --tier precommit` passes or every unrelated
      failure is documented.
- [ ] CI-only Qt coverage and visible/manual smoke steps are documented.
- [ ] No pre-existing user-owned dirty file was accidentally committed.
- [ ] Architecture/user documentation matches the shipped behavior.
- [ ] This plan is marked complete and moved/handled according to repository
      plan-retention policy.

Commit:

`docs(stats): complete native inference overhaul`

## Verification Matrix

| Change | Required local gate | Additional coverage |
| --- | --- | --- |
| Analysis contracts/core | `verify.py --scope stats --tier focused` | unit reference fixtures |
| Dataset group identity/export | Stats + project-I/O focused | manifest/index fixtures |
| Reporting | Stats focused + reporting-legibility audit | workbook/text goldens |
| GUI/controller/workers | Stats + GUI focused | CI-only registered pytest-qt |
| Harmonic provenance only | Stats focused | canonical/fixed policy tests |
| Final handoff | repo precommit | visible/manual Stats workflow |

Qt execution remains CI-only. Never set `QT_QPA_PLATFORM=offscreen`.

## Manual Visible Smoke Path

To perform after Phase 6 in a safe visible Windows session:

1. Open a normal single-group project and launch Statistical Analysis.
2. Confirm Single Group mode, profile/provenance text, selected conditions,
   coverage, and primary action label.
3. Run the primary pipeline; confirm the UI remains responsive, progress/status
   changes, plain-English summary, detailed export path, and no modal loop.
4. Open a true two-group project.
5. Confirm canonical group labels/N and Multi-Group mode.
6. Include an optional incomplete condition and verify it is shown as excluded
   from the primary complete core.
7. Run the multi-group pipeline; confirm responsive UI and completion.
8. Confirm the visible summary distinguishes omnibus group effects, corrected
   cell contrasts, sensitivities, and limitations.
9. Open the detailed workbook/report and verify methods, formulae, corrections,
   assumptions, coverage, effects/CIs, and provenance.
10. Switch projects and verify no prior project state/results survive.
11. Start a long sensitivity run, cancel it, and verify controls recover and
    no partial result is labelled complete.
12. Force a model or report-export error and confirm a short actionable status
    plus technical details in Run log.

## Progress

- [x] Phase 0 - Plan and baseline
- [x] Phase 1 - Shared inference and design core
- [x] Phase 2 - Single-group inference
- [x] Phase 3 - Native multi-group engines
- [x] Phase 4 - Robust sensitivities and diagnostics
- [x] Phase 5 - Pipeline, exports, and detailed reporting
- [x] Phase 6 - GUI and non-expert workflow
- [ ] Phase 7 - Validation, documentation, and closure

## Decision Log

### 2026-07-29

- Preserve the locked harmonic-selection method; add inference provenance
  rather than changing signal quantification.
- Treat same-sample response-versus-zero inference as exploratory.
- Treat user-fixed harmonics as unverified until independent selection is
  explicitly attested; "fixed" alone is not a confirmatory guarantee.
- Use complete shared conditions for primary analyses.
- Freeze the QC-eligible cohort before finding shared conditions; never trade
  participants for a larger condition set.
- Use global Holm for the direct "any Condition x ROI pair?" group question.
- Keep Welch cell tests secondary to an omnibus Group x Condition x ROI model.
- Define Group-related omnibus tests with explicit nested formulas and reserve
  "average group difference" for an estimated marginal contrast.
- Preserve participant display labels/Stats-ready schema and pass canonical
  group IDs through a separate native-inference map.
- Keep available-case/protocol LMMs secondary and subject to estimability.
- Implement native multi-group analysis as a new Stats pipeline rather than
  coupling Stats to another tool or external script.
- Keep non-expert headlines short; place complete publication details in
  exports.
- Protect the three pre-existing dirty harmonic-cache/QC files from phase
  commits.

## Risks and Mitigations

### Adaptive harmonic selection

Risk: inflated response-versus-zero evidence.

Mitigation: provenance, exploratory label, fixed-harmonic confirmatory route,
and future nested-selection resampling boundary.

### Small sample mixed-model inference

Risk: asymptotic LRT/Wald calibration and singular random structures.

Mitigation: complete-core default, tested nested formulas, diagnostic
suppression of primary claims, sensitivity analyses, effect estimates/CIs, and
an explicit statement that the statsmodels ML LRT is asymptotic and is not a
Kenward-Roger/Satterthwaite result. Store independent R/lmerTest/emmeans
reference outputs for validation without creating an R runtime dependency.

### Structural missingness

Risk: available-case LMM appears to estimate aliased Condition/protocol effects.

Mitigation: design-rank/coverage audit and non-estimable blocking.

### Multiplicity fragmentation

Risk: within-slice corrections under-control a cross-ROI headline family.

Mitigation: named global families and family IDs on every row.

### GUI complexity

Risk: expert options overwhelm non-expert users.

Mitigation: simple mode-aware Basic page, defaults/profile explanation, and
Advanced-only technical controls.

### Runtime

Risk: permutation, robust sensitivity, and repeated mixed models are slow.

Mitigation: background workers, deterministic configurable resample counts,
progress signals, and prepared-data reuse.

### Backward compatibility

Risk: changed column names/report schemas break current callers/tests.

Mitigation: additive generic fields plus compatibility aliases and explicit
golden export tests.
