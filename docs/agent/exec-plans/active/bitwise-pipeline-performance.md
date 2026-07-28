# Bitwise-Equivalent QC and Processing Performance

## Status

Implementation complete on `codex/finalize-multi-group-bitwise-speedups`,
branched from local `codex/finalize-multi-group` at `f45512ec`. Awaiting a
visible representative-project smoke run and merge back to that branch.

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
| 5 | Combine QC percentiles and use finite-data NumPy operations while retaining the original NaN-aware fallback | Moderate QC-stage gain; measured exact for finite and non-finite inputs | Low with byte-level regression tests | Implemented; representative per-channel helpers measured 1.19-1.81x faster |
| 6 | Compute identical Excel column widths in column blocks instead of one pandas conversion per column | Moderate export CPU gain | Very low | Implemented; 64 x 12,000 benchmark measured 2.83x faster |
| 7 | Avoid an unconditional float64 epoch-array copy before the unchanged mean | Low to moderate memory-bandwidth and peak-RAM gain | Very low | Implemented with byte-exact float64, float32, and non-contiguous coverage |
| 8 | Batch FFT multi-notch transforms over a memory-bounded channel block | Moderate; measured about 1.4-1.7x for that stage | Moderate memory/oversubscription risk in multi-process runs | Deferred pending representative recording-length profiling |
| 9 | Serialize or pipeline main-run BDF reads per physical rotational device | Potentially very high on HDD cold runs | Moderate; hardware detection and workload interaction need real-drive measurements | Deferred for device benchmarking |
| 10 | Reuse condition epoch means between workbook and source-ready export | Moderate | Moderate; current bad-channel pick semantics differ | Deferred |

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
  faster depending on condition length; exact float64 result bytes were
  checked against the prior scalar formulas. NaN/Inf data retains the original
  NaN-aware operations and is covered separately.
- A representative 4.16 MiB workbook assembly issued 189 non-empty writes
  before publication. Cross-volume staging turns those destination-volume
  writes into one final sequential copy. No rotational/external drive was
  available, so its end-to-end HDD gain remains to be measured.

## Verification Notes

- Do not run pytest-qt or offscreen Qt locally.
- Use the pinned `.venv1` environment when present.
- Preserve current timing records and add cache/staging timing visibility where
  useful.
- Directly affected equivalence/cache/lifecycle bundle: 91 passed.
- Post-processing worker behavior/static bundle: 17 passed.
- Stats focused gate: 48 passed. Project-I/O focused gate: 71 passed.
- Full agent, GUI, project-path, protected-boundary, and source-localization
  audits passed. Ruff, bytecode compilation, and `git diff --check` passed.
- The repo precommit gate completed 1,014 passing and two skipped tests. Its
  only three failures are unchanged condition-QC memmap tests blocked by this
  Windows sandbox with `PermissionError`/`WinError 5`; the same three failures
  occurred before the final changes in the processing focused gate. All three
  passed when rerun outside the filesystem sandbox (`3 passed`), so the
  combined precommit result is green.
- No local Qt/offscreen execution was used. Visible smoke: process a
  representative multi-group project from an internal drive and an external
  drive, run the post-processing continuation, confirm progress and completion
  states, reopen the generated workbooks, and compare scientific sheets plus
  QC/harmonic outputs with the base-branch run.
