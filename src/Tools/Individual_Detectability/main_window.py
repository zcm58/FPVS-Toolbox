from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QPlainTextEdit,
    QSizePolicy,
    QSpinBox,
    QDoubleSpinBox,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QHeaderView,
)

from .core import (
    ConditionInfo,
    DetectabilitySettings,
    discover_conditions,
    parse_participant_id,
    sanitize_filename_stem,
)
from .worker import IndividualDetectabilityWorker, RunRequest


class IndividualDetectabilityWindow(QWidget):
    def __init__(self, parent: QWidget | None = None, project_root: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Individual Detectability")
        self.resize(1040, 820)

        self._project_root = self._resolve_project_root(project_root)
        self._last_dir: Optional[Path] = None
        self._conditions: list[ConditionInfo] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[IndividualDetectabilityWorker] = None

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.basic_tab = QWidget()
        self.advanced_tab = QWidget()
        self.tabs.addTab(self.basic_tab, "Basic")
        self.tabs.addTab(self.advanced_tab, "Advanced")
        layout.addWidget(self.tabs)

        self._build_basic_tab()
        self._build_advanced_tab()
        self._build_bottom_panel(layout)
        self._apply_button_styling()
        self._apply_button_icons()

        self._set_default_input_root()
        self._refresh_conditions()
        self._update_run_state()

    @contextmanager
    def _block_signals(self, widget: QWidget):
        was_blocked = widget.blockSignals(True)
        try:
            yield
        finally:
            widget.blockSignals(was_blocked)

    def _resolve_project_root(self, provided_root: str | None) -> Optional[Path]:
        if provided_root:
            root = Path(provided_root)
            if root.exists():
                return root
        env_root = os.environ.get("FPVS_PROJECT_ROOT")
        if env_root:
            root = Path(env_root)
            if root.exists():
                return root
        proj = getattr(self.parent(), "currentProject", None)
        if proj and hasattr(proj, "project_root"):
            root = Path(proj.project_root)
            if root.exists():
                return root
        return None

    def _build_basic_tab(self) -> None:
        layout = QVBoxLayout(self.basic_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._build_input_group(layout)
        self._build_conditions_group(layout)
        self._build_output_group(layout)
        self._build_participant_group(layout)
        layout.addStretch(1)

    def _build_input_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Input data")
        self._apply_groupbox_title_style(group)
        layout = QFormLayout(group)
        layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)

        self.input_root_edit = QLineEdit()
        self.input_root_edit.setReadOnly(True)
        self.input_root_edit.setPlaceholderText("Select Excel root folder")
        self.input_root_btn = QPushButton("Browse…")
        self.input_root_btn.clicked.connect(self._browse_input_root)
        self.refresh_btn = QPushButton("Refresh conditions")
        self.refresh_btn.clicked.connect(self._refresh_conditions)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(self.input_root_edit, 1)
        row_layout.addWidget(self.input_root_btn)

        layout.addRow(QLabel("Excel root folder"), row)
        layout.addRow(QLabel(""), self.refresh_btn)
        parent_layout.addWidget(group)

    def _build_conditions_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Conditions")
        self._apply_groupbox_title_style(group)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)

        self.conditions_list = QListWidget()
        self.conditions_list.itemChanged.connect(self._on_condition_check_changed)

        button_row = QWidget()
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(6)
        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.clicked.connect(lambda: self._set_all_conditions(True))
        self.select_none_btn = QPushButton("Select none")
        self.select_none_btn.clicked.connect(lambda: self._set_all_conditions(False))
        button_layout.addWidget(self.select_all_btn)
        button_layout.addWidget(self.select_none_btn)
        button_layout.addStretch(1)

        self.conditions_summary = QLabel("Selected conditions: 0 | Total files: 0")
        self.conditions_summary.setStyleSheet("color: #666;")

        layout.addWidget(self.conditions_list)
        layout.addWidget(button_row)
        layout.addWidget(self.conditions_summary)
        parent_layout.addWidget(group)

    def _build_output_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Output")
        self._apply_groupbox_title_style(group)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)

        self.output_root_edit = QLineEdit()
        self.output_root_edit.setReadOnly(True)
        self.output_root_edit.setPlaceholderText("Select output folder")
        self.output_root_btn = QPushButton("Browse…")
        self.output_root_btn.clicked.connect(self._browse_output_root)
        self.output_root_open_btn = QPushButton("Open")
        self.output_root_open_btn.clicked.connect(self._open_output_folder)

        out_row = QWidget()
        out_layout = QHBoxLayout(out_row)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.setSpacing(6)
        out_layout.addWidget(self.output_root_edit, 1)
        out_layout.addWidget(self.output_root_open_btn)
        out_layout.addWidget(self.output_root_btn)
        form.addRow(QLabel("Output folder"), out_row)

        layout.addLayout(form)

        self.output_table = QTableWidget(0, 2)
        self.output_table.setHorizontalHeaderLabels(["Condition", "Filename stem"])
        self.output_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.output_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.output_table.verticalHeader().setVisible(False)
        self.output_table.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)

        self.autofill_btn = QPushButton("Auto-fill stems")
        self.autofill_btn.clicked.connect(self._autofill_stems)

        format_row = QWidget()
        format_layout = QHBoxLayout(format_row)
        format_layout.setContentsMargins(0, 0, 0, 0)
        format_layout.setSpacing(10)
        self.export_svg_check = QCheckBox("Export SVG")
        self.export_svg_check.setChecked(True)
        self.export_svg_check.setEnabled(False)
        self.export_png_check = QCheckBox("Also export PNG (600 DPI)")
        self.open_on_complete_check = QCheckBox("Open output folder on completion")
        self.open_on_complete_check.setChecked(True)
        format_layout.addWidget(self.export_svg_check)
        format_layout.addWidget(self.export_png_check)
        format_layout.addStretch(1)

        layout.addWidget(self.output_table)
        layout.addWidget(self.autofill_btn)
        layout.addWidget(format_row)
        layout.addWidget(self.open_on_complete_check)
        parent_layout.addWidget(group)

    def _build_participant_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Participant filtering (optional)")
        self._apply_groupbox_title_style(group)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(6)

        help_text = QLabel(
            "Checked participants are excluded from figure generation for all selected conditions."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #666;")

        filter_row = QWidget()
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(6)
        self.participant_search = QLineEdit()
        self.participant_search.setPlaceholderText("Search participants")
        self.participant_search.textChanged.connect(self._apply_participant_filter)
        self.show_excluded_check = QCheckBox("Show only excluded")
        self.show_excluded_check.stateChanged.connect(self._apply_participant_filter)
        filter_layout.addWidget(self.participant_search, 1)
        filter_layout.addWidget(self.show_excluded_check)

        self.participant_table = QTableWidget(0, 2)
        self.participant_table.setHorizontalHeaderLabels(["Exclude", "Participant ID"])
        self.participant_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.participant_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.participant_table.verticalHeader().setVisible(False)
        self.participant_table.itemChanged.connect(self._apply_participant_filter)

        self.participant_summary = QLabel("Excluded: 0 | Included: 0 | Total detected: 0")
        self.participant_summary.setStyleSheet("color: #666;")

        layout.addWidget(help_text)
        layout.addWidget(filter_row)
        layout.addWidget(self.participant_table)
        layout.addWidget(self.participant_summary)
        parent_layout.addWidget(group)

    def _build_advanced_tab(self) -> None:
        layout = QVBoxLayout(self.advanced_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        settings = DetectabilitySettings()

        harmonics_group = QGroupBox("Harmonics & thresholds")
        self._apply_groupbox_title_style(harmonics_group)
        harm_layout = QFormLayout(harmonics_group)
        harm_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        harm_layout.setHorizontalSpacing(10)
        harm_layout.setVerticalSpacing(6)

        self.harmonics_edit = QLineEdit(", ".join([str(h) for h in settings.oddball_harmonics_hz]))
        self.harmonics_edit.textChanged.connect(self._update_summary_text)
        self.z_threshold_spin = QDoubleSpinBox()
        self.z_threshold_spin.setDecimals(3)
        self.z_threshold_spin.setRange(-99.0, 99.0)
        self.z_threshold_spin.setValue(settings.z_threshold)
        self.z_threshold_spin.valueChanged.connect(self._update_summary_text)
        self.use_bh_fdr_check = QCheckBox("Use BH-FDR correction")
        self.use_bh_fdr_check.setChecked(settings.use_bh_fdr)
        self.use_bh_fdr_check.stateChanged.connect(self._toggle_fdr_alpha)
        self.fdr_alpha_spin = QDoubleSpinBox()
        self.fdr_alpha_spin.setDecimals(4)
        self.fdr_alpha_spin.setRange(0.0001, 1.0)
        self.fdr_alpha_spin.setSingleStep(0.01)
        self.fdr_alpha_spin.setValue(settings.fdr_alpha)
        self.fdr_alpha_spin.valueChanged.connect(self._update_summary_text)

        harm_layout.addRow(QLabel("Oddball harmonics (Hz)"), self.harmonics_edit)
        harm_layout.addRow(QLabel("Z threshold"), self.z_threshold_spin)
        harm_layout.addRow(QLabel(""), self.use_bh_fdr_check)
        harm_layout.addRow(QLabel("FDR alpha"), self.fdr_alpha_spin)

        snr_group = QGroupBox("SNR mini-spectrum")
        self._apply_groupbox_title_style(snr_group)
        snr_layout = QFormLayout(snr_group)
        snr_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        snr_layout.setHorizontalSpacing(10)
        snr_layout.setVerticalSpacing(6)

        self.half_window_spin = QDoubleSpinBox()
        self.half_window_spin.setDecimals(3)
        self.half_window_spin.setRange(0.01, 20.0)
        self.half_window_spin.setValue(settings.half_window_hz)
        self.half_window_spin.valueChanged.connect(self._update_summary_text)
        self.snr_ymin_spin = QDoubleSpinBox()
        self.snr_ymin_spin.setDecimals(2)
        self.snr_ymin_spin.setRange(-10.0, 10.0)
        self.snr_ymin_spin.setValue(settings.snr_ymin_fixed)
        self.snr_ymin_spin.valueChanged.connect(self._update_summary_text)
        self.snr_ymax_spin = QDoubleSpinBox()
        self.snr_ymax_spin.setDecimals(2)
        self.snr_ymax_spin.setRange(0.1, 50.0)
        self.snr_ymax_spin.setValue(settings.snr_ymax_fixed)
        self.snr_ymax_spin.valueChanged.connect(self._update_summary_text)
        self.show_mid_xtick_check = QCheckBox("Show 0 Hz tick")
        self.show_mid_xtick_check.setChecked(settings.snr_show_mid_xtick)
        self.show_mid_xtick_check.stateChanged.connect(self._update_summary_text)

        snr_layout.addRow(QLabel("Half window (Hz)"), self.half_window_spin)
        snr_layout.addRow(QLabel("SNR y-min"), self.snr_ymin_spin)
        snr_layout.addRow(QLabel("SNR y-max"), self.snr_ymax_spin)
        snr_layout.addRow(QLabel(""), self.show_mid_xtick_check)

        layout_group = QGroupBox("Layout")
        self._apply_groupbox_title_style(layout_group)
        layout_form = QFormLayout(layout_group)
        layout_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout_form.setHorizontalSpacing(10)
        layout_form.setVerticalSpacing(6)

        self.grid_cols_spin = QSpinBox()
        self.grid_cols_spin.setRange(1, 10)
        self.grid_cols_spin.setValue(settings.grid_ncols)
        self.grid_cols_spin.valueChanged.connect(self._update_summary_text)
        self.letter_portrait_check = QCheckBox("Use letter portrait")
        self.letter_portrait_check.setChecked(settings.use_letter_portrait)
        self.letter_portrait_check.stateChanged.connect(self._update_summary_text)

        layout_form.addRow(QLabel("Grid columns"), self.grid_cols_spin)
        layout_form.addRow(QLabel(""), self.letter_portrait_check)

        self.summary_box = QTextEdit()
        self.summary_box.setReadOnly(True)
        self.summary_box.setMinimumHeight(110)

        layout.addWidget(harmonics_group)
        layout.addWidget(snr_group)
        layout.addWidget(layout_group)
        layout.addWidget(QLabel("Effective parameters summary"))
        layout.addWidget(self.summary_box)
        layout.addStretch(1)
        self._toggle_fdr_alpha()
        self._update_summary_text()

    def _build_bottom_panel(self, parent_layout: QVBoxLayout) -> None:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self._start_run)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet("color: #666;")
        row_layout.addWidget(self.run_btn)
        row_layout.addWidget(self.progress, 1)
        row_layout.addWidget(self.status_label)

        log_row = QWidget()
        log_layout = QHBoxLayout(log_row)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(6)
        self.toggle_log_btn = QPushButton("Show log")
        self.toggle_log_btn.setCheckable(True)
        self.toggle_log_btn.toggled.connect(self._toggle_log_panel)
        self.copy_log_btn = QPushButton("Copy log")
        self.copy_log_btn.clicked.connect(self._copy_log)
        self.open_output_btn = QPushButton("Open output folder")
        self.open_output_btn.clicked.connect(self._open_output_folder)
        log_layout.addWidget(self.toggle_log_btn)
        log_layout.addWidget(self.copy_log_btn)
        log_layout.addWidget(self.open_output_btn)
        log_layout.addStretch(1)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setVisible(False)
        self.log_box.setMinimumHeight(140)

        layout.addWidget(row)
        layout.addWidget(log_row)
        layout.addWidget(self.log_box)
        parent_layout.addWidget(panel)

    def _apply_groupbox_title_style(self, group: QGroupBox) -> None:
        font = group.font()
        font.setBold(True)
        group.setFont(font)

    def _apply_button_styling(self) -> None:
        for btn in self.findChildren(QPushButton):
            btn.setFixedHeight(28)
            btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.toggle_log_btn.setFixedHeight(26)

    def _apply_button_icons(self) -> None:
        style = QApplication.instance().style()
        self.input_root_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.refresh_btn.setIcon(style.standardIcon(QStyle.SP_BrowserReload))
        self.output_root_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.output_root_open_btn.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        self.autofill_btn.setIcon(style.standardIcon(QStyle.SP_ArrowRight))
        self.run_btn.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.toggle_log_btn.setIcon(style.standardIcon(QStyle.SP_FileDialogInfoView))
        self.copy_log_btn.setIcon(style.standardIcon(QStyle.SP_DialogSaveButton))
        self.open_output_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))

    def _set_default_input_root(self) -> None:
        if self.input_root_edit.text().strip():
            return
        if self._project_root:
            candidate = self._project_root / "1 - Excel Data Files"
            if candidate.exists():
                self.input_root_edit.setText(str(candidate))

    def _browse_input_root(self) -> None:
        start_dir = self._default_browse_dir()
        folder = QFileDialog.getExistingDirectory(self, "Select Excel root folder", str(start_dir))
        if folder:
            self.input_root_edit.setText(folder)
            self._last_dir = Path(folder)
            self._refresh_conditions()

    def _browse_output_root(self) -> None:
        start_dir = self._default_browse_dir()
        folder = QFileDialog.getExistingDirectory(self, "Select output folder", str(start_dir))
        if folder:
            self.output_root_edit.setText(folder)
            self._last_dir = Path(folder)
            self._update_run_state()

    def _default_browse_dir(self) -> Path:
        if self._last_dir and self._last_dir.exists():
            return self._last_dir
        if self._project_root:
            candidate = self._project_root / "1 - Excel Data Files"
            if candidate.exists():
                return candidate
        return Path.home()

    def _refresh_conditions(self) -> None:
        root_text = self.input_root_edit.text().strip()
        self._conditions = discover_conditions(Path(root_text)) if root_text else []
        with self._block_signals(self.conditions_list):
            self.conditions_list.clear()
            for cond in self._conditions:
                item = QListWidgetItem(f"{cond.name} ({len(cond.files)})")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.conditions_list.addItem(item)
        self._populate_output_table()
        self._update_condition_summary()
        self._populate_participants()
        self._update_run_state()

    def _populate_output_table(self) -> None:
        self.output_table.setRowCount(len(self._conditions))
        for row, cond in enumerate(self._conditions):
            name_item = QTableWidgetItem(cond.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            stem_item = QTableWidgetItem(
                sanitize_filename_stem(f"{cond.name}_individual_detectability_grid")
            )
            self.output_table.setItem(row, 0, name_item)
            self.output_table.setItem(row, 1, stem_item)

    def _autofill_stems(self) -> None:
        for row in range(self.output_table.rowCount()):
            cond = self.output_table.item(row, 0)
            if cond is None:
                continue
            stem = sanitize_filename_stem(
                f"{cond.text()}_individual_detectability_grid"
            )
            self.output_table.setItem(row, 1, QTableWidgetItem(stem))

    def _on_condition_check_changed(self, _item: QListWidgetItem) -> None:
        self._update_condition_summary()
        self._populate_participants()
        self._update_run_state()

    def _set_all_conditions(self, checked: bool) -> None:
        with self._block_signals(self.conditions_list):
            for i in range(self.conditions_list.count()):
                item = self.conditions_list.item(i)
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._update_condition_summary()
        self._populate_participants()
        self._update_run_state()

    def _selected_conditions(self) -> list[ConditionInfo]:
        selected: list[ConditionInfo] = []
        for idx, cond in enumerate(self._conditions):
            item = self.conditions_list.item(idx)
            if item and item.checkState() == Qt.Checked:
                selected.append(cond)
        return selected

    def _update_condition_summary(self) -> None:
        selected = self._selected_conditions()
        total_files = sum(len(cond.files) for cond in selected)
        self.conditions_summary.setText(
            f"Selected conditions: {len(selected)} | Total files: {total_files}"
        )

    def _populate_participants(self) -> None:
        selected = self._selected_conditions()
        files = [f for cond in selected for f in cond.files]
        participants: list[str] = []
        for path in files:
            pid = parse_participant_id(path.stem)
            if pid and pid not in participants:
                participants.append(pid)
        participants.sort(key=lambda p: int(p[1:]) if p[1:].isdigit() else p)

        with self._block_signals(self.participant_table):
            self.participant_table.setRowCount(len(participants))
            for row, pid in enumerate(participants):
                exclude_item = QTableWidgetItem()
                exclude_item.setFlags(
                    Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
                )
                exclude_item.setCheckState(Qt.Unchecked)
                pid_item = QTableWidgetItem(pid)
                pid_item.setFlags(pid_item.flags() & ~Qt.ItemIsEditable)
                self.participant_table.setItem(row, 0, exclude_item)
                self.participant_table.setItem(row, 1, pid_item)
        self._apply_participant_filter()

    def _apply_participant_filter(self) -> None:
        search = self.participant_search.text().strip().lower()
        only_excluded = self.show_excluded_check.isChecked()
        excluded = 0
        total = self.participant_table.rowCount()
        for row in range(total):
            pid_item = self.participant_table.item(row, 1)
            exclude_item = self.participant_table.item(row, 0)
            if not pid_item or not exclude_item:
                continue
            pid_text = pid_item.text().lower()
            is_excluded = exclude_item.checkState() == Qt.Checked
            if is_excluded:
                excluded += 1
            visible = True
            if search and search not in pid_text:
                visible = False
            if only_excluded and not is_excluded:
                visible = False
            self.participant_table.setRowHidden(row, not visible)
        included = total - excluded
        self.participant_summary.setText(
            f"Excluded: {excluded} | Included: {included} | Total detected: {total}"
        )

    def _toggle_fdr_alpha(self) -> None:
        enabled = self.use_bh_fdr_check.isChecked()
        self.fdr_alpha_spin.setEnabled(enabled)
        self._update_summary_text()

    def _update_summary_text(self) -> None:
        settings = self._collect_settings()
        summary = [
            f"Harmonics: {', '.join([str(h) for h in settings.oddball_harmonics_hz])}",
            f"Z threshold: {settings.z_threshold}",
            f"BH-FDR enabled: {settings.use_bh_fdr}",
            f"FDR alpha: {settings.fdr_alpha}",
            f"SNR half window: {settings.half_window_hz}",
            f"SNR y-limits: {settings.snr_ymin_fixed} to {settings.snr_ymax_fixed}",
            f"Show 0 Hz tick: {settings.snr_show_mid_xtick}",
            f"Grid columns: {settings.grid_ncols}",
            f"Letter portrait: {settings.use_letter_portrait}",
        ]
        self.summary_box.setText("\n".join(summary))

    def _collect_settings(self) -> DetectabilitySettings:
        harmonics = self._parse_harmonics(self.harmonics_edit.text())
        return DetectabilitySettings(
            oddball_harmonics_hz=harmonics,
            z_threshold=float(self.z_threshold_spin.value()),
            use_bh_fdr=self.use_bh_fdr_check.isChecked(),
            fdr_alpha=float(self.fdr_alpha_spin.value()),
            half_window_hz=float(self.half_window_spin.value()),
            snr_ymin_fixed=float(self.snr_ymin_spin.value()),
            snr_ymax_fixed=float(self.snr_ymax_spin.value()),
            snr_show_mid_xtick=self.show_mid_xtick_check.isChecked(),
            grid_ncols=int(self.grid_cols_spin.value()),
            use_letter_portrait=self.letter_portrait_check.isChecked(),
        )

    def _parse_harmonics(self, text: str) -> list[float]:
        values: list[float] = []
        for token in text.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                values.append(float(token))
            except ValueError:
                continue
        return values

    def _collect_output_stems(self) -> dict[str, str]:
        stems: dict[str, str] = {}
        for row in range(self.output_table.rowCount()):
            cond_item = self.output_table.item(row, 0)
            stem_item = self.output_table.item(row, 1)
            if not cond_item or not stem_item:
                continue
            stems[cond_item.text()] = sanitize_filename_stem(stem_item.text())
        return stems

    def _excluded_participants(self) -> set[str]:
        excluded: set[str] = set()
        for row in range(self.participant_table.rowCount()):
            pid_item = self.participant_table.item(row, 1)
            exclude_item = self.participant_table.item(row, 0)
            if pid_item and exclude_item and exclude_item.checkState() == Qt.Checked:
                excluded.add(pid_item.text())
        return excluded

    def _update_run_state(self) -> None:
        ready = bool(self.output_root_edit.text().strip())
        ready = ready and bool(self._selected_conditions())
        ready = ready and bool(self._collect_output_stems())
        self.run_btn.setEnabled(ready and self._thread is None)

    def _toggle_log_panel(self, checked: bool) -> None:
        self.log_box.setVisible(checked)
        self.toggle_log_btn.setText("Hide log" if checked else "Show log")

    def _append_log(self, message: str) -> None:
        self.log_box.appendPlainText(message)
        self.status_label.setText(message)

    def _copy_log(self) -> None:
        QApplication.clipboard().setText(self.log_box.toPlainText())

    def _open_output_folder(self) -> None:
        path = self.output_root_edit.text().strip()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _start_run(self) -> None:
        if self._thread is not None:
            return
        output_root = self.output_root_edit.text().strip()
        input_root = self.input_root_edit.text().strip()
        if not input_root:
            QMessageBox.critical(self, "Error", "Select an Excel root folder.")
            return
        if not output_root:
            QMessageBox.critical(self, "Error", "Select an output folder.")
            return
        selected_conditions = self._selected_conditions()
        if not selected_conditions:
            QMessageBox.critical(self, "Error", "Select at least one condition.")
            return
        settings = self._collect_settings()
        if not settings.oddball_harmonics_hz:
            QMessageBox.critical(self, "Error", "Provide at least one harmonic value.")
            return

        request = RunRequest(
            input_root=Path(input_root),
            output_root=Path(output_root),
            conditions=selected_conditions,
            output_stems=self._collect_output_stems(),
            excluded_participants=self._excluded_participants(),
            settings=settings,
            export_png=self.export_png_check.isChecked(),
        )
        self.log_box.clear()
        self.progress.setValue(0)
        self.status_label.setText("Starting...")

        self._thread = QThread()
        self._worker = IndividualDetectabilityWorker(request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.status.connect(self.status_label.setText)
        self._worker.log.connect(self._append_log)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()
        self.run_btn.setEnabled(False)

    def _on_worker_error(self, message: str) -> None:
        self._append_log(message)
        QMessageBox.critical(self, "Individual Detectability error", message)

    def _on_worker_finished(self, output_root: str) -> None:
        self.status_label.setText("Complete.")
        self.progress.setValue(100)
        if self.open_on_complete_check.isChecked():
            QDesktopServices.openUrl(QUrl.fromLocalFile(output_root))
        self._update_run_state()

    def _cleanup_worker(self) -> None:
        if self._worker:
            self._worker.deleteLater()
        if self._thread:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._update_run_state()
