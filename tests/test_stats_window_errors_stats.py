import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QMessageBox

from Tools.Stats.Legacy import stats_analysis, stats_helpers
from Tools.Stats.PySide6 import stats_workers
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow
from Tools.Stats.PySide6.stats_worker import StatsWorker


def _prepare_window(win: StatsWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        win, "refresh_rois", lambda: setattr(win, "rois", {"ROI": ["Cz"]}), raising=False
    )
    monkeypatch.setattr(win, "_get_analysis_settings", lambda: (6.0, 0.05), raising=False)
    monkeypatch.setattr(win, "_check_for_open_excel_files", lambda _folder: False, raising=False)
    monkeypatch.setattr(win, "ensure_pipeline_ready", lambda *a, **k: True, raising=False)


def _wait_for_idle(win: StatsWindow, qtbot, button) -> None:
    qtbot.waitUntil(lambda: button.isEnabled(), timeout=5000)
    qtbot.waitUntil(lambda: not win.spinner.isVisible(), timeout=5000)


@pytest.fixture(autouse=True)
def _stub_message_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    for method in ("critical", "information", "warning", "question"):
        monkeypatch.setattr(
            QMessageBox,
            method,
            staticmethod(lambda *args, **kwargs: QMessageBox.Ok),
            raising=False,
        )


@pytest.fixture(autouse=True)
def _stub_legacy_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stats_helpers, "apply_rois_to_modules", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(stats_analysis, "set_rois", lambda *a, **k: None, raising=False)
    from Tools.Stats.PySide6 import stats_main_window

    monkeypatch.setattr(stats_main_window, "apply_rois_to_modules", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(stats_main_window, "set_rois", lambda *a, **k: None, raising=False)


@pytest.fixture(autouse=True)
def _inline_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    def immediate_run(self):  # pragma: no cover - replaces threaded execution in tests
        progress_emit = getattr(self.signals, "progress").emit
        message_emit = getattr(self.signals, "message").emit
        try:
            result = self._fn(progress_emit, message_emit, *self._args, **self._kwargs)
            payload = result if isinstance(result, dict) else {"result": result}
            self.signals.finished.emit(payload)
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))

    monkeypatch.setattr(StatsWorker, "run", immediate_run, raising=False)
    monkeypatch.setattr(QThreadPool, "start", lambda self, worker: worker.run(), raising=False)


def test_single_pipeline_worker_failure(qtbot, tmp_path, monkeypatch):
    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    win.show()

    _prepare_window(win, monkeypatch)
    win.subject_data = {"S1": {"CondA": {"ROI": 1.0}}}
    win.subjects = ["S1"]
    win.conditions = ["CondA"]
    win.subject_groups = {"S1": None}

    def raise_single(*_args, **_kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(stats_workers, "run_rm_anova", raise_single, raising=False)

    qtbot.mouseClick(win.analyze_single_btn, Qt.LeftButton)
    _wait_for_idle(win, qtbot, win.analyze_single_btn)

    log_text = win.output_text.toPlainText()
    assert "simulated failure" in log_text or "ERROR" in log_text


def test_between_pipeline_mixed_model_failure(qtbot, tmp_path, monkeypatch):
    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    win.show()

    _prepare_window(win, monkeypatch)
    win.subject_data = {
        "S1": {"CondA": {"ROI": 1.0}},
        "S2": {"CondA": {"ROI": 2.0}},
    }
    win.subjects = ["S1", "S2"]
    win.conditions = ["CondA"]
    win.subject_groups = {"S1": "G1", "S2": "G2"}

    monkeypatch.setattr(stats_workers, "run_between_group_anova", lambda *_a, **_k: {})
    
    def raise_between(*_args, **_kwargs):
        raise RuntimeError("between mixed failure")

    monkeypatch.setattr(
        stats_workers,
        "run_between_group_mixed_model",
        raise_between,
        raising=False,
    )

    qtbot.mouseClick(win.analyze_between_btn, Qt.LeftButton)
    _wait_for_idle(win, qtbot, win.analyze_between_btn)

    log_text = win.output_text.toPlainText()
    assert "between mixed failure" in log_text or "ERROR" in log_text


def test_summary_failure_releases_busy_state(qtbot, tmp_path, monkeypatch):
    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    win.show()

    _prepare_window(win, monkeypatch)
    win.subject_data = {"S1": {"CondA": {"ROI": 1.0}}}
    win.subjects = ["S1"]
    win.conditions = ["CondA"]
    win.subject_groups = {"S1": None}

    monkeypatch.setattr(stats_workers, "run_rm_anova", lambda *_a, **_k: {})
    monkeypatch.setattr(stats_workers, "run_lmm", lambda *_a, **_k: {})
    monkeypatch.setattr(stats_workers, "run_posthoc", lambda *_a, **_k: {})
    monkeypatch.setattr(win, "export_pipeline_results", lambda *_a, **_k: True)
    
    def raise_summary(*_args, **_kwargs):
        raise RuntimeError("summary failure")

    monkeypatch.setattr(
        win,
        "build_and_render_summary",
        raise_summary,
        raising=False,
    )

    qtbot.mouseClick(win.analyze_single_btn, Qt.LeftButton)
    _wait_for_idle(win, qtbot, win.analyze_single_btn)

    log_text = win.output_text.toPlainText()
    assert "summary failure" in log_text or "ERROR" in log_text
