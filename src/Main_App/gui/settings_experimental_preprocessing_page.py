"""Signal, removed-electrode and raw-spectral Settings controls.

Populate the existing Experimental preprocessing tabs in their original order.
The dialog owns saved settings, validation and review workflow callbacks.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QHBoxLayout,
    QComboBox,
    QGridLayout,
    QCheckBox,
    QMessageBox,
    QToolButton,
)
from Main_App.gui.components import (
    SectionCard,
    StatusBanner,
    make_action_button,
    make_form_layout,
)
from Main_App.gui.components import make_info_button
from Main_App.projects import RAW_SPECTRAL_SCREENING_BRIEF_TEXT
from Main_App.projects.preprocessing_settings import (
    MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
    REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED,
)
from Main_App.processing.removed_electrode_detection import (
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
    REMOVED_ELECTRODE_DETECTION_MODE_OFF,
    normalize_manual_removed_electrodes_map,
    normalize_removed_electrode_detection_mode,
)


def build_signal_review(
    self, signals_page, signals_layout, qc_preproc, experimental_settings,
) -> None:
    interpolation_card = SectionCard(
        "Experimental Signal Review",
        signals_page,
        object_name="settings_experimental_interpolation_card",
    )
    self._add_settings_scope(
        interpolation_card.content_layout,
        "Current project only. Review defaults do not change previously accepted repairs."
        if self.project is not None else "Open a project to edit experimental QC settings.",
    )
    self.raw_signal_screening_enabled_check = QCheckBox(
        "Review large signals and brief disturbances", interpolation_card,
    )
    self.raw_signal_screening_enabled_check.setObjectName("settings_raw_signal_screening_enabled")
    self.raw_signal_screening_enabled_check.setChecked(experimental_settings.raw_signal_screening_enabled)
    self._add_experimental_info_row(
        interpolation_card.content_layout, interpolation_card,
        self.raw_signal_screening_enabled_check, "Raw signal review",
        "Checks the analyzed parts of each recording for unusually large signals "
        "and brief disturbances. Findings are suggestions for review. Removed-electrode "
        "detection and raw-spectral review can run separately.",
        "settings_raw_signal_screening_info",
    )
    self.kurtosis_screening_enabled_check = QCheckBox(
        "Screen electrodes with kurtosis", interpolation_card,
    )
    self.kurtosis_screening_enabled_check.setObjectName("settings_kurtosis_screening_enabled")
    self.kurtosis_screening_enabled_check.setChecked(experimental_settings.kurtosis_screening_enabled)
    self._add_experimental_info_row(
        interpolation_card.content_layout, interpolation_card,
        self.kurtosis_screening_enabled_check, "Kurtosis screening and repairs",
        "Looks for electrodes with unusually uneven signals after filtering. "
        '"Auto interpolate all" repairs every valid flag. The review default '
        "preselects repairs only above a score magnitude of 10; you must still "
        "apply decisions. Turning screening off stops both options. Saved manual "
        "electrode lists work separately.",
        "settings_kurtosis_screening_info",
    )
    self.kurtosis_auto_interpolate_all_check = QCheckBox(
        "Auto interpolate all kurtosis flags", interpolation_card,
    )
    self.kurtosis_auto_interpolate_all_check.setObjectName(
        "settings_kurtosis_auto_interpolate_all"
    )
    self.kurtosis_auto_interpolate_all_check.setChecked(
        bool(qc_preproc.get("kurtosis_auto_interpolate_all", False))
    )
    self.kurtosis_auto_interpolate_all_check.setToolTip(
        "On: automatically interpolate every valid kurtosis flag above the "
        "configured absolute normalized-score threshold. Off: use the kurtosis "
        "review dialog. Invalid statistics still need review."
    )
    interpolation_card.content_layout.addWidget(self.kurtosis_auto_interpolate_all_check)

    self.kurtosis_review_auto_interpolate_extreme_check = QCheckBox(
        "Preselect extreme-score repairs in review",
        interpolation_card,
    )
    self.kurtosis_review_auto_interpolate_extreme_check.setObjectName(
        "settings_kurtosis_review_auto_interpolate_extreme"
    )
    self.kurtosis_review_auto_interpolate_extreme_check.setChecked(
        experimental_settings.kurtosis_review_auto_interpolate_extreme
    )
    self.kurtosis_review_auto_interpolate_extreme_check.setToolTip(
        "Sets the initial choice for new kurtosis review decisions. You can override "
        "it in review and must still apply decisions. Exactly 10 remains manual. "
        "Auto interpolate all kurtosis flags takes precedence when enabled."
    )
    interpolation_card.content_layout.addWidget(
        self.kurtosis_review_auto_interpolate_extreme_check
    )

    signals_layout.addWidget(interpolation_card)
    signals_layout.addStretch(1)


def build_removed_electrode_review(
    self, electrodes_page, electrodes_layout, qc_preproc,
) -> None:
    removed_detection_mode = normalize_removed_electrode_detection_mode(
        qc_preproc.get("removed_electrode_detection_mode"),
        auto_detect_removed_electrodes=qc_preproc.get(
            "auto_detect_removed_electrodes",
            False,
        ),
    )
    self._initial_removed_electrode_detection_mode = removed_detection_mode
    self._removed_electrode_choice_unresolved = (
        self.project is not None
        and qc_preproc.get("removed_electrode_detection_choice_status")
        == REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
    )
    self._manual_removed_electrodes_by_pid = (
        normalize_manual_removed_electrodes_map(
            qc_preproc.get("manual_removed_electrodes", {})
        )
    )
    self._manual_removed_electrodes_by_recording = (
        normalize_manual_removed_electrodes_map(
            qc_preproc.get("manual_removed_electrodes_by_recording", {})
        )
    )

    recording_aware_qc = bool(
        self.project is not None
        and (getattr(self.project, "sessions", {}) or {})
    )
    detector_card = SectionCard(
        "Experimental Removed-Electrode Detection",
        electrodes_page,
        object_name="settings_experimental_removed_electrode_card",
    )
    detector_text = QLabel(
        "Automatic detection was developed with one lab's BioSemi ActiveTwo "
        "64 recordings. Treat its output as suggestions for review. Manual "
        "removed-electrode lists are controlled separately.",
        detector_card,
    )
    detector_text.setObjectName(
        "settings_experimental_removed_electrode_explanation"
    )
    detector_text.setWordWrap(True)
    detector_card.content_layout.addWidget(detector_text)

    detector_form = make_form_layout()
    self.removed_electrode_detection_mode_combo = QComboBox(detector_card)
    self.removed_electrode_detection_mode_combo.setObjectName(
        "settings_removed_electrode_detection_mode"
    )
    if self._removed_electrode_choice_unresolved:
        self.removed_electrode_detection_mode_combo.addItem(
            "Choose before processing (Off recommended)",
            None,
        )
    self.removed_electrode_detection_mode_combo.addItem(
        "Off (recommended)",
        REMOVED_ELECTRODE_DETECTION_MODE_OFF,
    )
    self.removed_electrode_detection_mode_combo.addItem(
        "On",
        REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
    )
    if self._removed_electrode_choice_unresolved:
        self.removed_electrode_detection_mode_combo.setCurrentIndex(0)
    else:
        mode_index = self.removed_electrode_detection_mode_combo.findData(
            removed_detection_mode
        )
        self.removed_electrode_detection_mode_combo.setCurrentIndex(
            max(0, mode_index)
        )
    self.removed_electrode_detection_mode_combo.setToolTip(
        "Enable or disable the project-wide experimental automatic detector. "
        "Its findings require review and are separate from manual lists."
    )

    self.removed_electrode_detection_info_button = make_info_button(
        parent=detector_card,
        object_name="settings_removed_electrode_detection_info",
        tooltip="About experimental removed-electrode detection",
        size=16,
    )
    self.removed_electrode_detection_info_button.clicked.connect(
        self._show_removed_electrode_detection_info
    )

    detector_choice_row = QWidget(detector_card)
    detector_choice_row.setObjectName(
        "settings_removed_electrode_detection_row"
    )
    detector_choice_layout = QHBoxLayout(detector_choice_row)
    detector_choice_layout.setContentsMargins(0, 0, 0, 0)
    detector_choice_layout.setSpacing(8)
    detector_choice_layout.addWidget(
        self.removed_electrode_detection_mode_combo,
        1,
    )
    detector_choice_layout.addWidget(
        self.removed_electrode_detection_info_button
    )
    detector_form.addRow(
        QLabel("Automatic detection:", detector_card),
        detector_choice_row,
    )

    self.manual_removed_electrodes_enabled_check = QCheckBox(
        "Apply saved manual lists during processing",
        detector_card,
    )
    self.manual_removed_electrodes_enabled_check.setObjectName(
        "settings_manual_removed_electrodes_enabled"
    )
    self.manual_removed_electrodes_enabled_check.setChecked(
        bool(
            qc_preproc.get(
                MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
                False,
            )
        )
    )
    self.manual_removed_electrodes_enabled_check.setToolTip(
        "This choice is independent of automatic detection. Stored lists "
        "remain available when application is Off."
    )
    self.manual_removed_electrodes_button = make_action_button(
        "Edit Lists",
        compact=True,
        parent=detector_card,
    )
    self.manual_removed_electrodes_button.setObjectName(
        "settings_manual_removed_electrodes_edit"
    )
    self.manual_removed_electrodes_button.setToolTip(
        "Edit participant-wide fallbacks and recording-specific removed electrodes"
        if recording_aware_qc
        else "Edit participant-level manually removed electrodes"
    )
    self.manual_removed_electrodes_button.clicked.connect(
        self._edit_manual_removed_electrodes
    )
    manual_row = QWidget(detector_card)
    manual_layout = QHBoxLayout(manual_row)
    manual_layout.setContentsMargins(0, 0, 0, 0)
    manual_layout.setSpacing(8)
    manual_layout.addWidget(
        self.manual_removed_electrodes_enabled_check,
        1,
    )
    manual_layout.addWidget(self.manual_removed_electrodes_button)
    manual_info = make_info_button(
        parent=manual_row, object_name="settings_manual_removed_electrodes_info",
        tooltip="About saved manual electrode lists", size=16,
    )
    manual_info.clicked.connect(lambda: QMessageBox.information(
        self, "Saved manual electrode lists",
        "Applies electrodes you have marked for repair. Lists are independent "
        "of automatic detection and remain saved when this option is off.",
    ))
    manual_layout.addWidget(manual_info)
    detector_form.addRow(
        QLabel("Manual removed electrodes:", detector_card),
        manual_row,
    )
    detector_card.content_layout.addLayout(detector_form)

    self.removed_electrode_detection_status = StatusBanner(
        "",
        detector_card,
        variant="warning",
    )
    self.removed_electrode_detection_status.setObjectName(
        "settings_removed_electrode_detection_status"
    )
    detector_card.content_layout.addWidget(
        self.removed_electrode_detection_status
    )

    # Compatibility for callers that still read the former hidden checkbox.
    self.auto_detect_removed_electrodes_check = QCheckBox(detector_card)
    self.auto_detect_removed_electrodes_check.setObjectName(
        "settings_auto_detect_removed_electrodes"
    )
    self.auto_detect_removed_electrodes_check.setChecked(
        removed_detection_mode == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        and not self._removed_electrode_choice_unresolved
    )
    self.auto_detect_removed_electrodes_check.hide()
    self.auto_detect_removed_electrodes_check.toggled.connect(
        self._set_removed_electrode_detection_enabled
    )
    self.removed_electrode_detection_mode_combo.currentIndexChanged.connect(
        self._on_removed_electrode_detection_mode_changed
    )
    self._sync_removed_electrode_detection_checkbox()
    self._refresh_removed_electrode_detection_status()
    electrodes_layout.addWidget(detector_card)
    electrodes_layout.addStretch(1)


def build_raw_spectral_review(
    self, raw_spectral_page, raw_spectral_layout, experimental_settings,
) -> None:
    raw_spectral = experimental_settings.raw_spectral_screening
    raw_spectral_card = SectionCard(
        "Experimental Raw-Spectral Review",
        raw_spectral_page,
        object_name="settings_experimental_raw_spectral_card",
    )
    self.raw_spectral_explanation_label = QLabel(
        RAW_SPECTRAL_SCREENING_BRIEF_TEXT,
        raw_spectral_card,
    )
    self.raw_spectral_explanation_label.setObjectName(
        "settings_experimental_raw_spectral_explanation"
    )
    self.raw_spectral_explanation_label.setWordWrap(True)
    raw_spectral_card.content_layout.addWidget(
        self.raw_spectral_explanation_label
    )
    self.raw_spectral_screening_enabled_check = QCheckBox(
        "Enable experimental raw-spectral review",
        raw_spectral_card,
    )
    self.raw_spectral_screening_enabled_check.setObjectName(
        "settings_raw_spectral_screening_enabled"
    )
    self.raw_spectral_screening_enabled_check.setChecked(raw_spectral.enabled)
    self.raw_spectral_screening_enabled_check.setToolTip(
        "Peaks are compared with nearby FFT bins and labeled as expected FPVS, "
        "associated with the configured line-noise filter, or unexpected. "
        "Turning this off records the check as not performed."
    )
    self._add_experimental_info_row(
        raw_spectral_card.content_layout, raw_spectral_card,
        self.raw_spectral_screening_enabled_check, "Raw-spectral review",
        "Looks for unusually strong narrow-frequency signals before preprocessing. "
        "Expected stimulus responses and mains noise are identified separately. "
        "Findings need review and do not remove data automatically.",
        "settings_raw_spectral_screening_info",
    )

    self.raw_spectral_advanced_toggle = QToolButton(raw_spectral_card)
    self.raw_spectral_advanced_toggle.setObjectName(
        "settings_raw_spectral_advanced_toggle"
    )
    self.raw_spectral_advanced_toggle.setText("Advanced")
    self.raw_spectral_advanced_toggle.setCheckable(True)
    self.raw_spectral_advanced_toggle.setChecked(False)
    self.raw_spectral_advanced_toggle.setToolTip(
        "Show the locked provisional values used by this project."
    )
    raw_spectral_card.content_layout.addWidget(
        self.raw_spectral_advanced_toggle,
        0,
        Qt.AlignLeft,
    )

    self.raw_spectral_advanced_values = QWidget(raw_spectral_card)
    self.raw_spectral_advanced_values.setObjectName(
        "settings_raw_spectral_advanced_values"
    )
    raw_spectral_grid = QGridLayout(self.raw_spectral_advanced_values)
    raw_spectral_grid.setContentsMargins(0, 0, 0, 0)
    raw_spectral_grid.setHorizontalSpacing(16)
    raw_spectral_grid.setVerticalSpacing(8)
    raw_spectral_grid.setColumnStretch(1, 1)
    raw_spectral_specs = (
        ("Lower screen boundary", f"{raw_spectral.minimum_frequency_hz:g} Hz"),
        (
            "Legacy Hann-spectrum score",
            f"{raw_spectral.minimum_legacy_hann_spectrum_score:g}",
        ),
        ("Local mean ratio", f"{raw_spectral.minimum_local_mean_ratio:g}"),
        (
            "Local standardized score",
            f"{raw_spectral.minimum_local_standardized_score:g}",
        ),
        (
            "Widespread label",
            f"{raw_spectral.widespread_channel_fraction:.0%} and at least "
            f"{raw_spectral.widespread_min_channels} scalp channels",
        ),
        (
            "Noise neighborhood",
            f"+/-{raw_spectral.noise_window_bins} bins; "
            f"{raw_spectral.noise_candidate_bins} candidates; "
            f"{raw_spectral.noise_retained_bins} retained",
        ),
        (
            "Notch match",
            f"distance < {raw_spectral.notch_half_width_hz:g} Hz",
        ),
        ("Threshold policy", raw_spectral.policy_version),
    )
    self.raw_spectral_advanced_value_labels: dict[str, QLabel] = {}
    for row, (name, value) in enumerate(raw_spectral_specs):
        name_label = QLabel(f"{name}:", self.raw_spectral_advanced_values)
        value_label = QLabel(str(value), self.raw_spectral_advanced_values)
        value_label.setWordWrap(True)
        key = name.casefold().replace(" ", "_")
        value_label.setObjectName(f"settings_raw_spectral_{key}_value")
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.raw_spectral_advanced_value_labels[key] = value_label
        raw_spectral_grid.addWidget(name_label, row, 0)
        raw_spectral_grid.addWidget(value_label, row, 1)
    self.raw_spectral_advanced_values.setVisible(False)
    self.raw_spectral_advanced_toggle.toggled.connect(
        self.raw_spectral_advanced_values.setVisible
    )
    raw_spectral_card.content_layout.addWidget(
        self.raw_spectral_advanced_values
    )
    raw_spectral_layout.addWidget(raw_spectral_card)
    raw_spectral_layout.addStretch(1)
