# QC Performance: Exact Numerical Reuse

## Native Result I/O Follow-up (2026-09-07)

Scope: reduce SNR source capture reloads, retain exact Excel export cells with
less formatting/disk work, and replace new standard condition XLSX anchors
with small `.fpvs` manifests pointing to the unchanged uncompressed NumPy
companions. Keep old XLSX inputs readable and long/wide Excel reports intact.

- [x] Reuse SNR payloads inside fresh capture scopes; retain independent
  before/after integrity checks and snapshot immutability.
- [x] Streamline report formatting and intermediate writes, retaining writer
  serialization, numeric readback bits, formatting, and scientific operations.
- [x] Publish native manifests atomically and integrate discovery, expected
  paths, receipts, cleanup, and every downstream numerical reader.
- [x] Verify legacy/native exact parity, changed/corrupt/missing inputs,
  failed replacement, mixed projects, and focused processing/tool scopes.

No raw data or user project outputs are migrated in place. Visible smoke after
restart: process a small project, complete post-processing QC, open SNR/scalp
maps/ratio/Stats with the same choices, and inspect long/wide Excel exports.
Repeat with an old XLSX project and a project containing both generations.

Verification: processing scope **1,308 passed, 5 skipped**, Stats scope **430
passed**, GUI static scope **116 passed**, and project-I/O registry **173
passed**. Additional native receipt/frequency-review/missing-sheet checks
passed **53 tests**; downstream SNR/scalp/FHC/LORETA adapters passed **78**.
Exact array bits, portable manifests, original Excel numeric readback/styles,
fresh integrity boundaries, sibling cleanup, and legacy reuse are covered.
Ruff and compilation pass for changed Python files. No local Qt, full user
dataset run, or project-output migration was performed. The project-I/O and
repository precommit drivers still stop at the eight existing path findings
in unrelated untracked `outputs/`; applicable tests were run directly.
Commands: `python .agents/scripts/verify.py --scope processing --tier focused`,
`--scope stats --tier focused`, and `--scope gui --tier focused` passed;
`--scope project-io --tier focused` and `--scope repo --tier precommit` report
that existing path-audit failure. Residual verification is the visible smoke
above; backend parity does not replace a full interactive project run.

Synthetic paired component medians, not whole-run speed estimates: SNR capture
182.461 -> 139.843 ms; 12,000 x 10 full-audit Excel export 1.9208 -> 1.3438 s;
64-channel condition publication with FullFFT/FullSNR 142.756 -> 83.158 ms.
Native and XLSX anchors produced identical NumPy companion bytes/descriptors.

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

## Cache Maintenance Follow-up

- [x] Remove older QC entries only after a complete replacement for the same
  recording/event/occurrence is published; retain unrelated and unreplaced work.
- [x] Add Advanced settings cache inspection/clearing for known disposable
  project/app caches, with background workers and current-work guards.
- [x] Preserve recordings, analysis companions/exports, project settings,
  review decisions, processing ledgers, and downloaded anatomical dependencies.
- [x] Verify failed writes/cancellation, concurrent writers, replaced inputs,
  path redirection, partial deletion failures, and GUI wiring without local Qt.

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

Cache maintenance verification: **1,128 processing tests passed, 5 skipped**;
**52 non-Qt GUI checks passed**. Cache deletion/repopulation, locked predecessor
retry, failed publication, source changes, redirects, and cache-only manifest
updates are covered. The concurrency test now coordinates initial work with
barriers instead of assuming filesystem work finishes inside a 30-ms sleep;
the same concurrency limits remain asserted. Lint/compile/diff checks passed.
The broad gate still reports only the eight unrelated `outputs/` path findings.
Four cache-dialog Qt tests are registered for CI. No user caches were cleared.
See [cache ownership and visible smoke](../../architecture/cache-maintenance.md).

## Downstream Freshness Follow-up (2026-09-06)

Compared the active paths with `codex/v3-release` at `f586652e`.
The existing preprocessed FIF cache rounds filter header metadata to float32:
`0.1` becomes `0.10000000149011612`. The newer strict spectral-eligibility gate
correctly rejects that discrepancy, aborting exports at the first condition.
The cache now preserves verified exact metadata at its boundary; the scientific
validator, samples, filtering order, and FFT calculations remain unchanged.

The completion path also inherited a v3 bug that reported an entirely failed
batch as successful. It now reports failure while preserving intentional exclusions.
Read-only probes found stable workbook/NumPy identities across repeated reads;
regressions also cover completion timestamp refresh and SNR settings saved from
a GUI project object that predates the worker's completion. An all-reused EEG
run still follows v3's no-op behavior; pending downstream work uses Resume
Post-Processing or the existing tool rebuild prompt.

Visible smoke (manual/CI): process with the 0.1-Hz high-pass setting, repeat using
the preprocessed cache, complete QC and post-processing, then open and reopen SNR.
Both exports must pass the same eligibility gate without a new stale warning.
An entirely failed batch must not report successful completion. User recordings
and project outputs were inspected read-only during this audit, not reprocessed.

Verification: processing gate **1,145 passed, 5 skipped**; GUI non-Qt gate
**81 passed**; focused SNR/companion/receipt checks **77 passed**. Ruff, compile,
and whitespace checks passed. One initial unrelated pruning-index failure passed
both isolated and full reruns without pruning changes. The plot scope and broad
precommit audits remain blocked by the same eight unrelated paths in untracked
`outputs/`; focused downstream tests were run directly. Local Qt was not run.

## Post-Processing Step 1 Performance (2026-09-06)

The reported log gap included time away from the PC; it is not a measured
four-hour computation. Read-only MCCTR probes measured ledger/outcome loading
at about 0.07 s and the first 12 ROI-coverage cells at 0.42 s. These were not
large bottlenecks. No complete project processing or QC publication was run.

- Reuse verified companion identities/headers/schemas across workbook passes
  within the existing run scope, retaining file-signature checks and bounded
  memory. Keep the four-entry numerical payload cache and first-read validation.
- Traverse the audit table's same common-dtype values without allocating a
  pandas Series per row. On one 2,624-row table, paired medians were 65.65 ms
  before and 11.95 ms after, with identical evidence; this is a parser timing,
  not a whole-pipeline speedup.
- Show concise step-1 substages and log computation durations before the GUI
  review wait. Timings are absent from scientific reports and fingerprints.

Runtime changes are confined to `Main_App/io/condition_data.py`,
`Main_App/io/spectral_data.py`, `Main_App/io/xlsx_selected_reader.py`,
`Main_App/processing/frequency_domain_qc.py`, and
`Main_App/workers/post_processing_pipeline_worker.py`.
Visible smoke: complete post-processing QC and verify the step-1 description
changes as work advances, technical logs stay out of the status label, progress
does not falsely advance to step 2, and the review dialog still requires the
same decisions. Check the log's stage durations separately from review time.

Independent six-workbook read-only benchmark: repeated identity checks fell
from 0.1682 s (12 checksums) to 0.0121 s (none repeated); header checks fell
from 0.1281 s (6 checksums) to 0.0054 s (none repeated). Initial validation was
similar (0.1930 versus 0.2008 s). The memory policy caps verified records at
256 and unique spectral-header labels at 262,144; common grids share tuples.

Validation: processing scope **1,161 passed, 5 skipped**; direct companion,
selected-reader, SNR-context, and Stats-cache checks **86 passed**. Paired tests
retain exact audit evidence, findings, finite-data gates, and numeric values;
replacement/corruption, eviction, header detachment, and memory bounds pass.
Ruff/compile/diff checks passed. Project-I/O and broad precommit gates still
stop at the same eight unrelated `outputs/` path findings. Local visible Qt
was not run; use the smoke path above after restarting the application.

## All-QC Efficiency Audit (2026-09-06)

Baseline: the working tree at the start of this audit, including the step-1
improvements above. The seven runtime modules changed below were identical to
`cd546fe1` before this pass. No threshold, processing order, sample coordinate,
noise formula, selection policy, output schema, or review decision was changed.

| QC area reviewed | Result |
| --- | --- |
| Recording/header readiness and source identity | Retained cheap header checks and current source validation. |
| Channel health and experimental removed-electrode detection | Finite float64 metric batches avoid redundant NaN copies/masks; all classification rules retained. |
| CMS/DRL/common-noise, spatial and neighborhood checks | Retained current reductions, donors and evidence; no confirmed additional hotspot. |
| Condition spectral/artifact screening | Apply the same Hann window and amplitude scaling to privately allocated scratch arrays. |
| Marker occurrences and exact analysis windows | Index integer marker samples once; reuse exact interval evidence for repeated spacings. Span mapping remains unchanged. |
| Kurtosis evidence and automatic/manual review | Construct each identity payload once per serialization; recompute current fingerprints each call. Prepared-signal reuse remains in place. |
| Condition/participant exclusions and interpolation burden | Retained indexed lookups and current review-authority validation. |
| Retained-signal and computable-BCA integrity | Find the first invalid value without materializing every invalid coordinate; preserve target-major failure ordering. |
| Missing conditions, electrode/ROI coverage and output receipts | Retained current validation and mutable receipt hashing; bounded probes found no large hotspot. |
| FullFFT grid and harmonic technical eligibility | Reuse bounded immutable exact-input calculations; every file and exported row is still checked. |
| Harmonic selection and absolute/cohort frequency-domain review | Benefit from shared eligibility and the prior audit-table/read improvements; scientific calculations retained. |
| Final release, QC summaries and review persistence | Retained existing shared indexes, current decision checks and worker handoff. |

Paired component medians (before -> after; these are not whole-run estimates):

- Six FullFFT grid checks: 865.09 -> 148.22 ms; six eligibility reconstructions:
  34.54 -> 16.23 ms. Includes the first calculation; file I/O excluded.
- Finite 64 x 30,720 retained samples: 4.24 -> 0.77 ms; all-invalid input:
  24.91 -> 1.24 ms, with the same first error and payload.
- Six-condition marker plan: 10.80 -> 4.63 ms; 64-channel kurtosis serialization:
  1.66 -> 0.80 ms.
- 64 x 10,240 channel metrics: 9.06 -> 7.76 ms; 8 x 245,760 spectral batches:
  36.78 -> 34.34 ms.

Paired baseline checks preserve exact metric/FFT bits, complete evidence,
receipts, flags and fingerprints. Regressions cover NaN/Inf, overflow, signed
zero, strides, immutable source arrays, marker origins above 2**53, boundary
markers, changed rates/cycles/filter/notch, corrupt rows and bounded-cache
fallbacks. Only read-only, bounded real-project probes were used; the complete
user dataset was not reprocessed. The export contract documents pure-cache
ownership; other architecture and user workflows are unchanged.

Verification: the processing gate passed **1,256 tests**, skipped five, and
reported one existing concurrent-pruning test failure: an unavailable `.slots`
index caused safe retention of two cache generations instead of one. The
isolated test and then its complete file passed (**22 passed, 2 skipped**);
pruning production code and its tests were not changed. No numerical or parity
test failed. Independent review found no defect in the new immutable caches or
first-invalid-value checks. Ruff, compile, protected-boundary and whitespace
checks passed. Repository precommit still stops at the same eight unrelated
hardcoded paths in untracked `outputs/`. No Qt execution was needed or run for
these backend-only changes.

## Harmonic Calculation Metadata Copies (2026-09-07)

- [x] Drop unused DataFrame attrs only on the harmonic loader's owned working
  frame, before pandas column operations. Preserve shared reader metadata,
  validated source identities, exact values/reductions, and all selection rules.
- [x] Verify bitwise parity, electrode/column ordering, retained provenance,
  cached rereads, and unchanged nonfinite/source-membership rejection. A copy
  sentinel guards against reintroducing calculation-time metadata copying.

The observed MCCTR provisional-harmonic stage took 479.751 s. Live sampling
found pandas repeatedly deep-copying the attached 15,361-frequency grid.
A read-only full-loader comparison on one saved 64-electrode condition with
627 planned columns measured 3.2921 s before and 0.06289 s after (about 52x).
Every output float64 bit, frequency index, reference column, electrode count,
and selected-electrode set matched; original/fresh metadata and the companion
identity were unchanged. This is a single-loader measurement, not a measured
whole-project speedup. No user data were rewritten or reprocessed.

No architecture update is needed for this local working-frame optimization;
ownership, I/O formats, processing order, fingerprints and GUI workflows stay
the same. Manual smoke: restart the Toolbox, resume post-processing and compare
the logged provisional-harmonic duration; review decisions still apply normally.

Verification: **1,284 processing tests passed, 5 skipped**; **421 Stats tests**
passed before the added regression cases, then the complete modified profile
test file passed **31 tests**. GUI static checks passed **81 tests**, companion
reader checks **61**, and harmonic-cache checks **17**. Ruff, compilation and
whitespace checks passed. Repository precommit still reports only the eight
existing hardcoded paths in unrelated untracked `outputs/`; those files are
excluded from the commits. No local Qt workflow was run.

## Repeated Summed-BCA Review Fix (2026-09-07)

- [x] Reproduce accepted decisions changing the adaptive harmonic cache key
  and timestamp, then incorrectly invalidating otherwise identical QC evidence.
- [x] Exclude the three harmonic-cache annotations from scientific review
  identity. Preserve all source, settings, cohort, harmonic and finding checks.
- [x] Reuse older validated review receipts only when the complete current
  analysis matches after substituting the original cache annotations. Preserve
  original review evidence across automatic synchronization and repeated reuse.
- [x] Add regression coverage for cache rebuild/reload, old receipts, damaged
  receipts, changed inputs/settings and legitimate exclusion reconfirmation.

The export contract now documents this review-identity boundary. No scientific
selection rules, exclusion scopes, or persistence formats change.

Manual smoke: restart the Toolbox, resume post-processing, apply the QC review
choices, and verify unchanged findings do not reopen and processing advances.
If exclusions change the actual cohort or harmonic evidence, complete the
legitimate follow-up review and verify it settles. Existing saved choices should
also be reused when their scientific evidence still matches.

Verification: `python .agents/scripts/verify.py --scope processing --tier focused`
passed **1,324 tests, 5 skipped**, including eight new reuse regressions. Ruff,
compilation, protected/source-localization audits, independent review, and
whitespace checks passed. The protected audit evaluated the retired
`Legacy_App`, `PySide6_App`, Source Localization and quarantine boundaries;
none was changed by this fix. `python .agents/scripts/verify.py --scope repo
--tier precommit` still stops at eight existing hardcoded paths in unrelated
untracked `outputs/`. No Qt workflow was run locally; the visible smoke path
above remains to be exercised in the application.
