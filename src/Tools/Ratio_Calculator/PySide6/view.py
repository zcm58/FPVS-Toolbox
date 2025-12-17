from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from Main_App.PySide6_App.Backend.project import EXCEL_SUBFOLDER_NAME
from Tools.Ratio_Calculator.PySide6.model import RatioCalcInputs, RatioCalcResult
from Tools.Stats.PySide6.stats_data_loader import (
    auto_detect_project_dir,
    load_manifest_data,
    resolve_project_subfolder,
)
from Tools.Stats.roi_resolver import ROI


class RatioCalculatorWindow(QMainWindow):
    compute_requested = Signal(RatioCalcInputs)
    excel_root_changed = Signal(Path)

    def __init__(self, parent: QWidget | None = None, project_root: Path | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ratio Calculator")
        self._project_root, self._results_folder_hint, self._subfolder_hints = self._detect_project_context(
            parent, project_root
        )
        self._busy = False
        self._last_df: pd.DataFrame | None = None
        self._filename_user_edited = False
        self._pending_logs: list[str] = []
        self._default_excel_root: Path | None = None
        self._roi_definitions: list[ROI] = []

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        layout.addWidget(self._build_input_group())
        layout.addWidget(self._build_params_group())
        layout.addWidget(self._build_advanced_group())
        layout.addWidget(self._build_output_group())

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        layout.addWidget(self._build_log_group())
        self._flush_pending_logs()

        self._update_default_filename(force=True)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.compute_btn = QPushButton("Compute", self)
        self.compute_btn.clicked.connect(self._on_compute)
        btn_row.addWidget(self.compute_btn)
        layout.addLayout(btn_row)

        self.statusBar().showMessage("Ready")

    def _build_input_group(self) -> QGroupBox:
        group = QGroupBox("Excel Root", self)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignLeft)

        default_excel_root = self._preferred_excel_root()
        self._default_excel_root = default_excel_root
        self.excel_path_edit = QLineEdit(str(default_excel_root) if default_excel_root else "")
        self.excel_path_edit.setReadOnly(True)
        self.excel_browse_btn = QPushButton("Browse…", group)
        self.excel_browse_btn.clicked.connect(self._select_excel_root)

        row = QHBoxLayout()
        row.addWidget(self.excel_path_edit)
        row.addWidget(self.excel_browse_btn)
        form.addRow(QLabel("Excel folder:"), row)
        return group

    def _build_params_group(self) -> QGroupBox:
        group = QGroupBox("Parameters", self)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignLeft)

        self.cond_a_combo = QComboBox(group)
        self.cond_a_combo.currentTextChanged.connect(self._on_conditions_changed)
        self.cond_b_combo = QComboBox(group)
        self.cond_b_combo.currentTextChanged.connect(self._on_conditions_changed)
        form.addRow(QLabel("Condition A (numerator):"), self.cond_a_combo)
        form.addRow(QLabel("Condition B (denominator):"), self.cond_b_combo)

        self.roi_combo = QComboBox(group)
        form.addRow(QLabel("ROI:"), self.roi_combo)

        return group

    def _build_advanced_group(self) -> QGroupBox:
        group = QGroupBox("Advanced", self)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignLeft)

        self.threshold_spin = QDoubleSpinBox(group)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setRange(0.0, 10.0)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setValue(1.64)
        self.threshold_spin.setEnabled(False)
        form.addRow(QLabel("Z-score threshold:"), self.threshold_spin)

        self.significance_combo = QComboBox(group)
        self.significance_combo.addItem("Group-level (default)", userData="group")
        self.significance_combo.addItem("Per-participant (experimental)", userData="individual")
        form.addRow(QLabel("Significance mode:"), self.significance_combo)
        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("Output", self)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignLeft)

        default_output_dir = self._default_output_dir(self._default_excel_root)
        self.output_dir_edit = QLineEdit(str(default_output_dir) if default_output_dir else "")
        self.output_dir_edit.setReadOnly(True)
        self.output_browse_btn = QPushButton("Browse…", group)
        self.output_browse_btn.clicked.connect(self._select_output_dir)

        file_row = QHBoxLayout()
        self.output_filename_edit = QLineEdit("", group)
        self.output_filename_edit.textEdited.connect(self._on_filename_edited)
        file_row.addWidget(self.output_filename_edit)
        form.addRow(QLabel("Output filename:"), file_row)

        row = QHBoxLayout()
        row.addWidget(self.output_dir_edit)
        row.addWidget(self.output_browse_btn)
        form.addRow(QLabel("Output folder:"), row)
        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Logs", self)
        group.setCheckable(True)
        group.setChecked(True)
        layout = QVBoxLayout(group)
        self.log_view = QTextEdit(group)
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

        def _toggle(checked: bool) -> None:
            self.log_view.setVisible(checked)

        group.toggled.connect(_toggle)
        return group

    def _detect_project_context(
        self, parent: QWidget | None, project_root: Path | None
    ) -> tuple[Path | None, str | None, dict[str, str]]:
        if project_root and Path(project_root).exists():
            root = Path(project_root).resolve()
        else:
            proj = getattr(parent, "currentProject", None)
            if proj and hasattr(proj, "project_root"):
                root = Path(proj.project_root).resolve()
            else:
                root = Path(auto_detect_project_dir()).resolve()

        results_folder_hint: str | None = None
        subfolder_hints: dict[str, str] = {}
        manifest_path = root / "project.json"
        if manifest_path.is_file():
            try:
                cfg = json.loads(manifest_path.read_text(encoding="utf-8"))
                results_folder_hint, subfolder_hints = load_manifest_data(root, cfg)
            except Exception as exc:  # noqa: BLE001
                self._queue_log(f"Failed to load project manifest: {exc}")
        return root, results_folder_hint, subfolder_hints

    def _preferred_excel_root(self) -> Path | None:
        target = resolve_project_subfolder(
            self._project_root,
            self._results_folder_hint,
            self._subfolder_hints,
            "excel",
            EXCEL_SUBFOLDER_NAME,
        )
        if target.exists() and target.is_dir():
            return target
        self._queue_log(f"Default Excel folder not found at '{target}'. Please select a valid folder.")
        return None

    def _queue_log(self, message: str) -> None:
        if hasattr(self, "log_view"):
            self.append_log(message)
        else:
            self._pending_logs.append(message)

    def _flush_pending_logs(self) -> None:
        for msg in self._pending_logs:
            self.append_log(msg)
        self._pending_logs.clear()

    def _default_output_path(self) -> Path:
        folder = self._default_output_dir(self.excel_path_edit.text() or None)
        filename = self._build_suggested_filename()
        return (folder or Path.cwd()) / filename

    def _default_output_dir(self, excel_root: str | Path | None) -> Path | None:
        if self._project_root and self._project_root.exists():
            return resolve_project_subfolder(
                self._project_root,
                self._results_folder_hint,
                self._subfolder_hints,
                "ratio_results",
                "4 - Ratio Calculator Results",
            )
        if excel_root:
            fallback = Path(excel_root).parent
            self._queue_log(f"Using '{fallback}' for results because project root could not be resolved.")
            return fallback
        return None

    # View API for controller -------------------------------------------------
    def set_conditions(self, conditions: Iterable[str]) -> None:
        self.cond_a_combo.blockSignals(True)
        self.cond_b_combo.blockSignals(True)
        self.cond_a_combo.clear()
        self.cond_b_combo.clear()
        for cond in conditions:
            self.cond_a_combo.addItem(cond)
            self.cond_b_combo.addItem(cond)
        self.cond_a_combo.blockSignals(False)
        self.cond_b_combo.blockSignals(False)
        self._update_default_filename(force=False)

    def set_rois(self, rois: Iterable[ROI]) -> None:
        self._roi_definitions = list(rois)
        self.roi_combo.blockSignals(True)
        self.roi_combo.clear()
        if not self._roi_definitions:
            self.roi_combo.addItem("No ROIs defined in Settings")
            item = self.roi_combo.model().item(0)
            if item:
                item.setEnabled(False)
            self.compute_btn.setEnabled(False)
            self.append_log("No ROIs defined in Settings. Please add ROI pairs in Settings to proceed.")
        else:
            self.roi_combo.addItem("All ROIs")
            for roi in self._roi_definitions:
                self.roi_combo.addItem(roi.name)
            self.compute_btn.setEnabled(True)
        self.roi_combo.blockSignals(False)

    def append_log(self, message: str) -> None:
        self.log_view.append(message)
        self.statusBar().showMessage(message, 5000)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (
            self.excel_path_edit,
            self.excel_browse_btn,
            self.cond_a_combo,
            self.cond_b_combo,
            self.roi_combo,
            self.output_dir_edit,
            self.output_filename_edit,
            self.output_browse_btn,
            self.compute_btn,
        ):
            widget.setEnabled(not busy)
        self.progress.setVisible(busy or self.progress.value() > 0)

    def set_progress(self, value: int) -> None:
        self.progress.setValue(value)

    def status_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)
        self.append_log(message)

    def handle_result(self, result: RatioCalcResult) -> None:
        self._last_df = result.dataframe
        self.append_log(f"Saved results to {result.output_path}")
        self.statusBar().showMessage("Completed", 3000)

    # UI events --------------------------------------------------------------
    def _select_excel_root(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Excel root",
            str(self._project_root),
            options=QFileDialog.ShowDirsOnly,
        )
        if not directory:
            return
        self.excel_path_edit.setText(directory)
        default_output_dir = self._default_output_dir(Path(directory))
        if default_output_dir:
            self.output_dir_edit.setText(str(default_output_dir))
        self._update_default_filename(force=False)
        self.excel_root_changed.emit(Path(directory))

    def _select_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Select output folder",
            str(self._default_output_dir(self.excel_path_edit.text() or None) or self._project_root),
            options=QFileDialog.ShowDirsOnly,
        )
        if not path:
            return
        self.output_dir_edit.setText(path)

    def _on_compute(self) -> None:
        if self._busy:
            self.append_log("A computation is already running.")
            return
        excel_root_text = self.excel_path_edit.text().strip()
        if not excel_root_text:
            self.append_log("Please select a valid Excel root folder.")
            return
        excel_root = Path(excel_root_text)
        if not excel_root.exists():
            self.append_log("Please select a valid Excel root folder.")
            return
        cond_a = self.cond_a_combo.currentText()
        cond_b = self.cond_b_combo.currentText()
        if not cond_a or not cond_b or cond_a == cond_b:
            self.append_log("Please select two different conditions.")
            return
        roi_name = self.roi_combo.currentText() or None
        threshold = float(self.threshold_spin.value())
        significance_mode = self.significance_combo.currentData() or "group"
        output_path = self._resolve_output_path()
        if not self._roi_definitions:
            self.append_log("No ROIs available. Define ROIs in Settings before computing ratios.")
            return
        inputs = RatioCalcInputs(
            excel_root=excel_root,
            cond_a=cond_a,
            cond_b=cond_b,
            roi_name=roi_name,
            z_threshold=threshold,
            output_path=output_path,
            significance_mode=significance_mode,
            rois=self._roi_definitions,
        )
        self.compute_requested.emit(inputs)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._busy:
            event.ignore()
            self.append_log("Cannot close while computation is running.")
            return
        super().closeEvent(event)

    def _resolve_output_path(self) -> Path:
        filename = self.output_filename_edit.text().strip() or self._build_suggested_filename()
        if not filename.lower().endswith(".xlsx"):
            filename = f"{filename}.xlsx"
        output_dir_text = self.output_dir_edit.text().strip()
        output_dir = Path(output_dir_text) if output_dir_text else Path.cwd()
        if not output_dir_text:
            self._queue_log(f"No output folder selected; defaulting to '{output_dir}'.")
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir / filename

    def _build_suggested_filename(self) -> str:
        cond_a = self.cond_a_combo.currentText() or "condA"
        cond_b = self.cond_b_combo.currentText() or "condB"
        base = f"ratio_{cond_a}_vs_{cond_b}"
        return f"{self._sanitize_filename(base)}.xlsx"

    @staticmethod
    def _sanitize_filename(text: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
        return cleaned.strip("._") or "ratio_results"

    def _on_conditions_changed(self, _: str) -> None:
        self._update_default_filename(force=False)

    def _update_default_filename(self, force: bool) -> None:
        if self._filename_user_edited and not force:
            return
        suggested = self._build_suggested_filename()
        self.output_filename_edit.blockSignals(True)
        self.output_filename_edit.setText(suggested)
        self.output_filename_edit.blockSignals(False)
        if force:
            self._filename_user_edited = False

    def _on_filename_edited(self, _: str) -> None:
        self._filename_user_edited = True
