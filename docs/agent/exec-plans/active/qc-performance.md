# QC Performance: Exact Numerical Reuse

Baseline: `ffebf3ab`. Scope: pre-processing QC steps 1–7 and reuse of their
prepared signal during final processing. Existing settings-dialog edits are
outside this task.

## Implementation

- [x] Reuse numerical QC by recording and exact condition occurrence; unrelated
  participant decisions must not invalidate unchanged results.
- [x] Cache float64 kurtosis preparation/evidence and resume final processing
  at the existing interpolation boundary with current decisions.
- [x] Reuse verified source events, skip unchanged post-review rescans, and
  separately time reading, metrics, FFT work, and worker waits.
- [x] Batch window metrics where exact equivalence is demonstrated; retain
  original calculations for unsupported/nonfinite/precision-sensitive inputs.

## Required Verification

Compare the optimized and pre-change implementations on the same float64 samples,
including nonfinite values, signed zeros, strided arrays, partial windows, and
threshold boundaries. Require equal metrics, flags, evidence, trigger samples,
and final processed arrays. Cache checks cover unchanged reuse, source/settings/
scope/geometry changes, corruption, current review authority, and cancellation.
Maintain the locked preprocessing order and exact analyzed intervals. All caches
remain within the active project; incomplete entries must never be accepted.

Run focused processing and GUI checks, then the repository precommit gate. Qt
execution remains CI-only locally. Visible smoke: run QC twice on an unchanged
project; change one condition exclusion; switch automatic kurtosis on/off; verify
only affected evidence is recomputed and processing still follows current choices.
Record measured synthetic timings separately from numerical parity and do not
present them as a measured speedup of the user's full dataset.

## Verification Result (2026-09-05)

Completed all four items. Direct comparisons against `ffebf3ab` preserved exact
float bits for preflight metrics/flags and cold/warm processed samples (including
stim), MNE metadata, kurtosis evidence/decisions, and analyzed spans. The probe
covered real MNE filtering/resampling on deterministic synthetic recordings;
the user's complete BDF dataset was not rerun.

Processing gate: **1,073 passed, 1 skipped**. Final non-Qt workflow checks:
**9 passed**, including changed marker decisions requiring project-wide refresh.
Focused GUI/lint/compile checks passed. Repository precommit remains blocked
only by eight pre-existing hardcoded paths in unrelated untracked `outputs/`.
Visible Qt smoke remains manual/CI as required by repository policy.

Synthetic paired metric benchmark: median 12.533 ms before versus 11.039 ms after
(about 12% faster for that component). Cache hits avoid repeated evidence and
preparation work; no full-dataset wall-clock speedup is claimed. Full BDF loading
and current decision validation still run before final processing cache handoff.
