# Stats (PySide6) overview

The PySide6 Stats layer wraps the legacy statistical routines with a Qt-based UI and worker orchestration.
This package stays thin: the view only renders widgets and forwards user actions, while workers and legacy
code handle the calculations.

## Internal structure (MVC-ish)

* **View**
  * `stats_main_window.py` – QMainWindow that lays out controls and renders logs.
  * `stats_ui_pyside6.py` – Thin entry point that exposes `StatsWindow` and legacy worker hooks for tests.
* **Controller**
  * `stats_controller.py` – Coordinates the Single and Between pipelines, run state, and worker scheduling.
* **Model/services**
  * `stats_data_loader.py` – Scans projects/manifests and normalizes metadata.
  * `stats_workers.py` – Worker runner and pure statistical job functions.
  * `summary_utils.py` – Builds rule-based summaries from exported results.
* **Support**
  * `stats_core.py` – Shared enums, data classes, and constants.
  * `stats_logging.py` – Formatting helpers for UI log lines and structured logging.
  * `stats_file_scanner_pyside6.py` – PySide6-specific project scanning utilities.

### Pipeline flow

`Analyze` button → `StatsController` launches pipeline → `StatsWorker` executes legacy stats code →
DataFrames/exports → `summary_utils` builds summaries → `StatsWindow` displays status/log updates.

Worker logic and legacy statistical math intentionally stay GUI-agnostic to keep the view simple.
