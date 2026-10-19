"""Compact project acquisition controls for the existing Preprocessing page."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit

from Main_App.gui.hardware_selection import confirm_hardware_change
from Main_App.projects.hardware import (
    HARDWARE_LABELS, HARDWARE_SETTINGS_KEYS, confirm_hardware_selection,
    normalize_hardware_settings, resolve_hardware,
)


def build_hardware_controls(dialog, grid, row: int, settings: dict) -> None:
    dialog._hardware_draft = dict(settings)
    dialog._hardware_control_baseline = normalize_hardware_settings(settings)
    choice = resolve_hardware(settings)
    dialog.hardware_platform_combo = QComboBox(dialog.group_preproc)
    dialog.hardware_platform_combo.setObjectName("settings_hardware_platform")
    for key, label in HARDWARE_LABELS.items():
        dialog.hardware_platform_combo.addItem(label, key)
    dialog.hardware_platform_combo.setCurrentIndex(dialog.hardware_platform_combo.findData(choice.platform))
    dialog.hardware_platform_combo.setEnabled(dialog.project is not None)
    dialog.hardware_platform_combo.setToolTip("Saved for this project. Changing hardware requires confirmation and reprocessing.")
    grid.addWidget(QLabel("EEG hardware:", dialog.group_preproc), row, 0)
    grid.addWidget(dialog.hardware_platform_combo, row, 1)
    dialog.initial_reference_label = QLabel("Initial reference:", dialog.group_preproc)
    dialog.initial_reference_combo = QComboBox(dialog.group_preproc)
    dialog.initial_reference_combo.setObjectName("settings_initial_reference")
    dialog.initial_reference_combo.addItem("Keep recorded reference", "recorded")
    dialog.initial_reference_combo.addItem("Selected channels", "channels")
    dialog.initial_reference_combo.setCurrentIndex(max(0, dialog.initial_reference_combo.findData(settings.get("initial_reference", "recorded"))))
    grid.addWidget(dialog.initial_reference_label, row, 2)
    grid.addWidget(dialog.initial_reference_combo, row, 3)
    dialog.drop_reference_channels_check = QCheckBox("Drop selected reference channels", dialog.group_preproc)
    dialog.drop_reference_channels_check.setChecked(bool(settings.get("drop_reference_channels", False)))
    grid.addWidget(dialog.drop_reference_channels_check, row + 1, 2, 1, 2)
    dialog.channel_types_label = QLabel("Channel types:", dialog.group_preproc)
    dialog.channel_types_edit = QLineEdit(dialog.group_preproc)
    dialog.channel_types_edit.setObjectName("settings_channel_types")
    dialog.channel_types_edit.setPlaceholderText("VEOG=eog, ECG=ecg")
    dialog.channel_types_edit.setToolTip("Optional overrides using exact recorded channel names. Leave blank to keep reader channel types. Supported: eeg, eog, ecg, emg, misc.")
    dialog.channel_types_edit.setText(", ".join(f"{name}={role}" for name, role in settings.get("channel_types", {}).items()))
    grid.addWidget(dialog.channel_types_label, row + 1, 0)
    grid.addWidget(dialog.channel_types_edit, row + 1, 1)
    dialog.hardware_platform_combo.activated.connect(lambda _index: _choose_hardware(dialog))
    dialog.initial_reference_combo.currentIndexChanged.connect(lambda _index: _refresh_controls(dialog))
    if choice.platform == "brain_products":
        dialog.preproc_edits[4].setText(", ".join(settings.get("initial_reference_channels", [])))
    _refresh_controls(dialog)


def _choose_hardware(dialog) -> None:
    old = resolve_hardware(dialog._hardware_draft)
    selected = dialog.hardware_platform_combo.currentData()
    if old.confirmed and not confirm_hardware_change(dialog, old.platform, selected):
        dialog.hardware_platform_combo.setCurrentIndex(dialog.hardware_platform_combo.findData(old.platform))
        return
    if old.platform == selected:
        if not old.confirmed:
            dialog._hardware_draft = confirm_hardware_selection(dialog._hardware_draft, selected)
            dialog._draft_tracker.changed()
        return
    dialog._hardware_draft = confirm_hardware_selection(dialog._hardware_draft, selected, confirmed_change=True)
    draft = dialog._hardware_draft
    dialog.electrode_montage_combo.setCurrentIndex(dialog.electrode_montage_combo.findData(draft["electrode_montage"]))
    dialog.electrode_mapping_profile_combo.setCurrentIndex(dialog.electrode_mapping_profile_combo.findData(draft["electrode_mapping_profile"]))
    dialog.preproc_edits[4].setText(draft["ref_chan1"])
    dialog.preproc_edits[5].setText(draft["ref_chan2"])
    dialog.preproc_edits[6].setText("" if draft["max_chan_idx_keep"] is None else str(draft["max_chan_idx_keep"]))
    dialog.initial_reference_combo.setCurrentIndex(0)
    dialog.drop_reference_channels_check.setChecked(False)
    dialog.channel_types_edit.clear()
    _refresh_controls(dialog)


def _refresh_controls(dialog) -> None:
    brain_products = dialog.hardware_platform_combo.currentData() == "brain_products"
    selected_reference = dialog.initial_reference_combo.currentData() == "channels"
    dialog.initial_reference_label.setVisible(brain_products)
    dialog.initial_reference_combo.setVisible(brain_products)
    dialog.drop_reference_channels_check.setVisible(brain_products and selected_reference)
    dialog.channel_types_label.setVisible(brain_products)
    dialog.channel_types_edit.setVisible(brain_products)
    for index in (4, 5):
        visible = not brain_products or (index == 4 and selected_reference)
        dialog._preproc_field_containers[index].setVisible(visible)
        dialog._preproc_field_labels[index].setVisible(visible)
    dialog._preproc_field_labels[4].setText("Reference channels (comma-separated):" if brain_products else "Initial reference channel 1:")
    dialog.preproc_edits[6].setPlaceholderText("All channels" if brain_products else "")
    dialog.electrode_montage_combo.setEnabled(brain_products and dialog.project is not None)
    dialog.electrode_mapping_profile_combo.setEnabled(not brain_products and dialog.project is not None)
    dialog.preproc_edits[3].setEnabled(not brain_products)
    dialog.preproc_edits[3].setToolTip("BioSemi64 kurtosis screening is unavailable for other montages." if brain_products else "")
    refresh_hardware_qc_controls(dialog)


def collect_hardware_controls(dialog) -> dict:
    draft = getattr(dialog, "_hardware_draft", {})
    if hasattr(dialog, "_hardware_control_baseline") and dialog.project is not None:
        current = normalize_hardware_settings(dialog.project.preprocessing)
        if current != dialog._hardware_control_baseline:
            raise ValueError("Project EEG hardware settings changed in another window. Reopen Settings before saving.")
    result = {key: draft[key] for key in HARDWARE_SETTINGS_KEYS if key in draft}
    if resolve_hardware(draft).platform == "brain_products":
        selected_reference = dialog.initial_reference_combo.currentData() == "channels"
        result.update(
            initial_reference=dialog.initial_reference_combo.currentData(),
            initial_reference_channels=dialog.preproc_edits[4].text() if selected_reference else [],
            drop_reference_channels=selected_reference and dialog.drop_reference_channels_check.isChecked(),
            kurtosis_screening_enabled=False,
            channel_types=dialog.channel_types_edit.text(),
            auto_detect_removed_electrodes=False, removed_electrode_detection_mode="off",
            kurtosis_auto_interpolate_all=False, ref_chan1="", ref_chan2="",
        )
    return result


def refresh_hardware_qc_controls(dialog) -> None:
    brain_products = dialog.hardware_platform_combo.currentData() == "brain_products"
    for name in (
        "raw_signal_screening_enabled_check", "kurtosis_screening_enabled_check",
        "interpolation_burden_review_enabled_check",
        "condition_specific_interpolation_enabled_check", "kurtosis_auto_interpolate_all_check",
        "kurtosis_review_auto_interpolate_extreme_check",
    ):
        control = getattr(dialog, name, None)
        if control is not None:
            if brain_products:
                control.setChecked(False)
            enabled = not brain_products and dialog.project is not None
            if name in {"kurtosis_auto_interpolate_all_check", "kurtosis_review_auto_interpolate_extreme_check"}:
                enabled = enabled and dialog.kurtosis_screening_enabled_check.isChecked()
            if name == "condition_specific_interpolation_enabled_check":
                enabled = enabled and dialog.summed_bca_screening_enabled_check.isChecked()
            control.setEnabled(enabled)
            if brain_products:
                control.setToolTip("This review/repair policy is qualified for BioSemi64 only.")
    detector = getattr(dialog, "removed_electrode_detection_mode_combo", None)
    if detector is not None:
        if brain_products:
            detector.setCurrentIndex(detector.findData("off"))
        detector.setEnabled(not brain_products and dialog.project is not None)
