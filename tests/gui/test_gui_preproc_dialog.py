import importlib.util
import json
import os
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from Main_App.projects.project import Project
from Main_App.gui.main_window import MainWindow
from Main_App.gui.components import SectionCard
import Main_App.gui.settings_panel as settings_panel
from Main_App.gui.settings_panel import SettingsDialog


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
            "max_parallel_workers_override": 0,
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
    assert not hasattr(dlg, "save_fif_check")

    dlg.preproc_edits[2].setText("256")
    dlg.preproc_edits[4].setText("3.5")
    dlg.preproc_edits[5].setText("100")
    dlg.stim_edit.setText("Trigger")

    dlg._save()

    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["downsample"] == 256
    assert reloaded.preprocessing["rejection_z"] == 3.5
    assert reloaded.preprocessing["epoch_end_s"] == 100.0
    assert reloaded.preprocessing["stim_channel"] == "Trigger"
    assert "save_preprocessed_fif" not in reloaded.preprocessing

    dlg2 = SettingsDialog(win.settings, win, reloaded)
    qtbot.addWidget(dlg2)
    assert dlg2.preproc_edits[2].text() == "256"
    assert dlg2.stim_edit.text() == "Trigger"
    assert not hasattr(dlg2, "save_fif_check")

    win.loadProject(reloaded)
    first_row = win.event_rows[0].findChildren(QLineEdit)
    first_row[0].setText("CondA")
    first_row[1].setText("10")

    params = win._build_validated_params()
    assert params["downsample"] == 256
    assert params["reject_thresh"] == 3.5
    assert params["epoch_end"] == 100.0
    assert params["stim_channel"] == "Trigger"
    assert params["save_preprocessed_fif"] is False


def test_settings_dialog_uses_shared_component_layer(tmp_path, qtbot):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)

    cards = {
        card.header.title_label.text(): card for card in dlg.findChildren(SectionCard)
    }
    assert "Preprocessing Parameters" in cards
    assert dlg.group_preproc is cards["Preprocessing Parameters"]
    assert dlg.btn_changeRoot.property("secondary") is True


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


def test_preproc_tab_blocks_invalid_bandpass_when_leaving_tab(tmp_path, qtbot, monkeypatch):
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

    stats_tab_index = next(
        i for i in range(dlg.tabs.count()) if dlg.tabs.tabText(i) == "Stats"
    )
    dlg.tabs.setCurrentIndex(dlg._preproc_tab_index)
    dlg.preproc_edits[0].setText("0.1")
    dlg.preproc_edits[1].setText("50")
    dlg.tabs.setCurrentIndex(stats_tab_index)

    assert dlg.tabs.currentIndex() == dlg._preproc_tab_index
    assert warnings

    dlg.preproc_edits[0].setText("60")
    dlg.preproc_edits[1].setText("0.5")
    dlg.tabs.setCurrentIndex(stats_tab_index)

    assert dlg.tabs.currentIndex() == stats_tab_index


def test_parallel_worker_override_warning_blocks_save_on_no(tmp_path, qtbot, monkeypatch):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    monkeypatch.setattr(
        settings_panel.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=int(16 * (1024 ** 3))),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    prompts: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: (
            prompts.append(args[2] if len(args) >= 3 else kwargs.get("text", "")),
            QMessageBox.No,
        )[1],
    )

    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    dlg.preproc_edits[10].setText("6")
    dlg._save()

    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["max_parallel_workers_override"] == 0
    assert prompts
    assert "[4]" in prompts[0]


def test_parallel_worker_override_warning_allows_save_on_yes(tmp_path, qtbot, monkeypatch):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    monkeypatch.setattr(
        settings_panel.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=int(16 * (1024 ** 3))),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    dlg.preproc_edits[10].setText("6")
    dlg._save()

    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["max_parallel_workers_override"] == 6
