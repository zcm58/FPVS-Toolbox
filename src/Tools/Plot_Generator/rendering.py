"""Line and overlay plot rendering helpers for Plot Generator workers."""

from __future__ import annotations

import math
import time
from typing import Dict, List

import matplotlib
import numpy as np

from Tools.Plot_Generator.scalp_utils import ScalpInputs

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 12,
        "lines.linewidth": 1.5,
        "xtick.major.size": 6,
        "ytick.major.size": 6,
    }
)

_DEFAULT_A_PEAKS = "A-Peaks"
_DEFAULT_B_PEAKS = "B-Peaks"


class PlotRenderingMixin:
    """Worker-state helpers for PNG/SVG line and overlay plot rendering."""

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
                    color = (
                        self.stem_color
                        if idx == 0
                        else self.stem_color_b
                        if idx == 1
                        else palette[idx % len(palette)]
                    )
                    label = (
                        self._resolve_legend_label(self.legend_condition_a, group_name)
                        if idx == 0
                        else self._resolve_legend_label(self.legend_condition_b, group_name)
                        if idx == 1
                        else group_name
                    )
                    ax.plot(
                        freqs,
                        vals,
                        label=label,
                        color=color,
                        linewidth=2.0,
                    )
                    plotted = True
                if not plotted:
                    self._emit(
                        "No group data available for overlay. Displaying overall average only.",
                        0,
                        0,
                    )
                    ax.plot(
                        freqs,
                        amps,
                        color=self.stem_color,
                        label=self._resolve_legend_label(self.legend_condition_a, self.condition),
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
                if use_group_overlay and group_curves:
                    for group_idx, group_name in enumerate(self.selected_groups or group_curves.keys()):
                        vals = group_curves.get(group_name, {}).get(roi)
                        if not vals:
                            continue
                        color = (
                            self.stem_color
                            if group_idx == 0
                            else self.stem_color_b
                            if group_idx == 1
                            else palette[group_idx % len(palette)]
                        )
                        marker = "o" if group_idx == 0 else "^" if group_idx == 1 else "s"
                        peak_label = (
                            self._resolve_legend_label(self.legend_a_peaks, _DEFAULT_A_PEAKS)
                            if group_idx == 0
                            else self._resolve_legend_label(self.legend_b_peaks, _DEFAULT_B_PEAKS)
                            if group_idx == 1
                            else "_nolegend_"
                        )
                        for odd_idx, odd in enumerate(odd_freqs):
                            closest = int(np.abs(freq_array - odd).argmin())
                            label = peak_label if odd_idx == 0 else "_nolegend_"
                            ax.scatter(
                                freq_array[closest],
                                vals[closest],
                                marker=marker,
                                facecolor=color,
                                edgecolor="black",
                                zorder=4,
                                label=label,
                            )
                else:
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
                group_marker_count = (
                    sum(
                        1
                        for group_name in (self.selected_groups or group_curves.keys())
                        if group_curves.get(group_name, {}).get(roi)
                    )
                    if use_group_overlay and group_curves
                    else 1
                )
                self._emit(
                    f"Marked {len(odd_freqs) * group_marker_count} oddball points on ROI {roi}",
                    0,
                    0,
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
                fig = plt.figure(figsize=(10, 7))
                outer = fig.add_gridspec(
                    2,
                    1,
                    height_ratios=[3, 2],
                    hspace=0.35,
                )
                ax = fig.add_subplot(outer[0, 0])

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

            for scalp_ax, label, scalp_inputs in scalp_axes:
                self._plot_scalp_map(
                    scalp_ax,
                    scalp_inputs,
                    label,
                    cax=None,
                )

            if not has_scalp:
                fig.tight_layout(rect=[0, 0, 1, 0.93])
            else:
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
