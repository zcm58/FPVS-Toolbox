# FullFFT NumPy Companion Migration

Status: implemented; visible companion/recovery checks below remain pending
under the [v3 release ledger](v3-release-readiness.md#3-qualify-processing-and-project-compatibility).

The original 2026-09-05 implementation replaced dense FullFFT Excel storage
with uncompressed NumPy companions, including already-calculated FullSNR.
Current processing publishes native `.fpvs` anchors with spectral and condition
companions; explicit Excel reports and historical workbook reads remain supported.
The dated benchmarks and gate failures below describe their original revisions,
not the current output container or current blockers. Preprocessing, timing,
FFT, noise, averaging, harmonic, and ROI math remain unchanged.

## Contract

- `Main_App.io.spectral_data` owns versioned non-pickled NPZ storage and one
  shared full/header/selected-column reader with legacy XLSX compatibility.
- Store every value, exact FFT grid, display labels, channel order, units and
  calculation metadata without truncation or further rounding. Preserve
  FullSNR values independently; never recompute them from averaged FullFFT.
- New condition results use a native `.fpvs` manifest naming immutable numerical
  companions in the same directory. Explicit Excel report destinations retain
  their `Spectral Data`/`Condition Data` declarations and report behavior.
  Companion references cannot escape that directory.
- Write/validate companions first, then atomically publish the native or explicit
  workbook anchor. Record all artifacts in completion receipts and downstream
  fingerprints.
- Missing, corrupt, mismatched or altered declared companions fail clearly.
  Only workbooks without a companion declaration use legacy Excel data.
- Moving/copying a project or freezing plotting inputs must preserve companions.
  Existing Excel-only projects remain readable; no automatic data rewrite.

## Execution

- [x] Shared companion storage/readers and exact round-trip checks.
- [x] Writer, 512-Hz export, receipts, incremental completeness and project I/O.
- [x] Stats, FullFFT QC/provenance and Free Harmonic Clustering readers/caches.
- [x] SNR plots, scalp-map consumers and immutable plotting snapshots.
- [x] Focused scientific/format parity, missing/tampered data and portability
  checks; architecture/user docs and visible smoke instructions.

## Verification

Use focused processing, project-I/O, plotting, publication-map, Stats and FHC
non-GUI gates. Cover full and selected reads, 120 seconds at 512 Hz, exact
FFT-bin neighborhoods, unchanged FullSNR curves, legacy workbooks, moved
project folders and interrupted publication. Qt execution remains CI-only.
The pre-existing eight path-audit findings under `outputs/` are outside scope.

The active-reader review also found and migrated Individual Detectability.
No application-owned project clone/archive or workbook-only copy workflow
exists; project portability is covered by moved-folder tests, relative
companion references and user instructions to preserve each anchor and all its
declared companions.

Synthetic local comparison (64 channels, 120 seconds at 256 Hz, FullFFT and
FullSNR, same input arrays, previous HEAD production writer versus new writer):
XLSX write 12.906 s versus companion/workbook write 0.132 s; both full reads
6.924 s versus 0.225 s; combined size 15.66 versus 10.76 MiB. One run, OS cache
not flushed; this measures storage only, not overall application throughput.
The production 512-Hz export test preserves FFT bytes and FullSNR values exactly.

Visible smoke (pending local user/CI environment): process one condition,
confirm the `.fpvs` anchor and its NPZ companions appear together, then run
post-processing, SNR Plots, Scalp Maps and Individual Detectability. Check a
legacy project too. Copy the anchor and all declared companions to another
project location and repeat; temporarily withhold a companion in a test copy
and confirm a clear missing-data error.
Do not run offscreen Qt locally.

Final non-GUI verification: processing focused gate 643 passed, 1 skipped;
Stats focused gate 402 passed; registered project-I/O targets 132 passed;
FHC targets 144 passed; Plot targets plus companion consumers 121 passed;
Scalp/Publication Maps targets 117 passed. Target sets overlap; these are
per-command counts. Relevant Ruff/compile and `git diff --check` passed.
The broad `verify.py --scope repo --tier precommit` gate stopped at the same
eight pre-existing `outputs/` path findings. Project-I/O, Plot, Scalp and FHC
driver path gates share that blocker, so their registered safe test commands
were executed directly. Visible GUI smoke remains a handoff check, not a
claim of local Qt execution.

## Compact condition data extension (2026-09-05)

This dated extension added a separate uncompressed NumPy companion for
already-calculated FFT amplitude, BCA, SNR, Z, and processing-owned
eligibility/audit tables.
At that revision, per-condition XLSX files became small manifests/notices;
current processing uses the native `.fpvs` anchors described above. Automatic
long/wide statistical workbooks, legacy XLSX reads, and the explicit report-writer
option for compact Excel copies remain supported. Never recompute
metrics from averaged FullFFT or change timing, noise, harmonic, or ROI math.

- [x] Commit/push prior work before starting (`f356b035`).
- [x] Separate compact companion, shared readers, and atomic publication.
- [x] Stats, Scalp Maps, SNR setup, QC, source identities, and cleanup.
- [x] Exact parity, legacy/missing/corrupt/moved data, long/wide export tests,
      measured storage benchmark, docs, and focused verification.
- [x] After storage is complete, investigate missing start markers in two study recordings;
      do not infer or synthesize trigger timing or silently exclude data.
- [x] Add explicit GUI recovery for missing expected conditions, preserving
      FFT-grid calculations and requiring reprocessing after changed exclusions.

Production-writer benchmark against `f356b035`: median of three writes,
486 ms -> 185 ms (62% faster). Median of five reads of three metric sheets
plus eligibility: 28.3 -> 21.6 ms for 12 selected frequencies (24% faster),
33.0 -> 22.9 ms for all 40 frequencies (31% faster). Fresh application caches,
warm filesystem cache, integrity checks retained. Fixture: 64 electrodes,
four 40-frequency metric tables, 2,560 QC rows, eligibility/neighbors, and
unchanged FullFFT/FullSNR arrays. Workbook 235 KB -> 13 KB; total size +1.9%.
Stored tables match exactly. These are storage timings, not whole-app forecasts.

Visible smoke (pending): process a small condition and confirm both NPZ
companions appear beside its `.fpvs` anchor. Open SNR Plots, Scalp Maps,
and Stats; complete frequency-domain QC and verify long/wide
Excel outputs. Repeat with legacy Excel inputs. In a test copy, withhold one
companion and confirm a clear error. No local Qt execution.

Final extension checks: processing focused gate 678 passed, 1 skipped;
combined registered non-Qt backend targets
811 passed. Changed-file Ruff and diff checks passed. Broad precommit remains
blocked by the same eight unrelated, pre-existing `outputs/` path findings.

Storage implementation committed/pushed as `b407cb29` before marker work.
An additional temporary-copy check round-tripped all eight tables from the
actual study workbook exactly; its source file remained unchanged.

Marker investigation: direct BDF Status-byte reads confirm zero samples of
code 3 in one recording and code 12 in another, before MNE or Toolbox
processing. Both BDFs have consistent header/data lengths. Matching Studio logs record the first
condition start as `serial/sent` and 146 oddballs; the BDFs retain only 126
in one recording and 137 in the other before the next condition. This supports late
acquisition or an earlier missing beginning, but a software send log cannot prove hardware
receipt. Run-start timestamps include setup and are not exact lost durations.
The application already logged these missing outputs before the
NumPy storage changes. Active Toolbox loading is read-only and writes derivatives to separate DAT/FIF files, never source BDF.
No complete alternative BDF was found in the bounded project/Studio folders.

Recovery needs an intact original BDF or an explicit user condition exclusion;
missing samples and start markers cannot be reconstructed. Existing exclusion
tables omitted absent outputs, leaving no condition-only GUI recovery. Add
those expected cells as separate review rows, initially unchecked, without
making them FFT-grid observations or changing scientific inclusion silently.

Recovery verification: 704 processing tests passed, 1 skipped; GUI import,
Ruff and compile gate passed without Qt execution. The read-only actual-project
audit found 244 existing outputs at 144 oddball cycles and one recording requiring
missing-condition review; an existing whole-participant exclusion was respected.
Technical empty recordings were not offered as condition choices. No source or project data was edited. Visible smoke remains pending:
Settings > Harmonics > Review FFT Crop Exclusions; confirm the missing row is
unchecked, save an explicit choice, and rerun Processing before downstream QC.
