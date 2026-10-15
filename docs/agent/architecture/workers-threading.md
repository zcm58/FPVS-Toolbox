# Workers And Threading

Long-running work must not block the UI thread.

The canonical active import surface for Main App workers is
`src/Main_App/workers/`. It owns the Qt worker and multiprocessing bridge
implementations used by the main GUI, plus wrappers for Performance
process-runner helpers.

Standalone tools may keep tool-local workers when that is their public import
contract. Plot Generator keeps `_Worker` importable from
`Tools.Plot_Generator.worker`; helper modules under `src/Tools/Plot_Generator/`
own data collection, aggregation, and rendering logic while `worker.py` remains
the QObject signal shell.

Memory-admitted EEG preflight, QC preparation, normal processing and condition-cell
validation use `Main_App.workers.mp_env.compute_dynamic_worker_ceiling`. The ceiling
respects usable process CPUs and affinity, leaves one logical CPU available where
possible, and applies a positive project worker setting as an upper limit. Zero
means automatic. It has no installed-RAM tier or fixed twenty-worker cap. Windows
additionally respects `ProcessPoolExecutor`'s supported 61-worker maximum, including
shared ceilings supplied to EEG thread stages; this is a runtime limit rather than
a RAM recommendation. Other platforms retain their CPU/user ceiling. The
ceiling does not grant permission to allocate or run that many jobs. Each stage
separately checks fresh physical availability and, on Windows, actual commit
headroom, including background use. Estimates, host reserves and process floors
determine admitted concurrency. Unsupported routes retain exclusive native work.
These checks cannot prevent another application allocating after a snapshot.

The older `compute_effective_max_workers` and `get_ram_tier_recommendation` APIs
retain their tier behavior for Sensitivity Analysis and historical callers without
live admission. This EEG migration does not change their simulation policy.
The GUI resolves current project ceilings for preflight, preparation and normal
runs rather than reusing a previous run's worker count. Saved canonical and legacy
worker settings remain compatible; a positive value is a ceiling, not a guaranteed
number of active workers. RAM preload remains an explicit setting and is not
silently changed to disk loading when headroom falls.

Common long-running work:

- EEG preprocessing and post-processing.
- `Main_App.workers.cell_validation_pool` optionally dispatches independent
  recording-condition artifact validation in ordered read-only threads. The
  default `reconcile_recording_condition_outputs` call and metadata-only mode
  retain the native serial loop. Each opted-in task uses a fresh context rather
  than inheriting mutable XLSX/validation caches; every native checksum, schema,
  source/protocol identity and receipt check still runs. Canonical plan order
  determines returned rows and the first exception, regardless of completion
  order. All readers close before the caller publishes a ledger or completion.
  CPU affinity and the project worker ceiling bound the population. Before
  every submission, live available physical RAM and Windows commit headroom
  account for background use; no owned-memory add-back or Raw-worker floor is
  applied. A 32 MiB scratch allowance plus bounded uncompressed NPY metadata and
  declaration workspace reserves small header/checksum allocations, without
  loading dense FFT/metric arrays. Unknown, legacy, changed or oversized budget
  inputs run alone through the native validator. Reduced headroom drains current
  reads; an empty queue falls back to native serial work rather than waiting
  permanently or inventing a capacity failure. This is conservative admission,
  not protection against arbitrary concurrent external allocations.
- Plot generation and export.
- Statistics pipeline runs.
- File scanning over project folders.
- The optional thread-backend preprocessing-QC adapter starts `QcSourcePrefetchWorker` when step 2
  opens. Its QThread preloads sources sequentially, retains them through review,
  and closes them after the scanner releases its exclusive consumers. The
  worker's direct `request_finish()` uses thread-safe cancellation/events;
  a queued slot cannot interrupt its active loader. The GUI bridge handles
  worker/thread-finished signals and uses a responsive event loop for final
  cleanup, never a GUI-thread `wait()` or file deletion. The main window rejects
  Close until the review and worker cleanup release the prefetch bridge.
  Known participant exclusions never enter source hashing/loading. After each
  accepted review stage, the GUI sends current participant exclusions through
  the I/O-free `update_participant_exclusions` call. Pending work is vetoed;
  active reads finish under their existing owner, and background maintenance
  closes newly excluded ready sources and returns their staging budget.
  Borrowed sources remain exclusively owned until scanner release. A later
  re-inclusion can use the normal scanner fallback rather than restart
  speculative work. The worker performs maintenance while awaiting final
  cleanup, never by closing memmaps on the GUI thread.
  Step 6 reuses completed
  sources and stops queued speculative work. No-action steps 2, 3, and 5 show
  a brief counted summary with Continue; step 4 retains the editable electrode
  table and Save / Next. These controls have no timed delay or preload-completion
  requirement. CI coverage is `tests/gui/test_qc_source_prefetch_qt.py`; local
  verification uses source-cache, scanner, orchestration, and worker doubles.
- The standard GUI's QC-16 preparation uses the spawned review-only pool in
  `Main_App.workers.kurtosis_review_process`. The background scan classifies
  canonical exclusions and validates approved timing before scheduling eligible
  recordings. The CPU/affinity and current project ceiling bound the pool;
  initial memory pressure no longer permanently shrinks that ceiling. A drained
  executor may be replaced with a smaller population, or grow toward the same
  ceiling after headroom recovers; live executors always retain all their floors. The
  GUI-neutral `review_resource_budget` module obtains source-bound ordinary
  BDF geometry using the existing validated lazy loader and bounds loading,
  referencing, drops, filtering, resampling, raw AUTO QC, checkpoint restoration
  and target-rate kurtosis allocations. Raw removed-electrode AUTO and
  automatic kurtosis interpolation are distinct settings. Unknown/annotation/
  unpinned routes retain the exclusive legacy source-size fallback. No signal
  arrays or cross-run geometry cache are retained by the scheduler.
  Before admissions, the first-fit queue refreshes OS physical availability
  and Windows CommitLimit-minus-CommitTotal. Only matching-process unique
  resident pages offset physical reservations; private committed bytes offset
  the commit reservation separately. Shared RSS and pagefile-free bytes cannot
  be substituted. Missing ownership probes earn no memory credit. Worker floors
  cover every pool slot, including idle or not-yet-identified processes, with a
  separate host margin. Thus background
  RAM pressure pauses admissions with explicit waiting/resumed progress; recovery
  may reuse or replace the drained pool toward its full ceiling. These conservative estimates are scheduling credits, not a guarantee
  against arbitrary concurrent external allocations.
  One emergency reserve over active/prospective jobs covers a full-rate scoring
  fallback; unrelated pending recordings cannot prevent a smaller job starting. A
  runtime callback before every scoring copy, including warm checkpoints,
  passes immutable dimensions only; callbacks never enter persisted settings.
  Unexpected larger scoring requests use non-droppable control messages and
  per-job grants. Only one emergency borrower proceeds, prioritized over new
  jobs, and its reservation is released after its future/Raw cleanup completes.
  The unused part of that active/prospective reserve remains reserved during the loan and
  during prospective grant checks, including admission of additional files.
  Requests beyond the covered geometry fail before the scoring allocation.
  When no ordinary population fits current physical/commit headroom, a known
  healthy singleton may run with one pool floor and without reserving an
  unrequested hypothetical full-rate allocation. It stays alone through future
  cleanup. Its actual scoring request can use a smaller realized span, waits
  explicitly under temporary pressure, and fails before allocation if its exact
  bytes plus one worker/host reserve exceed physical capacity. A hypothetical
  full-rate bound alone does not reject otherwise successful healthy processing.
  A healthy preparation bound that cannot fit total physical capacity reports an
  actionable per-recording failure instead of waiting indefinitely. These
  failures are admission policy; they do not claim equivalence to successful
  native paging beyond physical capacity.
  Cancellation and parent failure release blocked requests cooperatively;
  numerical/statistical bodies and preprocessing order remain unchanged.
  Returned evidence keeps input order. Each
  process uses the existing main worker initializer,
  single-thread numerical policy, private memmaps and bounded prepared-FIR cache.
  Jobs call the shared serial evidence preparation and stop before interpolation,
  final reference and exports. Only evidence/progress returns to the parent;
  ordered results and all GUI callbacks remain on the background calling thread.
  Cancellation stops submissions and cooperatively waits for active Raw owners
  to close. The GUI skips parent source prefetch because Raw arrays cannot cross
  the spawn boundary. An explicit thread-backend caller can retain the existing
  prefetch adapter; a supplied prefetch is safely closed on the background scan
  thread before a process pool is budgeted. Prepared checkpoints bind native
  BLAS library/thread identity so earlier GUI-thread preparation cannot be reused
  as exact single-thread worker preparation. Unknown native policy is a cache miss.
- `Main_App.processing.qc_review_diagnostics` has a guarded exact integer-span
  path for the characterized MNE 1.9.0 finite float64, bounded, dyadic sample-rate
  domain. It retains the same consecutive-difference thresholds and onset/stop
  arithmetic; unknown inputs or changed detector/helper code use MNE. No
  preprocessing, interpolation, exclusion or receipt authority changes.
  `qc_review_diagnostics_cache` can reuse only the display-only report after
  binding source bytes/stat, current converted sample bytes, ordered occurrence
  scope, channels/references/bads, geometry/config, diagnostic implementation,
  packages and native numerical policy. The scanner still loads Raw, prepares
  evidence, verifies unchanged source content again, and closes its owner.
  Corrupt/unknown/memory-limited cache operations fall back to computation;
  cancellation propagates. Publication follows the scanner's second source
  proof. The `raw_diagnostics` namespace lives within the existing project
  preflight cache and clears through its existing cache-management workflow.
- `Main_App.io.buffered_fif` changes only the ordinary file I/O buffer to 1 MiB
  in an isolated, fingerprint-guarded copy of the characterized MNE save chain.
  Source-ready export and preprocessed-cache owners retain their paths, FIF
  block geometry, split handling, numerical formats, close/fsync and publication
  guards. No shared MNE global is patched. Unknown runtimes, changed writers or
  overridden Raw methods use public `Raw.save`; buffer allocation failure falls
  back to its original small-buffer open before header/data writing.
- Main App processing runs now receive a precomputed incremental plan from
  `Main_App.processing.processing_ledger` before `MpRunnerBridge.start()`.
  Workers receive only the files selected by that plan. Multi-group runs also
  receive a per-file output group-folder map so post-export writes into the
  condition-first/group-second Excel tree.
- Normal EEG processing uses live physical/Windows-commit admission for the
  complete file lifetime, including loading, preprocessing, condition epochs,
  FFT/export work and cleanup. Pool floors and host reserves remain part of the
  budget, and owned-memory offsets require matching process identity. Active
  jobs are accounted for until they finish; executors resize only after draining.
  A reduced pool deliberately stops refilling when recovered headroom supports
  a larger useful population, including partial recovery below the CPU ceiling.
  Current jobs, phase grants and cancellation continue through that drain; the
  population is chosen again from fresh headroom after all owners finish.
  Scheduling changes must preserve source order, cancellation and the existing
  per-file numerical route. A preparation-only estimate must not be presented as
  a bound for the later epochs and export stages.
  `processing_resource_budget` characterizes the native common-grid BDF route
  on CPython 3.13 with MNE 1.9.0, NumPy 2.3.1, SciPy 1.16.0 and pandas 2.3.0.
  Other runtime versions, custom metadata or unsupported geometries use one
  exclusive native worker until their allocation behavior is characterized.
  A conservative upper estimate larger than installed RAM also selects that
  fallback; it does not prove that the native operation is impossible. Supported
  files validate actual shape at an unconditional finish barrier, including
  disabled kurtosis and warm preparation checkpoints. Source-rate fallback must
  obtain its complete credit before repairs and cache publication; the later
  tail barrier also protects epochs and exports. Only control metadata crosses
  the admission queue, and these callbacks do not enter scientific settings.
- EEG preflight uses its CPU/user ceiling with fresh whole-file memory credits
  before submissions. Active thread credits are retained in full because the
  parent also owns unrelated allocations; parent RSS/USS is not reclaimed as
  per-job credit. Unknown or over-host estimates run exclusively through the
  native chunked route, and unavailable required host information reports an
  actionable resource error. The existing two-reader and two-spectral-evaluator
  semaphores remain independent limits. Results and errors retain canonical
  order even when files complete out of order.
- Each persistent processing pool worker owns one bounded prepared-FIR cache
  for that batch. The initializer creates it after configuring numerical thread
  limits. A per-file context is always reset on return or exception; only
  immutable coefficient/kernel bytes survive between that worker's files.
  The 4 MiB cap includes coefficient-key and result buffers. Reinitialization
  closes the prior cache, ordinary process exit closes it, and forced pool
  termination releases it with the process. Direct preprocessing outside an
  explicit cache scope retains no kernel. No cache crosses worker processes,
  batches or project settings serialization.
  Native thread limits remain under the worker initializer's ownership and
  stay fixed during its processing work; kernel preparation observes that
  policy without changing it. Cache identities distinguish native library and
  thread-count changes between calls.
- After a successful Main App processing run, `PostProcessingPipelineWorker`
  orchestrates downstream analysis prep in a background `QThread`. The full
  order is frequency-domain QC acceptance, neutral FullFFT provenance,
  harmonic selection, the standard Stats-ready Summed BCA export, the additive
  full-audit analysis-ready export, and both canonical Hauk source-PSD map
  producers. The spreadsheet exports and maps are
  sibling consumers of one accepted canonical included-harmonic list; one
  failure must be reported without relabeling an old artifact as current. This
  worker is orchestration only;
  harmonic selection, standard Summed BCA export, full-audit workbook
  generation, and source-estimation logic remain owned by their processing,
  Stats, `Main_App.exports`, and LORETA source-producer modules.
  For a canonical repeated-session project, the participant-keyed legacy
  Stats-ready workbook and both LORETA project-source producers are not
  applicable: the worker emits explicit successful skip steps and phase
  progress without invoking them or touching existing artifacts. The
  recording-aware full-audit export still runs. Single-session behavior keeps
  the full order above.
- After accepted frequency-domain QC is marked current, the full pipeline
  writes or revalidates processing-owned neutral FullFFT provenance before it
  attempts harmonic selection or any selection-derived export. That
  header-only record is independent of the standard Summed-BCA selection and
  is the common provenance gate for Free Harmonic Clustering GUI inspection
  and direct preparation.
  Before presenting findings, the worker checks completed candidate workbook
  geometry against the project's montage and channel-label mapping, respecting
  validated cohort exclusions without requiring a completed new review. A
  mismatch reports the saved and requested mapping before ROI/report work.
  Failed neutral provenance stops harmonic selection and its consumers; failed
  harmonic selection stops its dependent exports. The original failure remains
  the recovery reason, while successful prerequisites retain the existing
  independence between spreadsheet and source-map exports.
- Accepting the summed-BCA review starts `FrequencyDomainQcDecisionWorker`
  through `gui/frequency_domain_qc_handoff.py`. Report/provenance generation,
  decision persistence, and the tools-metadata reread run on that worker, never
  in the dialog-close callback. The main shell stays on a locked "Saving QC
  Decisions" activity page and regains focus once when the review closes. The
  GUI bridge applies returned tools metadata and resumes the existing pipeline
  only after the save thread exits successfully. Save errors keep downstream
  outputs stale, show the failure, and release the run controls. Closing the
  app is blocked until the save finishes. The shared Start/Stop action is
  disabled during this non-cancellable save. The continuation also disables the
  action and labels it "Preparing Outputs…": the post-processing worker has no
  cancellation API. Existing completion, failure and cancelled-review paths
  restore Start Processing or Resume Post-processing; worker progress never
  steals focus.
  This changes scheduling only, not decision validation or pipeline ordering.
  Visible smoke: accept a summed-BCA review, verify the main window and spinner
  remain visible/responsive while saving, then verify processing resumes. A
  save failure must show an error and leave Resume Post-processing available.
  The delayed-save heartbeat smoke test is registered for CI; local Qt execution
  remains prohibited.
- Once harmonic selection succeeds, the worker activates the canonical
  selection fingerprint. A changed fingerprint marks the Stats-ready,
  full-audit, L2-MNE Hauk source-PSD map, and eLORETA Hauk source-PSD map
  derivatives stale before export; an identical fingerprint leaves current
  derivatives current.
  Each successful atomic file or directory publication is marked current
  independently, while a failed rebuild restores the preceding artifact and
  records `failed` for the newly required fingerprint.
- Downstream post-processing starts only after the processing ledger update
  succeeds. A ledger-write failure skips source generation so the exporter
  cannot infer a participant cohort from stale or partial state.
- `PostProcessingPipelineWorker` retains its text progress signal for logging
  and also emits structured phase progress as `(phase_id, completed_units,
  total_units, user_message)`. The main-thread GUI bridge uses that contract to
  replace completed per-file rows with downstream progress across frequency-
  domain QC, harmonic selection, Stats-ready export, and Hauk source-PSD map
  generation; numeric progress must not be inferred from free-form log messages.
- Within frequency-domain QC, output readiness, ROI coverage, dataset indexing,
  and report generation emit step-1 status messages and INFO timing records.
  The report's friendly substage messages use structured phase progress; technical
  details stay in the log. These timings finish before the GUI review wait and
  never enter scientific report payloads or fingerprints. Visible smoke: verify
  the step-1 description advances through its checks without advancing to step 2
  or displaying technical diagnostics, then complete the unchanged review.
- `ProjectProcessingCacheResetWorker` performs recursive cache inspection and
  deletion in a background `QThread`. The GUI confirms the exact scope first,
  then locks project navigation, the active workspace, the Start button, and
  the shared processing start guard until the worker emits completion or
  failure; the worker never touches widgets.
- Settings harmonic recalculation runs its FullFFT-grid audit and harmonic
  selection in separate background `QThread` workers. Result, failure, text
  progress, structured phase progress, and thread-finished signals must pass
  through the main-thread `_SettingsWorkerUiBridge` before updating GUI state,
  opening review or result dialogs, or releasing controls. The harmonic worker
  emits selection milestones and forwards the nested post-processing worker's
  `(phase_id, completed_units, total_units, user_message)` events; numeric
  progress must not be inferred from its free-form status messages. After
  selection is accepted, the worker resumes publication with the exact
  selection metadata. This resume begins after harmonic selection, rebuilds
  the Stats-ready and full-audit workbooks plus both Hauk source-PSD map
  directories, and never loads BDFs, preprocesses EEG, or regenerates FFT
  workbooks. Source-map calculation reuses the durable source-ready FIF
  derivatives. If the fingerprint is unchanged and every dependent target
  still exists with a current matching record, it may finish as a no-op. A
  standard selection-only rebuild leaves neutral FullFFT provenance unchanged
  because its source/cohort inputs did not change.
  Repeated-session resumes rebuild only recording-aware applicable outputs;
  the participant-keyed Stats-ready and LORETA steps remain explicit
  non-applicable successes.
- A confirmed Save-triggered harmonic rebuild shows the shared post-processing
  activity page while the embedded Settings page remains alive and guarded in
  the background. The FullFFT-grid audit uses indeterminate progress, then the
  harmonic and publication phase signals drive the normal progress bar and
  status presentation. The non-cancellable processing action remains disabled.
  Success returns Home; cancellation, grid/validation failure, or a selection
  failure before persistence restores the snapshot and returns to Settings. A
  later publication failure also returns to Settings but keeps the newly saved
  method and correctly stale/failed derivative records. The explicit
  **Recalculate Harmonics** action may remain on Settings with its inline status
  presentation.
- Settings snapshots project preprocessing, app analysis/ROI configuration,
  and its project cache before it persists inputs for recalculation. A failed
  save, failed grid audit, incompatible grid, or cancelled exclusion-review
  dialog restores that snapshot. Starting the worker does not itself mark
  derivatives stale: the old selection and artifacts remain current until a
  replacement selection is successfully persisted. If selection fails before
  that point, Settings restores the snapshot; after a replacement selection is
  persisted, the new method is committed and a later export failure restores
  the preceding file/directory but leaves it stale or failed for the required
  fingerprint. Settings close/reject and application navigation remain locked
  throughout the grid-review-to-harmonic-worker handoff even when the shared
  activity page is visible and Settings is only alive in the background. The
  current implementation does not cooperatively cancel an in-flight
  selection-plus-publication run.
- An accepted participant-condition exclusion changes the FullFFT cohort, not
  only the selected harmonic list. After the grid worker releases its thread,
  Settings therefore resumes the full frequency-domain post-processing path so
  frequency QC and neutral FullFFT provenance are refreshed before selection;
  it still does not reload or preprocess raw EEG.
- Downstream tools may emit a post-processing-required request containing an
  actionable stale reason and canonical project root. The Main App validates
  that root, presents the shared recovery dialog, and delegates acceptance to
  the existing post-processing activity workflow. This route reuses processed
  workbooks and never starts EEG preprocessing or a tool-local rebuild thread.

Rules:

- Active callers should import Qt workers, `MpRunnerBridge`, process-runner
  helpers, and multiprocessing environment helpers through `Main_App.workers`.
- Use `QThread` or `QRunnable` with `QThreadPool`.
- Workers must not touch widgets directly.
- Communicate progress, errors, and completion through signals.
- Keep user-facing errors non-blocking where possible.
- Individual preprocessing file failures emit `file_status`, remain in the
  bridge's final `errors` payload, and leave the batch active. The GUI passes
  them to the processing ledger and QC report, then shows one deduplicated
  completion summary. Ordinary file failures must not finalize or unlock an
  active run. Controller faults also finish through the single `finished`
  snapshot, so the ledger retains completed work before controls unlock.
- `run_project_parallel()` owns the sole terminal `done` message across
  reconciliation, pool creation, submission, harvesting, cancellation, and
  shutdown. It includes explicit `status` (`success`, `error`, `cancelled`),
  `controller_error`, complete result/error/exclusion lists, and
  `interrupted_files`. Without a queue, controller exceptions still propagate
  to the synchronous caller. Completed futures are harvested before stopping
  an exceptional or cancelled pool; unsubmitted files remain accounted for.
- `MpRunnerBridge` uses an in-process thread-safe queue: the controller thread
  is its only producer, and child results arrive through executor futures.
  Polling observes controller death before draining that queue, so a real
  terminal message wins over synthesized abnormal-exit failure without any
  multiprocessing feeder delay. Startup failure is delivered on the next
  timer tick. All terminal paths release bridge state once and allow restart.
  Queue faults request cancellation and retain the run lock until the
  controller stops. The GUI records completed results, reports controller
  failure, and skips downstream processing for that failed run.
- The spawned-worker initializer calls `set_worker_thread_limits()`. It retains
  a `threadpoolctl` limiter for already-loaded BLAS/OpenMP pools, sets the
  environment for subsequently loaded libraries, and limits NumExpr if already
  imported. This changes only child-process thread counts; the parent keeps its
  existing thread policy. Scientific parameters and processing order are
  unchanged. `tests/processing/test_worker_thread_limits.py` verifies effective
  runtime limits across repeated tasks in one real spawned child and byte-exact
  synthetic FIR/notch/resampling/FFT/kurtosis parity against an uncapped child.
- Log diagnostics with structured logging.
- Main App preprocessing cancellation is a hard-stop request: `MpRunnerBridge.cancel()`
  sets the shared cancel event, `run_project_parallel()` terminates active
  process-pool workers, cancels queued files, emits a cancelled done payload,
  and reports interrupted files so partial outputs are not treated as complete.
- `processing_ledger.record_processing_results()` is the post-run authority for
  marking participant outputs completed, failed, or incomplete. It requires
  expected Excel files to exist before writing a completed ledger entry.

Focused local verification:

```console
python .agents/scripts/verify.py --scope processing --tier focused
```

If the worker change is Stats-owned, use the `stats` scope instead. Qt worker
and focus tests run in CI only by default; document a visible/manual smoke path
for signal and cancellation behavior changed in the GUI.

Controller lifecycle coverage: `tests/processing/test_process_runner_lifecycle.py`
injects setup, creation, submission, worker, cancellation, and cleanup faults.
`tests/gui/test_processing_failure_routing_static.py` exercises the actual
bridge and completion methods with non-Qt doubles. The registered CI-only
`tests/processing/test_mp_runner_bridge_full_pipeline_smoke.py` covers actual
signals, abnormal controller exit, deferred startup failure, and restart.
Visible/manual smoke: start a small run, cancel it while work is active, verify
the completed files remain recorded and interrupted files are identified, then
start it again. Exercise an unavailable output location or injected controller
failure; verify one failure completion, restored controls, and no downstream
continuation before successfully restarting. Local Qt execution remains disabled.

Worker-setting visible/manual smoke: save `0` and a positive maximum in Settings;
neither should show the obsolete RAM-tier override prompt. Verify the field explains
that live memory can reduce active concurrency. Change the saved maximum between
runs and confirm preflight, preparation and normal-run logs use the current
CPU-bounded ceiling rather than the preceding run's value. Do not infer actual
concurrency from the ceiling alone. This path is not executed locally by the
non-Qt checks.
