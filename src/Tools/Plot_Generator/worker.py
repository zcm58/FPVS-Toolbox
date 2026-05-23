"""Worker classes for the plot generator."""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import matplotlib
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
import numpy as np
import pandas as pd
import mne
from Main_App import SettingsManager

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PySide6.QtCore import QObject, Signal

from Tools.Stats.analysis.stats_analysis import ALL_ROIS_OPTION
from Tools.Plot_Generator.data_collection import PlotDataCollectionMixin
from Tools.Plot_Generator.excel_inputs import (
    _frequency_pairs_from_columns,
    _infer_subject_id_from_path,
    _select_frequency_pairs,
)
from Tools.Plot_Generator.scalp_utils import (
    ScalpInputs,
    prepare_scalp_inputs,
    select_oddball_harmonics,
)
from Tools.Plot_Generator.worker_config import PlotWorkerConfig

logger = logging.getLogger(__name__)
_DEFAULT_A_PEAKS = "A-Peaks"
_DEFAULT_B_PEAKS = "B-Peaks"
_DEFAULT_ODDBALL_FREQ = 1.2
__all__ = [
    "_Worker",
    "_frequency_pairs_from_columns",
    "_infer_subject_id_from_path",
    "_select_frequency_pairs",
]


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


_ZERO_MIDPOINT_COLOR = "#b6e3b6"
_SCALP_CMAP = LinearSegmentedColormap.from_list(
    "BlueGreenRed",
    ["#2166ac", _ZERO_MIDPOINT_COLOR, "#b2182b"],
)


class _Worker(QObject, PlotDataCollectionMixin):
    """Worker to process Excel files and generate plots."""

    progress = Signal(str, int, int)
    finished = Signal(dict)

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
        include_scalp_maps: bool = False,
        scalp_vmin: float = -1.0,
        scalp_vmax: float = 1.0,
        scalp_title_a_template: str = "{condition} {roi} scalp map",
        scalp_title_b_template: str = "{condition} {roi} scalp map",
        legend_custom_enabled: bool = False,
        legend_condition_a: str | None = None,
        legend_condition_b: str | None = None,
        legend_a_peaks: str | None = None,
        legend_b_peaks: str | None = None,
        project_root: str | None = None,
    ) -> None:
        super().__init__()
        self.config = PlotWorkerConfig(
            folder=folder,
            condition=condition,
            roi_map=roi_map,
            selected_roi=selected_roi,
            title=title,
            xlabel=xlabel,
            ylabel=ylabel,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            out_dir=out_dir,
            stem_color=stem_color,
            condition_b=condition_b,
            stem_color_b=stem_color_b,
            oddballs=oddballs,
            use_matlab_style=use_matlab_style,
            overlay=overlay,
            subject_groups=subject_groups,
            selected_groups=selected_groups,
            enable_group_overlay=enable_group_overlay,
            multi_group_mode=multi_group_mode,
            include_scalp_maps=include_scalp_maps,
            scalp_vmin=scalp_vmin,
            scalp_vmax=scalp_vmax,
            scalp_title_a_template=scalp_title_a_template,
            scalp_title_b_template=scalp_title_b_template,
            legend_custom_enabled=legend_custom_enabled,
            legend_condition_a=legend_condition_a,
            legend_condition_b=legend_condition_b,
            legend_a_peaks=legend_a_peaks,
            legend_b_peaks=legend_b_peaks,
            project_root=project_root,
        )
        self.folder = self.config.folder
        self.condition = self.config.condition
        self.roi_map = self.config.roi_map
        self.selected_roi = self.config.selected_roi
        self.metric = "SNR"
        self.title = self.config.title
        self.xlabel = self.config.xlabel
        self.ylabel = self.config.ylabel
        self.x_min = self.config.x_min
        self.x_max = self.config.x_max
        self.y_min = self.config.y_min
        self.y_max = self.config.y_max

        self.out_dir = Path(self.config.out_dir)
        self.stem_color = self.config.stem_color.lower()
        self.stem_color_b = self.config.stem_color_b.lower()
        self.condition_b = self.config.condition_b
        self.overlay = self.config.overlay
        self._analysis_base_freq = self._read_analysis_float("base_freq", 0.0)
        self._analysis_oddball_freq = self._read_analysis_float(
            "oddball_freq", _DEFAULT_ODDBALL_FREQ
        )
        # Maintain explicit oddballs override for compatibility with older callers.
        if self.config.oddballs:
            parsed_oddballs: List[float] = []
            for odd in self.config.oddballs:
                try:
                    odd_val = float(odd)
                except Exception:
                    continue
                if not math.isfinite(odd_val) or odd_val <= 0:
                    continue
                parsed_oddballs.append(odd_val)
            self.oddballs = parsed_oddballs
        else:
            self.oddballs = self._derive_oddball_harmonics(self.x_max)
        self.use_matlab_style = self.config.use_matlab_style
        self._stop_requested = False
        normalized_groups = {
            pid.upper(): grp
            for pid, grp in (self.config.subject_groups or {}).items()
            if isinstance(pid, str) and isinstance(grp, str)
        }
        self.subject_groups: Dict[str, str] = normalized_groups
        ordered = [g for g in (self.config.selected_groups or []) if isinstance(g, str) and g]
        self.selected_groups: List[str] = ordered
        self._selected_group_set = set(ordered)
        self.enable_group_overlay = bool(self.config.enable_group_overlay and ordered)
        self.multi_group_mode = self.config.multi_group_mode
        self._unknown_subject_files: set[str] = set()
        self.include_scalp_maps = self.config.include_scalp_maps
        self.scalp_vmin = self.config.scalp_vmin
        self.scalp_vmax = self.config.scalp_vmax
        self.scalp_title_a_template = self.config.scalp_title_a_template
        self.scalp_title_b_template = self.config.scalp_title_b_template
        self._scalp_title_warned = False
        self.legend_custom_enabled = self.config.legend_custom_enabled
        self.legend_condition_a = self.config.legend_condition_a
        self.legend_condition_b = self.config.legend_condition_b
        self.legend_a_peaks = self.config.legend_a_peaks
        self.legend_b_peaks = self.config.legend_b_peaks
        self.project_root = self.config.project_root
        self.generated_paths: list[str] = []
        self.failed_items: list[dict[str, str]] = []
        self._timings: dict[str, float] = {
            "excel_load": 0.0,
            "roi_aggregate": 0.0,
            "scalp_prepare": 0.0,
            "plot_render": 0.0,
            "file_save": 0.0,
        }

    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:
            self._record_failure(
                item=self.condition,
                error=f"Unhandled worker exception: {exc}",
            )
            logger.error(
                "SNR plot generation failed.",
                exc_info=exc,
                extra={
                    "operation": "snr_plot_generate",
                    "project_root": self.project_root,
                    "compare_two_conditions": self.overlay,
                    "custom_labels_enabled": self.legend_custom_enabled,
                },
            )
            self._emit("SNR plot generation failed. See logs for details.", 0, 0)
        finally:
            self._emit_timing_summary()
            self.finished.emit(
                {
                    "condition": self.condition,
                    "overlay": self.overlay,
                    "generated_paths": list(self.generated_paths),
                    "failed_items": list(self.failed_items),
                }
            )

    def stop(self) -> None:
        self._stop_requested = True

    def _emit(self, msg: str, processed: int = 0, total: int = 0) -> None:
        self.progress.emit(msg, processed, total)

    def _mark_timing(self, phase: str, started: float) -> None:
        self._timings[phase] = self._timings.get(phase, 0.0) + (
            time.perf_counter() - started
        )

    def _timed_call(self, phase: str, callback):
        started = time.perf_counter()
        try:
            return callback()
        finally:
            self._mark_timing(phase, started)

    def _read_excel_timed(self, *args, **kwargs) -> pd.DataFrame:
        return self._timed_call("excel_load", lambda: pd.read_excel(*args, **kwargs))

    def _emit_timing_summary(self) -> None:
        total = sum(self._timings.values())
        if total <= 0:
            return
        parts = [
            f"{name.replace('_', ' ')}={seconds:.2f}s"
            for name, seconds in self._timings.items()
            if seconds > 0
        ]
        if not parts:
            return
        message = "Timing summary: " + ", ".join(parts) + f", total={total:.2f}s"
        self._emit(message, 0, 0)
        logger.info(
            "SNR plot generation timing summary.",
            extra={
                "operation": "snr_plot_generate",
                "project_root": self.project_root,
                "condition": self.condition,
                "timings": {key: round(value, 4) for key, value in self._timings.items()},
                "timed_total_seconds": round(total, 4),
            },
        )

    def _resolve_legend_label(self, custom: str | None, default: str) -> str:
        if self.legend_custom_enabled and custom is not None and custom.strip():
            return custom.strip()
        return default

    def _record_generated_path(self, path: Path) -> None:
        self.generated_paths.append(str(path))

    def _record_failure(self, *, item: str, error: str) -> None:
        self.failed_items.append({"item": item, "error": error})

    def _read_analysis_float(self, option: str, fallback: float) -> float:
        try:
            mgr = SettingsManager()
            raw = mgr.get("analysis", option, str(fallback))
            value = float(raw)
        except Exception:
            return fallback
        return value if math.isfinite(value) else fallback

    def _derive_oddball_harmonics(self, max_hz: float) -> List[float]:
        if not math.isfinite(max_hz) or max_hz <= 0:
            return []

        oddball_freq = self._analysis_oddball_freq
        if not math.isfinite(oddball_freq) or oddball_freq <= 0:
            oddball_freq = _DEFAULT_ODDBALL_FREQ

        max_harmonic = int(math.floor((max_hz / oddball_freq) + 1e-9))
        if max_harmonic < 1:
            return []

        configured = [oddball_freq * idx for idx in range(1, max_harmonic + 1)]
        selected = select_oddball_harmonics(configured, base_freq=self._analysis_base_freq)
        return sorted(
            {
                round(freq, 4)
                for freq in selected
                if math.isfinite(freq) and freq > 0
            }
        )

    def _visible_oddball_frequencies(self, freqs: Sequence[float]) -> List[float]:
        if not self.oddballs or not freqs:
            return []
        lo = min(freqs)
        hi = max(freqs)
        return [freq for freq in self.oddballs if lo <= freq <= hi]

    def _selected_roi_names(self) -> List[str]:
        return list(self.roi_map.keys()) if self.selected_roi == ALL_ROIS_OPTION else [self.selected_roi]

    def _aggregate_roi_data(
        self,
        subject_data: Dict[str, Dict[str, List[float]]],
        subjects: Iterable[str] | None = None,
    ) -> Dict[str, List[float]]:
        started = time.perf_counter()
        try:
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
        finally:
            self._mark_timing("roi_aggregate", started)

    def _scalp_oddball_frequencies(self) -> List[float]:
        return list(self.oddballs)

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

    def _prepare_scalp_inputs(
        self, subject_maps: Dict[str, Dict[str, float]]
    ) -> ScalpInputs | None:
        if not self.include_scalp_maps:
            return None

        inputs = self._timed_call(
            "scalp_prepare",
            lambda: prepare_scalp_inputs(
                subject_maps,
                self.roi_map.get(self.selected_roi, []),
            ),
        )
        if inputs is None and subject_maps:
            self._emit("No scalp map data available for plotting.")
        return inputs

    def _plot_scalp_map(
            self,
            ax: plt.Axes,
            scalp_inputs: ScalpInputs,
            title: str,
            *,
            cax: plt.Axes | None = None,
    ) -> None:
        """Render a scalp topomap for the provided electrode data.

        Parameters
        ----------
        ax
            Target matplotlib Axes to render the topomap into.
        scalp_inputs
            Container holding the per-electrode data vector and an MNE Info object
            with BioSemi64 channel locations already set.
        title
            Title to display above the topomap.
        cax
            Optional explicit Axes to use for the colorbar. If not provided, a
            dedicated colorbar Axes is appended to the right of `ax` to keep
            map+colorbar centering stable across figures.
        """
        # Local import so this is copy/paste safe without touching module imports.
        from mpl_toolkits.axes_grid1 import make_axes_locatable

        vmin = self.scalp_vmin
        vmax = self.scalp_vmax

        if vmin is None or vmax is None:
            data = np.asarray(scalp_inputs.data, dtype=float)
            max_abs = float(np.nanmax(np.abs(data))) if data.size else 0.0
            if max_abs == 0:
                max_abs = 1.0
            vmin = -max_abs
            vmax = max_abs

        vlim = (float(vmin), float(vmax))
        norm: TwoSlopeNorm | None = None
        use_cnorm = vlim[0] < 0 < vlim[1]
        if use_cnorm:
            norm = TwoSlopeNorm(vmin=vlim[0], vcenter=0.0, vmax=vlim[1])

        im = None
        if use_cnorm and norm is not None:
            try:
                im, _ = mne.viz.plot_topomap(
                    scalp_inputs.data,
                    scalp_inputs.info,
                    axes=ax,
                    cmap=_SCALP_CMAP,
                    cnorm=norm,
                    contours=0,
                    sensors=True,
                    show=False,
                    outlines="head",
                )
            except TypeError:
                use_cnorm = False
                lim = max(abs(vlim[0]), abs(vlim[1]))
                vlim = (-lim, lim)

        if im is None:
            try:
                # MNE versions that use vlim (e.g., mne==1.9.x)
                im, _ = mne.viz.plot_topomap(
                    scalp_inputs.data,
                    scalp_inputs.info,
                    axes=ax,
                    cmap=_SCALP_CMAP,
                    vlim=vlim,
                    contours=0,
                    sensors=True,
                    show=False,
                    outlines="head",
                )
            except TypeError:
                try:
                    im, _ = mne.viz.plot_topomap(
                        scalp_inputs.data,
                        scalp_inputs.info,
                        axes=ax,
                        cmap=_SCALP_CMAP,
                        vmin=vlim[0],
                        vmax=vlim[1],
                        contours=0,
                        sensors=True,
                        show=False,
                        outlines="head",
                    )
                except TypeError:
                    lim = max(abs(vlim[0]), abs(vlim[1]))
                    im, _ = mne.viz.plot_topomap(
                        scalp_inputs.data,
                        scalp_inputs.info,
                        axes=ax,
                        cmap=_SCALP_CMAP,
                        vmin=-lim,
                        vmax=lim,
                        contours=0,
                        sensors=True,
                        show=False,
                        outlines="head",
                    )

        if cax is None:
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="4.5%", pad=0.08)

        cbar = plt.colorbar(im, cax=cax)
        cbar.ax.set_ylabel("uV")
        cbar.ax.yaxis.set_label_position("right")
        cbar.ax.yaxis.set_ticks_position("right")

        ax.set_title(title, fontsize=12, fontweight="bold", pad=8)
        ax.set_anchor("C")

    def _format_scalp_title(self, template: str, condition: str, roi: str) -> str:
        try:
            return template.format(condition=condition, roi=roi)
        except Exception:
            if not self._scalp_title_warned:
                self._emit(
                    "Invalid scalp title template detected. Reverting to default.",
                    0,
                    0,
                )
                self._scalp_title_warned = True
            return f"{condition} {roi} scalp map"

    def _run(self) -> None:
        if self.overlay and self.condition_b:
            files_a = self._list_excel_files(self.condition)
            files_b = self._list_excel_files(self.condition_b)
            total_a = len(files_a)
            total_b = len(files_b)
            total = total_a + total_b
            freqs_a, data_a, scalp_a = self._collect_data(
                self.condition,
                excel_files=files_a,
                offset=0,
                total_override=total,
            )
            freqs_b, data_b, scalp_b = self._collect_data(
                self.condition_b,
                excel_files=files_b,
                offset=total_a,
                total_override=total,
            )
            if freqs_a and data_a and freqs_b and data_b:
                avg_a = self._aggregate_roi_data(data_a)
                avg_b = self._aggregate_roi_data(data_b)
                if avg_a and avg_b:
                    scalp_inputs_a = self._prepare_scalp_inputs(scalp_a)
                    scalp_inputs_b = self._prepare_scalp_inputs(scalp_b)
                    self._plot_overlay(
                        freqs_a, avg_a, avg_b, scalp_inputs_a, scalp_inputs_b
                    )
            return

        freqs, subject_data, scalp_data = self._collect_data(self.condition)
        if freqs and subject_data:
            averaged = self._aggregate_roi_data(subject_data)
            if not averaged:
                self._emit("No ROI data to plot.")
                return
            group_curves = self._build_group_curves(subject_data)
            scalp_inputs = self._prepare_scalp_inputs(scalp_data)
            if group_curves or scalp_inputs is not None:
                self._plot(freqs, averaged, group_curves, scalp_inputs)
            else:
                self._plot(freqs, averaged)

    def _plot(
        self,
        freqs: List[float],
        roi_data: Dict[str, List[float]],
        group_curves: Dict[str, Dict[str, List[float]]] | None = None,
        scalp_inputs: ScalpInputs | None = None,
    ) -> None:
        odd_freqs = self._visible_oddball_frequencies(freqs)

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
            render_started = time.perf_counter()
            has_scalp = scalp_inputs is not None and self.include_scalp_maps
            if has_scalp:
                fig = plt.figure(figsize=(10, 7), constrained_layout=True)
                cbar_width = 0.03
                gs = fig.add_gridspec(
                    2,
                    3,
                    height_ratios=[3, 2],
                    width_ratios=[cbar_width, 1.0, cbar_width],
                )
                ax = fig.add_subplot(gs[0, :])
                spacer_ax = fig.add_subplot(gs[1, 0])
                spacer_ax.axis("off")
                scalp_axes = [(fig.add_subplot(gs[1, 1]), fig.add_subplot(gs[1, 2]))]
            else:
                fig, ax = plt.subplots(figsize=(10, 4))
                scalp_axes: list[tuple[plt.Axes, plt.Axes]] = []

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
                ax.plot(
                    freqs,
                    amps,
                    color=self.stem_color,
                    label=self._resolve_legend_label(self.legend_condition_a, self.condition),
                )
                self._emit(
                    f"Plotted {len(amps)} SNR values for ROI {roi}", 0, 0
                )

            if odd_freqs:
                freq_array = np.array(freqs)
                for idx, odd in enumerate(odd_freqs):
                    closest = int(np.abs(freq_array - odd).argmin())
                    label = (
                        self._resolve_legend_label(self.legend_a_peaks, _DEFAULT_A_PEAKS)
                        if idx == 0
                        else "_nolegend_"
                    )
                    ax.scatter(
                        freq_array[closest],
                        amps[closest],
                        marker="o",
                        facecolor=self.stem_color,
                        edgecolor="black",
                        zorder=4,
                        label=label,
                    )
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

            handles, _labels = ax.get_legend_handles_labels()
            if handles:
                ax.legend(loc="upper right", frameon=True)

            ax.set_xlabel(self.xlabel)
            ax.set_ylabel(self.ylabel)
            ax.grid(axis="y", linestyle=":", linewidth=0.8, color="gray")

            combined_title = f"{self.title}: {roi}"
            fig.suptitle(combined_title, fontsize=16, ha="center", va="top")

            if has_scalp and scalp_inputs:
                scalp_ax, cbar_ax = scalp_axes[0]
                self._plot_scalp_map(
                    scalp_ax,
                    scalp_inputs,
                    self._format_scalp_title(
                        self.scalp_title_a_template, self.condition, roi
                    ),
                    cax=cbar_ax,
                )

            if not has_scalp:
                fig.tight_layout(rect=[0, 0, 1, 0.93])
            fname = f"{self.condition}_{roi}_{self.metric}.png"
            save_kwargs = {"dpi": 300, "pad_inches": 0.05}
            if not has_scalp:
                save_kwargs["bbox_inches"] = "tight"
            out_path = self.out_dir / fname
            self._mark_timing("plot_render", render_started)
            save_started = time.perf_counter()
            try:
                fig.savefig(out_path, **save_kwargs)
                fig.savefig(out_path.with_suffix(".svg"), format="svg")
            finally:
                self._mark_timing("file_save", save_started)
                plt.close(fig)
            self._record_generated_path(out_path)
            self._emit(f"Saved {fname}")

    def _plot_overlay(
            self,
            freqs: List[float],
            data_a: Dict[str, List[float]],
            data_b: Dict[str, List[float]],
            scalp_a: ScalpInputs | None = None,
            scalp_b: ScalpInputs | None = None,
    ) -> None:
        plt.rcParams.update({"font.family": "Times New Roman", "font.size": 12})
        odd_freqs = self._visible_oddball_frequencies(freqs)

        for roi in data_a:
            if self._stop_requested:
                self._emit("Generation cancelled by user.")
                return
            render_started = time.perf_counter()

            has_scalp_a = bool(self.include_scalp_maps and scalp_a is not None)
            has_scalp_b = bool(self.include_scalp_maps and scalp_b is not None)
            has_scalp = has_scalp_a or has_scalp_b

            if has_scalp:
                # Outer layout: top SNR axis + bottom scalp row.
                fig = plt.figure(figsize=(10, 7))
                outer = fig.add_gridspec(
                    2,
                    1,
                    height_ratios=[3, 2],
                    hspace=0.35,
                )
                ax = fig.add_subplot(outer[0, 0])

                # Bottom row becomes 1x2 when both scalp maps exist, otherwise 1x1 (centered).
                scalp_items: list[tuple[str, ScalpInputs]] = []
                if has_scalp_a and scalp_a is not None:
                    scalp_items.append(
                        (
                            self._format_scalp_title(self.scalp_title_a_template, self.condition, roi),
                            scalp_a,
                        )
                    )
                if has_scalp_b and scalp_b is not None:
                    scalp_items.append(
                        (
                            self._format_scalp_title(
                                self.scalp_title_b_template,
                                self.condition_b or "",
                                roi,
                            ),
                            scalp_b,
                        )
                    )

                n_maps = len(scalp_items)
                bottom = outer[1, 0].subgridspec(
                    1,
                    n_maps,
                    wspace=0.25,
                )
                scalp_axes: list[tuple[plt.Axes, str, ScalpInputs]] = []
                for i, (label, inputs) in enumerate(scalp_items):
                    scalp_ax = fig.add_subplot(bottom[0, i])
                    scalp_axes.append((scalp_ax, label, inputs))
            else:
                fig, ax = plt.subplots(figsize=(10, 4))
                scalp_axes = []

            # --- SNR overlay curves ---
            ax.plot(
                freqs,
                data_a[roi],
                color=self.stem_color,
                label=self._resolve_legend_label(self.legend_condition_a, self.condition),
            )
            ax.plot(
                freqs,
                data_b.get(roi, []),
                color=self.stem_color_b,
                label=self._resolve_legend_label(
                    self.legend_condition_b, self.condition_b or ""
                ),
            )

            if odd_freqs:
                freq_array = np.array(freqs)
                for idx, odd in enumerate(odd_freqs):
                    closest = int(np.abs(freq_array - odd).argmin())
                    val_a = data_a[roi][closest]
                    val_b = data_b[roi][closest] if roi in data_b and data_b[roi] else None

                    label_a = (
                        self._resolve_legend_label(
                            self.legend_a_peaks, _DEFAULT_A_PEAKS
                        )
                        if idx == 0
                        else "_nolegend_"
                    )
                    ax.scatter(
                        freq_array[closest],
                        val_a,
                        marker="o",
                        facecolor=self.stem_color,
                        edgecolor="black",
                        zorder=4,
                        label=label_a,
                    )
                    if val_b is not None:
                        label_b = (
                            self._resolve_legend_label(
                                self.legend_b_peaks, _DEFAULT_B_PEAKS
                            )
                            if idx == 0
                            else "_nolegend_"
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

            handles, _labels = ax.get_legend_handles_labels()
            if handles:
                ax.legend(loc="upper right", frameon=True)

            ax.set_xlabel(self.xlabel)
            ax.set_ylabel(self.ylabel)
            base = self.title or f"{self.condition} vs {self.condition_b}"
            ax.grid(axis="y", linestyle=":", linewidth=0.8, color="gray")

            combined_title = f"{base}: {roi}"
            fig.suptitle(combined_title, fontsize=16, ha="center", va="top")

            # --- Scalp maps (bottom row) ---
            for scalp_ax, label, scalp_inputs in scalp_axes:
                self._plot_scalp_map(
                    scalp_ax,
                    scalp_inputs,
                    label,
                    cax=None,  # colorbar will be appended to the right of each scalp axis
                )

            # Layout:
            if not has_scalp:
                fig.tight_layout(rect=[0, 0, 1, 0.93])
            else:
                # Keep a little room for suptitle, avoid tight_layout warnings with MNE axes.
                fig.subplots_adjust(top=0.90)

            fname = f"{self.condition}_vs_{self.condition_b}_{roi}_{self.metric}.png"
            out_path = self.out_dir / fname
            self._mark_timing("plot_render", render_started)
            save_started = time.perf_counter()
            try:
                fig.savefig(
                    out_path,
                    dpi=300,
                    pad_inches=0.05,
                )
                fig.savefig(
                    out_path.with_suffix(".svg"),
                    format="svg",
                    pad_inches=0.05,
                )
            finally:
                self._mark_timing("file_save", save_started)
                plt.close(fig)
            self._record_generated_path(out_path)
            self._emit(f"Saved {fname}")
