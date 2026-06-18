"""Widget assembly helpers for the Ratio Calculator GUI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QTableWidget,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from Main_App.gui.components import (
    ActionRow,
    PathPickerRow,
    SectionCard,
    StatusBanner,
    SubsectionHeaderLabel,
    apply_font_role,
    make_action_button,
    make_form_layout,
)


class RatioSectionsMixin:
    """GUI-only widget construction and button presentation helpers."""

    def _build_basic_tab(self) -> None:
        layout = QVBoxLayout(self.basic_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        cond_group = QWidget()
        cond_group.setObjectName("ratio_calculator_conditions")
        cond_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        cond_group_layout = QVBoxLayout(cond_group)
        cond_group_layout.setContentsMargins(0, 0, 0, 0)
        cond_group_layout.setSpacing(6)
        cond_layout = QGridLayout()
        cond_layout.setContentsMargins(0, 0, 0, 0)
        cond_layout.setHorizontalSpacing(12)
        cond_layout.setVerticalSpacing(7)

        self.condition_a_combo = QComboBox()
        self.condition_a_combo.currentTextChanged.connect(self._on_condition_a_selected)
        self.refresh_btn = make_action_button("Refresh", compact=True, parent=cond_group)
        self.refresh_btn.clicked.connect(self._refresh_conditions)
        self.swap_btn = make_action_button("Swap A/B", compact=True, parent=cond_group)
        self.swap_btn.clicked.connect(self._swap_conditions)

        (
            self.input_a_row,
            self.input_a_edit,
            self.input_a_open_btn,
            self.input_a_btn,
        ) = self._make_folder_path_row(
            cond_group,
            row_name="ratio_calculator_input_a_row",
            actions_name="ratio_calculator_input_a_actions",
            placeholder="Select condition A folder",
        )
        self.input_a_open_btn.clicked.connect(lambda: self._open_folder_from_edit(self.input_a_edit))
        self.input_a_btn.clicked.connect(
            lambda: self._browse_folder(self.input_a_edit, is_output=False, condition_key="a")
        )

        self.label_a_edit = QLineEdit()
        self.label_a_edit.setPlaceholderText("Condition A label")
        self.label_a_edit.textEdited.connect(self._mark_label_a_dirty)
        self.label_a_edit.textChanged.connect(self._on_label_text_changed)

        self.condition_b_combo = QComboBox()
        self.condition_b_combo.currentTextChanged.connect(self._on_condition_b_selected)

        (
            self.input_b_row,
            self.input_b_edit,
            self.input_b_open_btn,
            self.input_b_btn,
        ) = self._make_folder_path_row(
            cond_group,
            row_name="ratio_calculator_input_b_row",
            actions_name="ratio_calculator_input_b_actions",
            placeholder="Select condition B folder",
        )
        self.input_b_open_btn.clicked.connect(lambda: self._open_folder_from_edit(self.input_b_edit))
        self.input_b_btn.clicked.connect(
            lambda: self._browse_folder(self.input_b_edit, is_output=False, condition_key="b")
        )

        self.label_b_edit = QLineEdit()
        self.label_b_edit.setPlaceholderText("Condition B label")
        self.label_b_edit.textEdited.connect(self._mark_label_b_dirty)
        self.label_b_edit.textChanged.connect(self._on_label_text_changed)

        (
            self.output_path_row,
            self.output_edit,
            self.output_open_btn,
            self.output_btn,
        ) = self._make_folder_path_row(
            cond_group,
            row_name="ratio_calculator_output_row",
            actions_name="ratio_calculator_output_actions",
            placeholder="Select output folder",
        )
        self.output_open_btn.clicked.connect(lambda: self._open_folder_from_edit(self.output_edit))
        self.output_btn.clicked.connect(lambda: self._browse_folder(self.output_edit, is_output=True))

        self.run_label_edit = QLineEdit()
        self.run_label_edit.setPlaceholderText("Run label")
        self.run_label_edit.textEdited.connect(self._mark_run_label_dirty)

        self.validation_label = StatusBanner("", variant="error")
        self.validation_label.setVisible(False)

        condition_actions = ActionRow(cond_group, alignment=Qt.AlignLeft, spacing=6)
        condition_actions.setObjectName("ratio_calculator_condition_actions")
        condition_actions.add_button(self.refresh_btn)
        condition_actions.add_button(self.swap_btn)
        condition_b_header = QWidget(cond_group)
        condition_b_header_layout = QHBoxLayout(condition_b_header)
        condition_b_header_layout.setContentsMargins(0, 0, 0, 0)
        condition_b_header_layout.setSpacing(6)
        condition_b_header_layout.addWidget(self._make_caption_label("Condition B"))
        condition_b_header_layout.addStretch(1)
        condition_b_header_layout.addWidget(condition_actions)

        cond_layout.addWidget(self._make_caption_label("Condition A"), 0, 0)
        cond_layout.addWidget(condition_b_header, 0, 1)
        cond_layout.addWidget(self.condition_a_combo, 1, 0)
        cond_layout.addWidget(self.condition_b_combo, 1, 1)
        cond_layout.addWidget(self._make_caption_label("Condition A Folder"), 2, 0)
        cond_layout.addWidget(self._make_caption_label("Condition B Folder"), 2, 1)
        cond_layout.addWidget(self.input_a_row, 3, 0)
        cond_layout.addWidget(self.input_b_row, 3, 1)
        cond_layout.addWidget(self._make_caption_label("Condition A Label"), 4, 0)
        cond_layout.addWidget(self._make_caption_label("Condition B Label"), 4, 1)
        cond_layout.addWidget(self.label_a_edit, 5, 0)
        cond_layout.addWidget(self.label_b_edit, 5, 1)
        cond_layout.addWidget(self.validation_label, 6, 0, 1, 2)
        cond_layout.setColumnStretch(0, 1)
        cond_layout.setColumnStretch(1, 1)
        cond_group_layout.addLayout(cond_layout)

        for button in (
            self.input_a_open_btn,
            self.input_a_btn,
            self.input_b_open_btn,
            self.input_b_btn,
            self.output_open_btn,
            self.output_btn,
        ):
            button.setMinimumHeight(30)
        for field in (
            self.condition_a_combo,
            self.condition_b_combo,
            self.input_a_edit,
            self.input_b_edit,
            self.label_a_edit,
            self.label_b_edit,
        ):
            field.setMinimumHeight(30)

        layout.addWidget(cond_group)

        participants_group = SectionCard(
            "Participant exclusions (optional)",
            object_name="ratio_calculator_participants",
        )
        participants_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        participants_layout = participants_group.content_layout
        participants_group.setToolTip(
            "Checked participants are excluded from group summaries and distribution overlays. "
            "They still appear in *_ALL* sheets and keep the excluded marker in plots."
        )
        counts_row = QHBoxLayout()
        self.participant_counts = QLabel("A: 0 | B: 0 | Paired: 0")
        self.exclusion_status = QLabel("Excluded: 0 / Paired: 0 \u2192 Used: 0")
        self.exclusion_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        counts_row.addWidget(self.participant_counts)
        counts_row.addStretch(1)
        counts_row.addWidget(self.exclusion_status)
        participants_layout.addLayout(counts_row)

        filter_row = QHBoxLayout()
        self.participant_filter_edit = QLineEdit()
        self.participant_filter_edit.setPlaceholderText("Search participant IDs...")
        self.participant_filter_edit.textChanged.connect(self._apply_participant_filter)
        self.show_excluded_check = QCheckBox("Show only excluded")
        self.show_excluded_check.toggled.connect(self._apply_participant_filter)
        filter_row.addWidget(self.participant_filter_edit)
        filter_row.addWidget(self.show_excluded_check)
        filter_row.addStretch(1)
        participants_layout.addLayout(filter_row)

        self.exclude_table = QTableWidget()
        self.exclude_table.setColumnCount(2)
        self.exclude_table.setHorizontalHeaderLabels(["Exclude", "Participant ID"])
        self.exclude_table.verticalHeader().setVisible(False)
        self.exclude_table.setSelectionMode(QTableWidget.NoSelection)
        self.exclude_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.exclude_table.setAlternatingRowColors(True)
        header = self.exclude_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.exclude_table.setColumnWidth(0, 70)
        apply_font_role(header, "table_header")
        self.exclude_table.itemChanged.connect(self._on_exclusion_item_changed)
        participants_layout.addWidget(self.exclude_table)

        self.select_all_btn = make_action_button("Exclude all", compact=True, parent=participants_group)
        self.select_all_btn.clicked.connect(self._confirm_exclude_all)
        self.select_none_btn = make_action_button("Exclude none", compact=True, parent=participants_group)
        self.select_none_btn.clicked.connect(lambda: self._set_all_exclusions(False))
        self.clear_exclusions_btn = make_action_button("Clear exclusions", compact=True, parent=participants_group)
        self.clear_exclusions_btn.clicked.connect(lambda: self._set_all_exclusions(False))
        participant_actions = ActionRow(participants_group, alignment=Qt.AlignLeft)
        participant_actions.setObjectName("ratio_calculator_participant_actions")
        participant_actions.add_button(self.select_all_btn)
        participant_actions.add_button(self.select_none_btn)
        participant_actions.add_button(self.clear_exclusions_btn)
        participant_actions.row_layout.addStretch(1)
        participants_layout.addWidget(participant_actions)

        roi_group = SectionCard("ROIs (read-only)", object_name="ratio_calculator_rois")
        roi_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        roi_layout = roi_group.content_layout
        self.roi_table = QTableWidget()
        self.roi_table.setColumnCount(2)
        self.roi_table.setHorizontalHeaderLabels(["ROI", "Electrodes"])
        self.roi_table.verticalHeader().setVisible(False)
        self.roi_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.roi_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.roi_table.setRowCount(0)
        self.roi_table.setAlternatingRowColors(True)
        self.roi_table.setWordWrap(True)
        self.roi_table.setTextElideMode(Qt.ElideRight)
        header = self.roi_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)

        roi_layout.addWidget(self.roi_table)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(participants_group)
        splitter.addWidget(roi_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 320])
        layout.addWidget(splitter, 1)

        for widget in [
            self.input_a_edit,
            self.input_b_edit,
            self.output_edit,
            self.label_a_edit,
            self.label_b_edit,
            self.run_label_edit,
        ]:
            widget.textChanged.connect(self._update_run_state)

    @staticmethod
    def _make_caption_label(text: str) -> SubsectionHeaderLabel:
        return SubsectionHeaderLabel(text)

    @staticmethod
    def _make_folder_path_row(
        parent: QWidget,
        *,
        row_name: str,
        actions_name: str,
        placeholder: str,
    ) -> tuple[PathPickerRow, QLineEdit, QPushButton, QPushButton]:
        row = PathPickerRow(
            "Browse...",
            parent,
            placeholder=placeholder,
            read_only=True,
            compact_button=True,
        )
        row.setObjectName(row_name)
        row.row_layout.setSpacing(6)
        row.setMinimumHeight(34)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.line_edit.setMinimumHeight(30)

        browse_button = row.button
        row.row_layout.removeWidget(browse_button)
        open_button = make_action_button("Open", compact=True, parent=row)
        actions = ActionRow(row, alignment=Qt.AlignLeft, spacing=6)
        actions.setObjectName(actions_name)
        actions.add_button(open_button)
        actions.add_button(browse_button)
        row.row_layout.addWidget(actions)
        return row, row.line_edit, open_button, browse_button

    def _apply_button_styling(self) -> None:
        buttons = [
            self.refresh_btn,
            self.swap_btn,
            self.input_a_open_btn,
            self.input_a_btn,
            self.input_b_open_btn,
            self.input_b_btn,
            self.output_open_btn,
            self.output_btn,
            self.select_all_btn,
            self.select_none_btn,
            self.clear_exclusions_btn,
            self.run_btn,
            self.open_output_btn,
            self.copy_log_btn,
            self.log_toggle_btn,
        ]
        for button in buttons:
            button.setMinimumHeight(28)
            apply_font_role(button, "button_strong")
        for button in (
            self.input_a_open_btn,
            self.input_a_btn,
            self.input_b_open_btn,
            self.input_b_btn,
            self.output_open_btn,
            self.output_btn,
        ):
            button.setMinimumHeight(30)
        self.run_btn.setMinimumWidth(90)

    def _build_advanced_tab(self) -> None:
        layout = QVBoxLayout(self.advanced_tab)
        settings_group = SectionCard(
            "Harmonic settings",
            object_name="ratio_calculator_harmonic_settings",
        )
        form = make_form_layout()

        self.oddball_spin = QDoubleSpinBox()
        self.oddball_spin.setDecimals(3)
        self.oddball_spin.setRange(0.1, 100.0)
        self.oddball_spin.setValue(1.2)

        self.sum_up_spin = QDoubleSpinBox()
        self.sum_up_spin.setDecimals(3)
        self.sum_up_spin.setRange(0.1, 200.0)
        self.sum_up_spin.setValue(16.8)

        self.excluded_edit = QLineEdit("6.0, 12.0, 18.0, 24.0")
        self.excluded_edit.setPlaceholderText("Comma-separated frequencies")

        self.palette_combo = QComboBox()
        self.palette_combo.addItems(["vibrant", "muted", "colorblind_safe"])

        self.png_dpi_spin = QSpinBox()
        self.png_dpi_spin.setRange(600, 600)
        self.png_dpi_spin.setValue(600)

        self.use_stable_ylims_check = QCheckBox("Use stable y-limits")
        self.use_stable_ylims_check.setChecked(True)

        self.ylim_raw_z_edit = QLineEdit()
        self.ylim_raw_snr_edit = QLineEdit()
        self.ylim_raw_bca_edit = QLineEdit()
        self.ylim_ratio_z_edit = QLineEdit()
        self.ylim_ratio_snr_edit = QLineEdit()
        self.ylim_ratio_bca_edit = QLineEdit()

        for edit in [
            self.ylim_raw_z_edit,
            self.ylim_raw_snr_edit,
            self.ylim_raw_bca_edit,
            self.ylim_ratio_z_edit,
            self.ylim_ratio_snr_edit,
            self.ylim_ratio_bca_edit,
        ]:
            edit.setPlaceholderText("auto or min,max")

        form.addRow("Oddball base (Hz):", self.oddball_spin)
        form.addRow("Sum up to (Hz):", self.sum_up_spin)
        form.addRow("Excluded freqs (Hz):", self.excluded_edit)
        form.addRow("Palette:", self.palette_combo)
        form.addRow("Figure DPI:", self.png_dpi_spin)
        form.addRow(self.use_stable_ylims_check)
        form.addRow("YLIM raw Z:", self.ylim_raw_z_edit)
        form.addRow("YLIM raw SNR:", self.ylim_raw_snr_edit)
        form.addRow("YLIM raw BCA:", self.ylim_raw_bca_edit)
        form.addRow("YLIM ratio Z:", self.ylim_ratio_z_edit)
        form.addRow("YLIM ratio SNR:", self.ylim_ratio_snr_edit)
        form.addRow("YLIM ratio BCA:", self.ylim_ratio_bca_edit)
        settings_group.content_layout.addLayout(form)

        layout.addWidget(settings_group)
        layout.addStretch(1)

    def _build_bottom_panel(self) -> QWidget:
        panel = SectionCard("Run", object_name="ratio_calculator_run")
        panel.header.setVisible(False)
        panel.shell_layout.setSpacing(6)
        layout = panel.content_layout
        layout.setSpacing(6)

        output_row = QWidget(panel)
        output_row.setObjectName("ratio_calculator_run_output_row")
        output_layout = QGridLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setHorizontalSpacing(12)
        output_layout.setVerticalSpacing(4)
        output_layout.addWidget(self._make_caption_label("Output Folder"), 0, 0)
        output_layout.addWidget(self._make_caption_label("Run Label"), 0, 1)
        output_layout.addWidget(self.output_path_row, 1, 0)
        output_layout.addWidget(self.run_label_edit, 1, 1)
        output_layout.setColumnStretch(0, 3)
        output_layout.setColumnStretch(1, 1)
        layout.addWidget(output_row)

        self.run_btn = make_action_button("Run", variant="primary", parent=panel)
        self.run_btn.clicked.connect(self._start_run)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.status_label = StatusBanner("Ready", parent=panel)
        run_row = ActionRow(panel, alignment=Qt.AlignLeft)
        run_row.setObjectName("ratio_calculator_run_actions")
        run_row.add_button(self.run_btn)
        run_row.row_layout.addWidget(self.progress, 2)
        run_row.row_layout.addWidget(self.status_label)
        layout.addWidget(run_row)

        self.open_output_btn = make_action_button("Open output folder", compact=True, parent=panel)
        self.open_output_btn.setEnabled(False)
        self.open_output_btn.clicked.connect(self._open_output_folder)
        self.copy_log_btn = make_action_button("Copy log", compact=True, parent=panel)
        self.copy_log_btn.clicked.connect(self._copy_log)
        self.log_toggle_btn = make_action_button("Open log", variant="tertiary", compact=True, parent=panel)
        self.log_toggle_btn.clicked.connect(self._show_log_dialog)
        bottom_actions = ActionRow(panel, alignment=Qt.AlignLeft)
        bottom_actions.setObjectName("ratio_calculator_bottom_actions")
        bottom_actions.add_button(self.open_output_btn)
        bottom_actions.add_button(self.copy_log_btn)
        bottom_actions.row_layout.addWidget(self.log_toggle_btn)
        run_row.row_layout.addWidget(bottom_actions)
        run_row.row_layout.addStretch(1)

        self._log_text = ""

        return panel

    def _apply_button_tooltips(self) -> None:
        self.refresh_btn.setToolTip("Refresh conditions list from the project folder.")
        self.swap_btn.setToolTip("Swap condition A and B selections.")
        self.input_a_open_btn.setToolTip("Open Condition A folder.")
        self.input_b_open_btn.setToolTip("Open Condition B folder.")
        self.output_open_btn.setToolTip("Open output folder.")
        self.input_a_btn.setToolTip("Browse for Condition A folder.")
        self.input_b_btn.setToolTip("Browse for Condition B folder.")
        self.output_btn.setToolTip("Browse for output folder.")
        self.select_all_btn.setToolTip("Exclude all paired participants.")
        self.select_none_btn.setToolTip("Clear all exclusions.")
        self.clear_exclusions_btn.setToolTip("Clear all exclusions.")
        self.run_btn.setToolTip("Run ratio calculations.")
        self.open_output_btn.setToolTip("Open the output folder.")
        self.copy_log_btn.setToolTip("Copy log text to the clipboard.")
        self.log_toggle_btn.setToolTip("Show or hide the run log.")

    def _apply_button_icons(self) -> None:
        style = self.style()
        self.refresh_btn.setIcon(style.standardIcon(QStyle.SP_BrowserReload))
        self.swap_btn.setIcon(style.standardIcon(QStyle.SP_ArrowLeft))
        self.input_a_open_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.input_b_open_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.output_open_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.input_a_btn.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        self.input_b_btn.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        self.output_btn.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        self.run_btn.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.open_output_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.copy_log_btn.setIcon(style.standardIcon(QStyle.SP_FileDialogDetailedView))
