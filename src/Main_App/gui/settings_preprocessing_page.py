"""Preprocessing controls and initial values for Settings.

Builders populate the existing SettingsDialog and connect its workflow methods.
The dialog retains draft validation, persistence, and background-work ownership.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QComboBox,
    QTabWidget,
    QGridLayout,
    QCheckBox,
)
from Main_App.gui.components import SectionCard
from Main_App.gui.settings_feedback import refresh_preprocessing_feedback
from Main_App.projects.preprocessing_settings import (
    ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
    ELECTRODE_MONTAGE_BIOSEMI64,
    PREPROCESSING_DEFAULTS,
    SUPPORTED_ELECTRODE_MAPPING_PROFILES,
    SUPPORTED_ELECTRODE_MONTAGES,
    normalize_preprocessing_settings,
)


def build_preprocessing_page(self, tabs: QTabWidget) -> QWidget:
    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    self._add_settings_scope(
        layout,
        "Signal preparation for the current project."
        if self.project is not None else "Application preprocessing preferences. Open a project to edit its processing settings.",
    )

    self.group_preproc = SectionCard(
        "Preprocessing Parameters",
        tab,
        object_name="preprocessing_parameters_card",
        content_layout=QGridLayout(),
    )
    grid = self.group_preproc.content_layout
    for column, stretch in enumerate((2, 3, 2, 3)):
        grid.setColumnStretch(column, stretch)
    params = [
        "Low-pass filter (Hz):",
        "High-pass filter (Hz):",
        "Downsample rate (Hz):",
        "Kurtosis flag threshold (absolute score):",
        "Initial reference channel 1:",
        "Initial reference channel 2:",
        "Last channel index to keep:",
        "Bad-channel count warning:",
        "Maximum parallel workers (0 = automatic):",
    ]
    self.preproc_edits: list[QLineEdit] = []
    self.preproc_error_labels: list[QLabel] = []
    for i, label_text in enumerate(params):
        row, col = divmod(i, 2)
        lbl = QLabel(label_text, self.group_preproc)
        lbl.setWordWrap(True)
        edit = QLineEdit(self.group_preproc)
        if i == 8:
            edit.setToolTip(
                "An upper limit for EEG processing. Automatic uses available CPUs; "
                "live RAM and Windows commit headroom determine how many jobs run. "
                "A positive value can lower the limit."
            )
        edit.setAccessibleName(label_text.rstrip(":"))
        lbl.setBuddy(edit)
        self.preproc_edits.append(edit)
        field = QWidget(self.group_preproc)
        field_layout = QVBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(2)
        field_layout.addWidget(edit)
        error = QLabel(field)
        error.setObjectName(f"preproc_{i}_error")
        error.setWordWrap(True)
        error.setTextFormat(Qt.PlainText)
        error.hide()
        field_layout.addWidget(error)
        self.preproc_error_labels.append(error)
        grid.addWidget(lbl, row, col * 2)
        grid.addWidget(field, row, col * 2 + 1)

    pre_keys = [
        ("preprocessing", "low_pass", str(PREPROCESSING_DEFAULTS["low_pass"]), "low_pass"),
        ("preprocessing", "high_pass", str(PREPROCESSING_DEFAULTS["high_pass"]), "high_pass"),
        ("preprocessing", "downsample", str(PREPROCESSING_DEFAULTS["downsample"]), "downsample"),
        ("preprocessing", "reject_thresh", str(PREPROCESSING_DEFAULTS["rejection_z"]), "rejection_z"),
        ("preprocessing", "ref_chan1", str(PREPROCESSING_DEFAULTS["ref_chan1"]), "ref_chan1"),
        ("preprocessing", "ref_chan2", str(PREPROCESSING_DEFAULTS["ref_chan2"]), "ref_chan2"),
        ("preprocessing", "max_idx_keep", str(PREPROCESSING_DEFAULTS["max_chan_idx_keep"]), "max_chan_idx_keep"),
        ("preprocessing", "max_bad_chans", str(PREPROCESSING_DEFAULTS["max_bad_chans"]), "max_bad_chans"),
        (
            "preprocessing",
            "max_parallel_workers",
            str(PREPROCESSING_DEFAULTS["max_parallel_workers_override"]),
            "max_parallel_workers_override",
        ),
    ]
    project_pp = self._project_preprocessing() if self.project else None
    for edit, (sec, opt, fallback, canonical) in zip(self.preproc_edits, pre_keys):
        if project_pp is not None:
            value = project_pp.get(canonical)
            edit.setText("" if value is None else str(value))
        else:
            edit.setText(self.manager.get(sec, opt, fallback))

    if project_pp is not None:
        line_noise_settings = project_pp
    else:
        line_noise_raw = {
            "line_noise_filter_enabled": self.manager.get(
                "preprocessing",
                "line_noise_filter_enabled",
                str(PREPROCESSING_DEFAULTS["line_noise_filter_enabled"]),
            ),
            "line_noise_frequency_hz": self.manager.get(
                "preprocessing",
                "line_noise_frequency_hz",
                str(PREPROCESSING_DEFAULTS["line_noise_frequency_hz"]),
            ),
        }
        try:
            line_noise_settings = normalize_preprocessing_settings(line_noise_raw)
        except ValueError:
            line_noise_settings = normalize_preprocessing_settings({})

    line_noise_tooltip = (
        "Smart FFT Hann multi-notch with a 0.5 Hz width on each side of the "
        "mains frequency and its first two harmonics. Components already removed "
        "by the FIR low-pass are skipped."
    )
    line_noise_row = (len(params) + 1) // 2
    self.line_noise_filter_enabled_check = QCheckBox(
        "Remove mains line noise",
        self.group_preproc,
    )
    self.line_noise_filter_enabled_check.setObjectName(
        "settings_line_noise_filter_enabled"
    )
    self.line_noise_filter_enabled_check.setToolTip(line_noise_tooltip)
    self.line_noise_filter_enabled_check.setChecked(
        bool(line_noise_settings["line_noise_filter_enabled"])
    )
    grid.addWidget(self.line_noise_filter_enabled_check, line_noise_row, 0, 1, 2)

    line_noise_frequency_label = QLabel(
        "Mains frequency:",
        self.group_preproc,
    )
    line_noise_frequency_label.setToolTip(line_noise_tooltip)
    self.line_noise_frequency_combo = QComboBox(self.group_preproc)
    self.line_noise_frequency_combo.setObjectName(
        "settings_line_noise_frequency_hz"
    )
    self.line_noise_frequency_combo.setToolTip(line_noise_tooltip)
    self.line_noise_frequency_combo.addItem("60 Hz", 60)
    self.line_noise_frequency_combo.addItem("50 Hz", 50)
    line_noise_frequency_index = self.line_noise_frequency_combo.findData(
        int(line_noise_settings["line_noise_frequency_hz"])
    )
    self.line_noise_frequency_combo.setCurrentIndex(
        max(0, line_noise_frequency_index)
    )
    self.line_noise_frequency_combo.setEnabled(
        self.line_noise_filter_enabled_check.isChecked()
    )
    self.line_noise_filter_enabled_check.toggled.connect(
        self.line_noise_frequency_combo.setEnabled
    )
    grid.addWidget(line_noise_frequency_label, line_noise_row, 2)
    grid.addWidget(self.line_noise_frequency_combo, line_noise_row, 3)

    montage_row = line_noise_row + 1
    montage_tooltip = (
        "FPVS Toolbox currently supports only the BioSemi ActiveTwo "
        "64-channel 10-20 cap. This project setting is reserved for "
        "validated future montage support."
    )
    montage_label = QLabel("Electrode montage:", self.group_preproc)
    montage_label.setToolTip(montage_tooltip)
    self.electrode_montage_combo = QComboBox(self.group_preproc)
    self.electrode_montage_combo.setObjectName(
        "settings_electrode_montage"
    )
    self.electrode_montage_combo.setToolTip(montage_tooltip)
    for montage_id, montage_name in SUPPORTED_ELECTRODE_MONTAGES:
        self.electrode_montage_combo.addItem(montage_name, montage_id)
    montage_index = self.electrode_montage_combo.findData(
        str(
            (project_pp or PREPROCESSING_DEFAULTS).get(
                "electrode_montage",
                ELECTRODE_MONTAGE_BIOSEMI64,
            )
        )
    )
    self.electrode_montage_combo.setCurrentIndex(max(0, montage_index))
    self.electrode_montage_combo.setEnabled(False)
    grid.addWidget(montage_label, montage_row, 0)
    grid.addWidget(self.electrode_montage_combo, montage_row, 1)

    mapping_tooltip = (
        "Use anatomical labels when the BDF already names scalp electrodes. "
        "Choose the A/B profile only for the standard BioSemi 64-channel "
        "10-20 A1-A32/B1-B32 wiring. It does not support BioSemi ABC, "
        "equiradial, or custom cap layouts."
    )
    mapping_label = QLabel("Channel mapping profile:", self.group_preproc)
    mapping_label.setToolTip(mapping_tooltip)
    self.electrode_mapping_profile_combo = QComboBox(self.group_preproc)
    self.electrode_mapping_profile_combo.setSizeAdjustPolicy(
        QComboBox.AdjustToMinimumContentsLengthWithIcon
    )
    self.electrode_mapping_profile_combo.setMinimumContentsLength(24)
    self.electrode_mapping_profile_combo.setObjectName(
        "settings_electrode_mapping_profile"
    )
    self.electrode_mapping_profile_combo.setToolTip(mapping_tooltip)
    for profile_id, profile_name in SUPPORTED_ELECTRODE_MAPPING_PROFILES:
        self.electrode_mapping_profile_combo.addItem(profile_name, profile_id)
    mapping_index = self.electrode_mapping_profile_combo.findData(
        str(
            (project_pp or PREPROCESSING_DEFAULTS).get(
                "electrode_mapping_profile",
                ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
            )
        )
    )
    self.electrode_mapping_profile_combo.setCurrentIndex(max(0, mapping_index))
    self.electrode_mapping_profile_combo.setEnabled(self.project is not None)
    self._electrode_geometry_control_baseline = {
        "electrode_montage": self.electrode_montage_combo.currentData(),
        "electrode_mapping_profile": self.electrode_mapping_profile_combo.currentData(),
    }
    grid.addWidget(mapping_label, montage_row, 2)
    grid.addWidget(self.electrode_mapping_profile_combo, montage_row, 3)

    layout.addWidget(self.group_preproc)

    layout.addStretch(1)
    tabs.addTab(tab, "Preprocessing")
    canonical_keys = [
        "low_pass",
        "high_pass",
        "downsample",
        "rejection_z",
        "ref_chan1",
        "ref_chan2",
        "max_chan_idx_keep",
        "max_bad_chans",
        "max_parallel_workers_override",
    ]
    for edit, canonical in zip(self.preproc_edits, canonical_keys):
        edit.textChanged.connect(lambda _text: refresh_preprocessing_feedback(self))
        edit.editingFinished.connect(
            lambda canon=canonical, field=edit: self._on_preproc_edit_finished(canon, field)
        )

    return tab
