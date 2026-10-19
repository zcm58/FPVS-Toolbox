# QC Performance: Exact Numerical Reuse

Status reviewed 2026-10-18: implementation is integrated and source CI passed.
The published v3 installer passed automated native acceptance; human visible
review remains unclaimed. Broader optional private-project qualification was
stopped by the user, not left as an active task. The
[release ledger](v3-release-readiness.md#3-qualify-processing-and-project-compatibility)
owns current evidence and deferrals. Dated records below preserve contracts
and original measurement limits; earlier pending CI statements are historical.

## Postprocessing Review Readiness And Audit Parsing (2026-09-08)

Baseline: `c44665827da158de0643758b4bbb999b26d8b6b2`. The approved first batch
from the [postprocessing QC investigation](../../reviews/postprocessing-qc-v3-investigation.md)
adds accurate review readiness and exact-target navigation, decision consequence
and unsaved-state copy, honest non-cancellable post-processing controls, and a
bounded per-read memo for repeated exact frequency-label parsing.

- [x] Preserve the original choices, reasons, group actions, undo and backend
  validation; show missing choices, missing artifact confirmations and conflicts.
- [x] Explain broad exclusion and interpolation consequences within existing
  detail panes, retaining the supported dialog size and filter/selection state.
- [x] Keep the shared action disabled during output preparation and saving;
  restore existing Start/Resume behavior on completion or failure.
- [x] Reuse at most 256 built-in string tokens, each at most 128 characters, in
  one audit-table read; on cache allocation failure use original conversion.
- [x] Complete frozen-baseline regressions, production timing/parity checks,
  focused verification and independent review.

No numerical operation, summation order, precision, harmonic selection, raw
source validation, project identity, decision schema, persistence ownership or
export format changes. No long-lived cache, preview viewer, new broad bulk
action or saved draft is introduced. Architecture updates document presentation,
worker-state and per-read cache ownership; statistical-method docs need no
change because the scientific contract is unchanged.

Actual production verification uses the harness's `--baseline-ref c4466582`
option to load the frozen parser, converters and constants by AST from Git.
Three alternating real-project pairs (12 runs across new/reused provisional
evidence) retained identical complete ordered result fingerprints and source
validation read counts. Median backend preparation was **30.570 → 28.479 s**
with new evidence (**6.8%**, 2.091 s saved), and **21.523 → 19.094 s** with
reused evidence (**11.3%**, 2.429 s saved). The manifest hash stayed unchanged
and the write-blocking audit recorded no mutation attempts. These measurements
exclude GUI/user time, saving, repair and export publication; durable harmonic
caches remained available and OS caches were not flushed. No memory reduction
is claimed. The actual parser's five-pair helper median was **11.938 → 6.882 ms**,
reducing frequency conversions from 2,624 to 41 for the measured table.
[Production evidence](../../reviews/postprocessing-qc-v3-implementation-evidence.json)
retains all timings, hashes, environment details and bounds. The earlier
investigation's prototype timings remain historical, not final-code receipts.

Reproduce the real read-only comparison with the repo environment:

```console
python scripts/manual_diagnostics/investigate_postprocessing_qc.py PROJECT_ROOT NEW_DIAGNOSTIC_DIRECTORY --baseline-ref c44665827da158de0643758b4bbb999b26d8b6b2 --trials 3
```

The diagnostic directory must be outside the project and unused. No other
CPU-heavy test or benchmark should run concurrently. This is a developer-only
probe in `scripts/manual_diagnostics`, not a runtime workflow.

Final implementation checks: processing focused **1,871 passed, 5 skipped**
(59 existing synthetic FIR/stim warnings); GUI focused **414 passed**. The first
GUI run exposed an extracted-callback fixture missing the new tooltip state;
the fixture now supplies it and asserts restoration, and the full GUI rerun
passes. The parser's focused 39 cases and the non-Qt worker lifecycle cases are
included in these scopes. Ruff, compilation, GUI/protected/source-localization
audits and whitespace checks pass. The repository precommit gate still stops
before broad tests on the same eight pre-existing hard-coded paths in unrelated
untracked `outputs/`; it is not a passing gate. Those files remain untouched.
Independent review found and resolved post-processing thread-start cleanup,
with no remaining actionable finding. Qt execution, visible fit, installer and
CachyOS smoke remain unrun; the path below and the existing CI registry cover
the required next validation. This handoff implements only the approved first
batch; investigation proposals for viewers, broader caching and other deferred
work remain recommendations.

Visible smoke (not run locally; Qt execution is CI-only): at 1280x900 and the
1000x650 dialog minimum, verify all actions fit with long identities. Filter and
sort to hide a missing choice, unconfirmed repair and conflicting exclusion;
Next needs attention must reveal the exact target and focus its combo or
confirmation. Verify reasons/choices survive navigation, counts update when
confirming repair, group hidden/replaced counts are accurate, and undo restores
choices and confirmations. Cancel must leave Resume available without saving;
acceptance must show Saving QC then Preparing Outputs with disabled controls,
and completion/failure must restore Start/Resume and the usual tooltip. Check
save/start failures and optional export failure without marking failed artifacts
current. Repeat on Windows 11 and CachyOS. Local tests cover the non-Qt model
and orchestration; registered Qt tests describe the remaining visible behavior.

## Participant Exclusions Before Kurtosis Loading (2026-09-07)

Baseline: `37739269`. Remove known participant exclusions from speculative
step-2 source loading and refresh eligibility as review choices change. Select
step-6 workers from recordings that require work, and report eligible progress
separately from exclusions and failures. Preserve scientific calculations,
continuous filtering for retained conditions, ordered evidence/skip results,
cache identities, and source immutability.

- [x] Filter and refresh the preload queue without GUI-thread I/O; retire
  excluded ready buffers safely and let active reads release their own data.
- [x] Resolve verified skips before worker resource estimates and add
  structured eligible/excluded progress without breaking legacy callbacks.
- [x] Wire current participant choices and clear progress into the GUI.
- [x] Verify races, exclusion scope, eligible-only scheduling, exact evidence,
  cancellation and cleanup; run processing/GUI gates and commit.

Scope is participant-level speculative loading. Recording and condition
exclusions retain their existing scientific authority; partial exclusions do
not justify changing the continuous filter input. Temporary sources remain
inside the active project's `.fpvs_processing/qc-source-*` directory.

The preload constructor matches normalized, case-insensitive participant IDs
from `RawFileInfo.subject_id`, never filenames. The GUI refreshes exclusions
after accepted reviews and before each kurtosis scan. Refresh only changes
thread-safe state: queued work is skipped, active reads finish safely without
publishing excluded data, and ready buffers are retired by background
maintenance. Borrowed Raw objects remain owned until release. Retired work is
not restarted if a participant is re-included; normal source loading remains
available. Maintenance and final cleanup coordinate ownership and staging
budget, including cancellation and concurrent close.

The kurtosis coordinator resolves existing participant, recording and complete
condition exclusions before file-size or duplicate-stem resource estimates.
Invalid plans remain explicit errors; partial exclusions retain continuous
filtering. Ordered skip/error/evidence results and legacy progress accounting
remain available. Structured progress reports eligible completions, exclusions
and failures; the GUI shows `Processed X of Y eligible recordings; Z excluded`
and a separate failure count. Zero eligible recordings complete without source
hashing, loading or worker allocation. An excluded but still active preload
continues to reserve its concurrency slot until it releases its data.

Production files: `src/Main_App/processing/qc_source_prefetch.py`,
`src/Main_App/workers/qc_source_prefetch_worker.py`,
`src/Main_App/processing/kurtosis_review_scan.py`, and
`src/Main_App/gui/preprocessing_qc_workflow.py`. Coverage is in
`tests/processing/test_qc_source_prefetch.py`,
`tests/processing/test_kurtosis_review_scan.py`,
`tests/workers/test_qc_source_prefetch_worker_static.py`,
`tests/gui/test_qc_source_prefetch_static.py`, the extracted-loop fixture in
`tests/gui/test_kurtosis_review_dialog_static.py`, and the existing CI-only fixture
in `tests/gui/test_qc_source_prefetch_qt.py`. This plan, the preprocessing
contract and workers/threading contract document the changes. Project roots
still come from the active project; no hard-coded paths, export formats,
method fingerprints or retired-package boundaries changed.

The complete serial body from `raw_plans` through its final result is AST-
identical to `37739269`. Focused tests compare full ordered scientific payload
bits against that unchanged body, including errors, exclusions and retained
conditions. Initial focused checks passed 50 source/worker cases, 40 scanner
cases, and 30 GUI-safe orchestration cases. No local Qt execution or real
project mutation occurred.

Final combined focused verification passed **142 tests** across the source,
scanner, worker and GUI-safe orchestration files above plus preflight reuse and
Continue checks; Ruff, compilation, GUI/protected/source-localization audits
and whitespace checks passed. `python .agents/scripts/verify.py --scope gui
--tier focused` passed **382 tests**. The processing driver (`--scope processing
--tier focused`) completed with **1,690 passed, 5 skipped** and six failures:
five were old extracted-loop test namespaces missing the new refresh helper,
now fixed and covered by the passing combined run. The remaining fixed-profile
harmonic-selection failure is caused by a concurrent, unrelated Stats edit
whose canonical ROI comparison differs from its old `FZ` fixture. That test
fails alone with the concurrent edit and passes in an isolated test process
when only the Stats function is restored from `37739269`; no working-tree
files were changed for that confirmation. Concurrent Stats/export edits remain
outside this commit. The repository precommit driver (`--scope repo --tier
precommit`) still stops on the same eight pre-existing path-audit findings in
unrelated untracked `outputs/`. The broad gates are therefore not claimed as
passing. Independent final review found no actionable QC regression.

Visible smoke after restart: use a small project with a participant exclusion,
leave step 2 open, and confirm that participant never appears in preload logs.
Add a participant exclusion during review and confirm unstarted loads are
skipped, the UI stays responsive, and step 6 reports eligible/excluded counts.
Repeat with every participant excluded, then cancel an active preload/scan and
confirm run-owned temporary directories disappear after cleanup. Re-including
a participant must retain the normal loading fallback. Qt execution is CI-only
locally under the repository policy.

## Preprocessing Step 1 Follow-up (2026-09-07)

Baseline: `ed089e9d`. Require exact float bits, complete scientific evidence,
row ordering, source immutability and unchanged cache/method fingerprints.
Allow up to eight recording threads when the shared CPU/RAM policy permits;
keep two readers and two spectral evaluators. Do not change FFTs, BLAS thread
counts, reference/filter order or diagnostic windows.

The latest 51-file MCCTR log spans 306.971 seconds. Overlapping worker-stage
totals identify raw-channel QC (745.621 s) as dominant, compared with condition
reads (186.410 s), events/planning (186.393 s) and spectral work (4.689 s;
experimental spectral screening was disabled). These totals are concurrent
worker times, not additive wall time. A read-only 64-channel, 120-second real
occurrence profile attributes about 0.975 of 1.619 seconds to spatial scoring,
including repeated NaN-aware donor means on entirely finite data.

- [x] Profile actual logs and a read-only real occurrence before selecting work.
- [x] Add guarded finite-input reductions while preserving the original
  nonfinite/unsupported-layout path and every spatial norm/dot operation.
- [x] Verify frozen before/after float bits on edge cases and real recordings.
- [x] Benchmark complete cold/warm step-1 scans with isolated scratch caches.
- [x] Compare four/eight workers on synthetic and complete real scans.
- [x] Verify the final resource-aware worker policy and document measured limits.

User recordings, project manifests, review choices and existing caches remain
unchanged by diagnostic probes. The GUI workflow does not change; its reported
worker count now uses the same resource-aware selector as the backend.

Read-only paired measurements (Windows, NumPy 2.3.1, MNE 1.9.0):

| Scope | Baseline | Optimized | Observed reduction |
| --- | ---: | ---: | ---: |
| One recording's five analyzed occurrences, raw-QC median across two alternating comparisons per occurrence | 1.738 s | 1.257 s | 27.7% |
| Four recordings / 24 occurrences, complete step 1, first pair | 25.879 s | 18.983 s | 26.6% |
| Same four recordings, reversed-order pair | 34.007 s | 29.440 s | 13.4% |
| Complete step-1 median of those pairs | 29.943 s | 24.211 s | 19.1% |

Complete scan cases used fresh isolated QC caches beneath verified repository
scratch paths; the operating-system file cache was not cleared. Four recording
workers and all existing limits/settings remained unchanged. Both versions
slowed during the second pair; CPU work and reads varied, and the measurements
do not identify the cause. These are subset measurements, not a predicted
51-recording duration or a universal performance guarantee.

All ten occurrence comparisons and every complete cold scan matched the frozen
baseline's scientific float bits and ordered payloads. Full comparisons covered
channel metrics/findings, spectra, analyzed plans and fingerprints; only timing
and cache-status metadata differed. An optimized warm scan took 0.323 seconds
with four cache hits and identical scientific evidence. Raw buffers, recording
metadata and project-manifest bytes remained unchanged. Benchmark cache folders
were removed after each case; no real project cache was cleared or replaced.

Median raw-QC worker time fell from 76.475 to 57.376 seconds across the four
recordings. Sampled peak process RSS ranged from 1,550–1,591 MiB before to
1,510–1,522 MiB after. RSS sampling and allocator history limit precision.

The subsequent worker comparison used the optimized code in every case:

| Scope | Four workers | Eight workers | Observed reduction |
| --- | ---: | ---: | ---: |
| Eight synthetic 64-channel, 120-second occurrences, calculation-only median | 5.509 s | 4.171 s | 24.3% |
| Eight real recordings / 48 occurrences, complete step 1, first pair | 48.957 s | 42.799 s | 12.6% |
| Same eight recordings, reversed-order pair | 49.828 s | 44.954 s | 9.8% |
| Complete step-1 median of those pairs | 49.393 s | 43.877 s | 11.2% |

The full worker comparison retained two readers and two spectral evaluators,
with fresh isolated QC caches and an uncleared operating-system file cache.
Every ordered scientific payload matched bit for bit across all four cases.
Sampled peak RSS rose from 1,499–1,500 MiB to 1,928–2,005 MiB, and median CPU
time rose from 121.133 to 140.594 seconds. The smaller complete-scan gain came
with increased read/wait and per-worker calculation time. These are separate
subset benchmarks; their percentages
must not be added or used to predict the entire project duration.

The eight-worker ceiling applies the existing shared CPU/total-RAM policy to
requests above four, without RAM-cap bypass. Existing requests of four or
fewer stay unchanged; unavailable resource information keeps the previous
four-worker ceiling. For these additional-concurrency requests, RAM tiers
permit at most two workers below 12 GiB, four below 40 GiB, seven below 80 GiB,
and eight at 80 GiB or more when CPU/request limits allow. This uses the
established total-RAM policy, not a new live-memory
guarantee. It neither changes BLAS thread settings nor adds process pools.

Changed files:

- `src/Main_App/processing/raw_channel_qc.py`: three guarded finite reductions.
- `src/Main_App/processing/preflight_qc.py`: shared resource-aware worker selector.
- `src/Main_App/processing/preflight_qc_plan.py`: eight-worker ceiling.
- `src/Main_App/gui/preprocessing_qc_workflow.py`: report the resolved worker count.
- `tests/processing/test_raw_channel_metric_batching.py`: scalar and batch float-bit parity.
- `tests/processing/test_raw_channel_spatial_parity.py`: frozen spatial formulas and evidence parity.
- `tests/processing/test_preflight_qc_v2.py`: bounded worker policy and scheduling checks.
- `.agents/verification.toml`: register the spatial parity test.
- `docs/agent/architecture/preprocessing-contract.md`: reductions and worker contract.
- `docs/agent/architecture/workers-threading.md`: current worker admission and ceilings.
- `docs/agent/exec-plans/active/qc-performance.md`: scope, measurements and verification.

No project paths, exported formats or processing order changed.

Rejected alternatives: replacing the median and changing native BLAS thread
counts produced different numeric bits in probes. Spectral scratch reuse had
little impact on this project's bottleneck. More participant processes were
not justified: recording threads already run native calculations
concurrently, and processes add transfer, startup and memory costs.

Final verification: `python .agents/scripts/verify.py --scope processing --tier focused`
passed **1,674 tests, 5 skipped**, with the existing 56 synthetic FIR/stim
warnings. `python .agents/scripts/verify.py --scope gui --tier focused` passed
**375 non-GUI-execution checks**. Ruff, compilation, GUI/protected-path/source-
localization audits, verification registration and whitespace checks passed.
The independent final review found no actionable regression. The repository
precommit driver (`python .agents/scripts/verify.py --scope repo --tier precommit`)
still stops before its full test run on the same eight
pre-existing local paths in unrelated untracked `outputs/`; those files were
not changed. No local Qt execution occurred. Visible follow-up: restart the
toolbox from this branch, run step 1 on a representative project, confirm the
reported worker count respects its CPU/RAM/request limits, compare its existing
timing log and review findings, and confirm cancellation and cached restart remain
responsive. A complete 51-recording GUI run was not repeated by the probe.

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
maps/Stats with the same choices, and inspect long/wide Excel exports.
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

## QC Resume And Geometry Recovery (2026-09-07)

- [x] Reproduce the second false review from resolved exclusion reconfirmations:
  a saved review had 26 Retains, including nine resolved reconfirmations; the
  next report had 17 unchanged ordinary findings and the same analysis hash.
  Dropping the nine completed receipts changed the decision hash. Retain these
  independently validated receipts while the analysis remains current, without
  adding findings or restoring exclusion authority.
- [x] Forward the project montage and channel-label mapping into GUI processing
  parameters. Omitting both made the worker and run plan default to anatomical
  labels while final provenance validated a different saved A/B setting. Both
  profile cases fail the new forwarding regression before the fix and pass after.
- [x] Validate candidate geometry before requesting QC decisions. Honor valid
  reviewed cohort exclusions, reject invalid/mixed geometry, name mapping
  mismatches precisely, and preserve an existing downstream failure reason.
- [x] Stop dependent consumers after failed FullFFT provenance or harmonic
  selection, preserving one final receipt and normal cleanup. Independent
  spreadsheet/source exports still proceed when their prerequisites succeeded.
- [x] Accept the current source-ready crop tag in its consumer, preserving all
  existing sample-grid, reference, channel, processing and integrity checks.
- [x] Make app-level BioSemi64/anatomical defaults explicit, test new-project
  persistence, and apply the user-requested pairing to all six configured
  projects and the local app settings. Changed manifests have exact original
  backups under `.fpvs_processing/config_backups/`; app settings have an INI
  backup. Recorded samples, completed processing geometry, and review history
  are not rewritten by this settings correction.

Comparison baseline: `codex/v3-release` at `f586652e`. That branch predates the
per-finding reconfirmation receipts and the strict current geometry contract;
the new receipt-loss bug is not a reason to restore its automatic-exclusion
semantics. Its unconditional downstream orchestration remained in the current
worker, producing secondary stale-QC errors after the geometry failure. Its
source input reader also still accepted only `55_onbin`, although the current
producer writes `project_marker_plan_target_grid_v2`.

Read-only validation of the affected project found all 24 BDF headers already
use anatomical scalp labels and all completed records use canonical BioSemi64.
After the approved mapping correction, the project passes strict geometry
validation with the same 64-channel identity recorded during processing.

Visible smoke (Qt remains CI-only locally): restart the Toolbox; verify Settings
shows BioSemi64 and anatomical labels; resume post-processing. A completed
Retain reconfirmation must not reopen unchanged ordinary findings. Genuine
changed findings still require review. A mapping mismatch must stop before the
review, and failed prerequisites must report the original reason without
launching dependent exports. Source-ready data using either supported crop tag
must retain its normal validation and publication behavior.

Verification: `python .agents/scripts/verify.py --scope processing --tier focused`
reported **1,401 passed, 5 skipped** and one existing cache-pruning failure:
an unavailable `.slots` index retained an extra cache generation. The complete
unchanged pruning test file then passed **22 tests, 2 skipped** in isolation.
`--scope gui --tier focused` passed **188 tests**. The explicit non-Qt worker and
source-input bundle passed **59 tests**; the new worker-static file is now also
registered in the processing scope. All new failing-before-fix regressions pass.
Ruff, compilation, protected/source-localization and GUI audits, independent
review, and whitespace checks passed. `--scope repo --tier precommit` and the
LORETA/path gate remain blocked by eight existing hardcoded paths in unrelated
untracked `outputs/`. No local Qt workflow, numerical reprocessing or source-map
generation was run. The visible smoke above remains the final application check.

Runtime changes are confined to `settings/settings_manager.py`,
`gui/processing_inputs.py`, `processing/frequency_domain_qc.py`,
`processing/full_fft_provenance.py`, `workers/post_processing_pipeline_worker.py`
under `src/Main_App`, and
`src/Tools/LORETA_Visualizer/source_producers/project_time_domain_inputs.py`.
The protected `Legacy_App`, `PySide6_App`, removed Source Localization and
quarantine boundaries were audited and remain unchanged. Scientific processing
order, numerical algorithms, and existing output formats remain unchanged.

## Stale Project Mapping Save Recovery (2026-09-07)

The subsequent preflight log rejected all 24 selected BDF files because MCCTR's
saved channel profile again requested A/B labels. The manifest was rewritten
at 10:19:26 local time, after its approved anatomical-label correction. The
other five project manifests and app defaults retained the requested pairing.
An executable reproduction identified a persistence bug: an older loaded
`Project` saved its cached A/B profile during an unrelated edit, replacing a
newer anatomical profile already saved to disk.

- [x] Track the two geometry fields observed at project load, refresh, or the
  last successful save. Reconcile unchanged local fields with the newest saved
  values; preserve explicit local edits and existing unrelated settings behavior.
- [x] Share one validated disk snapshot with the existing worker tool-metadata
  merge. Invalid or unreadable saved settings must stop saving; failed writes
  must not advance the geometry baseline.
- [x] Refresh project geometry before building processing parameters without
  saving the manifest. A failed refresh warns and stops parameter construction.
- [x] Preserve the same correction through an already-open Settings panel.
  Track geometry controls separately from its mutable general settings cache;
  refresh unchanged selectors, preserve explicitly edited selectors, and rebase
  only after a successful save. Failed saves keep pending choices available.
- [x] Reproduce stale saves and stale parameter construction before the fix;
  test explicit edits, successive refreshes/saves, failed-save retries,
  malformed/denied manifests, and preservation of worker tool metadata.
- [x] Restore MCCTR with an exact original-manifest backup under
  `.fpvs_processing/config_backups/`. Verify all six configured projects and
  app settings still use BioSemi64/anatomical labels.
- [x] Open all 24 previously rejected files through the actual public preflight
  lazy loader using the repaired project settings. Every file opens with all
  64 canonical scalp channels, montage coordinates, and `preload=False`.
  This check does not read whole EEG recordings or run numerical preprocessing.
  The repaired project also passes the strict pre-review geometry check against
  its existing completed processing records with the same 64-channel identity.

Runtime ownership added by this follow-up is confined to `projects/project.py`
and the existing `gui/processing_inputs.py` and `gui/settings_panel.py` boundaries.
The project I/O contract
documents the geometry reconciliation. The 21 new persistence regressions are
registered in the project-io focused verification bundle; eight Settings-panel
AST regressions are registered in the GUI bundle.

Visible smoke: fully close and restart the Toolbox so old Python classes and
any previously open Settings panel are discarded. Open MCCTR, confirm BioSemi64
and anatomical labels, and start processing. All selected BDF files must pass
the label check; then exercise the frequency-domain review/resume path described
above. Save an unrelated Settings change twice and confirm the mapping stays
anatomical. A deliberate selector change must save normally; a failed save must
leave that pending selection available. No local Qt workflow or complete
numerical pipeline was executed.

Verification: the processing focused gate passed **1,424 tests, 5 skipped**.
The GUI focused gate passed **199 non-Qt tests**, including the new panel cases.
The complete configured non-Qt project I/O bundle passed **194 tests** when
run directly after its focused gate stopped on the existing path audit findings.
The repo precommit gate still stops on the same eight hardcoded paths in
unrelated untracked `outputs/`. New persistence and parameter regressions were
shown failing before the fixes. Ruff, compilation, GUI/protected/retired-source
audits, and independent review passed for the corresponding changed code.

## Background Source Loading During Interactive QC (2026-09-07)

User scope: begin loading and temporarily caching sources as step 2 opens,
allow unfinished loading to continue into step 6, and keep clear review steps
visible for a brief user acknowledgement. No timed pause or minimum review
duration is introduced.

- [x] Start a background QThread after the initial signal scan and before
  marker review. Stage sequential disk-backed decoded sources in a private
  active-project `.fpvs_processing/qc-source-*` directory, bounded to 16 GiB
  while reserving 2 GiB of free space. The GUI-side constructor performs no I/O.
- [x] Let step 6 adopt ready sources once with the existing geometry, events,
  spans, current decisions, file hashes and sample checks. Stop unstarted
  speculative loads at handoff; pending sources fall back without waiting
  behind a recording that was excluded. Share concurrency with an active load.
- [x] Verify source content before/after preload and again at handoff. This
  rejects same-size source edits whose original modification time was restored,
  including Windows where ctime is creation time. Hashing is cancellable.
- [x] Release consumed sources after use and close remaining resources off the
  GUI thread on every review exit. Prevent duplicate filename collisions,
  stale mutated reuse, redirected cleanup, and implicit MNE/tempfile deletion
  bypasses. Reject closing the main window while its prefetch bridge is active.
- [x] Show no-action steps 2, 3, and 5 with accurate counts and one Continue
  button. Step 4 keeps its editable electrode table and Save / Next; its clear
  state no longer presents a redundant introductory modal. Flagged reviews
  keep their existing scientific decisions and persistence behavior.

This first implementation preloads sources only. Filtering/downsampling and
kurtosis calculation still occur at step 6; current prepared-kurtosis
checkpoints and final-runner behavior remain intact. No numerical method,
processing order, exported format, or approval authority changes. No complete
user dataset was reprocessed, and no wall-clock speedup is claimed.

Runtime changes are confined to `io/load_utils.py`, `gui/main_window.py`,
`gui/preprocessing_qc_workflow.py`, `processing/kurtosis_review_scan.py`, new
`processing/qc_source_prefetch.py`, and new
`workers/qc_source_prefetch_worker.py` under `src/Main_App/`. Loading,
preprocessing, and worker architecture pages document ownership and lifecycle.
The retired Legacy_App, PySide6_App, removed Source Localization, and quarantine
boundaries remain unchanged; the root MNE/fsaverage cache is never a target.

Verification: `.venv/Scripts/python.exe .agents/scripts/verify.py --scope
processing --tier focused` passed **1,453 tests, 5 skipped**. After lifecycle
and source-content hardening, the focused loader/scanner/cache/review/worker
bundle passed **128 tests**; the completed source-prefetch file passed **28
tests**, including unexpected hash-failure release. The final GUI focused gate
passed **222 non-Qt tests**. Real MNE comparisons preserve exact sample bytes,
kurtosis evidence, decision plans, and previews through both review preparation
and final preprocessing. Ruff, compilation, GUI/protected/removed-source and
garbage-collection audits, and whitespace checks pass. The repository
precommit gate still stops at the eight existing hardcoded paths in unrelated
untracked `outputs/`.

CI-only coverage: `tests/gui/test_qc_source_prefetch_qt.py` registers two real
QThread tests for review/Continue responsiveness, heartbeat during final cleanup,
signal delivery, and retained completed prefetch. No local Qt workflow was run.
Safe coverage also lives in `tests/processing/test_qc_source_prefetch.py`,
`test_kurtosis_review_scan.py`, `test_shared_load_utils.py`,
`tests/gui/test_qc_source_prefetch_static.py`,
`test_preprocessing_qc_continue_static.py`, the existing marker/kurtosis/reuse
static tests, and `tests/workers/test_qc_source_prefetch_worker_static.py`.

Visible smoke after restart: start a small project at 1280x900, pause on step 2,
and confirm preloads progress in the log while Continue remains immediately
usable. Inspect clear steps 2/3/5 and edit step-4 removals normally. At step 6,
check the preloaded-recording status and complete the same decisions. Repeat
by advancing rapidly, changing review choices, and cancelling step 6. Confirm
Close is blocked while review cleanup owns the worker, temporary run files
disappear on QC exit, and original recordings/persistent checkpoints remain.

## Consolidated Dataset Exclusions (2026-09-07)

User scope: consolidate participant exclusions into one list that distinguishes
skipping raw processing from excluding already-processed data from analysis.
Restoring a participant must also release a remembered manual processing skip.

- [x] Replace the two Advanced Settings management controls with one Dataset
  Exclusions manager, retaining the frequency-QC threshold summary.
- [x] Show processed-data availability, explicit processing/analysis scopes,
  existing overlap, reasons, and condition-specific exclusions without silently
  migrating or removing saved decisions.
- [x] Support individual edits, selected-row bulk edits, and restoration across
  the full participant/recording list independently of the search filter.
- [x] Load and save through a worker; preserve modal ownership and close guards.
  Apply saves immediately and refreshes only the live exclusion fields, avoiding
  stale Settings saves that would restore removed exclusions.
- [x] Revalidate cached manual ledger exclusions against current participant
  and recording settings. The final removed scope becomes runnable without
  deleting caches or processing history; header-only and automatic rules remain.
- [x] Finish backend persistence/review-authority regressions and independent
  review. The backend rejects stale edits, validates the prospective snapshot
  before atomic publication, archives obsolete completed-review authority, and
  preserves condition decisions and unrelated project state.
- [x] Complete the focused processing gate and record final verification.

Owners added: `processing/dataset_exclusions.py`,
`gui/dataset_exclusions_dialog.py`, `gui/dataset_exclusions_workflow.py`, and
`workers/dataset_exclusions.py`. Existing Settings and processing-ledger owners
provide integration; raw preprocessing, numerical methods, and output formats
are unchanged. The project-I/O architecture and user guide document the
workflow. Cache-reset wording now states that saved exclusions still apply.

Visible smoke after restart (Qt execution remains CI-only locally): open the
manager on a project containing processed and unprocessed participants; verify
the two exclusion scopes are clear, analysis exclusion is unavailable for a new
unprocessed row, existing overlaps and condition decisions are visible, and
all controls fit the supported 1280x900 workspace. Stage individual/bulk edits,
cancel once, then apply; reopen Settings and save an unrelated change to verify
restored choices remain restored. Restore a previously skipped participant and
verify the next incremental Start includes it without resetting caches. Check
processing versus analysis exclusion, repeated recordings and inherited
participant scopes, filtered bulk restore, stale-project errors, and closing
while a load/save worker is active.

Verification: `.venv/Scripts/python.exe .agents/scripts/verify.py --scope
processing --tier focused` passed **1,493 tests, 5 skipped**. The equivalent GUI
focused gate passed **246 non-Qt tests**. The 15 new backend regressions and
existing QC/reuse bundle passed **51 tests**; the ledger/expected-output/cache
bundle passed **116 tests, 1 skipped**. The final worker-start exception cleanup
change passed all **13** dialog/worker static tests. Ruff, compilation,
GUI/protected/removed-source audits, independent review, and whitespace checks
passed. The repository precommit gate stops at the same eight unrelated
hardcoded paths under untracked `outputs/`; no new audit findings remain.

Read-only validation against MCCTR returns all **55 participants**: 24 have
only a processing exclusion, five have both processing and analysis exclusions,
and 26 have neither whole-participant exclusion. Processed result files are
available for 24 participants; one participant's condition-specific exclusion appears in its
details. The project manifest remained byte-identical. No actual project
exclusions, raw files, or processed outputs were modified during implementation.

CI-only coverage consists of six tests in
`tests/gui/test_dataset_exclusions_qt.py`, plus the updated manager entry-point
test in `tests/gui/test_gui_preproc_dialog.py`. No local Qt workflow ran; the
visible smoke above is still required for the actual dialog presentation.

Files for this feature:

- Runtime: `src/Main_App/processing/dataset_exclusions.py`,
  `src/Main_App/processing/frequency_domain_qc.py`,
  `src/Main_App/processing/processing_ledger.py`,
  `src/Main_App/gui/dataset_exclusions_dialog.py`,
  `src/Main_App/gui/dataset_exclusions_workflow.py`,
  `src/Main_App/gui/settings_panel.py`,
  `src/Main_App/gui/project_workflows.py`,
  `src/Main_App/gui/toolbox_cache_workflow.py`, and
  `src/Main_App/workers/dataset_exclusions.py`.
- Tests: `tests/processing/test_dataset_exclusions.py`,
  `tests/processing/test_processing_ledger.py`,
  `tests/gui/test_dataset_exclusions_static.py`,
  `tests/gui/test_dataset_exclusions_workflow_static.py`,
  `tests/gui/test_dataset_exclusions_qt.py`, and
  `tests/gui/test_gui_preproc_dialog.py`; registration in
  `.agents/verification.toml` and `tests/qt_test_files.txt`.
- Documentation: `docs/user/index.md`,
  `docs/agent/architecture/project-io.md`,
  `docs/agent/architecture/cache-maintenance.md`, and this active plan.
