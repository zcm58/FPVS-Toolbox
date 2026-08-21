"""Worker classes for the plot generator."""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Dict, List, Sequence

from Main_App import SettingsManager
from Main_App.processing.full_fft_provenance import FullFftProvenanceError
from Main_App.projects import ProjectDatasetIndex

from PySide6.QtCore import QObject, Signal

from Tools.Plot_Generator.aggregation import PlotAggregationMixin
from Tools.Plot_Generator.data_collection import PlotDataCollectionMixin
from Tools.Plot_Generator.excel_inputs import (
    _frequency_grids_match,
    _infer_subject_id_from_path,
)
from Tools.Plot_Generator.rendering import PlotRenderingMixin, matplotlib, plt
from Tools.Plot_Generator.output_interface import PlotOutputInterfaceMixin
from Tools.Plot_Generator.session_rendering import SessionPlotRenderingMixin
from Tools.Plot_Generator.session_workflow import SessionPlotWorkflowMixin
from Tools.Plot_Generator.worker_config import PlotWorkerConfig

logger = logging.getLogger(__name__)
_DEFAULT_ODDBALL_FREQ = 1.2
__all__ = [
    "_Worker",
    "_infer_subject_id_from_path",
    "matplotlib",
    "plt",
]


class _Worker(
    QObject,
    PlotDataCollectionMixin,
    PlotAggregationMixin,
    PlotRenderingMixin,
    SessionPlotWorkflowMixin,
    SessionPlotRenderingMixin,
    PlotOutputInterfaceMixin,
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
        legend_custom_enabled: bool = False,
        legend_condition_a: str | None = None,
        legend_condition_b: str | None = None,
        legend_a_peaks: str | None = None,
        legend_b_peaks: str | None = None,
        project_root: str | None = None,
        spectral_qc_enabled: bool = True,
        prepared_dataset_index: ProjectDatasetIndex | None = None,
        workbook_session_ids: Sequence[str] | None = None,
        session_comparison_ids: Sequence[str] | None = None,
        session_group_ids: Sequence[str] | None = None,
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
            legend_custom_enabled=legend_custom_enabled,
            legend_condition_a=legend_condition_a,
            legend_condition_b=legend_condition_b,
            legend_a_peaks=legend_a_peaks,
            legend_b_peaks=legend_b_peaks,
            project_root=project_root,
            spectral_qc_enabled=spectral_qc_enabled,
            prepared_dataset_index=prepared_dataset_index,
            workbook_session_ids=workbook_session_ids,
            session_comparison_ids=session_comparison_ids,
            session_group_ids=session_group_ids,
        )
        self.folder = self.config.folder
        self.condition = self.config.condition
        self.roi_map = self.config.roi_map
        self.selected_roi = self.config.selected_roi
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
        self._analysis_base_freq = self._read_analysis_float("base_freq", 6.0)
        self._analysis_oddball_freq = self._read_analysis_float(
            "oddball_freq", _DEFAULT_ODDBALL_FREQ
        )
        # Maintain explicit oddballs override for compatibility with older callers.
        self._explicit_oddballs = bool(self.config.oddballs)
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
        self._cancellation_reported = False
        self._completed_figure_saved = False
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
        self._unselected_group_files: set[str] = set()
        self.legend_custom_enabled = self.config.legend_custom_enabled
        self.legend_condition_a = self.config.legend_condition_a
        self.legend_condition_b = self.config.legend_condition_b
        self.legend_a_peaks = self.config.legend_a_peaks
        self.legend_b_peaks = self.config.legend_b_peaks
        self.project_root = self.config.project_root
        self.spectral_qc_enabled = self.config.spectral_qc_enabled
        self._prepared_dataset_index = self.config.prepared_dataset_index
        self.workbook_session_ids = tuple(self.config.workbook_session_ids or ())
        self.session_comparison_ids = tuple(self.config.session_comparison_ids or ())
        self.session_group_ids = tuple(self.config.session_group_ids or ())
        self._dataset_index_loaded = False
        self._workbook_records_by_path = {}
        self.generated_paths: list[str] = []
        self.spectral_qc_flags: list[dict[str, object]] = []
        self.failed_items: list[dict[str, str]] = []
        self.warning_items: list[dict[str, str]] = []
        self.group_roi_sample_sizes: dict[str, dict[str, int]] = {}
        self._timings: dict[str, float] = {
            "excel_load": 0.0,
            "roi_aggregate": 0.0,
            "plot_render": 0.0,
            "file_save": 0.0,
        }
        self._timing_details: dict[str, float] = {}
        self._post_processing_required_reason: str | None = None
        self._initialize_plot_output_interface()

    def run(self) -> None:
        try:
            if not self._cancellation_checkpoint():
                self._run()
        except FullFftProvenanceError as exc:
            if not self._cancellation_checkpoint():
                self._post_processing_required_reason = str(exc)
                self._record_failure(
                    item=self.condition,
                    error=f"Post-processing required: {exc}",
                )
                logger.warning(
                    "SNR plot generation requires refreshed post-processing.",
                    extra={
                        "operation": "snr_plot_post_processing_required",
                        "project_root": (
                            str(self._analysis_project_root)
                            if self._analysis_project_root is not None
                            else self.project_root
                        ),
                    },
                )
                self._emit(f"Post-processing is required before plotting: {exc}")
        except Exception as exc:
            if not self._cancellation_checkpoint():
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
                self._emit(f"SNR plot generation failed: {exc}", 0, 0)
        finally:
            self._emit_timing_summary()
            payload = {
                "condition": self.condition,
                "overlay": self.overlay,
                "generated_paths": list(self.generated_paths),
                "spectral_qc_flags": list(self.spectral_qc_flags),
                "failed_items": list(self.failed_items),
                "warning_items": list(self.warning_items),
                "cancelled": (
                    self._stop_requested and not self._completed_figure_saved
                ),
                "analysis_source_kind": self._analysis_source_kind,
                "analysis_project_root": (
                    str(self._analysis_project_root)
                    if self._analysis_project_root is not None
                    else None
                ),
                "post_processing_required_reason": (
                    self._post_processing_required_reason
                ),
            }
            if self._dataset_index_loaded:
                payload["_prepared_dataset_index"] = self._dataset_index
            self.finished.emit(payload)

    def stop(self) -> None:
        self._stop_requested = True

    def _cancellation_checkpoint(self) -> bool:
        """Return whether cancellation was requested and report it once."""

        if not self._stop_requested:
            return False
        if not self._cancellation_reported:
            self._emit("Generation cancelled by user.")
            self._cancellation_reported = True
        return True

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
        detail_parts = [
            f"{name.replace('_', ' ').replace('fullsnr', 'FullSNR')}={seconds:.2f}s"
            for name, seconds in self._timing_details.items()
            if seconds > 0
        ]
        if detail_parts:
            self._emit("Excel load details: " + ", ".join(detail_parts), 0, 0)
        logger.info(
            "SNR plot generation timing summary.",
            extra={
                "operation": "snr_plot_generate",
                "project_root": self.project_root,
                "condition": self.condition,
                "timings": {key: round(value, 4) for key, value in self._timings.items()},
                "timing_details": {
                    key: round(value, 4) for key, value in self._timing_details.items()
                },
                "timed_total_seconds": round(total, 4),
            },
        )

    def _record_generated_path(self, path: Path) -> None:
        self.generated_paths.append(str(path))

    def _record_spectral_qc_flags(self, flags: list[dict[str, object]]) -> None:
        self.spectral_qc_flags.extend(flags)

    def _record_failure(self, *, item: str, error: str) -> None:
        self.failed_items.append({"item": item, "error": error})

    def _record_warning(self, *, code: str, item: str, message: str) -> None:
        warning = {"code": code, "item": item, "message": message}
        if warning not in self.warning_items:
            self.warning_items.append(warning)

    def _read_analysis_float(self, option: str, fallback: float) -> float:
        try:
            mgr = getattr(self, "_settings_manager", None)
            if mgr is None:
                mgr = SettingsManager()
            raw = mgr.get("analysis", option, str(fallback))
            value = float(raw)
            if not math.isfinite(value):
                return fallback
            self._settings_manager = mgr
        except Exception:
            return fallback
        return value

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
        selected = [
            freq
            for freq in configured
            if math.isfinite(freq)
            and not self._is_base_harmonic(freq, self._analysis_base_freq)
        ]
        return sorted(
            {
                round(freq, 4)
                for freq in selected
                if math.isfinite(freq) and freq > 0
            }
        )

    def _is_base_harmonic(self, freq: float, base_freq: float) -> bool:
        if base_freq <= 0:
            return False
        ratio = freq / base_freq
        nearest = round(ratio)
        return (
            math.isclose(ratio, nearest, rel_tol=1e-3, abs_tol=1e-3)
            and nearest > 0
        )

    def _visible_oddball_frequencies(self, freqs: Sequence[float]) -> List[float]:
        if not self.oddballs or not freqs:
            return []
        lo = min(freqs)
        hi = max(freqs)
        return [freq for freq in self.oddballs if lo <= freq <= hi]

    def _run(self) -> None:
        if self._cancellation_checkpoint():
            return
        if self.session_comparison_ids:
            self._run_session_comparison()
            return
        group_mode_error = self._group_mode_configuration_error()
        if group_mode_error is not None:
            self._record_failure(item=self.condition, error=group_mode_error)
            self._emit(group_mode_error, 0, 0)
            return
        if self.overlay and self.condition_b:
            files_a = self._list_excel_files(self.condition)
            if self._cancellation_checkpoint():
                return
            files_b = self._list_excel_files(self.condition_b)
            if self._cancellation_checkpoint():
                return
            total_a = len(files_a)
            total_b = len(files_b)
            total = total_a + total_b
            freqs_a, data_a = self._collect_data(
                self.condition,
                excel_files=files_a,
                offset=0,
                total_override=total,
            )
            if self._cancellation_checkpoint():
                return
            freqs_b, data_b = self._collect_data(
                self.condition_b,
                excel_files=files_b,
                offset=total_a,
                total_override=total,
            )
            if self._cancellation_checkpoint():
                return
            if freqs_a and data_a and freqs_b and data_b:
                if not _frequency_grids_match(freqs_a, freqs_b):
                    comparison = f"{self.condition} vs {self.condition_b}"
                    self._record_failure(
                        item=comparison,
                        error="Condition overlay FullSNR frequency grid mismatch",
                    )
                    self._emit(
                        f"Cannot overlay {comparison}: the two conditions use "
                        "different FullSNR frequency grids. Reprocess both "
                        "conditions with the same frequency-grid settings.",
                        total,
                        total,
                    )
                    return
                avg_a = self._aggregate_roi_data(data_a)
                if self._cancellation_checkpoint():
                    return
                avg_b = self._aggregate_roi_data(data_b)
                if self._cancellation_checkpoint():
                    return
                avg_a, avg_b = self._matched_overlay_roi_data(avg_a, avg_b)
                if avg_a and avg_b:
                    self._revalidate_analysis_context_for_output()
                    self._prepare_overlay_source_curves(
                        frequencies_hz=freqs_a,
                        condition_a=self.condition,
                        subject_data_a=data_a,
                        plotted_data_a=avg_a,
                        condition_b=self.condition_b,
                        subject_data_b=data_b,
                        plotted_data_b=avg_b,
                    )
                    self._plot_overlay(freqs_a, avg_a, avg_b)
            return

        freqs, subject_data = self._collect_data(self.condition)
        if self._cancellation_checkpoint():
            return
        if self.enable_group_overlay and (not freqs or not subject_data):
            self._build_group_curves({})
            return
        if freqs and subject_data:
            averaged = self._aggregate_roi_data(subject_data)
            if self._cancellation_checkpoint():
                return
            if self.enable_group_overlay:
                group_curves = self._build_group_curves(subject_data)
                if not group_curves:
                    return
                if not averaged:
                    self._emit("No ROI data to plot.")
                    return
                self._revalidate_analysis_context_for_output()
                self._prepare_single_source_curves(
                    frequencies_hz=freqs,
                    condition=self.condition,
                    subject_data=subject_data,
                    plotted_roi_data=averaged,
                    group_curves=group_curves,
                )
                self._plot(freqs, averaged, group_curves)
            else:
                if not averaged:
                    self._emit("No ROI data to plot.")
                    return
                self._revalidate_analysis_context_for_output()
                self._prepare_single_source_curves(
                    frequencies_hz=freqs,
                    condition=self.condition,
                    subject_data=subject_data,
                    plotted_roi_data=averaged,
                )
                self._plot(freqs, averaged)
