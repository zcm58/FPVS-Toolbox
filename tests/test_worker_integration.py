import importlib.util
import os
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtWidgets import QApplication

from Main_App.PySide6_App.Backend.project import Project
from Main_App.PySide6_App.GUI.main_window import MainWindow
from Main_App.PySide6_App.workers.mp_runner_bridge import MpRunnerBridge


def _build_worker_project(root: Path) -> Project:
    project = Project.load(root)
    project.update_preprocessing(
        {
            "low_pass": 0.2,
            "high_pass": 50.0,
            "downsample": 256,
            "rejection_z": 5.0,
            "epoch_start_s": -1.0,
            "epoch_end_s": 125.0,
            "ref_chan1": "EXG1",
            "ref_chan2": "EXG2",
            "max_chan_idx_keep": 64,
            "max_bad_chans": 10,
            "save_preprocessed_fif": True,
            "stim_channel": "StimA",
        }
    )
    project.event_map = {"CondA": 11}
    project.save()
    input_dir = Path(project.input_folder)
    input_dir.mkdir(parents=True, exist_ok=True)
    (input_dir / "sample.bdf").write_bytes(b"")
    return project


def test_worker_receives_project_params(tmp_path, qtbot, monkeypatch):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)

    project = _build_worker_project(tmp_path / "proj")

    QApplication.instance() or QApplication([])

    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    captured: dict = {}

    def fake_start(self, project_root, data_files, settings, event_map, save_folder, max_workers):
        captured["settings"] = settings
        captured["event_map"] = event_map
        self.finished.emit({"files": len(data_files)})

    monkeypatch.setattr(MpRunnerBridge, "start", fake_start, raising=False)

    win.start_processing()
    qtbot.waitUntil(lambda: not getattr(win, "_run_active", False), timeout=2000)

    assert captured["event_map"] == {"CondA": 11}
    assert captured["settings"]["stim_channel"] == "StimA"
    assert captured["settings"]["save_preprocessed_fif"] is True
