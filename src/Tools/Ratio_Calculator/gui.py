from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSignalBlocker, QThread, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QFileDialog,
)

from .constants import RatioCalculatorSettings, ROI_DEFS_DEFAULT
from .worker import RatioCalculatorWorker
from .utils import parse_participant_id

PID_PATTERN = re.compile(r"^P\d+$", re.IGNORECASE)
CUSTOM_CONDITION_OPTION = "Custom path"


class RatioCalculatorWindow(QWidget):
    def __init__(self, parent: QWidget | None = None, project_root: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ratio Calculator")
        self.resize(980, 760)

        self._project_root = self._resolve_project_root(project_root)
        self._last_dir: Optional[Path] = None
        self._paired_participants: list[str] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[RatioCalculatorWorker] = None
        self._output_dir: Optional[Path] = None
        self._condition_paths: dict[str, Path] = {}
        self._label_a_dirty = False
        self._label_b_dirty = False
        self._run_label_dirty = False
        self._loading_participants = False

        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.basic_tab = QWidget()
        self.advanced_tab = QWidget()
        self.tabs.addTab(self.basic_tab, "Basic")
        self.tabs.addTab(self.advanced_tab, "Advanced")

        self._build_basic_tab()
        self._build_advanced_tab()

        main_layout.addWidget(self.tabs)
        main_layout.addWidget(self._build_bottom_panel())

        self._refresh_conditions()
        self._set_default_output()
        self._update_run_state()

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

        cond_group = QGroupBox("Conditions")
        cond_group_layout = QVBoxLayout(cond_group)
        cond_group_layout.setContentsMargins(8, 8, 8, 8)
        cond_group_layout.setSpacing(6)
        cond_layout = QFormLayout()
        cond_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        cond_layout.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        cond_layout.setHorizontalSpacing(10)
        cond_layout.setVerticalSpacing(6)

        action_row = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_conditions)
        self.swap_btn = QPushButton("Swap A/B")
        self.swap_btn.clicked.connect(self._swap_conditions)
        action_row.addWidget(self.refresh_btn)
        action_row.addWidget(self.swap_btn)
        action_row.addStretch(1)

        self.condition_a_combo = QComboBox()
        self.condition_a_combo.currentTextChanged.connect(self._on_condition_a_selected)

        self.input_a_edit = QLineEdit()
        self.input_a_edit.setReadOnly(True)
        self.input_a_edit.setPlaceholderText("Select condition A folder")
        self.input_a_open_btn = QPushButton("Open")
        self.input_a_open_btn.clicked.connect(lambda: self._open_folder_from_edit(self.input_a_edit))
        self.input_a_btn = QPushButton("Browse…")
        self.input_a_btn.clicked.connect(
            lambda: self._browse_folder(self.input_a_edit, is_output=False, condition_key="a")
        )

        self.label_a_edit = QLineEdit()
        self.label_a_edit.setPlaceholderText("Condition A label")
        self.label_a_edit.textEdited.connect(self._mark_label_a_dirty)
        self.label_a_edit.textChanged.connect(self._on_label_text_changed)

        self.condition_b_combo = QComboBox()
        self.condition_b_combo.currentTextChanged.connect(self._on_condition_b_selected)

        self.input_b_edit = QLineEdit()
        self.input_b_edit.setReadOnly(True)
        self.input_b_edit.setPlaceholderText("Select condition B folder")
        self.input_b_open_btn = QPushButton("Open")
        self.input_b_open_btn.clicked.connect(lambda: self._open_folder_from_edit(self.input_b_edit))
        self.input_b_btn = QPushButton("Browse…")
        self.input_b_btn.clicked.connect(
            lambda: self._browse_folder(self.input_b_edit, is_output=False, condition_key="b")
        )

        self.label_b_edit = QLineEdit()
        self.label_b_edit.setPlaceholderText("Condition B label")
        self.label_b_edit.textEdited.connect(self._mark_label_b_dirty)
        self.label_b_edit.textChanged.connect(self._on_label_text_changed)

        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setPlaceholderText("Select output folder")
        self.output_open_btn = QPushButton("Open")
        self.output_open_btn.clicked.connect(lambda: self._open_folder_from_edit(self.output_edit))
        self.output_btn = QPushButton("Browse…")
        self.output_btn.clicked.connect(lambda: self._browse_folder(self.output_edit, is_output=True))

        self.run_label_edit = QLineEdit()
        self.run_label_edit.setPlaceholderText("Run label")
        self.run_label_edit.textEdited.connect(self._mark_run_label_dirty)

        self.validation_label = QLabel("")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #b00020;")

        a_path_row = QWidget()
        a_path_layout = QHBoxLayout(a_path_row)
        a_path_layout.setContentsMargins(0, 0, 0, 0)
        a_path_layout.setSpacing(6)
        a_path_layout.addWidget(self.input_a_edit, 1)
        a_path_layout.addWidget(self.input_a_open_btn)
        a_path_layout.addWidget(self.input_a_btn)

        b_path_row = QWidget()
        b_path_layout = QHBoxLayout(b_path_row)
        b_path_layout.setContentsMargins(0, 0, 0, 0)
        b_path_layout.setSpacing(6)
        b_path_layout.addWidget(self.input_b_edit, 1)
        b_path_layout.addWidget(self.input_b_open_btn)
        b_path_layout.addWidget(self.input_b_btn)

        out_path_row = QWidget()
        out_path_layout = QHBoxLayout(out_path_row)
        out_path_layout.setContentsMargins(0, 0, 0, 0)
        out_path_layout.setSpacing(6)
        out_path_layout.addWidget(self.output_edit, 1)
        out_path_layout.addWidget(self.output_open_btn)
        out_path_layout.addWidget(self.output_btn)

        cond_group_layout.addLayout(action_row)
        cond_layout.addRow("Condition A", self.condition_a_combo)
        cond_layout.addRow("Condition A Folder", a_path_row)
        cond_layout.addRow("Condition A Label", self.label_a_edit)
        cond_layout.addRow("Condition B", self.condition_b_combo)
        cond_layout.addRow("Condition B Folder", b_path_row)
        cond_layout.addRow("Condition B Label", self.label_b_edit)
        cond_layout.addRow("Output Folder", out_path_row)
        cond_layout.addRow("Run Label", self.run_label_edit)
        cond_layout.addRow(self.validation_label)
        cond_group_layout.addLayout(cond_layout)

        layout.addWidget(cond_group)

        participants_group = QGroupBox("Participant exclusions (optional)")
        participants_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        participants_layout = QVBoxLayout(participants_group)
        participants_layout.setContentsMargins(8, 8, 8, 8)
        participants_layout.setSpacing(6)
        participants_help = QLabel(
            "Checked participants are excluded from group summaries and distribution overlays. "
            "They still appear in *_ALL* sheets and keep the excluded marker in plots."
        )
        participants_help.setWordWrap(True)
        participants_layout.addWidget(participants_help)
        load_row = QHBoxLayout()
        self.load_btn = QPushButton("Load participants")
        self.load_btn.clicked.connect(self._load_participants)
        self.participant_counts = QLabel("A: 0 | B: 0 | Paired: 0")
        load_row.addWidget(self.load_btn)
        load_row.addWidget(self.participant_counts)
        load_row.addStretch(1)
        participants_layout.addLayout(load_row)

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

        header_row = QHBoxLayout()
        exclude_header = QLabel("Exclude")
        exclude_font = exclude_header.font()
        exclude_font.setBold(True)
        exclude_header.setFont(exclude_font)
        id_header = QLabel("Participant ID")
        id_header.setFont(exclude_font)
        header_row.addWidget(exclude_header)
        header_row.addSpacing(18)
        header_row.addWidget(id_header)
        header_row.addStretch(1)
        participants_layout.addLayout(header_row)

        self.exclude_list = QListWidget()
        self.exclude_list.setSelectionMode(QListWidget.NoSelection)
        self.exclude_list.itemChanged.connect(self._update_exclusion_status)
        participants_layout.addWidget(self.exclude_list)

        self.exclusion_status = QLabel("Excluded: 0 / Paired: 0 \u2192 Used: 0")
        exclusion_font = self.exclusion_status.font()
        exclusion_font.setBold(True)
        self.exclusion_status.setFont(exclusion_font)
        participants_layout.addWidget(self.exclusion_status)

        button_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(lambda: self._set_all_exclusions(True))
        self.select_none_btn = QPushButton("Select None")
        self.select_none_btn.clicked.connect(lambda: self._set_all_exclusions(False))
        self.clear_exclusions_btn = QPushButton("Clear exclusions")
        self.clear_exclusions_btn.clicked.connect(lambda: self._set_all_exclusions(False))
        button_row.addWidget(self.select_all_btn)
        button_row.addWidget(self.select_none_btn)
        button_row.addWidget(self.clear_exclusions_btn)
        button_row.addStretch(1)
        participants_layout.addLayout(button_row)

        roi_group = QGroupBox("ROIs (read-only)")
        roi_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        roi_layout = QVBoxLayout(roi_group)
        roi_layout.setContentsMargins(8, 8, 8, 8)
        roi_layout.setSpacing(6)
        self.roi_table = QTableWidget()
        self.roi_table.setColumnCount(2)
        self.roi_table.setHorizontalHeaderLabels(["ROI", "Electrodes"])
        self.roi_table.verticalHeader().setVisible(False)
        self.roi_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.roi_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.roi_table.setRowCount(len(ROI_DEFS_DEFAULT))

        for row, (roi, electrodes) in enumerate(ROI_DEFS_DEFAULT.items()):
            roi_item = QTableWidgetItem(roi)
            roi_item.setFlags(roi_item.flags() & ~Qt.ItemIsEditable)
            elec_item = QTableWidgetItem(", ".join(electrodes))
            elec_item.setFlags(elec_item.flags() & ~Qt.ItemIsEditable)
            self.roi_table.setItem(row, 0, roi_item)
            self.roi_table.setItem(row, 1, elec_item)

        self.roi_table.resizeColumnsToContents()
        roi_layout.addWidget(self.roi_table)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(participants_group)
        splitter.addWidget(roi_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 320])
        layout.addWidget(splitter)

        for widget in [
            self.input_a_edit,
            self.input_b_edit,
            self.output_edit,
            self.label_a_edit,
            self.label_b_edit,
            self.run_label_edit,
        ]:
            widget.textChanged.connect(self._update_run_state)

    def _mark_label_a_dirty(self) -> None:
        self._label_a_dirty = True

    def _mark_label_b_dirty(self) -> None:
        self._label_b_dirty = True

    def _mark_run_label_dirty(self) -> None:
        self._run_label_dirty = True

    def _on_label_text_changed(self) -> None:
        self._update_run_label_default()

    def _update_run_label_default(self) -> None:
        if self._run_label_dirty:
            return
        label_a = self.label_a_edit.text().strip()
        label_b = self.label_b_edit.text().strip()
        if label_a and label_b:
            with QSignalBlocker(self.run_label_edit):
                self.run_label_edit.setText(f"{label_a} vs {label_b}")

    def _excel_root(self) -> Optional[Path]:
        if not self._project_root:
            return None
        return self._project_root / "1 - Excel Data Files"

    def _set_default_output(self) -> None:
        if self.output_edit.text().strip():
            return
        if self._project_root:
            default_out = self._project_root / "5 - Ratio Summaries"
            self._set_path_display(self.output_edit, str(default_out))

    def _set_path_display(self, edit: QLineEdit, path: str) -> None:
        edit.setText(path)
        edit.setToolTip(path)

    def _scan_condition_folders(self, excel_root: Path) -> list[Path]:
        if not excel_root.exists():
            return []
        folders: list[Path] = []
        for child in sorted(excel_root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            if any(
                fp.suffix.lower() == ".xlsx" and not fp.name.startswith("~$")
                for fp in child.glob("*.xlsx")
            ):
                folders.append(child)
        return folders

    def _refresh_conditions(self) -> None:
        excel_root = self._excel_root()
        condition_paths: dict[str, Path] = {}
        if excel_root:
            for folder in self._scan_condition_folders(excel_root):
                condition_paths[folder.name] = folder
        self._condition_paths = condition_paths

        self._populate_condition_combo(self.condition_a_combo, self.input_a_edit)
        self._populate_condition_combo(self.condition_b_combo, self.input_b_edit)
        if (
            len(self._condition_paths) > 1
            and self.condition_a_combo.currentText() == self.condition_b_combo.currentText()
        ):
            second = list(self._condition_paths.keys())[1]
            with QSignalBlocker(self.condition_b_combo):
                self.condition_b_combo.setCurrentText(second)
            self._apply_condition_selection(second, is_a=False)
        self._update_run_state()

    def _populate_condition_combo(self, combo: QComboBox, edit: QLineEdit) -> None:
        current_path = edit.text().strip()
        current_match = None
        if current_path:
            for name, folder in self._condition_paths.items():
                if folder.resolve() == Path(current_path).resolve():
                    current_match = name
                    break

        with QSignalBlocker(combo):
            combo.clear()
            combo.addItems(self._condition_paths.keys())
            combo.addItem(CUSTOM_CONDITION_OPTION)
            if current_match:
                combo.setCurrentText(current_match)
            elif self._condition_paths:
                combo.setCurrentText(next(iter(self._condition_paths.keys())))
            else:
                combo.setCurrentText(CUSTOM_CONDITION_OPTION)

        selected = combo.currentText()
        if selected in self._condition_paths:
            self._set_path_display(edit, str(self._condition_paths[selected]))
            self._set_condition_labels_from_folder(selected, combo is self.condition_a_combo)

    def _set_condition_labels_from_folder(self, folder_name: str, is_a: bool) -> None:
        if is_a:
            if not self._label_a_dirty:
                with QSignalBlocker(self.label_a_edit):
                    self.label_a_edit.setText(folder_name)
        else:
            if not self._label_b_dirty:
                with QSignalBlocker(self.label_b_edit):
                    self.label_b_edit.setText(folder_name)
        self._update_run_label_default()

    def _on_condition_a_selected(self, condition: str) -> None:
        self._apply_condition_selection(condition, is_a=True)

    def _on_condition_b_selected(self, condition: str) -> None:
        self._apply_condition_selection(condition, is_a=False)

    def _apply_condition_selection(self, condition: str, is_a: bool) -> None:
        if condition == CUSTOM_CONDITION_OPTION:
            self._update_run_state()
            return

        target_edit = self.input_a_edit if is_a else self.input_b_edit
        selected_path = self._condition_paths.get(condition)
        if selected_path:
            self._set_path_display(target_edit, str(selected_path))
            self._set_condition_labels_from_folder(condition, is_a)
            self._last_dir = selected_path
        self._maybe_autoload_participants()
        self._update_run_state()

    def _swap_conditions(self) -> None:
        a_path = self.input_a_edit.text()
        b_path = self.input_b_edit.text()
        a_label = self.label_a_edit.text()
        b_label = self.label_b_edit.text()
        a_combo = self.condition_a_combo.currentText()
        b_combo = self.condition_b_combo.currentText()
        a_dirty = self._label_a_dirty
        b_dirty = self._label_b_dirty

        with QSignalBlocker(self.condition_a_combo), QSignalBlocker(self.condition_b_combo):
            self.condition_a_combo.setCurrentText(b_combo)
            self.condition_b_combo.setCurrentText(a_combo)

        self._set_path_display(self.input_a_edit, b_path)
        self._set_path_display(self.input_b_edit, a_path)
        with QSignalBlocker(self.label_a_edit), QSignalBlocker(self.label_b_edit):
            self.label_a_edit.setText(b_label)
            self.label_b_edit.setText(a_label)

        self._label_a_dirty = b_dirty
        self._label_b_dirty = a_dirty
        self._update_run_label_default()
        self._maybe_autoload_participants()
        self._update_run_state()

    def _build_advanced_tab(self) -> None:
        layout = QVBoxLayout(self.advanced_tab)
        settings_group = QGroupBox("Harmonic settings")
        form = QFormLayout(settings_group)

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
        self.png_dpi_spin.setRange(72, 600)
        self.png_dpi_spin.setValue(300)

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

        form.addRow("Oddball base (Hz)", self.oddball_spin)
        form.addRow("Sum up to (Hz)", self.sum_up_spin)
        form.addRow("Excluded freqs (Hz)", self.excluded_edit)
        form.addRow("Palette", self.palette_combo)
        form.addRow("PNG DPI", self.png_dpi_spin)
        form.addRow(self.use_stable_ylims_check)
        form.addRow("YLIM raw Z", self.ylim_raw_z_edit)
        form.addRow("YLIM raw SNR", self.ylim_raw_snr_edit)
        form.addRow("YLIM raw BCA", self.ylim_raw_bca_edit)
        form.addRow("YLIM ratio Z", self.ylim_ratio_z_edit)
        form.addRow("YLIM ratio SNR", self.ylim_ratio_snr_edit)
        form.addRow("YLIM ratio BCA", self.ylim_ratio_bca_edit)

        layout.addWidget(settings_group)
        layout.addStretch(1)

    def _build_bottom_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        run_row = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self._start_run)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.status_label = QLabel("Ready")
        run_row.addWidget(self.run_btn)
        run_row.addWidget(self.progress)
        run_row.addWidget(self.status_label)
        layout.addLayout(run_row)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        action_row = QHBoxLayout()
        self.open_output_btn = QPushButton("Open output folder")
        self.open_output_btn.setEnabled(False)
        self.open_output_btn.clicked.connect(self._open_output_folder)
        self.copy_log_btn = QPushButton("Copy log")
        self.copy_log_btn.clicked.connect(self._copy_log)
        action_row.addWidget(self.open_output_btn)
        action_row.addWidget(self.copy_log_btn)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        return panel

    def _browse_folder(self, target_edit: QLineEdit, is_output: bool, condition_key: str | None = None) -> None:
        start_dir = self._initial_dialog_dir(is_output)
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", str(start_dir))
        if folder:
            self._set_path_display(target_edit, folder)
            self._last_dir = Path(folder)
            if condition_key:
                combo = self.condition_a_combo if condition_key == "a" else self.condition_b_combo
                if combo.findText(CUSTOM_CONDITION_OPTION) == -1:
                    combo.addItem(CUSTOM_CONDITION_OPTION)
                with QSignalBlocker(combo):
                    combo.setCurrentText(CUSTOM_CONDITION_OPTION)
                self._set_condition_labels_from_folder(Path(folder).name, condition_key == "a")
            self._update_run_state()

    def _initial_dialog_dir(self, is_output: bool) -> Path:
        if self._project_root:
            if is_output:
                preferred = self._project_root / "5 - Ratio Summaries"
            else:
                preferred = self._project_root / "1 - Excel Data Files"
            if preferred.exists():
                return preferred
            return self._project_root
        if self._last_dir:
            return self._last_dir
        return Path.cwd()

    def _load_participants(self, silent: bool = False) -> bool:
        if self._loading_participants:
            return False
        self._loading_participants = True
        try:
            self.exclude_list.clear()
            self._paired_participants = []
            input_a = self.input_a_edit.text().strip()
            input_b = self.input_b_edit.text().strip()
            if not input_a or not input_b:
                if not silent:
                    QMessageBox.warning(self, "Missing folders", "Select both condition folders first.")
                return False

            try:
                map_a = self._index_folder(Path(input_a))
                map_b = self._index_folder(Path(input_b))
            except Exception as exc:
                if not silent:
                    QMessageBox.critical(self, "Error", str(exc))
                else:
                    self._append_log(str(exc))
                return False

            pids_a = sorted(map_a.keys())
            pids_b = sorted(map_b.keys())
            paired = sorted(set(pids_a).intersection(set(pids_b)))
            self._paired_participants = paired
            self.participant_counts.setText(f"A: {len(pids_a)} | B: {len(pids_b)} | Paired: {len(paired)}")

            if not paired:
                if not silent:
                    QMessageBox.warning(self, "No pairs", "No paired participants found between the folders.")
                self._update_exclusion_status()
                return False

            self.exclude_list.blockSignals(True)
            for pid in paired:
                item = QListWidgetItem(pid)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.exclude_list.addItem(item)
            self.exclude_list.blockSignals(False)

            self._apply_participant_filter()
            self._update_exclusion_status()
            self._update_run_state()
            return True
        finally:
            self._loading_participants = False

    def _index_folder(self, folder: Path) -> dict[str, Path]:
        if not folder.exists():
            raise ValueError(f"Folder not found: {folder}")
        mapping: dict[str, Path] = {}
        for file_path in sorted(folder.glob("*.xlsx")):
            if file_path.name.startswith("~$"):
                continue
            pid, _ = parse_participant_id(file_path.name)
            mapping[pid] = file_path
        return mapping

    def _set_all_exclusions(self, checked: bool) -> None:
        for idx in range(self.exclude_list.count()):
            item = self.exclude_list.item(idx)
            if item.isHidden():
                continue
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._update_exclusion_status()

    def _apply_participant_filter(self) -> None:
        query = self.participant_filter_edit.text().strip().lower()
        only_excluded = self.show_excluded_check.isChecked()
        for idx in range(self.exclude_list.count()):
            item = self.exclude_list.item(idx)
            text = item.text().lower()
            matches_query = query in text
            matches_excluded = item.checkState() == Qt.Checked
            show = matches_query and (matches_excluded if only_excluded else True)
            item.setHidden(not show)

    def _collect_manual_exclusions(self) -> list[str]:
        manual_list: list[str] = []
        invalid: list[str] = []
        for idx in range(self.exclude_list.count()):
            item = self.exclude_list.item(idx)
            if item.checkState() == Qt.Checked:
                pid = item.text().strip()
                if PID_PATTERN.match(pid):
                    manual_list.append(pid)
                else:
                    invalid.append(pid)
        if invalid:
            self._append_log(f"Invalid manual exclusions ignored: {invalid}")
            QMessageBox.information(
                self,
                "Invalid exclusions",
                f"Ignored invalid manual exclusion entries: {', '.join(invalid)}",
            )
        return manual_list

    def _update_exclusion_status(self) -> None:
        paired_count = len(self._paired_participants)
        excluded_count = sum(
            1 for idx in range(self.exclude_list.count()) if self.exclude_list.item(idx).checkState() == Qt.Checked
        )
        used_count = max(paired_count - excluded_count, 0)
        self.exclusion_status.setText(
            f"Excluded: {excluded_count} / Paired: {paired_count} \u2192 Used: {used_count}"
        )
        if self.show_excluded_check.isChecked():
            self._apply_participant_filter()

    def _settings_from_ui(self) -> RatioCalculatorSettings:
        excluded = self._parse_excluded_freqs()
        return RatioCalculatorSettings(
            oddball_base_hz=self.oddball_spin.value(),
            sum_up_to_hz=self.sum_up_spin.value(),
            excluded_freqs_hz=excluded,
            palette_choice=self.palette_combo.currentText(),
            png_dpi=self.png_dpi_spin.value(),
            use_stable_ylims=self.use_stable_ylims_check.isChecked(),
            ylim_raw_sum_z=self._parse_ylim(self.ylim_raw_z_edit.text()),
            ylim_raw_sum_snr=self._parse_ylim(self.ylim_raw_snr_edit.text()),
            ylim_raw_sum_bca=self._parse_ylim(self.ylim_raw_bca_edit.text()),
            ylim_ratio_z=self._parse_ylim(self.ylim_ratio_z_edit.text()),
            ylim_ratio_snr=self._parse_ylim(self.ylim_ratio_snr_edit.text()),
            ylim_ratio_bca=self._parse_ylim(self.ylim_ratio_bca_edit.text()),
        )

    def _parse_excluded_freqs(self) -> set[float]:
        text = self.excluded_edit.text().strip()
        if not text:
            return set()
        freqs: set[float] = set()
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                freqs.add(float(part))
            except ValueError:
                self._append_log(f"Invalid excluded frequency ignored: {part}")
        return freqs

    @staticmethod
    def _parse_ylim(text: str) -> Optional[tuple[float, float]]:
        raw = text.strip()
        if not raw:
            return None
        if raw.lower() == "auto":
            return None
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) != 2:
            return None
        try:
            low = float(parts[0])
            high = float(parts[1])
        except ValueError:
            return None
        return (low, high)

    def _open_folder_from_edit(self, edit: QLineEdit) -> None:
        path_str = edit.text().strip()
        if not path_str:
            QMessageBox.information(self, "Missing folder", "No folder has been set yet.")
            return
        path = Path(path_str)
        if not path.exists():
            QMessageBox.warning(self, "Folder not found", f"Folder does not exist:\n{path}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl

                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as exc:
            QMessageBox.warning(self, "Open failed", f"Failed to open folder:\n{exc}")

    def _ensure_output_dir(self, output_dir: str) -> tuple[bool, str | None]:
        if not output_dir:
            return False, "Select an output folder."
        out_path = Path(output_dir)
        try:
            out_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return False, f"Unable to create output folder: {exc}"
        if not out_path.is_dir():
            return False, "Output folder path is not a directory."
        return True, None

    def _validate_inputs(self) -> list[str]:
        errors: list[str] = []
        input_a = self.input_a_edit.text().strip()
        input_b = self.input_b_edit.text().strip()
        output_dir = self.output_edit.text().strip()

        folder_a_valid = bool(input_a) and Path(input_a).is_dir()
        folder_b_valid = bool(input_b) and Path(input_b).is_dir()

        if not input_a:
            errors.append("Select a Condition A folder.")
        elif not folder_a_valid:
            errors.append("Condition A folder does not exist.")

        if not input_b:
            errors.append("Select a Condition B folder.")
        elif not folder_b_valid:
            errors.append("Condition B folder does not exist.")

        if folder_a_valid and folder_b_valid and Path(input_a).resolve() == Path(input_b).resolve():
            errors.append("Condition A and B folders must be different.")

        ok_out, out_err = self._ensure_output_dir(output_dir)
        if not ok_out and out_err:
            errors.append(out_err)

        folders_ready = folder_a_valid and folder_b_valid and Path(input_a).resolve() != Path(input_b).resolve()
        if folders_ready and not self._paired_participants:
            errors.append("Participants are not loaded.")

        return errors

    def _set_validation_errors(self, errors: list[str]) -> None:
        if errors:
            self.validation_label.setText("\n".join(f"• {err}" for err in errors))
        else:
            self.validation_label.setText("")

    def _maybe_autoload_participants(self) -> None:
        if self._paired_participants:
            return
        input_a = self.input_a_edit.text().strip()
        input_b = self.input_b_edit.text().strip()
        if not input_a or not input_b:
            return
        if not Path(input_a).is_dir() or not Path(input_b).is_dir():
            return
        self._load_participants(silent=True)

    def _start_run(self) -> None:
        if self._thread and self._thread.isRunning():
            QMessageBox.information(self, "Running", "Ratio calculations are already running.")
            return

        input_a = self.input_a_edit.text().strip()
        input_b = self.input_b_edit.text().strip()
        output_dir = self.output_edit.text().strip()
        label_a = self.label_a_edit.text().strip()
        label_b = self.label_b_edit.text().strip()
        run_label = self.run_label_edit.text().strip()

        if not all([input_a, input_b, output_dir, label_a, label_b, run_label]):
            QMessageBox.warning(self, "Missing fields", "Fill out all required fields before running.")
            return

        ok_out, out_err = self._ensure_output_dir(output_dir)
        if not ok_out:
            QMessageBox.warning(self, "Output folder error", out_err or "Output folder is not usable.")
            return

        if not self._paired_participants:
            QMessageBox.warning(self, "Participants not loaded", "Load participants before running.")
            return

        self.progress.setValue(0)
        self.status_label.setText("Running...")
        self.log_box.clear()
        self.open_output_btn.setEnabled(False)

        settings = self._settings_from_ui()
        manual_list = self._collect_manual_exclusions()
        manual_set = set(manual_list)
        paired_set = set(self._paired_participants)
        assert manual_set.issubset(paired_set)

        n_paired = len(self._paired_participants)
        n_excl = len(manual_set.intersection(paired_set))
        n_used = n_paired - n_excl
        if n_used == 0:
            msg = QMessageBox(self)
            msg.setWindowTitle("All participants excluded")
            msg.setText(
                "You excluded all paired participants. Group summaries and violin/box/mean overlays will be empty."
            )
            go_back_btn = msg.addButton("Go Back", QMessageBox.RejectRole)
            msg.addButton("Continue Anyway", QMessageBox.AcceptRole)
            msg.setDefaultButton(go_back_btn)
            msg.setIcon(QMessageBox.Warning)
            msg.exec()
            if msg.clickedButton() == go_back_btn:
                self.progress.setValue(0)
                self.status_label.setText("Ready")
                return

        self._thread = QThread()
        self._worker = RatioCalculatorWorker(
            input_dir_a=input_a,
            condition_label_a=label_a,
            input_dir_b=input_b,
            condition_label_b=label_b,
            output_dir=output_dir,
            run_label=run_label,
            manual_exclude=manual_list,
            settings=settings,
            roi_defs=ROI_DEFS_DEFAULT,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.status.connect(self.status_label.setText)
        self._worker.log.connect(self._append_log)
        self._worker.error.connect(self._handle_error)
        self._worker.finished.connect(self._handle_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _handle_error(self, message: str) -> None:
        self._append_log(message)
        self.status_label.setText("Error")
        QMessageBox.critical(self, "Ratio Calculator Error", message)
        self._update_run_state()

    def _handle_finished(self, output_dir: str, excel_path: str) -> None:
        self._output_dir = Path(output_dir)
        self._append_log(f"Excel saved to: {excel_path}")
        self.status_label.setText("Complete")
        self.progress.setValue(100)
        self.open_output_btn.setEnabled(True)
        self._show_completion_dialog()
        self._update_run_state()

    def _show_completion_dialog(self) -> None:
        if self._output_dir is None:
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Processing Complete")
        msg.setText("Aggregation finished successfully.")
        msg.setInformativeText("Would you like to open the output folder?")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setIcon(QMessageBox.Information)
        if msg.exec() == QMessageBox.Yes:
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(self._output_dir))
                else:
                    from PySide6.QtGui import QDesktopServices
                    from PySide6.QtCore import QUrl

                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))
            except Exception as exc:
                self._append_log(f"Failed to open output folder: {exc}")

    def _open_output_folder(self) -> None:
        if self._output_dir is None:
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(self._output_dir))
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl

                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))
        except Exception as exc:
            self._append_log(f"Failed to open output folder: {exc}")

    def _copy_log(self) -> None:
        QApplication.clipboard().setText(self.log_box.toPlainText())

    def _append_log(self, message: str) -> None:
        self.log_box.append(message)

    def _update_run_state(self) -> None:
        errors = self._validate_inputs()
        self._set_validation_errors(errors)
        required_fields = all(
            [
                self.input_a_edit.text().strip(),
                self.input_b_edit.text().strip(),
                self.output_edit.text().strip(),
                self.label_a_edit.text().strip(),
                self.label_b_edit.text().strip(),
                self.run_label_edit.text().strip(),
            ]
        )
        if required_fields and not self._paired_participants:
            self._maybe_autoload_participants()
            errors = self._validate_inputs()
            self._set_validation_errors(errors)
        self.run_btn.setEnabled(required_fields and not errors)
        self.input_a_open_btn.setEnabled(bool(self.input_a_edit.text().strip()))
        self.input_b_open_btn.setEnabled(bool(self.input_b_edit.text().strip()))
        self.output_open_btn.setEnabled(bool(self.output_edit.text().strip()))
