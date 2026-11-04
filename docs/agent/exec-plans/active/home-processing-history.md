# Project Home processing history

## Scope and acceptance

Show one always-visible, wrapping Home line with the last recorded completed
data-processing time and distinct successfully processed participant count.
Keep missing history/counts explicit; never infer recency from output file dates
or participant count from recording count. Existing processing and analysis
readiness behavior stays unchanged.

Acceptance: reopening or switching projects loads that project's history;
returning Home and completing processing refreshes it without blocking Qt.
Stale background responses cannot overwrite another project's state. At
1280x900 the line and Start Processing remain visible with long values.

## Status

- Implementation: complete; additive run metadata, bounded read-only history
  reader, asynchronous label and Home/completion hooks. Requests during a read
  coalesce into a follow-up read so newly completed runs cannot be missed.
- Review fixes: malformed JSON and legacy cell statuses preserve usable history;
  extreme dates retain their saved timezone if local conversion fails. Accessible
  text follows the displayed date/count/status.
- Verification: GUI focused, backend/history-ledger, repository precommit,
  registry validation and strict MkDocs passed.
- Windows visible acceptance: synthetic histories in the actual MainWindow at
  1280x900 covered completed, missing, incomplete and unknown-count states,
  project switching, long values and accessible text. The history line and Start
  Processing stayed visible. No private data or EEG processing was exercised.
- Remaining acceptance: automated Qt tests run in CI; check reopening a real
  project and refreshing after a real processing run in a visible session.

## Changed files

- Processing: `src/Main_App/processing/processing_history.py`,
  `src/Main_App/processing/processing_ledger.py`.
- Presentation/worker: `src/Main_App/gui/processing_history_model.py`,
  `src/Main_App/gui/processing_history_label.py`,
  `src/Main_App/workers/processing_history_worker.py`.
- Existing hooks: `src/Main_App/gui/ui_main.py`, `src/Main_App/gui/main_window.py`,
  `src/Main_App/gui/processing_completion.py`.
- Coverage: `tests/processing/test_processing_history.py`,
  `tests/processing/test_processing_ledger.py`,
  `tests/gui/test_processing_history_model.py`,
  `tests/gui/test_processing_history_label_qt.py`,
  `tests/gui/test_main_window_layout_smoke.py`,
  `tests/gui/test_processing_failure_routing_static.py`,
  `tests/qt_test_files.txt`, `.agents/verification.toml`.
- Contracts/routing: `ARCHITECTURE.md`, `docs/agent/agent-index.md`,
  `docs/agent/architecture/gui.md`, `docs/agent/architecture/project-io.md`,
  `docs/agent/exec-plans/README.md`, and this plan.
