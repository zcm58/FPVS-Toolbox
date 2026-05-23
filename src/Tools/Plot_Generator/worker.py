"""Worker classes for the plot generator."""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Dict, List, Sequence

import pandas as pd
from Main_App import SettingsManager

from PySide6.QtCore import QObject, Signal

from Tools.Plot_Generator.aggregation import PlotAggregationMixin
from Tools.Plot_Generator.data_collection import PlotDataCollectionMixin
from Tools.Plot_Generator.excel_inputs import (
    _frequency_pairs_from_columns,
    _infer_subject_id_from_path,
    _select_frequency_pairs,
)
from Tools.Plot_Generator.scalp_utils import select_oddball_harmonics
from Tools.Plot_Generator.scalp_rendering import PlotScalpRenderingMixin
from Tools.Plot_Generator.rendering import PlotRenderingMixin, matplotlib, plt
from Tools.Plot_Generator.worker_config import PlotWorkerConfig

logger = logging.getLogger(__name__)
_DEFAULT_ODDBALL_FREQ = 1.2
__all__ = [
    "_Worker",
    "_frequency_pairs_from_columns",
    "_infer_subject_id_from_path",
    "_select_frequency_pairs",
    "matplotlib",
    "plt",
]


class _Worker(
    QObject,
    PlotDataCollectionMixin,
    PlotAggregationMixin,
    PlotScalpRenderingMixin,
    PlotRenderingMixin,
):
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

