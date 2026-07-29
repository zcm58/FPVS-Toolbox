# Bitwise-Equivalent QC and Processing Performance

## Status

The original pipeline work is present on local `codex/finalize-multi-group`.
The post-processing extension is complete on
`codex/finalize-multi-group-postprocess-speedups`, branched from that local
branch at `72dbd412`. It is awaiting a visible representative-project smoke
run and manual review before merge.

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
- Cross-commit numerical fuzzing matched raw QC v1 on 1,011/1,011 arrays, raw
  QC v2 on 1,011/1,011 arrays, and epoch averaging on 263/263 layouts. Result
  bytes, exception identity, and warning category/message/order were exact.
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
