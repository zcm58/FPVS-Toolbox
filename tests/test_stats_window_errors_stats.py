import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

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


@pytest.fixture(autouse=True)
def _stub_message_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    for method in ("critical", "information", "warning"):
        monkeypatch.setattr(
            QMessageBox,
            method,
            staticmethod(lambda *args, **kwargs: QMessageBox.Ok),
            raising=False,
        )


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


@pytest.mark.qt
def test_single_pipeline_worker_failure(qtbot, tmp_path, monkeypatch):
    win = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(win)
    win.show()

    _prepare_window(win, monkeypatch)
    win.subject_data = {"S1": {"CondA": {"ROI": 1.0}}}
    win.subjects = ["S1"]
    win.conditions = ["CondA"]
    win.subject_groups = {"S1": None}

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(stats_workers, "run_rm_anova", boom)

    qtbot.mouseClick(win.analyze_single_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_single_btn.isEnabled(), timeout=5000)
    qtbot.waitUntil(lambda: not win.spinner.isVisible(), timeout=5000)

    log_text = win.output_text.toPlainText()
    assert "simulated failure" in log_text or "ERROR" in log_text


@pytest.mark.qt
def test_between_pipeline_worker_failure(qtbot, tmp_path, monkeypatch):
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

    def between_boom(*_args, **_kwargs):
        raise RuntimeError("between failure")

    monkeypatch.setattr(stats_workers, "run_between_group_anova", between_boom)

    qtbot.mouseClick(win.analyze_between_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_between_btn.isEnabled(), timeout=5000)
    qtbot.waitUntil(lambda: not win.spinner.isVisible(), timeout=5000)

    log_text = win.output_text.toPlainText()
    assert "between failure" in log_text or "ERROR" in log_text


@pytest.mark.qt
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

    def summary_boom(*_args, **_kwargs):
        raise RuntimeError("summary failure")

    monkeypatch.setattr(win, "build_and_render_summary", summary_boom, raising=False)

    qtbot.mouseClick(win.analyze_single_btn, Qt.LeftButton)

    qtbot.waitUntil(lambda: win.analyze_single_btn.isEnabled(), timeout=5000)
    qtbot.waitUntil(lambda: not win.spinner.isVisible(), timeout=5000)

    log_text = win.output_text.toPlainText()
    assert "summary failure" in log_text or "ERROR" in log_text

