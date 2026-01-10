import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from Main_App.Legacy_App.processing_utils import ProcessingMixin
from Main_App.PySide6_App.GUI.main_window import MainWindow
import Main_App.PySide6_App.workers.mp_runner_bridge as mp_runner_bridge


def test_single_file_process_mode_routes_through_mp_runner(qtbot, tmp_path, monkeypatch):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)

    QApplication.instance() or QApplication([])

    project_root = tmp_path / "project"
    input_folder = project_root / "input"
    input_folder.mkdir(parents=True)
    excel_subfolder = "1 - Excel Data Files"
    (project_root / excel_subfolder).mkdir(parents=True)

    preprocessing = {
        "low_pass": 0.1,
        "high_pass": 50.0,
        "downsample": 256,
        "rejection_z": 5.0,
        "epoch_start_s": -1.0,
        "epoch_end_s": 125.0,
        "ref_chan1": "EXG1",
        "ref_chan2": "EXG2",
        "max_chan_idx_keep": 64,
        "max_bad_chans": 10,
        "save_preprocessed_fif": False,
        "stim_channel": "Status",
    }

    win = MainWindow()
    qtbot.addWidget(win)
    win.currentProject = SimpleNamespace(
        project_root=project_root,
        input_folder=input_folder,
        subfolders={"excel": excel_subfolder},
        preprocessing=preprocessing,
        options={},
    )

    win._on_mode_changed("single")
    win.add_event_row("CondA", "1")

    dummy_path = input_folder / "sample.bdf"
    dummy_path.touch()
    win.data_paths = [str(dummy_path)]
    if hasattr(win, "le_input_file"):
        win.le_input_file.setText(str(dummy_path))

    def _no_processing_notice():
        return None

    monkeypatch.setattr(win, "_show_processing_started_notice", _no_processing_notice)
    monkeypatch.setattr(MainWindow, "_on_processing_finished", lambda self, payload=None: None)

    def _fail_legacy_start(self):
        raise AssertionError("Legacy start_processing was called unexpectedly.")

    monkeypatch.setattr(ProcessingMixin, "start_processing", _fail_legacy_start)

    class FakeMpRunnerBridge(QObject):
        progress = Signal(int)
        error = Signal(str)
        finished = Signal(object)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.start_calls = []

        def start(self, **kwargs):
            self.start_calls.append(kwargs)

    monkeypatch.setattr(mp_runner_bridge, "MpRunnerBridge", FakeMpRunnerBridge)

    win.start_processing()

    assert isinstance(win._mp, FakeMpRunnerBridge)
    assert win._mp.start_calls
    call = win._mp.start_calls[0]
    assert call["max_workers"] == 1
    assert call["data_files"] == [Path(dummy_path)]
