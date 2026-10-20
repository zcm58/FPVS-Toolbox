# Modular processing methods

## Scope and fixed decisions

The maintainer requests executable modules for each processing step so later
methods can replace implementations within their own step. This pass adds the
foundation and per-project selection contract, not new scientific algorithms.
Work continues on the existing multi-hardware development checkout and preserves
its uncommitted changes.

- Keep the current fixed order, default numerical operations, parameter meanings,
  event grid, output formats and legacy fingerprints.
- Persist versioned method IDs in optional `processing_pipeline` project settings.
  Missing settings resolve current methods; explicit current methods have the
  same scientific identity. Unknown versions/methods/steps fail before processing.
- Use actual callable dispatch per scientific step. Registry entries belong to
  application code; project data cannot import executable code.
- Cover raw screening, reference/removal/selection, filters, resampling, bad
  channel screening/interpolation/reference/condition repairs, epochs, repetition
  averaging, FFT, SNR/target metrics and occurrence aggregation.
- Keep acquisition, mandatory geometry/timing validation, review authority,
  cancellation, resource ownership and atomic export outside swappable methods.
  Cohort Stats/harmonic selection stays independently locked.
- Keep prepared-checkpoint and condition-local branch behavior. Review preparation
  and final execution must resolve the same methods and identities.
- Keep existing GUI controls while each slot has one qualified method. Do not
  add single-option selectors or explanatory UI clutter. Carry selections through
  drafts, saves and worker snapshots for future selectors.

## Work

- [x] Add immutable method catalog, fixed-slot plan and executable dispatch.
- [x] Extract preprocessing methods and preserve review/repair branches.
- [x] Route epoch and spectral operations through the same plan contract.
- [x] Persist settings atomically; bind changed plans to caches and provenance.
- [x] Preserve all acquisition settings in GUI-to-worker snapshots.
- [x] Run focused replacement/identity/checkpoint/repair/multi-hardware tests.
- [x] Repeat synthetic default equivalence and update architecture/agent docs.

Use repo-local boundary, path and GUI audits, focused non-GUI tests, strict docs
and a quick synthetic comparison. Do not run a repository-wide scientific suite
or local Qt/offscreen workflows. Visible follow-up: save/cancel project settings,
reopen/restart and process a supported recording with current methods unchanged.

## Validation and remaining acceptance

The implementation pass is complete. Alternative algorithms and their compact
GUI selectors remain a future pass; current controls are retained. Visible
Settings Save/Cancel/reopen and processing acceptance remain manual/CI work.
No local Qt or repository-wide scientific test suite was run.

- The final `pipeline-methods` focused gate passed **223 tests in 50.58 s**,
  exercising executable replacement methods,
  invalid selections, capability and output contracts, default fingerprints,
  project transactions, cache invalidation, prepared checkpoints, condition
  repair branches, source exports and all current hardware fixture routes.
- The safe GUI gate passed 676 non-Qt tests. The project/settings, processing
  ledger and condition-repair regressions also passed; these bundles overlap.
- Agent invariant audits, Ruff, compilation, strict documentation build, relative
  links/owners and Mermaid synchronization passed.
- [The five-participant receipt](../../../../scripts/manual_diagnostics/receipts/modular_pipeline_equivalence_20261019.json)
  compares the modular working tree against native-reader baseline
  `da14edaaa5c5710b026ea1e39acb363a4793ca8c`, with optional QC off:
  35 files, 415 arrays and 5,375,645 numerical values; maximum difference **0**;
  30 files byte-identical. Remaining differences are permitted provenance.
  Source signal/event/channel snapshots also agree.
- Observed totals: old processing **23.2214 s**, modular processing **23.2975 s**;
  BDF-to-BIDS conversion **0.7543 s**, full import preparation **1.3452 s**.
  These are one synthetic comparison's timings, not a performance benchmark or
  physical hardware qualification. QC/interpolation behavior is covered by the
  focused tests rather than the QC-disabled numerical comparison.

Integration review fixed mixed-method source-derivative merges and equivalent
default condition-repair identities. Replacement cancellation retains typed
cancel signals. Replacement occurrence aggregation receives original values;
the default keeps its historical reduction/memory path. Condition repair
replacements cannot broaden approved spans or rewrite authoritative provenance.
