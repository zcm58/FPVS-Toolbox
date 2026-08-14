# Harmonic Selection Strategies and Post-Processing Freshness

## Status

Implementation and automated verification are complete on feature branch
`codex/harmonic-selection-strategies-plan` as of 2026-08-14. The working tree
contains the four profile engines, balanced pooling, explicit new-project/
legacy migration, neutral FullFFT provenance, Free Harmonic Clustering
decoupling, per-artifact freshness, post-selection rebuild, and the Advanced
Settings integration. Architecture and user-method documentation now reflects
those boundaries. The plan remains active for the visible supported-platform
GUI smoke and a separately powered FHC automatic-domain null-calibration study;
the latter is validation of a conditional inferential claim, not unfinished
standard Summed-BCA implementation.

Created 2026-08-14. This plan overlaps the active
`stats-standard-screening-lmm.md`, `multi-group-project-foundation.md`, and
`free-harmonic-clustering-gui.md` plans. Implementers must preserve their
participant/group identity, available-observation, inference, and tool-boundary
contracts unless this plan explicitly supersedes a harmonic-selection rule.

## Executive Outcome

Harden and extend the existing Advanced Harmonic Selection setting so a
researcher chooses a named, versioned method for selecting the common harmonic
domain and determining which baseline-corrected amplitude (BCA) harmonics are
summed. The accepted method must define one canonical Summed BCA outcome that
every standard downstream consumer uses.

The feature will also:

- replace implicit workbook-weighted pooling with an explicit balanced policy
  for new adaptive methods;
- separate harmonic-selection electrodes from mutable downstream Stats ROIs;
- preserve the existing method as a named legacy profile for reproducibility;
- keep Free Harmonic Clustering Analysis scientifically independent of the
  standard Summed-BCA choice;
- invalidate and rerun only harmonic-dependent post-processing after a method
  change, without repeating raw EEG preprocessing or FFT export; and
- record sufficient method, cohort, weighting, and artifact provenance for
  exact reporting and stale-output detection.

This feature changes a locked statistical-method contract. Its implementation
PR must explicitly update the applicable `AGENTS.md`, architecture, user
methods, and focused contract tests.

## Current Problems

The current Settings surface already offers through-highest with the gap guard,
significant-only summation, a fixed harmonic list, and ROI-union versus
all-scalp electrode scope. These are real implemented behaviors, not a new UI
to recreate. They currently sit inside a shared policy shape that combines
strict local `z > 1.64` detections, equal weighting of every available
participant-condition workbook, and mutable settings/caching dependencies.
The default through-highest behavior also applies a one-time custom
greater-than-10-intervening-harmonic gap guard. This is a reproducible Toolbox
policy, but it is not a faithful profile of every published FPVS selection
method.

Consequences include:

- participants, conditions, and groups receive implicit unequal weight in an
  unbalanced project;
- mutable analysis ROIs can change the common selected harmonic set;
- a distant detection can admit otherwise weak intermediate harmonics into
  Summed BCA;
- the custom gap guard lacks a direct publication counterpart; and
- manually recalculating harmonics can leave derived workbooks and analyses
  based on the preceding selection.

Original participant-condition workbooks already retain all configured BCA
harmonics and the FullFFT spectrum. These source exports are sufficient to
reselect and re-sum BCA without rerunning preprocessing.

## Locked Product and Scientific Decisions

### Project-specific advanced setting

- The choice is scientific project state, even though it is edited through
  the Settings menu. Persist it in a processing-owned project namespace, not
  as an app-global preference or only in a Stats cache.
- Present named method profiles rather than unrestricted combinations of
  thresholds, stopping rules, and summation switches.
- Existing projects migrate to the exact current behavior and retain their
  numerical results until the user explicitly chooses another profile.
- Every profile has a stable ID, method version, human-readable citation or
  rationale, parameters, and reporting text.
- The GUI must call the concept `Harmonic Selection and Summation`; not every
  included harmonic is individually significant.
- A changed profile or parameter requires confirmation, saves an audit entry,
  marks dependent outputs stale, and offers immediate post-processing rebuild.

### Initial method profiles

1. **Legacy FPVS Toolbox** preserves the current threshold, electrode scope,
   workbook pooling, fill, gap guard, and output values for reproducibility.
2. **Fixed/preregistered domain** accepts an a-priori exact eligible harmonic
   list or upper harmonic/frequency, always applies dynamic base-rate-overlap
   exclusions, and is the preferred confirmatory profile. Base-overlap
   exclusion is a locked rule rather than a user-selectable option.
3. **Significant-only exploratory** preserves the existing option to include
   only locally threshold-passing harmonics from a bounded common search
   domain. It must report the same-sample post-selection limitation and must
   not be described as confirmatory merely because it excludes internal
   failures.
4. **Two-consecutive-failures literature profile** implements the quoted
   Dzhelyova/Poncet logic: build a grand spectrum separately by condition,
   calculate local Z-scores, average condition Z-scores equally, stop after
   two consecutive eligible harmonics fail the configured threshold, and sum
   the eligible common range through the resulting cutoff.
5. **Corrected adaptive profile** remains gated until its across-harmonic
   maximum-statistic or equivalent calibration, search band, missing-cell
   behavior, and simulations are approved. It must not be presented as a
   literature replication merely because it uses a familiar Z threshold.

Do not remove or retune the custom gap guard in isolation. Retire it from the
recommended path only after the replacement profiles exist; keep it inside
the versioned legacy profile.

The implementation branch must decide, with recorded rationale, which
non-legacy profile is the default for newly created projects. It must not
silently change the default for existing projects.

### Canonical selection and summation result

Every profile returns one immutable result containing at least:

- evaluated, detected, included, and base-overlap-excluded harmonic orders
  and exact frequency columns;
- stopping/cutoff reason and threshold details;
- selection electrode mask;
- group, condition, participant, and workbook coverage;
- stable canonical group IDs, with any human-readable labels kept separately;
- pooling cell sample sizes and explicit weights;
- source FullFFT/workbook fingerprints;
- method ID/version and same-sample versus independent/fixed provenance; and
- one canonical selection fingerprint.

The accepted active/history record lives under
`tools.processing.harmonic_selection` in `project.json`. A matching Stats cache
may accelerate calculation, but it is not authoritative for downstream tools.

`detected_harmonics` and `included_harmonics` are different concepts.
Downstream Summed BCA must sum the exact canonical included BCA columns and
must never independently refill, truncate, or reselect them. One common
included set applies to all participants, groups, conditions, electrodes, and
ROIs in a standard analysis so comparisons retain the same dependent-variable
definition. Signed BCA values and existing BCA/SNR formulas remain unchanged.

### Balanced pooling for adaptive profiles

- Average participants within every declared group x condition cell.
- Use canonical manifest `group_id` values for assignment, cell keys, cache
  identity, and weighting. A separate display label may be duplicated and
  cannot merge two groups.
- For a common multi-group selector, give groups equal explicit weight within
  each condition unless a separately named population-weighted estimand is
  later approved.
- Calculate condition-specific grand-spectrum Z-scores and give declared
  conditions equal weight when combining them.
- Export cell sample sizes, assigned weights, exclusions, and omissions.
- Never silently renormalize across an entirely missing declared group x
  condition cell. Block adaptive selection with a clear remedy, normally a
  fixed/preregistered profile or a completed dataset.
- Preserve the old equal-workbook weighting only inside the legacy profile.

Equal group weighting prevents the larger group from defining the shared
outcome, but gives each member of a smaller group more influence. Documentation
must describe this as an explicit estimand choice rather than a universally
superior weighting scheme.

### Selection electrode scope

- Separate the harmonic-selection mask from downstream Stats ROIs.
- Default new non-legacy profiles to all retained scalp EEG electrodes, while
  permitting a frozen a-priori selection mask for focal paradigms.
- Store the exact mask with project method state and selection provenance.
- Keep the current dynamic ROI-union behavior only in the legacy profile.
- Changing downstream ROIs must not invalidate an all-scalp or frozen-mask
  selection.

### Free Harmonic Clustering boundary

Free Harmonic Clustering Analysis remains a sibling inferential workflow. It
reads original `FullFFT Amplitude (uV)` sheets, constructs the participant x
sensor x harmonic tensor, and owns its Hermann automatic or fixed-ceiling
harmonic domain. Standard selection profiles, included harmonic lists, and
Summed BCA exports must never configure its numerical preparation.

The numerical independence is retained by a neutral, processing-owned FullFFT
provenance record containing project-relative source identity, grid/resolution,
stimulation rates, processing/export method fingerprint, cohort/QC revision,
and freshness state. The full post-processing pipeline writes this record
immediately after accepted frequency-domain QC and before harmonic selection,
Stats-ready/full-audit export, or source maps. GUI inspection and direct
API/CLI preparation apply the same validator; neither reads
`tools.stats.group_significant_harmonics_cache` as a fallback.

A standard Summed-BCA method change must not stale FullFFT or block Free
Harmonic Clustering. A FullFFT, cohort, frequency-QC, or relevant stimulation
change must invalidate the clustering preparation as appropriate.

Cluster permutation is a strong cluster-level multiplicity-control procedure
when whole-participant assignments are exchangeable. Documentation must still
state that its validity and sensitivity depend on the candidate domain,
adjacency, cluster-entry threshold, and contrast family; it favors spatially or
harmonically extended effects, does not confer pointwise sensor/harmonic
significance, and does not correct a collection of separately run contrasts.
The clean-room spatial graph also remains Hermann-compatible rather than an
author-validated numerical copy. Because the automatic observed-data ceiling
is chosen before and then held fixed during permutation, the implementation
branch must also run end-to-end null simulations that repeat selection and
permutation together; conditional cluster correction alone must not be used to
claim unconditional error control for that adaptive workflow.

### Post-processing freshness and rebuild

- Retain immutable preprocessing/FFT workbooks as the upstream source. A
  harmonic-method change never requests BDF loading, filtering, epoching, or
  FFT recomputation.
- Compare the old and new canonical selection fingerprints after successful
  recalculation. Identical results do not invalidate derivatives.
- When the fingerprint changes, mark every harmonic-dependent artifact
  `stale` before rebuilding. Use per-artifact `current/stale/failed` state
  rather than only one global Boolean.
- Record the selection fingerprint in Stats-ready, full-audit, maps, and every
  other canonical Summed-BCA derivative. Validate it whenever an existing
  artifact is loaded.
- Track the two canonical workbooks and both Hauk source-PSD map directories:
  Stats-ready, full-audit, L2-MNE, and eLORETA. The accepted-selection summary
  has its own current audit record.
- Reuse the normal post-processing orchestration from harmonic selection
  onward. Automatically rebuild inexpensive fixed-path canonical workbooks;
  queue or offer Resume Post-processing for expensive optional derivatives.
- Publish replacements atomically. A failed rebuild retains the preceding
  reproducible file, labels it stale, and never clears the artifact's stale
  state.
- Preserve historical user-run reports and figures with their original method
  fingerprint. Do not silently overwrite them; identify them as based on an
  earlier harmonic definition and require an explicit rerun for new inference.

## Non-Goals

- Do not change preprocessing order, FFT cropping, FFT amplitude, local-noise,
  BCA, or SNR formulas in this feature.
- Do not remove all-harmonic or FullFFT source data from participant-condition
  workbooks.
- Do not make Free Harmonic Clustering consume standard selected harmonics or
  Stats-ready Summed BCA.
- Do not claim that any one profile is universally correct or that a
  preliminary local Z threshold is across-harmonic familywise correction.
- Do not permit condition-, group-, or ROI-specific Summed BCA definitions in
  the same standard comparative analysis.
- Do not change the intentional metric-specific aggregation behavior covered
  by issue 10.
- Do not run long recalculation or export work on the GUI thread.
- Do not run local offscreen Qt workflows.

## Implementation Phases

### Phase 0 - Scientific specification and frozen baselines

#### Work

- Finalize profile names, parameters, default for new projects, exact
  two-failure boundary behavior, and missing-cell policy.
- Define the balanced multi-group/condition estimand and a simulation plan for
  any corrected adaptive profile.
- Capture balanced, unbalanced, base-overlap, distant-peak, missing-cell,
  significant-only, and fixed-list numerical fixtures from the current
  implementation.
- Record the existing project schema, cache identity, output consumers, and
  post-processing dependency graph.

#### Definition of Done

- [x] The legacy fixture reproduces current selections and Summed BCA exactly.
- [x] Every proposed profile has an unambiguous algorithm and reporting text.
- [x] The default for new projects is explicitly approved.
- [x] No implemented profile retains unresolved scientific semantics.

### Phase 1 - Neutral FullFFT provenance and clustering independence

#### Work

- Add a processing-owned, project-local FullFFT provenance record sourced from
  the canonical `ProjectDatasetIndex` and active project root.
- Validate the selected cohort and grids consistently in Free Harmonic
  Clustering GUI, API, and CLI paths.
- Remove the runtime requirement for the standard Stats harmonic cache, with a
  one-time compatibility path that requests post-processing rebuild when
  neutral provenance is absent.
- Separate FullFFT-input freshness from Summed-BCA-derivative freshness.
- Add an end-to-end null-simulation harness for the complete automatic FHC
  selection-plus-permutation pipeline, with its acceptance envelope declared
  before results are inspected.

#### Definition of Done

- [x] Changing every standard profile/selection leaves clustering candidates,
      prepared tensors, and scientific result fingerprint unchanged.
- [x] A valid FullFFT provenance record permits clustering when the old Stats
      selection cache is absent.
- [x] Stale Summed BCA alone does not block clustering; stale FullFFT does.
- [x] GUI inspection and direct preparation enforce the same provenance.
- [ ] Empirical null error is reported for the complete automatic workflow;
      any failure of the prespecified envelope changes the default or its
      confirmatory interpretation rather than being hidden.

### Phase 2 - Policy model, persistence, and migration

#### Work

- Add GUI-neutral, versioned method specifications and canonical result
  models under a processing-owned import surface.
- Persist project-specific selection/summation settings and change history.
- Migrate existing projects to the exact legacy profile without changing
  outputs.
- Include method, cohort, electrode mask, pooling, source, and software
  versions in the cache key and exported provenance.

#### Definition of Done

- [x] Existing projects load with the legacy profile and unchanged values.
- [x] Copied projects rebase all recorded source paths beneath the new active
      project root.
- [x] Unknown/newer method versions fail safely with a migration message.
- [x] A failed settings save or a cancelled/failed FFT-grid review before the
      harmonic worker starts restores the preceding saved project/app settings
      and leaves current artifacts unchanged.
- [x] After the worker starts, a partial rebuild failure restores any preceding
      reproducible artifact but records it stale/failed for the required
      fingerprint; no all-or-nothing scientific-state rollback is claimed.

### Phase 3 - Selection engines and balanced pooling

#### Work

- Isolate profile implementations behind one canonical selection API.
- Refactor the existing fixed, significant-only, and through-highest behaviors
  into versioned profiles, then implement the two-consecutive-failure profile.
- Implement equal group x condition cell pooling and fixed electrode masks.
- Retain current calculations only in the legacy implementation.
- Calibrate and approve the corrected adaptive profile before exposing it.

#### Definition of Done

- [x] Published-profile fixtures recover their expected stopping and included
      harmonics, including base-rate overlaps and internal failures.
- [x] Unbalanced synthetic projects recover the declared equal-cell result and
      export exact sample sizes and weights.
- [x] Reordering workbook discovery cannot change a selection.
- [x] Missing declared cells block rather than silently changing weights.
- [x] All profiles return the same canonical result schema.

### Phase 4 - Canonical Summed BCA consumers and artifact freshness

#### Work

- Make Stats-ready, full-audit, maps, reports, and other standard consumers use
  only the canonical included harmonic columns and fingerprint.
- Add per-artifact dependency/freshness records to project metadata.
- On a changed method, mark derivatives stale and resume the existing
  post-processing pipeline after FFT generation.
- Make canonical replacements atomic and retain stale historical artifacts for
  audit.

#### Definition of Done

- [x] Every standard consumer receives identical included harmonic semantics.
- [x] No consumer recalculates or silently modifies the selected list.
- [x] A changed method rebuilds Summed BCA derivatives without reading raw EEG.
- [x] Partial rebuild failure cannot present an old artifact as current or
      destroy its last reproducible version.
- [x] Statistics cannot silently run from a stale canonical workbook.

### Phase 5 - Advanced Settings GUI and worker orchestration

#### Work

- Refactor the existing flat Advanced harmonic section into
  `Harmonic Selection and Summation` using shared PySide6 components; do not
  add a duplicate settings surface.
- Show method summary, citations/rationale, current electrode scope, pooling
  policy, same-sample warning, current fingerprint, and derivative freshness.
- Add non-blocking recalculate/rebuild progress, confirmation, cancellable
  pre-start FFT-grid/exclusion review, a close guard once the worker starts,
  and actionable failure states. In-flight harmonic selection/publication is
  not cooperatively cancellable in this version.
- Route long selection and export work through workers and signals.

#### Definition of Done

- [x] A user can inspect and change the project method without editing files.
- [x] The UI distinguishes detections from harmonics actually included in BCA.
- [x] Cancelling the pre-start FFT-grid/exclusion review leaves project/app
      settings and current artifacts unchanged; once the worker starts,
      Settings stays open until it finishes.
- [x] Changed settings visibly require/recommend post-processing rebuild.
- [x] Project switching cannot retain another project's method or worker state.

### Phase 6 - Documentation, reporting, and release validation

#### Work

- Update architecture, scoped agent contracts, user methods, Statistics help,
  Free Harmonic Clustering help, and reporting checklists.
- Document each profile, weighting estimand, electrode scope, adaptive
  selection limitation, method-change history, and FHC independence.
- Add reporting templates that state detected versus included harmonics and
  whether the range was fixed, literature-adaptive, corrected-adaptive, or
  legacy.
- Run focused processing, Stats, project-I/O, GUI-static, and clustering gates,
  then the repository precommit gate.

#### Definition of Done

- [x] GUI, workbooks, reports, user docs, and method fingerprints agree.
- [x] Existing-project legacy reproduction and new-profile tests pass.
- [ ] The visible manual smoke path passes on a supported platform.
- [x] Architecture and nearest scoped `AGENTS.md` files describe final
      ownership and dependency boundaries.

## Required Documentation Updates

Implementation must update at least:

- `AGENTS.md` locked harmonic-method contract;
- `docs/agent/architecture/post-processing-export-contract.md`;
- `docs/agent/architecture/statistics-tools.md`;
- `docs/agent/architecture/project-io.md`;
- `docs/agent/architecture/workers-threading.md`;
- `docs/agent/architecture/gui.md`;
- `src/Tools/Free_Harmonic_Clustering/AGENTS.md` and `ARCHITECTURE.md`;
- `docs/user/reference/methods-reporting-checklist.md`;
- `docs/user/tools/statistics.md`; and
- `docs/user/tools/free-harmonic-clustering.md`.

Update `ARCHITECTURE.md` if the implementation introduces the planned neutral
processing-owned policy/provenance owner as a new durable boundary.

## Verification

Use the repository-selected `.venv1` or `.venv` and add focused numerical tests
for every profile before GUI work. Planned gates are:

```console
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/scripts/audit/agent_audit.py --check stats-structure
python .agents/scripts/verify.py --scope project-io --tier focused
python .agents/scripts/verify.py --scope processing --tier focused
python .agents/scripts/verify.py --scope stats --tier focused
python .agents/scripts/verify.py --scope free-harmonic-clustering --tier focused
python .agents/scripts/verify.py --scope repo --tier precommit
```

Qt smoke definitions execute in CI. Do not use offscreen Qt locally.

## Visible Manual Smoke Path

Run in a normal visible supported Windows 11 or CachyOS session:

1. Open an existing project and confirm it reports the legacy method and
   reproduces its preceding selected/included harmonics and Summed BCA.
2. Switch to a fixed profile, cancel once, and confirm neither settings nor
   artifacts change.
3. Apply the fixed profile and confirm only harmonic-dependent outputs become
   stale, then rebuild them without preprocessing.
4. Apply the two-consecutive-failure profile and review its condition Z-scores,
   stopping reason, included harmonics, cell weights, and electrode mask.
5. Open an unbalanced two-group project and confirm equal group x condition
   weighting plus explicit cell sample sizes.
6. Run Standard FPVS Screening and another Summed-BCA consumer and confirm they
   report the same method fingerprint and included harmonics.
7. Change the standard profile, then prepare the same Free Harmonic Clustering
   contrast and confirm its own selected domain and tensors do not change.
8. Corrupt or stale FullFFT provenance and confirm clustering blocks with a
   rebuild instruction while stale Summed BCA alone does not block it.
9. Confirm pre-start review cancellation restores the saved settings, Settings
   cannot close after the worker starts, project switching remains guarded,
   and repeated rebuilds plus a simulated export failure retain the last
   reproducible artifact.

## Residual Risks

- More user-selectable methods increase researcher degrees of freedom. Method
  changes must be auditable, reportable, and visibly discouraged after results
  have been inspected; fixed/preregistered selection remains the strongest
  confirmatory option.
- Literature profiles reproduce published conventions but do not turn their
  preliminary per-harmonic Z screens into formal across-harmonic inference.
- Equal cell weighting and participant-weighted pooling estimate different
  targets; neither is universally correct.
- A broad fixed or automatically selected clustering domain can reduce power
  by enlarging the maximum-cluster null family.
- The Free Harmonic Clustering spatial graph and independent-group extension
  retain their existing clean-room validation limitations.
- Historical outputs remain scientifically reproducible only when their saved
  method fingerprint and source provenance are retained with them.

## Progress Log

- 2026-08-14: Executive plan approved and promoted directly to the active plans
  directory. Repository behavior was reviewed read-only; no runtime method was
  changed. Free Harmonic Clustering was confirmed to read FullFFT and select
  harmonics independently of Standard Summed BCA, with one Stats-cache
  provenance coupling scheduled for removal in Phase 1. The project-path audit
  passed before this plan was added.
- 2026-08-14: The user authorized execution. Implementation began on
  `codex/harmonic-selection-strategies-plan` with the existing worktree changes
  preserved. Initial project-path, GUI-import, retired-boundary, and
  source-localization audits passed.
- 2026-08-14: Implemented four v1 profile engines. Missing/unversioned existing
  projects resolve to exact Legacy behavior; new project creation explicitly
  persists the Dzhelyova/Poncet two-consecutive-failures profile with all-scalp
  selection. Non-legacy adaptive profiles use participant-within-cell, equal-
  group-within-condition, condition-local-Z, equal-condition pooling and block
  on an entirely missing declared group x condition cell. The literature stop
  now hard-fails when the configured ceiling ends before two eligible failures.
- 2026-08-14: Added canonical scientific selection fingerprints and project-
  local current/stale/failed records for Stats-ready, full-audit, L2-MNE Hauk
  source-PSD map, and eLORETA Hauk source-PSD map derivatives.
  Harmonic recalculation can resume post-processing from accepted selection
  metadata without raw EEG preprocessing or FFT export; replacement archives
  and rollback preserve the preceding reproducible artifact on failure.
- 2026-08-14: Replaced Free Harmonic Clustering's operational dependency on the
  Stats harmonic cache with processing-owned neutral FullFFT provenance shared
  by GUI inspection and direct preparation. The full pipeline now publishes
  that neutral record immediately after accepted frequency-domain QC and before
  harmonic selection or its derivatives. Standard Summed-BCA selection
  freshness is outside that record. Added a deterministic 24-replicate
  automatic-selection-plus-permutation null smoke envelope, explicitly scoped
  as regression coverage rather than calibrated unconditional FWER validation.
- 2026-08-14: Updated root/scoped agent contracts, architecture, Statistics and
  Free Harmonic Clustering help, and the methods-reporting checklist for profile
  algorithms, balanced estimand, masks, stopping failure, detected-versus-
  included provenance, derivative freshness, rerun behavior, and conditional
  cluster-inference limitations. Existing harmonic-specific RMS-normalization
  documentation edits were preserved and merged. `mkdocs build --strict`,
  `git diff --check`, and the complete agent audit passed for this documentation
  checkpoint.
- 2026-08-14: Reconciled the plan and documentation with the completed
  implementation details: fixed-profile base-overlap exclusion is mandatory;
  selection freshness tracks Stats-ready, full-audit, L2-MNE, and eLORETA
  derivatives; canonical group IDs remain distinct from display labels;
  neutral FullFFT provenance is published after accepted frequency QC and
  before selection; and Settings rollback is limited to failures/cancellation
  before a replacement selection is persisted; starting the worker alone does
  not stale the preceding derivatives. Settings and shell navigation stay
  locked through the grid-to-selection handoff. Accepted participant-condition
  exclusions refresh frequency QC and neutral FullFFT provenance through the
  post-processing-only resume path. The strict MkDocs build and
  `git diff --check` passed; Git reported line-ending conversion warnings only.
  Formal FHC null calibration and the visible supported-platform GUI smoke
  remain open.
- 2026-08-14: Final focused gates passed for Stats (382), processing (357 with
  one skip), project I/O (70), Free Harmonic Clustering (80), and LORETA (278).
  The repository precommit gate then passed with 1,579 tests and 3 skips, along
  with Ruff, compilation, strict MkDocs, and the complete agent audit. No
  supported-platform visible/manual GUI smoke was performed in this session.
