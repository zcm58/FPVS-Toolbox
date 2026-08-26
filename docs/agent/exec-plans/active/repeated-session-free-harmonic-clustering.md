# Repeated-Session Free Harmonic Clustering

## Status

Complete on branch `codex/repeated-session-fhc`.

Started 2026-08-18. This plan covers a versioned repeated-session batch beside
the frozen legacy single-contrast workflow.

## Goal

Extend Free Harmonic Clustering (FHC) to canonical repeated-session projects
without collapsing visits or treating recordings as independent. For two
ordered groups, two ordered sessions, and every selected condition, one batch
must estimate four participant-level contrast families:

1. Group A minus Group B after averaging the two sessions within each complete
   participant;
2. Visit 2 minus Visit 1 within Group A;
3. Visit 2 minus Visit 1 within Group B; and
4. Group A minus Group B in participant-level Visit 2 minus Visit 1 change.

The Birth Control project is the first real-data acceptance project. Its labels
must remain `Luteal Phase (Visit 1)` and `Follicular Phase (Visit 2)`, with the
fixed-order phase/visit/time/retest confounding stated in every human-readable
result.

## Locked Scientific Decisions

- Preserve `hermann_free_harmonic_clustering_cleanroom_v2` and its powered null
  receipt exactly for legacy `independent_groups` and `paired_conditions` runs.
- Give the repeated-session batch a separate versioned method/contract. The
  legacy calibration receipt is not evidence for the new batch workflow.
- Resolve participant, group, recording, session, visit, condition, and source
  identity only through the managed project and neutral FullFFT provenance.
- Require exactly two selected stable groups and exactly two selected sessions
  with distinct visit indices. Keep incomplete visits as audited coverage; use
  complete pairs for all four primary families.
- Honor project QC/exclusions and allow additive analysis-specific recording
  exclusions with required reasons. Never mutate `project.json` or QC state.
- Build one shared harmonic domain across every included
  group x session x condition cell, then freeze it for the whole batch.
- For the session-averaged group family, average the two candidate-SNR tensors
  within participant and L2-normalize that mean once.
- For paired-session families, L2-normalize each session tensor separately and
  sign-flip the participant Visit 2 minus Visit 1 tensors.
- For the group-by-session-change family, compare those participant Visit 2
  minus Visit 1 tensors by whole-participant group-label permutation; do not
  renormalize the difference tensor.
- Keep the existing spatial/free-harmonic graph, node-entry threshold, signed
  cluster mass, separate directional max-cluster nulls, and default 10,000
  assignments.
- A run-level two-sided global p-value is the strongest cluster's existing
  doubled two-sided max-cluster p (1 when no cluster forms). Apply Holm across
  the selected conditions within each of the four named scientific families,
  and also export conservative Holm adjustment across every batch run.
  Cross-condition corrections are run-level; cluster-specific raw p-values
  must not be relabelled as cross-condition adjusted.
- FHC concerns the normalized electrode x harmonic response distribution, not
  total Raw BCA magnitude. Cluster-level significance never establishes an
  individual node as pointwise significant.

## Non-Goals

- Do not change standard harmonic selection, Summed BCA, preprocessing, QC,
  project metadata, source workbooks, or legacy FHC calibration code.
- Do not add a general repeated-measures model builder or pretend that fixed
  phase order can be separated from visit/order/time/retest.
- Do not use or inspect `src/Standalone_Scripts/**`.
- Do not run Qt or offscreen GUI tests locally.

## Delivery Phases

### Phase 1 — Recording-Aware Preparation

- Add immutable repeated-batch requests, audit identities, prepared-run, and
  prepared-batch models.
- Stream each canonical FullFFT workbook once, validate recording/session/group
  ownership and one shared grid, and create all four tensor families.
- Select and freeze one harmonic domain for all included conditions and arms.
- Add synthetic coverage for incomplete visits, unstable identities, explicit
  exclusions, tensor construction, normalization, and legacy compatibility.

### Phase 2 — Batch Inference And Export

- Reuse the existing whole-participant permutation core for each prepared run.
- Add deterministic per-run seeds, progress/cancellation, run-global p-values,
  within-family Holm, and all-batch Holm.
- Publish one additive transactional batch containing a readable summary,
  per-run cluster/node/null details, full cohort/coverage/exclusion audit,
  shared harmonic provenance, CSV/NPZ data, and completion manifest.
- Add a headless CLI path suitable for the Birth Control acceptance run.

### Phase 3 — GUI And Documentation

- Keep the legacy one-contrast GUI unchanged for flat projects.
- For repeated projects, expose the two ordered groups, two ordered sessions,
  all-condition batch, method summary, and analysis-specific recording
  exclusions in a 1280x900-safe workflow; keep the fixed-order confounding in
  exported provenance rather than a repeated GUI warning.
- Run preparation, 16 permutation analyses, and export in one worker pipeline;
  widgets receive signals only.
- Update package/user/method docs, verification registry, and CI-only
  pytest-qt smoke definitions.

### Phase 4 — Verification And Birth Control Acceptance

- Run focused non-Qt FHC tests, audits, compilation, Ruff, diff checks, and the
  appropriate repository gate. Record any sandbox-only failures separately.
- In the managed Birth Control project, run the full four-family x four-
  condition batch with `participant-id__session-id` excluded for the user-declared
  outlier reason and all existing project QC decisions retained.
- Inspect the workbook/manifest, summarize raw and adjusted cluster results in
  manuscript style, and state sample coverage and the fixed-order limitation.
- Commit the verified branch without staging unrelated `outputs/**` artifacts.

## Verification

- `.venv\\Scripts\\python.exe -m pytest tests/free_harmonic_clustering -q`
- `.venv\\Scripts\\python.exe .agents/scripts/verify.py --scope free-harmonic-clustering --tier focused`
- `.venv\\Scripts\\python.exe .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py`
- `.venv\\Scripts\\python.exe .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py`
- `.venv\\Scripts\\python.exe .agents/scripts/verify.py --scope repo --tier precommit`
- `git diff --check`

## Baseline

- Branch started clean at `88486583` except for unrelated untracked
  `outputs/**` artifacts, which remain outside this feature.
- Baseline FHC suite: 109 passed; the only failure was the existing Windows
  managed-sandbox denial when `ProcessPoolExecutor` creates its named pipe in
  the null-calibration determinism test.
- GUI import audit passed. Project-path audit reported only eight unrelated,
  pre-existing hard-coded developer paths below untracked `outputs/rcads-*`.

## Progress

- [x] Recording-aware preparation models and canonical input inspection.
- [x] Batch inference, run-global multiplicity, atomic export, and headless CLI.
- [x] Automatic repeated-project GUI mode, batch-local reasoned recording
  exclusions, one worker pipeline, compact result table, and CI-only pytest-qt
  smoke definitions.
- [x] Scoped architecture, agent contract, user guide, reporting checklist,
  tool information, and parent repeated-session plan updated.
- [x] Integrated verification and the 10,000-assignment Birth Control
  acceptance run completed with `participant-id__session-id` excluded for the
  investigator-declared Raw BCA outlier.
- [x] The result bundle was independently reconciled across manifest, CSV,
  NPZ, and workbook artifacts. Study results are retained privately.
- [x] Commit the verified branch.

## Acceptance Record

The study-specific results, participant exclusions, and input identities are
retained in the private research archive. Public verification uses synthetic
fixtures and the documented focused tests.
