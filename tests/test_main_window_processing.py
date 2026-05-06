import importlib.util
import os
from pathlib import Path

import pytest

# Skip entire module if Qt or pytest-qt are unavailable
if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from Main_App.projects.project import Project
import Main_App.processing.preprocess as backend_preprocess
import Main_App.projects.project_manager as project_manager
import Main_App.workers.mp_runner_bridge as mp_runner_bridge
import Main_App.io.load_utils as load_utils
import Main_App.processing.processing as processing
import Main_App.Shared.post_process as post_process
from Main_App.Shared import user_messages
import Main_App.Shared.processing_mixin as processing_mixin
import threading


# ---------------------- helpers ----------------------

def _stub_processing(monkeypatch, projects_root: Path) -> None:
    monkeypatch.setattr(
        project_manager,
        "select_projects_root",
        lambda self: setattr(self, "projectsRoot", projects_root),
    )
    monkeypatch.setattr(load_utils, "load_eeg_file", lambda *a, **k: object())
    monkeypatch.setattr(backend_preprocess, "perform_preprocessing", lambda *a, **k: (object(), 0))
    monkeypatch.setattr(processing, "process_data", lambda *a, **k: None)
    monkeypatch.setattr(post_process, "post_process", lambda *a, **k: None)

    def fail_compat_start(self):
        raise AssertionError("Compatibility ProcessingMixin.start_processing was called")

    monkeypatch.setattr(processing_mixin.ProcessingMixin, "start_processing", fail_compat_start)

    class FakeMpRunnerBridge(QObject):
        progress = Signal(int)
        error = Signal(str)
        finished = Signal(object)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.start_calls = []

        def start(self, **kwargs):
            self.start_calls.append(kwargs)
            QTimer.singleShot(
                0,
                lambda: self.finished.emit(
                    {
                        "files": len(kwargs.get("data_files", [])),
                        "results": [],
                        "cancelled": False,
                    }
                ),
            )

    monkeypatch.setattr(mp_runner_bridge, "MpRunnerBridge", FakeMpRunnerBridge)

    for name in ("show_error", "show_warning", "show_info", "ask_yes_no"):
        monkeypatch.setattr(user_messages, name, lambda *a, **k: True)


def _create_project(root: Path) -> Project:
    proj_root = root / "proj"
    data_dir = proj_root / "input"
    data_dir.mkdir(parents=True)
    (data_dir / "sample.bdf").touch()
    project = Project.load(proj_root)
    project.input_folder = data_dir
    project.save()
    return project


# ---------------------- tests ----------------------

@pytest.mark.parametrize("debug", [False, True])
def test_main_window_processing_runs(tmp_path, qtbot, monkeypatch, debug):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)

    _stub_processing(monkeypatch, tmp_path)
    project = _create_project(tmp_path)

    QApplication.instance() or QApplication([])

    from Main_App.gui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    win.settings.set("debug", "enabled", str(debug))
    win.settings.save()

    win.start_processing()
    qtbot.waitUntil(lambda: not win._run_active, timeout=1000)


@pytest.mark.parametrize("debug", [False, True])
def test_periodic_queue_check_does_not_finalize_twice(tmp_path, qtbot, monkeypatch, debug):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)

    _stub_processing(monkeypatch, tmp_path)
    call_count = 0

    from Main_App.gui.main_window import MainWindow

    orig_finalize = MainWindow._finalize_processing

    def counting_finalize(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return orig_finalize(self, *args, **kwargs)

    def dummy_start(self):
        self._run_active = True
        self._finalize_processing(True)

    monkeypatch.setattr(MainWindow, "_finalize_processing", counting_finalize)
    monkeypatch.setattr(MainWindow, "start_processing", dummy_start)

    project = _create_project(tmp_path)

    QApplication.instance() or QApplication([])

    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    win.settings.set("debug", "enabled", str(debug))
    win.settings.save()

    win.start_processing()
    qtbot.waitUntil(lambda: not win._run_active, timeout=1000)

    win._periodic_queue_check()

    assert call_count == 1



def test_export_post_process_threadsafe(tmp_path, qtbot, monkeypatch):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)

    project = _create_project(tmp_path)

    QApplication.instance() or QApplication([])

    from Main_App.gui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    def threaded_export(self, labels):
        def worker():
            self.gui_queue.put({"type": "log", "message": f"exported {labels}"})

        t = threading.Thread(target=worker)
        t.start()
        t.join()

    monkeypatch.setattr(MainWindow, "_export_with_post_process", threaded_export)
    win.post_process = threaded_export.__get__(win, MainWindow)

    win.post_process(["CondA"])
    msg = win.gui_queue.get_nowait()
    assert msg["message"] == "exported ['CondA']"

