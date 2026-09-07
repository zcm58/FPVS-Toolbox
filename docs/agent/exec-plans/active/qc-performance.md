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

Runtime changes are confined to `Shared/settings_manager.py`,
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

Runtime changes are confined to `Shared/load_utils.py`, `gui/main_window.py`,
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
