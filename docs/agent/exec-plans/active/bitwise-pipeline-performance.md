# Bitwise-Equivalent QC and Processing Performance

## Status

The November 2026 MCCTR qualification used the Windows source GUI and private
study data. The [five-change benchmark](#goal-for-the-five-optimizations) and
[incremental benchmark](#goal-for-incremental-mcctr-processing) record
separate acceptance criteria and measured click-to-completion times.

Reviewed 2026-10-18: implementation is integrated, source CI passed, and the
exact published v3 installer passed automated native lifecycle acceptance.
Bounded two-recording comparisons and archived prepared-FHC replay passed.
Broader private fresh-project/full-cohort qualification was stopped at the
user's direction; human visible acceptance remains unclaimed. The
[v3 ledger](v3-release-readiness.md#3-qualify-processing-and-project-compatibility)
owns current evidence and deferrals. Dated implementation records below retain
their original measurement scope and do not reopen completed CI/release gates.

### Dataset indexing and spectral exports

#### Goal for the five optimizations

Measure the combined effect of the five changes below from the real GUI's
Process button through final output publication. Verify the scientific results
against the same project processed by the build without those five changes.
This goal covers both cold and warm processing. The incremental 65-to-69
participant workflow has its own acceptance criteria.

- [x] Implement and individually verify all five changes in the table below.
- [x] Compare cold GUI runs on the same internal SSD with the same worker
  policy, inputs and scientific settings. The first pair completed in 49m 57s
  before and 39m 28s after. All 400 native result manifests and 800 companions
  matched byte for byte. Workbook values, QC decisions and source maps matched.
- [x] Compare the cache-seeded warm GUI runs. Both builds reused all 71
  preflights and all 69 preprocessed recordings, rebuilt all 69 kurtosis
  checkpoints, and missed all 400 participant-condition source spectra for
  each source method. Click-to-ready time fell from 35m 53s to 35m 03s
  (50.10 seconds, 2.33%). The 400 condition exports, published group results,
  source maps and 938 private cache checks matched between builds.
- [x] Record click-to-ready, stage, review and CPU measurements. See below.
- [x] Report the limit on attributing the cold saving. The two runs spent
  15.55 s and 118.80 s waiting on measured preflight choices, and host CPU
  utilization averaged 35.39% and 48.93%. A matched-control cold repeat
  remains an optional follow-up for stronger attribution.

| GUI stage | Cold before | Cold after | Cache-seeded before | Cache-seeded after |
| --- | ---: | ---: | ---: | ---: |
| Preflight | 4m 09s | 4m 02s | 18s | 15s |
| Kurtosis preparation and review scan | 11m 20s | 10m 05s | 11m 56s | 11m 54s |
| Recording workers | 12m 46s | 10m 20s | 1m 51s | 1m 20s |
| Downstream workers | 20m 24s | 11m 29s | 20m 26s | 20m 14s |
| **Process click to ready** | **49m 57s** | **39m 28s** | **35m 53s** | **35m 03s** |

All four real GUI runs used the internal SSD and a 16-worker ceiling.
Mean workstation CPU use was 35.39% before and 48.93% after on the cold pair.
The cold preflight prompt waited 15.55s before and 118.80s after. These host
and operator differences limit causal attribution of the observed 21.0% cold
reduction. CPU use on the warm pair averaged 22.95% before and 23.43% after.

Windows source comparisons on 2026-11-20 used synthetic inputs and the existing
checkout at `1ed0bdf2`. Each measurement covers the named operation.

| Change | Before and after | What the comparison checked |
| --- | --- | --- |
| Build the recording-ID lookup once per scan | 800 filenames and 200 recording IDs required 160,000 case-fold operations before and 200 after. Matching took 11.96 ms and 1.89 ms respectively. | Exact recording IDs, including mixed case. |
| Reuse frequency and candidate-bin labels | At 64 channels and 50 targets, each of the two formatting operations runs 50 times per FFT input, down from 3,200. | Four paired exports produced identical native manifests, both NumPy companions and 3,200 ordered QC rows per export. Registered replacement methods retain their own candidate-bin text. |
| Reuse confirmed export success | Finalization skips one recursive snapshot. With 256 existing result anchors its median time fell from 41.1 ms to under 0.01 ms over 11 paired trials. | Unconfirmed runs still distinguish new, overwritten and unchanged outputs and retain filesystem errors. |
| Assemble complete spectral sheets from one detached matrix | A cached complete read of 64 electrodes × 8,192 bins took 36.67 ms before and 8.03 ms after over 21 paired trials. | Float bits, column layout, electrode order, metadata and isolation from caller edits. |
| Prune ignored directories below the selected scan root | With one eligible and 24 ignored workbooks, directory enumerations fell from 56 to 4. Included folders retain both the initial listing and the later enumeration for descent. | Ordered records and diagnostics, direct file and root selections, native sibling precedence, NTFS junctions and errors in included folders. |

The two skipped directory scans no longer surface errors observable only by
those scans. Companion verification, processing receipts and scientific
calculations retain their existing checks.

#### Goal for incremental MCCTR processing

Measure three real GUI workflows using the same scientific settings and the
RAM-tier worker policy. A completed 65-recording project gains four recordings,
a completed 69-recording project runs again without changes, and a full cold
69-recording run supplies the reference.

- [x] Verify the 65 original recordings keep their original export receipts and
  byte-identical results when their inputs and approved decisions still apply.
  Record every original that requires new work and why.
- [x] Compare all 400 eligible condition results, cohort QC decisions, harmonic
  selections and source maps to the full cold reference. Check exclusions and
  unavailable conditions separately.
- [x] On the unchanged repeat, measure click-to-ready time and count actual
  recording jobs, checkpoint rebuilds and regenerated outputs.
- [x] Qualify source-spectrum reuse for the 376 original cells per method,
  then measure its effect in a real GUI addition with valid prior evidence.

The historical cold and warm preparation keys differed on all 69 recordings.
Reconstructing the original headers isolated the BIDS identity-check clock as
the only differing input on MCCTR. On P1, the revised key reused the prepared
recording in 1.57s after a 16.12s cold preparation. Its 15,841,280 float64
samples, events, evidence and five authorized channel decisions matched the
uncached calculation exactly. This timing covers one recording's preparation.
In a separate real GUI launch with the worker override set to Auto, the
128 GB workstation selected 16 and recorded 16 concurrent preflight threads.

The initial 65-person GUI project published 376 condition manifests identical
to the matching files in the full cold 69-person reference. Its group harmonic
Z scores changed with cohort size, while the selected frequencies stayed at
1.2, 2.4, 3.6, 4.8 and 7.2 Hz. Across L2-MNE and eLORETA, all 752 original
participant-condition results matched the cold 69-person reference for all
4,512 typed source vectors, frequency and channel order and rank diagnostics.
These are direct numerical comparisons. Reuse across cohorts additionally
requires matching the actual input waveform, numerical model and runtime.

The first 65-to-69 GUI attempt dispatched exactly four recordings. Five of
seven downstream steps succeeded. Both source producers correctly rejected an
unchanged recording whose signed preprocessing identity belonged to the prior
plan. Step 7 also replaced the project review workbook with the 1,625 new
flags. Its corrected project writer reproduced all 22,619 ordered review
rows and workbook styles from the archived 65-person and four-person reports.
The visible review still presents only the four current recordings. All 400
condition manifests matched the cold reference byte for byte. The QC summary
overcounted removed electrodes for 45 retained participants because its
fallback included kurtosis candidates the user had rejected. The ledger
retained their original counts. The corrected source reader authenticated all
65 retained recordings and accepted all six original P1 condition FIFs in a
native replay. The subsequent GUI run from the original 65-person state
tested both source methods and the corrected project workbooks.

In the original build, adding four classified the 65 completed recordings as
changed. The GUI prepared all 69 recordings for kurtosis in 602.51s and ran
all 69 processing jobs in 83.24s, with 65 preprocessed FIF hits and four new
files. The original and full-cold reviews returned the same 250 channel
decisions. The six previously excluded recordings kept their no-output
status, with different provenance for those decisions. Both source methods
computed their results and failed the final publication check because the
live project and the saved manifest listed identical participants in
different orders. A native replay reproduced this failure and verified that
the corrected check accepts a reordered list and rejects changed membership.
Participant averaging already uses sorted ledger IDs.

On the immediately following click with no new data, the original build
again prepared all 69 recordings (599.72s), dispatched 58 recording jobs
and then stopped at frequency-domain review. The 11 skipped recordings
still had condition outputs, but the new plan required 63 new export
receipts. The benchmark records time to both failure states separately from
times to a successful, fully published project.

The corrected GUI published all seven downstream products after adding the
four recordings in 24m 02.26s. Exactly four recording workers produced the
24 new condition outputs. Both source methods recalculated all 400
participant-condition spectra and published group maps. Clicking Process again
on the same 69-record project took 24.60s, including 23.38s to validate the
existing project. It launched no preflight, preparation, recording or
downstream jobs. The project manifest and processing ledger matched their
pre-click SHA-256 values.

With cross-cohort source reuse enabled, the same four-recording addition took
22m 06.37s from the Process click through all seven downstream products,
1m 55.89s (8.04%) faster than the successful 24m 02.26s run. Each source
method reused 376 participant-condition spectra and calculated the 24 new
ones. Capturing the reuse evidence cost 9.00s in the separate initial-65
source-stage comparison and saved 124.36s across both source stages on
expansion. The final unchanged click took 24.42s, including 23.43s in
validation, and launched zero processing jobs. These timings use the
Windows source-launched GUI on the internal SSD with a 16-worker ceiling.
Independent readback of the final archive matched the full cold 69 for all
400 native manifests, 800 companions, 400 source time series, 800 source
spectra, and the scientific content of all 72 source maps and the Stats/QC
workbooks. All 376 original export receipts were preserved. Published maps
carry the new run's provenance and observed cache counts.

Compared with full cold 69, the corrected incremental run retained all 376
original export receipts. All 400 native manifests and 800 companions matched
byte for byte. All 400 source FIFs and 800 source PSDs matched scientifically,
as did the 72 published group maps, their participant vectors and masks,
the Stats workbooks, the 75-row QC summary and all 22,619 review flags.
The independently verified run-specific references belong to each project's
own processing ledger. The original build's 65 reprocessed participants
produced numerical differences in all 376 original condition outputs.

#### Group harmonic validation

The first 400-condition audit found each request hashed 800 companions
covering 5,053,537,880 bytes. Two consecutive builds took 11.26s and 16.25s.
The processing worker now uses the request built after frequency-domain
exclusions for its in-memory key, saved-selection lookup and canonical
metadata. It builds a fresh request before publishing the staged workbook
and active selection. An intervening manifest change triggers a retry under
the project lock. The provisional and standalone selection paths keep their
independent workbook checks.

On the internal SSD, each MCCTR stage run verified 1,600 fewer companion
digests and read 10,107,075,760 fewer bytes for hashing. Both builds emitted
the same processing-version warning, so the subsequent independent check
for the memory key remained active. Forced recalculation across the 400
participant-condition spectra, including workbook and manifest publication,
took 241.36s before and 199.87s after (41.48s saved, 17.19%). Every score,
mask, selected frequency and input/selection fingerprint matched. Only the
generated save and packaging timestamps differed.

Revalidating a saved selection, from stage entry through publication, took
136.30s before and 100.50s after. Running the builds in reverse order gave
133.07s before and 98.99s after. Across the two pairs the mean fell from
134.68s to 99.74s (34.94s saved, 25.94%). For both saved pairs and the
forced pair, the complete project JSON serialized to identical bytes after
substituting the verified save timestamps. Workbook members and scientific
cells also matched after accounting for those timestamps and workbook
creation times. These measurements cover the harmonic stage of MCCTR
processing on the 128 GB workstation.

#### Paired source-map publication on MCCTR

The paired source-stage benchmark starts inside the desktop processing
worker and ends after both methods publish. Each run used a fresh Python
process, the same project path on the internal SSD, 69 participants, 400
eligible participant-condition cells and the workstation's 16-worker ceiling.
All 400 participant PSDs for each method were available in the primary
cache. The harmonic-validation cache started empty and both methods rebuilt
their group maps and statistics.

Each publication pass now hashes a shared participant manifest once and
checks the digest declared by every condition. The two producers can also
share validated QC evidence after independently checking the native results,
the spectral and condition companions, and the live project state. A primary
PSD lookup prepares the canonical scientific key once and compares its bytes
with the stored key. The on-disk key format and the verification of the
numerical arrays are unchanged.

| Elapsed seconds | Before | Manifest and QC changes | With cache-key change |
| --- | ---: | ---: | ---: |
| L2-MNE | 159.40 | 154.01 | 143.50 |
| eLORETA | 133.79 | 132.32 | 121.87 |
| Both stages, including publication | 293.23 | 286.37 | 265.41 |

This three-run comparison saved 27.82 seconds overall (9.49%). The full
harmonic check inside L2-MNE fell from 62.86 to 54.93 seconds and eLORETA's
fell from 21.61 to 4.78 seconds. Participant-manifest checksum reads fell
from 1,600 to 276 across the four verification passes. The new integrity
check read 400 native result files and 800 companions at each method. Bytes
observed through the coordinator's streaming digest increased from 26.09
to 28.32 GB. These counters measure bytes supplied to the hashing API.
The two timing differences come from consecutive individual runs.

Across all 800 hits, preparing the requested key once reduced serialization
from 2,400 passes to 800, saving 606,109,600 bytes of serialization. A
separate alternating-order lookup benchmark used eight real cells per method:
L2-MNE primary lookup took 0.2833 seconds before and 0.1861 after, and
eLORETA took 0.2357 and 0.1496. Reading a qualified cross-cohort origin
took 0.2568 and 0.1577 seconds for L2-MNE and 0.2503 and 0.1517 for
eLORETA. Those figures cover the eight lookups together. Numerical runtime
qualification initially read 20 implementation files (48,922,550 bytes).
Repeated checks reopened zero implementation files for content.

Independent readback matched all 800 primary numerical archives and their
800 metadata files byte for byte. All 4,800 typed arrays, the 800 rank
records, all 72 published maps, their masks, p-values and participant exports
matched exactly. All 84 publication files verified against their own release
receipts. Four publication files matched byte for byte across releases.
The others carried new run identifiers, timestamps, or checksums derived
from those fields.

As a negative control, a writer changed a spectral companion while keeping
its handle open and restoring the original size and modification time. Its
file identity also stayed the same. Both builds rejected the affected
condition with the same QC release error before the second method could
publish.

Existing primary entries retain their keys across the update. Cross-cohort
reuse also verifies the installed numerical implementation. An older build's
certificate requires fresh qualification under the new build on a primary
miss.

#### Forced full reprocessing across cache temperatures

Both builds' full warm reprocess reused all 69 preprocessed FIF files.
Their ordinary cache writer uses MNE's single-precision default, while the
cold calculation uses float64. A native replay on P1 reproduced the warm
samples with single precision and all 5,898,624 cold FFT bins with double
precision. All 400 condition exports differed across temperatures on both
builds, with identical selected harmonics. The warm processing ledger also
lost the per-recording kurtosis evidence and decision plan for all 69 inputs.
The prepared checkpoint sample arrays remained identical across temperatures.

### Adaptive QC-16 process preparation (2026-10-13)

The user authorized replacing the GUI's serial kurtosis preparation with a
modular multicore implementation that scales across CPU designs. A live Birth
Control 2 scan selected one recording job from a transient prefetch snapshot
and retained it after loading finished. Its first six complete recordings had
median raw diagnostics of 11.61 s and preparation/evidence of 29.12 s, while
the kurtosis calculation itself took about 0.30 s. The scan was cancelled safely;
these partial observations are not a RAM-preload comparison.

- [x] Add a review-only spawned pool reusing the normal worker initialization,
  native thread policy, private memmaps, FIR cache and shared preparation.
- [x] Size concurrency from CPU capacity, main RAM tiers/override, and half
  available RAM using conservative recording-size estimates; retain a one-job
  fallback for constrained hosts and preserve excluded/error accounting.
- [x] Keep GUI review, interpolation authority and exports outside review jobs;
  avoid unusable parent source staging, preserve cancellation and input order.
- [x] Bind prepared checkpoints to native library/thread identity. Characterization
  found a maximum 2.1684e-19 V sample difference between native 1/24-thread
  preparation; cross-policy float/evidence bytes are not an equivalence claim.
  Serial and concurrent processes under the same one-thread policy, and FIR
  cache miss/hit preparation, match exact scientific bytes in synthetic tests.
- [x] Complete local verification: processing focused 2,158 passed/6 skipped;
  GUI static checks passed; broad precommit audits, Ruff and compilation passed,
  with 5,441 pytest cases passed/24 skipped and one Windows `WinError 5` during
  an unrelated temporary-file replacement. The complete affected test module
  passed on immediate rerun (4 passed); the broad command itself remains failed.
- [x] Visible Birth Control 2 preparation smoke: spawned two review workers,
  remained responsive before Windows locked, and completed 58/58 jobs without
  cancellation. OFF preparation took 1,099.684 s; sampled peak process-tree RSS
  was 6.542 GiB, maximum active workers 2, and mean per-worker CPU 93.54% of one
  core. This is one preparation phase, not a completed OFF/ON comparison.
- [x] Complete the superseding native comparison at a requested 12-worker ceiling:
  starting versus final code with RAM OFF, and final code with RAM OFF versus ON,
  with compute time, peak RAM, worker use and exact full/checkpoint proofs recorded.
  Primary L2-normalized SNR FHC and the exploratory raw-BCA companion also completed
  on the approved common cohort/domain. See the
  [final performance and analysis report](../../reviews/pipeline-bitwise-performance-report-2026-10-15.md).

The new pool owner is `src/Main_App/workers/kurtosis_review_process.py`;
`processing/kurtosis_review_scan.py` owns classification and legacy thread
compatibility, and `gui/preprocessing_qc_workflow.py` selects process execution.
No preprocessing order, statistical profile, raw recording, condition, trigger,
or output format is changed. Architecture docs record the scheduling ownership
and exact-checkpoint guard; the user-method contracts do not change.

The 2026-09-08 follow-up starts from `164e6dce` on a new branch,
`codex/bitwise-performance-followup`, created from `codex/preprocessing-qc-v3`.
The user authorized implementation of the investigation's fingerprint hoist,
ledger-only validation reuse, sparse/dense FHC guard, and reviewed FIR kernel
integration, with exact parity/fallback tests and representative timing.
After reviewing the exact-parity results, the user authorized committing this
follow-up, merging it into `codex/preprocessing-qc-v3`, and pushing that branch.
Pre-existing untracked `outputs/` remains untouched. Scientific methods and
output contracts are fixed.

- [x] Hoist the frozen condition-eligibility fingerprint after its existing
  guard; preserve every numerical calculation and exported row.
- [x] Add exact baseline characterization and a sparse/dense FHC scan guard;
  retain union, component, summation, assignment and progress order.
- [x] Finish bounded ledger-only reuse and concurrent-change review.
- [x] Finish the isolated FIR adapter's final native-thread invalidation guard.
- [x] Confirm focused checks and project timings after that final guard.

### 2026-09-08 measurements and review

Benchmarks use the repository `.venv` (CPython 3.13.9, MNE 1.9.0,
NumPy 2.3.1, SciPy 1.16.0) and frozen base `164e6dce` on Windows.
CPU-heavy timing runs are serialized. Cold means application-cache miss/new output;
the OS file cache is not flushed. Scratch reproducers and receipts are under
ignored `.codex-tmp/perf-next/`. Real project access rejects writes with an
audit hook. The stage timings and complete processing-batch measurements below
are separate observations, not aggregate full-GUI workflow claims.

| Actual implementation | Baseline | Changed | Evidence |
| --- | ---: | ---: | --- |
| Condition export, new output (3 paired trials, median) | 1.586 s | 0.583 s | Native arrays, declarations, logs and input bytes exact |
| Condition export, unchanged repeat | 1.563 s | 0.567 s | Same oracle |
| Condition export, changed input | 1.584 s | 0.549 s | Same oracle; refreshed values |
| MCCTR selection + Stats-ready preparation, fresh scope | 29.022 s | 26.160 s | 24 participants, 6 conditions, 432 rows; all 4 frames exact |
| Same complete-cohort operation, warm scope | 15.771 s | 12.754 s | Numeric dtype/shape/order/bytes and manifest SHA unchanged |
| FHC independent contrast, 10,000 assignments | 8.832 s | 1.083 s | 18+16 participants, 64 sensors, 6 harmonics |
| FHC paired contrast, 10,000 assignments | 12.240 s | 0.812 s | 18 participants, same geometry/domain |
| Full preprocessing helper, prepared FIR miss | 14.502 s | 15.168 s | 120 s, 67 source channels, 2048 Hz; 67,585-tap kernel |
| Full preprocessing helper, prepared FIR hit | 14.502 s | 2.527 s | Exact full Raw state, scientific settings, logs, QC count and untouched input |

The MCCTR, FIR and 10,000-assignment rows are single confirming before/after pairs.
The FIR miss is not a speedup claim; only later identical coefficient kernels
within the same worker batch benefit. The cache retained 1,622,032 buffer bytes
and zero after close. The helper timing excludes source loading and export.
It used the shell's native-thread configuration, not the spawned worker's
thread limits; its roughly 12-second saving must not be extrapolated to workers.
The FHC density matrix used five paired trials at 2/6/24 harmonics and
1/5/10/50/100% density. At 1% density it was 7–17x faster; dense fallback
differences ranged from -0.5% to +1.6%, consistent with timing noise.
FHC parity covers all scientific result fields and array bytes, RNG identity,
union order, all 41 progress callbacks, errors and cancellation; elapsed timing
fields are intentionally not compared. Explicit XLSX parity compares all
decompressed ZIP members, normalizing only core container timestamps, so
values, ordering, sheets, styles and dimensions must match.

Reproducers: `exports/verify_implementation.py`,
`benchmark_ledger_implementation.py`, `downstream/bench_fhc_final.py` and
`downstream/bench_fhc_guard.py` under the scratch root. Independent FIR review
reproduced stale behavior after altered MNE defaults or NumPy's native
correlation operator; strengthened guards now fall back with exact public-MNE
bytes in both cases. A ledger ABA regression fails without the immutable
snapshot and passes with it. No scientific method fingerprints were changed.
The FIR helper reproducer and receipt are `raw/benchmark_production_fir.py`
and `raw/production-fir-results.json`.

Final worker-environment review also reproduced different coefficient
convolution bytes at BLAS thread counts 1 and 2. Native library/thread identity
is now part of the kernel key, with unknown configurations bypassing
reuse and visible mid-call changes preventing admission. It does not change
thread counts; active worker ownership keeps that policy stable. An uncontrolled
external change and restoration during a native call cannot be made atomic by
before/after snapshots and is outside this worker contract. Stable thread
changes, missing NumPy-pool identity and changes observed during convolution or
hit detachment now have regression coverage. The final guard passed 79 focused
FIR/filter-order/runner checks and the fresh batch comparisons below.
Worker-configured direct kernel construction measured about 0.92 seconds,
which is the relevant reusable cost here, rather than the earlier roughly
12-second default-thread estimate.

The actual `run_project_parallel` benchmark used four immutable synthetic
BioSemi BDF recordings, each 120 seconds at 2048 Hz with 64 scalp channels,
two references and stim, two 50-second analyzed conditions, and two spawned
workers. Baseline workers loaded the frozen source overlay; changed workers
loaded this branch. Per-worker source hashes confirm both. The timer includes
pool startup, BDF/cache loading, preprocessing, epochs, native condition
exports, source-ready FIF output and worker shutdown; fixture generation,
post-run comparisons, interactive preflight review and optional downstream
tools are excluded. Native BLAS used one thread per worker.

| Complete four-recording batch | Baseline | Changed | Reduction |
| --- | ---: | ---: | ---: |
| Cold application caches | 17.416 s | 14.599 s | 16.2% |
| Warm preprocessed-Raw cache | 6.853 s | 4.697 s | 31.5% |
| Cutoff invalidation, 50 to 45 Hz | 16.653 s | 13.836 s | 16.9% |

Each row is one confirming pair with `PYTHONHASHSEED=0` in both runs. This
controls pre-existing set-derived receipt ordering between spawned processes;
receipt list ordering is compared exactly, not normalized away. All pairs
matched ordered NPZ members and array dtype/shape/strides/bytes, complete FIF
container SHA-256 and sample bytes, source JSON bytes, native manifests and
scientific result/audit/receipt ordering. Only generated output-root/file-time
identity and elapsed fields are normalized in runtime receipts; original
receipt fingerprints are independently verified against their own artifacts.
The common BDF hashes stayed unchanged. Each cold/invalidation worker had one
FIR miss and one hit; warm-Raw runs had neither. All worker caches closed with
zero retained bytes. Reproducer: `exports/whole_project_benchmark.py`; fixtures,
frozen overlay, case receipts and worker audits: `exports/whole_project/`.
The final comparisons use `threadguard_{cold,warm,invalidation}_comparison.json`
and `baseline_threadguard`/`current_threadguard` output roots, and record the
final `prepared_fir.py` source hash in each changed worker. These timings
supersede the preliminary fixed-seed runs before native-thread guarding.

The production changes are limited to:

- `exports/post_process.py`: local eligibility-fingerprint hoist.
- `processing/frequency_domain_qc.py` and `post_processing_context.py`:
  ledger snapshot, bounded scoped admission and detached reuse.
- `Tools/Free_Harmonic_Clustering/analysis.py`: empty-node scan guard.
- `processing/prepared_fir.py`, `processing/preprocess.py` and
  `workers/process_runner.py`: isolated MNE adapter and batch-worker owner.

The `processing/`, `exports/` and `workers/` paths above are under
`src/Main_App/`. Four focused test modules characterize the changed behavior;
the processing verification registry includes the new ledger/FIR modules.
Those modules are `tests/processing/test_post_process_output_receipts.py`,
`tests/processing/test_independent_qc_context_reuse.py`,
`tests/processing/test_prepared_fir.py` and
`tests/free_harmonic_clustering/test_sparse_cluster_parity.py`.
Architecture updates document cache ownership and unchanged processing/graph
contracts. No user-method update is required because no method changed.

Visible/manual smoke for this follow-up remains intentionally unrun locally:
process multiple files with two workers, verify successful condition outputs,
repeat to exercise the existing preprocessed-Raw cache, change a cutoff to
invalidate it, and cancel/restart a batch to check responsiveness and fresh
worker ownership. Continue an accepted frequency-QC review into standard
exports and run an FHC contrast; check current provenance and normal progress.
Run this only in a safe visible app session or CI; no local offscreen Qt or
Standalone_Scripts access is permitted. CachyOS and frozen-installer timing
remain unverified; uncharacterized FIR runtimes deliberately fall back to MNE.

Verification: `verify.py --scope processing --tier focused` passed
1,842 tests with 5 skips; `--scope stats --tier focused` passed 442;
`--scope legacy-boundary --tier focused` passed 4, and the final
`--scope repo --tier focused` passed 18. The complete registered
non-Qt FHC bundle passed 239 tests, including 88 new exact cases. The FIR
module was rerun after strengthening direct sample-buffer assertions: 32
passed. After the final native-thread guard, FIR plus processing-order and
runner-contract checks passed 79 tests (36 FIR and 43 order/runner).
Relevant Ruff, compilation, protected-boundary and source-localization
audits passed. `verify.py --scope repo --tier precommit` and the FHC focused
driver still stop at the same eight pre-existing hard-coded-path findings in
untracked `outputs/`; their blocked gates are not reported as passing.
Transcripts are `processing-implementation.txt`, `stats-implementation.txt`,
`legacy-implementation.txt`, `fir-final-tests.txt` and
`precommit-implementation.txt` under the scratch root.

### 2026-09-07 completed follow-up

The 2026-09-07 follow-up starts from `593b358c` on
`codex/preprocessing-qc-v3`. The user approved implementing the first three
findings from the MCCTR post-processing investigation: numerical source-cache
reuse across selection-fingerprint-only changes, bounded accepted-selection
and release validation reuse, and unchanged provisional QC evidence reuse
across review. Commit and push after exactness, invalidation and performance
checks. Existing untracked `outputs/` path-audit findings remain outside scope.

Follow-up execution:

- [x] Normalize participant source cache identities without changing source
  arrays or current output provenance; safely reuse compatible existing caches.
- [x] Reuse validated selection/release state within bounded export operations,
  retaining replacement, decision, settings, cohort and caller-mutation guards.
- [x] Reuse provisional scientific evidence across review only when all its
  inputs remain identical; always apply the current review decisions.
- [x] Verify exact output parity and stale/corrupt/missing input handling,
  measure representative-project latency, document visible smoke and commit.

### Follow-up implementation and measurements

The source-PSD identity now excludes the project-wide selection fingerprint
alongside the three existing selection-cache annotations. Exact derivative,
inverse-model, method, harmonics and FFT-bin identities remain mandatory. Both
public producers use a bounded compatibility index scoped to that export
(shared across the worker's two source-map modes);
historical metadata must validate under its original key and the complete
normalized current key, and every hit revalidates the numerical archive.
Existing cache files remain usable without migration or deletion. Newly
published source manifests carry the current selection fingerprint.

Accepted selection and release validation are scoped to the worker's
QC/selection/workbook phases or one standalone export operation. Nested
consumers reuse detached validated results. Live semantic manifest, canonical
dataset/cohort, ordered ROI/profile/protocol/condition inputs and current review
decisions remain checked. Ledger and anchor SHA-256 checks detect same-stat
in-place edits; companions retain the existing verified-reader policy with
additional replacement identities. Only artifact-freshness publication is
ignored in the selection key. No retained validation survives scope exit.

The provisional evidence cache is an explicit two-entry object passed through
the GUI review/save/resume flow and cleared when that flow finishes or fails.
Its key includes ordered numerical inputs and actual anchor/companion bytes.
Only the unchanged provisional calculation is reused; all current report,
exclusion, integrity and release steps still execute. The calculation's body
and statistical methods are unchanged.

Representative MCCTR checks used its current 24 participants, six conditions
and 143 available source cells. Measurements are affected-stage observations,
not a full-pipeline timing claim:

- All 286 historical L2-MNE/eLORETA source-cache requests hit compatible
  entries. Every returned array matched the corresponding original array
  bytes exactly. The read-only lookup plus independent comparison took 15.8 s;
  no source inverse computation or project write was performed.
- A read-only outer selection load plus actual Stats-ready preparation used
  the same project-manifest SHA-256 at baseline `593b358c` and after these
  changes. Two fresh-operation runs took 52.483/45.195 s before and
  29.358/29.352 s after: median 48.839 to 29.355 s, 39.9% less time (1.66x).
  All four export frames matched exactly in values, ordering and dtypes;
  every numeric column also matched byte-for-byte. The current project
  produced 432 long-format rows. Repeated runs matched exactly too. Benchmark
  audit hooks rejected all project writes; only scratch receipts were saved.
- Provisional harmonic calculation took 36.413 s on the unchanged path,
  39.359 s on the cache miss including content validation, and 2.001 s on the
  resumed hit. Exact scientific metadata, container ordering and float bits
  matched; only existing transient cache annotations were excluded from that
  benchmark comparison. Native and historical-source regression tests also
  compare entire current QC reports and exported report text after Retain or
  condition-exclusion decisions.

Verification: processing focused gate 1,783 passed and 5 skipped; GUI focused
gate 395 passed; Stats focused gate 442 passed; complete non-Qt LORETA suite
333 passed; repo focused gate 18 passed; worker orchestration checks
27 passed, including scope disposal on completion, review pause and exception,
and shared source-index disposal after either successful or failed exports.
Ruff and compilation passed for changed code. The broad command
`python .agents/scripts/verify.py --scope repo --tier precommit` stops at eight
pre-existing hard-coded-path audit findings in untracked `outputs/` content,
before its test phase. That unrelated content is preserved and excluded from
this commit. Focused/direct non-Qt suites provide the applicable validation;
this is not a claim that the blocked broad gate passed.

Visible/manual smoke remains intentionally unrun locally: in a visible Main
App session, run a representative project through frequency-domain QC, retain
unchanged findings and continue. Verify one provisional-cache hit on resume,
responsive controls, successful standard Stats/full-audit workbooks and both
source exports with current provenance. Repeat with a condition exclusion to
verify a miss/current report, then cancel review and verify a later run starts
with fresh evidence. Confirm no pending source/validation state crosses the
end of a workflow. Local checks execute orchestration without Qt; Qt execution
remains CI-only unless a safe visible session is explicitly approved.

Historical branch context: the original pipeline work was developed on
`codex/finalize-multi-group` and the post-processing extension on
`codex/finalize-multi-group-postprocess-speedups` from `72dbd412`. Both are
present in the 2026-09-08 investigation baseline `c4466582`. The visible
representative-project smoke above remains unexecuted; it is a validation
limitation, not an unimplemented extension. The next bounded QC changes are
tracked in [QC Performance](qc-performance.md).

## Goal

Reduce cold- and warm-run latency for raw QC, preprocessing support work,
post-processing QC, and workbook export without changing scientific values,
processing order, project layout, workbook cells, sheet names, or user flow.
Favor changes that also reduce random reads and small writes when a project is
stored on a rotational, removable, or otherwise slow drive.

## Equivalence Contract

- Floating-point scientific arrays must retain dtype, shape, order, and exact
  element bytes. Tolerance-only parity is not sufficient.
- The locked preprocessing order, filter parameters, 256 Hz target, FFT crop,
  noise-bin rules, harmonic selection, and exclusion rules remain unchanged.
- JSON payload values, workbook cell values/order, worksheet names, column
  widths, and freeze-pane behavior remain unchanged.
- `.xlsx` container bytes are not a useful equivalence oracle because
  XlsxWriter records creation/modification timestamps. Compare worksheet
  content, styles, dimensions, and ZIP members after excluding normalized core
  timestamps.
- Generated files remain beneath the active project root. A system-temporary
  staging file may be used only as an ephemeral write buffer; publication to
  the project uses a same-directory temporary file and atomic replacement.

## Ranked Opportunities

| Rank | Candidate | Expected benefit | Risk | This branch |
| --- | --- | --- | --- | --- |
| 1 | Direct pre-open lookup for a valid full preflight-QC cache entry | Very high on repeated QC, especially HDD | Moderate; needs a versioned coarse-to-full cache index | Deferred until the cache-index design is separately characterized |
| 2 | Reuse identical selected XLSX reads during one post-processing worker run | High; avoids repeated ZIP/XML passes in provisional QC, harmonic selection, and Stats-ready export | Low when scoped to one immutable run and keyed by path/size/mtime | Implemented; a synthetic 4.0 MiB wide workbook improved a two-read sequence by 1.84x |
| 3 | Replace per-participant full cache-directory scans with one indexed scan; restrict stale-cache pruning to the source stem | High for large projects on HDD; removes quadratic metadata reads | Very low | Implemented; 100 participants reduced 10,000 JSON reads to 100 and measured 55x faster locally |
| 4 | Build cross-drive workbooks on the system drive, then publish with one sequential copy and atomic replace | High on external/rotational project drives | Low to moderate; requires cleanup and publish-failure coverage | Implement |
| 5 | Combine QC percentiles for safe finite native-float64 inputs while retaining the exact scalar fallback for zeros, non-finite values, extreme magnitudes, and other dtypes | Moderate QC-stage gain | Low with byte-, exception-, and warning-exact regression tests | Implemented; representative 64-channel QC bundle measured 23.34% less time |
| 6 | Compute identical Excel column widths in column blocks instead of one pandas conversion per column | Moderate export CPU gain | Very low | Implemented; 64 x 12,000 benchmark measured 2.83x faster |
| 7 | Avoid an unconditional float64 epoch-array copy before the unchanged mean | Low to moderate memory-bandwidth and peak-RAM gain | Very low | Implemented for native-float64 C/F-contiguous arrays; every other layout retains the established copy |
| 8 | Batch FFT multi-notch transforms over a memory-bounded channel block | Moderate; measured about 1.4-1.7x for that stage | Moderate memory/oversubscription risk in multi-process runs | Deferred pending representative recording-length profiling |
| 9 | Serialize or pipeline main-run BDF reads per physical rotational device | Potentially very high on HDD cold runs | Moderate; hardware detection and workload interaction need real-drive measurements | Deferred for device benchmarking |
| 10 | Reuse condition epoch means between workbook and source-ready export | Moderate | Moderate; current bad-channel pick semantics differ | Deferred |

## Post-Processing Extension

| Rank | Implemented change | Measured affected-stage benefit | Exact fallback |
| --- | --- | --- | --- |
| 1 | Write guarded finite-float64 metric-sheet bodies with XlsxWriter after pandas creates the exact headers/styles | 1.59-1.68x for a representative 64 x 5,001/6,001 sheet | Pandas writes every mixed, non-finite, non-float64, or nonstandard frame; `FFT and neighbors` always uses pandas |
| 2 | Calculate only the FullSNR prefix required by the exported interpolation grid | 6.31x for 64 x 32,001 input bins retaining 6,001 bins; 5.33x smaller working set | Multiple data objects retain complete-spectrum accumulation |
| 3 | Reuse one immutable project dataset index across the three downstream workbook-discovery phases | 2.70x for discovery over 384 synthetic processed workbooks | Standalone calls load a fresh index; a mismatched project root is rejected |
| 4 | Batch exact neighboring-bin target noise reductions across channels | 20.98x for 64 channels x 20 targets | Unsafe magnitude, dtype, layout, non-finite, zero, or constant-window inputs retain the scalar channel/target loop |
| 5 | Build a canonical Stats-ready wide matrix by validated reshape | 46-90x for the reshape helper | Any key-grid, order, length, or dtype mismatch retains the merge sequence |
| 6 | Hoist invariant harmonic-selection sets and batch guarded FullFFT column means | 83-235x for map construction; roughly 45x for representative means | Irregular/missing/non-float64/non-finite/signed-zero/overflow-risk columns retain scalar means |
| 7 | Select real MNE EEG data without deep-copying the entire object | 2.02x for Evoked picking and 2.76x for Epochs picking | Custom objects and empty selections retain `copy().pick(...)` |

## Explicitly Rejected

- Replacing `np.fft.fft(...)[positive_bins]` with `np.fft.rfft(...)` is faster
  but not bitwise equivalent in the pinned NumPy runtime.
- Reordering filtering/downsampling or changing FIR duration is outside scope.
- Axis-wide v2 QC percentile batching is not used: it was slower for long
  condition buffers in local measurements.
- Unscoped, process-lifetime workbook caches are not used because stale data
  and unbounded memory would violate the run-level equivalence boundary.

## Implementation Phases

1. Add exact-output characterization tests and microbenchmark the selected
   helpers in the pinned environment.
2. Land metadata-scan and QC-metric changes.
3. Land run-scoped workbook reuse and cross-drive export staging.
4. Run focused processing, Stats I/O, worker-static, project-I/O, protected
   boundary, and repo precommit gates without local Qt execution.
5. Record measured helper-stage gains, residual risk, and visible/manual smoke
   steps.

## Measurements

- The metadata benchmark used 100 exact cache identities and 100 JSON files.
  The former per-participant scan performed 10,000 JSON reads and took a
  5.118 s median; the run index performed 100 reads and took 0.093 s
  (55.05x). This is an OS-warm local-disk microbenchmark, not an end-to-end
  processing claim.
- The XLSX benchmark used 64 rows by 5,001 columns (4.0 MiB) and selected 251
  columns twice. The unscoped pair took 1.222 s; a scoped miss plus exact
  defensive-copy hit took 0.665 s (1.84x). The hit itself took 0.42 ms versus
  610 ms for a second parse. Exact DataFrame values, dtypes, numeric bytes,
  object values, columns, and index were checked.
- Block column-width calculation preserved the scalar width tuple and improved
  from 1.718 s to 0.607 s for a 64 by 12,000 mixed-width frame (2.83x).
- Representative finite per-channel QC metric calls measured 1.19-1.81x
  faster before the exhaustive edge-layout audit. With the final signed-zero,
  warning, and overflow guards, the representative 64-channel QC bundle
  measured 0.0935 s to 0.0717 s (23.34% less time, 1.304x). Inputs outside the
  safe vector path retain the prior scalar operations exactly.
- A representative affected-stage bundle used 48 participants across three
  groups, a 64 by 5,001 FullFFT workbook read twice, the 64-channel QC bundle,
  a 64 by 12,000 width frame, and a 96.5 MB contiguous float64 epoch array.
  Component medians totaled 3.5737 s before and 1.3668 s after: 61.75% less
  elapsed time, or 2.615x faster. This is not a universal end-to-end pipeline
  claim: unchanged BDF loading, filtering, FFT work, and most workbook
  serialization were outside the bundle. By Amdahl's law, if these affected
  stages were 10%, 25%, 50%, or 75% of an actual baseline run, the whole-run
  elapsed-time reductions would be 6.18%, 15.44%, 30.88%, or 46.31%,
  respectively.
- A representative 4.16 MiB workbook assembly issued 189 non-empty writes
  before publication. Cross-volume staging turns those destination-volume
  writes into one final sequential copy. No rotational/external drive was
  available, so its end-to-end HDD gain remains to be measured.
- The post-processing extension was compared directly with parent commit
  `72dbd412` using a real MNE EpochsArray with 64 EEG plus 2 EOG input
  channels, 3 epochs x 12,800 samples at 256 Hz, locked `N_step=640`
  metadata, one data object, and a 40 Hz export. Three interleaved trials had
  parent/current medians of 4.0452/2.6831 s: **33.67% less end-to-end
  post-processing time (1.508x)**. A two-object fallback fixture measured
  24.27% less time (1.321x).
- Both cross-commit fixtures preserved input hashes and produced the same
  logs after output-root normalization, timing-stage metadata after removing
  elapsed values, worksheet order/dimensions, populated-cell coordinates,
  values/types/styles/number formats, and every decompressed XLSX ZIP member
  except `docProps/core.xml` creation/modification timestamps.
- Dataset-index discovery over 96 participants x 4 conditions measured
  0.8211 s for three scans and 0.3040 s for one scan/reuse. This local,
  OS-warm result excludes the likely larger rotational-drive latency and is
  not added arithmetically to the end-to-end result above.

## Verification Notes

- Do not run pytest-qt or offscreen Qt locally.
- Use the pinned `.venv1` environment when present.
- Preserve current timing records and add cache/staging timing visibility where
  useful.
- Post-processing exactness bundle: 59 passed.
- Processing focused gate: 303 passed and one skipped. Stats focused gate:
  51 passed. LORETA focused gate: 275 passed.
- Worker-static dataset-index/cache lifecycle coverage: 6 passed. The
  PySide6 worker integration definition remains CI-only under the local
  no-Qt rule.
- Cross-commit numerical fuzzing matched raw QC v1 on 1,011/1,011 arrays and raw
  QC v2 on 1,011/1,011 arrays. Result bytes, exception identity, and warning
  category/message/order were exact.
  Layouts included C/F order, slices, zero-stride broadcasts, endian variants,
  unaligned arrays, and memmaps.
- Post-processing worker behavior/static bundle: 17 passed.
- Stats focused gate: 48 passed. Project-I/O focused gate: 71 passed.
- Full agent, GUI, project-path, protected-boundary, and source-localization
  audits passed. Ruff, bytecode compilation, and `git diff --check` passed.
- The final repo precommit gate ran outside the filesystem sandbox so the
  condition-QC memmap tests could execute normally: 1,028 passed and two
  skipped. The processing-focused gate passed 298 with one skipped.
- No local Qt/offscreen execution was used. Visible smoke: process a
  representative multi-group project from an internal drive and an external
  drive, run the post-processing continuation, confirm progress and completion
  states, reopen the generated workbooks, and compare scientific sheets plus
  QC/harmonic outputs with the base-branch run.
