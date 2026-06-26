"""Excel discovery and data collection helpers for Plot Generator workers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List, Sequence
import zipfile
from xml.etree import ElementTree

import numpy as np
import pandas as pd

from Main_App.Shared.file_filters import is_excel_workbook_file
from Tools.Plot_Generator.excel_inputs import (
    _infer_subject_id_from_path,
)
from Tools.Plot_Generator.full_snr_reader import (
    _read_full_snr_sheet_read_only,
)
from Tools.Plot_Generator.spectral_qc import (
    SpectralQcThresholds,
    electrode_snr_data,
    flag_spectral_qc_electrode_outliers,
    interpolate_fullfft_electrode_data,
    read_full_fft_sheet_read_only,
    summarize_spectral_qc_records,
)
from Tools.Plot_Generator.spectral_qc_report import (
    resolve_quality_check_dir,
    write_spectral_qc_report,
)


class PlotDataCollectionMixin:
    """Worker-state helpers for Excel discovery and FullSNR data collection."""

    def _count_excel_files(self, condition: str) -> int:
        """Return the number of Excel files for a condition."""
        return len(self._list_excel_files(condition))

    def _list_excel_files(self, condition: str) -> list[Path]:
        """Return sorted Excel files under a condition folder (recursive)."""
        cond_folder = Path(self.folder) / condition
        if not cond_folder.is_dir():
            return []
        files = [
            Path(root) / name
            for root, _, names in os.walk(cond_folder)
            for name in names
            if is_excel_workbook_file(name)
        ]
        files.sort()
        return files

    def _read_full_snr_direct(
        self,
        excel_path: Path,
        *,
        included_electrodes_upper: set[str] | None,
    ) -> tuple[pd.DataFrame, List[float], List[str]]:
        return self._timed_call(
            "excel_load",
            lambda: _read_full_snr_sheet_read_only(
                excel_path,
                x_min=self.x_min,
                x_max=self.x_max,
                timing_details=self._timing_details,
                included_electrodes_upper=included_electrodes_upper,
            ),
        )

    def _read_full_fft_direct(
        self,
        excel_path: Path,
        *,
        included_electrodes_upper: set[str] | None,
    ) -> tuple[pd.DataFrame, List[float], List[str]]:
        return self._timed_call(
            "excel_load",
            lambda: read_full_fft_sheet_read_only(
                excel_path,
                x_min=self.x_min,
                x_max=self.x_max,
                timing_details=self._timing_details,
                included_electrodes_upper=included_electrodes_upper,
            ),
        )

    def _apply_spectral_qc_to_condition(
        self,
        condition: str,
        freqs: Sequence[float],
        subject_snr_data: dict[str, dict[str, list[float]]],
        subject_fft_data: dict[str, dict[str, list[float]]],
        source_workbooks: dict[str, str],
    ) -> None:
        if not self.spectral_qc_enabled or not subject_fft_data:
            return

        thresholds = SpectralQcThresholds()
        result = flag_spectral_qc_electrode_outliers(
            condition=condition,
            freqs=freqs,
            subject_snr_data=subject_snr_data,
            subject_fft_data=subject_fft_data,
            source_workbooks=source_workbooks,
            oddball_freq=self._analysis_oddball_freq,
            base_freq=self._analysis_base_freq,
            thresholds=thresholds,
        )
        quality_check_dir = resolve_quality_check_dir(
            project_root=self.project_root,
            input_folder=self.folder,
            out_dir=str(self.out_dir),
        )
        result = write_spectral_qc_report(
            result=result,
            condition=condition,
            quality_check_dir=quality_check_dir,
            thresholds=thresholds,
            oddball_freq=self._analysis_oddball_freq,
            base_freq=self._analysis_base_freq,
        )
        if result.report_path is not None:
            self._record_qc_report_path(result.report_path)
            self._record_spectral_qc_flags(summarize_spectral_qc_records(result.records))
            self._emit(
                f"Spectral QC report saved: {result.report_path} "
                f"({result.flagged_cells} electrode-frequency rows flagged).",
                0,
                0,
            )

    def _collect_data(
        self,
        condition: str,
        *,
        excel_files: Sequence[Path] | None = None,
        offset: int = 0,
        total_override: int | None = None,
    ) -> tuple[List[float], Dict[str, Dict[str, List[float]]]]:
        cond_folder = Path(self.folder) / condition
        if not cond_folder.is_dir():
            self._emit(f"Condition folder not found: {cond_folder}")
            return [], {}

        self.out_dir.mkdir(parents=True, exist_ok=True)

        files = list(excel_files) if excel_files is not None else self._list_excel_files(condition)
        if not files:
            self._emit("No Excel files found for condition.")
            return [], {}

        total_files = len(files)
        overall_total = total_override if total_override is not None else total_files
        processed_files = 0
        self._emit(
            f"Found {total_files} Excel files in {cond_folder}",
            offset + processed_files,
            overall_total,
        )

        roi_names = self._selected_roi_names()

        subject_roi_data: Dict[str, Dict[str, List[float]]] = {}
        subject_snr_data: dict[str, dict[str, list[float]]] = {}
        subject_fft_data: dict[str, dict[str, list[float]]] = {}
        source_workbooks: dict[str, str] = {}
        freqs: Iterable[float] | None = None
        self._unknown_subject_files.clear()
        roi_channels_upper = {
            roi: {ch.upper() for ch in self.roi_map.get(roi, [])}
            for roi in roi_names
        }
        roi_channel_arrays = {
            roi: np.asarray(sorted(chans), dtype=str)
            for roi, chans in roi_channels_upper.items()
        }
        included_electrodes_upper = {
            channel
            for channels in roi_channels_upper.values()
            for channel in channels
        }

        for excel_path in files:
            if self._stop_requested:
                self._emit("Generation cancelled by user.")
                return [], {}
            self._emit(
                f"Reading {excel_path.name}",
                offset + processed_files,
                overall_total,
            )
            try:
                df, ordered_freqs, ordered_cols = self._read_full_snr_direct(
                    excel_path,
                    included_electrodes_upper=included_electrodes_upper,
                )
            except Exception as exc:
                message = (
                    "FullSNR sheet is required for SNR plots and could not be "
                    f"read from {excel_path.name}: {exc}"
                )
                self._emit(message, offset + processed_files, overall_total)
                raise RuntimeError(message) from exc
            if not ordered_cols:
                self._emit(
                    f"No frequencies in x-range [{self.x_min}, {self.x_max}] for {excel_path.name}",
                    offset + processed_files,
                    overall_total,
                )
                self._record_failure(
                    item=excel_path.name,
                    error="No frequencies in selected x-range",
                )
                processed_files += 1
                continue
            self._emit(
                f"Using {len(ordered_cols)} frequency columns in {excel_path.name}",
                offset + processed_files,
                overall_total,
            )

            subject_id = _infer_subject_id_from_path(
                excel_path,
                self.subject_groups.keys() if self.subject_groups else None,
            )
            if not subject_id:
                self._emit(
                    f"Skipping {excel_path.name}: unable to determine subject ID.",
                    offset + processed_files,
                    overall_total,
                )
                self._record_failure(item=excel_path.name, error="Unable to determine subject ID")
                processed_files += 1
                continue
            if (
                self.enable_group_overlay
                and self.multi_group_mode
                and self.subject_groups
                and subject_id not in self.subject_groups
            ):
                self._unknown_subject_files.add(excel_path.name)

            if freqs is None:
                freqs = ordered_freqs

            electrode_upper = df["Electrode"].astype(str).str.upper().to_numpy()
            snr_values = df[ordered_cols].to_numpy(dtype=float, copy=False)
            for roi in roi_names:
                chans = roi_channels_upper.get(roi, set())
                if not chans:
                    self._emit(f"No electrode definition for ROI {roi}")
                    self._record_failure(
                        item=f"{excel_path.name}:{roi}",
                        error="No electrodes configured for ROI",
                    )
                    continue
                roi_mask = np.isin(electrode_upper, roi_channel_arrays[roi])
                if not roi_mask.any():
                    self._emit(f"No electrodes for ROI {roi} in {excel_path.name}")
                    self._record_failure(
                        item=f"{excel_path.name}:{roi}",
                        error="No electrodes for ROI",
                    )
                    continue

                roi_values = snr_values[roi_mask]
                valid = ~np.isnan(roi_values)
                counts = valid.sum(axis=0)
                sums = np.nansum(roi_values, axis=0)
                means = np.divide(
                    sums,
                    counts,
                    out=np.full(sums.shape, np.nan, dtype=float),
                    where=counts > 0,
                ).tolist()
                subject_roi_data.setdefault(subject_id, {})[roi] = means

            if self.spectral_qc_enabled:
                try:
                    full_snr_df, full_snr_freqs, full_snr_cols = self._read_full_snr_direct(
                        excel_path,
                        included_electrodes_upper=None,
                    )
                    full_fft_df, full_fft_freqs, full_fft_cols = self._read_full_fft_direct(
                        excel_path,
                        included_electrodes_upper=None,
                    )
                except (
                    OSError,
                    KeyError,
                    ValueError,
                    zipfile.BadZipFile,
                    ElementTree.ParseError,
                ):
                    full_snr_df = pd.DataFrame()
                    full_snr_freqs = []
                    full_snr_cols = []
                    full_fft_df = pd.DataFrame()
                    full_fft_freqs = []
                    full_fft_cols = []
                if full_snr_cols and full_fft_cols and full_snr_freqs == ordered_freqs:
                    snr_by_electrode = electrode_snr_data(full_snr_df, full_snr_cols)
                    fft_by_electrode = interpolate_fullfft_electrode_data(
                        full_fft_df,
                        full_fft_freqs,
                        full_fft_cols,
                        ordered_freqs,
                    )
                    if snr_by_electrode and fft_by_electrode:
                        subject_snr_data[subject_id] = snr_by_electrode
                        subject_fft_data[subject_id] = fft_by_electrode
                        source_workbooks[subject_id] = str(excel_path)

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

        freq_list = list(freqs)
        self._apply_spectral_qc_to_condition(
            condition,
            freq_list,
            subject_snr_data,
            subject_fft_data,
            source_workbooks,
        )
        return freq_list, subject_roi_data
