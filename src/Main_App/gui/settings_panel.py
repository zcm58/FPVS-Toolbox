from __future__ import annotations

import copy
import json
import logging
from typing import Any, Callable, Dict
from pathlib import Path

import config

from Main_App.gui import (
    settings_preprocessing_page,
    settings_protocol_page,
    settings_harmonic_page,
    settings_experimental_page,
    settings_preferences_pages,
)
from Main_App.gui.settings_harmonic_page import HARMONIC_METHOD_INFO as HARMONIC_METHOD_INFO

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QHBoxLayout,
    QDialog,
    QTabWidget,
    QGridLayout,
    QMessageBox,
    QSizePolicy,
)

from Main_App.settings.settings_manager import SettingsManager
from Main_App.processing.roi_presets import (
    default_roi_presets,
    supported_roi_montages,
    validate_roi_montage,
)
from Main_App.gui.components import (
    ActionRow,
    StatusBanner,
    make_action_button,
    make_form_layout,
    show_tool_info,
)
from Main_App.gui.manual_removed_electrodes_dialog import ManualRemovedElectrodesDialog
from Main_App.gui.participant_condition_exclusions_dialog import (
    ParticipantConditionExclusionsDialog,
)
from Main_App.gui.project_protocol import (
    ANALYSIS_WINDOW_MODE_CYCLES,
    ANALYSIS_WINDOW_MODE_DURATION,
    ANALYSIS_WINDOW_MODE_STUDIO,
    ProtocolEditorValues,
    build_manual_protocol,
    duration_summary,
    editor_values_for_protocol,
    protocol_settings_save_requested,
    rate_summary,
)
from Main_App.gui.recording_qc_identity import project_recording_coverage_rows
from Main_App.gui.roi_settings_editor import ROISettingsEditor
from Main_App.gui.settings_feedback import (
    PREPROCESSING_FIELDS,
    SettingsDraftTracker,
    mark_invalid,
    preprocessing_error_field,
    refresh_preprocessing_feedback,
)
from Main_App.processing.processing_controller import prepare_batch_file_infos
from Main_App.processing.processing_ledger import load_ledger
from Main_App.processing.missing_condition_outputs import missing_output_exclusions_changed
from Main_App.processing.frequency_domain_qc import (
    mark_frequency_domain_outputs_stale,
)
from Main_App.projects import (
    DatasetIndexError,
    ExperimentalQcSettings,
    ExperimentalQcSettingsError,
    FrequencyProtocol,
    FrequencyProtocolError,
    ODDBALL_INPUT_MODE_DIRECT_HZ,
    ODDBALL_INPUT_MODE_RECURRENCE,
    SummedBcaScreeningSettings,
    load_project_dataset_index,
    validate_protocol_condition_codes,
)
from Main_App.projects.projects_root import changeProjectsRoot
from Main_App.projects.project import Project
from Main_App.projects.preprocessing_settings import (
    ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
    ELECTRODE_MONTAGE_BIOSEMI64,
    MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
    OPTIONAL_PREPROCESSING_KEYS,
    PREPROCESSING_DEFAULTS,
    REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS,
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_recording_conditions,
    normalize_preprocessing_settings,
)
from Main_App.processing.removed_electrode_detection import (
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
    REMOVED_ELECTRODE_DETECTION_MODE_OFF,
)
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_HARMONIC_INPUT_FREQUENCY_LIST,
    FIXED_HARMONIC_INPUT_UPPER_FREQUENCY,
    FIXED_HARMONIC_INPUT_UPPER_HARMONIC,
    FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
    FIXED_PREDEFINED_POLICY_NAME,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
    GROUP_SIGNIFICANT_POLICY_NAME,
    GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY,
    GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
    GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES,
    HARMONIC_PROFILE_FIXED_ID,
    HARMONIC_PROFILE_LEGACY_ID,
    HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
    HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID,
    HARMONIC_PROFILE_VERSION_1,
    normalize_dv_policy,
)
from Tools.Stats.analysis.dv_policy_group_significant import clear_group_significant_selection_cache
from Tools.Stats.data.group_harmonic_cache import clear_cached_group_harmonic_selections


logger = logging.getLogger(__name__)




class _SettingsWorkerUiBridge(QObject):
    """Marshal Settings worker callbacks onto the main GUI thread."""

    def __init__(
        self,
        *,
        result_callback: Callable[[object], None],
        failed_callback: Callable[[str], None] | None = None,
        progress_callback: Callable[[str], None] | None = None,
        phase_progress_callback: Callable[[str, int, int, str], None] | None = None,
        thread_finished_callback: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._result_callback = result_callback
        self._failed_callback = failed_callback
        self._progress_callback = progress_callback
        self._phase_progress_callback = phase_progress_callback
        self._thread_finished_callback = thread_finished_callback
        self._handling_result = False
        self._thread_finished_pending = False

    @Slot(object)
    def handle_result(self, result: object) -> None:
        self._handling_result = True
        try:
            self._result_callback(result)
        finally:
            self._handling_result = False
            if self._thread_finished_pending:
                self.handle_thread_finished()

    @Slot(str)
    def handle_failed(self, message: str) -> None:
        self._handling_result = True
        try:
            if self._failed_callback is not None:
                self._failed_callback(message)
        finally:
            self._handling_result = False
            if self._thread_finished_pending:
                self.handle_thread_finished()

    @Slot(str)
    def handle_progress(self, message: str) -> None:
        if self._progress_callback is not None:
            self._progress_callback(message)

    @Slot(str, int, int, str)
    def handle_phase_progress(
        self,
        phase_id: str,
        completed_units: int,
        total_units: int,
        message: str,
    ) -> None:
        if self._phase_progress_callback is not None:
            self._phase_progress_callback(
                phase_id,
                completed_units,
                total_units,
                message,
            )

    @Slot()
    def handle_thread_finished(self) -> None:
        # Result handlers can open a modal review. Its nested event loop may
        # deliver thread.finished before that handler returns to its controls.
        if self._handling_result:
            self._thread_finished_pending = True
            return
        self._thread_finished_pending = False
        callback = self._thread_finished_callback
        self._thread_finished_callback = None
        try:
            if callback is not None:
                callback()
        finally:
            self.deleteLater()


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
        self._trigger_maps_payload = (
            project.frequency_protocol.condition_trigger_maps.to_manifest()
            if project is not None and project.frequency_protocol.condition_trigger_maps is not None else None
        )
        self._initial_trigger_maps_payload = copy.deepcopy(self._trigger_maps_payload)
        self._trigger_protocol_baseline = (
            (project.frequency_protocol.to_manifest(), copy.deepcopy(project.event_map)) if project is not None else None
        )
        self._project_cache: Dict[str, Any] | None = None
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
        from Main_App.gui.settings_hardware_controls import refresh_hardware_qc_controls
        refresh_hardware_qc_controls(self)
        self._draft_tracker = SettingsDraftTracker(self)
        self._pending_save_succeeded = False
        self._refresh_guided_setup_availability()

    def _refresh_guided_setup_availability(self) -> None:
        from Main_App.gui.pipeline_setup_workflow import refresh_guided_setup_availability

        refresh_guided_setup_availability(self)

    def _show_pipeline_setup(self) -> None:
        from Main_App.gui.pipeline_setup_workflow import show_pipeline_setup

        show_pipeline_setup(self)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._refresh_guided_setup_availability()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("Settings[*]")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("settings_tabs")
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.setStyleSheet(
            "QTabWidget#settings_tabs::pane, "
            "QTabWidget#settings_protocol_sections::pane, "
            "QTabWidget#settings_experimental_sections::pane {"
            " border: none; background: transparent; }"
        )
        layout.addWidget(self.tabs, 1)

        self.settings_validation_status = StatusBanner("", self, variant="warning")
        self.settings_validation_status.setObjectName("settings_validation_status")
        self.settings_validation_status.label.setTextFormat(Qt.PlainText)
        self.settings_validation_status.hide()
        layout.addWidget(self.settings_validation_status)

        preproc_tab = self._init_preproc_tab(self.tabs)
        self._preproc_tab_index = self.tabs.indexOf(preproc_tab)
        protocol_tab = self._init_protocol_tab(self.tabs)
        self._protocol_tab_index = self.tabs.indexOf(protocol_tab)
        harmonic_tab = self._init_harmonic_tab(self.tabs)
        self._harmonic_tab_index = self.tabs.indexOf(harmonic_tab)
        self._init_rois_tab(self.tabs)
        self._init_quality_control_tab(self.tabs)
        experimental_tab = self._init_experimental_tab(self.tabs)
        self._experimental_tab_index = self.tabs.indexOf(experimental_tab)
        self._init_application_tab(self.tabs)
        self._add_settings_footer(layout)
        self._initial_protocol_editor_values = self._protocol_editor_values()
        self._initial_harmonic_settings_signature = (
            self._harmonic_settings_signature_from_preprocessing(
                self._project_preprocessing(),
                roi_pairs_override=self.manager.get_roi_pairs(),
            )
        )
        self._initial_frequency_analysis_signature = (
            self._frequency_analysis_settings_signature(
                roi_pairs_override=self.manager.get_roi_pairs(),
            )
        )
        self._last_tab_index = self.tabs.currentIndex()
        self._tab_change_guard = False
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _add_settings_footer(
        self,
        layout: QVBoxLayout,
    ) -> None:
        footer = QWidget(self)
        footer.setObjectName("settings_footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)
        note = QLabel("Save applies changes across all settings pages.", footer)
        note.setWordWrap(True)
        footer_layout.addWidget(note, 1)

        actions = ActionRow(footer, alignment=Qt.AlignRight)
        actions.setObjectName("settings_footer_actions")
        save_btn = make_action_button("Save", variant="primary", parent=actions)
        cancel_btn = make_action_button("Cancel", variant="secondary", parent=actions)
        save_btn.setObjectName("settings_footer_save")
        cancel_btn.setObjectName("settings_footer_cancel")
        save_btn.clicked.connect(self._save)
        cancel_btn.clicked.connect(self.reject)
        actions.add_button(save_btn)
        actions.add_button(cancel_btn)
        footer_layout.addWidget(actions)
        self._settings_footer_buttons.extend((save_btn, cancel_btn))

        layout.addWidget(footer)

    def _add_settings_scope(self, layout: QVBoxLayout, text: str) -> None:
        note = QLabel(text, layout.parentWidget())
        note.setWordWrap(True)
        note.setTextFormat(Qt.PlainText)
        layout.addWidget(note)

    # ------------------------------------------------------------------
    def _init_preproc_tab(self, tabs: QTabWidget) -> QWidget:
        return settings_preprocessing_page.build_preprocessing_page(self, tabs)

    def _init_protocol_tab(self, tabs: QTabWidget) -> QWidget:
        return settings_protocol_page.build_protocol_page(self, tabs)

    def _init_harmonic_tab(self, tabs: QTabWidget) -> QWidget:
        return settings_harmonic_page.build_harmonic_page(self, tabs)

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
            "harmonic_selection_profile": preprocessing.get(
                "harmonic_selection_profile",
                self.manager.get(
                    "preprocessing",
                    "harmonic_selection_profile",
                    HARMONIC_PROFILE_LEGACY_ID,
                ),
            ),
            "harmonic_selection_profile_version": preprocessing.get(
                "harmonic_selection_profile_version",
                self.manager.get(
                    "preprocessing",
                    "harmonic_selection_profile_version",
                    HARMONIC_PROFILE_VERSION_1,
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
                    "through_highest_significant",
                ),
            ),
            "group_significant_selection_electrodes": preprocessing.get(
                "group_significant_selection_electrodes",
                self.manager.get(
                    "preprocessing",
                    "group_significant_selection_electrodes",
                    "",
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
            "fixed_harmonic_input_mode": preprocessing.get(
                "fixed_harmonic_input_mode",
                self.manager.get(
                    "preprocessing",
                    "fixed_harmonic_input_mode",
                    FIXED_HARMONIC_INPUT_FREQUENCY_LIST,
                ),
            ),
            "fixed_harmonic_upper_harmonic_index": preprocessing.get(
                "fixed_harmonic_upper_harmonic_index",
                self.manager.get(
                    "preprocessing",
                    "fixed_harmonic_upper_harmonic_index",
                    "0",
                ),
            ),
            "fixed_harmonic_upper_frequency_hz": preprocessing.get(
                "fixed_harmonic_upper_frequency_hz",
                self.manager.get(
                    "preprocessing",
                    "fixed_harmonic_upper_frequency_hz",
                    "0.0",
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
        return settings_harmonic_page.add_harmonic_selection_section(
            self, tab, layout, project_pp,
        )

    # ------------------------------------------------------------------
    def _init_rois_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        current_montage = self.manager.get_roi_montage()
        montage_labels = dict(supported_roi_montages())
        default_rois = tuple(
            (preset.name, preset.electrodes)
            for preset in default_roi_presets(current_montage)
        )

        self.roi_editor = ROISettingsEditor(
            tab,
            self.manager.get_roi_pairs(),
            canonical_electrodes=config.DEFAULT_ELECTRODE_NAMES_64,
            default_rois=default_rois,
            current_montage=current_montage,
            montage_label=montage_labels[current_montage],
        )
        self.roi_editor.setObjectName("settings_rois_editor")
        self.roi_editor.montage_label.setText(
            f"Montage: {montage_labels[current_montage]} — ROI presets are shared across projects."
        )
        self.roi_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.roi_editor, 1)

        self._roi_tab_index = tabs.addTab(tab, "ROIs")

    # ------------------------------------------------------------------
    def _init_experimental_tab(self, tabs: QTabWidget) -> QWidget:
        return settings_experimental_page.build_experimental_page(self, tabs)

    def _add_experimental_info_row(
        self, layout: QVBoxLayout, parent: QWidget, content: QWidget | str,
        title: str, description: str, object_name: str,
    ) -> None:
        return settings_experimental_page.add_experimental_info_row(
            self, layout, parent, content, title, description, object_name,
        )

    def _refresh_experimental_qc_dependencies(self) -> None:
        project_enabled = self.project is not None
        kurtosis_enabled = project_enabled and self.kurtosis_screening_enabled_check.isChecked()
        self.kurtosis_auto_interpolate_all_check.setEnabled(kurtosis_enabled)
        self.kurtosis_review_auto_interpolate_extreme_check.setEnabled(kurtosis_enabled)
        summed_bca_enabled = project_enabled and self.summed_bca_screening_enabled_check.isChecked()
        self.condition_specific_interpolation_enabled_check.setEnabled(summed_bca_enabled)
        for edit in self.summed_bca_threshold_edits.values():
            edit.setEnabled(project_enabled)
        if hasattr(self, "hardware_platform_combo"):
            from Main_App.gui.settings_hardware_controls import refresh_hardware_qc_controls
            refresh_hardware_qc_controls(self)

    def _init_beta_tools_page(self, tabs: QTabWidget) -> None:
        return settings_experimental_page.build_beta_tools_page(self, tabs)

    def _add_experimental_threshold_grid(
        self,
        grid: QGridLayout,
        specs: tuple[tuple[str, str, object], ...],
        parent: QWidget,
    ) -> None:
        return settings_experimental_page.add_experimental_threshold_grid(
            self, grid, specs, parent,
        )

    def _init_application_tab(self, tabs: QTabWidget) -> None:
        return settings_preferences_pages.build_application_page(
            self, tabs, change_projects_root=lambda: changeProjectsRoot(self),
        )

    def _init_quality_control_tab(self, tabs: QTabWidget) -> None:
        return settings_preferences_pages.build_quality_control_page(self, tabs)

    def _clear_toolbox_cache(self) -> None:
        from Main_App.gui.toolbox_cache_workflow import show_toolbox_cache_clear

        show_toolbox_cache_clear(self)

    def _add_frequency_domain_qc_settings(self, parent: QWidget) -> None:
        return settings_preferences_pages.add_frequency_domain_qc_settings(self, parent)

    def _removed_electrode_detection_enabled(self) -> bool:
        return (
            self._removed_electrode_detection_mode()
            == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        )

    def _protocol_input_mode(self) -> str:
        return str(
            self.protocol_oddball_mode_combo.currentData()
            or ODDBALL_INPUT_MODE_RECURRENCE
        )

    def _protocol_editor_values(self) -> ProtocolEditorValues:
        return ProtocolEditorValues(
            presentation_rate_hz=self.protocol_presentation_rate_edit.text(),
            oddball_input_mode=self._protocol_input_mode(),
            oddball_every_n=self.protocol_oddball_every_n_edit.text(),
            entered_oddball_rate_hz=self.protocol_direct_oddball_rate_edit.text(),
            expected_analyzed_oddball_cycles=self.protocol_expected_cycles_edit.text(),
            analysis_window_mode=str(self.protocol_analysis_window_mode_combo.currentData()),
            requested_duration_seconds=self.protocol_requested_duration_edit.text(),
            target_sampling_rate_hz=self.preproc_edits[PREPROCESSING_FIELDS.index("downsample")].text(),
            oddball_marker_code=self.protocol_oddball_marker_code_edit.text(),
            requires_confirmation=bool(
                getattr(self, "_protocol_requires_confirmation", False)
            ),
            condition_oddball_markers_enabled=self.protocol_condition_markers_check.isChecked(),
            condition_oddball_marker_codes=tuple(
                (
                    str(self.protocol_condition_markers_table.item(row, 0).data(Qt.UserRole)),
                    self.protocol_condition_markers_table.item(row, 2).text(),
                )
                for row in range(self.protocol_condition_markers_table.rowCount())
            ),
            recording_oddball_markers_enabled=self.protocol_recording_markers_check.isChecked(),
            recording_oddball_marker_codes=tuple(
                (recording_id, tuple((str(onset), str(marker)) for onset, marker in codes))
                for recording_id, codes in self._recording_marker_codes
            ),
        )

    def _protocol_save_requested(self) -> bool:
        if self._trigger_maps_payload != self._initial_trigger_maps_payload:
            return True
        initial = getattr(
            self,
            "_initial_protocol_editor_values",
            self._protocol_editor_values(),
        )
        return protocol_settings_save_requested(
            initial,
            self._protocol_editor_values(),
            protocol_tab_active=(
                self.tabs.currentIndex() == self._protocol_tab_index
            ),
        )

    def _protocol_from_editor(self, *, require_ready: bool, include_recordings: bool = True) -> FrequencyProtocol:
        values = self._protocol_editor_values()
        protocol = build_manual_protocol(
            presentation_rate_hz=values.presentation_rate_hz,
            oddball_input_mode=values.oddball_input_mode,
            oddball_every_n=values.oddball_every_n,
            oddball_rate_hz=values.entered_oddball_rate_hz,
            expected_analyzed_oddball_cycles=(
                values.expected_analyzed_oddball_cycles
            ),
            analysis_window_mode=values.analysis_window_mode,
            requested_duration_seconds=values.requested_duration_seconds,
            target_sampling_rate_hz=values.target_sampling_rate_hz,
            oddball_marker_code=values.oddball_marker_code,
            existing_protocol=self.project.frequency_protocol,
            require_ready=require_ready,
            condition_oddball_markers_enabled=values.condition_oddball_markers_enabled,
            condition_oddball_marker_codes=values.condition_oddball_marker_codes,
            recording_oddball_markers_enabled=values.recording_oddball_markers_enabled if include_recordings else False,
            recording_oddball_marker_codes=values.recording_oddball_marker_codes if include_recordings else (),
        )
        if self._trigger_maps_payload is not None:
            protocol = protocol.with_condition_trigger_maps(self._trigger_maps_payload)
        return protocol

    def _validate_recording_marker_configuration(self, protocol: FrequencyProtocol) -> None:
        if protocol.condition_trigger_maps is not None:
            from Main_App.projects.condition_trigger_maps import validate_project_trigger_maps
            context = dict(self.project.manifest, frequency_protocol=protocol, event_map={})
            validate_project_trigger_maps(context)
            return
        if protocol.recording_oddball_marker_codes:
            from .recording_marker_schemas import recording_marker_editor_rows, validate_recording_marker_assignments

            validate_recording_marker_assignments(recording_marker_editor_rows(self.project), protocol.recording_oddball_marker_codes)

    def _configure_recording_marker_schemas(self) -> None:
        if self.project is None:
            return
        if self._trigger_maps_payload is not None:
            self._configure_trigger_maps()
            return
        from .recording_marker_schemas import recording_marker_editor_rows
        from .recording_marker_schemas_dialog import RecordingMarkerSchemasDialog

        try:
            template = self._protocol_from_editor(require_ready=False, include_recordings=False)
            onsets = tuple((getattr(self.project, "event_map", {}) or {}).values())
            validate_protocol_condition_codes(template, onsets)
            identities = recording_marker_editor_rows(self.project)
            if not identities:
                raise FrequencyProtocolError("Register the project's recordings before assigning their trigger schemas.")
        except ValueError as exc:
            self.protocol_status.set_variant("warning")
            self.protocol_status.set_text(str(exc))
            self.protocol_status.show()
            return
        dialog = RecordingMarkerSchemasDialog(identities, template, onsets, self._recording_marker_codes, self)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._recording_marker_codes = dialog.marker_codes()
                self._refresh_protocol_preview()
        finally:
            dialog.deleteLater()

    def _configure_trigger_maps(self) -> None:
        if self.project is None:
            return
        from Main_App.gui.trigger_maps_dialog import TriggerMapsDialog
        from Main_App.gui.trigger_maps_model import trigger_map_editor_payload
        from Main_App.gui.toolbox_cache_workflow import _cache_work_is_active
        from Main_App.gui.project_drafts import has_condition_changes
        if _cache_work_is_active(self.host or self):
            self._show_settings_validation("Wait for processing or guided setup to finish before editing trigger maps.")
            return
        if self.host is not None and has_condition_changes(self.host):
            self._show_settings_validation("Save or cancel your Home condition edits before editing trigger maps.")
            return
        try:
            if not self._trigger_protocol_is_current():
                return
            payload = self._trigger_maps_payload
            if payload is None:
                payload = trigger_map_editor_payload(self.project)
            dialog = TriggerMapsDialog(self.project, self, payload=payload, apply_to_settings=True)
        except ValueError as exc:
            self._show_settings_validation(str(exc))
            return
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._trigger_maps_payload = dialog.maps().to_manifest()
                self.protocol_condition_markers_check.setChecked(False)
                self.protocol_recording_markers_check.setChecked(False)
                self._refresh_protocol_preview()
                self._draft_tracker.changed()
        finally:
            dialog.deleteLater()

    def _trigger_protocol_is_current(self) -> bool:
        if self.project is None:
            return True
        baseline = self._trigger_protocol_baseline
        live = (self.project.frequency_protocol.to_manifest(), self.project.event_map)
        try:
            disk = json.loads(self.project.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return live == baseline
        except OSError as exc:
            self._show_settings_validation(str(exc))
            return False
        saved = (disk.get("frequency_protocol"), disk.get("event_map", {}))
        # An inferred legacy protocol may intentionally be absent on disk.
        disk_matches = saved == baseline or (saved[0] is None and not self.project._frequency_protocol_was_persisted and saved[1] == baseline[1])
        if live != baseline or not disk_matches:
            self._show_settings_validation("The project protocol or trigger maps changed. Reopen Settings before saving these edits.")
            return False
        return True

    def _save_project_with_trigger_guard(self) -> None:
        """Keep the trigger baseline check and publication under the same lock."""
        from Main_App.projects.manifest_store import project_manifest_transaction
        with project_manifest_transaction(self.project.manifest_path):
            try:
                disk = json.loads(self.project.manifest_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                disk = None
            if disk is not None:
                saved = (disk.get("frequency_protocol"), disk.get("event_map", {}))
                baseline = self._trigger_protocol_baseline
                legacy_absent = saved[0] is None and baseline[0].get("status") == "confirmation_required" and saved[1] == baseline[1]
                if saved != baseline and not legacy_absent:
                    raise ValueError("The project protocol or trigger maps changed. Reopen Settings before saving these edits.")
            self.project.save()
        self._trigger_protocol_baseline = (self.project.frequency_protocol.to_manifest(), copy.deepcopy(self.project.event_map))

    def _refresh_protocol_preview(self, *_args: object) -> None:
        analysis_mode = str(self.protocol_analysis_window_mode_combo.currentData())
        self._protocol_form.setRowVisible(self.protocol_expected_cycles_edit, analysis_mode == ANALYSIS_WINDOW_MODE_CYCLES)
        self._protocol_form.setRowVisible(self.protocol_requested_duration_edit, analysis_mode == ANALYSIS_WINDOW_MODE_DURATION)
        recording_markers = self.protocol_recording_markers_check.isChecked()
        source_maps = self._trigger_maps_payload is not None
        self.protocol_recording_markers_row.setVisible(recording_markers and not source_maps)
        self.protocol_recording_markers_summary.setText(f"{len(self._recording_marker_codes)} recording schemas configured.")
        condition_markers = self.protocol_condition_markers_check.isChecked()
        self.protocol_condition_markers_table.setVisible(condition_markers and not source_maps)
        self.protocol_oddball_marker_code_edit.setEnabled(self.project is not None and not condition_markers and not source_maps)
        self._protocol_markers_form.setRowVisible(self.protocol_oddball_marker_code_edit, not source_maps)
        self.protocol_condition_markers_check.setVisible(not source_maps)
        self.protocol_recording_markers_check.setVisible(not source_maps)
        self.protocol_marker_code_help.setVisible(not source_maps)
        self.protocol_trigger_maps_button.setText("Trigger maps…" if source_maps else "Use source maps…")
        self.protocol_marker_code_help.setText(
            "Enter the oddball marker emitted in each condition. Every condition needs a value; "
            "turn off this option to use the shared code above."
            if condition_markers else
            "Oddball marker code: Event code emitted for each oddball in every condition. Default: 55."
        )
        if self.project is None:
            self.protocol_resolved_oddball_rate_edit.setText("—")
            self.protocol_derived_duration_edit.setText("Open a project to edit")
            self.protocol_status.set_variant("info")
            self.protocol_status.set_text(
                "FPVS protocol values belong to the active project. Open a project "
                "to view or edit them."
            )
            self.protocol_status.setVisible(True)
            return

        direct_mode = self._protocol_input_mode() == ODDBALL_INPUT_MODE_DIRECT_HZ
        self.protocol_oddball_every_n_edit.setEnabled(not direct_mode)
        self.protocol_direct_oddball_rate_edit.setEnabled(direct_mode)
        try:
            protocol = self._protocol_from_editor(require_ready=False)
            validate_protocol_condition_codes(
                protocol,
                (getattr(self.project, "event_map", {}) or {}).values(),
            )
            self._validate_recording_marker_configuration(protocol)
        except ValueError as exc:
            self.protocol_resolved_oddball_rate_edit.setText("Invalid protocol")
            self.protocol_derived_duration_edit.setText("—")
            self.protocol_status.set_variant("warning")
            self.protocol_status.set_text(str(exc))
            self.protocol_status.setVisible(True)
            return

        if direct_mode and protocol.oddball_every_n is not None:
            previous = self.protocol_oddball_every_n_edit.blockSignals(True)
            self.protocol_oddball_every_n_edit.setText(str(protocol.oddball_every_n))
            self.protocol_oddball_every_n_edit.blockSignals(previous)
        elif protocol.oddball_rate_hz is not None:
            canonical_rate_text = protocol.to_manifest()["oddball_rate_hz"]
            previous = self.protocol_direct_oddball_rate_edit.blockSignals(True)
            self.protocol_direct_oddball_rate_edit.setText(
                str(canonical_rate_text or "")
            )
            self.protocol_direct_oddball_rate_edit.blockSignals(previous)
        self.protocol_resolved_oddball_rate_edit.setText(
            rate_summary(protocol.oddball_rate_hz)
        )
        self.protocol_derived_duration_edit.setText(
            duration_summary(protocol.derived_analyzed_seconds)
        )
        if analysis_mode != ANALYSIS_WINDOW_MODE_CYCLES:
            previous = self.protocol_expected_cycles_edit.blockSignals(True)
            self.protocol_expected_cycles_edit.setText(str(protocol.expected_analyzed_oddball_cycles or ""))
            self.protocol_expected_cycles_edit.blockSignals(previous)
        if analysis_mode == ANALYSIS_WINDOW_MODE_STUDIO:
            previous = self.protocol_requested_duration_edit.blockSignals(True)
            self.protocol_requested_duration_edit.setText(editor_values_for_protocol(protocol).requested_duration_seconds)
            self.protocol_requested_duration_edit.blockSignals(previous)
        if getattr(self, "_protocol_requires_confirmation", False):
            self.protocol_status.set_variant("warning")
            if protocol.expected_analyzed_oddball_cycles is None:
                self.protocol_status.set_text(
                    "Review the retained or proposed protocol, choose an analysis "
                    "duration or advanced cycle count, then save from Protocol to confirm it."
                )
            else:
                self.protocol_status.set_text(
                    "Review the retained protocol and proposed oddball marker code, "
                    "then save from Protocol to confirm them."
                )
        elif not protocol.is_ready:
            self.protocol_status.set_variant("warning")
            self.protocol_status.set_text(
                "Enter the intended analysis duration before processing, or choose an advanced cycle count."
            )
        else:
            self.protocol_status.set_variant("success")
            markers = (
                f"{len(protocol.condition_trigger_maps.profiles)} source trigger maps"
                if protocol.condition_trigger_maps is not None else
                f"{len(protocol.recording_oddball_marker_codes)} recording-specific trigger schemas"
                if protocol.recording_oddball_marker_codes else
                f"{len(protocol.condition_oddball_marker_codes)} condition-specific oddball markers"
                if protocol.condition_oddball_marker_codes else
                f"oddball marker code {protocol.oddball_marker_code}"
            )
            self.protocol_status.set_text(
                f"Every {protocol.oddball_every_n} stimuli; {markers}; ready to save for this project."
            )
        self.protocol_status.setVisible(True)

    def _validated_project_protocol(self) -> FrequencyProtocol | None:
        if self.project is None:
            return None
        try:
            protocol = self._protocol_from_editor(require_ready=True)
            validate_protocol_condition_codes(
                protocol,
                (getattr(self.project, "event_map", {}) or {}).values(),
            )
            self._validate_recording_marker_configuration(protocol)
            return protocol
        except ValueError as exc:
            self._show_settings_validation(str(exc))
            message = str(exc).casefold()
            if "target sampling rate" in message:
                self.tabs.setCurrentIndex(self._preproc_tab_index)
                field = self.preproc_edits[PREPROCESSING_FIELDS.index("downsample")]
                mark_invalid(field, str(exc))
                field.setFocus()
                field.selectAll()
                return None
            self.tabs.setCurrentIndex(self._protocol_tab_index)
            controls = (
                (("presentation", "base"), self.protocol_presentation_rate_edit),
                (("duration",), self.protocol_requested_duration_edit),
                (("cycle",), self.protocol_expected_cycles_edit),
                (("marker", "code"), self.protocol_oddball_marker_code_edit),
            )
            field = next(
                (edit for terms, edit in controls if any(term in message for term in terms)),
                self.protocol_direct_oddball_rate_edit
                if self._protocol_input_mode() == ODDBALL_INPUT_MODE_DIRECT_HZ
                else self.protocol_oddball_every_n_edit,
            )
            self.protocol_tabs.setCurrentIndex(
                1 if field is self.protocol_oddball_marker_code_edit else 0
            )
            mark_invalid(field, str(exc))
            field.setFocus()
            field.selectAll()
            return None

    def _project_protocol_signature(self) -> object:
        if self.project is None:
            return None
        try:
            return self._protocol_from_editor(require_ready=False).fingerprint
        except FrequencyProtocolError:
            return (
                self.protocol_presentation_rate_edit.text().strip(),
                self._protocol_input_mode(),
                self.protocol_oddball_every_n_edit.text().strip(),
                self.protocol_direct_oddball_rate_edit.text().strip(),
                self.protocol_expected_cycles_edit.text().strip(),
                self.protocol_analysis_window_mode_combo.currentData(),
                self.protocol_requested_duration_edit.text().strip(),
                self.protocol_oddball_marker_code_edit.text().strip(),
                self.protocol_condition_markers_check.isChecked(),
                self._protocol_editor_values().condition_oddball_marker_codes,
                self.protocol_recording_markers_check.isChecked(),
                self._protocol_editor_values().recording_oddball_marker_codes,
            )

    def _harmonic_settings_signature_from_settings(self, settings: Any) -> tuple[object, ...]:
        return (
            settings.name,
            str(settings.harmonic_selection_profile),
            str(settings.harmonic_selection_profile_version),
            str(settings.group_significant_electrode_scope),
            tuple(settings.group_significant_selection_electrodes),
            str(settings.group_significant_summation_method),
            str(settings.fixed_harmonic_input_mode),
            str(settings.fixed_harmonic_frequencies_hz).strip(),
            settings.fixed_harmonic_upper_harmonic_index,
            settings.fixed_harmonic_upper_frequency_hz,
            bool(settings.fixed_harmonic_auto_exclude_base),
        )

    def _harmonic_settings_signature_from_preprocessing(
        self,
        preprocessing: Dict[str, Any],
        *,
        roi_pairs_override: list[tuple[str, list[str]]] | None = None,
    ) -> tuple[object, ...]:
        settings = normalize_dv_policy(
            self._harmonic_policy_payload_from_preprocessing(preprocessing)
        )
        return (
            *self._harmonic_settings_signature_from_settings(settings),
            self._roi_settings_signature(roi_pairs_override),
        )

    def _roi_settings_signature(
        self, roi_pairs_override: list[tuple[str, list[str]]] | None = None,
    ) -> tuple[object, ...]:
        roi_pairs = roi_pairs_override
        if roi_pairs is None:
            roi_pairs = (
                self.roi_editor.get_pairs()
                if hasattr(self, "roi_editor")
                else self.manager.get_roi_pairs()
            )
        return tuple(
            (
                str(name).strip(),
                tuple(str(electrode).strip().upper() for electrode in electrodes),
            )
            for name, electrodes in roi_pairs
        )

    @staticmethod
    def _normalized_signature_number(value: object) -> object:
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value).strip()

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
            record.path.stem.casefold().endswith("_results")
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

    def _frequency_analysis_settings_signature(
        self, *, roi_pairs_override: list[tuple[str, list[str]]] | None = None,
    ) -> tuple[object, ...]:
        # Cohort-relative QC uses ROI membership even when the selection
        # profile uses all electrodes. Rebuild QC before selecting harmonics.
        return (
            self._project_protocol_signature(),
            self._roi_settings_signature(roi_pairs_override),
        )

    def _frequency_analysis_settings_changed_after_processing(self) -> bool:
        if self.project is None or not self._project_has_processed_outputs():
            return False
        initial = getattr(self, "_initial_frequency_analysis_signature", None)
        return (
            initial is not None
            and self._frequency_analysis_settings_signature() != initial
        )

    def _project_protocol_changed_after_processing(self) -> bool:
        if self.project is None or not self._project_has_processed_outputs():
            return False
        initial = getattr(self, "_initial_frequency_analysis_signature", None)
        return (
            initial is not None
            and self._project_protocol_signature() != initial[0]
        )

    def _experimental_qc_changes_after_processing(
        self, settings: ExperimentalQcSettings | None,
    ) -> tuple[bool, bool]:
        if self.project is None or settings is None or not self._project_has_processed_outputs():
            return False, False
        previous = self.project.experimental_qc_settings
        preprocessing_changed = (
            previous.raw_signal_screening_enabled != settings.raw_signal_screening_enabled
            or previous.kurtosis_screening_enabled != settings.kurtosis_screening_enabled
            or previous.raw_spectral_screening != settings.raw_spectral_screening
        )
        postprocessing_changed = (
            previous.summed_bca_screening != settings.summed_bca_screening
            or previous.interpolation_burden_review_enabled != settings.interpolation_burden_review_enabled
        )
        return preprocessing_changed, postprocessing_changed

    def _ask_recalculate_harmonics_after_settings_change(self) -> bool:
        choice = QMessageBox.question(
            self,
            "Recalculate Harmonics?",
            (
                "This project already has processed data, and settings that define "
                "harmonic selection or Summed BCA were changed. Rebuild the affected "
                "post-processing outputs now? Raw EEG preprocessing and FFT export "
                "will not be rerun."
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

    def _show_harmonic_method_info(self) -> None:
        profile_id = self.harmonic_summation_method_combo.currentData()
        show_tool_info(self, HARMONIC_METHOD_INFO[profile_id])

    def _fixed_harmonic_list_selected(self) -> bool:
        return (
            self.harmonic_summation_method_combo.currentData()
            == HARMONIC_PROFILE_FIXED_ID
        )

    def _update_harmonic_selection_controls(self) -> None:
        fixed_selected = self._fixed_harmonic_list_selected()
        profile_id = self.harmonic_summation_method_combo.currentData()
        legacy_selected = profile_id == HARMONIC_PROFILE_LEGACY_ID
        self.harmonic_electrode_scope_combo.setEnabled(not fixed_selected)
        if (
            not fixed_selected
            and not legacy_selected
            and self.harmonic_electrode_scope_combo.currentData()
            == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION
        ):
            all_index = self.harmonic_electrode_scope_combo.findData(
                GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL
            )
            self.harmonic_electrode_scope_combo.setCurrentIndex(all_index)
        frozen_selected = (
            not fixed_selected
            and self.harmonic_electrode_scope_combo.currentData()
            == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN
        )
        self.harmonic_selection_electrodes_edit.setEnabled(frozen_selected)

        self.fixed_harmonic_input_mode_combo.setEnabled(fixed_selected)
        fixed_mode = self.fixed_harmonic_input_mode_combo.currentData()
        self.fixed_harmonic_freqs_edit.setEnabled(
            fixed_selected and fixed_mode == FIXED_HARMONIC_INPUT_FREQUENCY_LIST
        )
        self.fixed_harmonic_upper_index_edit.setEnabled(
            fixed_selected and fixed_mode == FIXED_HARMONIC_INPUT_UPPER_HARMONIC
        )
        self.fixed_harmonic_upper_frequency_edit.setEnabled(
            fixed_selected and fixed_mode == FIXED_HARMONIC_INPUT_UPPER_FREQUENCY
        )
        self.fixed_harmonic_exclude_base_check.setEnabled(False)
        if profile_id == HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID:
            note = (
                "Include harmonics up to the cutoff before two consecutive "
                "nonsignificant results."
            )
            variant = "success"
        elif profile_id == HARMONIC_PROFILE_FIXED_ID:
            note = (
                "Choose the harmonic selection independently of this dataset. "
                "Frequencies overlapping the base rate are excluded."
            )
            variant = "info"
        elif profile_id == HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID:
            note = (
                "Include only harmonics detected above noise. Treat findings from "
                "this selection as exploratory."
            )
            variant = "warning"
        else:
            note = (
                "Preserve the selection used by older Toolbox projects, including "
                "its isolated-peak rule."
            )
            variant = "warning"
        self.fixed_harmonic_warning.set_variant(variant)
        self.fixed_harmonic_warning.set_text(note)
        self.fixed_harmonic_warning.setVisible(True)

    def _save_project_preprocessing_for_harmonic_recalculation(
        self,
        validated_preproc: Dict[str, Any],
    ) -> bool:
        if not self._trigger_protocol_is_current():
            return False
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
            self._sync_electrode_geometry_controls(saved=True)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            return False
        except Exception as exc:  # pragma: no cover - disk I/O error path
            QMessageBox.critical(self, "Save Error", str(exc))
            return False
        return True

    def _save_analysis_inputs_for_harmonic_recalculation(self) -> bool:
        """Persist every non-project input consumed by harmonic selection."""
        if not self._trigger_protocol_is_current():
            return False
        if self._trigger_maps_payload != self._initial_trigger_maps_payload:
            self._show_settings_validation("Save trigger-map edits in Settings and run Processing before recalculating harmonics.")
            return False
        if not self._validate_roi_draft():
            return False
        protocol = None
        if self.project is not None:
            if self._protocol_save_requested():
                protocol = self._validated_project_protocol()
                if protocol is None:
                    return False
            else:
                protocol = self.project.frequency_protocol
                if not protocol.is_ready:
                    QMessageBox.warning(
                        self,
                        "FPVS Protocol Required",
                        "Confirm the project FPVS protocol in Settings > Protocol "
                        "before recalculating harmonics.",
                    )
                    self.tabs.setCurrentIndex(self._protocol_tab_index)
                    return False
        try:
            self.manager.set_roi_montage(self._current_roi_montage())
            self.manager.set_roi_pairs(self.roi_editor.get_pairs())
            self.manager.save()
            if self.project is not None and protocol is not None:
                self.project.update_frequency_protocol(protocol)
                self.project.save()
        except Exception as exc:  # pragma: no cover - settings I/O failure
            QMessageBox.critical(self, "Save Error", str(exc))
            return False
        self._refresh_roi_consumers()
        return True

    def _refresh_roi_consumers(self) -> None:
        """Refresh committed ROI state in compatibility modules and cached pages."""

        try:
            from Tools.Stats.data.shared_rois import (
                apply_rois_to_modules,
                load_rois_from_settings,
            )

            apply_rois_to_modules(load_rois_from_settings(self.manager))
        except Exception:  # Consumer boundary: committed settings remain authoritative.
            logger.exception("roi_compatibility_module_refresh_failed")

        host = getattr(self, "host", None) or self.parent()
        if host is None:
            return
        for page_attribute, pass_manager in (
            ("_stats_page", False),
            ("_plot_generator_page", True),
        ):
            page = getattr(host, page_attribute, None)
            refresh_rois = getattr(page, "refresh_rois", None)
            if not callable(refresh_rois):
                continue
            try:
                if pass_manager:
                    refresh_rois(self.manager)
                else:
                    refresh_rois()
            except Exception:  # Cached-page boundary: refresh failures stay isolated.
                logger.exception(
                    "roi_cached_consumer_refresh_failed",
                    extra={"consumer": page_attribute},
                )

    def _capture_harmonic_settings_rollback(self) -> None:
        """Snapshot settings that must survive a cancelled FFT-grid review."""

        if self.project is None or hasattr(self, "_harmonic_settings_rollback"):
            return
        self._harmonic_settings_rollback = {
            "preprocessing": copy.deepcopy(self.project.preprocessing),
            "frequency_protocol": self.project.frequency_protocol,
            "manager_config": copy.deepcopy(self.manager.config),
            "project_cache": copy.deepcopy(self._project_cache),
            "manual_excluded_participant_conditions": copy.deepcopy(
                self._manual_excluded_participant_conditions
            ),
            "manual_excluded_recording_conditions": copy.deepcopy(
                self._manual_excluded_recording_conditions
            ),
        }

    def _clear_harmonic_settings_rollback(self) -> None:
        if hasattr(self, "_harmonic_settings_rollback"):
            del self._harmonic_settings_rollback

    def _restore_harmonic_settings_after_cancel(self) -> None:
        snapshot = getattr(self, "_harmonic_settings_rollback", None)
        if not isinstance(snapshot, dict):
            return
        restore_errors: list[str] = []
        try:
            if self.project is not None:
                try:
                    preprocessing = copy.deepcopy(snapshot["preprocessing"])
                    self.project.update_preprocessing(preprocessing)
                    self.project.update_frequency_protocol(
                        snapshot["frequency_protocol"]
                    )
                    self.project.save()
                    self._project_cache = copy.deepcopy(snapshot["project_cache"])
                    self._manual_excluded_participant_conditions = copy.deepcopy(
                        snapshot["manual_excluded_participant_conditions"]
                    )
                    self._manual_excluded_recording_conditions = copy.deepcopy(
                        snapshot["manual_excluded_recording_conditions"]
                    )
                except Exception as exc:  # pragma: no cover - disk I/O failure
                    restore_errors.append(f"project settings ({exc})")
            try:
                self.manager.config = copy.deepcopy(snapshot["manager_config"])
                self.manager.save()
                self.roi_editor.set_pairs(self.manager.get_roi_pairs())
            except Exception as exc:  # pragma: no cover - settings I/O failure
                restore_errors.append(f"application analysis settings ({exc})")
            self._refresh_roi_consumers()
        finally:
            self._clear_harmonic_settings_rollback()
        if restore_errors:
            logger.error(
                "harmonic_settings_rollback_failed project_root=%r errors=%r",
                str(getattr(self.project, "project_root", "") or ""),
                restore_errors,
            )
            QMessageBox.critical(
                self,
                "Settings Restore Failed",
                "The previous settings could not be restored completely: "
                + "; ".join(restore_errors),
            )

    def _mark_harmonic_derivatives_stale(self) -> None:
        if self.project is None:
            return
        from Main_App.processing.artifact_freshness import (
            mark_selection_derivatives_stale,
        )

        mark_selection_derivatives_stale(
            self.project.project_root,
            reason=(
                "Harmonic-selection or Summed-BCA analysis settings changed; "
                "recalculate harmonics before using dependent outputs."
            ),
        )

    def _mark_frequency_analysis_outputs_stale(self) -> None:
        if self.project is None:
            return
        from Main_App.processing.frequency_domain_qc import (
            mark_frequency_domain_outputs_stale,
        )

        mark_frequency_domain_outputs_stale(
            self.project.project_root,
            reason=(
                "The project protocol, QC settings, or ROI definitions changed; "
                "refresh processing and QC before using dependent outputs."
            ),
        )

    def _resume_frequency_domain_post_processing(self, *, all_settings_saved: bool = False) -> None:
        host = getattr(self, "host", None) or self.parent()
        if host is None:
            return
        from Main_App.gui.processing_workflows import resume_post_processing

        if self._settings_post_processing_activity_is_active():
            self._handoff_settings_activity_to_frequency_post_processing()
            if all_settings_saved:
                self._settings_save_completed()
        elif all_settings_saved:
            self.accept()
        # Recalculate saves its own inputs only. Keep unrelated Settings drafts
        # in their cached page while processing, rather than discarding them.
        resume_post_processing(host)

    def _on_recalculate_harmonics_clicked(self) -> None:
        validated_preproc = self._validated_preproc_payload()
        if validated_preproc is None:
            return
        if self._project_protocol_changed_after_processing():
            QMessageBox.warning(
                self,
                "Project Reprocessing Required",
                "Presentation rate, oddball recurrence or rate, expected analyzed "
                "cycles, or the oddball marker code changed. Save Settings, then "
                "reprocess the project so crops and FFT outputs use the confirmed "
                "protocol.",
            )
            return
        frequency_analysis_changed = (
            self._frequency_analysis_settings_changed_after_processing()
        )
        self._capture_harmonic_settings_rollback()
        if not self._save_project_preprocessing_for_harmonic_recalculation(validated_preproc):
            self._restore_harmonic_settings_after_cancel()
            return
        if not self._save_analysis_inputs_for_harmonic_recalculation():
            self._restore_harmonic_settings_after_cancel()
            return
        if not self._project_has_processed_outputs():
            self._restore_harmonic_settings_after_cancel()
            QMessageBox.information(
                self,
                "No Processed Data",
                "Process this project before recalculating harmonic selection.",
            )
            return
        if frequency_analysis_changed:
            try:
                self._mark_frequency_analysis_outputs_stale()
            except (OSError, RuntimeError, ValueError) as exc:
                QMessageBox.warning(
                    self,
                    "Freshness Status Warning",
                    f"Frequency-domain outputs could not be marked stale: {exc}",
                )
                self._restore_harmonic_settings_after_cancel()
                return
            self._clear_harmonic_settings_rollback()
            self._resume_frequency_domain_post_processing()
            return
        if not self._start_full_fft_grid_review(recalculate_after=True):
            self._restore_harmonic_settings_after_cancel()

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
        *,
        recording_exclusions: Dict[str, Any] | None = None,
        invalidate_outputs: bool = True,
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
        current_recordings = normalize_manual_excluded_recording_conditions(
            self.project.preprocessing.get(
                "manual_excluded_recording_conditions",
                {},
            )
        )
        normalized_recordings = (
            current_recordings
            if recording_exclusions is None
            else normalize_manual_excluded_recording_conditions(
                recording_exclusions
            )
        )
        if (
            normalized_exclusions == current
            and normalized_recordings == current_recordings
        ):
            self._manual_excluded_participant_conditions = normalized_exclusions
            self._manual_excluded_recording_conditions = normalized_recordings
            return True
        updated_preproc = dict(self.project.preprocessing)
        updated_preproc["manual_excluded_participant_conditions"] = (
            normalized_exclusions
        )
        updated_preproc["manual_excluded_recording_conditions"] = (
            normalized_recordings
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
        self._manual_excluded_recording_conditions = dict(
            normalized.get("manual_excluded_recording_conditions") or {}
        )
        if not invalidate_outputs:
            return True
        invalidation_warnings: list[str] = []
        try:
            mark_frequency_domain_outputs_stale(
                self.project.project_root,
                reason="Participant/recording-condition FFT crop exclusions changed.",
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

    def _lock_settings_navigation(self) -> None:
        owner = getattr(self, "host", None)
        if owner is None or owner is self:
            return
        if getattr(owner, "_settings_worker_navigation_locked", False):
            return
        from Main_App.gui import shell_status

        shell_status._set_processing_navigation_locked(owner, True)
        owner._settings_worker_navigation_locked = True

    def _settings_post_processing_activity_is_active(self) -> bool:
        owner = getattr(self, "host", None)
        if owner is None or owner is self:
            return False
        return bool(
            getattr(owner, "_settings_post_processing_activity_active", False)
        )

    def _begin_settings_post_processing_activity(self) -> bool:
        """Show the shared processing page for a Save-triggered rebuild."""

        owner = getattr(self, "host", None)
        if owner is None or owner is self:
            return False
        if self._settings_post_processing_activity_is_active():
            return True
        workspace = getattr(owner, "workspace_stack", None)
        processing_page = getattr(owner, "processing_page", None)
        if workspace is None or processing_page is None:
            return False
        try:
            if workspace.currentWidget() is not self:
                return False
        except RuntimeError:
            return False

        from Main_App.gui import shell_status

        start_button = getattr(owner, "btn_start", None)
        if start_button is not None:
            owner._settings_post_processing_start_button_state = (
                start_button.text(),
                start_button.isEnabled(),
            )
        shell_status.prepare_post_processing_activity(owner)
        owner._settings_post_processing_busy_state = bool(
            getattr(owner, "busy", False)
        )
        owner.busy = True
        owner._settings_post_processing_activity_active = True
        shell_status.show_processing_page(owner)
        if start_button is not None:
            start_button.setText("Post-processing in progress")
            start_button.setEnabled(False)

        self._set_settings_post_processing_stage(
            title="Checking Processed FFT Grids",
            message=(
                "FPVS Toolbox is checking existing FullFFT workbooks before "
                "recalculating harmonics."
            ),
            step="Preparing harmonic recalculation",
            indeterminate=True,
        )
        return True

    def _set_settings_post_processing_stage(
        self,
        *,
        title: str,
        message: str,
        step: str,
        indeterminate: bool = False,
    ) -> None:
        owner = getattr(self, "host", None)
        if owner is None or not self._settings_post_processing_activity_is_active():
            return
        title_label = getattr(owner, "processing_title_label", None)
        if title_label is not None:
            title_label.setText(title)
        message_label = getattr(owner, "processing_message_label", None)
        if message_label is not None:
            message_label.setText(message)
        step_label = getattr(owner, "processing_step_label", None)
        if step_label is not None:
            step_label.setText(step)
            step_label.setVisible(True)
        if not indeterminate:
            return
        progress_animation = getattr(owner, "_progress_anim", None)
        if progress_animation is not None:
            progress_animation.stop()
        progress_bar = getattr(owner, "progress_bar", None)
        if progress_bar is not None:
            progress_bar.setRange(0, 0)
            progress_bar.setVisible(True)

    def _finish_settings_post_processing_activity(
        self,
        *,
        return_home: bool,
    ) -> None:
        owner = getattr(self, "host", None)
        if owner is None or not self._settings_post_processing_activity_is_active():
            return
        from Main_App.gui import shell_status

        if return_home:
            owner._processing_return_widget = getattr(owner, "homeWidget", None)
        shell_status.hide_processing_page(owner)
        owner._settings_post_processing_activity_active = False
        start_button = getattr(owner, "btn_start", None)
        start_state = getattr(
            owner,
            "_settings_post_processing_start_button_state",
            None,
        )
        if start_button is not None and isinstance(start_state, tuple):
            start_button.setText(str(start_state[0]))
            start_button.setEnabled(bool(start_state[1]))
        if hasattr(owner, "_settings_post_processing_start_button_state"):
            del owner._settings_post_processing_start_button_state
        owner.busy = bool(
            getattr(owner, "_settings_post_processing_busy_state", False)
        )
        if hasattr(owner, "_settings_post_processing_busy_state"):
            del owner._settings_post_processing_busy_state
        if return_home:
            self.accept()

    def _finish_settings_post_processing_activity_when_idle(
        self,
        *,
        return_home: bool | None = None,
    ) -> None:
        """Finish the shared activity only after both Settings workers release."""

        owner = getattr(self, "host", None) or self
        if return_home is not None:
            owner._settings_post_processing_pending_return_home = bool(return_home)
        if getattr(owner, "_settings_full_fft_grid_qc_thread", None) is not None:
            return
        if getattr(owner, "_settings_harmonic_recalc_thread", None) is not None:
            return
        pending = getattr(
            owner,
            "_settings_post_processing_pending_return_home",
            None,
        )
        if hasattr(owner, "_settings_post_processing_pending_return_home"):
            del owner._settings_post_processing_pending_return_home
        if pending is not None:
            if self._settings_post_processing_activity_is_active():
                self._finish_settings_post_processing_activity(
                    return_home=bool(pending),
                )
            elif pending:
                self.accept()

    def _handoff_settings_activity_to_frequency_post_processing(self) -> None:
        owner = getattr(self, "host", None)
        if owner is None or not self._settings_post_processing_activity_is_active():
            return
        refresh_host = getattr(self, "_refresh_host_settings_indicators", None)
        if callable(refresh_host):
            refresh_host()
        owner._processing_return_widget = getattr(owner, "homeWidget", None)
        owner._settings_post_processing_activity_active = False
        if hasattr(owner, "_settings_post_processing_pending_return_home"):
            del owner._settings_post_processing_pending_return_home
        if hasattr(owner, "_settings_post_processing_busy_state"):
            del owner._settings_post_processing_busy_state
        if hasattr(owner, "_settings_post_processing_start_button_state"):
            del owner._settings_post_processing_start_button_state

    def _unlock_settings_navigation_if_idle(self) -> None:
        owner = getattr(self, "host", None)
        if owner is None or owner is self:
            return
        if getattr(owner, "_settings_full_fft_grid_qc_thread", None) is not None:
            return
        if getattr(owner, "_settings_harmonic_recalc_thread", None) is not None:
            return
        if not getattr(owner, "_settings_worker_navigation_locked", False):
            return
        from Main_App.gui import shell_status

        shell_status._set_processing_navigation_locked(owner, False)
        owner._settings_worker_navigation_locked = False

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

        try:
            thread = QThread(owner)
            worker = FullFftGridQcWorker(self.project.project_root)
            worker.moveToThread(thread)
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
        owner._settings_full_fft_grid_qc_thread = thread
        owner._settings_full_fft_grid_qc_worker = worker
        self._lock_settings_navigation()
        resume_frequency_postprocessing_after_release = False
        frequency_postprocessing_resume_started = False
        activity_handed_off = False

        def _resume_frequency_postprocessing_once() -> None:
            nonlocal frequency_postprocessing_resume_started
            if frequency_postprocessing_resume_started:
                return
            frequency_postprocessing_resume_started = True
            self._resume_frequency_domain_post_processing(all_settings_saved=accept_on_success)

        def _release_worker() -> None:
            owner._settings_full_fft_grid_qc_thread = None
            owner._settings_full_fft_grid_qc_worker = None
            owner._settings_full_fft_grid_qc_bridge = None
            if getattr(owner, "_settings_harmonic_recalc_thread", None) is None:
                self._set_full_fft_grid_review_controls_enabled(True)
            self._unlock_settings_navigation_if_idle()
            if resume_frequency_postprocessing_after_release:
                _resume_frequency_postprocessing_once()
            elif accept_on_success:
                self._finish_settings_post_processing_activity_when_idle(
                    return_home=False if not activity_handed_off else None,
                )

        def _handle_finished(audit: object) -> None:
            nonlocal activity_handed_off
            nonlocal resume_frequency_postprocessing_after_release
            candidates = tuple(getattr(audit, "review_candidates", ()) or ())
            missing_outputs = tuple(getattr(audit, "missing_condition_outputs", ()) or ())
            should_open = (
                bool(candidates)
                or bool(missing_outputs)
                or bool(
                    getattr(audit, "has_unresolved_grid_conflict", False)
                )
                or not recalculate_after
            )
            recording_review = any(
                str(getattr(observation, "recording_id", "") or "").strip()
                for observation in (
                    (*missing_outputs, *getattr(audit, "observations", ())) or candidates
                )
            )
            accepted = True
            current_exclusions = normalize_manual_excluded_participant_conditions(
                self._manual_excluded_participant_conditions
            )
            current_recording_exclusions = (
                normalize_manual_excluded_recording_conditions(
                    self._manual_excluded_recording_conditions
                )
            )
            proposed_exclusions = current_exclusions
            proposed_recording_exclusions = current_recording_exclusions
            if should_open:
                if recording_review:
                    dialog = ParticipantConditionExclusionsDialog(
                        audit,
                        self._manual_excluded_participant_conditions,
                        self,
                        excluded_recording_conditions=(
                            self._manual_excluded_recording_conditions
                        ),
                    )
                else:
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
                    if recording_review:
                        proposed_recording_exclusions = (
                            dialog.excluded_recording_conditions()
                        )
            if not accepted:
                self._restore_harmonic_settings_after_cancel()
                self._set_harmonic_recalculation_status(
                    "FFT crop exclusion review was cancelled.",
                    "warning",
                )
                return
            needs_processing = any(row.requires_processing for row in missing_outputs) or (
                missing_output_exclusions_changed(
                    missing_outputs,
                    current_exclusions, proposed_exclusions,
                    current_recording_exclusions, proposed_recording_exclusions,
                )
            )
            if recalculate_after and not needs_processing:
                compatible = (
                    audit.is_compatible_with_exclusions(
                        proposed_exclusions,
                        recording_exclusions=proposed_recording_exclusions,
                    )
                    if recording_review
                    else audit.is_compatible_with_exclusions(
                        proposed_exclusions
                    )
                )
                if not compatible:
                    self._restore_harmonic_settings_after_cancel()
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
            normalized_proposed = normalize_manual_excluded_participant_conditions(
                proposed_exclusions
            )
            normalized_recording_proposed = (
                normalize_manual_excluded_recording_conditions(
                    proposed_recording_exclusions
                )
            )
            exclusions_changed = (
                normalized_proposed != current_exclusions
                or normalized_recording_proposed != current_recording_exclusions
            )
            if exclusions_changed and not self._save_participant_condition_exclusions(
                normalized_proposed,
                recording_exclusions=normalized_recording_proposed,
                invalidate_outputs=True,
            ):
                self._restore_harmonic_settings_after_cancel()
                return
            if needs_processing:
                self._clear_harmonic_settings_rollback()
                self._set_harmonic_recalculation_status(
                    (
                        "Condition exclusions saved. Rerun Processing after restoring "
                        "missing condition data or confirming its exclusion."
                        if exclusions_changed else
                        "Missing condition inputs still need review. Restore complete source "
                        "data or explicitly exclude those conditions, then rerun Processing."
                    ),
                    "warning",
                )
                return
            if recalculate_after:
                if exclusions_changed:
                    # The active FullFFT cohort changed, so neutral FullFFT
                    # provenance and frequency-domain QC must be rebuilt too.
                    self._clear_harmonic_settings_rollback()
                    resume_frequency_postprocessing_after_release = True
                    activity_handed_off = True
                    if (
                        getattr(owner, "_settings_full_fft_grid_qc_thread", None)
                        is None
                    ):
                        _resume_frequency_postprocessing_once()
                    return
                if self._start_harmonic_recalculation(
                    accept_on_success=accept_on_success
                ):
                    activity_handed_off = True
                else:
                    self._restore_harmonic_settings_after_cancel()
            else:
                self._set_harmonic_recalculation_status(
                    "Participant-condition exclusions saved. Recalculate harmonics "
                    "to rebuild the project-wide selection.",
                    "success",
                )

        def _handle_failed(message: str) -> None:
            self._restore_harmonic_settings_after_cancel()
            self._set_harmonic_recalculation_status(
                f"FFT grid check failed: {message}",
                "warning",
            )
            QMessageBox.warning(self, "FFT Grid Check Failed", message)

        bridge = _SettingsWorkerUiBridge(
            result_callback=_handle_finished,
            failed_callback=_handle_failed,
            thread_finished_callback=_release_worker,
            parent=owner,
        )
        owner._settings_full_fft_grid_qc_bridge = bridge
        try:
            thread.started.connect(worker.run)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            worker.finished.connect(bridge.handle_result)
            worker.failed.connect(thread.quit)
            worker.failed.connect(worker.deleteLater)
            worker.failed.connect(bridge.handle_failed)
            thread.finished.connect(bridge.handle_thread_finished)
            thread.finished.connect(thread.deleteLater)
            thread.start()
        except Exception as exc:  # noqa: BLE001
            owner._settings_full_fft_grid_qc_thread = None
            owner._settings_full_fft_grid_qc_worker = None
            owner._settings_full_fft_grid_qc_bridge = None
            self._set_full_fft_grid_review_controls_enabled(True)
            self._unlock_settings_navigation_if_idle()
            for obj in (worker, bridge, thread):
                try:
                    obj.deleteLater()
                except RuntimeError:
                    pass
            QMessageBox.warning(
                self,
                "FFT Grid Check Unavailable",
                f"The FFT grid check could not start: {exc}",
            )
            return False
        if accept_on_success:
            try:
                self._begin_settings_post_processing_activity()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "settings_post_processing_activity_presentation_failed"
                )
                self._set_harmonic_recalculation_status(
                    "The FFT grid check is still running in the background; "
                    "progress could not be shown on the processing page.",
                    "warning",
                )
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

        try:
            thread = QThread(owner)
            worker = ProcessingHarmonicSelectionWorker(self.project)
            worker.moveToThread(thread)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self,
                "Recalculation Unavailable",
                f"Harmonic recalculation could not start: {exc}",
            )
            return False

        self._set_harmonic_recalculation_status(
            "Recalculating harmonics and rebuilding Summed-BCA outputs from existing processed workbooks...",
            "info",
        )
        self._set_full_fft_grid_review_controls_enabled(False)
        owner._settings_harmonic_recalc_thread = thread
        owner._settings_harmonic_recalc_worker = worker
        self._lock_settings_navigation()
        activity_return_home = False
        active_phase_id = "harmonic_selection"

        def _handle_progress(message: str) -> None:
            if not self._settings_post_processing_activity_is_active():
                return
            from Main_App.gui.processing_workflows import (
                _post_processing_phase_display_state,
            )

            title, display_message, phase_index = (
                _post_processing_phase_display_state(active_phase_id)
            )
            self._set_settings_post_processing_stage(
                title=title,
                message=display_message,
                step=f"Post-processing phase {phase_index}",
            )

        def _handle_phase_progress(
            phase_id: str,
            completed_units: int,
            total_units: int,
            message: str,
        ) -> None:
            nonlocal active_phase_id
            active_phase_id = str(phase_id)
            if not self._settings_post_processing_activity_is_active():
                return
            from Main_App.gui import shell_status
            from Main_App.gui.processing_workflows import (
                _post_processing_phase_display_state,
            )

            title, display_message, phase_index = (
                _post_processing_phase_display_state(active_phase_id, message)
            )
            self._set_settings_post_processing_stage(
                title=title,
                message=display_message,
                step=(
                    f"Post-processing phase {phase_index} of "
                    f"{max(1, int(total_units))}"
                ),
            )
            shell_status.update_post_processing_progress(
                owner,
                completed_units=completed_units,
                total_units=total_units,
                phase_index=phase_index,
            )

        def _handle_finished(result: object) -> None:
            nonlocal activity_return_home
            payload = result if isinstance(result, dict) else {}
            if payload.get("ok"):
                activity_return_home = bool(accept_on_success)
                self._clear_harmonic_settings_rollback()
                workbook_path = payload.get("workbook_path", "")
                self._initial_harmonic_settings_signature = (
                    self._harmonic_settings_signature_from_preprocessing(
                        self._project_preprocessing()
                    )
                )
                self._set_harmonic_recalculation_status(
                    f"Harmonics and downstream Summed-BCA outputs rebuilt: {workbook_path}",
                    "success",
                )
                QMessageBox.information(
                    self,
                    "Harmonics and Outputs Rebuilt",
                    (
                        "Harmonic selection and downstream Summed-BCA outputs were "
                        "rebuilt from the existing processed workbooks. Raw EEG "
                        f"preprocessing was not rerun.\n\nSelection audit:\n{workbook_path}"
                    ),
                )
            else:
                if payload.get("selection_recalculated"):
                    # A new canonical selection was already accepted. Keep its
                    # matching settings and the downstream failed/stale state.
                    self._clear_harmonic_settings_rollback()
                else:
                    self._restore_harmonic_settings_after_cancel()
                message = str(payload.get("error") or "Unknown error")
                self._set_harmonic_recalculation_status(
                    f"Harmonic recalculation failed: {message}",
                    "warning",
                )
                QMessageBox.warning(
                    self,
                    "Harmonic Recalculation Failed",
                    message,
                )

        def _release_worker() -> None:
            owner._settings_harmonic_recalc_thread = None
            owner._settings_harmonic_recalc_worker = None
            owner._settings_harmonic_recalc_bridge = None
            self._set_full_fft_grid_review_controls_enabled(True)
            self._unlock_settings_navigation_if_idle()
            if accept_on_success:
                self._finish_settings_post_processing_activity_when_idle(
                    return_home=activity_return_home,
                )

        bridge = _SettingsWorkerUiBridge(
            result_callback=_handle_finished,
            progress_callback=_handle_progress,
            phase_progress_callback=_handle_phase_progress,
            thread_finished_callback=_release_worker,
            parent=owner,
        )
        owner._settings_harmonic_recalc_bridge = bridge
        try:
            thread.started.connect(worker.run)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            worker.finished.connect(bridge.handle_result)
            worker.progress.connect(bridge.handle_progress)
            worker.phase_progress.connect(bridge.handle_phase_progress)
            thread.finished.connect(bridge.handle_thread_finished)
            thread.finished.connect(thread.deleteLater)
            thread.start()
        except Exception as exc:  # noqa: BLE001
            owner._settings_harmonic_recalc_thread = None
            owner._settings_harmonic_recalc_worker = None
            owner._settings_harmonic_recalc_bridge = None
            self._set_full_fft_grid_review_controls_enabled(True)
            self._unlock_settings_navigation_if_idle()
            for obj in (worker, bridge, thread):
                try:
                    obj.deleteLater()
                except RuntimeError:
                    pass
            QMessageBox.warning(
                self,
                "Recalculation Unavailable",
                f"Harmonic recalculation could not start: {exc}",
            )
            return False
        if accept_on_success:
            try:
                self._begin_settings_post_processing_activity()
            except Exception:  # noqa: BLE001
                logger.exception(
                    "settings_post_processing_activity_presentation_failed"
                )
                self._set_harmonic_recalculation_status(
                    "Harmonic recalculation is still running in the background; "
                    "progress could not be shown on the processing page.",
                    "warning",
                )
        return True

    def _removed_electrode_detection_mode(self) -> str:
        if (
            self.removed_electrode_detection_mode_combo.currentData()
            == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        ):
            return REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        return REMOVED_ELECTRODE_DETECTION_MODE_OFF

    def _removed_electrode_choice_should_be_confirmed(self) -> bool:
        current_data = self.removed_electrode_detection_mode_combo.currentData()
        if self._removed_electrode_choice_unresolved:
            return current_data in {
                REMOVED_ELECTRODE_DETECTION_MODE_OFF,
                REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
            }
        return (
            current_data in {
                REMOVED_ELECTRODE_DETECTION_MODE_OFF,
                REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
            }
            and current_data != self._initial_removed_electrode_detection_mode
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
        self._refresh_removed_electrode_detection_status()

    def _update_manual_removed_electrodes_button(self) -> None:
        self.manual_removed_electrodes_button.setEnabled(self.project is not None)

    def _refresh_removed_electrode_detection_status(self) -> None:
        status = self.removed_electrode_detection_status
        if self.project is None:
            status.set_variant("info")
            status.set_text("Open a project to edit its experimental QC settings.")
            status.setVisible(True)
            return
        if (
            self._removed_electrode_choice_unresolved
            and self.removed_electrode_detection_mode_combo.currentData() is None
        ):
            status.set_variant("warning")
            status.set_text(
                "Choose On or Off before the next processing run. Off is "
                "recommended. Saving other settings will not record a choice."
            )
            status.setVisible(True)
            return
        status.setVisible(False)

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

    def _qc_recording_rows(self):
        """Return declared visit coverage for recording-aware QC editors."""

        if self.project is None or not (getattr(self.project, "sessions", {}) or {}):
            return ()
        try:
            raw_file_infos = prepare_batch_file_infos(self.project)
        except (OSError, RuntimeError, ValueError):
            raw_file_infos = []
        return project_recording_coverage_rows(self.project, raw_file_infos)

    def _edit_manual_removed_electrodes(self) -> None:
        recording_rows = self._qc_recording_rows()
        if recording_rows:
            dialog = ManualRemovedElectrodesDialog(
                self._manual_removed_electrode_participant_ids(),
                self._manual_removed_electrodes_by_pid,
                self,
                recording_rows=recording_rows,
                manual_removed_electrodes_by_recording=(
                    self._manual_removed_electrodes_by_recording
                ),
            )
        else:
            dialog = ManualRemovedElectrodesDialog(
                self._manual_removed_electrode_participant_ids(),
                self._manual_removed_electrodes_by_pid,
                self,
            )
        if dialog.exec() == QDialog.Accepted:
            self._manual_removed_electrodes_by_pid = dialog.manual_removed_electrodes()
            self._manual_removed_electrodes_by_recording = (
                dialog.manual_removed_electrodes_by_recording()
            )
            self._draft_tracker.changed()

    def _manage_dataset_exclusions(self) -> None:
        from Main_App.gui.dataset_exclusions_workflow import show_dataset_exclusions

        show_dataset_exclusions(self)

    def _show_removed_electrode_detection_info(self) -> None:
        QMessageBox.information(
            self,
            "Removed-electrode detection",
            "Suggests electrodes that may have been unplugged during recording. "
            "Developed with one lab's BioSemi ActiveTwo 64 data, it still needs "
            "independent validation. Review its suggestions before accepting repairs. "
            "Saved manual electrode lists work separately.",
        )

    def _current_roi_montage(self) -> str:
        return validate_roi_montage(self.roi_editor.current_montage())

    def _validate_roi_draft(self) -> bool:
        if self.roi_editor.validate_draft():
            return True
        self.tabs.setCurrentIndex(self._roi_tab_index)
        self.roi_editor.validate_draft()
        return False

    def _on_tab_changed(self, index: int) -> None:
        # Drafts may be incomplete while the user edits related fields/tabs.
        self._last_tab_index = index

    # ------------------------------------------------------------------
    def _focus_invalid_preproc_field(self, message: str) -> None:
        key = preprocessing_error_field(message)
        if key is not None:
            self.tabs.setCurrentIndex(self._preproc_tab_index)
            edit = self.preproc_edits[PREPROCESSING_FIELDS.index(key)]
            refresh_preprocessing_feedback(self)
        else:
            self.tabs.setCurrentIndex(self._harmonic_tab_index)
            if self._fixed_harmonic_list_selected():
                mode = self.fixed_harmonic_input_mode_combo.currentData()
                edit = (
                    self.fixed_harmonic_upper_index_edit
                    if mode == FIXED_HARMONIC_INPUT_UPPER_HARMONIC
                    else self.fixed_harmonic_upper_frequency_edit
                    if mode == FIXED_HARMONIC_INPUT_UPPER_FREQUENCY
                    else self.fixed_harmonic_freqs_edit
                )
            else:
                edit = self.harmonic_selection_electrodes_edit
        if edit.isEnabled():
            mark_invalid(edit, message)
            edit.setFocus()
            edit.selectAll()

    def _show_settings_validation(self, message: str) -> None:
        self.settings_validation_status.set_text(message)
        self.settings_validation_status.show()

    def has_unsaved_changes(self) -> bool:
        tracker = getattr(self, "_draft_tracker", None)
        return tracker is not None and tracker.is_dirty()

    def save_pending_changes(self) -> bool:
        self._pending_save_succeeded = False
        try:
            self._save()
        except OSError as exc:
            logger.exception("settings_draft_save_failed")
            QMessageBox.critical(self, "Save Error", str(exc))
        owner = self.host or self
        return bool(
            self._pending_save_succeeded
            and not getattr(owner, "_run_active", False)
            and not getattr(owner, "_settings_post_processing_activity_active", False)
            and not self._full_fft_grid_review_is_running()
            and not self._harmonic_recalculation_is_running()
        )

    def _settings_save_completed(self) -> None:
        self._pending_save_succeeded = True
        if self.project is not None:
            self._trigger_protocol_baseline = (self.project.frequency_protocol.to_manifest(), copy.deepcopy(self.project.event_map))
            self._initial_trigger_maps_payload = copy.deepcopy(self._trigger_maps_payload)
            if self.project.frequency_protocol.condition_trigger_maps is not None and getattr(self.host, "currentProject", None) is self.project:
                from Main_App.gui.trigger_maps_workflow import refresh_home_trigger_maps
                refresh_home_trigger_maps(self.host)
        self._draft_tracker.mark_saved()

    def accept(self) -> None:
        self._settings_save_completed()
        super().accept()

    def _experimental_qc_settings_from_editor(self) -> ExperimentalQcSettings:
        if self.project is None:
            return ExperimentalQcSettings.for_new_project()
        values = {
            field_name: edit.text()
            for field_name, edit in self.summed_bca_threshold_edits.items()
        }
        screening = SummedBcaScreeningSettings(
            enabled=self.summed_bca_screening_enabled_check.isChecked(),
            warning_summed_bca_uv=values["warning_summed_bca_uv"],
            strong_warning_summed_bca_uv=values[
                "strong_warning_summed_bca_uv"
            ],
            extreme_review_summed_bca_uv=values[
                "extreme_review_summed_bca_uv"
            ],
            concentrated_review_flagged_cells=values[
                "concentrated_review_flagged_cells"
            ],
            broad_extreme_review_unique_electrodes=values[
                "broad_extreme_review_unique_electrodes"
            ],

        )
        raw_spectral = (
            self.project.experimental_qc_settings.raw_spectral_screening.with_enabled(
                self.raw_spectral_screening_enabled_check.isChecked()
            )
        )
        return (
            self.project.experimental_qc_settings.with_summed_bca_screening(
                screening
            ).with_raw_spectral_screening(raw_spectral)
            .with_condition_specific_interpolation_enabled(
                self.condition_specific_interpolation_enabled_check.isChecked()
            )
            .with_kurtosis_review_auto_interpolate_extreme(
                self.kurtosis_review_auto_interpolate_extreme_check.isChecked()
            )
            .with_review_features(
                raw_signal_screening_enabled=self.raw_signal_screening_enabled_check.isChecked(),
                kurtosis_screening_enabled=self.kurtosis_screening_enabled_check.isChecked(),
                interpolation_burden_review_enabled=self.interpolation_burden_review_enabled_check.isChecked(),
                snr_spectral_screening_enabled=self.snr_spectral_screening_enabled_check.isChecked(),
                stats_dv_screening_enabled=self.stats_dv_screening_enabled_check.isChecked(),
            )
        )

    def _validated_experimental_qc_settings(
        self,
    ) -> ExperimentalQcSettings | None:
        try:
            return self._experimental_qc_settings_from_editor()
        except ExperimentalQcSettingsError as exc:
            self._show_settings_validation(str(exc))
            self.tabs.setCurrentIndex(self._experimental_tab_index)
            self.experimental_tabs.setCurrentIndex(
                self._experimental_summed_bca_tab_index
            )
            self.postprocessing_qc_tabs.setCurrentIndex(1)
            message = str(exc).casefold()
            for field_name, edit in self.summed_bca_threshold_edits.items():
                if field_name.casefold() in message:
                    mark_invalid(edit, str(exc))
                    edit.setFocus()
                    edit.selectAll()
                    break
            return None

    def _validated_preproc_payload(self) -> Dict[str, Any] | None:
        try:
            normalized = normalize_preprocessing_settings(
                self._collect_project_preprocessing_inputs()
            )
            harmonic_settings = normalize_dv_policy(
                self._harmonic_policy_payload_from_preprocessing(normalized)
            )
            if harmonic_settings.harmonic_selection_profile == HARMONIC_PROFILE_FIXED_ID:
                if (
                    harmonic_settings.fixed_harmonic_input_mode
                    == FIXED_HARMONIC_INPUT_FREQUENCY_LIST
                ):
                    from Tools.Stats.analysis.dv_policy_fixed_predefined import (
                        parse_fixed_harmonic_frequency_list,
                    )

                    parse_fixed_harmonic_frequency_list(
                        harmonic_settings.fixed_harmonic_frequencies_hz
                    )
                elif (
                    harmonic_settings.fixed_harmonic_input_mode
                    == FIXED_HARMONIC_INPUT_UPPER_HARMONIC
                    and harmonic_settings.fixed_harmonic_upper_harmonic_index is None
                ):
                    raise ValueError(
                        "Enter a positive whole-number upper harmonic index."
                    )
                elif (
                    harmonic_settings.fixed_harmonic_input_mode
                    == FIXED_HARMONIC_INPUT_UPPER_FREQUENCY
                    and harmonic_settings.fixed_harmonic_upper_frequency_hz is None
                ):
                    raise ValueError("Enter a positive upper harmonic frequency in Hz.")
            return normalized
        except OSError as exc:
            QMessageBox.warning(self, "Project Settings Unavailable", str(exc))
            return None
        except ValueError as exc:
            self._show_settings_validation(str(exc))
            self._focus_invalid_preproc_field(str(exc))
            return None

    def _validate_preproc_fields(self) -> bool:
        return self._validated_preproc_payload() is not None

    def _on_preproc_edit_finished(self, canonical: str, field: QLineEdit) -> None:  # noqa: ARG002
        refresh_preprocessing_feedback(self)

    def _confirm_parallel_worker_override(self, normalized: Dict[str, Any]) -> bool:
        """Retain the save hook; validated ceilings need no RAM-tier override."""
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

    def _harmonic_recalculation_is_running(self) -> bool:
        owner = getattr(self, "host", None) or self
        thread = getattr(owner, "_settings_harmonic_recalc_thread", None)
        if thread is None:
            return False
        is_running = getattr(thread, "isRunning", None)
        if not callable(is_running):
            return True
        try:
            return bool(is_running())
        except RuntimeError:
            return False

    def _can_leave_settings(self) -> bool:
        if self._full_fft_grid_review_is_running():
            QMessageBox.information(
                self,
                "FFT Grid Check In Progress",
                "Wait for the processed FFT grid check to finish before closing "
                "Settings.",
            )
            return False
        if self._harmonic_recalculation_is_running():
            QMessageBox.information(
                self,
                "Harmonic Recalculation In Progress",
                "Wait for harmonic recalculation and downstream publication to "
                "finish before closing Settings.",
            )
            return False
        return True

    def reject(self) -> None:
        if not self._can_leave_settings():
            return
        super().reject()

    # ------------------------------------------------------------------
    def _restore_failed_project_settings_save(self, snapshot: tuple) -> None:
        """Restore live state after a failed write without retrying disk I/O."""

        project_state, manager_config, project_cache = snapshot
        self.project.__dict__.clear()
        self.project.__dict__.update(project_state)
        self.manager.config = manager_config
        self._project_cache = project_cache
        self._clear_harmonic_settings_rollback()

    def _save(self) -> None:
        if not self._trigger_protocol_is_current():
            return
        if self._full_fft_grid_review_is_running():
            QMessageBox.information(
                self,
                "FFT Grid Check In Progress",
                "Wait for the processed FFT grid check to finish before saving "
                "Settings.",
            )
            return
        if self._harmonic_recalculation_is_running():
            QMessageBox.information(
                self,
                "Harmonic Recalculation In Progress",
                "Wait for harmonic recalculation and downstream publication to "
                "finish before saving Settings.",
            )
            return
        using_project = self.project is not None

        protocol_save_requested = bool(
            using_project and self._protocol_save_requested()
        )
        validated_protocol = (
            self._validated_project_protocol()
            if protocol_save_requested
            else None
        )
        if protocol_save_requested and validated_protocol is None:
            return
        validated_experimental_qc = self._validated_experimental_qc_settings()
        if using_project and validated_experimental_qc is None:
            return
        validated_preproc = self._validated_preproc_payload()
        if validated_preproc is None:
            return
        if not self._validate_roi_draft():
            return
        if not self._confirm_parallel_worker_override(validated_preproc):
            return
        harmonic_settings_changed = self._harmonic_settings_changed_after_processing(
            validated_preproc
        )
        frequency_analysis_changed = (
            self._frequency_analysis_settings_changed_after_processing()
        )
        protocol_changed_after_processing = (
            self._project_protocol_changed_after_processing()
        )
        preprocessing_qc_changed, postprocessing_qc_changed = (
            self._experimental_qc_changes_after_processing(validated_experimental_qc)
        )
        frequency_analysis_changed = (
            frequency_analysis_changed or preprocessing_qc_changed or postprocessing_qc_changed
        )
        recalculate_harmonics_after_save = False
        if harmonic_settings_changed and not (protocol_changed_after_processing or preprocessing_qc_changed):
            recalculate_harmonics_after_save = (
                self._ask_recalculate_harmonics_after_settings_change()
            )
        application_config_snapshot = copy.deepcopy(self.manager.config)
        project_save_snapshot = (
            (
                copy.deepcopy(vars(self.project)),
                application_config_snapshot,
                copy.deepcopy(self._project_cache),
            )
            if using_project
            else None
        )
        if recalculate_harmonics_after_save:
            self._capture_harmonic_settings_rollback()

        if not using_project:
            self.manager.set("stim", "channel", config.DEFAULT_STIM_CHANNEL)
        self.manager.set("analysis", "alpha", self.alpha_edit.text())
        self.manager.set_roi_montage(self._current_roi_montage())
        self.manager.set_roi_pairs(self.roi_editor.get_pairs())
        pre_keys = [
            ("preprocessing", "low_pass", "low_pass"),
            ("preprocessing", "high_pass", "high_pass"),
            ("preprocessing", "downsample", "downsample"),
            ("preprocessing", "reject_thresh", "rejection_z"),
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
                "harmonic_selection_profile",
                "harmonic_selection_profile_version",
                "group_significant_electrode_scope",
                "group_significant_selection_electrodes",
                "group_significant_summation_method",
                "fixed_harmonic_frequencies_hz",
                "fixed_harmonic_input_mode",
                "fixed_harmonic_upper_harmonic_index",
                "fixed_harmonic_upper_frequency_hz",
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
                if self._removed_electrode_choice_should_be_confirmed():
                    normalized = (
                        self.project.confirm_removed_electrode_detection_choice(
                            self._removed_electrode_detection_mode()
                        )
                    )
                if validated_protocol is not None:
                    if validated_protocol.condition_trigger_maps is not None:
                        if self.project.frequency_protocol.condition_trigger_maps is None:
                            migration = self.project.manifest.setdefault("tools", {}).setdefault("trigger_map_migration", {})
                            migration["legacy_protocol"] = self.project.frequency_protocol.to_manifest()
                            migration["legacy_event_map"] = copy.deepcopy(self.project.event_map)
                        self.project.event_map = {}
                    self.project.update_frequency_protocol(validated_protocol)
                self.project.update_experimental_qc_settings(
                    validated_experimental_qc
                )
                self._project_cache = normalized
                self._save_project_with_trigger_guard()
            except ValueError as exc:
                self._restore_failed_project_settings_save(project_save_snapshot)
                QMessageBox.warning(self, "Invalid Settings", str(exc))
                return
            except Exception as exc:  # pragma: no cover - disk I/O error path
                self._restore_failed_project_settings_save(project_save_snapshot)
                QMessageBox.critical(self, "Save Error", str(exc))
                return
            self._sync_electrode_geometry_controls(saved=True)
            if harmonic_settings_changed and not recalculate_harmonics_after_save:
                try:
                    self._mark_harmonic_derivatives_stale()
                except (OSError, RuntimeError, ValueError) as exc:
                    QMessageBox.warning(
                        self,
                        "Freshness Status Warning",
                        (
                            "The settings were saved, but the Summed-BCA freshness "
                            f"record could not be updated: {exc}. Downstream loaders "
                            "will still reject the mismatched saved selection."
                        ),
                    )
        prev_debug = self.manager.debug_enabled()
        prev_beta_tools = self.manager.beta_tools_enabled()
        self.manager.set("debug", "enabled", str(self.debug_check.isChecked()))
        self.manager.set_beta_tools_enabled(self.beta_tools_check.isChecked())
        try:
            self.manager.save()
        except Exception as exc:  # Application settings may fail after the project saved.
            self.manager.config = application_config_snapshot
            self._clear_harmonic_settings_rollback()
            # ROI edits were rolled back with application settings. Invalidate
            # only frequency inputs that already committed to the project.
            if using_project and (
                protocol_changed_after_processing or preprocessing_qc_changed or postprocessing_qc_changed
            ):
                try:
                    self._mark_frequency_analysis_outputs_stale()
                except (OSError, RuntimeError, ValueError):
                    logger.exception("frequency_freshness_update_after_settings_save_failure")
            if using_project and recalculate_harmonics_after_save:
                try:
                    self._mark_harmonic_derivatives_stale()
                except (OSError, RuntimeError, ValueError):
                    logger.exception("harmonic_freshness_update_after_settings_save_failure")
            message = (
                "The project settings were saved, but the application settings "
                "could not be saved.\n\n"
                if using_project else ""
            )
            QMessageBox.critical(self, "Save Error", message + str(exc))
            return
        self._refresh_roi_consumers()

        if using_project and frequency_analysis_changed:
            try:
                self._mark_frequency_analysis_outputs_stale()
            except (OSError, RuntimeError, ValueError) as exc:
                QMessageBox.warning(
                    self,
                    "Freshness Status Warning",
                    f"Frequency-domain outputs could not be marked stale: {exc}",
                )
                if recalculate_harmonics_after_save:
                    self._restore_harmonic_settings_after_cancel()
                    return

        if protocol_changed_after_processing:
            QMessageBox.warning(
                self,
                "Project Reprocessing Required",
                "The project FPVS protocol was saved. Reprocess this project before "
                "using its FFT, QC, harmonic-selection, or statistical outputs.",
            )
        elif preprocessing_qc_changed:
            QMessageBox.warning(
                self, "Project Reprocessing Required",
                "Preprocessing QC settings were saved. Run Processing again to apply "
                "the new checks and repair choices before using the project's results.",
            )
        elif postprocessing_qc_changed and not recalculate_harmonics_after_save:
            QMessageBox.information(
                self, "Post-processing QC Updated",
                "Use Resume Post-processing to apply these QC choices and refresh "
                "dependent results. Accepted repairs remain in place.",
            )

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

        if recalculate_harmonics_after_save:
            if frequency_analysis_changed:
                self._clear_harmonic_settings_rollback()
                self._resume_frequency_domain_post_processing(all_settings_saved=True)
                return
            if self._start_full_fft_grid_review(
                recalculate_after=True,
                accept_on_success=True,
            ):
                return
            self._restore_harmonic_settings_after_cancel()
            return
        if harmonic_settings_changed and not (protocol_changed_after_processing or preprocessing_qc_changed):
            remedy = (
                "Use Resume Post-processing to rebuild frequency-domain QC and "
                "dependent outputs before running downstream analyses."
                if frequency_analysis_changed
                else (
                    "Use Recalculate Harmonics before running downstream analyses. "
                    "The original FullFFT workbooks and Free Harmonic Clustering "
                    "inputs remain valid."
                )
            )
            QMessageBox.warning(
                self,
                "Summed-BCA Outputs Are Stale",
                (
                    "The harmonic method settings were saved, but the replacement "
                    "harmonic selection and Summed-BCA outputs have not been built. "
                    + remedy
                ),
            )

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
            "rejection_z",
            "ref_chan1",
            "ref_chan2",
            "max_chan_idx_keep",
            "max_bad_chans",
            "max_parallel_workers_override",
        ]
        for edit, canonical in zip(self.preproc_edits, canonical_keys):
            values[canonical] = edit.text()
        values["experimental_ram_preload"] = self.experimental_ram_preload_check.isChecked()
        values["line_noise_filter_enabled"] = (
            self.line_noise_filter_enabled_check.isChecked()
        )
        values["kurtosis_auto_interpolate_all"] = (
            self.kurtosis_auto_interpolate_all_check.isChecked()
        )
        values["line_noise_frequency_hz"] = int(
            self.line_noise_frequency_combo.currentData()
        )
        values.update(self._sync_electrode_geometry_controls())
        if self.project is not None:
            self.project.refresh_processing_pipeline_settings()
            values.update({key: copy.deepcopy(self.project.preprocessing[key])
                           for key in OPTIONAL_PREPROCESSING_KEYS if key in self.project.preprocessing})
            for key in REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS:
                if key in self.project.preprocessing:
                    values[key] = self.project.preprocessing[key]
        mode = self._removed_electrode_detection_mode()
        values["removed_electrode_detection_mode"] = mode
        values["auto_detect_removed_electrodes"] = (
            mode == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
        )
        values["manual_removed_electrodes"] = dict(self._manual_removed_electrodes_by_pid)
        values[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] = (
            self.manual_removed_electrodes_enabled_check.isChecked()
        )
        values["manual_removed_electrodes_by_recording"] = dict(
            self._manual_removed_electrodes_by_recording
        )
        values["manual_excluded_participants"] = list(
            self._manual_excluded_participants
        )
        values["manual_excluded_recordings"] = list(
            self._manual_excluded_recordings
        )
        values["manual_excluded_participant_conditions"] = dict(
            self._manual_excluded_participant_conditions
        )
        values["manual_excluded_recording_conditions"] = dict(
            self._manual_excluded_recording_conditions
        )
        selected_profile = (
            self.harmonic_summation_method_combo.currentData()
            or HARMONIC_PROFILE_LEGACY_ID
        )
        fixed_selected = self._fixed_harmonic_list_selected()
        values["harmonic_selection_policy"] = (
            FIXED_PREDEFINED_POLICY_NAME
            if fixed_selected
            else GROUP_SIGNIFICANT_POLICY_NAME
        )
        values["harmonic_selection_profile"] = selected_profile
        values["harmonic_selection_profile_version"] = HARMONIC_PROFILE_VERSION_1
        values["group_significant_electrode_scope"] = (
            self.harmonic_electrode_scope_combo.currentData()
            or GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ALL
        )
        values["group_significant_selection_electrodes"] = (
            self.harmonic_selection_electrodes_edit.text()
        )
        if selected_profile == HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID:
            summation_method = GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY
        elif selected_profile == HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID:
            summation_method = GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES
        else:
            summation_method = GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST
        values["group_significant_summation_method"] = summation_method
        values["fixed_harmonic_frequencies_hz"] = self.fixed_harmonic_freqs_edit.text()
        values["fixed_harmonic_input_mode"] = (
            self.fixed_harmonic_input_mode_combo.currentData()
            or FIXED_HARMONIC_INPUT_FREQUENCY_LIST
        )
        values["fixed_harmonic_upper_harmonic_index"] = (
            self.fixed_harmonic_upper_index_edit.text().strip() or 0
        )
        values["fixed_harmonic_upper_frequency_hz"] = (
            self.fixed_harmonic_upper_frequency_edit.text().strip() or 0.0
        )
        values["fixed_harmonic_auto_exclude_base"] = True
        values["stim_channel"] = config.DEFAULT_STIM_CHANNEL
        from Main_App.gui.settings_hardware_controls import collect_hardware_controls
        values.update(collect_hardware_controls(self))
        return values

    def _sync_electrode_geometry_controls(self, *, saved: bool = False) -> Dict[str, Any]:
        """Refresh untouched controls; accept explicit edits only after a successful save."""

        if self.project is not None and not saved:
            self.project.refresh_electrode_geometry_settings()
        if self.project is not None and saved and hasattr(self, "_hardware_draft"):
            from Main_App.projects.hardware import normalize_hardware_settings
            self._hardware_draft = dict(self.project.preprocessing)
            self._hardware_control_baseline = normalize_hardware_settings(self.project.preprocessing)
        values: Dict[str, Any] = {}
        for key, combo, default in (
            ("electrode_montage", self.electrode_montage_combo, ELECTRODE_MONTAGE_BIOSEMI64),
            (
                "electrode_mapping_profile", self.electrode_mapping_profile_combo,
                ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
            ),
        ):
            selected = combo.currentData() or default
            if self.project is not None and (
                saved or selected == self._electrode_geometry_control_baseline[key]
            ):
                selected = self.project.preprocessing.get(key, default)
                index = combo.findData(selected)
                if index < 0:
                    raise ValueError(f"Unsupported project {key}: {selected}")
                combo.setCurrentIndex(index)
                self._electrode_geometry_control_baseline[key] = selected
            values[key] = selected
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
        self._settings_save_completed()
        self._return_to_home()

    def reject(self) -> None:
        if not self._can_leave_settings():
            return
        self._return_to_home()

    def _refresh_host_settings_indicators(self) -> None:
        host = getattr(self, "host", None)
        if host is None:
            return
        debug_label = getattr(host, "lbl_debug", None)
        if debug_label is not None:
            debug_label.setVisible(host.settings.debug_enabled())

    def _return_to_home(self) -> None:
        host = getattr(self, "host", None)
        if host is None:
            return
        self._refresh_host_settings_indicators()
        show_home_page = getattr(host, "show_home_page", None)
        if callable(show_home_page):
            show_home_page()
        if getattr(host, "_settings_page", None) is self:
            workspace_stack = getattr(host, "workspace_stack", None)
            if workspace_stack is not None:
                workspace_stack.removeWidget(self)
            host._settings_page = None
            refresh = getattr(host, "_refresh_project_dirty_indicator", None)
            if callable(refresh):
                refresh()
            self.deleteLater()
