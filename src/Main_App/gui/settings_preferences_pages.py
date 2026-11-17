"""Application preferences and standard QC overview for Settings.

Builders populate the existing SettingsDialog and connect its workflow methods.
The dialog retains draft validation, persistence, and background-work ownership.
"""

from __future__ import annotations

from typing import Callable
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QTabWidget,
    QCheckBox,
    QComboBox,
    QFormLayout,
)
from Main_App.gui.components import (
    ActionRow,
    SubsectionHeaderLabel,
    make_action_button,
    make_form_layout,
)
from Main_App.gui.style_tokens import SECTION_GAP, SECTION_HEADER_CONTENT_GAP
from Main_App.settings.appearance import APPEARANCE_MODES
from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_participants,
    normalize_manual_excluded_recording_conditions,
    normalize_manual_excluded_recordings,
)


def build_application_page(
    self, tabs: QTabWidget, *, change_projects_root: Callable[[], None],
) -> None:
    tab = QWidget()
    tab.setObjectName("settings_application_tab")
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(0, SECTION_HEADER_CONTENT_GAP, 0, 0)
    layout.setSpacing(SECTION_GAP)

    preferences = make_form_layout()
    preferences.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    preferences.setHorizontalSpacing(2 * SECTION_GAP)
    preferences.setVerticalSpacing(SECTION_GAP)
    preferences.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)

    field_width = 128
    self.appearance_mode_combo = QComboBox(tab)
    self.appearance_mode_combo.setObjectName("settings_appearance_mode")
    self.appearance_mode_combo.setToolTip("Auto follows your operating system's appearance.")
    self.appearance_mode_combo.addItems(APPEARANCE_MODES)
    self._initial_appearance_mode = self.manager.get_appearance_mode()
    self.appearance_mode_combo.setCurrentText(self._initial_appearance_mode)
    self.appearance_mode_combo.setFixedWidth(field_width)
    preferences.addRow("Appearance", self.appearance_mode_combo)

    self.alpha_edit = QLineEdit(self.manager.get("analysis", "alpha", "0.05"), tab)
    self.alpha_edit.setFixedWidth(field_width)
    self.alpha_edit.setToolTip(
        "The significance threshold for Standard FPVS Screening. The default is 0.05."
    )
    preferences.addRow("Screening alpha", self.alpha_edit)

    self.debug_check = QCheckBox("Enable debug logging", tab)
    self.debug_check.setObjectName("settings_enable_debug")
    self.debug_check.setAccessibleName("Enable debug logging")
    self.debug_check.setChecked(self.manager.get("debug", "enabled", "False").lower() == "true")
    self.debug_check.setToolTip("Restart FPVS Toolbox after changing debug logging.")
    preferences.addRow("", self.debug_check)
    layout.addLayout(preferences)

    layout.addSpacing(SECTION_HEADER_CONTENT_GAP)
    layout.addWidget(SubsectionHeaderLabel("Projects and cache", tab))
    actions = ActionRow(tab, alignment=Qt.AlignLeft)
    actions.setObjectName("settings_application_maintenance_actions")
    self.btn_changeRoot = make_action_button("Change Projects Folder…", parent=actions)
    self.btn_changeRoot.setObjectName("settings_advanced_footer_change_root")
    self.btn_changeRoot.clicked.connect(change_projects_root)
    actions.add_button(self.btn_changeRoot)
    self._settings_footer_buttons.append(self.btn_changeRoot)

    self.clear_toolbox_cache_button = make_action_button(
        "Clear Toolbox Cache…", parent=actions,
    )
    self.clear_toolbox_cache_button.setObjectName("settings_clear_toolbox_cache")
    self.clear_toolbox_cache_button.clicked.connect(self._clear_toolbox_cache)
    actions.add_button(self.clear_toolbox_cache_button)
    layout.addWidget(actions, alignment=Qt.AlignLeft)
    layout.addStretch(1)
    tabs.addTab(tab, "Application")


def build_quality_control_page(self, tabs: QTabWidget) -> None:
    tab = QWidget()
    tab.setObjectName("settings_quality_control_tab")
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SECTION_GAP)
    if self.project is not None:
        qc_preproc = self._project_preprocessing()
        self._manual_excluded_participants = (
            normalize_manual_excluded_participants(
                qc_preproc.get("manual_excluded_participants", [])
            )
        )
        self._manual_excluded_recordings = (
            normalize_manual_excluded_recordings(
                qc_preproc.get("manual_excluded_recordings", [])
            )
        )
        self._manual_excluded_participant_conditions = (
            normalize_manual_excluded_participant_conditions(
                qc_preproc.get(
                    "manual_excluded_participant_conditions",
                    {},
                )
            )
        )
        self._manual_excluded_recording_conditions = (
            normalize_manual_excluded_recording_conditions(
                qc_preproc.get(
                    "manual_excluded_recording_conditions",
                    {},
                )
            )
        )
    else:
        self._add_settings_scope(layout, "Open a project to manage dataset exclusions.")
        self._manual_excluded_participants = (
            normalize_manual_excluded_participants(
                self.manager.get(
                    "preprocessing",
                    "manual_excluded_participants",
                    "[]",
                )
            )
        )
        self._manual_excluded_recordings = []
        self._manual_excluded_participant_conditions = {}
        self._manual_excluded_recording_conditions = {}

    self.dataset_exclusions_button = make_action_button(
        "Manage Dataset Exclusions…",
        parent=tab,
    )
    self.dataset_exclusions_button.setObjectName(
        "settings_dataset_exclusions_manage"
    )
    self.dataset_exclusions_button.setToolTip(
        "Manage exclusions from processing and exclusions from analysis in one list."
    )
    self.dataset_exclusions_button.setEnabled(self.project is not None)
    self.dataset_exclusions_button.clicked.connect(
        self._manage_dataset_exclusions
    )
    layout.addWidget(self.dataset_exclusions_button, alignment=Qt.AlignLeft)

    layout.addStretch(1)
    tabs.addTab(tab, "Quality Control")
