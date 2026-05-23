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

Useful tests:

```powershell
python -m pytest tests/processing/test_postprocess_worker_qt.py tests/stats/gui/test_stats_focus_async.py -q
```
