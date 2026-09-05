# FullFFT NumPy Companion Migration

User-approved on 2026-09-05. Replace dense FullFFT Excel storage with an
uncompressed NumPy companion alongside each condition workbook. Include the
already-calculated FullSNR arrays so plotting avoids wide Excel reads too.
Keep preprocessing, timing, FFT, noise, averaging, harmonic, and ROI math intact.

## Contract

- `Main_App.io.spectral_data` owns versioned non-pickled NPZ storage and one
  shared full/header/selected-column reader with legacy XLSX compatibility.
- Store every value, exact FFT grid, display labels, channel order, units and
  calculation metadata without truncation or further rounding. Preserve
  FullSNR values independently; never recompute them from averaged FullFFT.
- New workbooks retain Excel reports and small spectral-sheet notices, plus
  a `Spectral Data` manifest naming an immutable, content-addressed companion
  in the same directory. Companion references cannot escape that directory.
- Write/validate the companion first, then atomically publish the workbook.
  Record both artifacts in completion receipts and downstream fingerprints.
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
companion references and user instructions to preserve both files.

Synthetic local comparison (64 channels, 120 seconds at 256 Hz, FullFFT and
FullSNR, same input arrays, previous HEAD production writer versus new writer):
XLSX write 12.906 s versus companion/workbook write 0.132 s; both full reads
6.924 s versus 0.225 s; combined size 15.66 versus 10.76 MiB. One run, OS cache
not flushed; this measures storage only, not overall application throughput.
The production 512-Hz export test preserves FFT bytes and FullSNR values exactly.

Visible smoke (pending local user/CI environment): process one condition,
confirm the workbook and NPZ appear together, then run post-processing, SNR
Plots, Scalp Maps and Individual Detectability. Check a legacy project too.
Copy both artifacts to another project location and repeat; temporarily
withhold the companion in a test copy and confirm a clear missing-data error.
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

After completing this migration, explain original-rate epoching in plain
language. Do not change the processing order in this task.
