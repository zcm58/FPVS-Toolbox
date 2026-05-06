# Workers And Threading

Long-running work must not block the UI thread.

The canonical active import surface for Main App workers is
`src/Main_App/workers/`. It owns the Qt worker and multiprocessing bridge
implementations used by the main GUI, plus wrappers for Performance
process-runner helpers.

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

Useful tests:

```powershell
python -m pytest tests/test_postprocess_worker_qt.py tests/test_stats_focus_async.py -q
```
