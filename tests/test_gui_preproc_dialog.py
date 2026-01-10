import importlib.util
import json
import os

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from Main_App.PySide6_App.Backend.project import Project
from Main_App.PySide6_App.GUI.main_window import MainWindow
from Main_App.PySide6_App.GUI.settings_panel import SettingsDialog


def _prep_project(root):
    proj_root = root / "project"
    proj_root.mkdir()
    project = Project.load(proj_root)
    project.update_preprocessing(
        {
            "low_pass": 45.0,
            "high_pass": 0.25,
            "downsample": 512,
            "rejection_z": 4.0,
            "epoch_start_s": -0.25,
            "epoch_end_s": 95.0,
            "ref_chan1": "Cz",
            "ref_chan2": "Pz",
            "max_chan_idx_keep": 32,
            "max_bad_chans": 5,
            "save_preprocessed_fif": False,
            "stim_channel": "Status",
        }
    )
    project.save()
    return project


def test_dialog_loads_saves_project(tmp_path, qtbot):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)

    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])

    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)

    assert dlg.preproc_edits[2].text() == "512"
    assert dlg.stim_edit.text() == "Status"
    assert dlg.save_fif_check.isChecked() is False

    dlg.preproc_edits[2].setText("256")
    dlg.preproc_edits[4].setText("3.5")
    dlg.preproc_edits[5].setText("100")
    dlg.stim_edit.setText("Trigger")
    dlg.save_fif_check.setChecked(True)

    dlg._save()

    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["downsample"] == 256
    assert reloaded.preprocessing["rejection_z"] == 3.5
    assert reloaded.preprocessing["epoch_end_s"] == 100.0
    assert reloaded.preprocessing["stim_channel"] == "Trigger"
    assert reloaded.preprocessing["save_preprocessed_fif"] is True

    dlg2 = SettingsDialog(win.settings, win, reloaded)
    qtbot.addWidget(dlg2)
    assert dlg2.preproc_edits[2].text() == "256"
    assert dlg2.stim_edit.text() == "Trigger"
    assert dlg2.save_fif_check.isChecked() is True

    win.loadProject(reloaded)
    first_row = win.event_rows[0].findChildren(QLineEdit)
    first_row[0].setText("CondA")
    first_row[1].setText("10")

    params = win._build_validated_params()
    assert params["downsample"] == 256
    assert params["reject_thresh"] == 3.5
    assert params["epoch_end"] == 100.0
    assert params["stim_channel"] == "Trigger"
    assert params["save_preprocessed_fif"] is True


def test_dialog_saves_bandpass_mapping(tmp_path, qtbot, monkeypatch):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)

    dlg.preproc_edits[0].setText("40")
    dlg.preproc_edits[1].setText("0.2")
    dlg._save()

    saved = json.loads((project.project_root / "project.json").read_text())
    assert saved["preprocessing"]["low_pass"] == 40.0
    assert saved["preprocessing"]["high_pass"] == 0.2


def test_preproc_tab_blocks_invalid_bandpass(tmp_path, qtbot, monkeypatch):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args[2] if len(args) >= 3 else kwargs.get("text", "")),
    )
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)

    dlg.tabs.setCurrentIndex(dlg._preproc_tab_index)
    dlg.preproc_edits[0].setText("0.1")
    dlg.preproc_edits[1].setText("50")
    dlg.tabs.setCurrentIndex(dlg._loreta_tab_index)

    assert dlg.tabs.currentIndex() == dlg._preproc_tab_index
    assert warnings

    dlg.preproc_edits[0].setText("60")
    dlg.preproc_edits[1].setText("0.5")
    dlg.tabs.setCurrentIndex(dlg._loreta_tab_index)

    assert dlg.tabs.currentIndex() == dlg._loreta_tab_index
