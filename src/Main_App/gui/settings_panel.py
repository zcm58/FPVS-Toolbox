from __future__ import annotations

import json
from typing import Any, Dict
from pathlib import Path

import config
import psutil

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QHBoxLayout,
    QComboBox,
    QDialog,
    QTabWidget,
    QGridLayout,
    QCheckBox,
    QMessageBox,
    QSizePolicy,
    QToolButton,
)

from Main_App.Shared.settings_manager import SettingsManager
from Main_App.Shared.roi_presets import (
    default_roi_name_keys,
    default_roi_presets,
    supported_roi_montages,
    validate_roi_montage,
)
from Main_App.workers.mp_env import get_ram_tier_recommendation
from Main_App.gui.components import (
    ActionRow,
    SectionCard,
    StatusBanner,
    SubsectionHeaderLabel,
    make_action_button,
    make_form_layout,
)
from Main_App.gui.icons import sidebar_icon
from Main_App.gui.manual_participant_exclusions_dialog import (
    ManualParticipantExclusionsDialog,
)
from Main_App.gui.manual_removed_electrodes_dialog import ManualRemovedElectrodesDialog
from Main_App.gui.participant_condition_exclusions_dialog import (
    ParticipantConditionExclusionsDialog,
)
from Main_App.gui.roi_settings_editor import ROISettingsEditor
from Main_App.processing.processing_controller import prepare_batch_file_infos
from Main_App.processing.processing_ledger import load_ledger
from Main_App.processing.frequency_domain_qc import (
    active_frequency_domain_exclusions,
    clear_manual_frequency_domain_participant_exclusions,
    mark_frequency_domain_outputs_stale,
    thresholds_summary_lines,
)
from Main_App.projects import DatasetIndexError, load_project_dataset_index
from Main_App.projects.projects_root import changeProjectsRoot
from Main_App.projects.project import Project
from Main_App.projects.preprocessing_settings import (
    PREPROCESSING_DEFAULTS,
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_participants,
    normalize_preprocessing_settings,
)
from Main_App.processing.removed_electrode_detection import (
    REMOVED_ELECTRODE_DETECTION_INFO_TEXT,
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
    REMOVED_ELECTRODE_DETECTION_MODE_MANUAL,
    REMOVED_ELECTRODE_DETECTION_MODE_OFF,
    normalize_manual_removed_electrodes_map,
    normalize_removed_electrode_detection_mode,
)
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
    FIXED_PREDEFINED_POLICY_NAME,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
    GROUP_SIGNIFICANT_POLICY_NAME,
    GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY,
    GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
    normalize_dv_policy,
)
from Tools.Stats.analysis.dv_policy_group_significant import clear_group_significant_selection_cache
from Tools.Stats.data.group_harmonic_cache import clear_cached_group_harmonic_selections


class SettingsPanel(QWidget):
    """Simple settings editor using PySide6 widgets."""

    settings_saved = Signal()
    settings_canceled = Signal()

    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = make_form_layout()
        layout.addLayout(form)

        self.out_edit = QLineEdit()
        self.thr_edit = QLineEdit()
        form.addRow(QLabel("Output Folder"), self.out_edit)
        form.addRow(QLabel("Threshold"), self.thr_edit)

        self.ok_btn = make_action_button("OK", variant="primary")
        self.cancel_btn = make_action_button("Cancel", variant="tertiary")
        btn_row = ActionRow(self, alignment=Qt.AlignLeft)
        btn_row.setObjectName("settings_panel_actions")
        btn_row.add_button(self.ok_btn)
        btn_row.add_button(self.cancel_btn)
        layout.addWidget(btn_row)

        self.ok_btn.clicked.connect(self._on_ok)
        self.cancel_btn.clicked.connect(self._on_cancel)

    def _on_ok(self) -> None:
        values = {
            "output_folder": self.out_edit.text(),
            "threshold": self.thr_edit.text(),
        }
        if hasattr(self.controller, "save_settings"):
            self.controller.save_settings(values)
        self.settings_saved.emit()

    def _on_cancel(self) -> None:
        self.settings_canceled.emit()


class SettingsDialog(QDialog):
    """Dialog for editing application settings via :class:`SettingsManager`."""

    def __init__(
        self,
        manager: SettingsManager,
        parent: QWidget | None = None,
        project: Project | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = parent
        self.manager = manager
        self.project = project
        self._project_cache: Dict[str, Any] | None = None
        self._custom_roi_presets_by_montage: dict[str, list[tuple[str, list[str]]]] = {}
        self._settings_footer_buttons: list[QWidget] = []
        # Stub attributes for pruned settings to avoid AttributeError if referenced
        self.data_edit = None
        self.out_edit = None
        self.main_size_edit = None
        self.stats_size_edit = None
        self.resize_size_edit = None
        self.adv_size_edit = None
        self.cond_edit = None
        self.id_edit = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("Settings")
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        preproc_tab = self._init_preproc_tab(self.tabs)
        self._preproc_tab_index = self.tabs.indexOf(preproc_tab)
        self._init_stats_tab(self.tabs)
        self._init_rois_tab(self.tabs)
        self._init_advanced_tab(self.tabs)
        self._last_tab_index = self.tabs.currentIndex()
        self._tab_change_guard = False
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _add_settings_footer(self, tab: QWidget, layout: QVBoxLayout, object_name: str) -> None:
        footer = QWidget(tab)
        footer.setObjectName(object_name)
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)

        change_root = make_action_button("Change Projects Root...", parent=footer)
        change_root.setObjectName(f"{object_name}_change_root")
        change_root.clicked.connect(lambda: changeProjectsRoot(self))
        footer_layout.addWidget(change_root)
        if not hasattr(self, "btn_changeRoot"):
            self.btn_changeRoot = change_root

        actions = ActionRow(footer, alignment=Qt.AlignRight)
        actions.setObjectName(f"{object_name}_actions")
        save_btn = make_action_button("Save", variant="primary", parent=actions)
        cancel_btn = make_action_button("Cancel", variant="secondary", parent=actions)
        save_btn.clicked.connect(self._save)
        cancel_btn.clicked.connect(self.reject)
        actions.add_button(save_btn)
        actions.add_button(cancel_btn)
        footer_layout.addWidget(actions)
        self._settings_footer_buttons.extend(
            (change_root, save_btn, cancel_btn)
        )

        layout.addWidget(footer)

    # ------------------------------------------------------------------
    def _init_preproc_tab(self, tabs: QTabWidget) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.group_preproc = SectionCard(
            "Preprocessing Parameters",
            tab,
            object_name="preprocessing_parameters_card",
            content_layout=QGridLayout(),
        )
        grid = self.group_preproc.content_layout
        params = [
            "Low Pass (Hz):",
            "High Pass (Hz):",
            "Downsample (Hz):",
            "Epoch Start (s):",
            "Rejection Z-Thresh:",
            "Epoch End (s):",
            "Ref Chan 1:",
            "Ref Chan 2:",
            "Max Chan Idx Keep:",
            "Max Bad Chans (Flag):",
            "Max Parallel Workers Override (0=Auto):",
        ]
        self.preproc_edits: list[QLineEdit] = []
        for i, label_text in enumerate(params):
            row, col = divmod(i, 2)
            lbl = QLabel(label_text, self.group_preproc)
            edit = QLineEdit(self.group_preproc)
            self.preproc_edits.append(edit)
            grid.addWidget(lbl, row, col * 2)
            grid.addWidget(edit, row, col * 2 + 1)

        pre_keys = [
            ("preprocessing", "low_pass", str(PREPROCESSING_DEFAULTS["low_pass"]), "low_pass"),
            ("preprocessing", "high_pass", str(PREPROCESSING_DEFAULTS["high_pass"]), "high_pass"),
            ("preprocessing", "downsample", str(PREPROCESSING_DEFAULTS["downsample"]), "downsample"),
            ("preprocessing", "epoch_start", str(PREPROCESSING_DEFAULTS["epoch_start_s"]), "epoch_start_s"),
            ("preprocessing", "reject_thresh", str(PREPROCESSING_DEFAULTS["rejection_z"]), "rejection_z"),
            ("preprocessing", "epoch_end", str(PREPROCESSING_DEFAULTS["epoch_end_s"]), "epoch_end_s"),
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
            "Recording-site mains frequency:",
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

        layout.addWidget(self.group_preproc)
        self._add_harmonic_selection_section(tab, layout, project_pp)

        layout.addStretch(1)
        self._add_settings_footer(tab, layout, "settings_preproc_footer")
        tabs.addTab(tab, "Preprocessing")
        canonical_keys = [
            "low_pass",
            "high_pass",
            "downsample",
            "epoch_start_s",
            "rejection_z",
            "epoch_end_s",
            "ref_chan1",
            "ref_chan2",
            "max_chan_idx_keep",
            "max_bad_chans",
            "max_parallel_workers_override",
        ]
        for edit, canonical in zip(self.preproc_edits, canonical_keys):
            edit.editingFinished.connect(
                lambda canon=canonical, field=edit: self._on_preproc_edit_finished(canon, field)
            )

        return tab

    def _harmonic_policy_payload_from_preprocessing(
        self,
        preprocessing: Dict[str, Any] | None,
    ) -> dict[str, object]:
        preprocessing = preprocessing or {}
        return {
            "name": preprocessing.get(
                "harmonic_selection_policy",
                self.manager.get(
                    "preprocessing",
                    "harmonic_selection_policy",
                    GROUP_SIGNIFICANT_POLICY_NAME,
                ),
            ),
            "group_significant_electrode_scope": preprocessing.get(
                "group_significant_electrode_scope",
                self.manager.get(
                    "preprocessing",
                    "group_significant_electrode_scope",
                    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
                ),
            ),
            "group_significant_summation_method": preprocessing.get(
                "group_significant_summation_method",
                self.manager.get(
                    "preprocessing",
                    "group_significant_summation_method",
                    GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
                ),
            ),
            "fixed_harmonic_frequencies_hz": preprocessing.get(
                "fixed_harmonic_frequencies_hz",
                self.manager.get(
                    "preprocessing",
                    "fixed_harmonic_frequencies_hz",
                    FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
                ),
            ),
            "fixed_harmonic_auto_exclude_base": preprocessing.get(
                "fixed_harmonic_auto_exclude_base",
                self.manager.get(
                    "preprocessing",
                    "fixed_harmonic_auto_exclude_base",
                    "True",
                ),
            ),
        }

    def _add_harmonic_selection_section(
        self,
        tab: QWidget,
        layout: QVBoxLayout,
        project_pp: Dict[str, Any] | None,
    ) -> None:
        settings = normalize_dv_policy(self._harmonic_policy_payload_from_preprocessing(project_pp))
        self._initial_harmonic_settings_signature = (
            self._harmonic_settings_signature_from_settings(settings)
        )
        harmonic_group = SectionCard(
            "Harmonic Selection",
            tab,
            object_name="settings_harmonic_selection_card",
        )
        harmonic_form = make_form_layout()

        self.harmonic_summation_method_combo = QComboBox(harmonic_group)
        self.harmonic_summation_method_combo.setObjectName(
            "settings_harmonic_summation_method"
        )
        self.harmonic_summation_method_combo.addItem(
            "Up to highest significant (trim gaps >10)",
            GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
        )
        self.harmonic_summation_method_combo.addItem(
            "Significant harmonics only",
            GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY,
        )
        self.harmonic_summation_method_combo.addItem(
            "Fixed harmonic list",
            "fixed_predefined",
        )
        selected_method = (
            "fixed_predefined"
            if settings.name == FIXED_PREDEFINED_POLICY_NAME
            else settings.group_significant_summation_method
        )
        method_index = self.harmonic_summation_method_combo.findData(selected_method)
        self.harmonic_summation_method_combo.setCurrentIndex(max(0, method_index))
        self.harmonic_summation_method_combo.setToolTip(
            "Choose which oddball harmonics are included in Summed BCA after processing. "
            "The default fills through the highest significant harmonic, but excludes an "
            "isolated highest peak when more than 10 eligible non-base harmonics lie "
            "between the two highest significant peaks."
        )
        harmonic_form.addRow(
            QLabel("Summation method:", harmonic_group),
            self.harmonic_summation_method_combo,
        )

        self.harmonic_electrode_scope_combo = QComboBox(harmonic_group)
        self.harmonic_electrode_scope_combo.setObjectName(
            "settings_harmonic_electrode_scope"
        )
        self.harmonic_electrode_scope_combo.addItem(
            "Average within selected ROIs only",
            GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
        )
        self.harmonic_electrode_scope_combo.addItem(
            "Grand average across all scalp electrodes",
            GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL,
        )
        scope_index = self.harmonic_electrode_scope_combo.findData(
            settings.group_significant_electrode_scope
        )
        self.harmonic_electrode_scope_combo.setCurrentIndex(max(0, scope_index))
        self.harmonic_electrode_scope_combo.setToolTip(
            "Choose the electrode set used to build the group-level FFT spectrum for harmonic selection."
        )
        harmonic_form.addRow(
            QLabel("Averaging method:", harmonic_group),
            self.harmonic_electrode_scope_combo,
        )

        self.fixed_harmonic_freqs_edit = QLineEdit(
            str(settings.fixed_harmonic_frequencies_hz),
            harmonic_group,
        )
        self.fixed_harmonic_freqs_edit.setObjectName("settings_fixed_harmonics")
        self.fixed_harmonic_freqs_edit.setPlaceholderText("1.2, 2.4, 3.6, 4.8, 7.2")
        self.fixed_harmonic_freqs_edit.setToolTip(
            "Comma-separated harmonic frequencies in Hz. Used only when Fixed harmonic list is selected."
        )
        harmonic_form.addRow(
            QLabel("Fixed harmonics (Hz):", harmonic_group),
            self.fixed_harmonic_freqs_edit,
        )

        self.fixed_harmonic_exclude_base_check = QCheckBox(
            "Automatically exclude base-rate overlaps",
            harmonic_group,
        )
        self.fixed_harmonic_exclude_base_check.setObjectName(
            "settings_fixed_harmonics_exclude_base"
        )
        self.fixed_harmonic_exclude_base_check.setChecked(
            bool(settings.fixed_harmonic_auto_exclude_base)
        )
        harmonic_form.addRow("", self.fixed_harmonic_exclude_base_check)

        harmonic_group.content_layout.addLayout(harmonic_form)
        self.fixed_harmonic_warning = StatusBanner(
            "Fixed harmonics may not match the statistically significant harmonic "
            "list selected by FPVS Toolbox. Use this for exploratory or comparison "
            "checks; primary summaries use the shared significant-harmonic policy.",
            harmonic_group,
            variant="warning",
        )
        self.fixed_harmonic_warning.setObjectName("settings_fixed_harmonic_warning")
        self.fixed_harmonic_warning.setVisible(False)
        harmonic_group.content_layout.addWidget(self.fixed_harmonic_warning)
        harmonic_actions = ActionRow(harmonic_group, alignment=Qt.AlignLeft)
        harmonic_actions.setObjectName("settings_harmonic_selection_actions")
        self.recalculate_harmonics_button = make_action_button(
            "Recalculate Harmonics",
            compact=True,
            parent=harmonic_group,
        )
        self.recalculate_harmonics_button.setObjectName(
            "settings_recalculate_harmonics_button"
        )
        self.recalculate_harmonics_button.setToolTip(
            "Rebuild the project's statistically significant harmonic list from the processed Excel outputs."
        )
        self.recalculate_harmonics_button.setEnabled(self.project is not None)
        self.recalculate_harmonics_button.clicked.connect(
            self._on_recalculate_harmonics_clicked
        )
        self.review_condition_exclusions_button = make_action_button(
            "Review FFT Crop Exclusions",
            compact=True,
            parent=harmonic_group,
        )
        self.review_condition_exclusions_button.setObjectName(
            "settings_review_condition_exclusions_button"
        )
        self.review_condition_exclusions_button.setToolTip(
            "Check processed FullFFT grids and exclude selected participant-condition "
            "pairs from downstream analyses."
        )
        self.review_condition_exclusions_button.setEnabled(self.project is not None)
        self.review_condition_exclusions_button.clicked.connect(
            self._on_review_condition_exclusions_clicked
        )
        harmonic_actions.add_button(self.recalculate_harmonics_button)
        harmonic_actions.add_button(self.review_condition_exclusions_button)
        harmonic_group.content_layout.addWidget(harmonic_actions)

        self.harmonic_recalculation_status = StatusBanner("", harmonic_group, variant="info")
        self.harmonic_recalculation_status.setObjectName(
            "settings_harmonic_recalculation_status"
        )
        self.harmonic_recalculation_status.setVisible(False)
        harmonic_group.content_layout.addWidget(self.harmonic_recalculation_status)

        layout.addWidget(harmonic_group)
        self.harmonic_summation_method_combo.currentIndexChanged.connect(
            self._update_harmonic_selection_controls
        )
        self._update_harmonic_selection_controls()

    # ------------------------------------------------------------------
    def _init_stats_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        analysis_group = SectionCard(
            "Analysis Defaults",
            tab,
            object_name="settings_stats_analysis_card",
        )
        analysis_form = make_form_layout()

        self.base_freq_edit = QLineEdit(self.manager.get("analysis", "base_freq", "6.0"))
        analysis_form.addRow(QLabel("FPVS base frequency (Hz):"), self.base_freq_edit)

        self.oddball_freq_edit = QLineEdit(str(config.DEFAULT_ODDBALL_FREQ))
        self.oddball_freq_edit.setReadOnly(True)
        self.oddball_freq_edit.setToolTip(
            "Locked at 1.2 Hz. Use BCA harmonic upper limit to choose how high harmonics are calculated."
        )
        analysis_form.addRow(QLabel("Oddball frequency (Hz):"), self.oddball_freq_edit)

        self.bca_limit_edit = QLineEdit(self.manager.get("analysis", "bca_upper_limit", "16.8"))
        analysis_form.addRow(QLabel("BCA harmonic upper limit:"), self.bca_limit_edit)

        self.alpha_edit = QLineEdit(self.manager.get("analysis", "alpha", "0.05"))
        analysis_form.addRow(QLabel("ANOVA alpha value:"), self.alpha_edit)
        analysis_group.content_layout.addLayout(analysis_form)
        layout.addWidget(analysis_group)

        layout.addStretch(1)
        self._add_settings_footer(tab, layout, "settings_stats_footer")

        tabs.addTab(tab, "Stats")

    # ------------------------------------------------------------------
    def _init_rois_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        current_montage = self.manager.get_roi_montage()
        self._custom_roi_presets_by_montage[current_montage] = self.manager.get_custom_roi_presets(
            current_montage
        )
        quick_add_group = SectionCard(
            "Quick Add",
            tab,
            object_name="settings_rois_quick_add_card",
        )
        quick_add_form = make_form_layout()

        self.roi_montage_combo = QComboBox(quick_add_group)
        self.roi_montage_combo.setObjectName("settings_rois_montage_combo")
        for montage_key, label in supported_roi_montages():
            self.roi_montage_combo.addItem(label, montage_key)
        montage_index = self.roi_montage_combo.findData(current_montage)
        if montage_index >= 0:
            self.roi_montage_combo.setCurrentIndex(montage_index)
        quick_add_form.addRow(QLabel("Electrode montage:", quick_add_group), self.roi_montage_combo)

        self.roi_preset_combo = QComboBox(quick_add_group)
        self.roi_preset_combo.setObjectName("settings_rois_preset_combo")
        quick_add_form.addRow(QLabel("Quick-add ROI:", quick_add_group), self.roi_preset_combo)

        self.roi_preset_electrodes_edit = QLineEdit(quick_add_group)
        self.roi_preset_electrodes_edit.setObjectName("settings_rois_preset_electrodes")
        self.roi_preset_electrodes_edit.setReadOnly(True)
        quick_add_form.addRow(QLabel("Electrodes:", quick_add_group), self.roi_preset_electrodes_edit)
        quick_add_group.content_layout.addLayout(quick_add_form)

        quick_add_actions = ActionRow(quick_add_group, alignment=Qt.AlignLeft)
        quick_add_actions.setObjectName("settings_rois_quick_add_actions")
        add_preset_btn = make_action_button("Add ROI", compact=True, parent=quick_add_group)
        add_preset_btn.setObjectName("settings_rois_add_preset")
        add_preset_btn.clicked.connect(self._add_selected_roi_preset)
        save_presets_btn = make_action_button("Save Custom Presets", compact=True, parent=quick_add_group)
        save_presets_btn.setObjectName("settings_rois_save_custom_presets")
        save_presets_btn.clicked.connect(self._save_roi_editor_as_custom_presets)
        quick_add_actions.add_button(add_preset_btn)
        quick_add_actions.add_button(save_presets_btn)
        quick_add_group.content_layout.addWidget(quick_add_actions)

        self.roi_preset_status = StatusBanner("", quick_add_group, variant="info")
        self.roi_preset_status.setObjectName("settings_rois_preset_status")
        self.roi_preset_status.setVisible(False)
        quick_add_group.content_layout.addWidget(self.roi_preset_status)

        self.roi_montage_combo.currentIndexChanged.connect(self._on_roi_montage_changed)
        self.roi_preset_combo.currentIndexChanged.connect(self._update_roi_preset_preview)

        roi_group = SectionCard(
            "Regions of Interest",
            tab,
            object_name="settings_rois_card",
        )
        roi_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        roi_header = QWidget(roi_group)
        roi_header_layout = QHBoxLayout(roi_header)
        roi_header_layout.setContentsMargins(0, 0, 0, 0)
        roi_header_layout.setSpacing(8)
        roi_header_layout.addWidget(SubsectionHeaderLabel("ROI name", roi_header), 1)
        roi_header_layout.addWidget(SubsectionHeaderLabel("Electrodes", roi_header), 1)
        roi_header_layout.addSpacing(32)
        roi_group.content_layout.addWidget(roi_header)

        self.roi_editor = ROISettingsEditor(self, self.manager.get_roi_pairs())
        self.roi_editor.setObjectName("settings_rois_editor")
        self.roi_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.roi_editor.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        roi_group.content_layout.addWidget(self.roi_editor, 1)

        add_btn = make_action_button("+ Add ROI", compact=True, parent=roi_group)
        add_btn.setObjectName("settings_rois_add_roi")
        add_btn.clicked.connect(lambda: self.roi_editor.add_entry())
        roi_actions = ActionRow(roi_group, alignment=Qt.AlignLeft)
        roi_actions.setObjectName("settings_rois_actions")
        roi_actions.add_button(add_btn)
        roi_group.content_layout.addWidget(roi_actions)

        layout.addWidget(roi_group, 1)
        layout.addWidget(quick_add_group)
        self._add_settings_footer(tab, layout, "settings_rois_footer")
        self._refresh_roi_preset_combo()

        tabs.addTab(tab, "ROIs")

    # ------------------------------------------------------------------
    def _init_advanced_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        advanced_group = SectionCard(
            "Application Options",
            tab,
            object_name="settings_advanced_application_card",
        )
        advanced_form = make_form_layout()

        debug_default = self.manager.get("debug", "enabled", "False").lower() == "true"
        self.debug_check = QCheckBox("Enable Debug", advanced_group)
        self.debug_check.setObjectName("settings_enable_debug")
        self.debug_check.setChecked(debug_default)
        advanced_form.addRow(QLabel("Debug Mode", advanced_group), self.debug_check)

        self.beta_tools_check = QCheckBox("Enable Beta Tools", advanced_group)
        self.beta_tools_check.setObjectName("settings_enable_beta_tools")
        self.beta_tools_check.setChecked(self.manager.beta_tools_enabled())
        advanced_form.addRow(QLabel("Beta Tools", advanced_group), self.beta_tools_check)

        advanced_group.content_layout.addLayout(advanced_form)
        layout.addWidget(advanced_group)

        qc_group = SectionCard(
            "Processing QC",
            tab,
            object_name="settings_advanced_processing_qc_card",
        )
        qc_form = make_form_layout()
        if self.project is not None:
            qc_preproc = self._project_preprocessing()
            removed_detection_mode = normalize_removed_electrode_detection_mode(
                qc_preproc.get("removed_electrode_detection_mode"),
                auto_detect_removed_electrodes=qc_preproc.get(
                    "auto_detect_removed_electrodes",
                    PREPROCESSING_DEFAULTS["auto_detect_removed_electrodes"],
                ),
            )
            self._manual_removed_electrodes_by_pid = (
                normalize_manual_removed_electrodes_map(
                    qc_preproc.get("manual_removed_electrodes", {})
                )
            )
            self._manual_excluded_participants = normalize_manual_excluded_participants(
                qc_preproc.get("manual_excluded_participants", [])
            )
            self._manual_excluded_participant_conditions = (
                normalize_manual_excluded_participant_conditions(
                    qc_preproc.get(
                        "manual_excluded_participant_conditions",
                        {},
                    )
                )
            )
        else:
            auto_detect_default = (
                self.manager.get(
                    "preprocessing",
                    "auto_detect_removed_electrodes",
                    str(PREPROCESSING_DEFAULTS["auto_detect_removed_electrodes"]),
                ).lower()
                == "true"
            )
            removed_detection_mode = normalize_removed_electrode_detection_mode(
                self.manager.get(
                    "preprocessing",
                    "removed_electrode_detection_mode",
                    "",
                ),
                auto_detect_removed_electrodes=auto_detect_default,
            )
            self._manual_removed_electrodes_by_pid = (
                normalize_manual_removed_electrodes_map(
                    self.manager.get(
                        "preprocessing",
                        "manual_removed_electrodes",
                        "{}",
                    )
                )
            )
            self._manual_excluded_participants = normalize_manual_excluded_participants(
                self.manager.get(
                    "preprocessing",
                    "manual_excluded_participants",
                    "[]",
                )
            )
            self._manual_excluded_participant_conditions = {}
        self.removed_electrode_detection_mode_combo = QComboBox(qc_group)
        self.removed_electrode_detection_mode_combo.setObjectName(
            "settings_removed_electrode_detection_mode"
        )
        self.removed_electrode_detection_mode_combo.addItem(
            "Off",
            REMOVED_ELECTRODE_DETECTION_MODE_OFF,
        )
        self.removed_electrode_detection_mode_combo.addItem(
            "Conservative auto-detect",
            REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
        )
        self.removed_electrode_detection_mode_combo.addItem(
            "Manual list",
            REMOVED_ELECTRODE_DETECTION_MODE_MANUAL,
        )
        mode_index = self.removed_electrode_detection_mode_combo.findData(
            removed_detection_mode
        )
        self.removed_electrode_detection_mode_combo.setCurrentIndex(max(0, mode_index))
        self.removed_electrode_detection_mode_combo.setToolTip(
            "Choose whether raw-channel QC should mark high-confidence automatic "
            "candidates or use manual participant-level removed-electrode metadata."
        )

        self.removed_electrode_detection_info_button = QToolButton(qc_group)
        self.removed_electrode_detection_info_button.setObjectName(
            "settings_removed_electrode_detection_info"
        )
        self.removed_electrode_detection_info_button.setIcon(sidebar_icon("info", 16))
        self.removed_electrode_detection_info_button.setToolTip(
            "About conservative removed-electrode detection"
        )
        self.removed_electrode_detection_info_button.setCursor(Qt.PointingHandCursor)
        self.removed_electrode_detection_info_button.setProperty("compact", True)
        self.removed_electrode_detection_info_button.setProperty("iconButton", True)
        self.removed_electrode_detection_info_button.clicked.connect(
            self._show_removed_electrode_detection_info
        )
        self.manual_removed_electrodes_button = make_action_button(
            "Edit",
            compact=True,
            parent=qc_group,
        )
        self.manual_removed_electrodes_button.setObjectName(
            "settings_manual_removed_electrodes_edit"
        )
        self.manual_removed_electrodes_button.setToolTip(
            "Edit participant-level manually removed electrodes"
        )
        self.manual_removed_electrodes_button.clicked.connect(
            self._edit_manual_removed_electrodes
        )
        self.manual_participant_exclusions_button = make_action_button(
            "Edit",
            compact=True,
            parent=qc_group,
        )
        self.manual_participant_exclusions_button.setObjectName(
            "settings_manual_participant_exclusions_edit"
        )
        self.manual_participant_exclusions_button.setToolTip(
            "Edit participants that should be skipped during processing"
        )
        self.manual_participant_exclusions_button.clicked.connect(
            self._edit_manual_participant_exclusions
        )

        removed_detection_row = QWidget(qc_group)
        removed_detection_row.setObjectName("settings_removed_electrode_detection_row")
        removed_detection_layout = QHBoxLayout(removed_detection_row)
        removed_detection_layout.setContentsMargins(0, 0, 0, 0)
        removed_detection_layout.setSpacing(8)
        removed_detection_layout.addWidget(self.removed_electrode_detection_mode_combo, 1)
        removed_detection_layout.addWidget(self.manual_removed_electrodes_button)
        removed_detection_layout.addWidget(self.removed_electrode_detection_info_button)

        # Legacy compatibility for older helpers/tests that read the prior
        # checkbox attribute while the visible UI now uses a mode selector.
        self.auto_detect_removed_electrodes_check = QCheckBox(qc_group)
        self.auto_detect_removed_electrodes_check.setObjectName(
            "settings_auto_detect_removed_electrodes"
        )
        self.auto_detect_removed_electrodes_check.setChecked(
            removed_detection_mode == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        )
        self.auto_detect_removed_electrodes_check.hide()
        self.auto_detect_removed_electrodes_check.toggled.connect(
            self._set_removed_electrode_detection_enabled
        )
        self.removed_electrode_detection_mode_combo.currentIndexChanged.connect(
            self._on_removed_electrode_detection_mode_changed
        )
        self._sync_removed_electrode_detection_checkbox()
        self._update_manual_removed_electrodes_button()
        qc_form.addRow(
            QLabel("Removed-electrode QC mode", qc_group),
            removed_detection_row,
        )
        qc_form.addRow(
            QLabel("Manual participant exclusions", qc_group),
            self.manual_participant_exclusions_button,
        )
        qc_group.content_layout.addLayout(qc_form)

        self._add_frequency_domain_qc_settings(qc_group)
        layout.addWidget(qc_group)

        layout.addStretch(1)
        self._add_settings_footer(tab, layout, "settings_advanced_footer")

        tabs.addTab(tab, "Advanced")

    def _add_frequency_domain_qc_settings(self, parent: QWidget) -> None:
        header = SubsectionHeaderLabel("Frequency-domain QC", parent)
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

        self.frequency_domain_qc_exclusions_label = QLabel(parent)
        self.frequency_domain_qc_exclusions_label.setObjectName(
            "settings_frequency_domain_qc_exclusions"
        )
        self.frequency_domain_qc_exclusions_label.setWordWrap(True)

        self.clear_frequency_domain_manual_exclusions_button = make_action_button(
            "Clear Manual Frequency Exclusions",
            compact=True,
            parent=parent,
        )
        self.clear_frequency_domain_manual_exclusions_button.setObjectName(
            "settings_clear_frequency_domain_manual_exclusions"
        )
        self.clear_frequency_domain_manual_exclusions_button.clicked.connect(
            self._clear_frequency_domain_manual_exclusions
        )

        exclusion_row = QWidget(parent)
        exclusion_layout = QHBoxLayout(exclusion_row)
        exclusion_layout.setContentsMargins(0, 0, 0, 0)
        exclusion_layout.setSpacing(8)
        exclusion_layout.addWidget(self.frequency_domain_qc_exclusions_label, 1)
        exclusion_layout.addWidget(self.clear_frequency_domain_manual_exclusions_button)
        parent.content_layout.addWidget(exclusion_row)
        self._refresh_frequency_domain_qc_settings()

    def _refresh_frequency_domain_qc_settings(self) -> None:
        label = getattr(self, "frequency_domain_qc_exclusions_label", None)
        button = getattr(self, "clear_frequency_domain_manual_exclusions_button", None)
        if label is None or button is None:
            return
        if self.project is None:
            label.setText("Load a project to view active frequency-domain exclusions.")
            button.setEnabled(False)
            return
        exclusions = active_frequency_domain_exclusions(self.project.project_root)
        auto_participants = sorted(exclusions.auto_excluded_participants)
        manual_participants = sorted(exclusions.manual_excluded_participants)
        electrode_total = sum(
            len(electrodes)
            for electrodes in exclusions.auto_excluded_electrodes_by_participant.values()
        )
        parts = [
            "Automatic participants: "
            + (", ".join(auto_participants) if auto_participants else "none"),
            "Manual participants: "
            + (", ".join(manual_participants) if manual_participants else "none"),
            f"Automatic participant-electrode exclusions: {electrode_total}",
        ]
        if exclusions.downstream_outputs_stale:
            parts.append("Regeneration required before downstream frequency-domain tools can be used.")
        label.setText("\n".join(parts))
        button.setEnabled(bool(manual_participants))

    def _clear_frequency_domain_manual_exclusions(self) -> None:
        if self.project is None:
            return
        exclusions = active_frequency_domain_exclusions(self.project.project_root)
        manual_participants = sorted(exclusions.manual_excluded_participants)
        if not manual_participants:
            self._refresh_frequency_domain_qc_settings()
            return
        response = QMessageBox.question(
            self,
            "Clear Manual Frequency Exclusions?",
            (
                "Clearing manual frequency-domain exclusions requires regenerating "
                "final harmonics and downstream outputs before using frequency-domain tools."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if response != QMessageBox.Yes:
            return
        cleared = clear_manual_frequency_domain_participant_exclusions(
            self.project.project_root,
            manual_participants,
        )
        self._refresh_frequency_domain_qc_settings()
        if cleared:
            QMessageBox.information(
                self,
                "Regeneration Required",
                (
                    "Manual frequency-domain exclusions were cleared. Resume "
                    "post-processing before using downstream frequency-domain tools."
                ),
            )
            host = getattr(self, "host", None) or self.parent()
            if host is not None:
                try:
                    from Main_App.gui.processing_workflows import (
                        _set_resume_post_processing_pending,
                    )

                    _set_resume_post_processing_pending(host, True)
                except Exception:
                    pass

    def _removed_electrode_detection_enabled(self) -> bool:
        return (
            self._removed_electrode_detection_mode()
            == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        )

    def _harmonic_settings_signature_from_settings(self, settings: Any) -> tuple[object, ...]:
        if settings.name == FIXED_PREDEFINED_POLICY_NAME:
            return (
                settings.name,
                str(settings.fixed_harmonic_frequencies_hz).strip(),
                bool(settings.fixed_harmonic_auto_exclude_base),
            )
        return (
            settings.name,
            str(settings.group_significant_electrode_scope),
            str(settings.group_significant_summation_method),
        )

    def _harmonic_settings_signature_from_preprocessing(
        self,
        preprocessing: Dict[str, Any],
    ) -> tuple[object, ...]:
        settings = normalize_dv_policy(
            self._harmonic_policy_payload_from_preprocessing(preprocessing)
        )
        return self._harmonic_settings_signature_from_settings(settings)

    def _project_has_processed_outputs(self) -> bool:
        if self.project is None:
            return False
        project_root = Path(self.project.project_root)
        ledger = load_ledger(project_root)
        entries = ledger.get("entries")
        if isinstance(entries, dict):
            for entry in entries.values():
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("status") or "").casefold() == "completed":
                    return True
        try:
            dataset_index = load_project_dataset_index(project_root)
        except (DatasetIndexError, OSError):
            return False
        return any(
            record.path.name.casefold().endswith("_results.xlsx")
            for record in (
                *dataset_index.workbooks,
                *dataset_index.excluded_workbooks,
            )
        )

    def _harmonic_settings_changed_after_processing(
        self,
        validated_preproc: Dict[str, Any],
    ) -> bool:
        if self.project is None or not self._project_has_processed_outputs():
            return False
        initial = getattr(self, "_initial_harmonic_settings_signature", None)
        current = self._harmonic_settings_signature_from_preprocessing(validated_preproc)
        return initial is not None and current != initial

    def _ask_recalculate_harmonics_after_settings_change(self) -> bool:
        choice = QMessageBox.question(
            self,
            "Recalculate Harmonics?",
            (
                "This project already has processed data, and the harmonic selection "
                "settings were changed. Recalculate the statistically significant "
                "harmonic list now so downstream tools use the updated method?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        return choice == QMessageBox.Yes

    def _set_harmonic_recalculation_status(self, text: str, variant: str = "info") -> None:
        banner = getattr(self, "harmonic_recalculation_status", None)
        if banner is None:
            return
        banner.set_variant(variant)
        banner.set_text(text)
        banner.setVisible(bool(text))

    def _fixed_harmonic_list_selected(self) -> bool:
        return self.harmonic_summation_method_combo.currentData() == "fixed_predefined"

    def _update_harmonic_selection_controls(self) -> None:
        fixed_selected = self._fixed_harmonic_list_selected()
        self.harmonic_electrode_scope_combo.setEnabled(not fixed_selected)
        self.fixed_harmonic_freqs_edit.setEnabled(fixed_selected)
        self.fixed_harmonic_exclude_base_check.setEnabled(fixed_selected)
        self.fixed_harmonic_warning.setVisible(fixed_selected)

    def _save_project_preprocessing_for_harmonic_recalculation(
        self,
        validated_preproc: Dict[str, Any],
    ) -> bool:
        if self.project is None:
            QMessageBox.information(
                self,
                "No Project Loaded",
                "Load a project before recalculating harmonic selection.",
            )
            return False
        try:
            normalized = self.project.update_preprocessing(validated_preproc)
            self._project_cache = normalized
            self.project.save()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            return False
        except Exception as exc:  # pragma: no cover - disk I/O error path
            QMessageBox.critical(self, "Save Error", str(exc))
            return False
        return True

    def _on_recalculate_harmonics_clicked(self) -> None:
        validated_preproc = self._validated_preproc_payload()
        if validated_preproc is None:
            return
        if not self._save_project_preprocessing_for_harmonic_recalculation(validated_preproc):
            return
        if not self._project_has_processed_outputs():
            QMessageBox.information(
                self,
                "No Processed Data",
                "Process this project before recalculating harmonic selection.",
            )
            return
        self._start_full_fft_grid_review(recalculate_after=True)

    def _on_review_condition_exclusions_clicked(self) -> None:
        if self.project is None:
            return
        if not self._project_has_processed_outputs():
            QMessageBox.information(
                self,
                "No Processed Data",
                "Process this project before reviewing FFT crop exclusions.",
            )
            return
        self._start_full_fft_grid_review(recalculate_after=False)

    def _save_participant_condition_exclusions(
        self,
        exclusions: Dict[str, Any],
    ) -> bool:
        if self.project is None:
            return False
        normalized_exclusions = normalize_manual_excluded_participant_conditions(
            exclusions
        )
        current = normalize_manual_excluded_participant_conditions(
            self.project.preprocessing.get(
                "manual_excluded_participant_conditions",
                {},
            )
        )
        if normalized_exclusions == current:
            self._manual_excluded_participant_conditions = normalized_exclusions
            return True
        updated_preproc = dict(self.project.preprocessing)
        updated_preproc["manual_excluded_participant_conditions"] = (
            normalized_exclusions
        )
        try:
            normalized = self.project.update_preprocessing(updated_preproc)
            self.project.save()
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "Project Save Error",
                f"Could not save participant-condition exclusions: {exc}",
            )
            return False

        self._project_cache = normalized
        self._manual_excluded_participant_conditions = dict(
            normalized.get("manual_excluded_participant_conditions") or {}
        )
        invalidation_warnings: list[str] = []
        try:
            mark_frequency_domain_outputs_stale(
                self.project.project_root,
                reason="Participant-condition FFT crop exclusions changed.",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            invalidation_warnings.append(
                f"downstream-stale status could not be updated ({exc})"
            )
        try:
            clear_group_significant_selection_cache()
        except RuntimeError as exc:
            invalidation_warnings.append(
                f"the in-memory harmonic cache could not be cleared ({exc})"
            )
        try:
            clear_cached_group_harmonic_selections(self.project.project_root)
        except OSError as exc:
            invalidation_warnings.append(
                f"the saved harmonic cache could not be cleared ({exc})"
            )
        if invalidation_warnings:
            QMessageBox.warning(
                self,
                "Exclusions Saved With Warning",
                "The participant-condition exclusions were saved, but "
                + "; ".join(invalidation_warnings)
                + ". Recalculate harmonics before relying on downstream outputs.",
            )
        return True

    def _set_full_fft_grid_review_controls_enabled(self, enabled: bool) -> None:
        for button in self._settings_footer_buttons:
            try:
                button.setEnabled(enabled)
            except RuntimeError:
                continue
        self.recalculate_harmonics_button.setEnabled(
            enabled and self.project is not None
        )
        self.review_condition_exclusions_button.setEnabled(
            enabled and self.project is not None
        )

    def _start_full_fft_grid_review(
        self,
        *,
        recalculate_after: bool,
        accept_on_success: bool = False,
    ) -> bool:
        if self.project is None:
            return False
        owner = getattr(self, "host", None) or self
        if getattr(owner, "_settings_full_fft_grid_qc_thread", None) is not None:
            QMessageBox.information(
                self,
                "FFT Grid Check Already Running",
                "FPVS Toolbox is already checking processed FFT grids.",
            )
            return False
        if getattr(owner, "_settings_harmonic_recalc_thread", None) is not None:
            QMessageBox.information(
                self,
                "Recalculation Already Running",
                "Wait for harmonic recalculation to finish before checking FFT grids.",
            )
            return False
        try:
            from Main_App.gui.project_workflows import (
                _processing_cache_reset_is_busy,
            )

            project_operation_busy = _processing_cache_reset_is_busy(owner)
        except (AttributeError, RuntimeError):
            project_operation_busy = False
        if project_operation_busy:
            QMessageBox.information(
                self,
                "Project Operation In Progress",
                "Wait for the current data-quality, processing, post-processing, "
                "or cache-reset operation before checking FFT grids.",
            )
            return False
        try:
            from Main_App.workers.full_fft_grid_qc_worker import FullFftGridQcWorker
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "FFT Grid Check Unavailable",
                f"The FFT grid check could not start: {exc}",
            )
            return False

        self._set_harmonic_recalculation_status(
            "Checking processed FullFFT grids for incompatible crop lengths...",
            "info",
        )
        self._set_full_fft_grid_review_controls_enabled(False)
        thread = QThread(owner)
        worker = FullFftGridQcWorker(self.project.project_root)
        worker.moveToThread(thread)
        owner._settings_full_fft_grid_qc_thread = thread
        owner._settings_full_fft_grid_qc_worker = worker

        def _release_worker() -> None:
            owner._settings_full_fft_grid_qc_thread = None
            owner._settings_full_fft_grid_qc_worker = None
            self._set_full_fft_grid_review_controls_enabled(True)
            if getattr(owner, "_settings_harmonic_recalc_thread", None) is not None:
                self.recalculate_harmonics_button.setEnabled(False)
                self.review_condition_exclusions_button.setEnabled(False)

        def _handle_finished(audit: object) -> None:
            candidates = tuple(getattr(audit, "review_candidates", ()) or ())
            should_open = (
                bool(candidates)
                or bool(
                    getattr(audit, "has_unresolved_grid_conflict", False)
                )
                or not recalculate_after
            )
            accepted = True
            proposed_exclusions = self._manual_excluded_participant_conditions
            if should_open:
                dialog = ParticipantConditionExclusionsDialog(
                    audit,
                    self._manual_excluded_participant_conditions,
                    self,
                )
                accepted = dialog.exec() == QDialog.Accepted
                if accepted:
                    proposed_exclusions = (
                        dialog.excluded_participant_conditions()
                    )
                    accepted = self._save_participant_condition_exclusions(
                        proposed_exclusions
                    )
            if not accepted:
                self._set_harmonic_recalculation_status(
                    "FFT crop exclusion review was cancelled.",
                    "warning",
                )
                return
            if recalculate_after:
                if not audit.is_compatible_with_exclusions(
                    proposed_exclusions
                ):
                    self._set_harmonic_recalculation_status(
                        "Harmonic recalculation is waiting for one compatible "
                        "included FFT grid.",
                        "warning",
                    )
                    QMessageBox.warning(
                        self,
                        "Incompatible FFT Grids Still Included",
                        "The included participant-condition workbooks still use "
                        "more than one FFT grid, contain an invalid FullFFT header, "
                        "or leave no usable workbook. Adjust the checked exclusions "
                        "before recalculating harmonics.",
                    )
                    return
                self._start_harmonic_recalculation(
                    accept_on_success=accept_on_success
                )
            else:
                self._set_harmonic_recalculation_status(
                    "Participant-condition exclusions saved. Recalculate harmonics "
                    "to rebuild the project-wide selection.",
                    "success",
                )

        def _handle_failed(message: str) -> None:
            self._set_harmonic_recalculation_status(
                f"FFT grid check failed: {message}",
                "warning",
            )
            QMessageBox.warning(self, "FFT Grid Check Failed", message)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(_handle_finished)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        worker.failed.connect(_handle_failed)
        thread.finished.connect(_release_worker)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        return True

    def _start_harmonic_recalculation(self, *, accept_on_success: bool = False) -> bool:
        if self.project is None:
            return False
        owner = getattr(self, "host", None) or self
        cache_reset_thread = getattr(owner, "_project_processing_cache_thread", None)
        cache_reset_is_running = getattr(cache_reset_thread, "isRunning", None)
        try:
            cache_reset_active = bool(
                callable(cache_reset_is_running) and cache_reset_is_running()
            )
        except RuntimeError:
            cache_reset_active = False
        if cache_reset_active:
            QMessageBox.information(
                self,
                "Cache Reset In Progress",
                "Wait for the project processing-cache reset to finish before "
                "recalculating harmonics.",
            )
            return False
        if getattr(owner, "_settings_harmonic_recalc_thread", None) is not None:
            QMessageBox.information(
                self,
                "Recalculation Already Running",
                "FPVS Toolbox is already recalculating harmonic selection for this project.",
            )
            return False
        try:
            from Main_App.workers.harmonic_selection_worker import (
                ProcessingHarmonicSelectionWorker,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Recalculation Unavailable",
                f"Harmonic recalculation could not start: {exc}",
            )
            return False

        self._set_harmonic_recalculation_status(
            "Recalculating harmonic selection from processed Excel outputs...",
            "info",
        )
        self.recalculate_harmonics_button.setEnabled(False)
        self.review_condition_exclusions_button.setEnabled(False)
        thread = QThread(owner)
        worker = ProcessingHarmonicSelectionWorker(self.project)
        worker.moveToThread(thread)
        owner._settings_harmonic_recalc_thread = thread
        owner._settings_harmonic_recalc_worker = worker

        def _handle_finished(result: dict) -> None:
            try:
                if result.get("ok"):
                    workbook_path = result.get("workbook_path", "")
                    self._initial_harmonic_settings_signature = (
                        self._harmonic_settings_signature_from_preprocessing(
                            self._project_preprocessing()
                        )
                    )
                    self._set_harmonic_recalculation_status(
                        f"Harmonic selection recalculated: {workbook_path}",
                        "success",
                    )
                    QMessageBox.information(
                        self,
                        "Harmonics Recalculated",
                        f"Harmonic selection was recalculated and saved to:\n{workbook_path}",
                    )
                    if accept_on_success:
                        self.accept()
                else:
                    message = str(result.get("error") or "Unknown error")
                    self._set_harmonic_recalculation_status(
                        f"Harmonic recalculation failed: {message}",
                        "warning",
                    )
                    QMessageBox.warning(
                        self,
                        "Harmonic Recalculation Failed",
                        message,
                    )
            finally:
                owner._settings_harmonic_recalc_thread = None
                owner._settings_harmonic_recalc_worker = None
                enabled = self.project is not None
                self.recalculate_harmonics_button.setEnabled(enabled)
                self.review_condition_exclusions_button.setEnabled(enabled)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(_handle_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        return True

    def _removed_electrode_detection_mode(self) -> str:
        return normalize_removed_electrode_detection_mode(
            self.removed_electrode_detection_mode_combo.currentData(),
            auto_detect_removed_electrodes=True,
        )

    def _set_removed_electrode_detection_enabled(self, enabled: bool) -> None:
        mode = (
            REMOVED_ELECTRODE_DETECTION_MODE_AUTO
            if enabled
            else REMOVED_ELECTRODE_DETECTION_MODE_OFF
        )
        target_index = self.removed_electrode_detection_mode_combo.findData(mode)
        if target_index >= 0 and target_index != self.removed_electrode_detection_mode_combo.currentIndex():
            self.removed_electrode_detection_mode_combo.setCurrentIndex(target_index)

    def _sync_removed_electrode_detection_checkbox(self) -> None:
        enabled = self._removed_electrode_detection_enabled()
        if self.auto_detect_removed_electrodes_check.isChecked() == enabled:
            return
        self.auto_detect_removed_electrodes_check.blockSignals(True)
        try:
            self.auto_detect_removed_electrodes_check.setChecked(enabled)
        finally:
            self.auto_detect_removed_electrodes_check.blockSignals(False)

    def _on_removed_electrode_detection_mode_changed(self) -> None:
        self._sync_removed_electrode_detection_checkbox()
        self._update_manual_removed_electrodes_button()
        if self._removed_electrode_detection_mode() == REMOVED_ELECTRODE_DETECTION_MODE_MANUAL:
            self._edit_manual_removed_electrodes()

    def _update_manual_removed_electrodes_button(self) -> None:
        self.manual_removed_electrodes_button.setEnabled(
            self._removed_electrode_detection_mode()
            == REMOVED_ELECTRODE_DETECTION_MODE_MANUAL
        )

    def _manual_removed_electrode_participant_ids(self) -> list[str]:
        participant_ids: list[str] = []
        if self.project is None:
            return participant_ids
        participants = getattr(self.project, "participants", {}) or {}
        if isinstance(participants, dict):
            participant_ids.extend(str(pid) for pid in participants if str(pid).strip())
        try:
            participant_ids.extend(
                info.subject_id for info in prepare_batch_file_infos(self.project)
            )
        except (OSError, RuntimeError, ValueError):
            pass
        seen: set[str] = set()
        unique: list[str] = []
        for pid in participant_ids:
            key = pid.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(pid)
        return unique

    def _edit_manual_removed_electrodes(self) -> None:
        dialog = ManualRemovedElectrodesDialog(
            self._manual_removed_electrode_participant_ids(),
            self._manual_removed_electrodes_by_pid,
            self,
        )
        if dialog.exec() == QDialog.Accepted:
            self._manual_removed_electrodes_by_pid = dialog.manual_removed_electrodes()

    def _edit_manual_participant_exclusions(self) -> None:
        dialog = ManualParticipantExclusionsDialog(
            self._manual_removed_electrode_participant_ids(),
            self._manual_excluded_participants,
            self,
        )
        if dialog.exec() == QDialog.Accepted:
            self._manual_excluded_participants = dialog.excluded_participants()

    def _show_removed_electrode_detection_info(self) -> None:
        QMessageBox.information(
            self,
            "Conservative Removed-Electrode Detection",
            REMOVED_ELECTRODE_DETECTION_INFO_TEXT,
        )

    def _current_roi_montage(self) -> str:
        return validate_roi_montage(str(self.roi_montage_combo.currentData()))

    def _custom_roi_presets(self, montage: str) -> list[tuple[str, list[str]]]:
        montage_key = validate_roi_montage(montage)
        if montage_key not in self._custom_roi_presets_by_montage:
            self._custom_roi_presets_by_montage[montage_key] = self.manager.get_custom_roi_presets(montage_key)
        return self._custom_roi_presets_by_montage[montage_key]

    def _roi_preset_items(self, montage: str) -> list[tuple[str, list[str], bool]]:
        montage_key = validate_roi_montage(montage)
        items: list[tuple[str, list[str], bool]] = []
        seen: set[str] = set()
        for preset in default_roi_presets(montage_key):
            items.append((preset.name, list(preset.electrodes), True))
            seen.add(preset.name.casefold())
        for name, electrodes in self._custom_roi_presets(montage_key):
            if name.casefold() not in seen:
                items.append((name, list(electrodes), False))
                seen.add(name.casefold())
        return items

    def _refresh_roi_preset_combo(self) -> None:
        montage = self._current_roi_montage()
        self.roi_preset_combo.blockSignals(True)
        self.roi_preset_combo.clear()
        for name, electrodes, is_default in self._roi_preset_items(montage):
            source = "Default" if is_default else "Custom"
            self.roi_preset_combo.addItem(f"{name} ({source})", (name, electrodes, is_default))
        self.roi_preset_combo.blockSignals(False)
        self._update_roi_preset_preview()

    def _selected_roi_preset(self) -> tuple[str, list[str], bool] | None:
        preset = self.roi_preset_combo.currentData()
        if not isinstance(preset, tuple) or len(preset) != 3:
            return None
        name, electrodes, is_default = preset
        if not isinstance(name, str) or not isinstance(electrodes, list) or not isinstance(is_default, bool):
            return None
        return name, electrodes, is_default

    def _set_roi_preset_status(self, text: str, variant: str = "info") -> None:
        self.roi_preset_status.set_variant(variant)
        self.roi_preset_status.set_text(text)
        self.roi_preset_status.setVisible(bool(text))

    def _update_roi_preset_preview(self) -> None:
        preset = self._selected_roi_preset()
        if preset is None:
            self.roi_preset_electrodes_edit.clear()
            return
        _name, electrodes, _is_default = preset
        self.roi_preset_electrodes_edit.setText(",".join(electrodes))

    def _on_roi_montage_changed(self) -> None:
        self._refresh_roi_preset_combo()
        self._set_roi_preset_status("")

    def _add_selected_roi_preset(self) -> None:
        preset = self._selected_roi_preset()
        if preset is None:
            self._set_roi_preset_status("No ROI preset is selected.", "warning")
            return
        name, electrodes, _is_default = preset
        result = self.roi_editor.add_or_update_entry(name, electrodes)
        action = "Updated" if result == "updated" else "Added"
        self._set_roi_preset_status(f"{action} {name}.", "success")

    def _save_roi_editor_as_custom_presets(self) -> None:
        montage = self._current_roi_montage()
        default_names = default_roi_name_keys(montage)
        custom_by_name = {
            name.casefold(): (name, list(electrodes))
            for name, electrodes in self._custom_roi_presets(montage)
        }
        changed = 0
        for name, electrodes in self.roi_editor.get_pairs():
            name_key = name.casefold()
            if name_key in default_names:
                continue
            candidate = (name, list(electrodes))
            if custom_by_name.get(name_key) != candidate:
                changed += 1
            custom_by_name[name_key] = candidate

        self._custom_roi_presets_by_montage[montage] = list(custom_by_name.values())
        self._refresh_roi_preset_combo()
        if changed:
            self._set_roi_preset_status("Custom ROI presets will be saved when you click Save.", "success")
        else:
            self._set_roi_preset_status("No new custom ROI presets found.", "info")

    def _on_tab_changed(self, index: int) -> None:
        if getattr(self, "_tab_change_guard", False):
            return

        previous = getattr(self, "_last_tab_index", 0)
        if (
            previous == getattr(self, "_preproc_tab_index", -1)
            and index != getattr(self, "_preproc_tab_index", -1)
        ):
            if not self._validate_preproc_fields():
                self._tab_change_guard = True
                self.tabs.setCurrentIndex(getattr(self, "_preproc_tab_index", 0))
                self._tab_change_guard = False
                self._last_tab_index = getattr(self, "_preproc_tab_index", 0)
                return

        self._last_tab_index = index

    # ------------------------------------------------------------------
    def _focus_invalid_preproc_field(self, message: str) -> None:
        msg_lower = message.lower()
        target_idx = None
        if "low-pass" in msg_lower or "'low_pass'" in msg_lower:
            target_idx = 0
        elif "high-pass" in msg_lower or "'high_pass'" in msg_lower:
            target_idx = 1
        elif "'max_parallel_workers_override'" in msg_lower:
            target_idx = 10
        if target_idx is not None and target_idx < len(self.preproc_edits):
            edit = self.preproc_edits[target_idx]
            edit.setFocus()
            edit.selectAll()

    def _validated_preproc_payload(self) -> Dict[str, Any] | None:
        try:
            return normalize_preprocessing_settings(self._collect_project_preprocessing_inputs())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            self._focus_invalid_preproc_field(str(exc))
            return None

    def _validate_preproc_fields(self) -> bool:
        return self._validated_preproc_payload() is not None

    def _on_preproc_edit_finished(self, canonical: str, field: QLineEdit) -> None:  # noqa: ARG002
        if not self._validate_preproc_fields():
            field.setFocus()
            field.selectAll()

    def _confirm_parallel_worker_override(self, normalized: Dict[str, Any]) -> bool:
        override = int(normalized.get("max_parallel_workers_override", 0))
        if override <= 0:
            return True

        try:
            total_ram_bytes = int(psutil.virtual_memory().total)
        except Exception:
            return True

        _tier, recommended_cap, _ram_gib = get_ram_tier_recommendation(total_ram_bytes)
        if recommended_cap is None or override <= recommended_cap:
            return True

        message = (
            f"The maximum amount of workers recommended for your RAM tier is [{recommended_cap}]. "
            "Selecting a value higher than this could cause your system to become slow or "
            "completely unresponsive for a time. Do you wish to continue?"
        )
        choice = QMessageBox.question(
            self,
            "High Worker Count Warning",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            if len(self.preproc_edits) > 10:
                field = self.preproc_edits[10]
                field.setFocus()
                field.selectAll()
            return False
        return True

    def _full_fft_grid_review_is_running(self) -> bool:
        owner = getattr(self, "host", None) or self
        thread = getattr(owner, "_settings_full_fft_grid_qc_thread", None)
        if thread is None:
            return False
        is_running = getattr(thread, "isRunning", None)
        if not callable(is_running):
            return True
        try:
            return bool(is_running())
        except RuntimeError:
            return False

    def reject(self) -> None:
        if self._full_fft_grid_review_is_running():
            QMessageBox.information(
                self,
                "FFT Grid Check In Progress",
                "Wait for the processed FFT grid check to finish before closing "
                "Settings.",
            )
            return
        super().reject()

    # ------------------------------------------------------------------
    def _save(self) -> None:
        if self._full_fft_grid_review_is_running():
            QMessageBox.information(
                self,
                "FFT Grid Check In Progress",
                "Wait for the processed FFT grid check to finish before saving "
                "Settings.",
            )
            return
        using_project = self.project is not None

        validated_preproc = self._validated_preproc_payload()
        if validated_preproc is None:
            return
        if not self._confirm_parallel_worker_override(validated_preproc):
            return
        recalculate_harmonics_after_save = False
        if self._harmonic_settings_changed_after_processing(validated_preproc):
            recalculate_harmonics_after_save = (
                self._ask_recalculate_harmonics_after_settings_change()
            )

        if not using_project:
            self.manager.set("stim", "channel", config.DEFAULT_STIM_CHANNEL)
        self.manager.set("analysis", "base_freq", self.base_freq_edit.text())
        self.manager.set("analysis", "oddball_freq", str(config.DEFAULT_ODDBALL_FREQ))
        self.manager.set("analysis", "bca_upper_limit", self.bca_limit_edit.text())
        self.manager.set("analysis", "alpha", self.alpha_edit.text())
        self.manager.set_roi_montage(self._current_roi_montage())
        self.manager.set_roi_pairs(self.roi_editor.get_pairs())
        for montage_key, custom_presets in self._custom_roi_presets_by_montage.items():
            self.manager.set_custom_roi_presets(montage_key, custom_presets)
        pre_keys = [
            ("preprocessing", "low_pass", "low_pass"),
            ("preprocessing", "high_pass", "high_pass"),
            ("preprocessing", "downsample", "downsample"),
            ("preprocessing", "epoch_start", "epoch_start_s"),
            ("preprocessing", "reject_thresh", "rejection_z"),
            ("preprocessing", "epoch_end", "epoch_end_s"),
            ("preprocessing", "ref_chan1", "ref_chan1"),
            ("preprocessing", "ref_chan2", "ref_chan2"),
            ("preprocessing", "max_idx_keep", "max_chan_idx_keep"),
            ("preprocessing", "max_bad_chans", "max_bad_chans"),
            ("preprocessing", "max_parallel_workers", "max_parallel_workers_override"),
        ]
        if not using_project:
            for _edit, (sec, opt, canonical) in zip(self.preproc_edits, pre_keys):
                value = validated_preproc.get(canonical, "")
                self.manager.set(sec, opt, str(value))
            self.manager.set(
                "preprocessing",
                "auto_detect_removed_electrodes",
                str(bool(validated_preproc.get("auto_detect_removed_electrodes"))),
            )
            self.manager.set(
                "preprocessing",
                "removed_electrode_detection_mode",
                str(validated_preproc.get("removed_electrode_detection_mode")),
            )
            self.manager.set(
                "preprocessing",
                "manual_removed_electrodes",
                json.dumps(validated_preproc.get("manual_removed_electrodes", {})),
            )
            self.manager.set(
                "preprocessing",
                "manual_excluded_participants",
                json.dumps(validated_preproc.get("manual_excluded_participants", [])),
            )
            self.manager.set(
                "preprocessing",
                "line_noise_filter_enabled",
                str(bool(validated_preproc.get("line_noise_filter_enabled"))),
            )
            self.manager.set(
                "preprocessing",
                "line_noise_frequency_hz",
                str(int(validated_preproc.get("line_noise_frequency_hz", 60))),
            )
            for option in (
                "harmonic_selection_policy",
                "group_significant_electrode_scope",
                "group_significant_summation_method",
                "fixed_harmonic_frequencies_hz",
                "fixed_harmonic_auto_exclude_base",
            ):
                self.manager.set(
                    "preprocessing",
                    option,
                    str(validated_preproc.get(option, PREPROCESSING_DEFAULTS.get(option, ""))),
                )
        else:
            try:
                normalized = self.project.update_preprocessing(validated_preproc)
                self._project_cache = normalized
                self.project.save()
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid Settings", str(exc))
                return
            except Exception as exc:  # pragma: no cover - disk I/O error path
                QMessageBox.critical(self, "Save Error", str(exc))
                return
        prev_debug = self.manager.debug_enabled()
        prev_beta_tools = self.manager.beta_tools_enabled()
        self.manager.set("debug", "enabled", str(self.debug_check.isChecked()))
        self.manager.set_beta_tools_enabled(self.beta_tools_check.isChecked())
        self.manager.save()

        if not prev_debug and self.manager.debug_enabled():
            QMessageBox.information(
                self,
                "Debug Mode Enabled",
                "Debug mode enabled. Please close and reopen FPVS Toolbox for changes to take effect.",
            )
        if prev_beta_tools != self.manager.beta_tools_enabled():
            QMessageBox.information(
                self,
                "Tool Visibility Updated",
                "Please close and reopen FPVS Toolbox for your changes to take effect.",
            )

        try:
            from Tools.Stats.data.shared_rois import (
                load_rois_from_settings,
                apply_rois_to_modules,
            )

            rois = load_rois_from_settings(self.manager)
            apply_rois_to_modules(rois)

            host = getattr(self, "host", None) or self.parent()
            stats_page = getattr(host, "_stats_page", None)
            if stats_page is not None:
                refresh_rois = getattr(stats_page, "refresh_rois", None)
                if callable(refresh_rois):
                    refresh_rois()
        except Exception:
            pass

        try:
            from config import update_target_frequencies

            update_target_frequencies(
                config.DEFAULT_ODDBALL_FREQ,
                float(self.bca_limit_edit.text()),
            )
        except Exception:
            pass

        if recalculate_harmonics_after_save:
            if self._start_full_fft_grid_review(
                recalculate_after=True,
                accept_on_success=True,
            ):
                return

        self.accept()

    # ------------------------------------------------------------------
    def _project_preprocessing(self) -> Dict[str, Any]:
        if self.project is None:
            return {}
        if self._project_cache is None:
            try:
                self._project_cache = normalize_preprocessing_settings(self.project.preprocessing)
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid Settings", str(exc))
                self._project_cache = normalize_preprocessing_settings({})
        return self._project_cache

    def _collect_project_preprocessing_inputs(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        canonical_keys = [
            "low_pass",
            "high_pass",
            "downsample",
            "epoch_start_s",
            "rejection_z",
            "epoch_end_s",
            "ref_chan1",
            "ref_chan2",
            "max_chan_idx_keep",
            "max_bad_chans",
            "max_parallel_workers_override",
        ]
        for edit, canonical in zip(self.preproc_edits, canonical_keys):
            values[canonical] = edit.text()
        values["line_noise_filter_enabled"] = (
            self.line_noise_filter_enabled_check.isChecked()
        )
        values["line_noise_frequency_hz"] = int(
            self.line_noise_frequency_combo.currentData()
        )
        mode = self._removed_electrode_detection_mode()
        values["removed_electrode_detection_mode"] = mode
        values["auto_detect_removed_electrodes"] = (
            mode == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        )
        values["manual_removed_electrodes"] = dict(self._manual_removed_electrodes_by_pid)
        values["manual_excluded_participants"] = list(
            self._manual_excluded_participants
        )
        values["manual_excluded_participant_conditions"] = dict(
            self._manual_excluded_participant_conditions
        )
        fixed_selected = self._fixed_harmonic_list_selected()
        values["harmonic_selection_policy"] = (
            FIXED_PREDEFINED_POLICY_NAME
            if fixed_selected
            else GROUP_SIGNIFICANT_POLICY_NAME
        )
        values["group_significant_electrode_scope"] = (
            self.harmonic_electrode_scope_combo.currentData()
            or GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION
        )
        selected_summation_method = self.harmonic_summation_method_combo.currentData()
        values["group_significant_summation_method"] = (
            GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST
            if fixed_selected
            else (
                selected_summation_method
                or GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST
            )
        )
        values["fixed_harmonic_frequencies_hz"] = self.fixed_harmonic_freqs_edit.text()
        values["fixed_harmonic_auto_exclude_base"] = (
            self.fixed_harmonic_exclude_base_check.isChecked()
        )
        values["stim_channel"] = config.DEFAULT_STIM_CHANNEL
        return values


class EmbeddedSettingsPage(SettingsDialog):
    """Settings editor used as a workspace page inside the main shell."""

    def __init__(
        self,
        manager: SettingsManager,
        host: QWidget,
        project: Project | None = None,
    ) -> None:
        super().__init__(manager, host, project)
        self.host = host
        self.setObjectName("embedded_settings_page")
        self.setWindowFlags(Qt.Widget)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def accept(self) -> None:
        self._return_to_home()

    def reject(self) -> None:
        self._return_to_home()

    def _return_to_home(self) -> None:
        host = getattr(self, "host", None)
        if host is None:
            return
        debug_label = getattr(host, "lbl_debug", None)
        if debug_label is not None:
            debug_label.setVisible(host.settings.debug_enabled())
        show_home_page = getattr(host, "show_home_page", None)
        if callable(show_home_page):
            show_home_page()
