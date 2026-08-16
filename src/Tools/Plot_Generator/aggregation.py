"""ROI and group aggregation helpers for Plot Generator workers."""

from __future__ import annotations

import time
from typing import Dict, Iterable, List

import numpy as np

from Main_App.processing.roi_settings import ALL_ROIS_OPTION


def _nanmean_columns(rows: List[List[float]]) -> List[float]:
    try:
        values = np.asarray(rows, dtype=float)
    except ValueError:
        width = max(len(row) for row in rows)
        values = np.full((len(rows), width), np.nan, dtype=float)
        for idx, row in enumerate(rows):
            values[idx, : len(row)] = np.asarray(row, dtype=float)
    if values.ndim == 1:
        values = values.reshape(1, -1)
    valid = np.isfinite(values)
    counts = valid.sum(axis=0)
    sums = np.where(valid, values, 0.0).sum(axis=0)
    return np.divide(
        sums,
        counts,
        out=np.full(sums.shape, np.nan, dtype=float),
        where=counts > 0,
    ).tolist()


def _has_finite_value(values: Iterable[float]) -> bool:
    try:
        numeric = np.asarray(list(values), dtype=float)
    except (TypeError, ValueError):
        return False
    return bool(numeric.size and np.isfinite(numeric).any())


class PlotAggregationMixin:
    """Worker-state helpers for ROI averaging and group overlay curves."""

    def _group_mode_configuration_error(self) -> str | None:
        """Return a hard-stop message for an unsafe multi-group plot mode."""

        if not self.multi_group_mode:
            return None
        if self.overlay:
            return (
                "Canonical multi-group projects require one-condition "
                "group-overlay plots; condition A/B overlays are not supported."
            )
        if not self.enable_group_overlay or not self.selected_groups:
            return (
                "Canonical multi-group projects require group-overlay plotting "
                "with at least one selected project group."
            )
        return None

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
                    if values and _has_finite_value(values):
                        rows.append(values)
                if rows:
                    aggregated[roi] = _nanmean_columns(rows)
            return aggregated
        finally:
            self._mark_timing("roi_aggregate", started)

    def _matched_overlay_roi_data(
        self,
        data_a: Dict[str, List[float]],
        data_b: Dict[str, List[float]],
    ) -> tuple[Dict[str, List[float]], Dict[str, List[float]]]:
        """Return only ROIs with usable curves in both overlay conditions."""

        missing_pairs = [
            (roi, self.condition_b or "condition B")
            for roi in data_a
            if roi not in data_b
        ] + [
            (roi, self.condition)
            for roi in data_b
            if roi not in data_a
        ]
        for roi, missing_condition in missing_pairs:
            message = (
                f"Condition overlay omitted ROI '{roi}' because "
                f"'{missing_condition}' has no usable participant data."
            )
            self._emit(f"Warning: {message}", 0, 0)
            self._record_warning(
                code="overlay_roi_unavailable",
                item=f"{missing_condition}:{roi}",
                message=message,
            )
        shared = [roi for roi in data_a if roi in data_b]
        if not shared:
            comparison = f"{self.condition} vs {self.condition_b}"
            error = "No ROI has usable participant data in both conditions"
            self._record_failure(item=comparison, error=error)
            self._emit(f"Cannot overlay {comparison}: {error.lower()}.", 0, 0)
            return {}, {}
        return (
            {roi: data_a[roi] for roi in shared},
            {roi: data_b[roi] for roi in shared},
        )

    def _build_group_curves(
        self,
        subject_data: Dict[str, Dict[str, List[float]]],
    ) -> Dict[str, Dict[str, List[float]]]:
        if not self.enable_group_overlay or not self.subject_groups:
            self._unknown_subject_files.clear()
            self.group_roi_sample_sizes.clear()
            return {}

        # Group overlays reuse the already collected subject data so the worker
        # never re-reads Excel files or blocks the UI thread with redundant IO.
        per_group: Dict[str, Dict[str, List[float]]] = {}
        self.group_roi_sample_sizes.clear()
        roi_names = self._selected_roi_names()
        for group in self.selected_groups:
            subjects = {
                pid
                for pid, grp in self.subject_groups.items()
                if grp == group and pid in subject_data
            }
            roi_sample_sizes = {
                roi: sum(
                    _has_finite_value(
                        subject_data.get(pid, {}).get(roi, [])
                    )
                    for pid in subjects
                )
                for roi in roi_names
            }
            self.group_roi_sample_sizes[group] = roi_sample_sizes
            aggregated = (
                self._aggregate_roi_data(subject_data, subjects)
                if subjects
                else {}
            )
            if aggregated:
                per_group[group] = aggregated
            missing_rois = [
                roi for roi, sample_size in roi_sample_sizes.items()
                if sample_size == 0
            ]
            if missing_rois:
                roi_text = ", ".join(missing_rois)
                message = (
                    f"Selected group '{group}' has no usable participant SNR "
                    f"data for: {roi_text}. It will be omitted from those "
                    "group-overlay plots."
                )
                self._emit(f"Warning: {message}", 0, 0)
                self._record_warning(
                    code="selected_group_no_data",
                    item=group,
                    message=message,
                )

        for roi in roi_names:
            sample_sizes = [
                f"{group} n={self.group_roi_sample_sizes[group][roi]}"
                for group in self.selected_groups
                if self.group_roi_sample_sizes[group][roi] > 0
            ]
            if sample_sizes:
                self._emit(
                    f"Group sample sizes for ROI {roi}: "
                    + "; ".join(sample_sizes),
                    0,
                    0,
                )

        if not per_group:
            self._emit(
                "No selected group has usable participant SNR data. "
                "No group-overlay plot will be created.",
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
            message = (
                "The following Excel files lack canonical group assignments "
                f"and were excluded from group overlays: {files}"
            )
            self._emit(f"Warning: {message}", 0, 0)
            self._record_warning(
                code="unassigned_participant",
                item=files,
                message=message,
            )
            self._unknown_subject_files.clear()
        if self.enable_group_overlay and self._unselected_group_files:
            files = ", ".join(sorted(self._unselected_group_files))
            message = (
                "The following Excel files belong to groups that were not "
                f"selected and were excluded before workbook reads: {files}"
            )
            self._emit(f"Info: {message}", 0, 0)
            self._unselected_group_files.clear()
