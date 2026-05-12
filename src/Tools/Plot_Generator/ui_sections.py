"""Widget assembly helpers for the Plot Generator GUI."""
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
    QListWidget,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    PathPickerRow,
    SectionCard,
    SurfaceSize,
    configure_window_surface,
    make_action_button,
    make_form_layout,
)
from Tools.Plot_Generator.gui_settings import (
    _LEGEND_DEFAULT_A_PEAKS,
    _LEGEND_DEFAULT_B_PEAKS,
)
from Tools.Stats.analysis.stats_analysis import ALL_ROIS_OPTION


class PlotGeneratorUiSectionsMixin:
    """Build the Plot Generator widget tree."""

    def _toggle_log_panel(self, expanded: bool) -> None:
        self.log_toggle_btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.log_body.setVisible(expanded)
        self.log.setMinimumHeight(180 if expanded else 0)

    def _build_ui(self) -> None:
        configure_window_surface(
            self,
            size=SurfaceSize(width=1180, height=680, min_width=980, min_height=600),
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)
        file_box = SectionCard("File I/O")
        file_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum))
        file_layout = file_box.content_layout
        file_layout.setSpacing(6)
        file_form = make_form_layout()

        input_picker = PathPickerRow(
            "Browse...",
            placeholder="Select the folder containing your Excel sheets",
        )
        self.folder_edit = input_picker.line_edit
        self.folder_edit.setText(self._defaults.get("input_folder", ""))
        self.folder_edit.setToolTip("Select the folder containing your Excel sheets.")
        browse = input_picker.button
        browse.setToolTip(
            "Select the FOLDER that contains your results excel files"
        )
        browse.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse.clicked.connect(self._select_folder)
        self.folder_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        file_form.addRow(QLabel("Excel Files Folder:"), input_picker)

        output_picker = PathPickerRow(
            "Browse...",
            placeholder="Folder where plots will be saved",
        )
        self.out_edit = output_picker.line_edit
        self.out_edit.setText(self._defaults.get("output_folder", ""))
        self.out_edit.setToolTip("Folder where plots will be saved")
        browse_out = output_picker.button
        browse_out.setToolTip("Browse for output folder")
        browse_out.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        browse_out.clicked.connect(self._select_output)
        open_out = make_action_button("Open...", compact=True)
        open_out.setToolTip("Open save directory")
        open_out.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        open_out.clicked.connect(self._open_output_folder)
        output_picker.row_layout.addWidget(open_out, 0)
        self.out_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        file_form.addRow(QLabel("Save Plots To:"), output_picker)

        file_layout.addLayout(file_form)

        params_box = SectionCard("Plot Parameters")
        params_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum))
        params_form = make_form_layout()
        params_box.content_layout.addLayout(params_form)

        self.condition_combo = QComboBox()
        self.condition_combo.setToolTip("Select the condition to plot")
        self.condition_combo.currentTextChanged.connect(self._update_chart_title_state)

        self.color_a_btn = QPushButton()
        self.color_a_btn.setFixedSize(20, 20)
        self.color_a_btn.setStyleSheet(f"background-color: {self.stem_color};")
        self.color_a_btn.setToolTip("Color for Condition A")
        self.color_a_btn.clicked.connect(lambda: self._choose_color("a"))

        self.condition_b_combo = QComboBox()
        self.condition_b_combo.setToolTip("Select second condition")

        self.color_b_btn = QPushButton()
        self.color_b_btn.setFixedSize(20, 20)
        self.color_b_btn.setStyleSheet(f"background-color: {self.stem_color_b};")
        self.color_b_btn.setToolTip("Color for Condition B")
        self.color_b_btn.clicked.connect(lambda: self._choose_color("b"))

        self.roi_combo = QComboBox()
        self.roi_combo.addItems([ALL_ROIS_OPTION] + list(self.roi_map.keys()))
        self.roi_combo.setToolTip("Select the region of interest")

        self.condition_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.condition_b_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.roi_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        cond_a_container = QWidget()
        cond_a_layout = QVBoxLayout(cond_a_container)
        cond_a_layout.setContentsMargins(0, 0, 0, 0)
        cond_a_layout.setSpacing(4)
        cond_a_layout.addWidget(QLabel("Condition A"))
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
        self.condition_b_label = QLabel("Condition B")
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
        roi_layout.addWidget(QLabel("ROI"))
        roi_row = QHBoxLayout()
        roi_row.setContentsMargins(0, 0, 0, 0)
        roi_row.setSpacing(6)
        roi_row.addWidget(self.roi_combo)
        roi_layout.addLayout(roi_row)

        selectors_grid = QGridLayout()
        selectors_grid.setContentsMargins(0, 0, 0, 0)
        selectors_grid.setHorizontalSpacing(10)
        selectors_grid.setVerticalSpacing(2)
        selectors_grid.addWidget(cond_a_container, 0, 0)
        selectors_grid.addWidget(self.condB_container, 0, 1)
        selectors_grid.addWidget(roi_container, 0, 2)

        selectors_container = QWidget()
        selectors_container_layout = QHBoxLayout(selectors_container)
        selectors_container_layout.setContentsMargins(0, 0, 0, 0)
        selectors_container_layout.setSpacing(0)
        selectors_container_layout.addStretch(1)
        selectors_container_layout.addLayout(selectors_grid)
        selectors_container_layout.addStretch(1)

        self._selectors_grid = selectors_grid
        params_form.addRow(selectors_container)

        self.overlay_check = QCheckBox("Overlay Comparison")
        self.overlay_check.toggled.connect(self._overlay_toggled)

        overlay_row = QWidget()
        overlay_layout = QHBoxLayout(overlay_row)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(8)
        overlay_layout.addStretch(1)
        overlay_layout.addWidget(self.overlay_check)

        self.scalp_check = QCheckBox("Include scalp maps")
        self.scalp_check.setChecked(self.include_scalp_maps)
        self.scalp_check.toggled.connect(self._toggle_scalp_controls)
        overlay_layout.addWidget(self.scalp_check)
        overlay_layout.addStretch(1)

        params_form.addRow("", overlay_row)

        self.legend_group = SectionCard("Legend labels (optional)")
        legend_layout = self.legend_group.content_layout
        legend_layout.setSpacing(6)
        self.legend_custom_check = QCheckBox("Custom legend labels")
        self.legend_custom_check.toggled.connect(self._toggle_custom_legend_labels)
        legend_layout.addWidget(self.legend_custom_check)

        legend_form = make_form_layout()

        self.legend_condition_a_edit = QLineEdit()
        self.legend_condition_a_edit.setPlaceholderText("Condition A label")
        self.legend_condition_a_edit.setEnabled(False)
        self.legend_condition_a_edit.textChanged.connect(self._persist_legend_settings)
        self.legend_condition_a_label = QLabel("Condition A label:")
        legend_form.addRow(self.legend_condition_a_label, self.legend_condition_a_edit)

        self.legend_condition_b_edit = QLineEdit()
        self.legend_condition_b_edit.setPlaceholderText("Condition B label")
        self.legend_condition_b_edit.setEnabled(False)
        self.legend_condition_b_edit.textChanged.connect(self._persist_legend_settings)
        self.legend_condition_b_label = QLabel("Condition B label:")
        legend_form.addRow(self.legend_condition_b_label, self.legend_condition_b_edit)

        self.legend_a_peaks_edit = QLineEdit()
        self.legend_a_peaks_edit.setPlaceholderText(_LEGEND_DEFAULT_A_PEAKS)
        self.legend_a_peaks_edit.setEnabled(False)
        self.legend_a_peaks_edit.textChanged.connect(self._persist_legend_settings)
        self.legend_a_peaks_label = QLabel("A-Peaks label:")
        legend_form.addRow(self.legend_a_peaks_label, self.legend_a_peaks_edit)

        self.legend_b_peaks_edit = QLineEdit()
        self.legend_b_peaks_edit.setPlaceholderText(_LEGEND_DEFAULT_B_PEAKS)
        self.legend_b_peaks_edit.setEnabled(False)
        self.legend_b_peaks_edit.textChanged.connect(self._persist_legend_settings)
        self.legend_b_peaks_label = QLabel("B-Peaks label:")
        legend_form.addRow(self.legend_b_peaks_label, self.legend_b_peaks_edit)

        legend_layout.addLayout(legend_form)
        self.legend_reset_btn = make_action_button("Reset to defaults")
        self.legend_reset_btn.clicked.connect(self._reset_legend_defaults)
        legend_layout.addWidget(self.legend_reset_btn, alignment=Qt.AlignRight)
        params_form.addRow(self.legend_group)

        self.group_box = SectionCard("Group Options")
        group_layout = self.group_box.content_layout
        group_layout.setSpacing(6)
        self.group_overlay_check = QCheckBox("Overlay groups on plots")
        self.group_overlay_check.toggled.connect(self._on_group_overlay_toggled)
        group_layout.addWidget(self.group_overlay_check)
        self.group_list = QListWidget()
        self.group_list.setSelectionMode(QListWidget.NoSelection)
        self.group_list.setMinimumHeight(80)
        group_layout.addWidget(self.group_list)
        self.group_box.setVisible(False)
        params_form.addRow(self.group_box)

        self.scalp_title_a_edit = QLineEdit(self.scalp_title_a_template)
        self.scalp_title_a_edit.setPlaceholderText("{condition} {roi} scalp map")
        self.scalp_title_a_edit.setToolTip(
            "Title template for scalp maps. Use {condition} and {roi} placeholders."
        )
        self.scalp_title_a_edit.setProperty("invalid", False)
        params_form.addRow(QLabel("Scalp title (A):"), self.scalp_title_a_edit)

        self.scalp_title_b_edit = QLineEdit(self.scalp_title_b_template)
        self.scalp_title_b_edit.setPlaceholderText("{condition} {roi} scalp map")
        self.scalp_title_b_edit.setToolTip(
            "Title template for Condition B scalp maps. Use {condition} and {roi}."
        )
        self.scalp_title_b_edit.setProperty("invalid", False)
        self.scalp_title_b_label = QLabel("Scalp title (B):")
        params_form.addRow(self.scalp_title_b_label, self.scalp_title_b_edit)

        self.title_edit = QLineEdit(self._defaults["title_snr"])
        self.title_edit.setPlaceholderText("e.g. Fruit vs Veg")
        self.title_edit.setToolTip("Title shown on the plot")

        self.xlabel_edit = QLineEdit(self._defaults["xlabel"])
        self.xlabel_edit.setPlaceholderText("e.g. Frequency (Hz)")
        self.xlabel_edit.setToolTip("Label for the X axis")

        self.ylabel_edit = QLineEdit(self._defaults["ylabel_snr"])
        self.ylabel_edit.setPlaceholderText("Metric units")
        self.ylabel_edit.setToolTip("Label for the Y axis")

        ranges_box = SectionCard("Axis Ranges")
        ranges_box.setSizePolicy(
            QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        )
        ranges_form = make_form_layout()
        ranges_box.content_layout.addLayout(ranges_form)

        self.xmin_spin = QDoubleSpinBox()
        self.xmin_spin.setRange(-9999.0, 9999.0)
        self.xmin_spin.setDecimals(2)
        self.xmin_spin.setSingleStep(0.1)
        self.xmin_spin.setSuffix(" Hz")
        self.xmin_spin.setValue(float(self._defaults["x_min"]))
        self.xmin_spin.setToolTip("Minimum X frequency")
        self.xmax_spin = QDoubleSpinBox()
        self.xmax_spin.setRange(-9999.0, 9999.0)
        self.xmax_spin.setDecimals(2)
        self.xmax_spin.setSingleStep(0.1)
        self.xmax_spin.setSuffix(" Hz")
        self.xmax_spin.setValue(float(self._defaults["x_max"]))
        self.xmax_spin.setToolTip(
            "Maximum X frequency. Oddball harmonics and peak markers are derived up to this value."
        )
        x_row = QHBoxLayout()
        x_row.setContentsMargins(0, 0, 0, 0)
        x_row.setSpacing(8)
        x_row.addWidget(self.xmin_spin)
        x_row.addWidget(QLabel("to"))
        x_row.addWidget(self.xmax_spin)
        ranges_form.addRow(QLabel("X Range:"), x_row)

        self.ymin_spin = QDoubleSpinBox()
        self.ymin_spin.setRange(-9999.0, 9999.0)
        self.ymin_spin.setDecimals(2)
        self.ymin_spin.setSingleStep(0.1)
        self.ymin_spin.setValue(float(self._defaults["y_min_snr"]))
        self.ymin_spin.setToolTip("Minimum Y value")
        self.ymax_spin = QDoubleSpinBox()
        self.ymax_spin.setRange(-9999.0, 9999.0)
        self.ymax_spin.setDecimals(2)
        self.ymax_spin.setSingleStep(0.1)
        self.ymax_spin.setValue(float(self._defaults["y_max_snr"]))
        self.ymax_spin.setToolTip("Maximum Y value")
        y_row = QHBoxLayout()
        y_row.setContentsMargins(0, 0, 0, 0)
        y_row.setSpacing(8)
        y_row.addWidget(self.ymin_spin)
        y_row.addWidget(QLabel("to"))
        y_row.addWidget(self.ymax_spin)
        ranges_form.addRow(QLabel("Y Range:"), y_row)

        scalp_row = QHBoxLayout()
        scalp_row.setContentsMargins(0, 0, 0, 0)
        scalp_row.setSpacing(6)
        self.scalp_min_spin = QDoubleSpinBox()
        self.scalp_min_spin.setRange(-9999.0, 9999.0)
        self.scalp_min_spin.setDecimals(2)
        self.scalp_min_spin.setSingleStep(0.1)
        self.scalp_min_spin.setValue(float(self.scalp_min))
        self.scalp_min_spin.setSuffix(" uV")
        self.scalp_max_spin = QDoubleSpinBox()
        self.scalp_max_spin.setRange(-9999.0, 9999.0)
        self.scalp_max_spin.setDecimals(2)
        self.scalp_max_spin.setSingleStep(0.1)
        self.scalp_max_spin.setValue(float(self.scalp_max))
        self.scalp_max_spin.setSuffix(" uV")
        scalp_row.addWidget(self.scalp_min_spin)
        scalp_row.addWidget(QLabel("to"))
        scalp_row.addWidget(self.scalp_max_spin)
        ranges_form.addRow(QLabel("Scalp range (uV):"), scalp_row)

        advanced_box = SectionCard("Advanced")
        advanced_box.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        )
        advanced_layout = advanced_box.content_layout
        advanced_layout.setSpacing(6)

        advanced_form = make_form_layout()
        advanced_form.addRow(QLabel("Chart title:"), self.title_edit)
        advanced_form.addRow(QLabel("X-axis label:"), self.xlabel_edit)
        advanced_form.addRow(QLabel("Y-axis label:"), self.ylabel_edit)
        advanced_layout.addLayout(advanced_form)
        advanced_layout.addWidget(ranges_box)

        self.progress_bar = QProgressBar()

        progress_box = SectionCard("Progress")
        progress_box.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        )
        progress_layout = progress_box.content_layout
        progress_layout.setSpacing(6)
        progress_layout.addWidget(self.progress_bar)

        console_box = SectionCard("Log Output")
        console_layout = console_box.content_layout
        console_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(2, 2, 2, 2)
        header.setSpacing(6)
        self.log_toggle_btn = QToolButton()
        self.log_toggle_btn.setText("Log Output")
        self.log_toggle_btn.setCheckable(True)
        self.log_toggle_btn.setChecked(False)
        self.log_toggle_btn.setArrowType(Qt.RightArrow)
        self.log_toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.log_toggle_btn.toggled.connect(self._toggle_log_panel)
        header.addWidget(self.log_toggle_btn)
        header.addStretch()
        clear_btn = make_action_button("", compact=True)
        clear_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        clear_btn.setFixedSize(22, 22)
        clear_btn.setToolTip("Clear Log")
        clear_btn.clicked.connect(lambda: self.log.clear())
        header.addWidget(clear_btn)
        console_layout.addLayout(header)

        self.log_body = QWidget()
        log_body_layout = QVBoxLayout(self.log_body)
        log_body_layout.setContentsMargins(0, 0, 0, 0)
        log_body_layout.setSpacing(0)

        self.log = QTextEdit()
        self.log.setProperty("logSurface", True)
        self.log.setReadOnly(True)
        font = self.log.font()
        font.setBold(False)
        self.log.setFont(font)
        log_body_layout.addWidget(self.log)

        console_layout.addWidget(self.log_body)

        self.log_body.setVisible(False)

        left_column = QWidget()
        left_column.setSizePolicy(
            QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        )
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(file_box)
        left_layout.addWidget(progress_box)
        left_layout.addStretch(1)

        center_column = QWidget()
        center_column.setSizePolicy(
            QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        )
        center_layout = QVBoxLayout(center_column)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)
        center_layout.addWidget(params_box)

        right_column = QWidget()
        right_column.setSizePolicy(
            QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        )
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(advanced_box)
        right_layout.addWidget(console_box)
        right_layout.addStretch(1)

        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)
        content_layout.addWidget(left_column, 1)
        content_layout.addWidget(center_column, 2)
        content_layout.addWidget(right_column, 1)
        root_layout.addWidget(content_widget, 1)

        self.save_defaults_btn = make_action_button("Save Defaults")
        self.save_defaults_btn.setToolTip("Save current folders as defaults")
        self.save_defaults_btn.clicked.connect(self._save_defaults)
        self.load_defaults_btn = make_action_button("Reset to Default settings")
        self.load_defaults_btn.setToolTip("Reset all values to defaults")
        self.load_defaults_btn.clicked.connect(self._load_defaults)
        self.gen_btn = make_action_button("Generate", variant="primary")
        self.gen_btn.setToolTip("Start plot generation")
        self.gen_btn.clicked.connect(self._generate)
        self.gen_btn.setEnabled(False)
        self.cancel_btn = make_action_button("Cancel", variant="danger")
        self.cancel_btn.setToolTip("Cancel generation")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_generation)
        self.gen_btn.setDefault(True)
        self.gen_btn.setAutoDefault(True)
        self.gen_btn.setMinimumWidth(110)

        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(8, 8, 8, 8)
        actions_layout.setSpacing(12)
        actions_layout.addWidget(self.save_defaults_btn)
        actions_layout.addWidget(self.load_defaults_btn)
        actions_layout.addSpacing(12)
        actions_layout.addWidget(self.gen_btn)
        actions_layout.addWidget(self.cancel_btn)

        root_layout.addWidget(actions_widget, alignment=Qt.AlignHCenter)

        self.folder_edit.textChanged.connect(self._check_required)
        self.out_edit.textChanged.connect(self._check_required)
        self.condition_combo.currentTextChanged.connect(self._on_condition_a_changed)
        self.condition_b_combo.currentTextChanged.connect(self._on_condition_b_changed)
        self.overlay_check.toggled.connect(self._check_required)
        self.scalp_title_a_edit.textChanged.connect(self._check_required)
        self.scalp_title_b_edit.textChanged.connect(self._check_required)
        self._toggle_scalp_controls(self.include_scalp_maps)
        self._check_required()

        self._toggle_log_panel(False)
