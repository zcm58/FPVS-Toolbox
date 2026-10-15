# FPVS pipeline performance and Birth Control 2 analysis

Status: measurements, exact-output proofs and study analyses complete.
The final non-Qt repository check completed with five updater-environment failures,
detailed below.

Work is isolated on `codex/pipeline-bitwise-performance`, compared with starting
snapshot `6aab9fa69b926d79097991f30dd84af4b2a579fd`. The workstation has an
Intel i9-12900, 16 physical cores / 24 logical CPUs and 127.73 GiB RAM.
Windows and scratch storage are on C: NVMe; the project is on D: USB storage.

## Measured processing time

All nine captures completed successfully. Native business time includes core
processing and standard downstream work. It excludes human QC, artifact audits,
strict verification and the separate FHC permutation analyses.

| Matched pair | Starting code, RAM OFF | Final code, RAM OFF | Final code, RAM ON |
| --- | ---: | ---: | ---: |
| 1 | 1601.074 s / 26:41 | 954.471 s / 15:54 | 901.098 s / 15:01 |
| 2 | 1623.982 s / 27:04 | 946.663 s / 15:47 | 906.257 s / 15:06 |
| 3 | 1636.766 s / 27:17 | 947.200 s / 15:47 | 916.697 s / 15:17 |

The code changes reduced matched processing time by a median **41.7073%**
(range 40.3856–42.1298%), saving a median 677.319 seconds, with RAM OFF in both
versions. The median final/starting time ratio is 0.582927, about 1.72 times as fast.

On the same final code, RAM preload reduced time by a further median
**4.2682%** (range 3.2203–5.5919%), saving 40.406 seconds (range 30.503–53.373).
This is a modest practical gain. Three pairs do not establish statistical
significance. Preload also increased sampled peak private commit by a median
17.024% and sampled peak RSS by 14.508% relative to OFF.

All cases used the same requested 12-worker ceiling. The original conservative
preparation policy admitted two workers; the new preparation policy admitted 12.
Normal processing admitted 12 in both versions. This preserves the starting
policy as the comparator rather than changing its behavior for the benchmark.

## RAM, CPU, workers and storage

These are retained one-second samples within native business windows. Private
memory means Windows commit; RSS can count shared pages repeatedly. Peaks are
sampled maxima and may miss brief allocations. Mean cores is sampled CPU time
divided by the observed business-window interval, in logical-core equivalents.

| Case | Peak RSS / private GiB | CPU seconds / mean cores | Admitted prep / normal ceiling | Process read / write GiB | Generated project GiB | Sampler access errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Starting OFF1 | 37.05 / 41.69 | 4208.67 / 2.63 | 2 / 12 | 277.48 / 22.62 | 21.490 | 0 |
| Starting OFF2 | 36.94 / 41.62 | 4291.47 / 2.64 | 2 / 12 | 277.52 / 22.61 | 21.490 | 12 |
| Starting OFF3 | 39.31 / 43.38 | 4309.55 / 2.63 | 2 / 12 | 277.56 / 22.63 | 21.490 | 0 |
| Final OFF1 | 36.87 / 53.23 | 6436.06 / 6.74 | 12 / 12 | 278.09 / 22.79 | 21.671 | 14 |
| Final OFF2 | 36.98 / 53.11 | 6336.68 / 6.69 | 12 / 12 | 278.20 / 22.80 | 21.667 | 0 |
| Final OFF3 | 36.02 / 53.41 | 6425.23 / 6.78 | 12 / 12 | 278.22 / 22.79 | 21.664 | 3 |
| Final ON1 | 42.06 / 61.41 | 6378.13 / 7.08 | 12 / 12 | 278.03 / 22.79 | 21.665 | 3 |
| Final ON2 | 42.34 / 62.15 | 6413.58 / 7.08 | 12 / 12 | 278.21 / 22.81 | 21.674 | 3 |
| Final ON3 | 43.94 / 62.72 | 6529.72 / 7.12 | 12 / 12 | 278.01 / 22.78 | 21.671 | 19 |

Every case reached 12 observed workers and 12 CPU-active workers at some point;
this does not mean continuous 12-core utilization. CPU-active means more than
1% of one logical CPU in a sample. All cases had zero process-limit omissions
and zero incomplete private-memory samples. Process-access/exit sampling errors
above limit resource precision; they are separate from scientific-data errors.

Maximum sampled final-OFF private commit was 53.41 GiB; ON was 62.72 GiB.
Maximum sampled RSS was 36.98 GiB OFF and 43.94 GiB ON. The source changes also
increased CPU seconds by a median 49.09%, despite the shorter wall time. These
measurements establish a speed/resource tradeoff, not lower energy or fewer
instructions. Process I/O includes cached traffic and is not physical USB/NVMe
throughput. Volume occupancy includes other applications. Generated project
size includes native output/cache artifacts and is not peak scratch allocation.

Highest sampled whole-machine physical RAM used, including Windows and other
applications, was 55.97 GiB for the starting code, 55.02 GiB for final OFF and
60.81 GiB for final ON. These peaks occur independently of the process peaks
and must not be added to them.

Individual worker peaks were recorded by PID plus creation lifetime for both
pools in every case. Aggregate RAM was never divided by worker count. Their
full values and source bindings are in the retained lifetime reports.

## Retained changes

There are 21 touched runtime paths: 15 modified files and six new helpers.
Tests, manual diagnostics and documentation are additional. The beginning
already contained the preparation process pool, normal parallel runner,
prepared FIR kernels/checkpoints, RAM-preload option and earlier QC/export
optimizations; this investigation does not claim their introduction.

1. Preparation admits files with per-file geometry and phase memory credits,
   fresh physical RAM and actual Windows commit headroom, a background-host
   reserve, CPU/affinity/project ceilings and worker floors. It separates
   resident-memory and private-commit accounting, handles full-rate fallback,
   resizes only a drained pool and preserves small-host liveness. Each child
   still performs the established serial numerical calculation.
2. Guarded QC display diagnostics share an identical difference read and avoid
   repeated temporary MNE time/annotation construction for supported inputs.
   A display-only cache binds source bytes, converted sample bytes, scope,
   geometry, configuration and implementation. It cannot accept QC or change
   exclusions. Cold cache publication avoids a second identical durable write.
3. Guarded packed24 BDF decoding accelerates full RAM/memmap loads and owned
   lazy preflight reads. Event extraction decodes consumed Status integers
   while preserving every native bulk read, cursor and short-read behavior.
   Native constructors, calibration, events and metadata remain authoritative;
   temporary instance bindings are restored before Raw escapes.
4. A guarded integer-ratio Status resampler preserves native trigger selection
   and signed-zero behavior. EEG resampling and filter/downsample order remain
   fixed. Guarded FIF serialization uses an ordinary 1 MiB buffer while retaining
   native format, splitting, cleanup, fsync and publication behavior.
5. A bounded immutable frequency-header memo avoids repeated parsing while
   preserving selection, harmonic pooling, indices and frequency order.
6. Condition-repair adoption/reconciliation can validate cells in bounded
   threads with canonical result/error order and fresh physical/commit gates.
   EEG repair remains one recording/numerical worker at a time. Its measured
   component benefit is outside the main gain because the benchmark fixture
   already contains completed repairs.

The new proactive admission policy applies to preparation and repair-cell
validation. Normal processing retains its existing CPU/installed-RAM tiers,
requested ceiling and reactive 85%-physical-used submission guard; it does not
have the new prospective per-file Windows-commit admission policy.

Separate workflow changes add **Retain all** to interpolation-burden review
(Apply decisions still saves), and let independent FHC enter neutral FullFFT
validation despite a stale sibling standard-analysis selection. FHC formulas
and permutations are unchanged. The requested raw-BCA clustering is a separate
exploratory analysis companion.

## Evaluated alternatives

Larger QC batches were slower at tested long sizes. FFT batching, rFFT
substitution, finite std/extrema shortcuts and unconditional epoch/source mean
reuse were rejected or reverted where exact bits, operator semantics, picks
or metadata could change. Filter/downsample reordering, precision reduction
and statistical-method changes violate the requested scientific contract.

Persistent/global BDF patches and selective physical seeks would change
lookup, warnings, lifetime or read/error behavior; scoped ownership and
in-buffer decoding were retained instead. Checksum/source authority was kept.
Removing intrinsic copies/GC had unresolved ownership costs; staging FIF on
another drive added duplicate I/O. Parallel EEG repairs/shared repair pools
would change ownership and first-failure/publication boundaries. Extending
validation threads into the ordinary ledger saved little wall time while
adding CPU work and coordination, so it was not retained.

The search exhausted documented plausible candidates on the observed active
path. It does not establish a global optimum across optional inactive FFT-notch
settings, arbitrary hardware or every project configuration. Component gains
are not summed or multiplied into the measured full-run gain.

## Exactness and verification

Runtime v8 is frozen at 511 files, native harness v3 at seven files and verifier13
at 62 files. All comparisons use exact scientific payload bytes, scalar types,
shapes and order, without numerical tolerance or dropped scientific fingerprints.
The six full and six separate prepared scopes ran fresh under this one verifier;
no earlier accepted scope was reused.

| Comparison | Full proof: 2,045 selected artifacts | Prepared proof: 58 namespaces |
| --- | --- | --- |
| Starting OFF → final OFF, pair 1 | Passed; `80bd58d5462410dbff607c753a8a289792741581e1afe050d9e51bd479098945` | Passed; `ff0c3410c619d99baaec04c677500554d231b7b316ac1a7dcf05bf8cc1ee229e` |
| Starting OFF → final OFF, pair 2 | Passed; `45cbc3a3cf03171940b0cdcb5c6bf0402ad0c13d13e999179a8d0861a0e6f63d` | Passed; `dbbb53703401f2ba96d49855d2a95a74aa640f062fcc4b9b4d98ce16e0777609` |
| Starting OFF → final OFF, pair 3 | Passed; `4044a3e25860b2e8ca087c587ef60601ee86fe0d7af1fe94e8118f54d21b8bbe` | Passed; `0d55a5161a35a5732c7603e5bf431c2a351d8c41c2735fce9e61b83488b16359` |
| Final OFF → final ON, pair 1 | Passed; `9f8cd32c1ab3855bee4a92fe0c809114ec39b28c33e7e6d626bcd82e800c68cd` | Passed; `41cbc14309f389921178f96f51cbb11f8458e98e02d945ddc824cc212db3775b` |
| Final OFF → final ON, pair 2 | Passed; `24eed505a783198223032eb6fec255ac0c6c918561def5328bcf309f6177ed1a` | Passed; `3bceb0c4c0455ba17313b25d899ae276a85f49941adaae5102c97af11ff8b9c1` |
| Final OFF → final ON, pair 3 | Passed; `23cc4c3fe1472d2f8759160a02575d4d27914921aacf5247840741318a083625` | Passed; `2dd8bc2be5af4ddb9b2b9ab2f49f3cbc488d394d50dd1718b3c846003f791649` |

The full proofs cover selected scientific artifacts, genuine identity
correspondence and stable typed metadata. Prepared proofs separately cover
checkpoint arrays, encoded MNE state and kurtosis evidence in all 58 source
namespaces. Owned paths, timestamps, runtime/source provenance and native
historical-manifest preimages use explicit validated correspondence rules.
This does not claim equal raw SHA256 values for every provenance container.

The terminal queue receipt has status `all_six_full_and_six_prepared_scopes_accepted`
and SHA256 `38464ba0c0fc9dfc740d10f75e5652f734286a9e5a57478df49f62ba4ada0607`.
Its small acceptance projection is
`6ac1e23f406154fdffe0cb8df13eee892b48df25c3d733df8918cc1a6704db65`.

These proofs apply to the fixed-upper-index-6 benchmark, with five eligible
non-base frequencies and the approved source/QC settings. The actual study's
11-frequency standard selection and independent 16-harmonic FHC analyses have
separate evidence; their permutation analyses are outside the native timings.

The final verifier correction passed 367 controls with one existing host skip
across two invocations. The first invocation's 36 fixture setup errors remain
failed; only those 36 controls were rerun after the required protocol-source
argument was supplied. All 116 actual cache-audit owners also passed the
bounded native-payload admission check. Component admission is distinct from
the cross-archive proofs in the table. Earlier failed verifier reports and
preserved references remain retained as failed history.

The final non-Qt repository check executed the `repo` / `precommit` scope of
`.agents/scripts/verify.py` through the reviewed private wrapper02. Its
process-local interpreter resolver selected the physical Toolbox environment,
with Qt opt-in disabled and all 74 registered Qt test files excluded before
import. The protected standalone test directory was ignored.

All 11 audit families, changed-file Ruff and compilation passed. Pytest ended
with **6,412 passed, 24 skipped, 5 failed and 85 warnings in 396.22 seconds**.
The broad gate remains **failed**. All five failures are the real-subprocess
cases in `tests/updates/test_update_helper.py`: two round trips, cancellation,
explicit-no-parent apply, and stalled-worker cancellation. They failed before
spawning because the unchanged updater security guard requires a regular
single-link executable, while this environment's physical `python.exe` had
`st_nlink = 5`. No processing numerical assertion failed. The launcher-link
condition remains an environment limitation; no updater guard or environment
was changed and no tests were rerun.

The failed result receipt SHA256 is
`18022cfc0e2aa1d57f061ea428cb943c273de253c73b000953108c70b46f4dc3`;
stdout is `ecb698752c8acb860d35bd66adb185db4d130675e7d1f47d89a33d104757d0ed`
and empty stderr is
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
The compact result projection is
`0e6cf18a9b0d697076e86d9c4e14147f18684253ef1104beea36926ed9e84dae`.
All source/native/verifier inventory members remained exact before and after.
The first launch attempt stopped before checks because its broad process guard
matched another project's tests; that failed-before-execution receipt remains
preserved. The historical V7 broad failure and isolated follow-up also remain
separate historical results.

Visible Retain-all smoke completed on the original study's 34-row burden
review. The documented manual path is to open a pending review, set an Exclude
choice with a reason/scope, click Retain all, and verify every row becomes
Retain while reasons/scopes remain and the dialog stays open. Apply decisions
is still required to save; Cancel retains the existing unsaved-choice guard.
Check the action row at 1180x650 and the supported 1280x900 workspace. Qt
regression coverage is written for CI; no local offscreen Qt execution was used.

## Private study verification

Study results, individual exclusions, and group/session audit details are
retained in the private research archive. The software performance evidence
in this report is separate from those study analyses.

## Evidence and limits

Retained benchmark evidence root: `D:/FPVS Pipeline Performance/2026-10-13`.
Series: `runs/final_full58_workers12_v8_series`.

| Evidence | SHA256 |
| --- | --- |
| Runtime v8 manifest | `8a5afa2b6ba30d3734a23a38e43e86e7190f6c753497258044b78fbe349ae43d` |
| Native-v3 harness manifest | `abdd93c0448fbe76e2310fc10e38eb7ac41f8bb3e0818dc37ba839d3644d5e1f` |
| Verifier13 manifest | `cf6c7798bc1fd27a70a7b32ad992e80d5e0d5aa5f2030fb2a8aa5e0442310d57` |
| Preserved verifier12 manifest | `6a852f3f242706e73aa757468ebfb15c18f56991d1f411d37af7905a27844e0e` |
| Preserved verifier11 manifest | `2d7e6de8da4c5374efd334c3cd2a1c274f24f1cb4b48ec69052729514147ad77` |
| `source_paired_native_summary.json` | `cb7075e77a28d4f5536e68862c77f391d14d4243281644d7bbfd8b080dd2c11b` |
| `paired_native_summary.json` | `6343d07fb55fb99e88e3eec3686f839139b1d805af2970354f26b2df1466edd6` |
| C resource projection | `9305be0159209a333b2c216452d4f12b74f4816c96de380c0391303d4a0aa4b4` |
| C lifetime binding | `a29c5a8b47df21a4a69e800001d7978e3bac2a243f62d6c5789ff911521f509e` |
| First Full07 report | `80bd58d5462410dbff607c753a8a289792741581e1afe050d9e51bd479098945` |
| First Prepared07 report | `ff0c3410c619d99baaec04c677500554d231b7b316ac1a7dcf05bf8cc1ee229e` |

Application caches were fresh for each native case; OS caches were uncontrolled
and unflushed. Ambient Windows/application work was observed, not controlled.
Baseline 1 predates the small keep-awake helper and records a different ambient
annotation/interpreter alias; physical interpreter/environment correspondence
is separately proven, while original annotations remain retained. Results are
specific to this workstation, runtime, dataset, approved QC and 12-worker ceiling.
