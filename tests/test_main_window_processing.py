import importlib.util
import os
from pathlib import Path

import pytest

# Skip entire module if Qt or pytest-qt are unavailable
if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtWidgets import QApplication

from Main_App.PySide6_App.Backend.project import Project
import Main_App.PySide6_App.Backend.project_manager as project_manager
import Main_App.PySide6_App.Backend.loader as load_utils
import Main_App.Legacy_App.eeg_preprocessing as eeg_preprocessing
import Main_App.PySide6_App.Backend.processing as processing
import Main_App.Shared.post_process as post_process
from Main_App.Shared import user_messages
import Main_App.Legacy_App.processing_utils as processing_utils
import threading


# ---------------------- helpers ----------------------

def _stub_processing(monkeypatch, projects_root: Path) -> None:
    monkeypatch.setattr(
        project_manager,
        "select_projects_root",
        lambda self: setattr(self, "projectsRoot", projects_root),
    )
    monkeypatch.setattr(load_utils, "load_eeg_file", lambda *a, **k: object())
    monkeypatch.setattr(eeg_preprocessing, "perform_preprocessing", lambda *a, **k: (object(), 0))
    monkeypatch.setattr(processing, "process_data", lambda *a, **k: None)
    monkeypatch.setattr(post_process, "post_process", lambda *a, **k: None)

    def dummy_start(self):
        self._run_active = True
        self._finalize_processing(True)

    monkeypatch.setattr(processing_utils.ProcessingMixin, "start_processing", dummy_start)

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

    from Main_App.PySide6_App.GUI.main_window import MainWindow

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

    from Main_App.PySide6_App.GUI.main_window import MainWindow

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

    from Main_App.PySide6_App.GUI.main_window import MainWindow

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

