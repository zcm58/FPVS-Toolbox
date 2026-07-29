"""UI assembly for StatsWindow."""
# ruff: noqa: F405
from __future__ import annotations

from PySide6.QtWidgets import QProgressBar

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
        self.analyze_single_btn.clicked.connect(self._on_primary_analysis_clicked)

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
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.pipeline_phase_label = QLabel("Ready")
        self.pipeline_phase_label.setObjectName("stats_pipeline_phase_label")
        self.pipeline_phase_label.setMinimumWidth(150)
        self.pipeline_phase_label.setToolTip(
            "Current structured analysis phase. Detailed messages remain in Run log."
        )

        self.pipeline_progress_bar = QProgressBar()
        self.pipeline_progress_bar.setObjectName("stats_pipeline_progress_bar")
        self.pipeline_progress_bar.setRange(0, 100)
        self.pipeline_progress_bar.setValue(0)
        self.pipeline_progress_bar.setFormat("%p%")
        self.pipeline_progress_bar.setTextVisible(True)
        self.pipeline_progress_bar.setToolTip(
            "Progress through the currently active statistical pipeline."
        )

        self.cancel_analysis_btn = make_action_button(
            "Cancel",
            variant="danger",
            compact=True,
        )
        self.cancel_analysis_btn.setObjectName("stats_cancel_analysis_button")
        self.cancel_analysis_btn.setEnabled(False)
        self.cancel_analysis_btn.setToolTip(
            "Request cancellation after the current safe worker checkpoint."
        )
        self.cancel_analysis_btn.clicked.connect(self._on_cancel_analysis_clicked)

        self.pipeline_status_area = QWidget()
        self.pipeline_status_area.setObjectName("stats_pipeline_status_area")
        pipeline_status_layout = QVBoxLayout(self.pipeline_status_area)
        pipeline_status_layout.setContentsMargins(0, 0, 0, 0)
        pipeline_status_layout.setSpacing(6)
        pipeline_status_layout.addWidget(self.lbl_status)
        pipeline_progress_row = QHBoxLayout()
        pipeline_progress_row.setContentsMargins(0, 0, 0, 0)
        pipeline_progress_row.setSpacing(8)
        pipeline_progress_row.addWidget(self.pipeline_phase_label)
        pipeline_progress_row.addWidget(self.pipeline_progress_bar, 1)
        pipeline_progress_row.addWidget(self.cancel_analysis_btn)
        pipeline_status_layout.addLayout(pipeline_progress_row)

        self.inference_settings_group = SectionCard("Inference Settings")
        self.inference_settings_group.setObjectName("stats_inference_settings_group")
        self.inference_settings_group.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        )
        inference_layout = self.inference_settings_group.content_layout
        inference_layout.setSpacing(8)
        inference_grid = QGridLayout()
        inference_grid.setContentsMargins(0, 0, 0, 0)
        inference_grid.setHorizontalSpacing(10)
        inference_grid.setVerticalSpacing(6)

        self.analysis_profile_combo = QComboBox()
        self.analysis_profile_combo.setObjectName("stats_analysis_profile_combo")
        self.analysis_profile_combo.addItem(
            "Published-style exploratory",
            "published_style_exploratory",
        )
        self.analysis_profile_combo.addItem("Confirmatory", "confirmatory")
        self.analysis_profile_combo.setToolTip(
            "Choose how results will be interpreted. A profile change never overrides "
            "the recorded harmonic-selection provenance."
        )
        inference_grid.addWidget(QLabel("Analysis profile:"), 0, 0)
        inference_grid.addWidget(self.analysis_profile_combo, 0, 1)

        self.group_pair_label = QLabel("Groups to compare:")
        self.group_pair_label.setObjectName("stats_group_pair_label")
        self.group_pair_combo = QComboBox()
        self.group_pair_combo.setObjectName("stats_group_pair_combo")
        self.group_pair_combo.addItem(
            "Scan project groups to choose a comparison",
            None,
        )
        self.group_pair_combo.setEnabled(False)
        self.group_pair_combo.setToolTip(
            "Choose the explicit canonical group pair used for cell contrasts. "
            "A choice is required when the project contains more than two groups."
        )
        inference_grid.addWidget(self.group_pair_label, 0, 2)
        inference_grid.addWidget(self.group_pair_combo, 0, 3)

        self.multiplicity_combo = QComboBox()
        self.multiplicity_combo.setObjectName("stats_multiplicity_combo")
        self.multiplicity_combo.addItem("Holm (family-wise)", "holm")
        self.multiplicity_combo.addItem(
            "Benjamini-Hochberg FDR",
            "fdr_bh",
        )
        self.multiplicity_combo.setToolTip(
            "Adjust related tests as one declared family. Holm is the default "
            "family-wise correction; FDR is an exploratory discovery option. "
            "Max-|t| results are reported separately as a resampling sensitivity."
        )
        inference_grid.addWidget(QLabel("Multiplicity:"), 1, 0)
        inference_grid.addWidget(self.multiplicity_combo, 1, 1)

        self.response_alternative_combo = QComboBox()
        self.response_alternative_combo.setObjectName(
            "stats_response_alternative_combo"
        )
        self.response_alternative_combo.addItem("Two-sided", "two_sided")
        self.response_alternative_combo.addItem(
            "Greater than zero",
            "greater",
        )
        self.response_alternative_combo.setToolTip(
            "Use a directional response test only when it was justified before "
            "examining these data."
        )
        inference_grid.addWidget(QLabel("Response alternative:"), 1, 2)
        inference_grid.addWidget(self.response_alternative_combo, 1, 3)

        self.analysis_scope_combo = QComboBox()
        self.analysis_scope_combo.setObjectName("stats_analysis_scope_combo")
        self.analysis_scope_combo.addItem(
            "Primary complete core",
            "complete_core",
        )
        self.analysis_scope_combo.setEnabled(False)
        self.analysis_scope_combo.setToolTip(
            "The primary analysis retains only conditions contributed by every "
            "included participant. A secondary available-case model is not run "
            "by the current native pipeline."
        )
        inference_grid.addWidget(QLabel("Analysis scope:"), 2, 0)
        inference_grid.addWidget(self.analysis_scope_combo, 2, 1)

        self.resample_count_spin = QSpinBox()
        self.resample_count_spin.setObjectName("stats_resample_count_spin")
        self.resample_count_spin.setRange(1, 100_000)
        self.resample_count_spin.setValue(9_999)
        self.resample_count_spin.setSingleStep(1_000)
        self.resample_count_spin.setGroupSeparatorShown(True)
        self.resample_count_spin.setToolTip(
            "Requested Monte Carlo draws when exact participant-level enumeration "
            "is not feasible."
        )
        inference_grid.addWidget(QLabel("Resampling draws:"), 2, 2)
        inference_grid.addWidget(self.resample_count_spin, 2, 3)

        self.strict_omnibus_family_checkbox = QCheckBox(
            "Require a supported omnibus effect before follow-up families"
        )
        self.strict_omnibus_family_checkbox.setObjectName(
            "stats_strict_omnibus_family_checkbox"
        )
        self.strict_omnibus_family_checkbox.setChecked(True)
        self.strict_omnibus_family_checkbox.setToolTip(
            "Keep follow-up interpretation within the declared omnibus-testing strategy."
        )
        inference_grid.addWidget(
            self.strict_omnibus_family_checkbox,
            3,
            0,
            1,
            2,
        )

        self.independent_selection_attestation = QCheckBox(
            "The fixed harmonic list was selected independently of these participants"
        )
        self.independent_selection_attestation.setObjectName(
            "stats_independent_selection_attestation"
        )
        self.independent_selection_attestation.setToolTip(
            "Use only for a prespecified or externally selected fixed list. This "
            "cannot make the canonical same-sample adaptive list independent."
        )
        self.independent_selection_attestation.toggled.connect(
            self._sync_provenance_warning
        )
        inference_grid.addWidget(
            self.independent_selection_attestation,
            3,
            2,
            1,
            2,
        )

        sensitivity_row = QWidget()
        sensitivity_row.setObjectName("stats_sensitivity_selection_row")
        sensitivity_layout = QHBoxLayout(sensitivity_row)
        sensitivity_layout.setContentsMargins(0, 0, 0, 0)
        sensitivity_layout.setSpacing(12)
        sensitivity_layout.addWidget(QLabel("Sensitivity analyses:"))

        self.robust_sensitivity_checkbox = QCheckBox("Robust")
        self.robust_sensitivity_checkbox.setObjectName(
            "stats_robust_sensitivity_checkbox"
        )
        self.robust_sensitivity_checkbox.setChecked(True)
        sensitivity_layout.addWidget(self.robust_sensitivity_checkbox)

        self.resampling_sensitivity_checkbox = QCheckBox("Resampling")
        self.resampling_sensitivity_checkbox.setObjectName(
            "stats_resampling_sensitivity_checkbox"
        )
        self.resampling_sensitivity_checkbox.setChecked(True)
        sensitivity_layout.addWidget(self.resampling_sensitivity_checkbox)

        self.stability_sensitivity_checkbox = QCheckBox("Leave-one-out stability")
        self.stability_sensitivity_checkbox.setObjectName(
            "stats_stability_sensitivity_checkbox"
        )
        self.stability_sensitivity_checkbox.setChecked(True)
        sensitivity_layout.addWidget(self.stability_sensitivity_checkbox)
        sensitivity_layout.addStretch(1)
        inference_layout.addLayout(inference_grid)
        inference_layout.addWidget(sensitivity_row)

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

        self.roi_context_text = QTextEdit()
        self.roi_context_text.setObjectName("stats_roi_context_text")
        self.roi_context_text.setReadOnly(True)
        self.roi_context_text.setAcceptRichText(True)
        self.roi_context_text.setPlaceholderText("ROI context will appear here after Settings are loaded.")
        self.roi_context_text.setMinimumHeight(128)
        self.roi_context_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.roi_context_text.document().setDocumentMargin(8)
        self.roi_context_text.setToolTip(
            "ROIs loaded from Settings. Update ROI definitions in Settings to change this list."
        )
        self.lbl_rois = self.roi_context_text

        roi_context_section = SectionCard("ROI Context")
        roi_context_section.setObjectName("stats_roi_context_section")
        roi_context_section.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred))
        roi_context_section.content_layout.setSpacing(6)
        roi_context_section.content_layout.addWidget(self.roi_context_text, 1)

        # output pane
        self.summary_text = QTextEdit()
        self.summary_text.setProperty("logSurface", True)
        self.summary_text.setObjectName("stats_at_a_glance_text")
        self.summary_text.setReadOnly(True)
        self.summary_text.setAcceptRichText(True)
        self.summary_text.setPlaceholderText(
            "A plain-language result summary will appear here after analysis."
        )
        self.summary_text.setMinimumHeight(140)
        self.summary_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.log_text = QPlainTextEdit(self)
        self.log_text.setProperty("logSurface", True)
        self.log_text.setObjectName("stats_run_log_text")
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText(
            "Worker phases, warnings, export messages, and errors will appear here."
        )
        self.log_text.setMinimumHeight(140)
        self.log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.reporting_summary_text = QPlainTextEdit(self)
        self.reporting_summary_text.setProperty("logSurface", True)
        self.reporting_summary_text.setObjectName("stats_methods_checks_text")
        self.reporting_summary_text.setReadOnly(True)
        self.reporting_summary_text.setPlaceholderText(
            "Methods, assumptions, multiplicity corrections, provenance, and "
            "diagnostic checks will appear here."
        )
        self.reporting_summary_text.setFont(fixed_width_font())

        self.copy_summary_btn = make_action_button("Copy at-a-glance")
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
        output_header_layout.addWidget(SubsectionHeaderLabel("Analysis Results"))
        output_header_layout.addStretch(1)

        output_header = ActionRow(output_header_widget, alignment=Qt.AlignRight)
        output_header.setObjectName("stats_output_copy_actions")
        output_header.add_button(self.copy_summary_btn)
        output_header_layout.addWidget(output_header)

        output_layout.addWidget(output_header_widget)
        self.results_tabs = QTabWidget()
        self.results_tabs.setObjectName("stats_results_tabs")
        self.results_tabs.setDocumentMode(True)
        self.results_tabs.setStyleSheet(
            """
            QTabWidget#stats_results_tabs::pane {
                border: 0;
                background: transparent;
            }
            QTabWidget#stats_results_tabs > QWidget {
                background: transparent;
            }
            """
        )
        self.results_tabs.addTab(self.summary_text, "At a glance")
        self.results_tabs.addTab(self.reporting_summary_text, "Methods & checks")
        self.results_tabs.addTab(self.log_text, "Run log")
        output_layout.addWidget(self.results_tabs, 1)

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

        self.analysis_design_group = SectionCard("Analysis Design")
        self.analysis_design_group.setObjectName("stats_analysis_design_group")
        self.analysis_design_group.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        )
        analysis_design_layout = self.analysis_design_group.content_layout
        analysis_design_layout.setSpacing(7)

        self.analysis_mode_banner = StatusBanner(
            "Single Group",
            self.analysis_design_group,
            variant="info",
        )
        self.analysis_mode_banner.setObjectName("stats_analysis_mode_banner")
        self.analysis_mode_value = self.analysis_mode_banner.label
        self.analysis_mode_value.setObjectName("stats_analysis_mode_value")
        analysis_design_layout.addWidget(self.analysis_mode_banner)

        analysis_design_form = make_form_layout()
        self.analysis_profile_value = QLabel("Published-style exploratory")
        self.analysis_profile_value.setObjectName("stats_analysis_profile_value")
        self.analysis_profile_value.setWordWrap(True)
        self.analysis_profile_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        analysis_design_form.addRow("Profile:", self.analysis_profile_value)

        self.analysis_group_value = QLabel("One pooled group; scan to confirm participant N.")
        self.analysis_group_value.setObjectName("stats_analysis_group_value")
        self.analysis_group_value.setWordWrap(True)
        self.analysis_group_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        analysis_design_form.addRow("Groups:", self.analysis_group_value)

        self.analysis_coverage_value = QLabel(
            "Scan the data folder to calculate participant and complete-core "
            "condition coverage."
        )
        self.analysis_coverage_value.setObjectName("stats_analysis_coverage_value")
        self.analysis_coverage_value.setWordWrap(True)
        self.analysis_coverage_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        analysis_design_form.addRow("Primary coverage:", self.analysis_coverage_value)
        analysis_design_layout.addLayout(analysis_design_form)

        analysis_design_note = QLabel(
            "Primary inference uses the frozen participant cohort and only conditions "
            "with one finite value for every selected ROI and participant."
        )
        analysis_design_note.setObjectName("stats_analysis_design_note")
        analysis_design_note.setWordWrap(True)
        analysis_design_layout.addWidget(analysis_design_note)

        basic_page = QWidget()
        basic_page.setObjectName("stats_basic_setup_page")
        basic_layout = QVBoxLayout(basic_page)
        basic_layout.setContentsMargins(0, 0, 0, 0)
        basic_layout.setSpacing(8)
        basic_layout.addWidget(file_box)
        basic_layout.addWidget(self.analysis_design_group)

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

        advanced_layout_page.addWidget(self.inference_settings_group)
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

        self.provenance_warning = StatusBanner(
            "",
            setup_area,
            variant="warning",
        )
        self.provenance_warning.setObjectName("stats_provenance_warning")
        self.provenance_warning.setToolTip(
            "Harmonic-selection provenance changes how response-versus-zero "
            "p-values may be interpreted."
        )
        setup_layout.addWidget(self.provenance_warning)

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
        setup_layout.addWidget(self.pipeline_status_area)

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

    def set_pipeline_progress(
        self,
        phase: str,
        completed: int | float | None = None,
        total: int | float | None = None,
        *,
        percent: int | float | None = None,
    ) -> None:
        """Render one structured pipeline phase/progress update."""
        self.pipeline_phase_label.setText(str(phase or "Running"))
        if percent is None and completed is not None and total not in {None, 0}:
            percent = (float(completed) / float(total)) * 100.0
        if percent is None:
            self.pipeline_progress_bar.setRange(0, 0)
            return
        bounded = max(0, min(100, int(round(float(percent)))))
        self.pipeline_progress_bar.setRange(0, 100)
        self.pipeline_progress_bar.setValue(bounded)

    def set_pipeline_running(
        self,
        running: bool,
        *,
        phase: str | None = None,
        cancellable: bool | None = None,
    ) -> None:
        """Update presentation state for a running or terminal pipeline."""
        is_running = bool(running)
        can_cancel = is_running if cancellable is None else is_running and bool(cancellable)
        self.cancel_analysis_btn.setVisible(True)
        self.cancel_analysis_btn.setEnabled(can_cancel)
        if phase:
            self.pipeline_phase_label.setText(str(phase))
        elif is_running:
            self.pipeline_phase_label.setText("Starting analysis")
        else:
            self.pipeline_phase_label.setText("Ready")
        if is_running:
            self.pipeline_progress_bar.setRange(0, 0)
        elif self.pipeline_progress_bar.maximum() == 0:
            self.pipeline_progress_bar.setRange(0, 100)
            self.pipeline_progress_bar.setValue(0)

    def _sync_summary_output_visibility(self, *_args) -> None:
        """Keep the shared run controls and result tabs visible in either setup tab."""
        output = getattr(self, "summary_output_container", None)
        action_bar = getattr(self, "run_action_bar", None)
        splitter = getattr(self, "root_splitter", None)
        if output is None:
            return
        output.setVisible(True)
        if action_bar is not None:
            action_bar.setVisible(True)
        if splitter is not None:
            splitter.setSizes([620, 200])
