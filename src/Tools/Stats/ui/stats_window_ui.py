"""UI assembly for StatsWindow."""
# ruff: noqa: F405
from __future__ import annotations

from Main_App.gui.components import make_info_button, show_tool_info
from Tools.Stats.ui.tool_info import STATS_TOOL_INFO
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
            "Choose the Summed BCA harmonic policy. Group-level significant harmonics are the default."
        )
        self.dv_policy_combo.addItems(
            [GROUP_SIGNIFICANT_POLICY_NAME, FIXED_PREDEFINED_POLICY_NAME]
        )
        self.dv_policy_combo.setMinimumContentsLength(14)
        self.dv_policy_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.dv_policy_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.dv_policy_combo.setCurrentText(self._dv_policy_name)
        self.dv_policy_combo.setEnabled(True)
        self.dv_policy_combo.currentTextChanged.connect(self._on_dv_policy_changed)
        dv_method_row.addWidget(self.dv_policy_combo, 1)
        dv_layout.addLayout(dv_method_row)

        self.fixed_predefined_controls = QWidget()
        fixed_predefined_layout = QVBoxLayout(self.fixed_predefined_controls)
        fixed_predefined_layout.setContentsMargins(0, 0, 0, 0)
        fixed_predefined_layout.setSpacing(6)
        fixed_predefined_form = make_form_layout()

        self.fixed_predefined_freqs_edit = QLineEdit()
        self.fixed_predefined_freqs_edit.setText(self._dv_fixed_harmonic_frequencies_hz)
        self.fixed_predefined_freqs_edit.setPlaceholderText("1.2, 2.4, 3.6, 4.8, 7.2")
        self.fixed_predefined_freqs_edit.setToolTip(
            "Comma-separated BCA harmonic frequencies in Hz."
        )
        self.fixed_predefined_freqs_edit.textChanged.connect(
            self._on_fixed_predefined_freqs_changed
        )
        fixed_predefined_form.addRow("Frequencies (Hz):", self.fixed_predefined_freqs_edit)

        self.fixed_predefined_exclude_base = QCheckBox("Automatically exclude base-rate overlaps")
        self.fixed_predefined_exclude_base.setChecked(self._dv_fixed_harmonic_auto_exclude_base)
        self.fixed_predefined_exclude_base.setToolTip(
            "Remove requested frequencies such as 6, 12, 18, and 24 Hz when they overlap with the base rate."
        )
        self.fixed_predefined_exclude_base.stateChanged.connect(
            self._on_fixed_predefined_exclude_base_changed
        )
        fixed_predefined_form.addRow("", self.fixed_predefined_exclude_base)

        self.fixed_predefined_base_freq_value = QLabel(f"{self._current_base_freq:g} Hz")
        self.fixed_predefined_base_freq_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fixed_predefined_form.addRow("Base frequency:", self.fixed_predefined_base_freq_value)

        fixed_predefined_layout.addLayout(fixed_predefined_form)

        self.fixed_predefined_preview_btn = make_action_button("Validate harmonic list")
        self.fixed_predefined_preview_btn.setToolTip(
            "Validate the fixed harmonic list against BCA frequency columns."
        )
        self.fixed_predefined_preview_btn.clicked.connect(self._on_preview_fixed_predefined_clicked)
        fixed_predefined_layout.addWidget(self.fixed_predefined_preview_btn)

        self.fixed_predefined_preview_table = QTableWidget(0, 6)
        self.fixed_predefined_preview_table.setHorizontalHeaderLabels(
            ["Requested Hz", "Matched Hz", "BCA column", "Bin", "Included", "Reason"]
        )
        self.fixed_predefined_preview_table.verticalHeader().setVisible(False)
        self.fixed_predefined_preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.fixed_predefined_preview_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.fixed_predefined_preview_table.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        )
        self.fixed_predefined_preview_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.fixed_predefined_preview_table.setMinimumHeight(120)
        self.fixed_predefined_preview_table.setMaximumHeight(150)
        fixed_predefined_header = self.fixed_predefined_preview_table.horizontalHeader()
        for col in range(self.fixed_predefined_preview_table.columnCount()):
            fixed_predefined_header.setSectionResizeMode(col, QHeaderView.Stretch)
        fixed_predefined_header.setStretchLastSection(True)
        fixed_predefined_layout.addWidget(self.fixed_predefined_preview_table)

        dv_layout.addWidget(self.fixed_predefined_controls)

        self.group_significant_note = QLabel(
            "Uses one common z-significant oddball harmonic list selected from "
            "grand-averaged FullFFT amplitude spectra; this is the default Stats DV policy."
        )
        self.group_significant_note.setWordWrap(True)
        self.group_significant_note.setToolTip(
            "Selection is group-level across final included participants and selected conditions, "
            "with base-rate overlaps excluded."
        )
        self.recalculate_harmonics_btn = make_action_button(
            "Recalculate Harmonics",
            compact=True,
        )
        self.recalculate_harmonics_btn.setObjectName("stats_recalculate_harmonics_button")
        self.recalculate_harmonics_btn.setToolTip(
            "Clear saved group-level significant harmonics for this project."
        )
        self.recalculate_harmonics_btn.clicked.connect(self.on_recalculate_harmonics_clicked)
        group_significant_row = QHBoxLayout()
        group_significant_row.setSpacing(8)
        group_significant_row.addWidget(self.group_significant_note, 1)
        group_significant_row.addWidget(self.recalculate_harmonics_btn, 0, Qt.AlignTop)
        dv_layout.addLayout(group_significant_row)
        self._set_fixed_predefined_controls_visible(
            self._dv_policy_name == FIXED_PREDEFINED_POLICY_NAME
        )

        self.outlier_group = QWidget()
        self.outlier_group.setObjectName("stats_outlier_flagging")
        self.outlier_group.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        self.outlier_group.setToolTip(
            "Flag participants whose DV values are outside the allowed range."
        )
        outlier_layout = QVBoxLayout(self.outlier_group)
        outlier_layout.setContentsMargins(0, 0, 0, 0)
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
        export_row.addWidget(QLabel("Path:"))
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

        self.stats_ready_export_btn = make_action_button("Export Stats-Ready Workbook")
        self.stats_ready_export_btn.setObjectName("stats_ready_export_button")
        self.stats_ready_export_btn.setToolTip(
            "Write an additional Summed BCA workbook for JASP, R/RStudio, and SAS."
        )
        self.stats_ready_export_btn.clicked.connect(self.on_export_stats_ready_clicked)

        outlier_section = SectionCard("Outlier Flagging")
        outlier_section.setObjectName("stats_outlier_flagging_section")
        outlier_section.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        outlier_section.content_layout.setSpacing(6)
        outlier_section.content_layout.addWidget(self.outlier_group)

        comparison_exports_section = SectionCard("Exports")
        comparison_exports_section.setObjectName("stats_comparison_exports_section")
        comparison_exports_section.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        )
        comparison_exports_layout = comparison_exports_section.content_layout
        comparison_exports_layout.setSpacing(8)

        export_options_actions = ActionRow(comparison_exports_section, alignment=Qt.AlignLeft)
        export_options_actions.setObjectName("stats_export_options_actions")
        export_options_actions.add_button(self.stats_ready_export_btn)
        export_options_actions.add_button(self.export_options_btn)
        export_options_actions.row_layout.addStretch(1)
        comparison_exports_layout.addWidget(export_options_actions)

        last_export_section = SectionCard("Last Export")
        last_export_section.setObjectName("stats_last_export_section")
        last_export_section.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        last_export_section.content_layout.setSpacing(6)
        last_export_section.content_layout.addLayout(export_row)

        self.lbl_rois = QLabel("")
        self.lbl_rois.setWordWrap(True)
        self.lbl_rois.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.lbl_rois.setToolTip(
            "ROIs loaded from Settings. Update ROI definitions in Settings to change this list."
        )

        roi_context_section = SectionCard("ROI Context")
        roi_context_section.setObjectName("stats_roi_context_section")
        roi_context_section.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        roi_context_section.content_layout.setSpacing(6)
        roi_context_section.content_layout.addWidget(self.lbl_rois)

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
        self.reporting_summary_text.setFont(fixed_width_font())
        self.reporting_summary_text.hide()

        self.copy_summary_btn = make_action_button("Copy summary")
        self.copy_summary_btn.clicked.connect(self._copy_summary_text)

        output_container = QWidget()
        output_container.setObjectName("stats_summary_output_container")
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(6)
        output_header_widget = QWidget(output_container)
        output_header_layout = QHBoxLayout(output_header_widget)
        output_header_layout.setContentsMargins(0, 0, 0, 0)
        output_header_layout.setSpacing(8)
        output_header_layout.addWidget(SubsectionHeaderLabel("Significant Results Summary:"))
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
        self.stats_tool_info_btn = make_info_button(
            parent=file_box,
            tooltip="About Statistical Analysis",
            object_name="stats_tool_info_btn",
        )
        self.stats_tool_info_btn.clicked.connect(
            lambda: show_tool_info(self, STATS_TOOL_INFO)
        )
        file_box.header.add_action_widget(self.stats_tool_info_btn)
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

        advanced_page = QWidget()
        advanced_page.setObjectName("stats_advanced_setup_page")
        advanced_layout_page = QVBoxLayout(advanced_page)
        advanced_layout_page.setContentsMargins(0, 0, 0, 0)
        advanced_layout_page.setSpacing(10)

        advanced_top_row = QWidget()
        advanced_top_row.setObjectName("stats_advanced_screening_export_row")
        advanced_top_layout = QHBoxLayout(advanced_top_row)
        advanced_top_layout.setContentsMargins(0, 0, 0, 0)
        advanced_top_layout.setSpacing(10)
        advanced_top_layout.addWidget(outlier_section, 1)
        advanced_top_layout.addWidget(comparison_exports_section, 1)

        advanced_bottom_row = QWidget()
        advanced_bottom_row.setObjectName("stats_advanced_context_row")
        advanced_bottom_layout = QHBoxLayout(advanced_bottom_row)
        advanced_bottom_layout.setContentsMargins(0, 0, 0, 0)
        advanced_bottom_layout.setSpacing(10)
        advanced_bottom_layout.addWidget(last_export_section, 1)
        advanced_bottom_layout.addWidget(roi_context_section, 1)

        advanced_layout_page.addWidget(self.dv_group)
        advanced_layout_page.addWidget(advanced_top_row)
        advanced_layout_page.addWidget(advanced_bottom_row)
        advanced_layout_page.addStretch(1)

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
        self.setup_tabs.addTab(advanced_page, "Advanced")
        self.setup_tabs.currentChanged.connect(self._sync_summary_output_visibility)
        setup_layout.addWidget(self.setup_tabs, 1)

        self.stats_processing_notice = SectionCard("Stats analysis in progress")
        self.stats_processing_notice.setObjectName("stats_processing_notice")
        self.stats_processing_notice.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        )
        processing_notice_layout = QHBoxLayout()
        processing_notice_layout.setContentsMargins(0, 0, 0, 0)
        processing_notice_layout.setSpacing(14)
        self.stats_processing_animation = BrainPulseWidget(self.stats_processing_notice)
        self.stats_processing_animation.setObjectName("stats_processing_brain_animation")
        processing_notice_layout.addWidget(
            self.stats_processing_animation,
            0,
            Qt.AlignVCenter,
        )
        self.stats_processing_message = QLabel(
            "FPVS Toolbox is currently calculating an average FFT spectrum across "
            "all electrodes and participants to determine which harmonics are "
            "considered statistically significant. This could take a few minutes."
        )
        self.stats_processing_message.setObjectName("stats_processing_message")
        self.stats_processing_message.setWordWrap(True)
        self.stats_processing_message.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        )
        processing_notice_layout.addWidget(self.stats_processing_message, 1)
        self.stats_processing_notice.content_layout.addLayout(processing_notice_layout)
        self.stats_processing_notice.hide()
        self.stats_processing_animation.stop()
        setup_layout.addWidget(self.stats_processing_notice)

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
        self.root_splitter = root_splitter
        self.summary_output_container = output_container

        main_layout.addWidget(root_splitter, 1)

        # initialize export buttons
        self._update_export_buttons()
        self._populate_conditions_panel([])
        self._sync_summary_output_visibility()

    # --------------------------- actions ---------------------------

    def _auto_export_reporting_summary_enabled(self) -> bool:
        action = getattr(self, "reporting_summary_export_action", None)
        return bool(action is None or action.isChecked())

    def _sync_summary_output_visibility(self, *_args) -> None:
        """Show Basic-only summary and run controls only on the Basic tab."""
        tabs = getattr(self, "setup_tabs", None)
        output = getattr(self, "summary_output_container", None)
        action_bar = getattr(self, "run_action_bar", None)
        splitter = getattr(self, "root_splitter", None)
        if tabs is None or output is None:
            return
        show_basic_controls = tabs.currentIndex() == 0
        output.setVisible(show_basic_controls)
        if action_bar is not None:
            action_bar.setVisible(show_basic_controls)
        if splitter is not None:
            splitter.setSizes([620, 200] if show_basic_controls else [820, 0])
