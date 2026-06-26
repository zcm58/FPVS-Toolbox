import importlib.util
import json
import os
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QWidget

from Main_App.projects.project import Project
from Main_App.gui.main_window import MainWindow
from Main_App.gui.manual_participant_exclusions_dialog import (
    ManualParticipantExclusionsDialog,
)
from Main_App.gui.manual_removed_electrodes_dialog import ManualRemovedElectrodesDialog
from Main_App.gui import processing_inputs
from Main_App.gui.components import ActionRow, SectionCard, SubsectionHeaderLabel
from Main_App.gui.style_tokens import EVENT_REMOVE_BUTTON_SIZE
from Main_App.processing.processing_controller import RawFileInfo
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
            "auto_detect_removed_electrodes": True,
            "removed_electrode_detection_mode": "auto",
            "manual_removed_electrodes": {},
            "manual_excluded_participants": [],
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
    assert not hasattr(dlg, "stim_edit")
    assert not hasattr(dlg, "save_fif_check")

    dlg.preproc_edits[2].setText("256")
    dlg.preproc_edits[4].setText("3.5")
    dlg.preproc_edits[5].setText("100")
    dlg.auto_detect_removed_electrodes_check.setChecked(False)
    assert dlg.removed_electrode_detection_mode_combo.currentData() == "off"

    dlg._save()

    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["downsample"] == 256
    assert reloaded.preprocessing["rejection_z"] == 3.5
    assert reloaded.preprocessing["epoch_end_s"] == 100.0
    assert reloaded.preprocessing["auto_detect_removed_electrodes"] is False
    assert reloaded.preprocessing["removed_electrode_detection_mode"] == "off"
    assert reloaded.preprocessing["manual_excluded_participants"] == []
    assert reloaded.preprocessing["stim_channel"] == "Status"
    assert "save_preprocessed_fif" not in reloaded.preprocessing

    dlg2 = SettingsDialog(win.settings, win, reloaded)
    qtbot.addWidget(dlg2)
    assert dlg2.preproc_edits[2].text() == "256"
    assert not hasattr(dlg2, "stim_edit")
    assert not hasattr(dlg2, "save_fif_check")

    win.loadProject(reloaded)
    first_row = win.event_rows[0].findChildren(QLineEdit)
    first_row[0].setText("CondA")
    first_row[1].setText("10")

    params = win._build_validated_params()
    assert params["downsample"] == 256
    assert params["reject_thresh"] == 3.5
    assert params["epoch_end"] == 100.0
    assert params["auto_detect_removed_electrodes"] is False
    assert params["removed_electrode_detection_mode"] == "off"
    assert params["manual_excluded_participants"] == []
    assert params["stim_channel"] == "Status"
    assert params["save_preprocessed_fif"] is False


def test_settings_dialog_beta_tools_save_prompts_for_restart(tmp_path, qtbot, monkeypatch):
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    win.settings.set_beta_tools_enabled(False)
    win.settings.save()

    info_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, message, *_args, **_kwargs: info_calls.append((title, message)),
    )

    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    assert dlg.beta_tools_check.isChecked() is False

    dlg.beta_tools_check.setChecked(True)
    dlg._save()

    expected_message = "Please close and reopen FPVS Toolbox for your changes to take effect."
    assert ("Tool Visibility Updated", expected_message) in info_calls
    assert win.settings.beta_tools_enabled() is True

    dlg2 = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg2)
    assert dlg2.beta_tools_check.isChecked() is True

    dlg2.beta_tools_check.setChecked(False)
    dlg2._save()

    assert info_calls.count(("Tool Visibility Updated", expected_message)) == 2
    assert win.settings.beta_tools_enabled() is False


def test_settings_dialog_uses_shared_component_layer(tmp_path, qtbot, monkeypatch):
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
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
    assert "Application Options" in cards
    assert "Processing QC" in cards
    assert "Diagnostics" not in cards
    assert "Tool Visibility" not in cards
    assert "Analysis Defaults" in cards
    assert "Quick Add" in cards
    assert "Regions of Interest" in cards
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == [
        "Preprocessing",
        "Stats",
        "ROIs",
        "Advanced",
    ]
    assert "General" not in [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert "Oddball" not in [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert dlg.group_preproc is cards["Preprocessing Parameters"]
    assert cards["Application Options"].isAncestorOf(dlg.debug_check)
    assert cards["Application Options"].isAncestorOf(dlg.beta_tools_check)
    assert cards["Processing QC"].isAncestorOf(dlg.auto_detect_removed_electrodes_check)
    assert cards["Processing QC"].isAncestorOf(dlg.removed_electrode_detection_mode_combo)
    assert cards["Processing QC"].isAncestorOf(dlg.removed_electrode_detection_info_button)
    assert cards["Processing QC"].isAncestorOf(dlg.manual_removed_electrodes_button)
    assert cards["Processing QC"].isAncestorOf(dlg.manual_participant_exclusions_button)
    assert dlg.auto_detect_removed_electrodes_check.isChecked() is True
    assert dlg.removed_electrode_detection_mode_combo.currentData() == "auto"
    assert dlg.removed_electrode_detection_mode_combo.itemText(0) == "Off"
    assert (
        dlg.removed_electrode_detection_mode_combo.itemText(1)
        == "Conservative auto-detect"
    )
    assert dlg.removed_electrode_detection_mode_combo.itemText(2) == "Manual list"
    assert dlg.manual_removed_electrodes_button.isEnabled() is False
    info_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, message, *_args, **_kwargs: info_calls.append((title, message)),
    )
    dlg.removed_electrode_detection_info_button.click()
    assert info_calls == [
        (
            "Conservative Removed-Electrode Detection",
            settings_panel.REMOVED_ELECTRODE_DETECTION_INFO_TEXT,
        )
    ]
    assert dlg.beta_tools_check.text() == "Enable Beta Tools"
    assert dlg.beta_tools_check.isChecked() is False
    assert cards["Analysis Defaults"].isAncestorOf(dlg.oddball_freq_edit)
    assert dlg.oddball_freq_edit.text() == "1.2"
    assert dlg.oddball_freq_edit.isReadOnly()
    assert cards["Regions of Interest"].sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert cards["Regions of Interest"].isAncestorOf(dlg.roi_editor)
    assert dlg.roi_editor.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    remove_buttons = dlg.roi_editor.findChildren(QPushButton, "settings_rois_remove_roi")
    assert remove_buttons
    assert all(button.text() == "x" for button in remove_buttons)
    assert all(button.property("variant") == "secondary" for button in remove_buttons)
    assert all(button.property("compact") is True for button in remove_buttons)
    assert all(button.property("iconButton") is True for button in remove_buttons)
    assert all(button.width() == EVENT_REMOVE_BUTTON_SIZE for button in remove_buttons)
    assert all(button.height() == EVENT_REMOVE_BUTTON_SIZE for button in remove_buttons)
    assert dlg.btn_changeRoot.property("secondary") is True
    preproc_tab = dlg.tabs.widget(dlg._preproc_tab_index)
    stats_tab_index = next(
        i for i in range(dlg.tabs.count()) if dlg.tabs.tabText(i) == "Stats"
    )
    rois_tab_index = next(
        i for i in range(dlg.tabs.count()) if dlg.tabs.tabText(i) == "ROIs"
    )
    advanced_tab_index = next(
        i for i in range(dlg.tabs.count()) if dlg.tabs.tabText(i) == "Advanced"
    )
    stats_tab = dlg.tabs.widget(stats_tab_index)
    rois_tab = dlg.tabs.widget(rois_tab_index)
    advanced_tab = dlg.tabs.widget(advanced_tab_index)
    assert not preproc_tab.isAncestorOf(cards["Application Options"])
    assert advanced_tab.isAncestorOf(cards["Application Options"])
    assert advanced_tab.isAncestorOf(cards["Processing QC"])
    assert rois_tab.isAncestorOf(cards["Regions of Interest"])
    assert rois_tab.isAncestorOf(cards["Quick Add"])
    assert not stats_tab.isAncestorOf(cards["Regions of Interest"])
    rois_layout = rois_tab.layout()
    assert rois_layout.indexOf(cards["Regions of Interest"]) < rois_layout.indexOf(cards["Quick Add"])
    assert preproc_tab.findChild(ActionRow, "settings_preproc_footer_actions") is not None
    assert stats_tab.findChild(ActionRow, "settings_stats_footer_actions") is not None
    assert rois_tab.findChild(ActionRow, "settings_rois_footer_actions") is not None
    assert advanced_tab.findChild(ActionRow, "settings_advanced_footer_actions") is not None
    assert preproc_tab.findChild(QWidget, "settings_preproc_footer") is not None
    assert stats_tab.findChild(QWidget, "settings_stats_footer") is not None
    assert rois_tab.findChild(QWidget, "settings_rois_footer") is not None
    assert advanced_tab.findChild(QWidget, "settings_advanced_footer") is not None
    assert rois_tab.findChild(ActionRow, "settings_rois_actions") is not None
    assert rois_tab.findChild(ActionRow, "settings_rois_quick_add_actions") is not None
    assert dlg.roi_montage_combo.count() == 1
    assert dlg.roi_montage_combo.currentData() == "10-10"
    assert dlg.roi_preset_combo.findText("LOT (Default)") >= 0
    assert dlg.roi_preset_combo.findText("ROT (Default)") >= 0
    assert dlg.roi_preset_electrodes_edit.isReadOnly()
    dlg.roi_preset_combo.setCurrentIndex(dlg.roi_preset_combo.findText("ROT (Default)"))
    dlg._add_selected_roi_preset()
    assert ("ROT", ["P8", "P10", "PO8", "PO4", "O2"]) in dlg.roi_editor.get_pairs()
    dlg.roi_editor.set_pairs([
        ("Custom Occipito Temporal", ["PO7", "PO8"]),
        ("LOT", ["BAD"]),
    ])
    dlg._save_roi_editor_as_custom_presets()
    assert dlg._custom_roi_presets_by_montage["10-10"] == [
        ("Custom Occipito Temporal", ["PO7", "PO8"]),
    ]
    roi_headers = {
        label.text()
        for label in cards["Regions of Interest"].findChildren(SubsectionHeaderLabel)
    }
    assert {"ROI name", "Electrodes"} <= roi_headers

    panel = settings_panel.SettingsPanel(controller=SimpleNamespace(save_settings=lambda _values: None))
    qtbot.addWidget(panel)
    actions = panel.findChild(ActionRow, "settings_panel_actions")
    assert actions is not None
    assert actions.row_layout.indexOf(panel.ok_btn) >= 0
    assert actions.row_layout.indexOf(panel.cancel_btn) >= 0


def test_manual_removed_electrodes_dialog_saves_project_map(tmp_path, qtbot, monkeypatch):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)
    project.participants = {
        "P01": {"raw_file": project.input_folder / "P01.bdf"},
        "P02": {"raw_file": project.input_folder / "P02.bdf"},
    }
    project.save()

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    def _fake_exec(self):
        self.table.item(0, 1).setText("ft7, P9")
        self.table.item(1, 1).setText("OZ")
        return QDialog.Accepted

    monkeypatch.setattr(ManualRemovedElectrodesDialog, "exec", _fake_exec)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    manual_index = dlg.removed_electrode_detection_mode_combo.findData("manual")
    dlg.removed_electrode_detection_mode_combo.setCurrentIndex(manual_index)

    assert dlg.manual_removed_electrodes_button.isEnabled() is True
    assert dlg._manual_removed_electrodes_by_pid == {
        "P01": ["FT7", "P9"],
        "P02": ["Oz"],
    }

    dlg._save()
    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["removed_electrode_detection_mode"] == "manual"
    assert reloaded.preprocessing["auto_detect_removed_electrodes"] is False
    assert reloaded.preprocessing["manual_removed_electrodes"] == {
        "P01": ["FT7", "P9"],
        "P02": ["Oz"],
    }


def test_manual_participant_exclusions_dialog_saves_project_list(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)
    project.participants = {
        "P01": {"raw_file": project.input_folder / "P01.bdf"},
        "P12": {"raw_file": project.input_folder / "P12.bdf"},
    }
    project.save()

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    def _fake_exec(self):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == "P12":
                self.table.item(row, 1).setCheckState(Qt.Checked)
        return QDialog.Accepted

    monkeypatch.setattr(ManualParticipantExclusionsDialog, "exec", _fake_exec)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    dlg._edit_manual_participant_exclusions()
    dlg._save()

    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["manual_excluded_participants"] == ["P12"]


def test_manual_removed_electrodes_prompt_updates_new_bdf_pool_pid(
    tmp_path,
    monkeypatch,
):
    project = _prep_project(tmp_path)
    project.update_preprocessing(
        {
            **project.preprocessing,
            "removed_electrode_detection_mode": "manual",
            "manual_removed_electrodes": {"P01": ["P9"]},
        }
    )
    project.save()
    raw_p01 = project.input_folder / "P01.bdf"
    raw_p02 = project.input_folder / "P02.bdf"
    host = SimpleNamespace(
        currentProject=project,
        validated_params={},
        log=lambda message, *args, **kwargs: None,
    )
    params = {
        "removed_electrode_detection_mode": "manual",
        "manual_removed_electrodes": {"P01": ["P9"]},
        "auto_detect_removed_electrodes": False,
    }

    captured: dict[str, object] = {}

    class FakeManualDialog:
        def __init__(self, participant_ids, manual_removed_electrodes, parent):
            captured["participant_ids"] = list(participant_ids)
            captured["manual_removed_electrodes"] = dict(manual_removed_electrodes)

        def exec(self):
            return QDialog.Accepted

        def manual_removed_electrodes(self):
            return {"P01": ["P9"], "P02": ["FT7"]}

    monkeypatch.setattr(
        processing_inputs,
        "ManualRemovedElectrodesDialog",
        FakeManualDialog,
    )

    accepted = processing_inputs._ensure_manual_removed_electrodes_reviewed(
        host,
        [
            RawFileInfo(raw_p01, "P01"),
            RawFileInfo(raw_p02, "P02"),
        ],
        params,
    )

    assert accepted is True
    assert captured["participant_ids"] == ["P01", "P02"]
    assert captured["manual_removed_electrodes"] == {"P01": ["P9"]}
    assert params["manual_removed_electrodes"] == {
        "P01": ["P9"],
        "P02": ["FT7"],
    }
    assert project.preprocessing["manual_removed_electrodes"] == {
        "P01": ["P9"],
        "P02": ["FT7"],
    }


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
