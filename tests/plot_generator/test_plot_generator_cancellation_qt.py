from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMainWindow, QMessageBox

from Tools.Plot_Generator import gui as plot_gui
from Main_App.gui import main_window as main_window_module


@pytest.mark.qt
def test_main_window_defers_close_while_snr_generation_stops(monkeypatch) -> None:
    class PlotPage:
        shutdown_calls = 0

        @staticmethod
        def has_active_generation() -> bool:
            return True

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    page = PlotPage()
    ignored: list[bool] = []
    notices: list[tuple[str, str]] = []
    host = SimpleNamespace(_plot_generator_page=page)
    event = SimpleNamespace(ignore=lambda: ignored.append(True))
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "information",
        lambda _parent, title, message: notices.append((title, message)),
    )

    main_window_module.MainWindow.closeEvent(host, event)

    assert ignored == [True]
    assert page.shutdown_calls == 1
    assert notices == [
        (
            "SNR Plot Generation Is Stopping",
            "Cancellation was requested. Wait for the active SNR plot worker "
            "to stop before closing FPVS Toolbox.",
        )
    ]


@pytest.mark.qt
def test_cancel_waits_for_worker_exit_and_suppresses_queued_condition(
    qtbot,
    tmp_path,
    monkeypatch,
) -> None:
    class ControlledWorker(QObject):
        progress = Signal(str, int, int)
        finished = Signal(dict)
        instances: list["ControlledWorker"] = []

        def __init__(self, _folder, condition, *_args, **_kwargs) -> None:
            super().__init__()
            self.condition = condition
            self.started = threading.Event()
            self.stop_requested = threading.Event()
            self.allow_finish = threading.Event()
            self.instances.append(self)

        def run(self) -> None:
            self.started.set()
            self.stop_requested.wait(timeout=5.0)
            self.allow_finish.wait(timeout=5.0)
            self.finished.emit(
                {
                    "condition": self.condition,
                    "generated_paths": [],
                    "failed_items": [],
                    "warning_items": [],
                    "cancelled": self.stop_requested.is_set(),
                }
            )

        def stop(self) -> None:
            self.stop_requested.set()

    condition_a = tmp_path / "Condition A"
    condition_b = tmp_path / "Condition B"
    condition_a.mkdir()
    condition_b.mkdir()
    output_dir = tmp_path / "plots"
    output_dir.mkdir()

    monkeypatch.setattr(plot_gui, "_Worker", ControlledWorker, raising=False)
    monkeypatch.setattr(
        plot_gui,
        "load_rois_from_settings",
        lambda: {"ROI": ["Cz"]},
    )
    questions: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, title, *_args, **_kwargs: questions.append(title)
        or QMessageBox.No,
    )

    host = QMainWindow()
    window = plot_gui.PlotGeneratorWindow(parent=host)
    host.setCentralWidget(window)
    qtbot.addWidget(host)
    window.folder_edit.setText(str(tmp_path))
    window._populate_conditions(str(tmp_path))
    window.out_edit.setText(str(output_dir))
    window.condition_combo.setCurrentText(plot_gui.ALL_CONDITIONS_OPTION)

    window._generate()
    qtbot.waitUntil(lambda: bool(ControlledWorker.instances), timeout=2000)
    worker = ControlledWorker.instances[0]
    qtbot.waitUntil(worker.started.is_set, timeout=2000)

    try:
        assert window.gen_btn.isEnabled() is False
        assert window.cancel_btn.isEnabled() is True
        assert host.menuBar().isEnabled() is False
        assert not window.workflow_status.isHidden()
        assert not window.progress_bar.isHidden()

        window._cancel_generation()

        assert worker.stop_requested.is_set()
        assert window.workflow_status.property("statusVariant") == "warning"
        assert "Stopping SNR plot generation" in window.workflow_status.text()
        assert window.gen_btn.isEnabled() is False
        assert window.cancel_btn.isEnabled() is False
        assert not window.workflow_status.isHidden()
        assert not window.progress_bar.isHidden()
        assert window._thread is not None
        assert window._worker is worker
        assert host.menuBar().isEnabled() is False

        window._generate()
        assert len(ControlledWorker.instances) == 1

        worker.allow_finish.set()
        qtbot.waitUntil(lambda: window._thread is None, timeout=3000)

        assert window._worker is None
        assert window.gen_btn.isEnabled() is True
        assert window.cancel_btn.isEnabled() is False
        assert host.menuBar().isEnabled() is True
        assert len(ControlledWorker.instances) == 1
        assert questions == []
        assert "Cancellation requested" in window.log.toPlainText()
        assert "Generation cancelled." in window.log.toPlainText()
        assert window.workflow_status.property("statusVariant") == "warning"
        assert "No new figure files were saved" in window.workflow_status.text()
        assert not window.workflow_status.isHidden()
        assert window.progress_bar.isHidden()
    finally:
        worker.allow_finish.set()
        if window._thread is not None:
            qtbot.waitUntil(lambda: window._thread is None, timeout=6000)
