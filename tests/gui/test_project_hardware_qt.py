"""CI-only hardware selection, cancellation and persisted project settings."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QWidget

from Main_App.gui import hardware_selection
from Main_App.gui.settings_panel import SettingsDialog
from Main_App.projects.hardware import confirm_hardware_selection, hardware_evidence
from Main_App.projects.project import Project
from Main_App.settings.settings_manager import SettingsManager
from tests.gui.test_gui_preproc_dialog import _assert_settings_widget_unclipped, _prep_project


def test_detected_hardware_cancel_preserves_project(tmp_path, monkeypatch):
    project = Project.load(tmp_path)
    project.save()
    original = (tmp_path / "project.json").read_bytes()
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.Cancel)
    assert not hardware_selection.ensure_project_hardware_ready(
        SimpleNamespace(currentProject=project), [tmp_path / "P01.vhdr"],
    )
    assert (tmp_path / "project.json").read_bytes() == original
    assert "hardware_platform" not in project.preprocessing


def test_detected_hardware_confirmation_persists_and_does_not_repeat(tmp_path, monkeypatch):
    project = Project.load(tmp_path)
    project.save()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]) or QMessageBox.Yes)
    host = SimpleNamespace(currentProject=project)
    assert hardware_selection.ensure_project_hardware_ready(host, [tmp_path / "P01.vhdr"])
    assert "break Toolbox functionality" in warnings[0]
    host.currentProject = Project.load(tmp_path)
    assert hardware_selection.ensure_project_hardware_ready(host, [tmp_path / "P01.vhdr"])
    assert len(warnings) == 1
    assert host.currentProject.preprocessing["hardware_platform"] == "brain_products"


def test_hardware_save_failure_restores_memory_and_disk(tmp_path, monkeypatch):
    project = Project.load(tmp_path)
    project.save()
    before = dict(project.preprocessing)
    original = (tmp_path / "project.json").read_bytes()
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.Yes)
    monkeypatch.setattr(project, "save", lambda: (_ for _ in ()).throw(PermissionError("read only")))
    assert not hardware_selection.ensure_project_hardware_ready(SimpleNamespace(currentProject=project), ["p.vhdr"])
    assert project.preprocessing == before
    assert (tmp_path / "project.json").read_bytes() == original


def test_new_project_hardware_dialog_cancellation_returns_no_draft(monkeypatch):
    monkeypatch.setattr(hardware_selection.QInputDialog, "getItem", lambda *_: ("Brain Products", False))
    settings = {"existing": "kept"}
    assert hardware_selection.choose_new_project_hardware(None, settings) is None
    assert settings == {"existing": "kept"}


def test_brain_products_settings_controls_save_reference_and_roles(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    project = _prep_project(tmp_path)
    project.update_preprocessing(confirm_hardware_selection(project.preprocessing, "brain_products", confirmed_change=True))
    project.save()
    widget = SettingsDialog(SettingsManager(str(tmp_path / "settings.ini")), project=project)
    qtbot.addWidget(widget)
    assert widget.hardware_platform_combo.currentData() == "brain_products"
    assert widget.electrode_montage_combo.isEnabled()
    assert not widget.kurtosis_screening_enabled_check.isEnabled()
    assert not widget.raw_signal_screening_enabled_check.isEnabled()
    assert not widget.interpolation_burden_review_enabled_check.isEnabled()
    assert widget.preproc_edits[6].text() == ""
    widget.initial_reference_combo.setCurrentIndex(widget.initial_reference_combo.findData("channels"))
    widget.preproc_edits[4].setText("TP9, TP10")
    widget.channel_types_edit.setText("VEOG=eog, ECG=ecg")
    values = widget._validated_preproc_payload()
    assert values["initial_reference_channels"] == ["TP9", "TP10"]
    assert values["channel_types"] == {"VEOG": "eog", "ECG": "ecg"}
    assert widget.save_pending_changes()
    reopened = Project.load(project.project_root)
    assert reopened.preprocessing["channel_types"] == {"VEOG": "eog", "ECG": "ecg"}
    assert reopened.preprocessing["initial_reference"] == "channels"


def test_recorded_reference_mode_clears_hidden_selected_channel_policy(qtbot, tmp_path, monkeypatch):
    from Main_App.processing.acquisition_policy import brain_products_policy

    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    project = _prep_project(tmp_path)
    settings = confirm_hardware_selection(project.preprocessing, "brain_products", confirmed_change=True)
    settings.update(initial_reference="channels", initial_reference_channels=["TP9", "TP10"], drop_reference_channels=True)
    project.update_preprocessing(settings)
    project.save()
    widget = SettingsDialog(SettingsManager(str(tmp_path / "settings.ini")), project=project)
    qtbot.addWidget(widget)
    widget.initial_reference_combo.setCurrentIndex(widget.initial_reference_combo.findData("recorded"))
    draft = widget._validated_preproc_payload()
    assert draft["initial_reference_channels"] == []
    assert draft["drop_reference_channels"] is False
    assert brain_products_policy(draft)["initial_reference"] == "recorded"
    assert widget.save_pending_changes()
    reopened = Project.load(project.project_root)
    assert reopened.preprocessing["initial_reference_channels"] == []
    assert reopened.preprocessing["drop_reference_channels"] is False


def test_settings_hardware_change_cancel_restores_selection(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    project = _prep_project(tmp_path)
    widget = SettingsDialog(SettingsManager(str(tmp_path / "settings.ini")), project=project)
    qtbot.addWidget(widget)
    original = dict(project.preprocessing)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.Cancel)
    index = widget.hardware_platform_combo.findData("brain_products")
    widget.hardware_platform_combo.setCurrentIndex(index)
    widget.hardware_platform_combo.activated.emit(index)
    assert widget.hardware_platform_combo.currentData() == "biosemi"
    assert project.preprocessing == original
    assert not widget.has_unsaved_changes()


def test_spatial_action_shows_one_capability_message_without_blocking_stats(monkeypatch):
    from Main_App.gui.tool_workflows import spatial_tool_available

    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    project = SimpleNamespace(preprocessing={"hardware_platform": "brain_products", "hardware_confirmed": True})
    assert not spatial_tool_available(None, project, "LORETA Visualizer")
    assert len(messages) == 1 and "BioSemi64" in messages[0]
    assert spatial_tool_available(None, project, "Standard FPVS Screening")
    assert len(messages) == 1


def test_settings_can_confirm_displayed_hardware_evidence_without_resetting_policy(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    project = _prep_project(tmp_path)
    settings = confirm_hardware_selection(project.preprocessing, "brain_products", confirmed_change=True)
    evidence = hardware_evidence("brain_products", source="verified_import_adapter")
    settings.update(
        hardware_confirmed=evidence.confirmed, hardware_selection_source=evidence.source,
        initial_reference="channels", initial_reference_channels=["TP9", "TP10"],
        drop_reference_channels=True, channel_types={"VEOG": "eog"}, electrode_montage="standard_1020",
    )
    project.update_preprocessing(settings)
    project.save()
    widget = SettingsDialog(SettingsManager(str(tmp_path / "settings.ini")), project=project)
    qtbot.addWidget(widget)
    assert not widget.has_unsaved_changes()
    widget.hardware_platform_combo.activated.emit(widget.hardware_platform_combo.currentIndex())
    assert widget.has_unsaved_changes()
    assert project.preprocessing["hardware_confirmed"] is False
    assert widget.save_pending_changes()
    reopened = Project.load(project.project_root)
    assert reopened.preprocessing["hardware_confirmed"] is True
    assert reopened.preprocessing["hardware_selection_source"] == "user_confirmed"
    for key in ("initial_reference", "initial_reference_channels", "drop_reference_channels", "channel_types", "electrode_montage"):
        assert reopened.preprocessing[key] == settings[key]


def test_concurrent_hardware_change_does_not_escape_live_field_validation(qtbot, tmp_path, monkeypatch):
    from Main_App.gui.settings_feedback import refresh_preprocessing_feedback

    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    project = _prep_project(tmp_path)
    widget = SettingsDialog(SettingsManager(str(tmp_path / "settings.ini")), project=project)
    qtbot.addWidget(widget)
    project.update_preprocessing(confirm_hardware_selection(project.preprocessing, "brain_products", confirmed_change=True))
    project.save()
    original = (project.project_root / "project.json").read_bytes()
    refresh_preprocessing_feedback(widget)
    assert widget._validated_preproc_payload() is None
    assert "changed in another window" in widget.settings_validation_status.text()
    assert (project.project_root / "project.json").read_bytes() == original


def test_brain_products_reference_and_channel_controls_fit_1280_by_900_workspace(qtbot, tmp_path, monkeypatch):
    from Main_App.gui.main_window import MainWindow

    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "config"))
    project = _prep_project(tmp_path)
    settings = confirm_hardware_selection(project.preprocessing, "brain_products", confirmed_change=True)
    settings.update(initial_reference="channels", initial_reference_channels=["TP9", "TP10"], channel_types={"VEOG": "eog"})
    project.update_preprocessing(settings)
    project.save()
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1280, 900)
    window.loadProject(project)
    window.show()
    qtbot.waitExposed(window)
    window.open_settings_window()
    page = window._settings_page
    page.tabs.setCurrentIndex(page._preproc_tab_index)
    qtbot.wait(1)
    assert (window.width(), window.height()) == (1280, 900)
    preproc_page = page.tabs.currentWidget()
    assert not preproc_page.findChildren(QScrollArea)
    for control in (
        page.hardware_platform_combo, page.initial_reference_combo, page.preproc_edits[4],
        page.channel_types_edit, page.drop_reference_channels_check,
    ):
        _assert_settings_widget_unclipped(control, window)
    for control in preproc_page.findChildren(QWidget):
        if control.isVisibleTo(window) and isinstance(control, (QLabel, QLineEdit, QComboBox, QAbstractButton)):
            _assert_settings_widget_unclipped(control, window)
    footer = page.findChild(QWidget, "settings_footer")
    assert footer is not None
    for button in footer.findChildren(QPushButton):
        _assert_settings_widget_unclipped(button, window)
