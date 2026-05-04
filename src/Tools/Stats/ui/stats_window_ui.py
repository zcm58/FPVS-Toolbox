"""UI assembly for StatsWindow."""
from __future__ import annotations

from Tools.Stats.ui.stats_window_support import *  # noqa: F403

logger = logging.getLogger(__name__)


class StatsWindowUiMixin:
    def _init_ui(self) -> None:
        """Handle the init ui step for the Stats PySide6 workflow."""
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # included conditions panel
        self.conditions_group = SectionCard("Included Conditions")
        self.conditions_group.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding))
        self.conditions_group.setToolTip(
            "Choose which conditions to include in the analysis."
        )
        conditions_layout = self.conditions_group.content_layout
        conditions_layout.setSpacing(6)

        conditions_button_row = QHBoxLayout()
        self.conditions_select_all_btn = make_action_button("Select All", compact=True)
        self.conditions_select_all_btn.setToolTip("Include every condition in the analysis.")
        self.conditions_select_all_btn.clicked.connect(self._select_all_conditions)
        conditions_button_row.addWidget(self.conditions_select_all_btn)
        self.conditions_select_none_btn = make_action_button("Select None", compact=True)
        self.conditions_select_none_btn.setToolTip("Deselect all conditions.")
        self.conditions_select_none_btn.clicked.connect(self._select_no_conditions)
        conditions_button_row.addWidget(self.conditions_select_none_btn)
        conditions_button_row.addStretch(1)
        conditions_layout.addLayout(conditions_button_row)

        self.conditions_scroll_area = QScrollArea()
        self.conditions_scroll_area.setWidgetResizable(True)
        self.conditions_scroll_area.setMinimumHeight(120)
        conditions_list_widget = QWidget()
        self.conditions_list_layout = QVBoxLayout(conditions_list_widget)
        self.conditions_list_layout.setContentsMargins(0, 0, 0, 0)
        self.conditions_list_layout.setSpacing(4)
        self.conditions_scroll_area.setWidget(conditions_list_widget)
        conditions_layout.addWidget(self.conditions_scroll_area)

        # summed BCA definition panel
        self.dv_group = SectionCard("Summed BCA definition")
        self.dv_group.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding))
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
        self.dv_policy_combo.setCurrentText(self._dv_policy_name)
        self.dv_policy_combo.currentTextChanged.connect(self._on_dv_policy_changed)
        dv_method_row.addWidget(self.dv_policy_combo, 1)
        dv_layout.addLayout(dv_method_row)

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

        dv_layout.addLayout(fixed_form)
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
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        )
        self.group_mean_preview_table.setMinimumHeight(120)
        group_mean_layout.addWidget(self.group_mean_preview_table)

        dv_layout.addWidget(self.group_mean_controls)
        self._set_group_mean_controls_visible(
            self._dv_policy_name == ROSSION_POLICY_NAME
        )

        self.dv_variants_group = SectionCard("Optional comparison exports (do not change results)")
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
            FIXED_K_POLICY_NAME: "Export a comparison version using a fixed number of harmonics",
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
            content_layout=QHBoxLayout(),
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

        manual_layout.addStretch(1)
        self.manual_exclusion_edit_btn = make_action_button("Edit...")
        self.manual_exclusion_clear_btn = make_action_button("Clear", variant="danger")
        manual_layout.addWidget(self.manual_exclusion_edit_btn)
        manual_layout.addWidget(self.manual_exclusion_clear_btn)

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

        single_action_row = QHBoxLayout()
        self.analyze_single_btn = make_action_button("Analyze Single Group", variant="primary")
        self.analyze_single_btn.setToolTip(
            "Run the full single-group analysis pipeline using the selected settings."
        )
        self.analyze_single_btn.clicked.connect(self.on_analyze_single_group_clicked)
        single_action_row.addWidget(self.analyze_single_btn)

        self.single_advanced_btn = make_action_button("Advanced...")
        self.single_advanced_btn.setToolTip(
            "Run or export individual single-group steps."
        )
        self.single_advanced_btn.clicked.connect(self.on_single_advanced_clicked)
        single_action_row.addWidget(self.single_advanced_btn)
        single_layout.addLayout(single_action_row)

        self.single_status_lbl = StatusBanner("Idle")
        self.single_status_lbl.setWordWrap(True)
        single_layout.addWidget(self.single_status_lbl)

        # between-group section
        between_box = SectionCard("Between-Group Analysis")
        between_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        between_layout = between_box.content_layout

        between_action_row = QHBoxLayout()
        self.analyze_between_btn = make_action_button("Analyze Group Differences", variant="primary")
        self.analyze_between_btn.setToolTip(
            "Run the full between-group analysis pipeline."
        )
        self.analyze_between_btn.clicked.connect(self.on_analyze_between_groups_clicked)
        between_action_row.addWidget(self.analyze_between_btn)

        self.between_advanced_btn = make_action_button("Advanced...")
        self.between_advanced_btn.setToolTip(
            "Run or export individual between-group steps."
        )
        self.between_advanced_btn.clicked.connect(self.on_between_advanced_clicked)
        between_action_row.addWidget(self.between_advanced_btn)
        between_layout.addLayout(between_action_row)

        self.lela_mode_btn = make_action_button("Lela Mode (Cross-Phase LMM)")
        self.lela_mode_btn.setToolTip(
            "Run the cross-phase mixed model for between-group analyses."
        )
        self.lela_mode_btn.clicked.connect(self.on_run_lela_mode)
        between_layout.addWidget(self.lela_mode_btn)

        self.between_status_lbl = StatusBanner("Idle")
        self.between_status_lbl.setWordWrap(True)
        between_layout.addWidget(self.between_status_lbl)

        analysis_layout.addWidget(single_group_box)
        analysis_layout.addWidget(between_box)

        middle_scroll_area = QScrollArea()
        middle_scroll_area.setWidgetResizable(True)
        middle_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        middle_scroll_area.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding))
        middle_contents = QWidget()
        middle_layout = QVBoxLayout(middle_contents)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(8)
        middle_layout.addWidget(self.dv_group)
        middle_layout.addWidget(self.dv_variants_group)
        middle_layout.addWidget(self.outlier_group)
        middle_layout.addWidget(self.manual_exclusion_group)
        middle_layout.addStretch(1)
        middle_scroll_area.setWidget(middle_contents)

        right_top_widget = QWidget()
        right_layout = QVBoxLayout(right_top_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        data_actions_widget = QWidget()
        data_actions_layout = QVBoxLayout(data_actions_widget)
        data_actions_layout.setContentsMargins(0, 0, 0, 0)
        data_actions_layout.setSpacing(6)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)
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
        folder_row.addWidget(QLabel("Data Folder:"))
        folder_row.addWidget(self.le_folder, 1)
        folder_row.addWidget(btn_browse)
        folder_row.addWidget(self.btn_copy_folder)
        self.btn_open_results = make_action_button("Open Results Folder")
        self.btn_open_results.clicked.connect(self._open_results_folder)
        self.btn_open_results.setToolTip(
            "Open the folder where stats outputs are saved."
        )
        fm = QFontMetrics(self.btn_open_results.font())
        self.btn_open_results.setMinimumWidth(fm.horizontalAdvance(self.btn_open_results.text()) + 24)
        folder_row.addWidget(self.btn_open_results)
        self.info_button = make_action_button("Analysis Info")
        self.info_button.clicked.connect(self.on_show_analysis_info)
        self.info_button.setToolTip(
            "Show a short description of each analysis step."
        )
        folder_row.addWidget(self.info_button)
        folder_row.addStretch(1)
        data_actions_layout.addLayout(folder_row)

        multigroup_box = SectionCard("Multi-Group Scan Summary")
        multigroup_box.setSizePolicy(QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum))
        multigroup_layout = multigroup_box.content_layout
        multigroup_layout.setSpacing(4)

        multigroup_status_row = QHBoxLayout()
        multigroup_status_row.addWidget(QLabel("Status:"))
        self.multi_group_ready_value = StatusBanner("Not ready", variant="error")
        multigroup_status_row.addWidget(self.multi_group_ready_value)
        multigroup_status_row.addStretch(1)
        multigroup_layout.addLayout(multigroup_status_row)

        multigroup_counts = make_form_layout()
        self.multi_group_discovered_value = QLabel("0")
        self.multi_group_assigned_value = QLabel("0")
        self.multi_group_groups_value = QLabel("0")
        self.multi_group_unassigned_value = QLabel("0")
        multigroup_counts.addRow("Discovered subjects:", self.multi_group_discovered_value)
        multigroup_counts.addRow("Assigned subjects:", self.multi_group_assigned_value)
        multigroup_counts.addRow("Groups with subjects:", self.multi_group_groups_value)
        multigroup_counts.addRow("Unassigned subjects:", self.multi_group_unassigned_value)
        multigroup_layout.addLayout(multigroup_counts)

        shared_action_row = QHBoxLayout()
        self.compute_shared_harmonics_btn = make_action_button("Compute Shared Harmonics")
        self.compute_shared_harmonics_btn.setToolTip(
            "Compute shared harmonic sets pooled across groups and intersected across selected conditions."
        )
        self.compute_shared_harmonics_btn.setEnabled(False)
        self.compute_shared_harmonics_btn.clicked.connect(self._on_compute_shared_harmonics_clicked)
        shared_action_row.addWidget(self.compute_shared_harmonics_btn)

        self.compute_fixed_harmonic_dv_btn = make_action_button("Compute Fixed-harmonic DV")
        self.compute_fixed_harmonic_dv_btn.setToolTip(
            "Compute Summed BCA DV values using the cached shared-harmonics-by-ROI mapping."
        )
        self.compute_fixed_harmonic_dv_btn.setEnabled(False)
        self.compute_fixed_harmonic_dv_btn.clicked.connect(self._on_compute_fixed_harmonic_dv_clicked)
        shared_action_row.addWidget(self.compute_fixed_harmonic_dv_btn)
        shared_action_row.addStretch(1)
        multigroup_layout.addLayout(shared_action_row)

        fixed_status_row = QHBoxLayout()
        fixed_status_row.addWidget(QLabel("Fixed-harmonic DV:"))
        self.fixed_harmonic_dv_summary_value = QLabel("Waiting for shared harmonics.")
        self.fixed_harmonic_dv_summary_value.setWordWrap(True)
        fixed_status_row.addWidget(self.fixed_harmonic_dv_summary_value, 1)
        multigroup_layout.addLayout(fixed_status_row)

        issues_header = QHBoxLayout()
        issues_header.addWidget(QLabel("Issues:"))
        issues_header.addStretch(1)
        self.multi_group_issue_toggle_btn = make_action_button("Show details")
        self.multi_group_issue_toggle_btn.setEnabled(False)
        self.multi_group_issue_toggle_btn.clicked.connect(self._toggle_multigroup_issue_details)
        issues_header.addWidget(self.multi_group_issue_toggle_btn)
        multigroup_layout.addLayout(issues_header)

        self.multi_group_issue_text = QPlainTextEdit()
        self.multi_group_issue_text.setProperty("logSurface", True)
        self.multi_group_issue_text.setReadOnly(True)
        self.multi_group_issue_text.setPlaceholderText("Issues will appear here after scan.")
        self.multi_group_issue_text.setMinimumHeight(70)
        self.multi_group_issue_text.setMaximumHeight(120)
        self.multi_group_issue_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.multi_group_issue_text.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        multigroup_layout.addWidget(self.multi_group_issue_text)

        right_layout.addWidget(multigroup_box)
        right_layout.addWidget(analysis_box)

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
        export_row.addWidget(self.export_open_btn)
        export_row.addWidget(self.export_copy_btn)
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

        self.output_tabs = QTabWidget()
        self.output_tabs.addTab(self.summary_text, "Summary")
        self.output_tabs.addTab(self.log_text, "Log")

        reporting_tab = QWidget()
        reporting_layout = QVBoxLayout(reporting_tab)
        reporting_layout.setContentsMargins(0, 0, 0, 0)
        reporting_layout.setSpacing(6)
        self.reporting_summary_text = QPlainTextEdit()
        self.reporting_summary_text.setProperty("logSurface", True)
        self.reporting_summary_text.setReadOnly(True)
        self.reporting_summary_text.setPlaceholderText("Reporting Summary output")
        mono = self.reporting_summary_text.font()
        mono.setFamilies(["Consolas", "Menlo", "Courier New", "monospace"])
        self.reporting_summary_text.setFont(mono)
        reporting_layout.addWidget(self.reporting_summary_text)
        reporting_btn_row = QHBoxLayout()
        reporting_btn_row.addStretch(1)
        self.reporting_summary_copy_btn = make_action_button("Copy to Clipboard")
        self.reporting_summary_copy_btn.clicked.connect(self._copy_reporting_summary_text)
        self.reporting_summary_save_btn = make_action_button("Save .txt...")
        self.reporting_summary_save_btn.clicked.connect(self._save_reporting_summary_text)
        reporting_btn_row.addWidget(self.reporting_summary_copy_btn)
        reporting_btn_row.addWidget(self.reporting_summary_save_btn)
        reporting_layout.addLayout(reporting_btn_row)
        self.output_tabs.addTab(reporting_tab, "Reporting Summary")

        self.copy_summary_btn = make_action_button("Copy summary")
        self.copy_summary_btn.clicked.connect(self._copy_summary_text)
        self.copy_log_btn = make_action_button("Copy log")
        self.copy_log_btn.clicked.connect(self._copy_log_text)
        output_header = QHBoxLayout()
        output_header.addStretch(1)
        output_header.addWidget(self.copy_summary_btn)
        output_header.addWidget(self.copy_log_btn)

        output_container = QWidget()
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(6)
        output_layout.addLayout(output_header)
        output_layout.addWidget(self.output_tabs)

        self.output_text = self.log_text

        column_one = QWidget()
        column_one_layout = QVBoxLayout(column_one)
        column_one_layout.setContentsMargins(0, 0, 0, 0)
        column_one_layout.setSpacing(0)
        column_one_layout.addWidget(self.conditions_group)

        column_two = QWidget()
        column_two_layout = QVBoxLayout(column_two)
        column_two_layout.setContentsMargins(0, 0, 0, 0)
        column_two_layout.setSpacing(0)
        column_two_layout.addWidget(middle_scroll_area)

        column_three = QWidget()
        column_three_layout = QVBoxLayout(column_three)
        column_three_layout.setContentsMargins(0, 0, 0, 0)
        column_three_layout.setSpacing(0)
        column_three_layout.addWidget(right_top_widget)

        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.setObjectName("stats_top_splitter")
        top_splitter.setChildrenCollapsible(False)
        top_splitter.addWidget(column_one)
        top_splitter.addWidget(column_two)
        top_splitter.addWidget(column_three)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 2)
        top_splitter.setStretchFactor(2, 2)
        top_splitter.setSizes([280, 560, 560])

        root_splitter = QSplitter(Qt.Vertical)
        root_splitter.setObjectName("stats_root_splitter")
        root_splitter.setChildrenCollapsible(False)
        root_splitter.addWidget(top_splitter)
        root_splitter.addWidget(output_container)
        root_splitter.setStretchFactor(0, 5)
        root_splitter.setStretchFactor(1, 2)
        root_splitter.setSizes([620, 200])

        main_layout.addWidget(data_actions_widget)
        main_layout.addWidget(root_splitter, 1)

        # initialize export buttons
        self._update_export_buttons()
        self._populate_conditions_panel([])

    # --------------------------- actions ---------------------------
