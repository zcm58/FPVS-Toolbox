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
        self.conditions_group.setObjectName("stats_conditions_group")
        self.conditions_group.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding))
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
        self.conditions_scroll_area.setObjectName("stats_conditions_scroll_area")
        self.conditions_scroll_area.setWidgetResizable(True)
        self.conditions_scroll_area.setMinimumHeight(150)
        self.conditions_scroll_area.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        )
        conditions_list_widget = QWidget()
        self.conditions_list_layout = QVBoxLayout(conditions_list_widget)
        self.conditions_list_layout.setContentsMargins(0, 0, 0, 0)
        self.conditions_list_layout.setSpacing(4)
        self.conditions_scroll_area.setWidget(conditions_list_widget)
        conditions_layout.addWidget(self.conditions_scroll_area, 1)

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

        self.dv_variants_group = QWidget()
        self.dv_variants_group.setObjectName("stats_comparison_exports")
        self.dv_variants_group.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        dv_variants_layout = QVBoxLayout(self.dv_variants_group)
        dv_variants_layout.setContentsMargins(0, 0, 0, 0)
        dv_variants_layout.setSpacing(4)
        dv_variants_heading = QLabel("Comparison Exports")
        dv_variants_heading.setProperty("cardTitle", True)
        dv_variants_heading_font = dv_variants_heading.font()
        dv_variants_heading_font.setBold(True)
        dv_variants_heading.setFont(dv_variants_heading_font)
        dv_variants_layout.addWidget(dv_variants_heading)
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

        self.outlier_group = QWidget()
        self.outlier_group.setObjectName("stats_outlier_flagging")
        self.outlier_group.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        self.outlier_group.setToolTip(
            "Flag participants whose DV values are outside the allowed range."
        )
        outlier_layout = QVBoxLayout(self.outlier_group)
        outlier_layout.setContentsMargins(0, 0, 0, 0)
        outlier_layout.setSpacing(6)
        outlier_heading = QLabel("Outlier Flagging")
        outlier_heading.setProperty("cardTitle", True)
        outlier_heading_font = outlier_heading.font()
        outlier_heading_font.setBold(True)
        outlier_heading.setFont(outlier_heading_font)
        outlier_layout.addWidget(outlier_heading)

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

        manual_row = QWidget()
        manual_row.setObjectName("stats_manual_exclusion_row")
        manual_row.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        manual_layout = QHBoxLayout(manual_row)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(8)

        self.manual_exclusion_summary_label = QLabel("Excluded: 0")
        manual_layout.addWidget(self.manual_exclusion_summary_label)

        self.manual_exclusion_list = ElidedPathLabel("None")
        self.manual_exclusion_list.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.manual_exclusion_list.setMinimumHeight(22)
        self.manual_exclusion_list.setToolTip("None")
        manual_layout.addWidget(self.manual_exclusion_list, 1)

        self.manual_exclusion_group = SectionCard("Manual Exclusions")
        self.manual_exclusion_group.setObjectName("stats_manual_exclusion_group")
        self.manual_exclusion_group.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        )
        manual_group_layout = self.manual_exclusion_group.content_layout
        manual_group_layout.setSpacing(8)
        manual_group_layout.addWidget(manual_row)

        manual_note = QLabel(
            "Check participants to exclude them from modeling. Flagged participants remain suggestions until checked here."
        )
        manual_note.setWordWrap(True)
        manual_group_layout.addWidget(manual_note)

        manual_filter_row = QHBoxLayout()
        manual_filter_row.setSpacing(6)
        manual_filter_row.addWidget(QLabel("Filter:"))
        self.manual_exclusion_search_input = QLineEdit()
        self.manual_exclusion_search_input.setObjectName("stats_manual_exclusion_filter")
        self.manual_exclusion_search_input.setPlaceholderText("Filter participants...")
        manual_filter_row.addWidget(self.manual_exclusion_search_input, 1)
        manual_group_layout.addLayout(manual_filter_row)

        self.manual_exclusion_candidates_list = QListWidget()
        self.manual_exclusion_candidates_list.setObjectName("stats_manual_exclusion_candidates_list")
        self.manual_exclusion_candidates_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.manual_exclusion_candidates_list.setMinimumHeight(150)
        self.manual_exclusion_candidates_list.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        )
        manual_group_layout.addWidget(self.manual_exclusion_candidates_list, 1)

        self.manual_exclusion_select_all_btn = make_action_button("Exclude all")
        self.manual_exclusion_clear_btn = make_action_button("Clear exclusions", variant="danger")
        manual_actions = ActionRow(self.manual_exclusion_group, alignment=Qt.AlignLeft)
        manual_actions.setObjectName("stats_manual_exclusion_actions")
        manual_actions.add_button(self.manual_exclusion_select_all_btn)
        manual_actions.add_button(self.manual_exclusion_clear_btn)
        manual_actions.row_layout.addStretch(1)
        manual_group_layout.addWidget(manual_actions)

        self.manual_exclusion_search_input.textChanged.connect(
            self._filter_manual_exclusion_candidates
        )
        self.manual_exclusion_candidates_list.itemChanged.connect(
            self._on_manual_exclusion_item_changed
        )
        self.manual_exclusion_select_all_btn.clicked.connect(self._select_all_manual_exclusions)
        self.manual_exclusion_clear_btn.clicked.connect(self._clear_manual_exclusions)

        self.analyze_single_btn = make_action_button("Analyze Single Group", variant="primary")
        self.analyze_single_btn.setObjectName("stats_analyze_single_primary")
        self.analyze_single_btn.setMinimumHeight(36)
        self.analyze_single_btn.setMinimumWidth(190)
        self.analyze_single_btn.setDefault(True)
        self.analyze_single_btn.setToolTip(
            "Run the full single-group analysis pipeline using the selected settings."
        )
        self.analyze_single_btn.clicked.connect(self.on_analyze_single_group_clicked)

        self.single_advanced_btn = make_action_button("Advanced...")
        self.single_advanced_btn.setToolTip(
            "Run or export individual single-group steps."
        )
        self.single_advanced_btn.clicked.connect(self.on_single_advanced_clicked)

        self.le_folder = ElidedPathLabel()
        self.le_folder.setToolTip(
            "Selected folder that contains the FPVS result spreadsheets."
        )
        self.le_folder.setMinimumHeight(24)
        btn_browse = make_action_button("Browse...")
        btn_browse.setToolTip("Choose the folder that contains FPVS results.")
        btn_browse.clicked.connect(self.on_browse_folder)
        folder_actions = ActionRow(self, alignment=Qt.AlignLeft, spacing=6)
        folder_actions.setObjectName("stats_data_folder_actions")
        folder_actions.add_button(btn_browse)

        self.spinner = BusySpinner(self)
        self.spinner.setFixedSize(18, 18)
        self.spinner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.spinner.hide()
        self.lbl_status = StatusBanner("Select a folder containing FPVS results.", self)
        self.lbl_status.setObjectName("stats_status_internal")
        self.lbl_status.setWordWrap(False)
        self.lbl_status.setMaximumWidth(360)
        self.lbl_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.lbl_status.hide()

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
        export_actions = ActionRow(self, alignment=Qt.AlignLeft, spacing=6)
        export_actions.setObjectName("stats_export_path_actions")
        export_actions.add_button(self.export_open_btn)
        export_actions.add_button(self.export_copy_btn)
        export_row.addWidget(export_actions)

        self.export_options_btn = make_action_button("Export Options", compact=True)
        self.export_options_btn.setObjectName("stats_export_options_button")
        self.export_options_menu = QMenu(self.export_options_btn)
        self.reporting_summary_export_action = QAction(
            "Auto-save Reporting Summary (.txt)",
            self.export_options_menu,
        )
        self.reporting_summary_export_action.setCheckable(True)
        self.reporting_summary_export_action.setChecked(True)
        self.reporting_summary_export_action.setToolTip(
            "When checked, write a plain-text Reporting Summary at end-of-run."
        )
        self.export_options_menu.addAction(self.reporting_summary_export_action)
        self.export_options_btn.setMenu(self.export_options_menu)

        review_group = SectionCard("Review")
        review_group.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        review_layout = review_group.content_layout
        review_layout.setSpacing(8)
        review_layout.addWidget(self.outlier_group)
        review_layout.addWidget(self.dv_variants_group)
        review_layout.addLayout(export_row)
        review_actions = ActionRow(review_group, alignment=Qt.AlignLeft)
        review_actions.setObjectName("stats_review_export_actions")
        review_actions.add_button(self.export_options_btn)
        review_actions.row_layout.addStretch(1)
        review_layout.addWidget(review_actions)

        self.lbl_rois = QLabel("")
        self.lbl_rois.setWordWrap(True)
        self.lbl_rois.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.lbl_rois.setToolTip(
            "ROIs loaded from Settings. Update ROI definitions in Settings to change this list."
        )
        review_layout.addWidget(self.lbl_rois)

        # output pane
        self.summary_text = QTextEdit()
        self.summary_text.setProperty("logSurface", True)
        self.summary_text.setReadOnly(True)
        self.summary_text.setAcceptRichText(True)
        self.summary_text.setPlaceholderText("Significant results summary will appear here after analysis.")
        self.summary_text.setMinimumHeight(140)
        self.summary_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.log_text = QPlainTextEdit(self)
        self.log_text.setProperty("logSurface", True)
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Log output")
        self.log_text.setMinimumHeight(140)
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.log_text.hide()

        self.reporting_summary_text = QPlainTextEdit(self)
        self.reporting_summary_text.setProperty("logSurface", True)
        self.reporting_summary_text.setReadOnly(True)
        self.reporting_summary_text.setPlaceholderText("Reporting Summary output")
        mono = self.reporting_summary_text.font()
        mono.setFamilies(["Consolas", "Menlo", "Courier New", "monospace"])
        self.reporting_summary_text.setFont(mono)
        self.reporting_summary_text.hide()

        self.copy_summary_btn = make_action_button("Copy summary")
        self.copy_summary_btn.clicked.connect(self._copy_summary_text)

        output_container = QWidget()
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(6)
        output_header_widget = QWidget(output_container)
        output_header_layout = QHBoxLayout(output_header_widget)
        output_header_layout.setContentsMargins(0, 0, 0, 0)
        output_header_layout.setSpacing(8)
        output_header_layout.addWidget(QLabel("Significant Results Summary:"))
        output_header_layout.addStretch(1)

        output_header = ActionRow(output_header_widget, alignment=Qt.AlignRight)
        output_header.setObjectName("stats_output_copy_actions")
        output_header.add_button(self.copy_summary_btn)
        output_header_layout.addWidget(output_header)

        output_layout.addWidget(output_header_widget)
        output_layout.addWidget(self.summary_text)

        self.output_text = self.log_text

        setup_area = QWidget()
        setup_area.setObjectName("stats_setup_area")
        setup_layout = QVBoxLayout(setup_area)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.setSpacing(8)

        file_box = SectionCard("File I/O")
        file_box.setObjectName("stats_file_io_section")
        file_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum))
        file_layout = file_box.content_layout
        file_layout.setSpacing(6)
        file_grid = QGridLayout()
        file_grid.setContentsMargins(0, 0, 0, 0)
        file_grid.setHorizontalSpacing(10)
        file_grid.setVerticalSpacing(4)
        file_grid.addWidget(QLabel("Excel Files Folder:"), 0, 0)
        file_grid.addWidget(self.le_folder, 0, 1)
        file_grid.addWidget(folder_actions, 0, 2)
        file_grid.addWidget(self.spinner, 0, 3, alignment=Qt.AlignVCenter)
        file_grid.setColumnStretch(1, 1)
        file_layout.addLayout(file_grid)

        basic_page = QWidget()
        basic_page.setObjectName("stats_basic_setup_page")
        basic_layout = QVBoxLayout(basic_page)
        basic_layout.setContentsMargins(0, 0, 0, 0)
        basic_layout.setSpacing(8)
        basic_layout.addWidget(file_box)

        basic_content = QWidget()
        basic_content_layout = QHBoxLayout(basic_content)
        basic_content_layout.setContentsMargins(0, 0, 0, 0)
        basic_content_layout.setSpacing(10)

        basic_content_layout.addWidget(self.conditions_group, 1)
        basic_content_layout.addWidget(self.manual_exclusion_group, 1)
        basic_layout.addWidget(basic_content, 1)

        harmonics_page = QWidget()
        harmonics_page.setObjectName("stats_harmonics_setup_page")
        harmonics_layout = QVBoxLayout(harmonics_page)
        harmonics_layout.setContentsMargins(0, 0, 0, 0)
        harmonics_layout.setSpacing(8)
        harmonics_layout.addWidget(self.dv_group, 1)

        review_page = QWidget()
        review_page.setObjectName("stats_review_setup_page")
        review_layout_page = QVBoxLayout(review_page)
        review_layout_page.setContentsMargins(0, 0, 0, 0)
        review_layout_page.setSpacing(8)
        review_layout_page.addWidget(review_group, 1)

        self.setup_tabs = QTabWidget()
        self.setup_tabs.setObjectName("stats_setup_tabs")
        self.setup_tabs.setDocumentMode(True)
        self.setup_tabs.setStyleSheet(
            """
            QTabWidget#stats_setup_tabs::pane {
                border: 0;
                background: transparent;
            }
            QTabWidget#stats_setup_tabs > QWidget {
                background: transparent;
            }
            """
        )
        self.setup_tabs.addTab(basic_page, "Basic")
        self.setup_tabs.addTab(harmonics_page, "Significant Harmonics")
        self.setup_tabs.addTab(review_page, "Review")
        setup_layout.addWidget(self.setup_tabs, 1)

        self.run_action_bar = QWidget()
        self.run_action_bar.setObjectName("stats_run_action_bar")
        run_action_layout = QHBoxLayout(self.run_action_bar)
        run_action_layout.setContentsMargins(0, 0, 0, 0)
        run_action_layout.setSpacing(8)
        run_action_layout.addStretch(1)
        run_action_layout.addWidget(self.analyze_single_btn)
        run_action_layout.addWidget(self.single_advanced_btn)
        run_action_layout.addStretch(1)
        setup_layout.addWidget(self.run_action_bar)

        root_splitter = QSplitter(Qt.Vertical)
        root_splitter.setObjectName("stats_root_splitter")
        root_splitter.setChildrenCollapsible(False)
        root_splitter.addWidget(setup_area)
        root_splitter.addWidget(output_container)
        root_splitter.setStretchFactor(0, 5)
        root_splitter.setStretchFactor(1, 2)
        root_splitter.setSizes([620, 200])

        main_layout.addWidget(root_splitter, 1)

        # initialize export buttons
        self._update_export_buttons()
        self._populate_conditions_panel([])

    # --------------------------- actions ---------------------------

    def _auto_export_reporting_summary_enabled(self) -> bool:
        action = getattr(self, "reporting_summary_export_action", None)
        return bool(action is None or action.isChecked())
