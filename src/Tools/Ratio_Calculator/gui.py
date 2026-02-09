from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
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
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from .constants import RatioCalculatorSettings, ROI_DEFS_DEFAULT
from .worker import RatioCalculatorWorker
from .utils import parse_participant_id

PID_PATTERN = re.compile(r"^P\d+$", re.IGNORECASE)


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

        cond_group = QGroupBox("Conditions")
        cond_layout = QGridLayout(cond_group)

        self.input_a_edit = QLineEdit()
        self.input_a_edit.setPlaceholderText("Select condition A folder")
        self.input_a_btn = QPushButton("Browse…")
        self.input_a_btn.clicked.connect(lambda: self._browse_folder(self.input_a_edit, is_output=False))

        self.label_a_edit = QLineEdit()
        self.label_a_edit.setPlaceholderText("Condition A label")

        self.input_b_edit = QLineEdit()
        self.input_b_edit.setPlaceholderText("Select condition B folder")
        self.input_b_btn = QPushButton("Browse…")
        self.input_b_btn.clicked.connect(lambda: self._browse_folder(self.input_b_edit, is_output=False))

        self.label_b_edit = QLineEdit()
        self.label_b_edit.setPlaceholderText("Condition B label")

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Select output folder")
        self.output_btn = QPushButton("Browse…")
        self.output_btn.clicked.connect(lambda: self._browse_folder(self.output_edit, is_output=True))

        self.run_label_edit = QLineEdit()
        self.run_label_edit.setPlaceholderText("Run label")

        cond_layout.addWidget(QLabel("Condition A Folder"), 0, 0)
        cond_layout.addWidget(self.input_a_edit, 0, 1)
        cond_layout.addWidget(self.input_a_btn, 0, 2)
        cond_layout.addWidget(QLabel("Condition A Label"), 1, 0)
        cond_layout.addWidget(self.label_a_edit, 1, 1, 1, 2)

        cond_layout.addWidget(QLabel("Condition B Folder"), 2, 0)
        cond_layout.addWidget(self.input_b_edit, 2, 1)
        cond_layout.addWidget(self.input_b_btn, 2, 2)
        cond_layout.addWidget(QLabel("Condition B Label"), 3, 0)
        cond_layout.addWidget(self.label_b_edit, 3, 1, 1, 2)

        cond_layout.addWidget(QLabel("Output Folder"), 4, 0)
        cond_layout.addWidget(self.output_edit, 4, 1)
        cond_layout.addWidget(self.output_btn, 4, 2)
        cond_layout.addWidget(QLabel("Run Label"), 5, 0)
        cond_layout.addWidget(self.run_label_edit, 5, 1, 1, 2)

        layout.addWidget(cond_group)

        participants_group = QGroupBox("Participants")
        participants_layout = QVBoxLayout(participants_group)
        load_row = QHBoxLayout()
        self.load_btn = QPushButton("Load participants")
        self.load_btn.clicked.connect(self._load_participants)
        self.participant_counts = QLabel("A: 0 | B: 0 | Paired: 0")
        load_row.addWidget(self.load_btn)
        load_row.addWidget(self.participant_counts)
        load_row.addStretch(1)
        participants_layout.addLayout(load_row)

        self.exclude_list = QListWidget()
        self.exclude_list.setSelectionMode(QListWidget.NoSelection)
        self.exclude_list.itemChanged.connect(self._update_exclusion_status)
        participants_layout.addWidget(self.exclude_list)

        self.exclusion_status = QLabel("Excluded: 0 / Paired: 0 \u2192 Used: 0")
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

        layout.addWidget(participants_group)

        roi_group = QGroupBox("ROIs (read-only)")
        roi_layout = QVBoxLayout(roi_group)
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
        layout.addWidget(roi_group)

        for widget in [
            self.input_a_edit,
            self.input_b_edit,
            self.output_edit,
            self.label_a_edit,
            self.label_b_edit,
            self.run_label_edit,
        ]:
            widget.textChanged.connect(self._update_run_state)

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

    def _browse_folder(self, target_edit: QLineEdit, is_output: bool) -> None:
        start_dir = self._initial_dialog_dir(is_output)
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", str(start_dir))
        if folder:
            target_edit.setText(folder)
            self._last_dir = Path(folder)
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

    def _load_participants(self) -> None:
        self.exclude_list.clear()
        self._paired_participants = []
        input_a = self.input_a_edit.text().strip()
        input_b = self.input_b_edit.text().strip()
        if not input_a or not input_b:
            QMessageBox.warning(self, "Missing folders", "Select both condition folders first.")
            return

        try:
            map_a = self._index_folder(Path(input_a))
            map_b = self._index_folder(Path(input_b))
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return

        pids_a = sorted(map_a.keys())
        pids_b = sorted(map_b.keys())
        paired = sorted(set(pids_a).intersection(set(pids_b)))
        self._paired_participants = paired
        self.participant_counts.setText(f"A: {len(pids_a)} | B: {len(pids_b)} | Paired: {len(paired)}")

        if not paired:
            QMessageBox.warning(self, "No pairs", "No paired participants found between the folders.")

        self.exclude_list.blockSignals(True)
        for pid in paired:
            item = QListWidgetItem(pid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.exclude_list.addItem(item)
        self.exclude_list.blockSignals(False)

        self._update_exclusion_status()
        self._update_run_state()

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
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._update_exclusion_status()

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
        self.run_btn.setEnabled(required_fields and bool(self._paired_participants))
