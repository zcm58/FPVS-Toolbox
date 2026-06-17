"""Excel discovery and data collection helpers for Plot Generator workers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

from Tools.Plot_Generator.excel_inputs import (
    _frequency_pairs_from_columns,
    _infer_subject_id_from_path,
    _select_frequency_pairs,
)
from Tools.Plot_Generator.scalp_utils import summarize_subject_scalp
from Tools.Plot_Generator.snr_utils import calc_snr_matlab

_FULLSNR_SHEET = "FullSNR"
_MISSING_FULLSNR_MESSAGE = "Worksheet named 'FullSNR' not found"


def _full_snr_usecols(x_min: float, x_max: float):
    tolerance = 1e-3

    def include_column(column: object) -> bool:
        if column == "Electrode":
            return True
        if not isinstance(column, str) or not column.endswith("_Hz"):
            return False
        try:
            freq = float(column.split("_")[0])
        except ValueError:
            return False
        return (x_min - tolerance) <= freq <= (x_max + tolerance)

    return include_column


def _is_missing_full_snr_sheet(exc: ValueError) -> bool:
    return _MISSING_FULLSNR_MESSAGE in str(exc)


class PlotDataCollectionMixin:
    """Worker-state helpers for Excel discovery, reading, and SNR fallback."""

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
            if name.lower().endswith(".xlsx")
        ]
        files.sort()
        return files

    def _read_full_snr_direct(
        self,
        excel_path: Path,
    ) -> tuple[pd.DataFrame, List[float], List[str]]:
        df = self._read_excel_timed(
            excel_path,
            sheet_name=_FULLSNR_SHEET,
            usecols=_full_snr_usecols(self.x_min, self.x_max),
        )
        freq_pairs = _frequency_pairs_from_columns(df.columns)
        ordered_freqs, ordered_cols = _select_frequency_pairs(
            freq_pairs,
            x_min=self.x_min,
            x_max=self.x_max,
        )
        return df, ordered_freqs, ordered_cols

    def _read_full_snr_from_workbook(self, xls) -> tuple[pd.DataFrame, List[float], List[str]]:
        header = self._read_excel_timed(xls, sheet_name=_FULLSNR_SHEET, nrows=0)
        freq_pairs = _frequency_pairs_from_columns(header.columns)
        ordered_freqs, ordered_cols = _select_frequency_pairs(
            freq_pairs,
            x_min=self.x_min,
            x_max=self.x_max,
        )
        if ordered_cols:
            df = self._read_excel_timed(
                xls,
                sheet_name=_FULLSNR_SHEET,
                usecols=["Electrode"] + ordered_cols,
            )
        else:
            df = pd.DataFrame()
        return df, ordered_freqs, ordered_cols

    def _read_fft_amplitude_from_workbook(self, xls) -> tuple[pd.DataFrame, List[float], List[str]]:
        df_amp = self._read_excel_timed(xls, sheet_name="FFT Amplitude (uV)")
        freq_pairs = _frequency_pairs_from_columns(df_amp.columns)
        freq_cols_tmp = [col for _, col in freq_pairs]
        snr_vals = df_amp[freq_cols_tmp].apply(
            calc_snr_matlab,
            axis=1,
            result_type="expand",
        )
        snr_vals.columns = freq_cols_tmp
        snr_vals.insert(0, "Electrode", df_amp["Electrode"])
        ordered_freqs, ordered_cols = _select_frequency_pairs(
            freq_pairs,
            x_min=self.x_min,
            x_max=self.x_max,
        )
        if ordered_cols:
            snr_vals = snr_vals[["Electrode"] + ordered_cols]
        return snr_vals, ordered_freqs, ordered_cols

    def _collect_data(
        self,
        condition: str,
        *,
        excel_files: Sequence[Path] | None = None,
        offset: int = 0,
        total_override: int | None = None,
    ) -> tuple[List[float], Dict[str, Dict[str, List[float]]], Dict[str, Dict[str, float]]]:
        cond_folder = Path(self.folder) / condition
        if not cond_folder.is_dir():
            self._emit(f"Condition folder not found: {cond_folder}")
            return [], {}, {}

        self.out_dir.mkdir(parents=True, exist_ok=True)

        files = list(excel_files) if excel_files is not None else self._list_excel_files(condition)
        if not files:
            self._emit("No Excel files found for condition.")
            return [], {}, {}

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
        subject_scalp_data: Dict[str, Dict[str, float]] = {}
        collect_scalp = self.include_scalp_maps
        scalp_oddballs = self._scalp_oddball_frequencies() if collect_scalp else []
        warned_missing_bca = False
        warned_missing_z = False
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

        for excel_path in files:
            if self._stop_requested:
                self._emit("Generation cancelled by user.")
                return [], {}, {}
            self._emit(
                f"Reading {excel_path.name}",
                offset + processed_files,
                overall_total,
            )
            scalp_map: Dict[str, float] | None = None
            try:
                if not collect_scalp:
                    try:
                        df, ordered_freqs, ordered_cols = self._read_full_snr_direct(excel_path)
                    except ValueError as exc:
                        if not _is_missing_full_snr_sheet(exc):
                            raise
                        with self._timed_call("excel_load", lambda: pd.ExcelFile(excel_path)) as xls:
                            df, ordered_freqs, ordered_cols = self._read_fft_amplitude_from_workbook(xls)
                else:
                    with self._timed_call("excel_load", lambda: pd.ExcelFile(excel_path)) as xls:
                        sheet_names = set(xls.sheet_names)
                        if _FULLSNR_SHEET in sheet_names:
                            df, ordered_freqs, ordered_cols = self._read_full_snr_from_workbook(xls)
                        else:
                            df, ordered_freqs, ordered_cols = self._read_fft_amplitude_from_workbook(xls)

                        has_bca = "BCA (uV)" in sheet_names
                        has_z = "Z Score" in sheet_names
                        if not has_bca and not warned_missing_bca:
                            self._emit(
                                "BCA (uV) sheet missing; scalp maps skipped.",
                                offset + processed_files,
                                overall_total,
                            )
                            warned_missing_bca = True
                        if not has_z and not warned_missing_z:
                            self._emit(
                                "Z Score sheet missing; scalp maps skipped.",
                                offset + processed_files,
                                overall_total,
                            )
                            warned_missing_z = True
                        if has_bca and has_z:
                            try:
                                df_bca = self._read_excel_timed(xls, sheet_name="BCA (uV)")
                                df_z = self._read_excel_timed(xls, sheet_name="Z Score")
                                scalp_map = self._timed_call(
                                    "scalp_prepare",
                                    lambda: summarize_subject_scalp(
                                        df_bca,
                                        df_z,
                                        scalp_oddballs,
                                    ),
                                )
                            except Exception as exc:  # pragma: no cover - logged to UI
                                self._emit(f"Failed reading scalp data in {excel_path.name}: {exc}")
                                self._record_failure(
                                    item=excel_path.name,
                                    error=f"Failed reading scalp data: {exc}",
                                )
            except Exception as exc:  # pragma: no cover - simple logging
                self._emit(f"Failed reading {excel_path.name}: {exc}")
                self._record_failure(item=excel_path.name, error=f"Failed reading Excel: {exc}")
                continue
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

            if scalp_map is not None:
                subject_scalp_data[subject_id] = scalp_map

            processed_files += 1
            self._emit("", offset + processed_files, overall_total)

        if not freqs:
            self._emit(
                "No frequency data found.",
                offset + processed_files,
                overall_total,
            )
            return [], {}, {}

        if not subject_roi_data:
            self._emit("No ROI data to plot.")
            return [], {}, {}

        return list(freqs), subject_roi_data, subject_scalp_data
