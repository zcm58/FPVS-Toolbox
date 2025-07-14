"""PySide6 GUI for generating SNR/BCA line plots from Excel files."""
from __future__ import annotations
# Allow running this module directly by ensuring the package root is on sys.path
if __package__ is None:  # pragma: no cover - executed when run as script
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parents[2]))
import os
from pathlib import Path
from typing import Dict, List, Iterable
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
from Main_App.settings_manager import SettingsManager
from Tools.Plot_Generator.plot_settings import PlotSettingsManager
from config import update_target_frequencies

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
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        out_dir: str,

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
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max

        self.out_dir = Path(out_dir)


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

        self.out_dir.mkdir(parents=True, exist_ok=True)

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


        roi_data: Dict[str, List[List[float]]] = {rn: [] for rn in roi_names}
        freqs: Iterable[float] | None = None

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

            if freqs is None:
                freqs = [float(c.split("_")[0]) for c in freq_cols]

            for roi in roi_names:
                chans = [c.upper() for c in self.roi_map.get(roi, [])]
                df_roi = df[df["Electrode"].str.upper().isin(chans)]
                if df_roi.empty:
                    self._emit(f"No electrodes for ROI {roi} in {excel_path.name}")
                    continue

                means = df_roi[freq_cols].mean().tolist()
                roi_data[roi].append(means)

        if not freqs:
            self._emit("No frequency data found.")
            return

        averaged: Dict[str, List[float]] = {}
        for roi, rows in roi_data.items():
            if not rows:
                self._emit(f"No data collected for ROI {roi}")
                continue
            averaged[roi] = list(pd.DataFrame(rows).mean(axis=0))

        if not averaged:
            self._emit("No ROI data to plot.")
            return

        self._plot(list(freqs), averaged)

    def _plot(self, freqs: List[float], roi_data: Dict[str, List[float]]) -> None:
        plt.rcParams.update({"font.family": "Times New Roman", "font.size": 12})

        for roi, amps in roi_data.items():
            fig, ax = plt.subplots(figsize=(8, 3), dpi=300)

            freq_amp = dict(zip(freqs, amps))
            bar_x = []
            bar_y = []
            for odd in self.oddballs:
                amp = freq_amp.get(odd)
                if amp is None:
                    continue
                bar_x.append(odd)
                bar_y.append(amp)

            if not bar_x:
                self._emit(f"Oddball frequencies not found for ROI {roi}")
                continue

            ax.bar(bar_x, bar_y, width=0.05, color="black", align="center")
            ax.set_xticks(self.oddballs)
            ax.set_xticklabels([f"{odd:.1f} Hz" for odd in self.oddballs])
            ax.set_xlim(self.x_min, self.x_max)
            ax.set_ylim(self.y_min, self.y_max)
            ax.axhline(0, color="gray", linestyle="--", linewidth=1, alpha=0.5)
            ax.set_xlabel(self.xlabel)
            ax.set_ylabel(self.ylabel)
            ax.set_title(f"{self.title}: {roi}")
            # for odd in self.oddballs:
            #     ax.axvline(x=odd, color="black", linewidth=0.8)
            #     ax.text(odd, ax.get_ylim()[0], f"{odd} Hz", ha="center", va="top")
            ax.grid(False)
            fig.tight_layout()
            fname = f"{self.condition}_{roi}_{self.metric}.png"
            fig.savefig(self.out_dir / fname)
            plt.close(fig)
            self._emit(f"Saved {fname}")



class PlotGeneratorWindow(QWidget):
    """Main window for generating plots."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate Plots")
        self.roi_map = load_rois_from_settings()

        mgr = SettingsManager()
        self.plot_mgr = PlotSettingsManager()
        default_in = self.plot_mgr.get("paths", "input_folder", "")
        default_out = self.plot_mgr.get("paths", "output_folder", "")
        main_default = mgr.get("paths", "output_folder", "")
        if not default_in:
            default_in = main_default
        if not default_out:
            default_out = main_default
        odd_freqs_text = ""
        try:
            odd = float(mgr.get("analysis", "oddball_freq", ""))
            upper = float(mgr.get("analysis", "bca_upper_limit", ""))
            if odd and upper:
                freqs = update_target_frequencies(odd, upper)
                odd_freqs_text = ", ".join(f"{f:g}" for f in freqs)
        except Exception:
            pass


        self._defaults = {
            "title_snr": "SNR Plot",
            "title_bca": "BCA Plot",
            "xlabel": "Frequency (Hz)",
            "ylabel_snr": "SNR",
            "ylabel_bca": "Baseline-corrected amplitude (µV)",
            "x_min": "0.0",
            "x_max": "10.0",
            "y_min_snr": "0.0",
            "y_max_snr": "3.0",
            "y_min_bca": "0.0",
            "y_max_bca": "0.3",

            "odd_freqs": odd_freqs_text,
            "input_folder": default_in,
            "output_folder": default_out,
        }

        self._build_ui()
        if default_in:
            self.folder_edit.setText(default_in)
            self._populate_conditions(default_in)
        if default_out:
            self.out_edit.setText(default_out)

        self._thread: QThread | None = None
        self._worker: _Worker | None = None

    def _build_ui(self) -> None:
        layout = QGridLayout(self)
        row = 0
        layout.addWidget(QLabel("Excel Files Folder:"), row, 0)
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)

        self.folder_edit.setText(self._defaults.get("input_folder", ""))

        layout.addWidget(self.folder_edit, row, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._select_folder)
        layout.addWidget(browse, row, 2)
        row += 1


        layout.addWidget(QLabel("Save Plots To:"), row, 0)
        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(True)
        self.out_edit.setText(self._defaults.get("output_folder", ""))

        layout.addWidget(self.out_edit, row, 1)
        browse_out = QPushButton("Browse…")
        browse_out.clicked.connect(self._select_output)
        layout.addWidget(browse_out, row, 2)
        row += 1


        layout.addWidget(QLabel("Condition:"), row, 0)
        self.condition_combo = QComboBox()
        self.condition_combo.currentTextChanged.connect(self._condition_changed)
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

        self.freq_edit = QLineEdit(self._defaults["odd_freqs"])

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

        layout.addWidget(QLabel("X min:"), row, 0)
        self.xmin_edit = QLineEdit(self._defaults["x_min"])
        layout.addWidget(self.xmin_edit, row, 1)
        layout.addWidget(QLabel("X max:"), row, 2)
        self.xmax_edit = QLineEdit(self._defaults["x_max"])
        layout.addWidget(self.xmax_edit, row, 3)
        row += 1

        layout.addWidget(QLabel("Y min:"), row, 0)
        self.ymin_edit = QLineEdit(self._defaults["y_min_snr"])
        layout.addWidget(self.ymin_edit, row, 1)
        layout.addWidget(QLabel("Y max:"), row, 2)
        self.ymax_edit = QLineEdit(self._defaults["y_max_snr"])
        layout.addWidget(self.ymax_edit, row, 3)
        row += 1

        self.apply_btn = QPushButton("Apply Settings")
        self.apply_btn.clicked.connect(self._apply_settings)
        layout.addWidget(self.apply_btn, row, 0)
        self.save_defaults_btn = QPushButton("Save Defaults")
        self.save_defaults_btn.clicked.connect(self._save_defaults)
        layout.addWidget(self.save_defaults_btn, row, 1)
        self.gen_btn = QPushButton("Generate")
        self.gen_btn.clicked.connect(self._generate)
        layout.addWidget(self.gen_btn, row, 2)
        row += 1

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, row, 0, 1, 4)

    def _metric_changed(self, metric: str) -> None:
        if metric == "SNR":
            self.ylabel_edit.setText(self._defaults["ylabel_snr"])
            self.ymin_edit.setText(self._defaults["y_min_snr"])
            self.ymax_edit.setText(self._defaults["y_max_snr"])
        else:
            self.ylabel_edit.setText(self._defaults["ylabel_bca"])
            self.ymin_edit.setText(self._defaults["y_min_bca"])
            self.ymax_edit.setText(self._defaults["y_max_bca"])

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Excel Folder")
        if folder:
            self.folder_edit.setText(folder)
            self._populate_conditions(folder)


    def _select_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.out_edit.setText(folder)

    def _condition_changed(self, condition: str) -> None:
        if condition:
            self.title_edit.setText(condition)

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
        if subfolders:
            self._condition_changed(subfolders[0])

    def _apply_settings(self) -> None:
        metric = self.metric_combo.currentText()
        if metric == "SNR":
            self._defaults["title_snr"] = self.title_edit.text()
            self._defaults["ylabel_snr"] = self.ylabel_edit.text()
            self._defaults["y_min_snr"] = self.ymin_edit.text()
            self._defaults["y_max_snr"] = self.ymax_edit.text()
        else:
            self._defaults["title_bca"] = self.title_edit.text()
            self._defaults["ylabel_bca"] = self.ylabel_edit.text()
            self._defaults["y_min_bca"] = self.ymin_edit.text()
            self._defaults["y_max_bca"] = self.ymax_edit.text()

        self._defaults["xlabel"] = self.xlabel_edit.text()
        self._defaults["x_min"] = self.xmin_edit.text()
        self._defaults["x_max"] = self.xmax_edit.text()

        self._defaults["odd_freqs"] = self.freq_edit.text()
        self._defaults["input_folder"] = self.folder_edit.text()
        self._defaults["output_folder"] = self.out_edit.text()

        QMessageBox.information(self, "Settings", "New settings have been applied.")

    def _save_defaults(self) -> None:
        self.plot_mgr.set("paths", "input_folder", self.folder_edit.text())
        self.plot_mgr.set("paths", "output_folder", self.out_edit.text())
        self.plot_mgr.save()
        QMessageBox.information(self, "Defaults", "Default folders saved.")

    def _append_log(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _generate(self) -> None:
        folder = self.folder_edit.text()
        if not folder:
            QMessageBox.critical(self, "Error", "Select a folder first.")
            return

        out_dir = self.out_edit.text()
        if not out_dir:
            QMessageBox.critical(self, "Error", "Select an output folder first.")
            return

        if not self.condition_combo.currentText():
            QMessageBox.critical(self, "Error", "No condition selected.")
            return
        try:
            oddballs = [float(v.strip()) for v in self.freq_edit.text().split(",") if v.strip()]
        except ValueError:
            QMessageBox.critical(self, "Error", "Invalid oddball frequencies.")
            return
        try:
            x_min = float(self.xmin_edit.text())
            x_max = float(self.xmax_edit.text())
            y_min = float(self.ymin_edit.text())
            y_max = float(self.ymax_edit.text())
        except ValueError:
            QMessageBox.critical(self, "Error", "Invalid axis limits.")
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
            x_min,
            x_max,
            y_min,
            y_max,

            out_dir,

        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._append_log)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._generation_finished)
        self._thread.start()

    def _generation_finished(self) -> None:
        self.gen_btn.setEnabled(True)
        self._thread = None
        self._worker = None

def main() -> None:
    app = QApplication([])
    win = PlotGeneratorWindow()
    win.show()
    app.exec()

if __name__ == "__main__":
    main()
