from __future__ import annotations

import importlib.util

import pytest


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return False


@pytest.mark.parametrize("outcome", ["success", "error"])
def test_ratio_run_keeps_single_active_thread_until_terminal_cleanup(
    outcome,
    qtbot,
    tmp_path,
    monkeypatch,
):
    if not _module_available("PySide6") or not _module_available("pytestqt"):
        pytest.skip("PySide6 or pytest-qt not available")

    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication

    from Tools.Ratio_Calculator import gui_run_workflow
    from Tools.Ratio_Calculator.gui import RatioCalculatorWindow

    class FakeThread(QObject):
        started = Signal()
        finished = Signal()

        def __init__(self):
            super().__init__()
            self.start_calls = 0
            self.quit_calls = 0
            self._running = False

        def start(self):
            self.start_calls += 1

        def release_start(self):
            self._running = True
            self.started.emit()

        def quit(self):
            self.quit_calls += 1
            self._running = False

        def release_finished(self):
            self.finished.emit()

        def isRunning(self):  # noqa: N802 - mirrors QThread
            return self._running

    class FakeWorker(QObject):
        progress = Signal(int)
        status = Signal(str)
        error = Signal(str)
        finished = Signal(str, str)
        terminal = Signal()
        log = Signal(str)

        def __init__(self, **_kwargs):
            super().__init__()
            self.assigned_thread = None

        def moveToThread(self, thread):  # noqa: N802 - mirrors QObject
            self.assigned_thread = thread

        def run(self):
            if outcome == "success":
                self.finished.emit(
                    str(tmp_path / "output"),
                    str(tmp_path / "output" / "ratios.xlsx"),
                )
            else:
                self.error.emit("simulated ratio failure")

    QApplication.instance() or QApplication([])
    window = RatioCalculatorWindow(roi_loader=lambda: {"Occipital": ["Oz"]})
    qtbot.addWidget(window)
    window.show()
    window._roi_watch_timer.stop()

    monkeypatch.setattr(gui_run_workflow, "QThread", FakeThread)
    monkeypatch.setattr(gui_run_workflow, "RatioCalculatorWorker", FakeWorker)
    monkeypatch.setattr(
        gui_run_workflow,
        "repeated_session_tool_block_reason",
        lambda *_args, **_kwargs: None,
    )
    info_messages = []
    error_messages = []
    monkeypatch.setattr(
        gui_run_workflow,
        "show_info",
        lambda _parent, title, message: info_messages.append((title, message)),
    )
    monkeypatch.setattr(
        gui_run_workflow,
        "show_error",
        lambda _parent, title, message: error_messages.append((title, message)),
    )
    monkeypatch.setattr(window, "_validate_inputs", lambda: [])
    monkeypatch.setattr(window, "_ensure_output_dir", lambda _path: (True, None))
    monkeypatch.setattr(window, "_show_completion_dialog", lambda: None)

    input_a = tmp_path / "condition-a"
    input_b = tmp_path / "condition-b"
    output = tmp_path / "output"
    input_a.mkdir()
    input_b.mkdir()
    output.mkdir()
    window._paired_participants = ["P01"]
    window._active_roi_defs = {"Occipital": ["Oz"]}
    window.input_a_edit.setText(str(input_a))
    window.input_b_edit.setText(str(input_b))
    window.output_edit.setText(str(output))
    window.label_a_edit.setText("Condition A")
    window.label_b_edit.setText("Condition B")
    window.run_label_edit.setText("A vs B")
    window._update_run_state()
    assert window.run_btn.isEnabled()

    window._start_run()
    active_thread = window._thread
    active_worker = window._worker
    assert active_thread is not None
    assert active_worker is not None
    assert active_thread.start_calls == 1
    assert not window.run_btn.isEnabled()

    window._start_run()
    assert info_messages == [("Running", "Ratio calculations are already running.")]
    assert window._thread is active_thread
    assert window._worker is active_worker
    assert active_thread.start_calls == 1

    active_thread.release_start()
    assert window._thread is active_thread
    assert window._worker is active_worker
    assert active_thread.quit_calls == 0
    assert not window.run_btn.isEnabled()
    assert window.status_label.text() == ("Complete" if outcome == "success" else "Error")
    assert bool(error_messages) is (outcome == "error")

    active_worker.terminal.emit()
    assert active_thread.quit_calls == 1
    assert window._thread is active_thread
    assert window._worker is active_worker
    assert not window.run_btn.isEnabled()

    window._start_run()
    assert info_messages == [
        ("Running", "Ratio calculations are already running."),
        ("Running", "Ratio calculations are already running."),
    ]
    assert active_thread.start_calls == 1

    active_thread.release_finished()
    assert window._thread is None
    assert window._worker is None
    assert window.run_btn.isEnabled()
