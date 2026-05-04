"""Trace logging helpers for Stats DV policies."""
from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger("Tools.Stats")
_DV_TRACE_ENV = "FPVS_STATS_DV_TRACE"


def _dv_trace_enabled() -> bool:
    """Handle the dv trace enabled step for the Stats PySide6 workflow."""
    value = os.getenv(_DV_TRACE_ENV, "").strip().lower()
    return value not in ("", "0", "false", "no", "off")


def _log_dv_trace_empty_policy(
    *,
    initial_map: dict[str, list[float]],
    final_map: dict[str, list[float]],
    fallback_info: dict[str, dict[str, object]],
) -> None:
    """Handle the log dv trace empty policy step for the Stats PySide6 workflow."""
    if not _dv_trace_enabled():
        return
    for roi_name, initial_freqs in initial_map.items():
        final_freqs = final_map.get(roi_name, [])
        fallback_payload = fallback_info.get(roi_name, {})
        fallback_used = bool(fallback_payload.get("fallback_used", False))
        fallback_method = "Fixed-K" if fallback_used else "None"
        fallback_harmonics = fallback_payload.get("fallback_harmonics", []) or []
        contains_1p2hz = any(abs(float(freq) - 1.2) < 1e-6 for freq in fallback_harmonics)
        logger.info(
            "DV_TRACE empty_policy roi=%s initial_selected_count=%d after_policy_count=%d "
            "used_fallback=%s fallback_method=%s fallback_harmonics=%s contains_1p2hz=%s",
            roi_name,
            len(initial_freqs),
            len(final_freqs),
            fallback_used,
            fallback_method,
            fallback_harmonics,
            contains_1p2hz,
        )


def _log_dv_trace_dv_table_summary(
    *,
    subjects: list[str],
    conditions: list[str],
    rois_map: dict[str, list[str]],
    all_subject_data: dict[str, dict[str, dict[str, float]]],
) -> None:
    """Handle the log dv trace dv table summary step for the Stats PySide6 workflow."""
    if not _dv_trace_enabled():
        return
    expected_rows = len(subjects) * len(conditions) * len(rois_map)
    finite_values: list[float] = []
    cell_values: list[tuple[float, str, str, str]] = []
    valid_rows = 0
    for pid in subjects:
        for cond in conditions:
            roi_vals = (all_subject_data.get(pid, {}) or {}).get(cond, {}) or {}
            for roi_name in rois_map.keys():
                val = roi_vals.get(roi_name, np.nan)
                if val is not None and np.isfinite(val):
                    valid_rows += 1
                    float_val = float(val)
                    finite_values.append(float_val)
                    cell_values.append((float_val, str(pid), str(cond), str(roi_name)))
    nan_rows = expected_rows - valid_rows
    dv_min = float(np.nanmin(finite_values)) if finite_values else np.nan
    dv_mean = float(np.nanmean(finite_values)) if finite_values else np.nan
    dv_max = float(np.nanmax(finite_values)) if finite_values else np.nan
    dv_std = float(np.nanstd(finite_values)) if finite_values else np.nan
    logger.info(
        "DV_TRACE dv_table_summary expected_rows=%d valid_rows=%d nan_rows=%d "
        "min=%s mean=%s max=%s std=%s",
        expected_rows,
        valid_rows,
        nan_rows,
        dv_min,
        dv_mean,
        dv_max,
        dv_std,
    )
    if finite_values and dv_std <= 1e-9:
        logger.warning(
            "DV_TRACE dv_table_summary warning=degenerate_dv std=%s",
            dv_std,
        )
    for roi_name in rois_map.keys():
        roi_values = []
        for pid in subjects:
            for cond in conditions:
                val = (all_subject_data.get(pid, {}) or {}).get(cond, {}).get(roi_name, np.nan)
                if val is not None and np.isfinite(val):
                    roi_values.append(float(val))
        roi_min = float(np.nanmin(roi_values)) if roi_values else np.nan
        roi_mean = float(np.nanmean(roi_values)) if roi_values else np.nan
        roi_max = float(np.nanmax(roi_values)) if roi_values else np.nan
        roi_std = float(np.nanstd(roi_values)) if roi_values else np.nan
        logger.info(
            "DV_TRACE dv_by_roi roi=%s valid_rows=%d min=%s mean=%s max=%s std=%s",
            roi_name,
            len(roi_values),
            roi_min,
            roi_mean,
            roi_max,
            roi_std,
        )
    if cell_values:
        min_values = sorted(cell_values, key=lambda entry: entry[0])
        max_values = sorted(cell_values, key=lambda entry: entry[0], reverse=True)
        abs_values = sorted(cell_values, key=lambda entry: abs(entry[0]), reverse=True)
        for rank, (dv_value, pid, cond, roi_name) in enumerate(min_values[:3], start=1):
            logger.info(
                "DV_TRACE dv_extreme which=min rank=%d pid=%s condition=%s roi=%s dv=%s",
                rank,
                pid,
                cond,
                roi_name,
                dv_value,
            )
        for rank, (dv_value, pid, cond, roi_name) in enumerate(max_values[:3], start=1):
            logger.info(
                "DV_TRACE dv_extreme which=max rank=%d pid=%s condition=%s roi=%s dv=%s",
                rank,
                pid,
                cond,
                roi_name,
                dv_value,
            )
        for rank, (dv_value, pid, cond, roi_name) in enumerate(abs_values[:3], start=1):
            logger.info(
                "DV_TRACE dv_extreme which=abs rank=%d pid=%s condition=%s roi=%s dv=%s",
                rank,
                pid,
                cond,
                roi_name,
                dv_value,
            )
