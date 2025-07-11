"""PySide6 GUI for generating SNR/BCA line plots from Excel files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Ensure no GUI backend required
import matplotlib.pyplot as plt

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QComboBox,
    QPlainTextEdit,
    QWidget,
)

from Tools.Stats.stats_helpers import load_rois_from_settings
from Tools.Stats.stats_analysis import ALL_ROIS_OPTION


class _Worker(QObject):
    """Worker to process Excel files and generate plots."""

    progress = Signal(str)
    finished = Signal()

    def __init__(
        self,
        folder: str,
        condition: str,
        metric: str,
        roi_map: Dict[str, List[str]],
        selected_roi: str,
        oddballs: List[float],
        title: str,
        xlabel: str,
        ylabel: str,
    ) -> None:
        super().__init__()
        self.folder = folder
        self.condition = condition
        self.metric = metric
        self.roi_map = roi_map
        self.selected_roi = selected_roi
        self.oddballs = oddballs
        self.title = title
        self.xlabel = xlabel
        self.ylabel = ylabel

    def run(self) -> None:
        try:
            self._run()
        finally:
            self.finished.emit()

    def _emit(self, msg: str) -> None:
        self.progress.emit(msg)

    def _run(self) -> None:
        cond_folder = Path(self.folder) / self.condition
        if not cond_folder.is_dir():
            self._emit(f"Condition folder not found: {cond_folder}")
            return
        excel_files = [
            Path(root) / f
            for root, _, files in os.walk(cond_folder)
            for f in files
            if f.lower().endswith(".xlsx")
        ]
        if not excel_files:
            self._emit("No Excel files found for condition.")
            return

        sheet = "SNR" if self.metric == "SNR" else "BCA (uV)"
        roi_names = (
            list(self.roi_map.keys())
            if self.selected_roi == ALL_ROIS_OPTION
            else [self.selected_roi]
        )
        for excel_path in excel_files:
            try:
                df = pd.read_excel(excel_path, sheet_name=sheet)
            except Exception as e:  # pragma: no cover - simple logging
                self._emit(f"Failed reading {excel_path.name}: {e}")
                continue
            freq_cols = [c for c in df.columns if isinstance(c, str) and c.endswith("_Hz")]
            if not freq_cols:
                self._emit(f"No freq columns in {excel_path.name}")
                continue
            freqs = [float(c.split("_")[0]) for c in freq_cols]
            for roi in roi_names:
                chans = [c.upper() for c in self.roi_map.get(roi, [])]
                df_roi = df[df["Electrode"].str.upper().isin(chans)]
                if df_roi.empty:
                    self._emit(f"No electrodes for ROI {roi} in {excel_path.name}")
                    continue
                means = df_roi[freq_cols].mean().values
                self._plot(freqs, means, roi, excel_path.parent)

    def _plot(self, freqs: List[float], amps, roi: str, out_dir: Path) -> None:
        plt.rcParams.update({"font.family": "Times New Roman", "font.size": 12})
        fig, ax = plt.subplots(figsize=(8, 3), dpi=300)
        ax.plot(freqs, amps, color="black", linewidth=1.0)
        ax.set_xlim(0, max(freqs) + 0.5)
        ax.set_ylim(-0.05, 0.30)
        ax.set_xlabel(self.xlabel)
        ax.set_ylabel(self.ylabel)
        ax.set_title(self.title)
        for odd in self.oddballs:
            ax.axvline(x=odd, color="black", linewidth=0.8)
            ax.text(odd, ax.get_ylim()[0], f"{odd} Hz", ha="center", va="top")
        ax.grid(False)
        fig.tight_layout()
        fname = f"{self.condition}_{roi}_{self.metric}.png"
        fig.savefig(out_dir / fname)
        plt.close(fig)
        self._emit(f"Saved {fname}")


class PlotGeneratorWindow(QWidget):
    """Main window for generating plots."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate Plots")
        self.roi_map = load_rois_from_settings()
        self._defaults = {
            "title_snr": "SNR Plot",
            "title_bca": "BCA Plot",
            "xlabel": "Frequency (Hz)",
            "ylabel_snr": "SNR",
            "ylabel_bca": "Baseline-corrected amplitude (µV)",
        }
        self._build_ui()
        self._thread: QThread | None = None
        self._worker: _Worker | None = None

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        row = 0
        layout.addWidget(QLabel("Excel Files Folder:"), row, 0)
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        layout.addWidget(self.folder_edit, row, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._select_folder)
        layout.addWidget(browse, row, 2)
        row += 1

        layout.addWidget(QLabel("Condition:"), row, 0)
        self.condition_combo = QComboBox()
        layout.addWidget(self.condition_combo, row, 1, 1, 2)
        row += 1

        layout.addWidget(QLabel("Metric:"), row, 0)
        self.metric_combo = QComboBox()
        self.metric_combo.addItems(["SNR", "BCA"])
        self.metric_combo.currentTextChanged.connect(self._metric_changed)
        layout.addWidget(self.metric_combo, row, 1, 1, 2)
        row += 1

        layout.addWidget(QLabel("ROI:"), row, 0)
        self.roi_combo = QComboBox()
        self.roi_combo.addItems([ALL_ROIS_OPTION] + list(self.roi_map.keys()))
        layout.addWidget(self.roi_combo, row, 1, 1, 2)
        row += 1

        layout.addWidget(QLabel("Oddball frequencies (Hz):"), row, 0)
        self.freq_edit = QLineEdit()
        layout.addWidget(self.freq_edit, row, 1, 1, 2)
        row += 1

        layout.addWidget(QLabel("Chart title:"), row, 0)
        self.title_edit = QLineEdit(self._defaults["title_snr"])
        layout.addWidget(self.title_edit, row, 1, 1, 2)
        row += 1

        layout.addWidget(QLabel("X-axis label:"), row, 0)
        self.xlabel_edit = QLineEdit(self._defaults["xlabel"])
        layout.addWidget(self.xlabel_edit, row, 1, 1, 2)
        row += 1

        layout.addWidget(QLabel("Y-axis label:"), row, 0)
        self.ylabel_edit = QLineEdit(self._defaults["ylabel_snr"])
        layout.addWidget(self.ylabel_edit, row, 1, 1, 2)
        row += 1

        self.apply_btn = QPushButton("Apply Settings")
        self.apply_btn.clicked.connect(self._apply_settings)
        layout.addWidget(self.apply_btn, row, 0)
        self.gen_btn = QPushButton("Generate")
        self.gen_btn.clicked.connect(self._generate)
        layout.addWidget(self.gen_btn, row, 1)
        row += 1

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, row, 0, 1, 3)

    def _metric_changed(self, metric: str) -> None:
        if metric == "SNR":
            self.ylabel_edit.setText(self._defaults["ylabel_snr"])
            self.title_edit.setText(self._defaults["title_snr"])
        else:
            self.ylabel_edit.setText(self._defaults["ylabel_bca"])
            self.title_edit.setText(self._defaults["title_bca"])

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Excel Folder")
        if folder:
            self.folder_edit.setText(folder)
            self._populate_conditions(folder)

    def _populate_conditions(self, folder: str) -> None:
        self.condition_combo.clear()
        try:
            subfolders = [
                f.name
                for f in Path(folder).iterdir()
                if f.is_dir()
            ]
        except Exception:
            subfolders = []
        self.condition_combo.addItems(subfolders)

    def _apply_settings(self) -> None:
        self._defaults["title_snr"] = self.title_edit.text()
        self._defaults["title_bca"] = self.title_edit.text()
        self._defaults["xlabel"] = self.xlabel_edit.text()
        self._defaults["ylabel_snr"] = self.ylabel_edit.text()
        self._defaults["ylabel_bca"] = self.ylabel_edit.text()
        QMessageBox.information(self, "Settings", "New settings have been applied.")

    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _generate(self) -> None:
        folder = self.folder_edit.text()
        if not folder:
            QMessageBox.critical(self, "Error", "Select a folder first.")
            return
        if not self.condition_combo.currentText():
            QMessageBox.critical(self, "Error", "No condition selected.")
            return
        try:
            oddballs = [float(v.strip()) for v in self.freq_edit.text().split(",") if v.strip()]
        except ValueError:
            QMessageBox.critical(self, "Error", "Invalid oddball frequencies.")
            return

        self.gen_btn.setEnabled(False)
        self.log.clear()
        self._thread = QThread()
        self._worker = _Worker(
            folder,
            self.condition_combo.currentText(),
            self.metric_combo.currentText(),
            self.roi_map,
            self.roi_combo.currentText(),
            oddballs,
            self.title_edit.text(),
            self.xlabel_edit.text(),
            self.ylabel_edit.text(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._append_log)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(lambda: self.gen_btn.setEnabled(True))
        self._thread.start()


def main() -> None:
    app = QApplication([])
    win = PlotGeneratorWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
