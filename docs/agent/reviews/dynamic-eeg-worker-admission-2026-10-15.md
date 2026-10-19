# Dynamic EEG worker admission

Historical evidence note (2026-10-18): this review records its named baseline,
measurements and original verification limits. Old branch names, source paths
and pending checks below describe that point in time. For current ownership use
the [module map](../architecture/module-map.md); for published-artifact and
post-release source evidence use the
[release ledger](../exec-plans/active/v3-release-readiness.md). Do not treat this
report as an instruction to repeat completed implementation or private-data work.

This follow-up replaces fixed installed-RAM tier ceilings in memory-admitted EEG
stages. It follows measured commit
`38cc8ec18ede2506d49851ab59ef3cefa39f06c4` on
`codex/pipeline-bitwise-performance`. The user explicitly selected EEG processing
only. Sensitivity Analysis and historical callers retain the legacy tier API.

## Behavior

- Preflight, QC preparation, normal processing and condition-cell validation use
  usable process CPUs/affinity and the current saved project maximum. Automatic
  mode leaves one logical CPU available where possible. A positive setting is a
  ceiling. Windows also respects the process-pool runtime maximum of 61.
- Fresh available physical RAM and Windows commit headroom account for other
  applications. Stage-specific credits, host reserves and persistent process
  floors govern actual concurrency. Executors resize only after draining. When
  memory recovers, a smaller preparation/normal pool deliberately stops refilling
  so it can drain and grow; otherwise staggered completions could keep the batch
  at its initial smaller population. Partial recovery can grow the pool below
  the CPU ceiling. Current jobs, phase grants and cancellation keep progressing
  during the drain, and fresh headroom determines the replacement population.
- Normal processing credits include source loading, FIR/resampling, raw QC,
  notch FFT work, repairs, preparation/cache publication, overlapping epochs,
  spectra, native result exports, source-time exports and metadata. Actual
  source-rate fallback obtains additional credit before repairs/cache writes,
  including when kurtosis scoring is disabled. A single emergency borrower is
  held through file completion. Resident/private-memory credit requires matching
  worker PID and creation time; delayed reuse messages cannot reclaim an active
  worker as idle.
- Preflight retains its two-reader and two-spectral-evaluator semaphores. Shared
  parent-process memory earns no per-thread add-back. Results, first errors and
  submissions retain source order.
- Unsupported metadata, geometry or runtime versions use an exclusive native
  route. The normal estimator currently characterizes CPython 3.13, MNE 1.9.0,
  NumPy 2.3.1, SciPy 1.16.0 and pandas 2.3.0. Oversized conservative upper bounds
  also choose exclusive execution rather than falsely rejecting native work.
- GUI settings explain the maximum and live-memory policy without the obsolete
  RAM-tier override prompt. Each run resolves current settings rather than a
  previous run's worker count. RAM preload remains the explicitly selected mode.

The native numerical functions, thread policy, processing order, decisions,
formats and cache identity remain unchanged. New optional finish callbacks
inspect shape and wait for resource admission; they do not read waveform values
or enter scientific settings. No retired `Legacy_App`/`PySide6_App` package or
removed source-localization calculation was changed or restored. New ownership
stays under `Main_App.workers`; the existing process runner is its caller.

For eight usable logical CPUs, Auto has a ceiling of seven on both 16 and 32 GiB
machines. Actual concurrency can be lower and can differ between those machines
because it depends on live headroom and recording geometry. Four usable logical
CPUs have a ceiling of three. A saved maximum of 12 remains at most 12 on the
24-logical-CPU workstation.

## Verification

All commands used the repository environment and excluded local Qt execution.
No native study processing, timing capture or FHC analysis was repeated.

- `python .agents/scripts/verify.py --scope processing --tier focused`: the first
  invocation stopped at two new test-style lint violations before pytest; both
  were corrected. The next invocation passed audits/lint/compilation and ran
  3,196 passing, six skipped and six failing tests. Corrections covered a
  native-review fixture, preserving the explicitly passed worker initializer
  across spawn, and two scheduler fixtures with known synthetic geometry.
  The unchanged cache-pruning case also failed once on cache-index access.
- The subsequent targeted command passed **93 tests in 8.89 seconds**, including
  every failed processing case, the final notch/runtime estimator, real spawned
  scalar admission IPC, lifecycle/cancellation controls and four native synthetic
  sample/state/evidence equality checks. The cache-pruning case passed unchanged
  in isolation; its earlier failure remains recorded.
- `python .agents/scripts/verify.py --scope gui --tier focused`: **620 passed in
  12.52 seconds**, with GUI import/protected-boundary audits, lint and compilation
  passing. An earlier invocation had four stale AST fixture failures; those
  fixtures now execute the actual current-project resolver and CPU helper.
- The first `python .agents/scripts/verify.py --scope repo --tier precommit`
  completed with **6,544 passed, 24 skipped, five failed and 85 warnings in
  390.79 seconds**. All repository audits, lint and compilation passed. The five
  failures were the existing real-subprocess updater tests; this invocation
  selected the worktree's `.venv` junction, which the unchanged updater guard
  rejects as a linked application directory before spawning. The historical
  measured-commit gate used the physical interpreter and instead encountered its
  single-link executable guard. Neither guard nor installation was changed.
  This first follow-up gate had no processing assertion failures.
- Final review then found the recovery starvation described above. The
  corrected controllers passed four staggered-completion controls: normal
  processing **2 to 12** and **2 to 3**, preparation **2 to 12** and **2 to 4**.
  The first correction run had 97 passes and one failure; the subsequent
  recovery/liveness run had 67 passes and the same failure. The failing old-bug
  negative control correctly exposed premature admission, but also required an
  incidental observation of the full restored reserve after a different borrower
  could already own it. That ordering assertion was removed only from the
  intentionally broken negative control; its causal defect and cleanup assertions
  remain, and the repaired positive control still requires exact restoration.
  Both paired controls then passed in **5.45 seconds**. Additional pre-drain grant
  polling is scoped to characterized geometry; fallback queue cadence is retained.
- The repeated final `python .agents/scripts/verify.py --scope repo --tier
  precommit` completed with **6,547 passed, 24 skipped, six failed and 85 warnings
  in 379.76 seconds**. All 11 repository audit families, changed-file Ruff and
  compilation passed. The gate remains **failed**: five failures are the same
  updater linked-directory cases, and the sixth is
  `test_cold_publication_writes_one_complete_index[occurrences]` in
  `tests/processing/test_preflight_qc_pruning.py`. That case reported unavailable
  `.slots` index preparation, leaving zero observed index writes. The cache save
  still returned normally. No numerical equality or worker-admission test failed.
- A subsequent isolated diagnostic of the complete cache-pruning module passed
  **27 tests, two skipped, in 1.54 seconds**. A temporary exception trace observed
  no index-preparation exception in that run. The cache/index implementation and
  that test file match the measured parent commit exactly. The intermittent
  exception's cause is **unproven**; the passing isolated run does not erase the
  failed broad result or establish a fix. Index preparation conservatively skips
  pruning on error, so stale cache evidence can remain and index acceleration can
  be unavailable. No speculative cache or updater change was made.
- All **29** changed runtime/test/registry files matched their final-gate hash
  inventory after completion. Final staging removed one extra blank line at EOF
  from `test_preflight_resource_admission.py`; its parsed AST remained identical.
  No executable test or runtime change followed the gate. Other later changes
  were documentation only.
- Independent read-only reviews of memory bounds, scheduling lifecycle and GUI
  policy found no further concrete issue. Protected/source-localization audits
  passed. The visible Settings smoke path is documented in
  `docs/agent/architecture/workers-threading.md`; local Qt was not launched.

Detailed logs remain under the ignored `.codex-tmp/pipeline-bitwise/` directory:
`dynamic_eeg_processing_focused_01.log`,
`dynamic_eeg_processing_focused_02.log`,
`dynamic_eeg_targeted_corrections_03.log`,
`dynamic_eeg_gui_focused_01.log`, `dynamic_eeg_gui_focused_02.log`, and
`dynamic_eeg_repo_precommit_01.log`. Recovery evidence is in
`dynamic_eeg_growth_corrections_04.log`, `dynamic_eeg_growth_liveness_05.log`,
`dynamic_eeg_reserve_control_06.log`, and `dynamic_eeg_repo_precommit_02.log`.
The final gate's changed runtime/test/registry hashes are saved separately in
`dynamic_eeg_gate02_inventory.json`. The isolated cache diagnostic is preserved in
`dynamic_eeg_pruning_diagnostic_07.log` and
`dynamic_eeg_pruning_exceptions_07.json`. The staging-only newline correction's
before/after hashes and AST check are in `dynamic_eeg_stage_whitespace_08.json`.

## Measurement and remaining limits

The nine timing captures and twelve exact-output proofs in
`pipeline-bitwise-performance-report-2026-10-15.md` apply only to `38cc8ec1`.
Its measured 41.7% median elapsed-time reduction and the additional 4.3% median
RAM-preload reduction are historical results. This scheduling follow-up has no
new measured speedup or complete-study equality claim. Its new numerical
verification is the focused native synthetic coverage described above.

Memory estimates are intentionally conservative. Another application can
allocate after a snapshot, and unsupported routes cannot receive a characterized
per-file bound. The existing normal-run 85%-physical-use backstop remains an
additional guard. No updater policy, Python installation, power plan, screen-lock
policy or scientific dataset was changed for this follow-up.
