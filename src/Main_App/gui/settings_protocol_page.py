"""Project protocol controls and marker-table construction for Settings.

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
    QHBoxLayout,
    QComboBox,
    QTabWidget,
    QCheckBox,
    QSizePolicy,
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)
from Main_App.gui.components import (
    SectionCard,
    StatusBanner,
    make_action_button,
    make_form_layout,
)
from Main_App.gui.project_protocol import (
    ANALYSIS_WINDOW_MODE_CYCLES,
    ANALYSIS_WINDOW_MODE_DURATION,
    ANALYSIS_WINDOW_MODE_STUDIO,
    condition_marker_editor_rows,
    editor_values_for_protocol,
)
from Main_App.gui.settings_feedback import PREPROCESSING_FIELDS
from Main_App.projects import (
    ODDBALL_INPUT_MODE_DIRECT_HZ,
    ODDBALL_INPUT_MODE_RECURRENCE,
)


def build_protocol_page(self, tabs: QTabWidget) -> QWidget:
    tab = QWidget()
    tab.setObjectName("settings_protocol_tab")
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    # Keep the expandable trigger editor out of the timing form: its table
    # must receive real layout space even in a small logical viewport.
    self.protocol_tabs = QTabWidget(tab)
    self.protocol_tabs.setObjectName("settings_protocol_sections")
    self.protocol_tabs.setDocumentMode(True)
    self.protocol_tabs.tabBar().setDrawBase(False)
    layout.addWidget(self.protocol_tabs, 1)
    timing_page = QWidget()
    timing_page.setObjectName("settings_protocol_timing_page")
    timing_layout = QVBoxLayout(timing_page)
    timing_layout.setContentsMargins(0, 12, 0, 0)
    self.protocol_tabs.addTab(timing_page, "Timing")
    markers_page = QWidget()
    markers_page.setObjectName("settings_protocol_markers_page")
    markers_layout = QVBoxLayout(markers_page)
    markers_layout.setContentsMargins(0, 12, 0, 0)
    self.protocol_tabs.addTab(markers_page, "Trigger markers")

    protocol_card = SectionCard(
        "Project FPVS Protocol",
        timing_page,
        object_name="settings_project_protocol_card",
    )
    protocol_form = make_form_layout()
    markers_card = SectionCard(
        "Trigger markers", markers_page,
        object_name="settings_protocol_markers_card",
    )
    markers_form = make_form_layout()
    self._protocol_markers_form = markers_form
    markers_card.content_layout.addLayout(markers_form)
    self.protocol_trigger_maps_button = make_action_button("Use source maps…", compact=True, parent=markers_card)
    self.protocol_trigger_maps_button.setObjectName("settings_trigger_maps")
    self.protocol_trigger_maps_button.setEnabled(self.project is not None)
    self.protocol_trigger_maps_button.clicked.connect(self._configure_trigger_maps)
    markers_card.content_layout.addWidget(self.protocol_trigger_maps_button)
    markers_layout.addWidget(markers_card, 1)

    if self.project is None:
        values = None
    else:
        values = editor_values_for_protocol(self.project.frequency_protocol)

    self.protocol_presentation_rate_edit = QLineEdit(protocol_card)
    self.protocol_presentation_rate_edit.setObjectName(
        "settings_protocol_presentation_rate_hz"
    )
    self.protocol_presentation_rate_edit.setPlaceholderText("6")
    self.protocol_presentation_rate_edit.setToolTip(
        "The project-wide visual presentation rate in Hz. Decimal and exact "
        "fraction entries are accepted."
    )
    protocol_form.addRow(
        QLabel("Presentation rate (Hz):", protocol_card),
        self.protocol_presentation_rate_edit,
    )

    self.protocol_oddball_mode_combo = QComboBox(protocol_card)
    self.protocol_oddball_mode_combo.setObjectName(
        "settings_protocol_oddball_input_mode"
    )
    self.protocol_oddball_mode_combo.addItem(
        "Oddball every N stimuli",
        ODDBALL_INPUT_MODE_RECURRENCE,
    )
    self.protocol_oddball_mode_combo.addItem(
        "Direct oddball frequency",
        ODDBALL_INPUT_MODE_DIRECT_HZ,
    )
    protocol_form.addRow(
        QLabel("Oddball specification:", protocol_card),
        self.protocol_oddball_mode_combo,
    )

    self.protocol_oddball_every_n_edit = QLineEdit(protocol_card)
    self.protocol_oddball_every_n_edit.setObjectName(
        "settings_protocol_oddball_every_n"
    )
    self.protocol_oddball_every_n_edit.setPlaceholderText("5")
    self.protocol_oddball_every_n_edit.setToolTip(
        "A whole number of stimuli between oddballs; the minimum is 2."
    )
    protocol_form.addRow(
        QLabel("Oddball every N stimuli:", protocol_card),
        self.protocol_oddball_every_n_edit,
    )

    self.protocol_direct_oddball_rate_edit = QLineEdit(protocol_card)
    self.protocol_direct_oddball_rate_edit.setObjectName(
        "settings_protocol_direct_oddball_rate_hz"
    )
    self.protocol_direct_oddball_rate_edit.setPlaceholderText("1.2")
    self.protocol_direct_oddball_rate_edit.setToolTip(
        "The entered rate must resolve to a whole-number stimulus recurrence."
    )
    protocol_form.addRow(
        QLabel("Direct oddball frequency (Hz):", protocol_card),
        self.protocol_direct_oddball_rate_edit,
    )

    self.protocol_analysis_window_mode_combo = QComboBox(protocol_card)
    self.protocol_analysis_window_mode_combo.setObjectName("settings_protocol_analysis_window_mode")
    if values is not None and values.analysis_window_mode == ANALYSIS_WINDOW_MODE_STUDIO:
        self.protocol_analysis_window_mode_combo.addItem("Automatic from Studio", ANALYSIS_WINDOW_MODE_STUDIO)
    self.protocol_analysis_window_mode_combo.addItem("Duration (seconds)", ANALYSIS_WINDOW_MODE_DURATION)
    self.protocol_analysis_window_mode_combo.addItem("Cycle count (advanced)", ANALYSIS_WINDOW_MODE_CYCLES)
    analysis_mode_label = QLabel("Analysis window:", protocol_card)
    analysis_mode_label.setBuddy(self.protocol_analysis_window_mode_combo)
    protocol_form.addRow(analysis_mode_label, self.protocol_analysis_window_mode_combo)
    self.protocol_requested_duration_edit = QLineEdit(protocol_card)
    self.protocol_requested_duration_edit.setObjectName("settings_protocol_requested_duration_seconds")
    self.protocol_requested_duration_edit.setPlaceholderText("120")
    self.protocol_requested_duration_edit.setToolTip(
        "The maximum intended FFT duration. Toolbox retains complete oddball cycles "
        "compatible with the recording and processing sample grids."
    )
    duration_label = QLabel("Analysis duration (seconds):", protocol_card)
    duration_label.setBuddy(self.protocol_requested_duration_edit)
    protocol_form.addRow(duration_label, self.protocol_requested_duration_edit)
    self.protocol_expected_cycles_edit = QLineEdit(protocol_card)
    self.protocol_expected_cycles_edit.setObjectName(
        "settings_protocol_expected_analyzed_cycles"
    )
    self.protocol_expected_cycles_edit.setPlaceholderText("144")
    self.protocol_expected_cycles_edit.setToolTip(
        "The project-wide number of complete oddball cycles intended for the FFT."
    )
    cycles_label = QLabel("Analyzed oddball cycles (advanced):", protocol_card)
    cycles_label.setBuddy(self.protocol_expected_cycles_edit)
    protocol_form.addRow(cycles_label, self.protocol_expected_cycles_edit)
    self._protocol_form = protocol_form

    self.protocol_oddball_marker_code_edit = QLineEdit(markers_card)
    self.protocol_oddball_marker_code_edit.setObjectName(
        "settings_protocol_oddball_marker_code"
    )
    self.protocol_oddball_marker_code_edit.setPlaceholderText("55")
    self.protocol_oddball_marker_code_edit.setToolTip(
        "The project-wide event code emitted for each oddball. It must differ "
        "from every condition-onset code."
    )
    markers_form.addRow(
        QLabel("Oddball marker code:", markers_card),
        self.protocol_oddball_marker_code_edit,
    )
    self.protocol_condition_markers_check = QCheckBox(
        "Use a different oddball marker for each condition",
        markers_card,
    )
    self.protocol_condition_markers_check.setObjectName(
        "settings_protocol_condition_markers_enabled"
    )
    self.protocol_condition_markers_check.setToolTip(
        "Applies only to this project. Turn off to use the shared oddball marker code for every condition."
    )
    markers_card.content_layout.addWidget(self.protocol_condition_markers_check)
    self.protocol_condition_markers_table = QTableWidget(0, 3, markers_card)
    self.protocol_condition_markers_table.setObjectName(
        "settings_protocol_condition_marker_codes"
    )
    self.protocol_condition_markers_table.setHorizontalHeaderLabels(
        ("Condition", "Onset marker", "Oddball marker")
    )
    self.protocol_condition_markers_table.setSelectionBehavior(QAbstractItemView.SelectItems)
    self.protocol_condition_markers_table.setAlternatingRowColors(True)
    self.protocol_condition_markers_table.verticalHeader().hide()
    self.protocol_condition_markers_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    self.protocol_condition_markers_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
    self.protocol_condition_markers_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
    self.protocol_condition_markers_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    markers_card.content_layout.addWidget(self.protocol_condition_markers_table, 1)
    self.protocol_recording_markers_check = QCheckBox("Recording-specific trigger schemas", markers_card)
    self.protocol_recording_markers_check.setObjectName("settings_protocol_recording_markers_enabled")
    markers_card.content_layout.addWidget(self.protocol_recording_markers_check)
    self.protocol_recording_markers_button = make_action_button("Configure recording schemas…", compact=True, parent=markers_card)
    self.protocol_recording_markers_button.setObjectName("settings_protocol_recording_markers_configure")
    self.protocol_recording_markers_summary = QLabel("No recording schemas configured.", markers_card)
    self.protocol_recording_markers_summary.setWordWrap(True)
    self.protocol_recording_markers_row = QWidget(markers_card)
    recording_marker_layout = QHBoxLayout(self.protocol_recording_markers_row)
    recording_marker_layout.setContentsMargins(0, 0, 0, 0)
    recording_marker_layout.addWidget(self.protocol_recording_markers_button)
    recording_marker_layout.addWidget(self.protocol_recording_markers_summary, 1)
    markers_card.content_layout.addWidget(self.protocol_recording_markers_row)
    self._recording_marker_codes = values.recording_oddball_marker_codes if values is not None else ()
    self.protocol_recording_markers_check.setChecked(bool(self._recording_marker_codes))
    self.protocol_marker_code_help = QLabel(
        "Oddball marker code: Event code emitted for each oddball in every "
        "condition. Default: 55.",
        markers_card,
    )
    self.protocol_marker_code_help.setObjectName(
        "settings_protocol_oddball_marker_code_help"
    )
    self.protocol_marker_code_help.setWordWrap(True)

    self.protocol_resolved_oddball_rate_edit = QLineEdit(protocol_card)
    self.protocol_resolved_oddball_rate_edit.setObjectName(
        "settings_protocol_resolved_oddball_rate_hz"
    )
    self.protocol_resolved_oddball_rate_edit.setReadOnly(True)
    protocol_form.addRow(
        QLabel("Resolved oddball frequency:", protocol_card),
        self.protocol_resolved_oddball_rate_edit,
    )

    self.protocol_derived_duration_edit = QLineEdit(protocol_card)
    self.protocol_derived_duration_edit.setObjectName(
        "settings_protocol_derived_duration"
    )
    self.protocol_derived_duration_edit.setReadOnly(True)
    protocol_form.addRow(
        QLabel("Expected analyzed duration:", protocol_card),
        self.protocol_derived_duration_edit,
    )
    protocol_card.content_layout.addLayout(protocol_form)
    markers_card.content_layout.addWidget(self.protocol_marker_code_help)
    timing_layout.addWidget(protocol_card)
    timing_layout.addStretch(1)

    self.protocol_status = StatusBanner("", tab, variant="info")
    self.protocol_status.setObjectName("settings_protocol_status")
    layout.addWidget(self.protocol_status)

    if values is not None:
        self.protocol_presentation_rate_edit.setText(values.presentation_rate_hz)
        mode_index = self.protocol_oddball_mode_combo.findData(
            values.oddball_input_mode
        )
        self.protocol_oddball_mode_combo.setCurrentIndex(max(0, mode_index))
        self.protocol_oddball_every_n_edit.setText(values.oddball_every_n)
        self.protocol_direct_oddball_rate_edit.setText(
            values.entered_oddball_rate_hz
        )
        self.protocol_expected_cycles_edit.setText(
            values.expected_analyzed_oddball_cycles
        )
        self.protocol_analysis_window_mode_combo.setCurrentIndex(
            self.protocol_analysis_window_mode_combo.findData(values.analysis_window_mode)
        )
        self.protocol_requested_duration_edit.setText(values.requested_duration_seconds)
        self.protocol_oddball_marker_code_edit.setText(
            values.oddball_marker_code
        )
        marker_rows = condition_marker_editor_rows(
            getattr(self.project, "event_map", {}) or {}, values,
        )
        self.protocol_condition_markers_table.setRowCount(len(marker_rows))
        for row, (condition, onset, marker) in enumerate(marker_rows):
            for column, text in enumerate((condition, onset, marker)):
                item = QTableWidgetItem(text)
                if column < 2:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if column == 0:
                    item.setData(Qt.UserRole, onset)
                self.protocol_condition_markers_table.setItem(row, column, item)
        self.protocol_condition_markers_check.setChecked(values.condition_oddball_markers_enabled)

    project_enabled = self.project is not None
    for widget in (
        self.protocol_presentation_rate_edit,
        self.protocol_oddball_mode_combo,
        self.protocol_oddball_every_n_edit,
        self.protocol_direct_oddball_rate_edit,
        self.protocol_expected_cycles_edit,
        self.protocol_analysis_window_mode_combo,
        self.protocol_requested_duration_edit,
        self.protocol_oddball_marker_code_edit,
        self.protocol_condition_markers_check,
        self.protocol_condition_markers_table,
        self.protocol_recording_markers_check,
        self.protocol_recording_markers_button,
    ):
        widget.setEnabled(project_enabled)

    self.protocol_oddball_mode_combo.currentIndexChanged.connect(
        self._refresh_protocol_preview
    )
    self.protocol_presentation_rate_edit.textChanged.connect(
        self._refresh_protocol_preview
    )
    self.protocol_oddball_every_n_edit.textChanged.connect(
        self._refresh_protocol_preview
    )
    self.protocol_direct_oddball_rate_edit.textChanged.connect(
        self._refresh_protocol_preview
    )
    self.protocol_expected_cycles_edit.textChanged.connect(
        self._refresh_protocol_preview
    )
    self.protocol_analysis_window_mode_combo.currentIndexChanged.connect(self._refresh_protocol_preview)
    self.protocol_requested_duration_edit.textChanged.connect(self._refresh_protocol_preview)
    self.preproc_edits[PREPROCESSING_FIELDS.index("downsample")].textChanged.connect(self._refresh_protocol_preview)
    self.protocol_oddball_marker_code_edit.textChanged.connect(
        self._refresh_protocol_preview
    )
    self.protocol_condition_markers_check.toggled.connect(self._refresh_protocol_preview)
    self.protocol_condition_markers_table.itemChanged.connect(self._refresh_protocol_preview)
    self.protocol_recording_markers_check.toggled.connect(self._refresh_protocol_preview)
    self.protocol_recording_markers_button.clicked.connect(self._configure_recording_marker_schemas)
    self._protocol_requires_confirmation = bool(
        values is not None and values.requires_confirmation
    )
    self._refresh_protocol_preview()

    # Temporary aliases keep established internal consumers on the new
    # project-owned widgets until the Wave 4 ceiling cleanup lands.
    self.base_freq_edit = self.protocol_presentation_rate_edit
    self.oddball_freq_edit = self.protocol_resolved_oddball_rate_edit

    tabs.addTab(tab, "Protocol")
    return tab
