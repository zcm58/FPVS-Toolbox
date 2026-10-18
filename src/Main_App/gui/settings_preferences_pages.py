"""Application preferences and standard QC overview for Settings.

Builders populate the existing SettingsDialog and connect its workflow methods.
The dialog retains draft validation, persistence, and background-work ownership.
"""

from __future__ import annotations

from typing import Callable
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QTabWidget,
    QCheckBox,
)
from Main_App.gui.components import (
    SectionCard,
    SubsectionHeaderLabel,
    make_action_button,
    make_form_layout,
)
from Main_App.processing.frequency_domain_qc import thresholds_summary_lines
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
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    self._add_settings_scope(layout, "Application preferences apply across projects.")

    advanced_group = SectionCard(
        "Application Options",
        tab,
        object_name="settings_advanced_application_card",
    )
    advanced_form = make_form_layout()

    debug_default = self.manager.get("debug", "enabled", "False").lower() == "true"
    self.debug_check = QCheckBox("Enable debug logging", advanced_group)
    self.debug_check.setObjectName("settings_enable_debug")
    self.debug_check.setChecked(debug_default)
    self.debug_check.setToolTip("Enabling debug logging requires closing and reopening FPVS Toolbox.")
    advanced_form.addRow(QLabel("Diagnostics", advanced_group), self.debug_check)

    self.btn_changeRoot = make_action_button("Change Projects Root...", parent=advanced_group)
    self.btn_changeRoot.setObjectName("settings_advanced_footer_change_root")
    self.btn_changeRoot.clicked.connect(change_projects_root)
    advanced_form.addRow(QLabel("Project storage", advanced_group), self.btn_changeRoot)
    self._settings_footer_buttons.append(self.btn_changeRoot)

    self.clear_toolbox_cache_button = make_action_button(
        "Clear Toolbox Cache…", compact=True, parent=advanced_group,
    )
    self.clear_toolbox_cache_button.setObjectName("settings_clear_toolbox_cache")
    self.clear_toolbox_cache_button.clicked.connect(self._clear_toolbox_cache)
    advanced_form.addRow(QLabel("Temporary files", advanced_group), self.clear_toolbox_cache_button)
    cache_note = QLabel(
        "Keep recordings and results. The next calculations may take longer.",
        advanced_group,
    )
    cache_note.setWordWrap(True)
    advanced_form.addRow(cache_note)

    advanced_group.content_layout.addLayout(advanced_form)
    layout.addWidget(advanced_group)

    analysis_group = SectionCard(
        "Analysis Defaults", tab, object_name="settings_stats_analysis_card",
    )
    analysis_form = make_form_layout()
    self.alpha_edit = QLineEdit(self.manager.get("analysis", "alpha", "0.05"))
    alpha_label = QLabel("ANOVA alpha value:", analysis_group)
    alpha_label.setBuddy(self.alpha_edit)
    analysis_form.addRow(alpha_label, self.alpha_edit)
    analysis_group.content_layout.addLayout(analysis_form)
    layout.addWidget(analysis_group)
    layout.addStretch(1)
    tabs.addTab(tab, "Application")


def build_quality_control_page(self, tabs: QTabWidget) -> None:
    tab = QWidget()
    tab.setObjectName("settings_quality_control_tab")
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    self._add_settings_scope(
        layout,
        "Manage exclusions for the current project and inspect the standard QC thresholds."
        if self.project is not None else "Open a project to manage dataset exclusions.",
    )

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

    qc_group = SectionCard(
        "Processing QC",
        tab,
        object_name="settings_advanced_processing_qc_card",
    )
    qc_form = make_form_layout()
    self.dataset_exclusions_button = make_action_button(
        "Manage Dataset Exclusions…",
        compact=True,
        parent=qc_group,
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
    qc_form.addRow(
        QLabel(
            "Dataset exclusions",
            qc_group,
        ),
        self.dataset_exclusions_button,
    )
    qc_group.content_layout.addLayout(qc_form)

    self._add_frequency_domain_qc_settings(qc_group)
    layout.addWidget(qc_group)

    layout.addStretch(1)
    tabs.addTab(tab, "Quality Control")


def add_frequency_domain_qc_settings(self, parent: QWidget) -> None:
    header = SubsectionHeaderLabel("Frequency-domain QC thresholds (read-only)", parent)
    parent.content_layout.addWidget(header)

    self.frequency_domain_qc_thresholds_label = QLabel(
        "\n".join(thresholds_summary_lines()),
        parent,
    )
    self.frequency_domain_qc_thresholds_label.setObjectName(
        "settings_frequency_domain_qc_thresholds"
    )
    self.frequency_domain_qc_thresholds_label.setWordWrap(True)
    parent.content_layout.addWidget(self.frequency_domain_qc_thresholds_label)
