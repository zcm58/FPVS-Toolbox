import importlib.util
import json
import os
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from Main_App.Shared.settings_manager import SettingsManager
from Main_App.projects import (
    MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
    REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS,
    SUMMED_BCA_SCREENING_BRIEF_TEXT,
    FrequencyProtocol,
)
from Main_App.projects.project import Project
from Main_App.gui.main_window import MainWindow
from Main_App.gui.manual_participant_exclusions_dialog import (
    ManualParticipantExclusionsDialog,
)
from Main_App.gui.manual_removed_electrodes_dialog import ManualRemovedElectrodesDialog
from Main_App.gui.recording_qc_identity import QcRecordingIdentity
from Main_App.gui import processing_inputs
from Main_App.gui.components import ActionRow, SectionCard, SubsectionHeaderLabel
from Main_App.gui.style_tokens import EVENT_REMOVE_BUTTON_SIZE
from Main_App.gui.theme import apply_fpvs_theme
from Main_App.processing.processing_controller import RawFileInfo
import Main_App.gui.settings_panel as settings_panel
from Main_App.gui.settings_panel import SettingsDialog


_RETIRED_EPOCH_KEYS = {
    "epoch_start_s",
    "epoch_end_s",
    "epoch_start",
    "epoch_end",
}


class _FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        for callback in tuple(self._callbacks):
            callback(*args)


class _FakeSettingsWorker:
    def __init__(self):
        self.finished = _FakeSignal()
        self.failed = _FakeSignal()
        self.progress = _FakeSignal()
        self.phase_progress = _FakeSignal()
        self.deleted = False

    def moveToThread(self, _thread):
        return None

    def run(self):
        return None

    def deleteLater(self, *_args):
        self.deleted = True


class _FakeSettingsThread:
    def __init__(self, *, start_error: Exception | None = None):
        self.started = _FakeSignal()
        self.finished = _FakeSignal()
        self._start_error = start_error
        self._running = False
        self.deleted = False

    def start(self):
        if self._start_error is not None:
            raise self._start_error
        self._running = True

    def quit(self, *_args):
        self._running = False

    def isRunning(self):
        return self._running

    def deleteLater(self):
        self.deleted = True


def _prep_project(root):
    proj_root = root / "project"
    proj_root.mkdir()
    (proj_root / "project.json").write_text(
        json.dumps(
            {
                "preprocessing": {
                    "epoch_start_s": -0.25,
                    "epoch_end_s": 95.0,
                }
            }
        ),
        encoding="utf-8",
    )
    project = Project.load(proj_root)
    project.update_preprocessing(
        {
            "low_pass": 45.0,
            "high_pass": 0.25,
            "downsample": 512,
            "line_noise_filter_enabled": True,
            "line_noise_frequency_hz": 60,
            "rejection_z": 4.0,
            "ref_chan1": "Cz",
            "ref_chan2": "Pz",
            "max_chan_idx_keep": 32,
            "max_bad_chans": 5,
            "auto_detect_removed_electrodes": True,
            "removed_electrode_detection_mode": "auto",
            "manual_removed_electrodes": {},
            "manual_excluded_participants": [],
            "max_parallel_workers_override": 0,
            "harmonic_selection_policy": "Group-level significant harmonics (Volfart/Retter/Rossion style)",
            "harmonic_selection_profile": "legacy_fpvs_toolbox",
            "harmonic_selection_profile_version": "1.0",
            "group_significant_electrode_scope": "union_roi_electrodes",
            "group_significant_summation_method": "through_highest_significant",
            "fixed_harmonic_frequencies_hz": "1.2, 2.4, 3.6, 4.8, 7.2",
            "fixed_harmonic_auto_exclude_base": True,
            "stim_channel": "Status",
        }
    )
    project.confirm_removed_electrode_detection_choice("auto")
    project.update_frequency_protocol(
        FrequencyProtocol.from_recurrence(
            "6",
            5,
            expected_analyzed_oddball_cycles=144,
            expected_analyzed_oddball_cycles_source="manual",
        )
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
    preproc_labels = {
        label.text() for label in dlg.group_preproc.findChildren(QLabel)
    }
    assert "Epoch Start (s):" not in preproc_labels
    assert "Epoch End (s):" not in preproc_labels
    assert not hasattr(dlg, "stim_edit")
    assert not hasattr(dlg, "save_fif_check")
    assert dlg.line_noise_filter_enabled_check.isChecked() is True
    assert dlg.line_noise_frequency_combo.currentData() == 60
    assert dlg.line_noise_frequency_combo.isEnabled() is True
    assert dlg.electrode_montage_combo.count() == 1
    assert dlg.electrode_montage_combo.currentText() == "BioSemi ActiveTwo 64"
    assert dlg.electrode_montage_combo.currentData() == "biosemi64"
    assert dlg.electrode_montage_combo.isEnabled() is False
    assert (
        dlg.electrode_mapping_profile_combo.currentData() == "anatomical_labels"
    )
    assert dlg.electrode_mapping_profile_combo.isEnabled() is True
    assert "ABC" in dlg.electrode_mapping_profile_combo.toolTip()
    assert dlg.roi_montage_combo is not dlg.electrode_montage_combo

    dlg.preproc_edits[2].setText("256")
    dlg.preproc_edits[3].setText("3.5")
    significant_only_index = dlg.harmonic_summation_method_combo.findData(
        "significant_only_exploratory"
    )
    dlg.harmonic_summation_method_combo.setCurrentIndex(significant_only_index)
    all_electrodes_index = dlg.harmonic_electrode_scope_combo.findData("all_scalp_electrodes")
    dlg.harmonic_electrode_scope_combo.setCurrentIndex(all_electrodes_index)
    dlg.auto_detect_removed_electrodes_check.setChecked(False)
    assert dlg.removed_electrode_detection_mode_combo.currentData() == "off"
    dlg.summed_bca_screening_enabled_check.setChecked(False)
    assert not dlg.condition_specific_interpolation_enabled_check.isChecked()
    dlg.condition_specific_interpolation_enabled_check.setChecked(True)
    dlg.summed_bca_threshold_edits["warning_summed_bca_uv"].setText("12.5")
    dlg.line_noise_frequency_combo.setCurrentIndex(
        dlg.line_noise_frequency_combo.findData(50)
    )
    dlg.line_noise_filter_enabled_check.setChecked(False)
    assert dlg.line_noise_frequency_combo.isEnabled() is False
    assert dlg.line_noise_frequency_combo.currentData() == 50
    ab_profile_index = dlg.electrode_mapping_profile_combo.findData(
        "biosemi64_1020_ab_v1"
    )
    assert ab_profile_index >= 0
    dlg.electrode_mapping_profile_combo.setCurrentIndex(ab_profile_index)

    dlg._save()

    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["downsample"] == 256
    assert reloaded.preprocessing["rejection_z"] == 3.5
    assert _RETIRED_EPOCH_KEYS.isdisjoint(reloaded.preprocessing)
    assert reloaded.preprocessing["line_noise_filter_enabled"] is False
    assert reloaded.preprocessing["line_noise_frequency_hz"] == 50
    assert reloaded.preprocessing["electrode_montage"] == "biosemi64"
    assert (
        reloaded.preprocessing["electrode_mapping_profile"]
        == "biosemi64_1020_ab_v1"
    )
    assert reloaded.preprocessing["auto_detect_removed_electrodes"] is False
    assert reloaded.preprocessing["removed_electrode_detection_mode"] == "off"
    assert reloaded.experimental_qc_settings.summed_bca_screening.enabled is False
    assert reloaded.experimental_qc_settings.condition_specific_interpolation_enabled is True
    assert (
        reloaded.experimental_qc_settings.summed_bca_screening.warning_summed_bca_uv
        == 12.5
    )
    assert reloaded.preprocessing["manual_excluded_participants"] == []
    assert reloaded.preprocessing["harmonic_selection_policy"] == (
        "Group-level significant harmonics (Volfart/Retter/Rossion style)"
    )
    assert reloaded.preprocessing["group_significant_summation_method"] == "significant_only"
    assert reloaded.preprocessing["harmonic_selection_profile"] == (
        "significant_only_exploratory"
    )
    assert reloaded.preprocessing["group_significant_electrode_scope"] == "all_scalp_electrodes"
    assert reloaded.preprocessing["stim_channel"] == "Status"
    assert "save_preprocessed_fif" not in reloaded.preprocessing
    saved_manifest = json.loads(
        (project.project_root / "project.json").read_text(encoding="utf-8")
    )
    assert _RETIRED_EPOCH_KEYS.isdisjoint(saved_manifest["preprocessing"])
    assert saved_manifest["compatibility"]["processing_fingerprint_v9"] == {
        "epoch_start_s": -0.25,
        "epoch_end_s": 95.0,
    }

    dlg2 = SettingsDialog(win.settings, win, reloaded)
    qtbot.addWidget(dlg2)
    assert dlg2.preproc_edits[2].text() == "256"
    assert not hasattr(dlg2, "stim_edit")
    assert not hasattr(dlg2, "save_fif_check")
    assert dlg2.line_noise_filter_enabled_check.isChecked() is False
    assert dlg2.line_noise_frequency_combo.currentData() == 50
    assert dlg2.line_noise_frequency_combo.isEnabled() is False
    assert dlg2.electrode_montage_combo.count() == 1
    assert dlg2.electrode_montage_combo.currentData() == "biosemi64"
    assert dlg2.electrode_montage_combo.isEnabled() is False
    assert (
        dlg2.electrode_mapping_profile_combo.currentData()
        == "biosemi64_1020_ab_v1"
    )

    win.loadProject(reloaded)
    first_row = win.event_rows[0].findChildren(QLineEdit)
    first_row[0].setText("CondA")
    first_row[1].setText("10")

    params = win._build_validated_params()
    assert params["downsample"] == 256
    assert params["reject_thresh"] == 3.5
    assert _RETIRED_EPOCH_KEYS.isdisjoint(params)
    assert params["line_noise_filter_enabled"] is False
    assert params["line_noise_frequency_hz"] == 50
    assert params["auto_detect_removed_electrodes"] is False
    assert params["removed_electrode_detection_mode"] == "off"
    assert params["manual_excluded_participants"] == []
    assert params["stim_channel"] == "Status"
    assert params["save_preprocessed_fif"] is False


def test_unrelated_settings_save_does_not_confirm_missing_detector_choice(
    tmp_path,
    qtbot,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)
    manifest_path = project.project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS:
        manifest["preprocessing"].pop(key, None)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    project = Project.load(project.project_root)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)

    assert dlg.removed_electrode_detection_mode_combo.currentData() is None
    dlg.preproc_edits[0].setText("40")
    dlg._save()

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["preprocessing"]["low_pass"] == 40.0
    assert set(REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS).isdisjoint(
        saved["preprocessing"]
    )


def test_protocol_tab_requires_explicit_legacy_confirmation(
    tmp_path,
    qtbot,
    monkeypatch,
):
    project_root = tmp_path / "legacy_project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps({"event_map": {"Condition A": 11}}),
        encoding="utf-8",
    )
    project = Project.load(project_root)
    manager = SettingsManager(str(tmp_path / "settings.ini"))
    QApplication.instance() or QApplication([])
    dlg = SettingsDialog(manager, project=project)
    qtbot.addWidget(dlg)
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message, *_args, **_kwargs: warnings.append(
            (title, message)
        ),
    )

    assert dlg.protocol_presentation_rate_edit.text() == "6"
    assert dlg.protocol_oddball_every_n_edit.text() == "5"
    assert dlg.protocol_expected_cycles_edit.text() == ""
    assert dlg.protocol_oddball_marker_code_edit.text() == "55"
    assert dlg.protocol_marker_code_help.text() == (
        "Oddball marker code: Event code emitted for each oddball in every "
        "condition. Default: 55."
    )

    dlg._save()
    assert warnings[0][0] == "Invalid FPVS Protocol"
    assert "frequency_protocol" not in json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )

    dlg.protocol_expected_cycles_edit.setText("144")
    dlg._save()
    reloaded = Project.load(project_root)
    assert reloaded.frequency_protocol.is_ready
    assert reloaded.frequency_protocol.expected_analyzed_oddball_cycles == 144


def test_protocol_tab_direct_rate_updates_implied_recurrence(
    tmp_path,
    qtbot,
):
    project = _prep_project(tmp_path)
    manager = SettingsManager(str(tmp_path / "settings.ini"))
    QApplication.instance() or QApplication([])
    dlg = SettingsDialog(manager, project=project)
    qtbot.addWidget(dlg)

    direct_index = dlg.protocol_oddball_mode_combo.findData(
        "oddball_rate_hz"
    )
    dlg.protocol_oddball_mode_combo.setCurrentIndex(direct_index)
    dlg.protocol_direct_oddball_rate_edit.setText("2")

    assert dlg.protocol_oddball_every_n_edit.text() == "3"
    assert dlg.protocol_resolved_oddball_rate_edit.text() == "2 Hz"
    assert dlg.protocol_derived_duration_edit.text() == "72 seconds"

    dlg._save()
    reloaded = Project.load(project.project_root)
    assert reloaded.frequency_protocol.oddball_input_mode == "oddball_rate_hz"
    assert reloaded.frequency_protocol.oddball_every_n == 3
    assert str(reloaded.frequency_protocol.entered_oddball_rate_hz) == "2"


def test_dialog_loads_saves_app_line_noise_settings_without_project(tmp_path, qtbot):
    QApplication.instance() or QApplication([])
    manager = SettingsManager(str(tmp_path / "settings.ini"))

    dlg = SettingsDialog(manager)
    qtbot.addWidget(dlg)
    assert dlg.line_noise_filter_enabled_check.isChecked() is True
    assert dlg.line_noise_frequency_combo.currentData() == 60
    assert dlg.electrode_montage_combo.currentData() == "biosemi64"
    assert dlg.electrode_montage_combo.isEnabled() is False
    assert (
        dlg.electrode_mapping_profile_combo.currentData() == "anatomical_labels"
    )
    assert dlg.electrode_mapping_profile_combo.isEnabled() is False

    dlg.line_noise_frequency_combo.setCurrentIndex(
        dlg.line_noise_frequency_combo.findData(50)
    )
    dlg.line_noise_filter_enabled_check.setChecked(False)
    dlg._save()

    reloaded_manager = SettingsManager(str(tmp_path / "settings.ini"))
    assert (
        reloaded_manager.get("preprocessing", "line_noise_filter_enabled")
        == "False"
    )
    assert reloaded_manager.get("preprocessing", "line_noise_frequency_hz") == "50"

    dlg2 = SettingsDialog(reloaded_manager)
    qtbot.addWidget(dlg2)
    assert dlg2.line_noise_filter_enabled_check.isChecked() is False
    assert dlg2.line_noise_frequency_combo.currentData() == 50
    assert dlg2.line_noise_frequency_combo.isEnabled() is False


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
    assert "Project FPVS Protocol" in cards
    assert "Harmonic Selection and Summation" in cards
    assert "Application Options" in cards
    assert "Processing QC" in cards
    assert "Experimental Removed-Electrode Detection" in cards
    assert "Experimental Summed-BCA Screening" in cards
    assert "Diagnostics" not in cards
    assert "Tool Visibility" not in cards
    assert "Analysis Defaults" in cards
    assert "Quick Add" in cards
    assert "Regions of Interest" in cards
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == [
        "Preprocessing",
        "Protocol",
        "Harmonics",
        "Stats",
        "ROIs",
        "Experimental",
        "Advanced",
    ]
    assert "General" not in [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert "Oddball" not in [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert dlg.group_preproc is cards["Preprocessing Parameters"]
    assert cards["Preprocessing Parameters"].isAncestorOf(
        dlg.line_noise_filter_enabled_check
    )
    assert cards["Preprocessing Parameters"].isAncestorOf(
        dlg.line_noise_frequency_combo
    )
    assert dlg.line_noise_filter_enabled_check.text() == "Remove mains line noise"
    assert dlg.line_noise_filter_enabled_check.isChecked() is True
    assert dlg.line_noise_frequency_combo.currentData() == 60
    assert dlg.line_noise_frequency_combo.itemData(0) == 60
    assert dlg.line_noise_frequency_combo.itemData(1) == 50
    assert "0.5 Hz" in dlg.line_noise_filter_enabled_check.toolTip()
    assert "first two harmonics" in dlg.line_noise_frequency_combo.toolTip()
    dlg.line_noise_frequency_combo.setCurrentIndex(
        dlg.line_noise_frequency_combo.findData(50)
    )
    dlg.line_noise_filter_enabled_check.setChecked(False)
    assert dlg.line_noise_frequency_combo.isEnabled() is False
    assert dlg.line_noise_frequency_combo.currentData() == 50
    dlg.line_noise_filter_enabled_check.setChecked(True)
    assert dlg.line_noise_frequency_combo.isEnabled() is True
    assert dlg.line_noise_frequency_combo.currentData() == 50
    harmonic_card = cards["Harmonic Selection and Summation"]
    assert harmonic_card.isAncestorOf(dlg.harmonic_summation_method_combo)
    assert harmonic_card.isAncestorOf(dlg.harmonic_electrode_scope_combo)
    assert harmonic_card.isAncestorOf(dlg.fixed_harmonic_freqs_edit)
    assert harmonic_card.isAncestorOf(dlg.recalculate_harmonics_button)
    assert harmonic_card.isAncestorOf(dlg.harmonic_recalculation_status)
    assert harmonic_card.isAncestorOf(dlg.fixed_harmonic_warning)
    assert dlg.fixed_harmonic_warning.isHidden() is False
    assert dlg.recalculate_harmonics_button.text() == "Recalculate Harmonics"
    assert dlg.recalculate_harmonics_button.isEnabled() is True
    assert dlg.findChild(ActionRow, "settings_harmonic_selection_actions") is not None
    assert dlg.harmonic_summation_method_combo.itemText(0) == (
        "Dzhelyova/Poncet — stop after two consecutive failures (recommended)"
    )
    assert dlg.harmonic_summation_method_combo.itemText(1) == (
        "Fixed / preregistered harmonic domain"
    )
    assert dlg.harmonic_summation_method_combo.itemText(2) == (
        "Significant-only (exploratory)"
    )
    assert dlg.harmonic_summation_method_combo.currentData() == "legacy_fpvs_toolbox"
    assert dlg.harmonic_electrode_scope_combo.currentData() == "union_roi_electrodes"
    assert dlg.fixed_harmonic_freqs_edit.isEnabled() is False
    fixed_list_index = dlg.harmonic_summation_method_combo.findData(
        "fixed_preregistered_domain"
    )
    dlg.harmonic_summation_method_combo.setCurrentIndex(fixed_list_index)
    assert dlg.fixed_harmonic_freqs_edit.isEnabled() is True
    assert dlg.fixed_harmonic_input_mode_combo.isEnabled() is True
    assert dlg.harmonic_electrode_scope_combo.isEnabled() is False
    assert dlg.fixed_harmonic_exclude_base_check.isChecked() is True
    assert dlg.fixed_harmonic_exclude_base_check.isEnabled() is False
    assert dlg.fixed_harmonic_warning.isHidden() is False
    upper_index_mode = dlg.fixed_harmonic_input_mode_combo.findData(
        "upper_harmonic_index"
    )
    dlg.fixed_harmonic_input_mode_combo.setCurrentIndex(upper_index_mode)
    assert dlg.fixed_harmonic_freqs_edit.isEnabled() is False
    assert dlg.fixed_harmonic_upper_index_edit.isEnabled() is True
    assert dlg.fixed_harmonic_upper_frequency_edit.isEnabled() is False
    assert cards["Application Options"].isAncestorOf(dlg.debug_check)
    assert cards["Application Options"].isAncestorOf(dlg.beta_tools_check)
    detector_card = cards["Experimental Removed-Electrode Detection"]
    summed_bca_card = cards["Experimental Summed-BCA Screening"]
    assert detector_card.isAncestorOf(dlg.auto_detect_removed_electrodes_check)
    assert detector_card.isAncestorOf(dlg.removed_electrode_detection_mode_combo)
    assert detector_card.isAncestorOf(dlg.removed_electrode_detection_info_button)
    assert detector_card.isAncestorOf(dlg.manual_removed_electrodes_enabled_check)
    assert detector_card.isAncestorOf(dlg.manual_removed_electrodes_button)
    assert cards["Processing QC"].isAncestorOf(dlg.manual_participant_exclusions_button)
    assert dlg.auto_detect_removed_electrodes_check.isChecked() is True
    assert dlg.removed_electrode_detection_mode_combo.currentData() == "auto"
    assert dlg.removed_electrode_detection_mode_combo.itemText(0) == (
        "Off (recommended)"
    )
    assert dlg.removed_electrode_detection_mode_combo.itemText(1) == "On"
    assert dlg.removed_electrode_detection_mode_combo.count() == 2
    assert dlg.manual_removed_electrodes_enabled_check.isChecked() is False
    assert dlg.manual_removed_electrodes_button.isEnabled() is True
    assert dlg.summed_bca_explanation_label.text() == SUMMED_BCA_SCREENING_BRIEF_TEXT
    assert dlg.summed_bca_screening_enabled_check.isChecked() is True
    assert len(dlg.summed_bca_threshold_edits) == 11
    assert all(
        summed_bca_card.isAncestorOf(edit)
        for edit in dlg.summed_bca_threshold_edits.values()
    )
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
    assert cards["Project FPVS Protocol"].isAncestorOf(dlg.oddball_freq_edit)
    assert dlg.oddball_freq_edit.text() == "1.2 Hz (exactly 6/5 Hz)"
    assert dlg.oddball_freq_edit.isReadOnly()
    assert dlg.protocol_derived_duration_edit.text() == "120 seconds"
    assert dlg.protocol_oddball_marker_code_edit.text() == "55"
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
    harmonics_tab_index = next(
        i for i in range(dlg.tabs.count()) if dlg.tabs.tabText(i) == "Harmonics"
    )
    protocol_tab_index = next(
        i for i in range(dlg.tabs.count()) if dlg.tabs.tabText(i) == "Protocol"
    )
    stats_tab_index = next(
        i for i in range(dlg.tabs.count()) if dlg.tabs.tabText(i) == "Stats"
    )
    rois_tab_index = next(
        i for i in range(dlg.tabs.count()) if dlg.tabs.tabText(i) == "ROIs"
    )
    advanced_tab_index = next(
        i for i in range(dlg.tabs.count()) if dlg.tabs.tabText(i) == "Advanced"
    )
    experimental_tab_index = next(
        i for i in range(dlg.tabs.count()) if dlg.tabs.tabText(i) == "Experimental"
    )
    harmonics_tab = dlg.tabs.widget(harmonics_tab_index)
    protocol_tab = dlg.tabs.widget(protocol_tab_index)
    stats_tab = dlg.tabs.widget(stats_tab_index)
    rois_tab = dlg.tabs.widget(rois_tab_index)
    advanced_tab = dlg.tabs.widget(advanced_tab_index)
    experimental_tab = dlg.tabs.widget(experimental_tab_index)
    assert not preproc_tab.isAncestorOf(cards["Application Options"])
    assert not preproc_tab.isAncestorOf(cards["Harmonic Selection and Summation"])
    assert protocol_tab.isAncestorOf(cards["Project FPVS Protocol"])
    assert protocol_tab.objectName() == "settings_protocol_tab"
    assert harmonics_tab.isAncestorOf(cards["Harmonic Selection and Summation"])
    assert harmonics_tab.objectName() == "settings_harmonics_tab"
    assert advanced_tab.isAncestorOf(cards["Application Options"])
    assert advanced_tab.isAncestorOf(cards["Processing QC"])
    assert experimental_tab.isAncestorOf(detector_card)
    assert experimental_tab.isAncestorOf(summed_bca_card)
    assert experimental_tab.objectName() == "settings_experimental_tab"
    assert rois_tab.isAncestorOf(cards["Regions of Interest"])
    assert rois_tab.isAncestorOf(cards["Quick Add"])
    assert not stats_tab.isAncestorOf(cards["Regions of Interest"])
    rois_layout = rois_tab.layout()
    assert rois_layout.indexOf(cards["Regions of Interest"]) < rois_layout.indexOf(cards["Quick Add"])
    assert preproc_tab.findChild(ActionRow, "settings_preproc_footer_actions") is not None
    assert protocol_tab.findChild(ActionRow, "settings_protocol_footer_actions") is not None
    assert harmonics_tab.findChild(ActionRow, "settings_harmonic_footer_actions") is not None
    assert stats_tab.findChild(ActionRow, "settings_stats_footer_actions") is not None
    assert rois_tab.findChild(ActionRow, "settings_rois_footer_actions") is not None
    assert experimental_tab.findChild(
        ActionRow,
        "settings_experimental_footer_actions",
    ) is not None
    assert advanced_tab.findChild(ActionRow, "settings_advanced_footer_actions") is not None
    assert preproc_tab.findChild(QWidget, "settings_preproc_footer") is not None
    assert protocol_tab.findChild(QWidget, "settings_protocol_footer") is not None
    assert harmonics_tab.findChild(QWidget, "settings_harmonic_footer") is not None
    assert stats_tab.findChild(QWidget, "settings_stats_footer") is not None
    assert rois_tab.findChild(QWidget, "settings_rois_footer") is not None
    assert advanced_tab.findChild(QWidget, "settings_advanced_footer") is not None
    assert rois_tab.findChild(ActionRow, "settings_rois_actions") is not None
    assert rois_tab.findChild(ActionRow, "settings_rois_quick_add_actions") is not None
    assert dlg.roi_montage_combo.count() == 1
    assert dlg.roi_montage_combo.currentData() == "biosemi64"
    assert dlg.roi_montage_combo.currentText() == "BioSemi ActiveTwo 64"
    assert not dlg.roi_montage_combo.isEnabled()
    assert not dlg.tabs.tabBar().drawBase()
    assert not dlg.experimental_tabs.tabBar().drawBase()
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
    assert dlg._custom_roi_presets_by_montage["biosemi64"] == [
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


@pytest.fixture
def experimental_settings_page(tmp_path, qtbot):
    project = _prep_project(tmp_path)
    manifest_path = project.project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS:
        manifest["preprocessing"].pop(key, None)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    project = Project.load(project.project_root)

    app = QApplication.instance() or QApplication([])
    previous_stylesheet = app.styleSheet()
    previous_font = app.font()
    previous_palette = app.palette()
    previous_style = app.style().objectName()
    host = QWidget()
    qtbot.addWidget(host)
    try:
        apply_fpvs_theme(app)
        # This is the settings area inside the supported 1280 x 900 shell.
        # A fixed host prevents a large minimum size from hiding overflow by
        # silently enlarging the test window.
        host.setFixedSize(1000, 780)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        manager = SettingsManager(str(tmp_path / "settings.ini"))
        page = settings_panel.EmbeddedSettingsPage(manager, host, project)
        layout.addWidget(page)
        page.tabs.setCurrentIndex(page._experimental_tab_index)
        host.show()
        qtbot.waitExposed(host)
        yield page
    finally:
        host.close()
        app.setStyle(previous_style)
        app.setFont(previous_font)
        app.setPalette(previous_palette)
        app.setStyleSheet(previous_stylesheet)


def test_experimental_sections_fit_embedded_workspace(experimental_settings_page, qtbot):
    page = experimental_settings_page
    host = page.parentWidget()
    sections = page.experimental_tabs
    assert [sections.tabText(index) for index in range(sections.count())] == [
        "Electrodes",
        "Raw-Spectral Review",
        "Summed-BCA Screening",
    ]

    def assert_unclipped(widget):
        name = widget.objectName() or type(widget).__name__
        assert widget.isVisibleTo(host), name
        minimum_height = widget.minimumSizeHint().height()
        if isinstance(widget, QLabel) and widget.wordWrap():
            minimum_height = max(minimum_height, widget.heightForWidth(widget.width()))
        assert widget.height() >= minimum_height, name
        if isinstance(widget, (QLineEdit, QComboBox, QAbstractButton)):
            assert widget.width() >= widget.minimumSizeHint().width(), name
        ancestor = widget.parentWidget()
        while ancestor is not None:
            bounds = QRect(widget.mapTo(ancestor, QPoint(0, 0)), widget.size())
            assert ancestor.rect().contains(bounds), (name, ancestor.objectName())
            if ancestor is host:
                break
            ancestor = ancestor.parentWidget()

    expected_controls = (
        (
            page.kurtosis_auto_interpolate_all_check,
            page.condition_specific_interpolation_enabled_check,
            page.removed_electrode_detection_mode_combo,
            page.removed_electrode_detection_info_button,
            page.manual_removed_electrodes_enabled_check,
            page.manual_removed_electrodes_button,
            page.removed_electrode_detection_status,
        ),
        (
            page.raw_spectral_screening_enabled_check,
            page.raw_spectral_advanced_toggle,
            *page.raw_spectral_advanced_value_labels.values(),
        ),
        (
            page.summed_bca_screening_enabled_check,
            *page.summed_bca_threshold_edits.values(),
        ),
    )
    assert page.removed_electrode_detection_mode_combo.currentData() is None
    assert len(page.raw_spectral_advanced_value_labels) == 8
    assert len(page.summed_bca_threshold_edits) == 11

    for index, controls in enumerate(expected_controls):
        sections.setCurrentIndex(index)
        section = sections.currentWidget()
        qtbot.waitUntil(lambda: section.isVisibleTo(host))
        if index == 1:
            assert page.raw_spectral_advanced_values.isHidden()
            qtbot.mouseClick(page.raw_spectral_advanced_toggle, Qt.LeftButton)
            qtbot.waitUntil(page.raw_spectral_advanced_values.isVisible)
        QApplication.processEvents()
        for control in controls:
            assert section.isAncestorOf(control)
            assert_unclipped(control)
        for widget in section.findChildren(QWidget):
            if widget.isVisibleTo(host) and isinstance(
                widget, (QLabel, QLineEdit, QComboBox, QAbstractButton)
            ):
                assert_unclipped(widget)

        footer = page.findChild(QWidget, "settings_experimental_footer")
        assert footer is not None
        buttons = {button.text(): button for button in footer.findChildren(QPushButton)}
        assert set(buttons) == {"Change Projects Root...", "Save", "Cancel"}
        for button in buttons.values():
            assert_unclipped(button)
        root_bounds = QRect(
            buttons["Change Projects Root..."].mapTo(footer, QPoint(0, 0)),
            buttons["Change Projects Root..."].size(),
        )
        save_bounds = QRect(
            buttons["Save"].mapTo(footer, QPoint(0, 0)), buttons["Save"].size()
        )
        assert root_bounds.right() < save_bounds.left()
        assert root_bounds.top() <= save_bounds.center().y() <= root_bounds.bottom()


def test_invalid_experimental_threshold_reveals_its_section(
    experimental_settings_page, qtbot, monkeypatch
):
    page = experimental_settings_page
    page.experimental_tabs.setCurrentIndex(0)
    edit = page.summed_bca_threshold_edits["warning_summed_bca_uv"]
    edit.setText("not-a-number")
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    assert page._validated_experimental_qc_settings() is None

    assert warnings and warnings[0][0] == "Invalid Experimental Settings"
    assert "warning_summed_bca_uv" in warnings[0][1]
    assert page.experimental_tabs.currentWidget().isAncestorOf(edit)
    assert edit.isVisibleTo(page)
    qtbot.waitUntil(edit.hasFocus)
    assert edit.selectedText() == "not-a-number"


def test_harmonic_setting_change_after_processing_prompts_recalculation(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)

    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    monkeypatch.setattr(dlg, "_project_has_processed_outputs", lambda: True)
    started: list[bool] = []
    monkeypatch.setattr(
        dlg,
        "_start_full_fft_grid_review",
        lambda **_kwargs: started.append(True) or True,
    )
    questions: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda _parent, title, message, *_args, **_kwargs: (
            questions.append((title, message)) or QMessageBox.Yes
        ),
    )

    significant_only_index = dlg.harmonic_summation_method_combo.findData(
        "significant_only_exploratory"
    )
    dlg.harmonic_summation_method_combo.setCurrentIndex(significant_only_index)
    dlg._save()

    assert questions and questions[0][0] == "Recalculate Harmonics?"
    assert "already has processed data" in questions[0][1]
    assert started == [True]


def test_selection_derivative_signature_tracks_analysis_and_roi_inputs(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    monkeypatch.setattr(dlg, "_project_has_processed_outputs", lambda: True)
    validated = dlg._validated_preproc_payload()
    assert validated is not None
    assert dlg._harmonic_settings_changed_after_processing(validated) is False

    original_base = dlg.base_freq_edit.text()
    dlg.base_freq_edit.setText("5.88")
    assert dlg._harmonic_settings_changed_after_processing(validated) is False
    assert dlg._project_protocol_changed_after_processing() is True
    dlg.base_freq_edit.setText(original_base)
    assert dlg._project_protocol_changed_after_processing() is False

    assert not hasattr(dlg, "bca_limit_edit")

    roi_pairs = dlg.roi_editor.get_pairs()
    dlg.roi_editor.set_pairs([*roi_pairs, ("Audit ROI", ["OZ"])])
    assert dlg._harmonic_settings_changed_after_processing(validated) is True
    assert dlg._frequency_analysis_settings_changed_after_processing() is True
    assert dlg._project_protocol_changed_after_processing() is False


@pytest.mark.parametrize("rebuild_now", [True, False])
def test_saving_roi_removal_invalidates_qc_and_preserves_deletion(
    tmp_path, qtbot, monkeypatch, rebuild_now,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    retained = [("ROT", ["O2", "PO8"])]
    win.settings.set_roi_pairs([*retained, ("Test ROI", ["F8", "T8"])])
    win.settings.save()
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    dlg.roi_editor.set_pairs(retained)
    monkeypatch.setattr(dlg, "_project_has_processed_outputs", lambda: True)
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_kw: (
        QMessageBox.Yes if rebuild_now else QMessageBox.No
    ))
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a, **_kw: None)
    resumed = []
    monkeypatch.setattr(
        dlg, "_resume_frequency_domain_post_processing", lambda: resumed.append(True),
    )
    monkeypatch.setattr(dlg, "_start_full_fft_grid_review", lambda **_kw: pytest.fail(
        "ROI edits must rebuild frequency QC before harmonic selection"
    ))

    dlg._save()
    # A later canceled review must not restore an already committed ROI edit.
    dlg._restore_harmonic_settings_after_cancel()

    assert win.settings.get_roi_pairs() == retained
    assert SettingsManager(win.settings.ini_path).get_roi_pairs() == retained
    state = json.loads((project.project_root / "project.json").read_text(encoding="utf-8"))
    assert state["tools"]["frequency_domain_qc"]["downstream_outputs_stale"] is True
    assert resumed == ([True] if rebuild_now else [])


def test_explicit_harmonic_recalculation_persists_project_selection_inputs(
    tmp_path,
    qtbot,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    dlg.roi_editor.set_pairs([("Selection Audit", ["O1", "O2"])])
    assert dlg._save_analysis_inputs_for_harmonic_recalculation()

    assert project.frequency_protocol.presentation_rate_hz == 6
    assert win.settings.get_roi_pairs() == [("Selection Audit", ["O1", "O2"])]


def test_cancelled_grid_review_can_restore_staged_harmonic_settings(
    tmp_path,
    qtbot,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    original_protocol = project.frequency_protocol
    original_rois = win.settings.get_roi_pairs()
    original_condition_exclusions = {
        "P01": ["Condition A"],
    }
    dlg._manual_excluded_participant_conditions = dict(
        original_condition_exclusions
    )
    dlg._capture_harmonic_settings_rollback()

    profile_index = dlg.harmonic_summation_method_combo.findData(
        "significant_only_exploratory"
    )
    dlg.harmonic_summation_method_combo.setCurrentIndex(profile_index)
    dlg.base_freq_edit.setText("5.88")
    dlg.roi_editor.set_pairs([("Temporary", ["OZ"])])
    dlg._manual_excluded_participant_conditions = {
        "P02": ["Condition B"],
    }
    validated = dlg._validated_preproc_payload()
    assert validated is not None
    assert dlg._save_project_preprocessing_for_harmonic_recalculation(validated)
    assert dlg._save_analysis_inputs_for_harmonic_recalculation()

    dlg._restore_harmonic_settings_after_cancel()

    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["harmonic_selection_profile"] == "legacy_fpvs_toolbox"
    assert reloaded.frequency_protocol == original_protocol
    assert win.settings.get_roi_pairs() == original_rois
    assert dlg.roi_editor.get_pairs() == original_rois
    assert (
        dlg._manual_excluded_participant_conditions
        == original_condition_exclusions
    )


def test_harmonic_worker_failure_before_selection_restores_staged_settings(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)
    dlg._capture_harmonic_settings_rollback()

    profile_index = dlg.harmonic_summation_method_combo.findData(
        "significant_only_exploratory"
    )
    dlg.harmonic_summation_method_combo.setCurrentIndex(profile_index)
    validated = dlg._validated_preproc_payload()
    assert validated is not None
    assert dlg._save_project_preprocessing_for_harmonic_recalculation(validated)

    fake_thread = _FakeSettingsThread()
    fake_worker = _FakeSettingsWorker()
    monkeypatch.setattr(settings_panel, "QThread", lambda _owner: fake_thread)
    import Main_App.workers.harmonic_selection_worker as harmonic_worker_module

    monkeypatch.setattr(
        harmonic_worker_module,
        "ProcessingHarmonicSelectionWorker",
        lambda _project: fake_worker,
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)

    before_tools = json.loads(
        (project.project_root / "project.json").read_text(encoding="utf-8")
    ).get("tools")
    assert dlg._start_harmonic_recalculation() is True
    after_start_tools = json.loads(
        (project.project_root / "project.json").read_text(encoding="utf-8")
    ).get("tools")
    assert after_start_tools == before_tools
    assert win._settings_worker_navigation_locked is True

    fake_worker.finished.emit({"ok": False, "error": "selection failed"})
    fake_thread.finished.emit()

    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["harmonic_selection_profile"] == "legacy_fpvs_toolbox"
    assert win._settings_harmonic_recalc_thread is None
    assert win._settings_worker_navigation_locked is False


def test_embedded_settings_harmonic_save_uses_post_processing_activity_page(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    win.show()
    win.open_settings_window()
    page = win._settings_page
    assert page is not None
    monkeypatch.setattr(page, "_project_has_processed_outputs", lambda: True)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args, **_kwargs: None,
    )

    grid_thread = _FakeSettingsThread()
    harmonic_thread = _FakeSettingsThread()
    threads = iter((grid_thread, harmonic_thread))
    monkeypatch.setattr(settings_panel, "QThread", lambda _owner: next(threads))
    grid_worker = _FakeSettingsWorker()
    harmonic_worker = _FakeSettingsWorker()
    import Main_App.workers.full_fft_grid_qc_worker as grid_worker_module
    import Main_App.workers.harmonic_selection_worker as harmonic_worker_module

    monkeypatch.setattr(
        grid_worker_module,
        "FullFftGridQcWorker",
        lambda _project_root: grid_worker,
    )
    monkeypatch.setattr(
        harmonic_worker_module,
        "ProcessingHarmonicSelectionWorker",
        lambda _project: harmonic_worker,
    )

    profile_index = page.harmonic_summation_method_combo.findData(
        "significant_only_exploratory"
    )
    page.harmonic_summation_method_combo.setCurrentIndex(profile_index)
    page.debug_check.setChecked(True)
    page._save()

    assert win.workspace_stack.currentWidget() is win.processing_page
    assert not win.processing_spinner.isHidden()
    assert win.processing_files_card.isHidden()
    assert not win.processing_status_card.isHidden()
    assert win.processing_progress_heading_label.text() == "Post-Processing Progress"
    assert (win.progress_bar.minimum(), win.progress_bar.maximum()) == (0, 0)
    assert win.btn_start.text() == "Post-processing in progress"
    assert win.btn_start.isEnabled() is False
    assert win.busy is True
    assert win.sidebar.isEnabled() is True
    assert win.sidebar.property("processingLocked") is True

    audit = SimpleNamespace(
        review_candidates=(),
        has_unresolved_grid_conflict=False,
        is_compatible_with_exclusions=lambda _exclusions: True,
    )
    grid_worker.finished.emit(audit)
    harmonic_worker.phase_progress.emit(
        "stats_ready_export",
        3,
        5,
        "FPVS Toolbox is rebuilding analysis files.",
    )

    assert win.processing_title_label.text() == "Preparing Analysis Outputs"
    assert win.processing_message_label.text() == (
        "FPVS Toolbox is rebuilding analysis files."
    )
    assert win.processing_step_label.text() == "Post-processing phase 3 of 5"
    qtbot.waitUntil(lambda: win.progress_bar.value() == 60, timeout=1_000)

    harmonic_worker.finished.emit(
        {
            "ok": True,
            "workbook_path": "Quality Check/Harmonic_Selection_Summary.xlsx",
        }
    )
    harmonic_thread.finished.emit()

    # The harmonic worker can finish before the preceding grid thread releases.
    # Keep the shared activity and navigation lock until both workers are gone.
    assert win.workspace_stack.currentWidget() is win.processing_page
    assert win.sidebar.property("processingLocked") is True

    grid_thread.finished.emit()

    assert win.workspace_stack.currentWidget() is win.homeWidget
    assert win.processing_spinner.isHidden()
    assert win.sidebar.property("processingLocked") is False
    assert win.menuBar().isEnabled() is True
    assert win.btn_start.text() == "Start Processing"
    assert win.busy is False
    assert win.lbl_debug.isHidden()


def test_harmonic_thread_start_failure_releases_settings_worker_state(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)

    fake_thread = _FakeSettingsThread(start_error=RuntimeError("start failed"))
    fake_worker = _FakeSettingsWorker()
    monkeypatch.setattr(settings_panel, "QThread", lambda _owner: fake_thread)
    import Main_App.workers.harmonic_selection_worker as harmonic_worker_module

    monkeypatch.setattr(
        harmonic_worker_module,
        "ProcessingHarmonicSelectionWorker",
        lambda _project: fake_worker,
    )
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message, *_args, **_kwargs: warnings.append(
            (title, message)
        ),
    )

    assert dlg._start_harmonic_recalculation() is False
    assert win._settings_harmonic_recalc_thread is None
    assert win._settings_harmonic_recalc_worker is None
    assert win._settings_harmonic_recalc_bridge is None
    assert win._settings_worker_navigation_locked is False
    assert dlg.recalculate_harmonics_button.isEnabled() is True
    assert fake_worker.deleted is True
    assert fake_thread.deleted is True
    assert warnings and warnings[-1][0] == "Recalculation Unavailable"


def test_fft_grid_thread_start_failure_releases_settings_worker_state(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)

    fake_thread = _FakeSettingsThread(start_error=RuntimeError("start failed"))
    fake_worker = _FakeSettingsWorker()
    monkeypatch.setattr(settings_panel, "QThread", lambda _owner: fake_thread)
    import Main_App.workers.full_fft_grid_qc_worker as grid_worker_module

    monkeypatch.setattr(
        grid_worker_module,
        "FullFftGridQcWorker",
        lambda _project_root: fake_worker,
    )
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message, *_args, **_kwargs: warnings.append(
            (title, message)
        ),
    )

    assert dlg._start_full_fft_grid_review(recalculate_after=True) is False
    assert win._settings_full_fft_grid_qc_thread is None
    assert win._settings_full_fft_grid_qc_worker is None
    assert win._settings_full_fft_grid_qc_bridge is None
    assert win._settings_worker_navigation_locked is False
    assert dlg.recalculate_harmonics_button.isEnabled() is True
    assert fake_worker.deleted is True
    assert fake_thread.deleted is True
    assert warnings and warnings[-1][0] == "FFT Grid Check Unavailable"


def test_fft_grid_activity_presentation_failure_keeps_running_worker_owned(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)

    fake_thread = _FakeSettingsThread()
    fake_worker = _FakeSettingsWorker()
    monkeypatch.setattr(settings_panel, "QThread", lambda _owner: fake_thread)
    import Main_App.workers.full_fft_grid_qc_worker as grid_worker_module

    monkeypatch.setattr(
        grid_worker_module,
        "FullFftGridQcWorker",
        lambda _project_root: fake_worker,
    )
    monkeypatch.setattr(
        dlg,
        "_begin_settings_post_processing_activity",
        lambda: (_ for _ in ()).throw(RuntimeError("activity failed")),
    )
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args, **_kwargs: None)

    assert dlg._start_full_fft_grid_review(
        recalculate_after=True,
        accept_on_success=True,
    )
    assert fake_thread.isRunning() is True
    assert win._settings_full_fft_grid_qc_thread is fake_thread
    assert win._settings_full_fft_grid_qc_worker is fake_worker
    assert win._settings_worker_navigation_locked is True

    fake_worker.failed.emit("grid failed")
    fake_thread.finished.emit()

    assert win._settings_full_fft_grid_qc_thread is None
    assert win._settings_full_fft_grid_qc_worker is None
    assert win._settings_worker_navigation_locked is False


def test_changed_fft_exclusions_resume_when_grid_thread_finishes_inside_review(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    dlg = SettingsDialog(win.settings, win, project)
    qtbot.addWidget(dlg)

    fake_thread = _FakeSettingsThread()
    fake_worker = _FakeSettingsWorker()
    monkeypatch.setattr(settings_panel, "QThread", lambda _owner: fake_thread)
    import Main_App.workers.full_fft_grid_qc_worker as grid_worker_module

    monkeypatch.setattr(
        grid_worker_module,
        "FullFftGridQcWorker",
        lambda _project_root: fake_worker,
    )
    saved_exclusions = []
    monkeypatch.setattr(
        dlg,
        "_save_participant_condition_exclusions",
        lambda exclusions, **_kwargs: saved_exclusions.append(exclusions) or True,
    )
    resumed = []
    monkeypatch.setattr(
        dlg,
        "_resume_frequency_domain_post_processing",
        lambda: resumed.append(True),
    )

    class _NestedReviewDialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec(self):
            fake_thread.finished.emit()
            return QDialog.Accepted

        @staticmethod
        def excluded_participant_conditions():
            return {"P01": ["Condition A"]}

    monkeypatch.setattr(
        settings_panel,
        "ParticipantConditionExclusionsDialog",
        _NestedReviewDialog,
    )

    assert dlg._start_full_fft_grid_review(recalculate_after=True)
    audit = SimpleNamespace(
        review_candidates=(object(),),
        has_unresolved_grid_conflict=False,
        is_compatible_with_exclusions=lambda _exclusions: True,
    )
    fake_worker.finished.emit(audit)

    assert saved_exclusions == [{"P01": ["Condition A"]}]
    assert resumed == [True]
    assert win._settings_full_fft_grid_qc_thread is None


def test_embedded_settings_reject_is_blocked_while_harmonic_worker_runs(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(project)
    page = settings_panel.EmbeddedSettingsPage(win.settings, win, project)
    qtbot.addWidget(page)
    returned_home = []
    monkeypatch.setattr(page, "_return_to_home", lambda: returned_home.append(True))
    messages = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, message, *_args, **_kwargs: messages.append(
            (title, message)
        ),
    )
    thread = _FakeSettingsThread()
    thread.start()
    win._settings_harmonic_recalc_thread = thread

    page.reject()

    assert returned_home == []
    assert messages and messages[-1][0] == "Harmonic Recalculation In Progress"


def test_declined_harmonic_recalculation_marks_only_summed_bca_outputs_stale(
    tmp_path,
    qtbot,
    monkeypatch,
):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    project = _prep_project(tmp_path)
    manifest_path = project.project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.setdefault("tools", {}).setdefault("processing", {})[
        "full_fft_provenance"
    ] = {"status": "current", "token": "unchanged"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    QApplication.instance() or QApplication([])
    win = MainWindow()
    qtbot.addWidget(win)
    win.loadProject(Project.load(project.project_root))
    dlg = SettingsDialog(win.settings, win, win.currentProject)
    qtbot.addWidget(dlg)
    monkeypatch.setattr(dlg, "_project_has_processed_outputs", lambda: True)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.No,
    )
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, message, *_args, **_kwargs: warnings.append(
            (title, message)
        ),
    )

    profile_index = dlg.harmonic_summation_method_combo.findData(
        "significant_only_exploratory"
    )
    dlg.harmonic_summation_method_combo.setCurrentIndex(profile_index)
    dlg._save()

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = saved["tools"]["post_processing"]["artifact_freshness"][
        "artifacts"
    ]
    assert artifacts["harmonic_selection_summary"]["status"] == "stale"
    assert artifacts["stats_ready_summed_bca"]["status"] == "stale"
    assert artifacts["analysis_ready_full_audit"]["status"] == "stale"
    assert saved["tools"]["processing"]["full_fft_provenance"] == {
        "status": "current",
        "token": "unchanged",
    }
    assert warnings and warnings[-1][0] == "Summed-BCA Outputs Are Stale"


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
    dlg.manual_removed_electrodes_enabled_check.setChecked(True)
    dlg._edit_manual_removed_electrodes()

    assert dlg.manual_removed_electrodes_button.isEnabled() is True
    assert dlg._manual_removed_electrodes_by_pid == {
        "P01": ["FT7", "P9"],
        "P02": ["Oz"],
    }

    dlg._save()
    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["removed_electrode_detection_mode"] == "auto"
    assert reloaded.preprocessing["auto_detect_removed_electrodes"] is True
    assert reloaded.preprocessing[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is True
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


def test_recording_aware_manual_qc_dialogs_keep_missing_visit_as_coverage(qtbot):
    rows = (
        QcRecordingIdentity(
            participant_id="P01",
            group_id="control",
            group_label="No Birth Control",
            recording_id="P01__luteal",
            session_id="luteal",
            session_label="Luteal",
            visit_index=1,
        ),
        QcRecordingIdentity(
            participant_id="P01",
            group_id="control",
            group_label="No Birth Control",
            session_id="follicular",
            session_label="Follicular",
            visit_index=2,
            coverage_status="Missing / not registered",
        ),
    )
    removed_dialog = ManualRemovedElectrodesDialog(
        ["P01"],
        {"P01": ["Oz"]},
        recording_rows=rows,
    )
    qtbot.addWidget(removed_dialog)
    removed_dialog.table.item(1, 5).setCheckState(Qt.Checked)
    removed_dialog.table.item(1, 6).setText("P9")

    assert removed_dialog.table.item(2, 1).text() == "Missing / not registered"
    assert removed_dialog.manual_removed_electrodes() == {"P01": ["Oz"]}
    assert removed_dialog.manual_removed_electrodes_by_recording() == {
        "P01__luteal": ["P9"]
    }

    exclusion_dialog = ManualParticipantExclusionsDialog(
        ["P01"],
        [],
        recording_rows=rows,
    )
    qtbot.addWidget(exclusion_dialog)
    exclusion_dialog.table.item(1, 6).setCheckState(Qt.Checked)

    assert exclusion_dialog.excluded_participants() == []
    assert exclusion_dialog.excluded_recordings() == ["P01__luteal"]
    assert not (
        exclusion_dialog.table.item(2, 6).flags() & Qt.ItemIsEnabled
    )


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
    dlg.preproc_edits[8].setText("6")
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
    dlg.preproc_edits[8].setText("6")
    dlg._save()

    reloaded = Project.load(project.project_root)
    assert reloaded.preprocessing["max_parallel_workers_override"] == 6
