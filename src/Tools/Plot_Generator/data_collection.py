"""Excel discovery and data collection helpers for Plot Generator workers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

from Tools.Plot_Generator.excel_inputs import (
    _infer_subject_id_from_path,
)
from Tools.Plot_Generator.full_snr_reader import (
    _read_full_snr_sheet_read_only,
)

_EXCEL_WORKBOOK_SUFFIX = ".xlsx"
_IGNORED_EXCEL_PREFIXES = ("._", "~$")


def _is_excel_workbook_file(name: str) -> bool:
    """Return True when a filename is a user workbook, not metadata/temp output."""
    return (
        name.lower().endswith(_EXCEL_WORKBOOK_SUFFIX)
        and not name.startswith(_IGNORED_EXCEL_PREFIXES)
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
            if _is_excel_workbook_file(name)
        ]
        files.sort()
        return files

    def _read_full_snr_direct(
        self,
        excel_path: Path,
        *,
        included_electrodes_upper: set[str],
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
