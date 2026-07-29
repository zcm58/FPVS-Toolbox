import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QThread, Signal, Slot

from Main_App.gui.settings_panel import _SettingsWorkerUiBridge
from Main_App.workers import full_fft_grid_qc_worker, harmonic_selection_worker


pytestmark = pytest.mark.qt


class _ThreadedResultEmitter(QObject):
    finished = Signal(object)

    @Slot()
    def run(self) -> None:
        self.finished.emit({"ok": True})


def test_settings_worker_bridge_marshals_result_to_gui_thread(qtbot) -> None:
    main_thread_id = threading.get_ident()
    callback_thread_ids: list[int] = []
    bridge = _SettingsWorkerUiBridge(
        result_callback=lambda _result: callback_thread_ids.append(
            threading.get_ident()
        )
    )
    thread = QThread()
    emitter = _ThreadedResultEmitter()
    emitter.moveToThread(thread)
    thread.started.connect(emitter.run)
    emitter.finished.connect(bridge.handle_result)
    emitter.finished.connect(thread.quit)
    emitter.finished.connect(emitter.deleteLater)

    with qtbot.waitSignal(thread.finished):
        thread.start()
    qtbot.waitUntil(lambda: len(callback_thread_ids) == 1)
    thread.deleteLater()
    bridge.deleteLater()

    assert callback_thread_ids == [main_thread_id]


def test_settings_worker_forces_transactional_harmonic_recalculation(
    qtbot,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[dict[str, object]] = []
    report = SimpleNamespace(
        workbook_path=Path("Quality Check") / "Harmonic_Selection_Summary.xlsx",
        selection_metadata={"selected_harmonics_hz": [1.2]},
        messages=("recalculated",),
    )

    def _run(project, **kwargs):
        calls.append({"project": project, **kwargs})
        kwargs["log_func"]("Reading FullFFT workbooks 1/2.")
        return report

    monkeypatch.setattr(
        harmonic_selection_worker,
        "run_processing_harmonic_selection_qc",
        _run,
    )
    project = SimpleNamespace(project_root=Path("Example Project"))
    worker = harmonic_selection_worker.ProcessingHarmonicSelectionWorker(project)

    with caplog.at_level(logging.INFO, logger=harmonic_selection_worker.__name__):
        with qtbot.waitSignal(worker.finished) as blocker:
            worker.run()

    assert len(calls) == 1
    assert calls[0]["project"] is project
    assert callable(calls[0]["log_func"])
    assert calls[0]["force_recalculate"] is True
    assert blocker.args[0]["ok"] is True
    assert "harmonic_recalculation_started" in caplog.text
    assert "harmonic_recalculation_progress" in caplog.text
    assert "Reading FullFFT workbooks 1/2." in caplog.text
    assert "harmonic_recalculation_completed" in caplog.text
    assert "selected_harmonics=[1.2]" in caplog.text


def test_fft_grid_worker_logs_recalculation_phase_status(
    qtbot,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    audit = SimpleNamespace(
        observations=(object(), object()),
        review_candidates=(object(),),
        has_unresolved_grid_conflict=False,
        reference_support=2,
        reference_total=2,
    )
    monkeypatch.setattr(
        full_fft_grid_qc_worker,
        "audit_project_full_fft_grids",
        lambda _project_root: audit,
    )
    worker = full_fft_grid_qc_worker.FullFftGridQcWorker(Path("Example Project"))

    with caplog.at_level(logging.INFO, logger=full_fft_grid_qc_worker.__name__):
        with qtbot.waitSignal(worker.finished) as blocker:
            worker.run()

    assert blocker.args[0] is audit
    assert "harmonic_recalculation_grid_check_started" in caplog.text
    assert "harmonic_recalculation_grid_check_completed" in caplog.text
    assert "workbooks=2" in caplog.text
    assert "review_candidates=1" in caplog.text
