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
- After accepted frequency-domain QC is marked current, the full pipeline
  writes or revalidates processing-owned neutral FullFFT provenance before it
  attempts harmonic selection or any selection-derived export. That
  header-only record is independent of the standard Summed-BCA selection and
  is the common provenance gate for Free Harmonic Clustering GUI inspection
  and direct preparation.
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
- `ProjectProcessingCacheResetWorker` performs recursive cache inspection and
  deletion in a background `QThread`. The GUI confirms the exact scope first,
  then locks project navigation, the active workspace, the Start button, and
  the shared processing start guard until the worker emits completion or
  failure; the worker never touches widgets.
- Settings harmonic recalculation runs its FullFFT-grid audit and harmonic
  selection in separate background `QThread` workers. Result, failure, and
  thread-finished signals must pass through the main-thread
  `_SettingsWorkerUiBridge` before updating Settings widgets, opening review or
  result dialogs, or releasing GUI controls. After selection is accepted, the
  harmonic worker calls the post-processing resume entry point with the exact
  selection metadata. This resume begins after harmonic selection, rebuilds
  the Stats-ready and full-audit workbooks plus both Hauk source-PSD map
  directories, and never loads BDFs, preprocesses EEG, or regenerates FFT
  workbooks. Source-map calculation reuses the durable source-ready FIF
  derivatives. If the fingerprint is unchanged and every dependent target
  still exists with a current matching record, it may finish as a no-op. A
  standard selection-only rebuild leaves neutral FullFFT provenance unchanged
  because its source/cohort inputs did not change.
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
  throughout the grid-review-to-harmonic-worker handoff, and the current
  implementation does not cooperatively cancel an in-flight
  selection-plus-publication run.
- An accepted participant-condition exclusion changes the FullFFT cohort, not
  only the selected harmonic list. After the grid worker releases its thread,
  Settings therefore resumes the full frequency-domain post-processing path so
  frequency QC and neutral FullFFT provenance are refreshed before selection;
  it still does not reload or preprocess raw EEG.

Rules:

- Active callers should import Qt workers, `MpRunnerBridge`, process-runner
  helpers, and multiprocessing environment helpers through `Main_App.workers`.
- Use `QThread` or `QRunnable` with `QThreadPool`.
- Workers must not touch widgets directly.
- Communicate progress, errors, and completion through signals.
- Keep user-facing errors non-blocking where possible.
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
