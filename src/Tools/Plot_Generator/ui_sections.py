"""Widget assembly helpers for the Plot Generator GUI."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    PathPickerRow,
    SectionCard,
    SubsectionHeaderLabel,
    SurfaceSize,
    configure_window_surface,
    make_action_button,
    make_form_layout,
)
from Main_App.processing.roi_settings import ALL_ROIS_OPTION
from Tools.Plot_Generator.gui_settings import (
    _LEGEND_DEFAULT_A_PEAKS,
    _LEGEND_DEFAULT_B_PEAKS,
)
from Tools.Plot_Generator.log_dialog import SNRGenerationLogDialog
from Tools.Plot_Generator.ui_actions import build_generation_action_row
from Tools.Plot_Generator.ui_header import build_snr_tool_header


class PlotGeneratorUiSectionsMixin:
    """Build the Plot Generator widget tree."""

    def _build_ui(self) -> None:
        configure_window_surface(
            self,
            size=SurfaceSize(width=1180, height=760, min_width=980, min_height=680),
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)
        build_snr_tool_header(self, root_layout)
        file_box = SectionCard("Input and Output")
        file_box.setObjectName("snr_input_output_card")
        file_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum))
        file_layout = file_box.content_layout
        file_layout.setSpacing(6)
        file_grid = QGridLayout()
        file_grid.setContentsMargins(0, 0, 0, 0)
        file_grid.setHorizontalSpacing(12)
        file_grid.setVerticalSpacing(8)

        input_picker = PathPickerRow(
            "Choose Excel Folder",
            placeholder="Select the folder containing your Excel sheets",
        )
        input_picker.setObjectName("snr_input_folder_picker")
        self.folder_edit = input_picker.line_edit
        self.folder_edit.setObjectName("snr_input_folder")
        self.folder_edit.setAccessibleName("Processed Excel folder")
        self.folder_edit.setText(self._defaults.get("input_folder", ""))
        self.folder_edit.setToolTip("Select the folder containing your Excel sheets.")
        self.folder_edit.setMinimumWidth(220)
        input_picker.setMinimumWidth(0)
        self.input_folder_btn = input_picker.button
        self.input_folder_btn.setAccessibleName("Choose processed Excel folder")
        self.input_folder_btn.setToolTip("Choose the folder containing processed Excel workbooks")
        self.input_folder_btn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.input_folder_btn.clicked.connect(self._select_folder)
        self.folder_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        excel_label = QLabel("Processed Excel Folder:")
        excel_label.setBuddy(self.folder_edit)
        file_grid.addWidget(excel_label, 0, 0)
        file_grid.addWidget(input_picker, 0, 1)

        output_picker = PathPickerRow(
            "Choose Plot Folder",
            placeholder="Folder where plots will be saved",
        )
        output_picker.setObjectName("snr_output_folder_picker")
        self.out_edit = output_picker.line_edit
        self.out_edit.setObjectName("snr_output_folder")
        self.out_edit.setAccessibleName("Plot output folder")
        self.out_edit.setText(self._defaults.get("output_folder", ""))
        self.out_edit.setToolTip("Folder where plots will be saved")
        self.out_edit.setMinimumWidth(220)
        output_picker.setMinimumWidth(0)
        self.output_folder_btn = output_picker.button
        self.output_folder_btn.setAccessibleName("Choose plot output folder")
        self.output_folder_btn.setToolTip("Choose where PNG and PDF plots will be saved")
        self.output_folder_btn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.output_folder_btn.clicked.connect(self._select_output)
        self.out_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        save_label = QLabel("Plot Output Folder:")
        save_label.setBuddy(self.out_edit)
        file_grid.addWidget(save_label, 1, 0)
        file_grid.addWidget(output_picker, 1, 1)
        file_grid.setColumnStretch(1, 1)

        picker_button_width = max(
            self.input_folder_btn.sizeHint().width(),
            self.output_folder_btn.sizeHint().width(),
        )
        self.input_folder_btn.setFixedWidth(picker_button_width)
        self.output_folder_btn.setFixedWidth(picker_button_width)
        picker_button_style = "QPushButton { text-align: left; padding-left: 10px; }"
        self.input_folder_btn.setStyleSheet(picker_button_style)
        self.output_folder_btn.setStyleSheet(picker_button_style)

        file_layout.addLayout(file_grid)

        self.params_box = SectionCard("Plot Parameters")
        self.params_box.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        )
        params_layout = self.params_box.content_layout
        params_layout.setSpacing(8)

        self.condition_combo = QComboBox()
        self.condition_combo.setAccessibleName("Condition to plot")
        self.condition_combo.setToolTip("Select the condition to plot")
        self.condition_combo.currentTextChanged.connect(self._update_chart_title_state)

        self.color_a_btn = QPushButton()
        self.color_a_btn.setAccessibleName("Choose Condition A line color")
        self.color_a_btn.setFixedSize(20, 20)
        self.color_a_btn.setStyleSheet(f"background-color: {self.stem_color};")
        self.color_a_btn.setToolTip("Color for Condition A")
        self.color_a_btn.clicked.connect(lambda: self._choose_color("a"))

        self.condition_b_combo = QComboBox()
        self.condition_b_combo.setAccessibleName("Second condition to compare")
        self.condition_b_combo.setToolTip("Select second condition")

        self.color_b_btn = QPushButton()
        self.color_b_btn.setAccessibleName("Choose Condition B line color")
        self.color_b_btn.setFixedSize(20, 20)
        self.color_b_btn.setStyleSheet(f"background-color: {self.stem_color_b};")
        self.color_b_btn.setToolTip("Color for Condition B")
        self.color_b_btn.clicked.connect(lambda: self._choose_color("b"))

        self.roi_combo = QComboBox()
        self.roi_combo.setAccessibleName("Region of interest to plot")
        self.roi_combo.addItems([ALL_ROIS_OPTION] + list(self.roi_map.keys()))
        self.roi_combo.setToolTip("Select the region of interest")

        self.condition_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.condition_b_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.roi_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        cond_a_container = QWidget()
        cond_a_layout = QVBoxLayout(cond_a_container)
        cond_a_layout.setContentsMargins(0, 0, 0, 0)
        cond_a_layout.setSpacing(4)
        cond_a_layout.addWidget(SubsectionHeaderLabel("Condition A"))
        cond_a_row = QHBoxLayout()
        cond_a_row.setContentsMargins(0, 0, 0, 0)
        cond_a_row.setSpacing(6)
        cond_a_row.addWidget(self.condition_combo)
        cond_a_row.addWidget(self.color_a_btn)
        cond_a_layout.addLayout(cond_a_row)

        self.condB_container = QWidget()
        cond_b_layout = QVBoxLayout(self.condB_container)
        cond_b_layout.setContentsMargins(0, 0, 0, 0)
        cond_b_layout.setSpacing(4)
        self.condition_b_label = SubsectionHeaderLabel("Condition B")
        cond_b_layout.addWidget(self.condition_b_label)
        cond_b_row = QHBoxLayout()
        cond_b_row.setContentsMargins(0, 0, 0, 0)
        cond_b_row.setSpacing(6)
        cond_b_row.addWidget(self.condition_b_combo)
        cond_b_row.addWidget(self.color_b_btn)
        cond_b_layout.addLayout(cond_b_row)
        roi_container = QWidget()
        roi_layout = QVBoxLayout(roi_container)
        roi_layout.setContentsMargins(0, 0, 0, 0)
        roi_layout.setSpacing(4)
        roi_layout.addWidget(SubsectionHeaderLabel("ROI"))
        roi_row = QHBoxLayout()
        roi_row.setContentsMargins(0, 0, 0, 0)
        roi_row.setSpacing(6)
        roi_row.addWidget(self.roi_combo)
        roi_layout.addLayout(roi_row)

        selectors_grid = QGridLayout()
        selectors_grid.setContentsMargins(0, 0, 0, 0)
        selectors_grid.setHorizontalSpacing(10)
        selectors_grid.setVerticalSpacing(8)
        selectors_grid.addWidget(cond_a_container, 0, 0)
        selectors_grid.addWidget(roi_container, 0, 1)
        selectors_grid.addWidget(self.condB_container, 1, 0)
        selectors_grid.setColumnStretch(0, 1)
        selectors_grid.setColumnStretch(1, 1)

        self._selectors_grid = selectors_grid
        params_layout.addLayout(selectors_grid)

        self.overlay_check = QCheckBox("Overlay Comparison")
        self.overlay_check.toggled.connect(self._overlay_toggled)

        self.overlay_row = QWidget()
        overlay_layout = QHBoxLayout(self.overlay_row)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(8)
        overlay_layout.addStretch(1)
        overlay_layout.addWidget(self.overlay_check)
        overlay_layout.addStretch(1)

        params_layout.addWidget(self.overlay_row)

        self.legend_group = SectionCard("Legend labels (optional)")
        self.legend_group.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum))
        legend_layout = self.legend_group.content_layout
        legend_layout.setSpacing(6)
        self.legend_custom_check = QCheckBox("Custom legend labels")
        self.legend_custom_check.setChecked(True)
        self.legend_custom_check.toggled.connect(self._toggle_custom_legend_labels)
        legend_header = QHBoxLayout()
        legend_header.setContentsMargins(0, 0, 0, 0)
        legend_header.setSpacing(8)
        legend_header.addWidget(self.legend_custom_check)
        legend_header.addStretch(1)

        legend_form = QGridLayout()
        legend_form.setContentsMargins(0, 0, 0, 0)
        legend_form.setHorizontalSpacing(12)
        legend_form.setVerticalSpacing(6)

        self.legend_condition_a_edit = QLineEdit()
        self.legend_condition_a_edit.setPlaceholderText("Condition A label")
        self.legend_condition_a_edit.setMinimumWidth(0)
        self.legend_condition_a_edit.setEnabled(False)
        self.legend_condition_a_edit.textChanged.connect(self._persist_legend_settings)
        self.legend_condition_a_edit.textEdited.connect(
            lambda _text: self._on_legend_condition_label_edited("condition_a_label")
        )
        self.legend_condition_a_label = QLabel("Condition A label:")
        legend_form.addWidget(self.legend_condition_a_label, 0, 0)
        legend_form.addWidget(self.legend_condition_a_edit, 0, 1)

        self.legend_condition_b_edit = QLineEdit()
        self.legend_condition_b_edit.setPlaceholderText("Condition B label")
        self.legend_condition_b_edit.setMinimumWidth(0)
        self.legend_condition_b_edit.setEnabled(False)
        self.legend_condition_b_edit.textChanged.connect(self._persist_legend_settings)
        self.legend_condition_b_edit.textEdited.connect(
            lambda _text: self._on_legend_condition_label_edited("condition_b_label")
        )
        self.legend_condition_b_label = QLabel("Condition B label:")
        legend_form.addWidget(self.legend_condition_b_label, 0, 2)
        legend_form.addWidget(self.legend_condition_b_edit, 0, 3)

        self.legend_a_peaks_edit = QLineEdit()
        self.legend_a_peaks_edit.setPlaceholderText(_LEGEND_DEFAULT_A_PEAKS)
        self.legend_a_peaks_edit.setMinimumWidth(0)
        self.legend_a_peaks_edit.setEnabled(False)
        self.legend_a_peaks_edit.textChanged.connect(self._persist_legend_settings)
        self.legend_a_peaks_edit.textEdited.connect(
            lambda _text: self._mark_legend_manual_override("a_peaks_label")
        )
        self.legend_a_peaks_label = QLabel("A-Peaks label:")
        legend_form.addWidget(self.legend_a_peaks_label, 1, 0)
        legend_form.addWidget(self.legend_a_peaks_edit, 1, 1)

        self.legend_b_peaks_edit = QLineEdit()
        self.legend_b_peaks_edit.setPlaceholderText(_LEGEND_DEFAULT_B_PEAKS)
        self.legend_b_peaks_edit.setMinimumWidth(0)
        self.legend_b_peaks_edit.setEnabled(False)
        self.legend_b_peaks_edit.textChanged.connect(self._persist_legend_settings)
        self.legend_b_peaks_edit.textEdited.connect(
            lambda _text: self._mark_legend_manual_override("b_peaks_label")
        )
        self.legend_b_peaks_label = QLabel("B-Peaks label:")
        legend_form.addWidget(self.legend_b_peaks_label, 1, 2)
        legend_form.addWidget(self.legend_b_peaks_edit, 1, 3)
        legend_labels = (
            self.legend_condition_a_label,
            self.legend_condition_b_label,
            self.legend_a_peaks_label,
            self.legend_b_peaks_label,
        )
        legend_label_width = max(
            label.fontMetrics().horizontalAdvance(text)
            for label in legend_labels
            for text in (
                "Condition A label:",
                "Condition B label:",
                "First group label:",
                "Second group label:",
                "A-Peaks label:",
                "B-Peaks label:",
            )
        )
        for label in legend_labels:
            label.setFixedWidth(legend_label_width)
        legend_form.setColumnStretch(1, 1)
        legend_form.setColumnStretch(3, 1)

        self.legend_reset_btn = make_action_button("Reset to defaults")
        self.legend_reset_btn.clicked.connect(self._reset_legend_defaults)
        legend_header.addWidget(self.legend_reset_btn)
        legend_layout.addLayout(legend_header)
        legend_layout.addLayout(legend_form)

        self._legend_fields = {
            "condition_a_label": self.legend_condition_a_edit,
            "condition_b_label": self.legend_condition_b_edit,
            "a_peaks_label": self.legend_a_peaks_edit,
            "b_peaks_label": self.legend_b_peaks_edit,
        }
        self._legend_auto_values: dict[str, str] = {}
        self._legend_manual_overrides: set[str] = set()
        self._syncing_legend_defaults = False

        self.group_box = SectionCard("Group Options")
        self.group_box.setMaximumHeight(180)
        group_layout = self.group_box.content_layout
        group_layout.setSpacing(6)
        self.group_overlay_check = QCheckBox("Overlay groups on plots")
        self.group_overlay_check.setAccessibleName("Overlay project groups")
        self.group_overlay_check.toggled.connect(self._on_group_overlay_toggled)
        group_layout.addWidget(self.group_overlay_check)
        self.group_list = QListWidget()
        self.group_list.setAccessibleName("Project groups to include")
        self.group_list.setSelectionMode(QListWidget.NoSelection)
        self.group_list.setMinimumHeight(58)
        self.group_list.setMaximumHeight(80)
        group_layout.addWidget(self.group_list)
        self.group_box.setVisible(False)
        # Added below the legend in the left column; hidden unless multi-group data is present.

        params_layout.addStretch(1)

        self.title_edit = QLineEdit(self._defaults["title_snr"], self)
        self.title_edit.setObjectName("plot_generator_internal_figure_name")
        self.title_edit.setPlaceholderText("e.g. Fruit vs Veg")
        self.title_edit.setToolTip("Internal base name used for exported figure files")
        self.title_edit.hide()

        self.xlabel_edit = QLineEdit(self._defaults["xlabel"])
        self.xlabel_edit.setPlaceholderText("e.g. Frequency (Hz)")
        self.xlabel_edit.setToolTip("Label for the X axis")

        self.ylabel_edit = QLineEdit(self._defaults["ylabel_snr"])
        self.ylabel_edit.setPlaceholderText("Metric units")
        self.ylabel_edit.setToolTip("Label for the Y axis")

        self.axis_ranges_label = SubsectionHeaderLabel("Axis Ranges")
        ranges_grid = QGridLayout()
        ranges_grid.setContentsMargins(0, 0, 0, 0)
        ranges_grid.setHorizontalSpacing(10)
        ranges_grid.setVerticalSpacing(6)

        self.xmin_spin = QDoubleSpinBox()
        self.xmin_spin.setRange(-9999.0, 9999.0)
        self.xmin_spin.setDecimals(2)
        self.xmin_spin.setSingleStep(0.1)
        self.xmin_spin.setSuffix(" Hz")
        self.xmin_spin.setValue(float(self._defaults["x_min"]))
        self.xmin_spin.setToolTip("Minimum X frequency")
        self.xmin_spin.setMinimumWidth(105)
        self.xmax_spin = QDoubleSpinBox()
        self.xmax_spin.setRange(-9999.0, 9999.0)
        self.xmax_spin.setDecimals(2)
        self.xmax_spin.setSingleStep(0.1)
        self.xmax_spin.setSuffix(" Hz")
        self.xmax_spin.setValue(float(self._defaults["x_max"]))
        self.xmax_spin.setToolTip(
            "Maximum X frequency. Oddball harmonics and peak markers are derived up to this value."
        )
        self.xmax_spin.setMinimumWidth(105)
        ranges_grid.addWidget(QLabel("X Range:"), 0, 0)
        ranges_grid.addWidget(self.xmin_spin, 0, 1)
        ranges_grid.addWidget(QLabel("to"), 0, 2)
        ranges_grid.addWidget(self.xmax_spin, 0, 3)

        self.ymin_spin = QDoubleSpinBox()
        self.ymin_spin.setRange(-9999.0, 9999.0)
        self.ymin_spin.setDecimals(2)
        self.ymin_spin.setSingleStep(0.1)
        self.ymin_spin.setValue(float(self._defaults["y_min_snr"]))
        self.ymin_spin.setToolTip("Minimum Y value")
        self.ymin_spin.setMinimumWidth(105)
        self.ymax_spin = QDoubleSpinBox()
        self.ymax_spin.setRange(-9999.0, 9999.0)
        self.ymax_spin.setDecimals(2)
        self.ymax_spin.setSingleStep(0.1)
        self.ymax_spin.setValue(float(self._defaults["y_max_snr"]))
        self.ymax_spin.setToolTip("Maximum Y value")
        self.ymax_spin.setMinimumWidth(105)
        ranges_grid.addWidget(QLabel("Y Range:"), 1, 0)
        ranges_grid.addWidget(self.ymin_spin, 1, 1)
        ranges_grid.addWidget(QLabel("to"), 1, 2)
        ranges_grid.addWidget(self.ymax_spin, 1, 3)

        ranges_grid.setColumnStretch(1, 1)
        ranges_grid.setColumnStretch(3, 1)

        self.advanced_box = SectionCard("Advanced")
        self.advanced_box.setMinimumHeight(256)
        self.advanced_box.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        )
        advanced_layout = self.advanced_box.content_layout
        advanced_layout.setSpacing(6)

        advanced_form = make_form_layout()
        advanced_form.addRow(QLabel("X-axis label:"), self.xlabel_edit)
        advanced_form.addRow(QLabel("Y-axis label:"), self.ylabel_edit)
        advanced_layout.addLayout(advanced_form)
        advanced_layout.addWidget(self.axis_ranges_label)
        advanced_layout.addLayout(ranges_grid)
        self.spectral_qc_check = QCheckBox("Flag unexpected SNR peaks")
        self.spectral_qc_check.setChecked(
            bool(self._defaults.get("spectral_qc_enabled", True))
        )
        self.spectral_qc_check.setToolTip(
            "Flag strong SNR peaks at non-base, non-oddball, non-harmonic frequencies in the completion feedback. Plot values are not changed."
        )
        advanced_layout.addWidget(self.spectral_qc_check)

        self.generation_log_dialog = SNRGenerationLogDialog("", self)
        self.log = self.generation_log_dialog.viewer
        self.log.setProperty("logSurface", True)
        self.log.setAccessibleName("SNR plot generation log")

        left_column = QWidget()
        left_column.setSizePolicy(
            QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        )
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(self.params_box, 1)
        left_layout.addWidget(self.group_box)

        right_column = QWidget()
        right_column.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        )
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(self.advanced_box, 1)

        content_widget = QWidget()
        content_widget.setObjectName("snr_plot_content_columns")
        content_widget.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        )
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        content_layout.addWidget(left_column, 1)
        content_layout.addWidget(right_column, 1)
        root_layout.addWidget(file_box)
        root_layout.addWidget(content_widget)
        root_layout.addWidget(self.legend_group)
        root_layout.addStretch(1)

        build_generation_action_row(self, root_layout)

        self.folder_edit.textChanged.connect(self._check_required)
        self.out_edit.textChanged.connect(self._check_required)
        self.condition_combo.currentTextChanged.connect(self._on_condition_a_changed)
        self.condition_b_combo.currentTextChanged.connect(self._on_condition_b_changed)
        self.overlay_check.toggled.connect(self._check_required)
        self._check_required()
