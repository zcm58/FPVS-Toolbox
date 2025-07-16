"""Worker classes for the plot generator."""
from __future__ import annotations

import os
import math
from pathlib import Path
from typing import Dict, List, Iterable, Sequence

import pandas as pd
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PySide6.QtCore import QObject, Signal

from Tools.Stats.stats_analysis import ALL_ROIS_OPTION
from Tools.Plot_Generator.snr_utils import calc_snr_matlab


class _Worker(QObject):
    """Worker to process Excel files and generate plots."""

    progress = Signal(str, int, int)
    finished = Signal()

    def __init__(
        self,
        folder: str,
        condition: str,
        metric: str,
        roi_map: Dict[str, List[str]],
        selected_roi: str,
        title: str,
        xlabel: str,
        ylabel: str,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        out_dir: str,
        stem_color: str = "red",
        *,
        oddballs: Sequence[float] | None = None,
        use_matlab_style: bool = False,
    ) -> None:
        super().__init__()
        self.folder = folder
        self.condition = condition
        self.metric = metric
        self.roi_map = roi_map
        self.selected_roi = selected_roi
        self.title = title
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max

        self.out_dir = Path(out_dir)
        self.stem_color = stem_color.lower()
        # maintain oddballs attribute for compatibility with older versions
        self.oddballs: List[float] = list(oddballs or [])
        self.use_matlab_style = use_matlab_style

    def run(self) -> None:
        try:
            self._run()
        finally:
            self.finished.emit()

    def _emit(self, msg: str, processed: int = 0, total: int = 0) -> None:
        self.progress.emit(msg, processed, total)

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

        total_files = len(excel_files)
        processed_files = 0
        self._emit(
            f"Found {total_files} Excel files in {cond_folder}", processed_files, total_files
        )

        roi_names = (
            list(self.roi_map.keys())
            if self.selected_roi == ALL_ROIS_OPTION
            else [self.selected_roi]
        )

        roi_data: Dict[str, List[List[float]]] = {rn: [] for rn in roi_names}
        freqs: Iterable[float] | None = None

        for excel_path in excel_files:
            self._emit(f"Reading {excel_path.name}", processed_files, total_files)
            try:
                if self.metric == "SNR":
                    xls = pd.ExcelFile(excel_path)
                    if "FullSNR" in xls.sheet_names:
                        df = pd.read_excel(xls, sheet_name="FullSNR")
                    else:
                        df_amp = pd.read_excel(xls, sheet_name="FFT Amplitude (uV)")
                        freq_cols_tmp = [
                            c for c in df_amp.columns if isinstance(c, str) and c.endswith("_Hz")
                        ]
                        snr_vals = df_amp[freq_cols_tmp].apply(
                            calc_snr_matlab, axis=1, result_type="expand"
                        )
                        snr_vals.columns = freq_cols_tmp
                        snr_vals.insert(0, "Electrode", df_amp["Electrode"])
                        df = snr_vals
                else:
                    df = pd.read_excel(excel_path, sheet_name="BCA (uV)")
            except Exception as e:  # pragma: no cover - simple logging
                self._emit(f"Failed reading {excel_path.name}: {e}")
                continue
            freq_cols = [c for c in df.columns if isinstance(c, str) and c.endswith("_Hz")]
            if not freq_cols:
                self._emit(f"No freq columns in {excel_path.name}", processed_files, total_files)
                processed_files += 1
                continue
            self._emit(
                f"Found {len(freq_cols)} frequency columns in {excel_path.name}",
                processed_files,
                total_files,
            )

            freq_pairs: List[tuple[float, str]] = []
            for col in freq_cols:
                try:
                    freq = float(col.split("_")[0])
                except ValueError:
                    continue
                freq_pairs.append((freq, col))

            freq_pairs.sort(key=lambda x: x[0])
            ordered_freqs = [f for f, _ in freq_pairs]
            ordered_cols = [c for _, c in freq_pairs]
            if freqs is None:
                freqs = ordered_freqs

            for roi in roi_names:
                chans = [c.upper() for c in self.roi_map.get(roi, [])]
                df_roi = df[df["Electrode"].str.upper().isin(chans)]
                if df_roi.empty:
                    self._emit(f"No electrodes for ROI {roi} in {excel_path.name}")
                    continue

                means = df_roi[ordered_cols].mean().tolist()
                roi_data[roi].append(means)

            processed_files += 1
            self._emit("", processed_files, total_files)

        if not freqs:
            self._emit("No frequency data found.", processed_files, total_files)
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

            line_color = self.stem_color

            freq_amp = dict(zip(freqs, amps))

            if self.metric == "SNR":
                stem_vals = amps
                ax.stem(
                    freqs,
                    stem_vals,
                    linefmt=line_color,
                    markerfmt=" ",
                    basefmt=" ",
                    bottom=1.0,
                )
                self._emit(
                    f"Plotted {len(stem_vals)} SNR stems for ROI {roi}", 0, 0
                )
            else:
                ax.plot(freqs, amps, color=line_color, linewidth=1)
                self._emit(
                    f"Plotted continuous line for ROI {roi}", 0, 0
                )

            mark_x: list[float] = []
            mark_y: list[float] = []
            for odd in self.oddballs:
                amp = freq_amp.get(odd)
                if amp is None:
                    amp = float(np.interp([odd], freqs, amps)[0])
                mark_x.append(odd)
                mark_y.append(amp)

            if mark_x and not self.use_matlab_style:
                ax.scatter(mark_x, mark_y, color="blue", zorder=3)
                self._emit(
                    f"Marked {len(mark_x)} oddball points on ROI {roi}", 0, 0
                )

            tick_start = math.ceil(self.x_min)
            tick_end = math.floor(self.x_max) + 1
            ax.set_xticks(range(tick_start, tick_end))
            ax.set_xlim(self.x_min, self.x_max)
            ax.set_ylim(self.y_min, self.y_max)
            for fx in range(max(1, tick_start), tick_end):
                ax.axvline(
                    fx,
                    color="lightgray",
                    linestyle="--",
                    linewidth=0.5,
                    zorder=0,
                )
            for y in range(math.ceil(self.y_min), math.floor(self.y_max) + 1):
                ax.axhline(
                    y,
                    color="lightgray",
                    linestyle="--",
                    linewidth=0.5,
                    zorder=0,
                )
            if not self.use_matlab_style:
                ax.axhline(1.0, color="gray", linestyle="--", linewidth=1, alpha=0.5)

            ax.set_xlabel(self.xlabel)
            ax.set_ylabel(self.ylabel)
            ax.set_title(f"{self.title}: {roi}")
            ax.grid(False)
            fig.tight_layout()
            fname = f"{self.condition}_{roi}_{self.metric}.png"
            fig.savefig(self.out_dir / fname)
            plt.close(fig)
            self._emit(f"Saved {fname}")
