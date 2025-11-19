"""Worker classes for the plot generator."""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import matplotlib
import numpy as np
import pandas as pd
from Main_App import SettingsManager

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PySide6.QtCore import QObject, Signal

from Tools.Stats.Legacy.stats_analysis import ALL_ROIS_OPTION
from Tools.Plot_Generator.snr_utils import calc_snr_matlab


_PID_PATTERN = re.compile(r"(?:[A-Za-z]*)?(P\d+)", re.IGNORECASE)


def _infer_subject_id_from_path(excel_path: Path) -> str | None:
    """Return a best-effort subject identifier inferred from the file name."""

    match = _PID_PATTERN.search(excel_path.stem)
    if match:
        return match.group(1).upper()
    cleaned = excel_path.stem.strip()
    return cleaned.upper() if cleaned else None

# Global plotting style applied after imports
plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 12,
        "lines.linewidth": 1.5,
        "xtick.major.size": 6,
        "ytick.major.size": 6,
    }
)


class _Worker(QObject):
    """Worker to process Excel files and generate plots."""

    progress = Signal(str, int, int)
    finished = Signal()

    def __init__(
        self,
        folder: str,
        condition: str,
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
        condition_b: str | None = None,
        stem_color_b: str = "blue",
        oddballs: Sequence[float] | None = None,
        use_matlab_style: bool = False,
        overlay: bool = False,
        subject_groups: Dict[str, str | None] | None = None,
        selected_groups: Sequence[str] | None = None,
        enable_group_overlay: bool = False,
        multi_group_mode: bool = False,
    ) -> None:
        super().__init__()
        self.folder = folder
        self.condition = condition
        self.roi_map = roi_map
        self.selected_roi = selected_roi
        self.metric = "SNR"
        self.title = title
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.x_min = x_min
        self.x_max = x_max
        self.y_min = y_min
        self.y_max = y_max

        self.out_dir = Path(out_dir)
        self.stem_color = stem_color.lower()
        self.stem_color_b = stem_color_b.lower()
        self.condition_b = condition_b
        self.overlay = overlay
        # maintain oddballs attribute for compatibility with older versions
        self.oddballs: List[float] = list(oddballs or [])
        self.use_matlab_style = use_matlab_style
        self._stop_requested = False
        normalized_groups = {
            pid.upper(): grp
            for pid, grp in (subject_groups or {}).items()
            if isinstance(pid, str) and isinstance(grp, str)
        }
        self.subject_groups: Dict[str, str] = normalized_groups
        ordered = [g for g in (selected_groups or []) if isinstance(g, str) and g]
        self.selected_groups: List[str] = ordered
        self._selected_group_set = set(ordered)
        self.enable_group_overlay = bool(enable_group_overlay and ordered)
        self.multi_group_mode = multi_group_mode
        self._unknown_subject_files: set[str] = set()

    def run(self) -> None:
        try:
            self._run()
        finally:
            self.finished.emit()

    def stop(self) -> None:
        self._stop_requested = True

    def _emit(self, msg: str, processed: int = 0, total: int = 0) -> None:
        self.progress.emit(msg, processed, total)

    def _selected_roi_names(self) -> List[str]:
        return list(self.roi_map.keys()) if self.selected_roi == ALL_ROIS_OPTION else [self.selected_roi]

    def _aggregate_roi_data(
        self,
        subject_data: Dict[str, Dict[str, List[float]]],
        subjects: Iterable[str] | None = None,
    ) -> Dict[str, List[float]]:
        roi_names = self._selected_roi_names()
        filtered = set(subjects) if subjects is not None else None
        aggregated: Dict[str, List[float]] = {}
        for roi in roi_names:
            rows: List[List[float]] = []
            for pid, roi_values in subject_data.items():
                if filtered is not None and pid not in filtered:
                    continue
                values = roi_values.get(roi)
                if values:
                    rows.append(values)
            if rows:
                aggregated[roi] = list(pd.DataFrame(rows).mean(axis=0))
        return aggregated

    def _build_group_curves(
        self,
        subject_data: Dict[str, Dict[str, List[float]]],
    ) -> Dict[str, Dict[str, List[float]]]:
        if not self.enable_group_overlay or not self.subject_groups:
            self._unknown_subject_files.clear()
            return {}

        # Group overlays ride on top of the same averaged ROI curves that power
        # the single-subject plot. We simply filter the already aggregated
        # ``subject_data`` per group so the worker never re-reads Excel files or
        # blocks the UI thread with redundant IO.
        per_group: Dict[str, Dict[str, List[float]]] = {}
        for group in self.selected_groups:
            subjects = {
                pid
                for pid, grp in self.subject_groups.items()
                if grp == group and pid in subject_data
            }
            if not subjects:
                continue
            aggregated = self._aggregate_roi_data(subject_data, subjects)
            if aggregated:
                per_group[group] = aggregated

        if not per_group:
            self._emit(
                "No participants assigned to the selected groups. Showing overall average only.",
                0,
                0,
            )
        self._warn_unknown_subjects()
        return per_group

    def _warn_unknown_subjects(self) -> None:
        if (
            self.multi_group_mode
            and self.enable_group_overlay
            and self._unknown_subject_files
        ):
            files = ", ".join(sorted(self._unknown_subject_files))
            self._emit(
                "Warning: The following Excel files lack group assignments and were excluded from group overlays:"
                f" {files}",
                0,
                0,
            )
            self._unknown_subject_files.clear()

    def _count_excel_files(self, condition: str) -> int:
        """Return the number of Excel files for a condition."""
        cond_folder = Path(self.folder) / condition
        if not cond_folder.is_dir():
            return 0
        return sum(
            1
            for root, _, files in os.walk(cond_folder)
            for f in files
            if f.lower().endswith(".xlsx")
        )

    def _collect_data(
        self,
        condition: str,
        *,
        offset: int = 0,
        total_override: int | None = None,
    ) -> tuple[List[float], Dict[str, Dict[str, List[float]]]]:
        cond_folder = Path(self.folder) / condition
        if not cond_folder.is_dir():
            self._emit(f"Condition folder not found: {cond_folder}")
            return [], {}

        self.out_dir.mkdir(parents=True, exist_ok=True)

        excel_files = [
            Path(root) / f
            for root, _, files in os.walk(cond_folder)
            for f in files
            if f.lower().endswith(".xlsx")
        ]
        if not excel_files:
            self._emit("No Excel files found for condition.")
            return [], {}

        total_files = len(excel_files)
        overall_total = total_override if total_override is not None else total_files
        processed_files = 0
        self._emit(
            f"Found {total_files} Excel files in {cond_folder}",
            offset + processed_files,
            overall_total,
        )

        roi_names = self._selected_roi_names()

        subject_roi_data: Dict[str, Dict[str, List[float]]] = {}
        freqs: Iterable[float] | None = None
        self._unknown_subject_files.clear()

        for excel_path in excel_files:
            if self._stop_requested:
                self._emit("Generation cancelled by user.")
                return
            self._emit(
                f"Reading {excel_path.name}",
                offset + processed_files,
                overall_total,
            )
            try:
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
            except Exception as e:  # pragma: no cover - simple logging
                self._emit(f"Failed reading {excel_path.name}: {e}")
                continue
            freq_cols = [c for c in df.columns if isinstance(c, str) and c.endswith("_Hz")]
            if not freq_cols:
                self._emit(
                    f"No freq columns in {excel_path.name}",
                    offset + processed_files,
                    overall_total,
                )
                processed_files += 1
                continue
            self._emit(
                f"Found {len(freq_cols)} frequency columns in {excel_path.name}",
                offset + processed_files,
                overall_total,
            )

            subject_id = _infer_subject_id_from_path(excel_path)
            if not subject_id:
                self._emit(
                    f"Skipping {excel_path.name}: unable to determine subject ID.",
                    offset + processed_files,
                    overall_total,
                )
                processed_files += 1
                continue
            if (
                self.enable_group_overlay
                and self.multi_group_mode
                and self.subject_groups
                and subject_id not in self.subject_groups
            ):
                self._unknown_subject_files.add(excel_path.name)

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
                subject_roi_data.setdefault(subject_id, {})[roi] = means

            processed_files += 1
            self._emit("", offset + processed_files, overall_total)

        if not freqs:
            self._emit(
                "No frequency data found.",
                offset + processed_files,
                overall_total,
            )
            return [], {}

        if not subject_roi_data:
            self._emit("No ROI data to plot.")
            return [], {}

        return list(freqs), subject_roi_data

    def _run(self) -> None:
        if self.overlay and self.condition_b:
            total_a = self._count_excel_files(self.condition)
            total_b = self._count_excel_files(self.condition_b)
            total = total_a + total_b
            freqs_a, data_a = self._collect_data(
                self.condition,
                offset=0,
                total_override=total,
            )
            freqs_b, data_b = self._collect_data(
                self.condition_b,
                offset=total_a,
                total_override=total,
            )
            if freqs_a and data_a and freqs_b and data_b:
                avg_a = self._aggregate_roi_data(data_a)
                avg_b = self._aggregate_roi_data(data_b)
                if avg_a and avg_b:
                    self._plot_overlay(freqs_a, avg_a, avg_b)
            return

        freqs, subject_data = self._collect_data(self.condition)
        if freqs and subject_data:
            averaged = self._aggregate_roi_data(subject_data)
            if not averaged:
                self._emit("No ROI data to plot.")
                return
            group_curves = self._build_group_curves(subject_data)
            self._plot(freqs, averaged, group_curves)

    def _plot(
        self,
        freqs: List[float],
        roi_data: Dict[str, List[float]],
        group_curves: Dict[str, Dict[str, List[float]]] | None = None,
    ) -> None:
        mgr = SettingsManager()
        harm_str = mgr.get(
            "loreta",
            "oddball_harmonics",
            "1.2,2.4,3.6,4.8,7.2,8.4,9.6,10.8",
        )
        try:
            cfg_odds = [float(h) for h in harm_str.replace(";", ",").split(",") if h.strip()]
        except Exception:
            cfg_odds = []
        odd_freqs = self.oddballs if self.oddballs else cfg_odds


        group_curves = group_curves or {}
        use_group_overlay = bool(group_curves)
        color_cycle = plt.rcParams.get("axes.prop_cycle")
        palette = (
            color_cycle.by_key().get("color", []) if color_cycle else []
        ) or [
            "#1f77b4",
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
            "#9467bd",
            "#8c564b",
        ]

        for roi, amps in roi_data.items():
            if self._stop_requested:
                self._emit("Generation cancelled by user.")
                return
            fig, ax = plt.subplots(figsize=(12, 4))

            if use_group_overlay:
                plotted = False
                for idx, group_name in enumerate(self.selected_groups or group_curves.keys()):
                    data = group_curves.get(group_name)
                    if not data:
                        continue
                    vals = data.get(roi)
                    if not vals:
                        continue
                    color = palette[idx % len(palette)]
                    ax.plot(
                        freqs,
                        vals,
                        label=group_name,
                        color=color,
                        linewidth=2.0,
                    )
                    plotted = True
                ax.plot(
                    freqs,
                    amps,
                    color=self.stem_color,
                    linestyle="--",
                    linewidth=1.5,
                    label="All Subjects",
                )
                if not plotted:
                    self._emit(
                        "No group data available for overlay. Displaying overall average only.",
                        0,
                        0,
                    )
            else:
                line_color = self.stem_color
                stem_vals = amps
                cont = ax.stem(
                    freqs,
                    stem_vals,
                    linefmt=line_color,
                    markerfmt=" ",
                    basefmt=" ",
                    bottom=1.0,
                )
                cont.markerline.set_label(self.metric)
                self._emit(
                    f"Plotted {len(stem_vals)} SNR stems for ROI {roi}", 0, 0
                )

            if use_group_overlay and (not odd_freqs or self.use_matlab_style):
                ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=True)

            if odd_freqs and not self.use_matlab_style:
                freq_array = np.array(freqs)
                for idx, odd in enumerate(odd_freqs):
                    closest = int(np.abs(freq_array - odd).argmin())
                    label = "Oddball Peaks" if idx == 0 else "_nolegend_"
                    ax.scatter(
                        freq_array[closest],
                        amps[closest],
                        facecolor="red",
                        edgecolor="black",
                        zorder=4,
                        label=label,
                    )
                ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=True)
                self._emit(
                    f"Marked {len(odd_freqs)} oddball points on ROI {roi}", 0, 0
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
                ax.axhline(1.0, color="gray", linestyle="--", linewidth=1)

            ax.set_xlabel(self.xlabel)
            ax.set_ylabel(self.ylabel)
            ax.grid(axis="y", linestyle=":", linewidth=0.8, color="gray")

            combined_title = f"{self.title}: {roi}"
            fig.suptitle(combined_title, fontsize=16, ha="center", va="top")
            fig.tight_layout(rect=[0, 0, 1, 0.95])
            fname = f"{self.condition}_{roi}_{self.metric}.png"
            fig.savefig(self.out_dir / fname, dpi=300, bbox_inches="tight", pad_inches=0.05)
            plt.close(fig)
            self._emit(f"Saved {fname}")

    def _plot_overlay(
        self,
        freqs: List[float],
        data_a: Dict[str, List[float]],
        data_b: Dict[str, List[float]],
    ) -> None:
        plt.rcParams.update({"font.family": "Times New Roman", "font.size": 12})
        mgr = SettingsManager()
        harm_str = mgr.get(
            "loreta",
            "oddball_harmonics",
            "1.2,2.4,3.6,4.8,7.2,8.4,9.6,10.8",
        )
        try:
            cfg_odds = [float(h) for h in harm_str.replace(";", ",").split(",") if h.strip()]
        except Exception:
            cfg_odds = []
        odd_freqs = self.oddballs if self.oddballs else cfg_odds

        for roi in data_a:
            if self._stop_requested:
                self._emit("Generation cancelled by user.")
                return
            fig, ax = plt.subplots(figsize=(12, 4))
            ax.plot(freqs, data_a[roi], color=self.stem_color, label=self.condition)
            ax.plot(freqs, data_b.get(roi, []), color=self.stem_color_b, label=self.condition_b)

            if odd_freqs:
                freq_array = np.array(freqs)
                for idx, odd in enumerate(odd_freqs):
                    closest = int(np.abs(freq_array - odd).argmin())
                    val_a = data_a[roi][closest]
                    val_b = data_b[roi][closest]
                    label_a = "A-Peaks" if idx == 0 else "_nolegend_"
                    label_b = "B-Peaks" if idx == 0 else "_nolegend_"
                    ax.scatter(
                        freq_array[closest],
                        val_a,
                        marker="o",
                        facecolor=self.stem_color,
                        edgecolor="black",
                        zorder=4,
                        label=label_a,
                    )
                    ax.scatter(
                        freq_array[closest],
                        val_b,
                        marker="^",
                        facecolor=self.stem_color_b,
                        edgecolor="black",
                        zorder=4,
                        label=label_b,
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
                ax.axhline(1.0, color="gray", linestyle="--", linewidth=1)

            ax.set_xlabel(self.xlabel)
            ax.set_ylabel(self.ylabel)
            base = self.title or f"{self.condition} vs {self.condition_b}"
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), frameon=True)
            ax.grid(axis="y", linestyle=":", linewidth=0.8, color="gray")

            combined_title = f"{base}: {roi}"
            fig.suptitle(combined_title, fontsize=16, ha="center", va="top")
            fig.tight_layout(rect=[0, 0, 1, 0.95])
            fname = f"{self.condition}_vs_{self.condition_b}_{roi}_{self.metric}.png"
            fig.savefig(self.out_dir / fname, dpi=300, bbox_inches="tight", pad_inches=0.05)
            plt.close(fig)
            self._emit(f"Saved {fname}")
