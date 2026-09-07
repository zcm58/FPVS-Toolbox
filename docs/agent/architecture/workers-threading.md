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

Common long-running work:

- EEG preprocessing and post-processing.
- Plot generation and export.
- Statistics pipeline runs.
- File scanning over project folders.
- Interactive preprocessing QC starts `QcSourcePrefetchWorker` when step 2
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
- Main App processing runs now receive a precomputed incremental plan from
  `Main_App.processing.processing_ledger` before `MpRunnerBridge.start()`.
  Workers receive only the files selected by that plan. Multi-group runs also
  receive a per-file output group-folder map so post-export writes into the
  condition-first/group-second Excel tree.
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
  disabled only during this non-cancellable save and restored before the
  existing continuation/finalization runs; worker progress never steals focus.
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
  completion summary. `MpRunnerBridge.error` is reserved for bridge-level
  faults; ordinary file failures must not finalize or unlock an active run.
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
