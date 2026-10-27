"""Optional project pipeline walkthrough; scientific policy stays in the draft model."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import logging

from PySide6.QtCore import Qt, QSignalBlocker, QThread, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHeaderView,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from Main_App.gui.components import (
    ActionRow, AppDialog, StatusBanner, SubsectionHeaderLabel, SurfaceSize,
    make_action_button, make_form_layout,
)
from Main_App.gui.hardware_selection import confirm_hardware_change
from Main_App.gui.project_protocol import (
    ANALYSIS_WINDOW_MODE_CYCLES, ANALYSIS_WINDOW_MODE_DURATION,
    ANALYSIS_WINDOW_MODE_STUDIO, build_manual_protocol, editor_values_for_protocol,
)
from Main_App.projects import ODDBALL_INPUT_MODE_DIRECT_HZ, ODDBALL_INPUT_MODE_RECURRENCE
from Main_App.projects.hardware import (
    HARDWARE_LABELS, resolve_hardware,
)
from Main_App.projects.pipeline_setup import PIPELINE_SETUP_PAGES, PipelineSetupDraft
from Main_App.projects.preprocessing_settings import (
    SUPPORTED_ELECTRODE_MAPPING_PROFILES, SUPPORTED_ELECTRODE_MONTAGES,
)

logger = logging.getLogger(__name__)


class _PipelineSaveWorker(QThread):
    """Manifest locking and atomic I/O never block the GUI event loop."""

    def __init__(self, draft, project, parent):
        super().__init__(parent)
        self.draft = draft
        self.project = project
        self.error = ""

    def run(self):
        try:
            self.draft.save(self.project)
        except Exception as exc:  # A transaction failure must return to the editable draft.
            logger.exception("Pipeline setup save failed")
            self.error = str(exc) or "Could not save the pipeline."


class PipelineSetupDialog(AppDialog):
    """Edit one detached draft and publish it only from the final review page."""

    def __init__(self, project, parent=None, *, can_save: Callable[[], str] | None = None):
        super().__init__("Processing setup", parent, size=SurfaceSize(1080, 760, 960, 680))
        self.setObjectName("pipeline_setup_dialog")
        self.project = project
        self.draft = PipelineSetupDraft.from_project(project)
        self._can_save = can_save
        self._save_worker: _PipelineSaveWorker | None = None
        self.requires_reprocessing_saved = False
        self._pending_reprocessing = False
        self._current_page = 0
        self._loading = False
        self._fields: dict[str, QWidget] = {}
        self._field_labels: dict[str, str] = {}
        self._page_fields: dict[str, list[str]] = {}
        self._forms: dict[str, QFormLayout] = {}
        self._method_tables: dict[str, QTableWidget] = {}
        self._build_ui()
        self._load_values()
        for key in ("line_noise_filter_enabled", "raw_signal_screening_enabled",
                    "kurtosis_screening_enabled", "raw_spectral_screening_enabled"):
            self._fields[key].toggled.connect(self._update_method_preview)
        self._fields["removed_electrode_detection_mode"].currentIndexChanged.connect(self._update_method_preview)
        self._show_page(0)

    def _build_ui(self) -> None:
        body = QHBoxLayout()
        body.setSpacing(18)
        self.root_layout.addLayout(body, 1)
        self.navigation = QListWidget(self)
        self.navigation.setObjectName("pipeline_setup_navigation")
        self.navigation.setFixedWidth(210)
        self.navigation.setSpacing(5)
        for number, page in enumerate(PIPELINE_SETUP_PAGES, 1):
            self.navigation.addItem(f"{number}. {page.label}")
        body.addWidget(self.navigation)
        self.pages = QStackedWidget(self)
        self.pages.setObjectName("pipeline_setup_pages")
        body.addWidget(self.pages, 1)
        builders = {
            "recording": self._build_recording, "reference": self._build_reference,
            "filtering": self._build_filtering, "resampling": self._build_resampling,
            "qc": self._build_qc, "epochs": self._build_epochs, "review": self._build_review,
        }
        for page in PIPELINE_SETUP_PAGES:
            widget = QWidget(self.pages)
            widget.setObjectName(f"pipeline_setup_{page.id}_page")
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(12)
            layout.addWidget(SubsectionHeaderLabel(page.label, widget))
            self._page_fields[page.id] = []
            builders[page.id](widget, layout)
            self.pages.addWidget(widget)
        self.error_banner = StatusBanner(parent=self, variant="error")
        self.error_banner.setObjectName("pipeline_setup_error")
        self.error_banner.label.setTextFormat(Qt.PlainText)
        self.error_banner.hide()
        self.root_layout.addWidget(self.error_banner)
        actions = ActionRow(self)
        self.cancel_button = make_action_button("Cancel", variant="tertiary", parent=self)
        self.back_button = make_action_button("Back", parent=self)
        self.next_button = make_action_button("Next", variant="primary", parent=self)
        self.save_button = make_action_button("Save pipeline", variant="primary", parent=self)
        for name, button in (("cancel", self.cancel_button), ("back", self.back_button),
                             ("next", self.next_button), ("save", self.save_button)):
            button.setObjectName(f"pipeline_setup_{name}")
            button.setAutoDefault(False)
            actions.add_button(button)
        self.root_layout.addWidget(actions)
        self.cancel_button.clicked.connect(self.reject)
        self.back_button.clicked.connect(lambda: self._navigate(self._current_page - 1))
        self.next_button.clicked.connect(lambda: self._navigate(self._current_page + 1))
        self.save_button.clicked.connect(self._save)
        self.navigation.currentRowChanged.connect(self._navigate)

    def _form(self, page_id: str, layout: QVBoxLayout) -> QFormLayout:
        form = make_form_layout()
        self._forms[page_id] = form
        layout.addLayout(form)
        return form

    def _field(self, page_id: str, key: str, label: str, control: QWidget) -> QWidget:
        control.setObjectName(f"pipeline_setup_{key}")
        control.setAccessibleName(label.rstrip(":"))
        self._fields[key] = control
        self._field_labels[key] = label.rstrip(":")
        self._page_fields[page_id].append(key)
        caption = QLabel(label)
        caption.setWordWrap(True)
        caption.setBuddy(control)
        self._forms[page_id].addRow(caption, control)
        return control

    def _edit(self, page_id: str, key: str, label: str, *, tooltip="") -> QLineEdit:
        control = QLineEdit(self)
        control.setToolTip(tooltip)
        return self._field(page_id, key, label, control)

    def _combo(self, page_id: str, key: str, label: str, choices) -> QComboBox:
        control = QComboBox(self)
        control.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        control.setMinimumContentsLength(18)
        for value, text in choices:
            control.addItem(text, value)
        return self._field(page_id, key, label, control)

    def _check(self, page_id: str, key: str, label: str, *, tooltip="") -> QCheckBox:
        control = QCheckBox(self)
        control.setToolTip(tooltip)
        return self._field(page_id, key, label, control)

    @staticmethod
    def _table(headers, parent) -> QTableWidget:
        table = QTableWidget(0, len(headers), parent)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setWordWrap(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setAlternatingRowColors(True)
        return table

    def _methods(self, page_id: str, layout: QVBoxLayout) -> None:
        # A read-only catalog now; a future editor can replace this one surface.
        table = self._table(("Step", "Method"), self)
        table.setObjectName(f"pipeline_setup_{page_id}_methods")
        self._method_tables[page_id] = table
        layout.addWidget(table, 1)

    def _build_recording(self, widget, layout):
        self._form("recording", layout)
        self.hardware_combo = self._combo("recording", "hardware_platform", "EEG hardware:", HARDWARE_LABELS.items())
        self.hardware_combo.activated.connect(self._choose_hardware)
        self._combo("recording", "electrode_montage", "Electrode montage:", SUPPORTED_ELECTRODE_MONTAGES).setToolTip(
            "Use recorded positions or the matching cap template; channel count alone does not identify a montage.")
        self._combo("recording", "electrode_mapping_profile", "Channel mapping:", SUPPORTED_ELECTRODE_MAPPING_PROFILES).setToolTip(
            "Select the mapping matching recorded channel labels and verified electrode positions.")
        self._edit("recording", "channel_types", "Channel roles:", tooltip="Exact recorded names, for example VEOG=eog, ECG=ecg. Blank keeps recorded roles.").setPlaceholderText("VEOG=eog, ECG=ecg")
        from Main_App.gui.trigger_maps_model import trigger_maps_summary
        source_note = QLabel(trigger_maps_summary(self.draft.frequency_protocol), widget)
        source_note.setObjectName("pipeline_setup_source_maps_summary")
        source_note.setWordWrap(True)
        layout.addWidget(source_note)
        layout.addStretch(1)

    def _build_reference(self, widget, layout):
        self._form("reference", layout)
        self._combo("reference", "initial_reference", "Initial reference:", (("recorded", "Keep recorded reference"), ("channels", "Selected channels"))).currentIndexChanged.connect(self._refresh_capabilities)
        self._edit("reference", "initial_reference_channels", "Reference channels:", tooltip="Comma-separated exact recorded names.")
        self._edit("reference", "ref_chan1", "Reference channel 1:")
        self._edit("reference", "ref_chan2", "Reference channel 2:")
        self._check("reference", "drop_reference_channels", "Drop selected reference channels")
        self._edit("reference", "max_chan_idx_keep", "Scalp channel limit:", tooltip="Leave blank to retain all available scalp channels where supported.")
        self.reference_note = QLabel(widget)
        self.reference_note.setWordWrap(True)
        layout.addWidget(self.reference_note)
        self._methods("reference", layout)

    def _build_filtering(self, widget, layout):
        self._form("filtering", layout)
        self._edit("filtering", "high_pass", "High-pass cutoff (Hz):")
        self._edit("filtering", "low_pass", "Low-pass cutoff (Hz):")
        self._check("filtering", "line_noise_filter_enabled", "Remove mains line noise").toggled.connect(self._refresh_capabilities)
        self._combo("filtering", "line_noise_frequency_hz", "Mains frequency:", ((60, "60 Hz"), (50, "50 Hz")))
        self._methods("filtering", layout)

    def _build_resampling(self, widget, layout):
        self._form("resampling", layout)
        self._edit("resampling", "downsample", "Target sampling rate (Hz):")
        self.resampling_note = QLabel(widget)
        self.resampling_note.setWordWrap(True)
        layout.addWidget(self.resampling_note)
        self._methods("resampling", layout)

    def _build_qc(self, widget, layout):
        self._form("qc", layout)
        self._check("qc", "raw_signal_screening_enabled", "Review raw signals")
        self._combo("qc", "removed_electrode_detection_mode", "Removed-electrode detection:", (("off", "Off"), ("auto", "Automatic")))
        self._check("qc", "kurtosis_screening_enabled", "Screen electrodes with kurtosis").toggled.connect(self._refresh_capabilities)
        self._edit("qc", "rejection_z", "Kurtosis flag threshold:")
        self._check("qc", "kurtosis_auto_interpolate_all", "Automatically repair all kurtosis flags")
        self._check("qc", "manual_removed_electrodes_enabled", "Apply saved manual electrode repairs")
        self._check("qc", "raw_spectral_screening_enabled", "Review raw spectra", tooltip="Experimental thresholds. Flags data for review without automatic removal.")
        self.qc_note = QLabel(widget)
        self.qc_note.setWordWrap(True)
        layout.addWidget(self.qc_note)
        self._methods("qc", layout)

    def _build_epochs(self, widget, layout):
        self._form("epochs", layout)
        self._edit("epochs", "presentation_rate_hz", "Presentation rate (Hz):")
        self._combo("epochs", "oddball_input_mode", "Oddball specification:", ((ODDBALL_INPUT_MODE_RECURRENCE, "Every N stimuli"), (ODDBALL_INPUT_MODE_DIRECT_HZ, "Direct frequency"))).currentIndexChanged.connect(self._refresh_protocol_controls)
        self._edit("epochs", "oddball_every_n", "Oddball every N stimuli:")
        self._edit("epochs", "entered_oddball_rate_hz", "Oddball frequency (Hz):")
        choices = [(ANALYSIS_WINDOW_MODE_DURATION, "Duration (seconds)"), (ANALYSIS_WINDOW_MODE_CYCLES, "Cycle count (advanced)")]
        values = editor_values_for_protocol(self.draft.frequency_protocol)
        if values.analysis_window_mode == ANALYSIS_WINDOW_MODE_STUDIO:
            choices.insert(0, (ANALYSIS_WINDOW_MODE_STUDIO, "Automatic from Studio"))
        self._combo("epochs", "analysis_window_mode", "Analysis window:", choices).currentIndexChanged.connect(self._refresh_protocol_controls)
        self._edit("epochs", "requested_duration_seconds", "Analysis duration (seconds):")
        self._edit("epochs", "expected_analyzed_oddball_cycles", "Analyzed oddball cycles:")
        self._edit("epochs", "oddball_marker_code", "Shared oddball marker:")
        self.marker_note = QLabel(widget)
        self.marker_note.setWordWrap(True)
        layout.addWidget(self.marker_note)
        self._methods("epochs", layout)

    def _build_review(self, widget, layout):
        self.review_notice = StatusBanner(parent=widget, variant="warning")
        layout.addWidget(self.review_notice)
        tabs = QTabWidget(widget)
        self.review_table = self._table(("Section", "Setting", "Value", ""), tabs)
        self.review_table.setObjectName("pipeline_setup_review_configuration")
        self.review_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.changes_table = self._table(("Setting", "Saved", "Draft"), tabs)
        self.changes_table.setObjectName("pipeline_setup_review_changes")
        tabs.addTab(self.review_table, "Configuration")
        tabs.addTab(self.changes_table, "Changes")
        layout.addWidget(tabs, 1)

    def _value(self, key):
        control = self._fields[key]
        if isinstance(control, QComboBox):
            return control.currentData()
        if isinstance(control, QCheckBox):
            return control.isChecked()
        return control.text().strip()

    def _set_value(self, key, value):
        control = self._fields[key]
        with QSignalBlocker(control):
            if isinstance(control, QComboBox):
                control.setCurrentIndex(max(0, control.findData(value)))
            elif isinstance(control, QCheckBox):
                control.setChecked(bool(value))
            else:
                control.setText("" if value is None else str(value))

    def _load_values(self):
        self._loading = True
        settings = self.draft.preprocessing
        for key in self._fields:
            if key in settings:
                self._set_value(key, settings[key])
        self._set_value("hardware_platform", resolve_hardware(settings).platform)
        self._set_value("channel_types", ", ".join(f"{key}={value}" for key, value in settings.get("channel_types", {}).items()))
        self._set_value("initial_reference_channels", ", ".join(settings.get("initial_reference_channels", [])))
        self._set_value("initial_reference", settings.get("initial_reference", "recorded"))
        experimental = self.draft.experimental_qc_settings
        for key in ("raw_signal_screening_enabled", "kurtosis_screening_enabled"):
            self._set_value(key, getattr(experimental, key))
        self._set_value("raw_spectral_screening_enabled", experimental.raw_spectral_screening.enabled)
        values = editor_values_for_protocol(self.draft.frequency_protocol)
        for key in self._page_fields["epochs"]:
            self._set_value(key, getattr(values, key))
        schema_count = len(values.condition_oddball_marker_codes) + len(values.recording_oddball_marker_codes)
        mapped = self.draft.frequency_protocol.condition_trigger_maps is not None
        if mapped:
            from Main_App.gui.trigger_maps_model import trigger_maps_summary
            self.marker_note.setText(trigger_maps_summary(self.draft.frequency_protocol) + ". Save or cancel guided setup before editing maps in Settings → Protocol.")
        else:
            self.marker_note.setText("Saved condition/recording trigger schemas are retained. Edit them in Settings → Protocol." if schema_count else "")
        self.marker_note.setVisible(mapped or bool(schema_count))
        self._forms["epochs"].setRowVisible(self._fields["oddball_marker_code"], not mapped)
        self._refresh_methods()
        self._loading = False
        self._refresh_capabilities()
        self._refresh_protocol_controls()

    def _set_row_visible(self, page_id, key, visible):
        self._forms[page_id].setRowVisible(self._fields[key], visible)

    def _refresh_capabilities(self, *_):
        if self._loading or "raw_spectral_screening_enabled" not in self._fields:
            return
        capabilities = self.draft.capabilities
        policy = self.draft.control_policy
        recorded = policy.initial_reference_editor == "selected_channels"
        fixed_reference = policy.initial_reference_editor == "fixed"
        selected = self._value("initial_reference") == "channels"
        for key in ("ref_chan1", "ref_chan2"):
            self._set_row_visible("reference", key, not recorded and not fixed_reference)
        self._set_row_visible("reference", "initial_reference", recorded and not fixed_reference)
        self._set_row_visible("reference", "initial_reference_channels", recorded and not fixed_reference and selected)
        self._set_row_visible("reference", "drop_reference_channels", recorded and not fixed_reference and selected)
        self.reference_note.setText("Fixed scalp montage; final average reference." if fixed_reference else "Final reference: scalp average.")
        self._fields["max_chan_idx_keep"].setEnabled(policy.channel_limit_editable)
        self._fields["downsample"].setEnabled(capabilities.resampling_allowed)
        self.resampling_note.setText("" if capabilities.resampling_allowed else f"This recording retains its native {capabilities.required_sfreq:g} Hz sampling grid.")
        self.resampling_note.setVisible(not capabilities.resampling_allowed)
        self._fields["electrode_montage"].setEnabled(policy.montage_editable)
        self._fields["electrode_mapping_profile"].setEnabled(policy.mapping_editable)
        self._set_row_visible("recording", "channel_types", policy.channel_roles_editable)
        self._fields["line_noise_frequency_hz"].setEnabled(bool(self._value("line_noise_filter_enabled")))
        self._fields["raw_signal_screening_enabled"].setEnabled(capabilities.raw_screening_supported)
        self._fields["removed_electrode_detection_mode"].setEnabled(capabilities.removed_electrode_screening_supported)
        self._fields["kurtosis_screening_enabled"].setEnabled(capabilities.kurtosis_screening_supported)
        self._fields["rejection_z"].setEnabled(capabilities.kurtosis_screening_supported and self._value("kurtosis_screening_enabled"))
        self._fields["kurtosis_auto_interpolate_all"].setEnabled(capabilities.kurtosis_screening_supported and self._value("kurtosis_screening_enabled"))
        self._fields["manual_removed_electrodes_enabled"].setEnabled(capabilities.interpolation_allowed)
        if not capabilities.interpolation_allowed:
            note = "Interpolation and calibrated channel screening are unavailable for this recording."
        elif not capabilities.kurtosis_screening_supported:
            note = "Calibrated channel screening is unavailable for this montage. Saved manual repairs remain available."
        else:
            note = "Saved repair decisions are retained. Manage individual electrodes in Settings → Experimental."
        self.qc_note.setText(note)
        mapping = self._fields["electrode_mapping_profile"]
        allowed = {key for key, _label in policy.allowed_mappings}
        for index in range(mapping.count()):
            mapping.model().item(index).setEnabled(mapping.itemData(index) in allowed)
        montage = self._fields["electrode_montage"]
        allowed_montages = {key for key, _label in policy.allowed_montages}
        for index in range(montage.count()):
            montage.model().item(index).setEnabled(montage.itemData(index) in allowed_montages)

    def _refresh_protocol_controls(self, *_):
        if self._loading or "oddball_marker_code" not in self._fields:
            return
        recurrence = self._value("oddball_input_mode") == ODDBALL_INPUT_MODE_RECURRENCE
        self._set_row_visible("epochs", "oddball_every_n", recurrence)
        self._set_row_visible("epochs", "entered_oddball_rate_hz", not recurrence)
        mode = self._value("analysis_window_mode")
        self._set_row_visible("epochs", "requested_duration_seconds", mode == ANALYSIS_WINDOW_MODE_DURATION)
        self._set_row_visible("epochs", "expected_analyzed_oddball_cycles", mode == ANALYSIS_WINDOW_MODE_CYCLES)

    def _refresh_methods(self):
        for page_id, table in self._method_tables.items():
            rows = self.draft.method_rows(page_id)
            table.setRowCount(len(rows))
            for row, values in enumerate(rows):
                for column, value in enumerate(values):
                    table.setItem(row, column, QTableWidgetItem(str(value)))
            table.resizeRowsToContents()

    def _update_method_preview(self, *_):
        if self._loading:
            return
        detector_mode = self._value("removed_electrode_detection_mode")
        if detector_mode != self.draft.preprocessing["removed_electrode_detection_mode"]:
            self.draft.confirm_removed_electrode_choice(detector_mode)
        self.draft.update_preprocessing({
            "line_noise_filter_enabled": self._value("line_noise_filter_enabled"),
        })
        experimental = self.draft.experimental_qc_settings
        self.draft.update_experimental_qc_settings(replace(experimental,
            raw_signal_screening_enabled=self._value("raw_signal_screening_enabled"),
            kurtosis_screening_enabled=self._value("kurtosis_screening_enabled"),
            raw_spectral_screening=replace(experimental.raw_spectral_screening, enabled=self._value("raw_spectral_screening_enabled"))))
        self._refresh_methods()

    def _choose_hardware(self, *_):
        previous = resolve_hardware(self.draft.preprocessing)
        selected = self._value("hardware_platform")
        if previous.confirmed and not confirm_hardware_change(self, previous.platform, selected):
            self._set_value("hardware_platform", previous.platform)
            return
        # Back navigation preserves unfinished text. Hardware confirmation only
        # resets its dependent controls, never an unrelated filter/protocol edit.
        retained = {key: self._value(key) for key in (
            *self._page_fields["filtering"], *self._page_fields["epochs"], "rejection_z",
        )}
        target_rate = self._value("downsample")
        try:
            self.draft.confirm_hardware(selected, confirmed_change=True)
            self._load_values()
            for key, value in retained.items():
                self._set_value(key, value)
            if self.draft.capabilities.resampling_allowed:
                self._set_value("downsample", target_rate)
            self._refresh_capabilities()
            self._refresh_protocol_controls()
            self.error_banner.hide()
        except ValueError as exc:
            self._set_value("hardware_platform", previous.platform)
            self._error(str(exc))

    def _collect_page(self, page_id):
        if page_id == "recording":
            hardware = resolve_hardware(self.draft.preprocessing)
            if not hardware.confirmed:
                self.draft.confirm_hardware(hardware.platform)
            values = {key: self._value(key) for key in ("electrode_montage", "electrode_mapping_profile")}
            if self.draft.control_policy.channel_roles_editable:
                values["channel_types"] = self._value("channel_types")
            self.draft.update_preprocessing(values)
        elif page_id == "reference":
            values = {"max_chan_idx_keep": self._value("max_chan_idx_keep") or None}
            if self.draft.control_policy.initial_reference_editor == "selected_channels":
                selected = self._value("initial_reference") == "channels"
                values.update(initial_reference=self._value("initial_reference"),
                              initial_reference_channels=self._value("initial_reference_channels") if selected else [],
                              drop_reference_channels=selected and self._value("drop_reference_channels"))
            elif self.draft.control_policy.initial_reference_editor == "legacy_pair":
                values.update(ref_chan1=self._value("ref_chan1"), ref_chan2=self._value("ref_chan2"))
            self.draft.update_preprocessing(values)
        elif page_id in ("filtering", "resampling"):
            self.draft.update_preprocessing({key: self._value(key) for key in self._page_fields[page_id]})
        elif page_id == "qc":
            mode = self._value("removed_electrode_detection_mode")
            if (mode != self.draft.preprocessing["removed_electrode_detection_mode"]
                    or self.draft.preprocessing["removed_electrode_detection_choice_status"] != "ready"):
                self.draft.confirm_removed_electrode_choice(mode)
            self.draft.update_preprocessing({key: self._value(key) for key in ("rejection_z", "kurtosis_auto_interpolate_all", "manual_removed_electrodes_enabled")})
            experimental = self.draft.experimental_qc_settings
            self.draft.update_experimental_qc_settings(replace(experimental,
                raw_signal_screening_enabled=self._value("raw_signal_screening_enabled"),
                kurtosis_screening_enabled=self._value("kurtosis_screening_enabled"),
                raw_spectral_screening=replace(experimental.raw_spectral_screening, enabled=self._value("raw_spectral_screening_enabled"))))
        elif page_id == "epochs":
            current = editor_values_for_protocol(self.draft.frequency_protocol)
            unchanged = all(self._value(key) == getattr(current, key) for key in self._page_fields["epochs"])
            target = self.draft.preprocessing["downsample"]
            window = self.draft.frequency_protocol.analysis_window
            if (unchanged and self.draft.frequency_protocol.is_ready
                    and (window is None or window.target_sampling_rate_hz == target)):
                self.draft.validate_page(page_id)
                return
            protocol = build_manual_protocol(
                presentation_rate_hz=self._value("presentation_rate_hz"),
                oddball_input_mode=self._value("oddball_input_mode"),
                oddball_every_n=self._value("oddball_every_n"),
                oddball_rate_hz=self._value("entered_oddball_rate_hz"),
                expected_analyzed_oddball_cycles=self._value("expected_analyzed_oddball_cycles"),
                oddball_marker_code=self._value("oddball_marker_code"),
                existing_protocol=self.draft.frequency_protocol, require_ready=True,
                analysis_window_mode=self._value("analysis_window_mode"),
                requested_duration_seconds=self._value("requested_duration_seconds"),
                target_sampling_rate_hz=self.draft.preprocessing["downsample"],
            )
            self.draft.update_frequency_protocol(protocol)
        self.draft.validate_page(page_id)
        self._refresh_methods()

    def _navigate(self, index):
        if self._loading or index == self._current_page or not 0 <= index < len(PIPELINE_SETUP_PAGES):
            return
        if index < self._current_page:
            self._show_page(index)
            return
        try:
            self._collect_page(PIPELINE_SETUP_PAGES[self._current_page].id)
            if PIPELINE_SETUP_PAGES[index].id == "review":
                self._collect_all()
                self._refresh_review()
        except (ValueError, RuntimeError) as exc:
            self._error(str(exc))
            with QSignalBlocker(self.navigation):
                self.navigation.setCurrentRow(self._current_page)
            return
        self._show_page(index)

    def _show_page(self, index):
        self._current_page = index
        self.pages.setCurrentIndex(index)
        with QSignalBlocker(self.navigation):
            self.navigation.setCurrentRow(index)
        final = index == len(PIPELINE_SETUP_PAGES) - 1
        self.back_button.setEnabled(index > 0)
        self.next_button.setVisible(not final)
        self.save_button.setVisible(final)
        self.error_banner.hide()

    def _collect_all(self):
        for index, page in enumerate(PIPELINE_SETUP_PAGES[:-1]):
            try:
                self._collect_page(page.id)
            except (ValueError, RuntimeError):
                self._show_page(index)
                raise
        self.draft.validate()

    @staticmethod
    def _display(value):
        if isinstance(value, bool):
            return "On" if value else "Off"
        if value is None or value == "":
            return "—"
        if isinstance(value, (list, tuple)):
            return ", ".join(map(str, value)) or "—"
        return str(value)

    def _refresh_review(self):
        rows = []
        if self.draft.frequency_protocol.condition_trigger_maps is not None:
            from Main_App.gui.trigger_maps_model import trigger_maps_summary
            rows.append(("Recording", "Source trigger maps", trigger_maps_summary(self.draft.frequency_protocol), 0))
        for page_index, page in enumerate(PIPELINE_SETUP_PAGES[:-1]):
            for key in self._page_fields[page.id]:
                if not self._forms[page.id].isRowVisible(self._fields[key]):
                    continue
                control = self._fields[key]
                value = control.currentText() if isinstance(control, QComboBox) else self._display(self._value(key))
                rows.append((page.label, self._field_labels[key], value, page_index))
            rows.extend((page.label, step, method, page_index) for step, method in self.draft.method_rows(page.id))
        self.review_table.setRowCount(len(rows))
        for row, (section, setting, value, index) in enumerate(rows):
            for column, text in enumerate((section, setting, value)):
                self.review_table.setItem(row, column, QTableWidgetItem(str(text)))
            edit = make_action_button("Edit", compact=True, variant="tertiary", parent=self.review_table)
            edit.clicked.connect(lambda _checked=False, target=index: self._navigate(target))
            self.review_table.setCellWidget(row, 3, edit)
        self.review_table.resizeRowsToContents()
        changes = self.draft.review_changes()
        self.changes_table.setRowCount(len(changes))
        for row, change in enumerate(changes):
            for column, value in enumerate((change.label, self._display(change.before), self._display(change.after))):
                self.changes_table.setItem(row, column, QTableWidgetItem(value))
        self.changes_table.resizeRowsToContents()
        self.review_notice.set_text("Changed processing settings require reprocessing before existing results can be reused.")
        self.review_notice.setVisible(self.draft.requires_reprocessing)

    def _error(self, message):
        self.error_banner.set_text(message)
        self.error_banner.show()

    def _save(self):
        if self._current_page != len(PIPELINE_SETUP_PAGES) - 1:
            return
        try:
            self._collect_all()
            unavailable = self._can_save() if self._can_save is not None else ""
            if unavailable:
                raise ValueError(unavailable)
        except (ValueError, RuntimeError) as exc:
            self._error(str(exc))
            return
        self.error_banner.hide()
        self._pending_reprocessing = self.draft.requires_reprocessing
        self._set_saving(True)
        try:
            self._save_worker = _PipelineSaveWorker(self.draft, self.project, self)
            self._save_worker.finished.connect(self._save_finished)
            self._save_worker.start()
            if not self._save_worker.isRunning() and not self._save_worker.isFinished():
                raise RuntimeError("Could not start the pipeline save thread.")
        except Exception as exc:
            logger.exception("Could not start pipeline setup save")
            worker = self._save_worker
            self._save_worker = None
            if worker is not None:
                worker.deleteLater()
            self._set_saving(False)
            self._error(str(exc) or "Could not start saving the pipeline.")

    def _set_saving(self, saving):
        for widget in (self.navigation, self.pages, self.cancel_button,
                       self.back_button, self.next_button, self.save_button):
            widget.setEnabled(not saving)
        self.save_button.setText("Saving…" if saving else "Save pipeline")

    @Slot()
    def _save_finished(self):
        worker = self._save_worker
        self._save_worker = None
        error = worker.error
        worker.deleteLater()
        self._set_saving(False)
        if error:
            self._error(error)
        else:
            self.requires_reprocessing_saved = self._pending_reprocessing
            self.accept()

    def reject(self):
        if self._save_worker is None:
            super().reject()

    def closeEvent(self, event):
        if self._save_worker is not None:
            event.ignore()
        else:
            super().closeEvent(event)
