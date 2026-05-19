"""UI assembly for StatsWindow."""
from __future__ import annotations

from Tools.Stats.ui.stats_window_support import *  # noqa: F403

logger = logging.getLogger(__name__)


class StatsWindowUiMixin:
    def _init_ui(self) -> None:
        """Handle the init ui step for the Stats workflow."""
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # included conditions panel
        self.conditions_group = SectionCard("Included Conditions")
        self.conditions_group.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        self.conditions_group.setMaximumHeight(260)
        self.conditions_group.setToolTip(
            "Choose which conditions to include in the analysis."
        )
        conditions_layout = self.conditions_group.content_layout
        conditions_layout.setSpacing(6)

        self.conditions_select_all_btn = make_action_button("Select All", compact=True)
        self.conditions_select_all_btn.setToolTip("Include every condition in the analysis.")
        self.conditions_select_all_btn.clicked.connect(self._select_all_conditions)
        self.conditions_select_none_btn = make_action_button("Select None", compact=True)
        self.conditions_select_none_btn.setToolTip("Deselect all conditions.")
        self.conditions_select_none_btn.clicked.connect(self._select_no_conditions)
        conditions_button_row = ActionRow(self.conditions_group, alignment=Qt.AlignLeft)
        conditions_button_row.setObjectName("stats_conditions_actions")
        conditions_button_row.add_button(self.conditions_select_all_btn)
        conditions_button_row.add_button(self.conditions_select_none_btn)
        conditions_button_row.row_layout.addStretch(1)
        conditions_layout.addWidget(conditions_button_row)

        self.conditions_scroll_area = QScrollArea()
        self.conditions_scroll_area.setWidgetResizable(True)
        self.conditions_scroll_area.setMinimumHeight(120)
        self.conditions_scroll_area.setMaximumHeight(180)
        conditions_list_widget = QWidget()
        self.conditions_list_layout = QVBoxLayout(conditions_list_widget)
        self.conditions_list_layout.setContentsMargins(0, 0, 0, 0)
        self.conditions_list_layout.setSpacing(4)
        self.conditions_scroll_area.setWidget(conditions_list_widget)
        conditions_layout.addWidget(self.conditions_scroll_area)

        # summed BCA definition panel
        self.dv_group = SectionCard("Summed BCA definition")
        self.dv_group.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        self.dv_group.setToolTip(
            "Select how the primary Summed BCA DV is computed."
        )
        dv_layout = self.dv_group.content_layout
        dv_layout.setSpacing(6)

        dv_method_row = QHBoxLayout()
        dv_method_row.addWidget(QLabel("Method:"))
        self.dv_policy_combo = QComboBox()
        self.dv_policy_combo.setToolTip(
            "Choose the primary DV definition used for all statistical results."
        )
        self.dv_policy_combo.addItems(
            [
                LEGACY_POLICY_NAME,
                FIXED_K_POLICY_NAME,
                ROSSION_POLICY_NAME,
            ]
        )
        self.dv_policy_combo.setMinimumContentsLength(14)
        self.dv_policy_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.dv_policy_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.dv_policy_combo.setCurrentText(self._dv_policy_name)
        self.dv_policy_combo.currentTextChanged.connect(self._on_dv_policy_changed)
        dv_method_row.addWidget(self.dv_policy_combo, 1)
        dv_layout.addLayout(dv_method_row)

        self.fixed_k_controls = QWidget()
        fixed_controls_layout = QVBoxLayout(self.fixed_k_controls)
        fixed_controls_layout.setContentsMargins(0, 0, 0, 0)
        fixed_controls_layout.setSpacing(4)
        fixed_form = make_form_layout()

        self.fixed_k_spinbox = QSpinBox()
        self.fixed_k_spinbox.setRange(1, 50)
        self.fixed_k_spinbox.setValue(self._dv_fixed_k)
        self.fixed_k_spinbox.setToolTip(
            "Number of harmonics to include when using the Fixed-K method."
        )
        self.fixed_k_spinbox.valueChanged.connect(self._on_fixed_k_changed)
        fixed_form.addRow("K:", self.fixed_k_spinbox)

        self.fixed_k_exclude_h1 = QCheckBox("Exclude harmonic 1")
        self.fixed_k_exclude_h1.setChecked(self._dv_exclude_harmonic1)
        self.fixed_k_exclude_h1.setToolTip(
            "Skip the first harmonic when building the Fixed-K DV."
        )
        self.fixed_k_exclude_h1.stateChanged.connect(self._on_fixed_k_exclude_h1_changed)
        fixed_form.addRow("", self.fixed_k_exclude_h1)

        self.fixed_k_exclude_base = QCheckBox("Exclude base-rate harmonics")
        self.fixed_k_exclude_base.setChecked(self._dv_exclude_base_harmonics)
        self.fixed_k_exclude_base.setToolTip(
            "Exclude base-rate harmonics from the Fixed-K DV."
        )
        self.fixed_k_exclude_base.stateChanged.connect(self._on_fixed_k_exclude_base_changed)
        fixed_form.addRow("", self.fixed_k_exclude_base)

        self.fixed_k_base_freq_value = QLabel(f"{self._current_base_freq:g} Hz")
        self.fixed_k_base_freq_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.fixed_k_base_freq_value.setToolTip(
            "Base frequency from Settings used to identify harmonics."
        )
        fixed_form.addRow("Base frequency:", self.fixed_k_base_freq_value)

        fixed_controls_layout.addLayout(fixed_form)
        dv_layout.addWidget(self.fixed_k_controls)
        self._set_fixed_k_controls_enabled(self._dv_policy_name == FIXED_K_POLICY_NAME)

        self.group_mean_controls = QWidget()
        group_mean_layout = QVBoxLayout(self.group_mean_controls)
        group_mean_layout.setContentsMargins(0, 0, 0, 0)
        group_mean_layout.setSpacing(6)

        group_mean_form = make_form_layout()

        self.group_mean_z_threshold = QDoubleSpinBox()
        self.group_mean_z_threshold.setRange(-10.0, 10.0)
        self.group_mean_z_threshold.setDecimals(2)
        self.group_mean_z_threshold.setSingleStep(0.05)
        self.group_mean_z_threshold.setValue(self._dv_group_mean_z_threshold)
        self.group_mean_z_threshold.valueChanged.connect(
            self._on_group_mean_z_threshold_changed
        )
        self.group_mean_z_threshold.setToolTip(
            "Minimum group-mean Z value for a harmonic to count as significant."
        )
        group_mean_form.addRow("Z threshold:", self.group_mean_z_threshold)

        self.group_mean_empty_policy_combo = QComboBox()
        self.group_mean_empty_policy_combo.addItems(
            [
                EMPTY_LIST_FALLBACK_FIXED_K,
                EMPTY_LIST_SET_ZERO,
                EMPTY_LIST_ERROR,
            ]
        )
        self.group_mean_empty_policy_combo.setMinimumContentsLength(12)
        self.group_mean_empty_policy_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.group_mean_empty_policy_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.group_mean_empty_policy_combo.setCurrentText(self._dv_empty_list_policy)
        self.group_mean_empty_policy_combo.currentTextChanged.connect(
            self._on_empty_list_policy_changed
        )
        self.group_mean_empty_policy_combo.setToolTip(
            "What to do if no significant harmonics are found for an ROI."
        )
        group_mean_form.addRow("Empty list policy:", self.group_mean_empty_policy_combo)

        union_label = QLabel(
            "Selected conditions are used to estimate group-mean Z values for each ROI and harmonic."
        )
        union_label.setWordWrap(True)
        group_mean_form.addRow("", union_label)

        group_mean_layout.addLayout(group_mean_form)

        self.group_mean_preview_btn = make_action_button("Preview harmonic sets")
        self.group_mean_preview_btn.setToolTip(
            "Preview the harmonics that will be used by the Rossion method."
        )
        self.group_mean_preview_btn.clicked.connect(self._on_preview_group_mean_z_clicked)
        group_mean_layout.addWidget(self.group_mean_preview_btn)

        self.group_mean_preview_table = QTableWidget(0, 6)
        self.group_mean_preview_table.setHorizontalHeaderLabels(
            ["ROI", "Harmonics (Hz)", "Count", "Fallback", "Stop reason", "Stop fail harmonics"]
        )
        self.group_mean_preview_table.verticalHeader().setVisible(False)
        self.group_mean_preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.group_mean_preview_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.group_mean_preview_table.setSizePolicy(
            QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        )
        self.group_mean_preview_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.group_mean_preview_table.setMinimumHeight(96)
        self.group_mean_preview_table.setMaximumHeight(180)
        group_mean_layout.addWidget(self.group_mean_preview_table)

        dv_layout.addWidget(self.group_mean_controls)
        self._set_group_mean_controls_visible(
            self._dv_policy_name == ROSSION_POLICY_NAME
        )

        self.dv_variants_group = SectionCard("Comparison Exports")
        self.dv_variants_group.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred))
        dv_variants_layout = self.dv_variants_group.content_layout
        dv_variants_layout.setSpacing(4)
        dv_variants_note = QLabel(
            "These exports are for consistency checks. Statistical results use the Primary DV only."
        )
        dv_variants_note.setWordWrap(True)
        self.dv_variants_group.setToolTip(
            "Optional exports that compare alternative DV definitions. "
            "They do not change any statistical results."
        )
        dv_variants_layout.addWidget(dv_variants_note)

        dv_variant_labels = {
            FIXED_K_POLICY_NAME: "Fixed-K comparison export",
        }
        for policy_name in [FIXED_K_POLICY_NAME]:
            checkbox = QCheckBox(dv_variant_labels[policy_name])
            checkbox.setToolTip(
                "Uses K=5 harmonics when no significant harmonics are found; exports only."
            )
            checkbox.setChecked(False)
            checkbox.stateChanged.connect(self._on_dv_variant_toggled)
            dv_variants_layout.addWidget(checkbox)
            self._dv_variant_checkboxes[policy_name] = checkbox
        self._sync_selected_dv_variants()

        self.outlier_group = SectionCard("Outlier Flagging")
        self.outlier_group.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred))
        self.outlier_group.setToolTip(
            "Flag participants whose DV values are outside the allowed range."
        )
        outlier_layout = self.outlier_group.content_layout
        outlier_layout.setSpacing(6)

        self.outlier_enable_checkbox = QCheckBox("Enable DV flagging (always on)")
        self.outlier_enable_checkbox.setChecked(True)
        self.outlier_enable_checkbox.setToolTip(
            "Hard DV limit checks are always run to flag potential outliers."
        )
        self.outlier_enable_checkbox.stateChanged.connect(self._on_outlier_exclusion_toggled)
        self.outlier_enable_checkbox.setEnabled(False)
        outlier_layout.addWidget(self.outlier_enable_checkbox)

        outlier_form = make_form_layout()

        self.outlier_abs_limit_spin = QDoubleSpinBox()
        self.outlier_abs_limit_spin.setRange(0.0, 1_000_000.0)
        self.outlier_abs_limit_spin.setDecimals(2)
        self.outlier_abs_limit_spin.setSingleStep(1.0)
        self.outlier_abs_limit_spin.setValue(self._outlier_abs_limit)
        self.outlier_abs_limit_spin.setToolTip(
            "Participants are flagged if any DV exceeds this absolute cutoff."
        )
        self.outlier_abs_limit_spin.valueChanged.connect(self._on_outlier_abs_limit_changed)
        self.outlier_abs_limit_spin.setEnabled(True)
        outlier_form.addRow("Hard DV limit (abs):", self.outlier_abs_limit_spin)

        outlier_layout.addLayout(outlier_form)

        outlier_note = QLabel(
            "Flag participants if abs(DV) exceeds the limit; non-finite DV requires exclusion."
        )
        outlier_note.setWordWrap(True)
        outlier_note.setToolTip(
            "Applies to the Primary DV only; manual exclusions control modeling."
        )
        outlier_layout.addWidget(outlier_note)

        self.manual_exclusion_group = SectionCard(
            "Manual Exclusions",
            content_layout=QVBoxLayout(),
        )
        self.manual_exclusion_group.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        )
        manual_layout = self.manual_exclusion_group.content_layout
        manual_layout.setSpacing(8)

        self.manual_exclusion_summary_label = QLabel("Excluded: 0")
        manual_layout.addWidget(self.manual_exclusion_summary_label)

        self.manual_exclusion_list = ElidedPathLabel("None")
        self.manual_exclusion_list.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.manual_exclusion_list.setMinimumHeight(22)
        self.manual_exclusion_list.setToolTip("None")
        manual_layout.addWidget(self.manual_exclusion_list, 1)

        self.manual_exclusion_edit_btn = make_action_button("Edit...")
        self.manual_exclusion_clear_btn = make_action_button("Clear", variant="danger")
        manual_actions = ActionRow(self.manual_exclusion_group, alignment=Qt.AlignLeft)
        manual_actions.setObjectName("stats_manual_exclusion_actions")
        manual_actions.add_button(self.manual_exclusion_edit_btn)
        manual_actions.add_button(self.manual_exclusion_clear_btn)
        manual_actions.row_layout.addStretch(1)
        manual_layout.addWidget(manual_actions)

        self.manual_exclusion_edit_btn.clicked.connect(self._open_manual_exclusion_dialog)
        self.manual_exclusion_clear_btn.clicked.connect(self._clear_manual_exclusions)

        analysis_box = SectionCard("Analysis Controls", content_layout=QHBoxLayout())
        analysis_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        analysis_layout = analysis_box.content_layout
        analysis_layout.setSpacing(8)

        # single group section
        single_group_box = SectionCard("Single Group Analysis")
        single_group_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        single_layout = single_group_box.content_layout

        self.analyze_single_btn = make_action_button("Analyze Single Group", variant="primary")
        self.analyze_single_btn.setToolTip(
            "Run the full single-group analysis pipeline using the selected settings."
        )
        self.analyze_single_btn.clicked.connect(self.on_analyze_single_group_clicked)

        self.single_advanced_btn = make_action_button("Advanced...")
        self.single_advanced_btn.setToolTip(
            "Run or export individual single-group steps."
        )
        self.single_advanced_btn.clicked.connect(self.on_single_advanced_clicked)
        single_action_row = ActionRow(single_group_box, alignment=Qt.AlignLeft)
        single_action_row.setObjectName("stats_single_group_actions")
        single_action_row.add_button(self.analyze_single_btn)
        single_action_row.add_button(self.single_advanced_btn)
        single_layout.addWidget(single_action_row)

        self.single_status_lbl = StatusBanner("Idle")
        self.single_status_lbl.setWordWrap(True)
        single_layout.addWidget(self.single_status_lbl)

        analysis_layout.addWidget(single_group_box)

        right_top_widget = QWidget()
        right_layout = QVBoxLayout(right_top_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        data_actions_widget = QWidget()
        data_actions_layout = QVBoxLayout(data_actions_widget)
        data_actions_layout.setContentsMargins(0, 0, 0, 0)
        data_actions_layout.setSpacing(6)

        self.le_folder = ElidedPathLabel()
        self.le_folder.setToolTip(
            "Selected folder that contains the FPVS result spreadsheets."
        )
        self.le_folder.setMinimumHeight(24)
        btn_browse = make_action_button("Browse...")
        btn_browse.setToolTip("Choose the folder that contains FPVS results.")
        btn_browse.clicked.connect(self.on_browse_folder)
        self.btn_copy_folder = make_action_button("Copy", compact=True)
        self.btn_copy_folder.setToolTip("Copy the data folder path.")
        self.btn_copy_folder.setEnabled(False)
        self.btn_copy_folder.clicked.connect(self._copy_data_folder_path)
        self.btn_open_results = make_action_button("Results", compact=True)
        self.btn_open_results.clicked.connect(self._open_results_folder)
        self.btn_open_results.setToolTip(
            "Open the folder where stats outputs are saved."
        )
        self.info_button = make_action_button("Info", compact=True)
        self.info_button.clicked.connect(self.on_show_analysis_info)
        self.info_button.setToolTip(
            "Show a short description of each analysis step."
        )
        folder_actions = ActionRow(data_actions_widget, alignment=Qt.AlignLeft, spacing=6)
        folder_actions.setObjectName("stats_data_folder_actions")
        folder_actions.add_button(btn_browse)
        folder_actions.add_button(self.btn_copy_folder)
        folder_actions.add_button(self.btn_open_results)
        folder_actions.add_button(self.info_button)
        folder_actions.row_layout.addStretch(1)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)
        folder_row.addWidget(QLabel("Data Folder:"))
        folder_row.addWidget(self.le_folder, 1)
        data_actions_layout.addLayout(folder_row)
        data_actions_layout.addWidget(folder_actions)

        right_layout.addWidget(analysis_box)
        right_layout.addWidget(self.manual_exclusion_group)

        # status + ROI labels with spinner
        status_row = QHBoxLayout()
        self.spinner = BusySpinner()
        self.spinner.setFixedSize(18, 18)
        self.spinner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.spinner.hide()
        status_row.addWidget(self.spinner, alignment=Qt.AlignLeft)

        self.lbl_status = StatusBanner("Select a folder containing FPVS results.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        status_row.addWidget(self.lbl_status, 1)
        right_layout.addLayout(status_row)

        export_row = QHBoxLayout()
        export_row.setSpacing(6)
        export_row.addWidget(QLabel("Last Export:"))
        self.export_path_label = ElidedPathLabel()
        self.export_path_label.setMinimumHeight(22)
        export_row.addWidget(self.export_path_label, 1)
        self.export_open_btn = make_action_button("Open", compact=True)
        self.export_open_btn.setToolTip("Open the most recent export file or folder.")
        self.export_open_btn.setEnabled(False)
        self.export_open_btn.clicked.connect(self._open_export_path)
        self.export_copy_btn = make_action_button("Copy", compact=True)
        self.export_copy_btn.setToolTip("Copy the most recent export path.")
        self.export_copy_btn.setEnabled(False)
        self.export_copy_btn.clicked.connect(self._copy_export_path)
        export_actions = ActionRow(right_top_widget, alignment=Qt.AlignLeft, spacing=6)
        export_actions.setObjectName("stats_export_path_actions")
        export_actions.add_button(self.export_open_btn)
        export_actions.add_button(self.export_copy_btn)
        export_row.addWidget(export_actions)
        right_layout.addLayout(export_row)

        self.reporting_summary_export_checkbox = QCheckBox("Reporting Summary (.txt)")
        self.reporting_summary_export_checkbox.setChecked(True)
        self.reporting_summary_export_checkbox.setToolTip(
            "When checked, write a plain-text Reporting Summary at end-of-run."
        )
        right_layout.addWidget(self.reporting_summary_export_checkbox)

        self.lbl_rois = QLabel("")
        self.lbl_rois.setWordWrap(True)
        self.lbl_rois.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.lbl_rois.setToolTip(
            "ROIs loaded from Settings. Update ROI definitions in Settings to change this list."
        )
        right_layout.addWidget(self.lbl_rois)
        right_layout.addStretch(1)

        # output pane
        self.summary_text = QTextEdit()
        self.summary_text.setProperty("logSurface", True)
        self.summary_text.setReadOnly(True)
        self.summary_text.setAcceptRichText(True)
        self.summary_text.setPlaceholderText("Summary output")
        self.summary_text.setMinimumHeight(140)
        self.summary_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.log_text = QPlainTextEdit()
        self.log_text.setProperty("logSurface", True)
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Log output")
        self.log_text.setMinimumHeight(140)
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.reporting_summary_text = QPlainTextEdit()
        self.reporting_summary_text.setProperty("logSurface", True)
        self.reporting_summary_text.setReadOnly(True)
        self.reporting_summary_text.setPlaceholderText("Reporting Summary output")
        mono = self.reporting_summary_text.font()
        mono.setFamilies(["Consolas", "Menlo", "Courier New", "monospace"])
        self.reporting_summary_text.setFont(mono)
        self.reporting_summary_copy_btn = make_action_button("Copy")
        self.reporting_summary_copy_btn.clicked.connect(self._copy_reporting_summary_text)
        self.reporting_summary_save_btn = make_action_button("Save .txt...")
        self.reporting_summary_save_btn.clicked.connect(self._save_reporting_summary_text)

        self.copy_summary_btn = make_action_button("Copy summary")
        self.copy_summary_btn.clicked.connect(self._copy_summary_text)
        self.copy_log_btn = make_action_button("Copy log")
        self.copy_log_btn.clicked.connect(self._copy_log_text)

        output_container = QWidget()
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(6)
        output_header_widget = QWidget(output_container)
        output_header_layout = QHBoxLayout(output_header_widget)
        output_header_layout.setContentsMargins(0, 0, 0, 0)
        output_header_layout.setSpacing(8)
        output_header_layout.addWidget(QLabel("Results:"))
        self.results_selector = QComboBox()
        self.results_selector.setObjectName("stats_results_selector")
        self.results_selector.addItems(["Summary", "Report", "Log"])
        self.results_selector.setToolTip("Choose which Stats output to view.")
        self.results_selector.setMinimumContentsLength(8)
        self.results_selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.results_selector.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        output_header_layout.addWidget(self.results_selector)
        output_header_layout.addStretch(1)

        output_header = ActionRow(output_header_widget, alignment=Qt.AlignRight)
        output_header.setObjectName("stats_output_copy_actions")
        output_header.add_button(self.copy_summary_btn)
        output_header.add_button(self.copy_log_btn)
        output_header_layout.addWidget(output_header)

        reporting_btn_row = ActionRow(output_header_widget, alignment=Qt.AlignRight)
        reporting_btn_row.setObjectName("stats_reporting_summary_actions")
        reporting_btn_row.add_button(self.reporting_summary_copy_btn)
        reporting_btn_row.add_button(self.reporting_summary_save_btn)
        output_header_layout.addWidget(reporting_btn_row)
        self.reporting_summary_actions = reporting_btn_row

        self.results_stack = QStackedWidget()
        self.results_stack.setObjectName("stats_results_stack")
        self.results_stack.addWidget(self.summary_text)
        self.results_stack.addWidget(self.reporting_summary_text)
        self.results_stack.addWidget(self.log_text)
        self.results_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.results_selector.currentIndexChanged.connect(self._sync_results_view)
        output_layout.addWidget(output_header_widget)
        output_layout.addWidget(self.results_stack)

        self.output_text = self.log_text

        self.setup_tabs = QTabWidget()
        self.setup_tabs.setObjectName("stats_setup_tabs")

        basic_scroll_area = QScrollArea()
        basic_scroll_area.setObjectName("stats_basic_setup_scroll_area")
        basic_scroll_area.setWidgetResizable(True)
        basic_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        basic_scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        basic_contents = QWidget()
        basic_layout = QVBoxLayout(basic_contents)
        basic_layout.setContentsMargins(0, 0, 0, 0)
        basic_layout.setSpacing(8)
        basic_layout.addWidget(self.conditions_group)
        basic_layout.addWidget(right_top_widget)
        basic_layout.addStretch(1)
        basic_scroll_area.setWidget(basic_contents)
        self.setup_tabs.addTab(basic_scroll_area, "Basic")

        advanced_scroll_area = QScrollArea()
        advanced_scroll_area.setObjectName("stats_advanced_setup_scroll_area")
        advanced_scroll_area.setWidgetResizable(True)
        advanced_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        advanced_scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        advanced_contents = QWidget()
        advanced_layout = QVBoxLayout(advanced_contents)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)
        advanced_layout.addWidget(self.dv_group)
        advanced_layout.addWidget(self.dv_variants_group)
        advanced_layout.addWidget(self.outlier_group)
        advanced_layout.addStretch(1)
        advanced_scroll_area.setWidget(advanced_contents)
        self.setup_tabs.addTab(advanced_scroll_area, "Advanced")

        root_splitter = QSplitter(Qt.Vertical)
        root_splitter.setObjectName("stats_root_splitter")
        root_splitter.setChildrenCollapsible(False)
        root_splitter.addWidget(self.setup_tabs)
        root_splitter.addWidget(output_container)
        root_splitter.setStretchFactor(0, 5)
        root_splitter.setStretchFactor(1, 2)
        root_splitter.setSizes([620, 200])

        main_layout.addWidget(data_actions_widget)
        main_layout.addWidget(root_splitter, 1)

        # initialize export buttons
        self._update_export_buttons()
        self._populate_conditions_panel([])
        self._sync_results_view()

    # --------------------------- actions ---------------------------

    def _sync_results_view(self, *_args) -> None:
        index = self.results_selector.currentIndex() if hasattr(self, "results_selector") else 0
        if hasattr(self, "results_stack"):
            self.results_stack.setCurrentIndex(index)
        is_summary = index == 0
        is_report = index == 1
        is_log = index == 2
        if hasattr(self, "copy_summary_btn"):
            self.copy_summary_btn.setVisible(is_summary)
        if hasattr(self, "copy_log_btn"):
            self.copy_log_btn.setVisible(is_log)
        if hasattr(self, "reporting_summary_actions"):
            self.reporting_summary_actions.setVisible(is_report)
