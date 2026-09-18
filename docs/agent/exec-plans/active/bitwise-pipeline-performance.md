# Bitwise-Equivalent QC and Processing Performance

## Status

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

- `Shared/post_process.py`: local eligibility-fingerprint hoist.
- `processing/frequency_domain_qc.py` and `post_processing_context.py`:
  ledger snapshot, bounded scoped admission and detached reuse.
- `Tools/Free_Harmonic_Clustering/analysis.py`: empty-node scan guard.
- `processing/prepared_fir.py`, `processing/preprocess.py` and
  `Performance/process_runner.py`: isolated MNE adapter and batch-worker owner.

The `processing/`, `Shared/` and `Performance/` paths above are under
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
