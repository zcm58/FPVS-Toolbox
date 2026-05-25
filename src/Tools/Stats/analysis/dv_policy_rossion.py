"""Rossion DV policy helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from Tools.Stats.analysis.stats_analysis import (
    SUMMED_BCA_STOP_AFTER_N_CONSEC_NONSIG_DEFAULT,
    _current_rois_map,
)
from Tools.Stats.analysis.dv_policy_fixed_k import (
    _aggregate_bca_sum_harmonics,
    _determine_fixed_k_freqs,
)
from Tools.Stats.analysis.dv_policy_settings import (
    DVPolicySettings,
    EMPTY_LIST_ERROR,
    EMPTY_LIST_FALLBACK_FIXED_K,
    EMPTY_LIST_SET_ZERO,
    ROSSION_POLICY_NAME,
    _resolve_max_freq,
    normalize_dv_policy,
)
from Tools.Stats.analysis.dv_policy_trace import (
    _log_dv_trace_dv_table_summary,
    _log_dv_trace_empty_policy,
)
from Tools.Stats.analysis.group_harmonics import (
    build_common_rossion_harmonics_summary,
)


def apply_empty_union_policy(
    union_harmonics: dict[str, list[float]],
    *,
    policy: str,
    fallback_freqs: list[float],
) -> tuple[dict[str, list[float]], dict[str, dict[str, object]]]:
    """Handle the apply empty union policy step for the Stats workflow."""
    final_map: dict[str, list[float]] = {}
    info: dict[str, dict[str, object]] = {}
    for roi, freqs in union_harmonics.items():
        if freqs:
            final_map[roi] = list(freqs)
            info[roi] = {"policy": policy, "fallback_used": False}
            continue
        if policy == EMPTY_LIST_FALLBACK_FIXED_K:
            final_map[roi] = list(fallback_freqs)
            info[roi] = {
                "policy": policy,
                "fallback_used": True,
                "fallback_harmonics": list(fallback_freqs),
            }
        elif policy == EMPTY_LIST_SET_ZERO:
            final_map[roi] = []
            info[roi] = {"policy": policy, "fallback_used": False}
        elif policy == EMPTY_LIST_ERROR:
            final_map[roi] = []
            info[roi] = {"policy": policy, "fallback_used": False}
        else:
            final_map[roi] = list(freqs)
            info[roi] = {"policy": policy, "fallback_used": False}
    return final_map, info


def build_rossion_preview_payload(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    rois: Dict[str, List[str]],
    log_func: Callable[[str], None],
    dv_policy: dict[str, object] | None = None,
    max_freq: float | None = None,
    selection_conditions: List[str] | None = None,
) -> dict[str, object]:
    """Handle the build rossion preview payload step for the Stats workflow."""
    settings = normalize_dv_policy(dv_policy)
    resolved_max_freq = _resolve_max_freq(max_freq)
    if settings.name != ROSSION_POLICY_NAME:
        raise RuntimeError("Rossion preview requires the Rossion policy.")

    selection_conditions = list(selection_conditions or conditions)
    summary = build_common_rossion_harmonics_summary(
        subjects=subjects,
        conditions=selection_conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois,
        z_threshold=settings.z_threshold,
        exclude_harmonic1=settings.exclude_harmonic1,
        max_freq=resolved_max_freq,
        log_func=log_func,
        electrode_scope="all_scalp_electrodes",
        stop_after_n=SUMMED_BCA_STOP_AFTER_N_CONSEC_NONSIG_DEFAULT,
    )
    sensitivity = _build_union_roi_sensitivity(
        subjects=subjects,
        conditions=selection_conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois,
        settings=settings,
        max_freq=resolved_max_freq,
        log_func=log_func,
    )
    fallback_freqs = _determine_fixed_k_freqs(
        columns=summary.columns,
        base_freq=base_freq,
        settings=settings,
        log_func=log_func,
        max_freq=resolved_max_freq,
    )
    selected_map = {str(roi): list(summary.selected_harmonics) for roi in rois.keys()}
    final_map, fallback_info = apply_empty_union_policy(
        selected_map, policy=settings.empty_list_policy, fallback_freqs=fallback_freqs
    )
    _log_dv_trace_empty_policy(
        initial_map=selected_map,
        final_map=final_map,
        fallback_info=fallback_info,
    )

    if settings.empty_list_policy == EMPTY_LIST_ERROR:
        empty_rois = [roi for roi, freqs in selected_map.items() if not freqs]
        if empty_rois:
            missing = ", ".join(sorted(empty_rois))
            raise RuntimeError(
                "Rossion harmonic set empty for ROI(s): "
                f"{missing}. Adjust threshold or policy."
            )

    return {
        "union_harmonics_by_roi": final_map,
        "fallback_info_by_roi": fallback_info,
        "stop_metadata_by_roi": {
            str(roi): dict(summary.stop_metadata) for roi in rois.keys()
        },
        "mean_z_table": _common_mean_z_table(summary, rois.keys()),
        "harmonic_domain": summary.harmonic_freqs,
        "common_harmonics_hz": list(next(iter(final_map.values()), [])),
        "selection_scope": summary.selection_scope,
        "selection_z_by_harmonic": dict(summary.z_by_harmonic),
        "excluded_base_harmonics_hz": list(summary.excluded_base_harmonics),
        "sensitivity_union_roi_electrodes": sensitivity,
    }


def _common_mean_z_table(summary, rois) -> pd.DataFrame:
    rows = []
    for roi_name in rois:
        for freq_val in summary.harmonic_freqs:
            z_value = float(summary.z_by_harmonic.get(float(freq_val), np.nan))
            rows.append(
                {
                    "roi": str(roi_name),
                    "harmonic_hz": float(freq_val),
                    "mean_z": z_value,
                    "n_cells": int(summary.n_spectra),
                    "significant": bool(np.isfinite(z_value) and freq_val in summary.selected_harmonics),
                }
            )
    return pd.DataFrame(rows)


def _build_union_roi_sensitivity(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    rois: Dict[str, List[str]],
    settings: DVPolicySettings,
    max_freq: float | None,
    log_func: Callable[[str], None],
) -> dict[str, object]:
    try:
        summary = build_common_rossion_harmonics_summary(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            rois=rois,
            z_threshold=settings.z_threshold,
            exclude_harmonic1=settings.exclude_harmonic1,
            max_freq=max_freq,
            log_func=log_func,
            electrode_scope="union_roi_electrodes",
            stop_after_n=SUMMED_BCA_STOP_AFTER_N_CONSEC_NONSIG_DEFAULT,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "selection_scope": "union_roi_electrodes"}
    return {
        "selection_scope": summary.selection_scope,
        "harmonics_hz": list(summary.selected_harmonics),
        "selection_z_by_harmonic": dict(summary.z_by_harmonic),
        "excluded_base_harmonics_hz": list(summary.excluded_base_harmonics),
        "selection_electrode_count": int(summary.electrode_count),
        "selection_spectra_count": int(summary.n_spectra),
        "stop_metadata": dict(summary.stop_metadata),
    }


def _prepare_rossion_bca_data(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    log_func: Callable[[str], None],
    rois: Optional[Dict[str, List[str]]] = None,
    provenance_map: Optional[dict[tuple[str, str, str], dict[str, object]]] = None,
    settings: DVPolicySettings,
    dv_metadata: Optional[dict[str, object]] = None,
    max_freq: float | None = None,
    selection_conditions: List[str] | None = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """Handle the prepare rossion bca data step for the Stats workflow."""
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    rois_map = rois if rois is not None else _current_rois_map()
    if not rois_map:
        log_func("No ROIs defined or available.")
        return None

    selection_conditions = list(selection_conditions or conditions)
    summary = build_common_rossion_harmonics_summary(
        subjects=subjects,
        conditions=selection_conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois_map,
        z_threshold=settings.z_threshold,
        exclude_harmonic1=settings.exclude_harmonic1,
        max_freq=max_freq,
        log_func=log_func,
        electrode_scope="all_scalp_electrodes",
        stop_after_n=SUMMED_BCA_STOP_AFTER_N_CONSEC_NONSIG_DEFAULT,
    )
    sensitivity = _build_union_roi_sensitivity(
        subjects=subjects,
        conditions=selection_conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois_map,
        settings=settings,
        max_freq=max_freq,
        log_func=log_func,
    )
    fallback_freqs = _determine_fixed_k_freqs(
        columns=summary.columns,
        base_freq=base_freq,
        settings=settings,
        log_func=log_func,
        max_freq=max_freq,
    )
    selected_map = {str(roi): list(summary.selected_harmonics) for roi in rois_map.keys()}
    final_map, fallback_info = apply_empty_union_policy(
        selected_map, policy=settings.empty_list_policy, fallback_freqs=fallback_freqs
    )
    _log_dv_trace_empty_policy(
        initial_map=selected_map,
        final_map=final_map,
        fallback_info=fallback_info,
    )

    if settings.empty_list_policy == EMPTY_LIST_ERROR:
        empty_rois = [roi for roi, freqs in selected_map.items() if not freqs]
        if empty_rois:
            missing = ", ".join(sorted(empty_rois))
            raise RuntimeError(
                "Rossion harmonic set empty for ROI(s): "
                f"{missing}. Adjust threshold or policy."
            )

    all_subject_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    for pid in subjects:
        all_subject_data[pid] = {}
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            all_subject_data[pid].setdefault(cond_name, {})
            for roi_name in rois_map.keys():
                sum_val = np.nan
                diag_meta: Optional[dict[str, object]] = None
                if provenance_map is not None:
                    diag_meta = {}
                harmonics = final_map.get(roi_name, [])
                if not harmonics and settings.empty_list_policy == EMPTY_LIST_SET_ZERO:
                    sum_val = 0.0
                elif file_path and Path(file_path).exists():
                    sum_val = _aggregate_bca_sum_harmonics(
                        file_path,
                        roi_name,
                        log_func,
                        harmonics,
                        rois=rois_map,
                        diag_meta=diag_meta,
                    )
                else:
                    log_func(f"Missing file for {pid} {cond_name}: {file_path}")
                all_subject_data[pid][cond_name][roi_name] = sum_val
                if provenance_map is not None:
                    provenance = {
                        "source_file": file_path,
                        "sheet": "BCA (uV)",
                        "row_label": None,
                        "col_label": None,
                        "raw_cell": None,
                    }
                    if diag_meta:
                        provenance.update(diag_meta)
                    provenance_map[(pid, cond_name, roi_name)] = provenance

    if dv_metadata is not None:
        dv_metadata.update(
            settings.to_metadata(
                base_freq=base_freq,
                selected_conditions=conditions,
            )
        )
        dv_metadata["rossion_method"] = {
            "z_threshold": float(settings.z_threshold),
            "empty_list_policy": settings.empty_list_policy,
            "harmonic_domain": list(summary.harmonic_freqs),
            "common_harmonics_hz": list(next(iter(final_map.values()), [])),
            "union_harmonics_by_roi": final_map,
            "fallback_info_by_roi": fallback_info,
            "selection_scope": summary.selection_scope,
            "selection_conditions": list(selection_conditions),
            "selection_z_by_harmonic": dict(summary.z_by_harmonic),
            "excluded_base_harmonics_hz": list(summary.excluded_base_harmonics),
            "mean_z_table": _common_mean_z_table(summary, rois_map.keys()),
            "stop_metadata_by_roi": {
                str(roi): dict(summary.stop_metadata) for roi in rois_map.keys()
            },
            "selection_electrode_count": int(summary.electrode_count),
            "selection_spectra_count": int(summary.n_spectra),
            "sensitivity_union_roi_electrodes": sensitivity,
        }

    total = 0
    finite = 0
    for pid, conds in all_subject_data.items():
        for _cond, rois_dict in conds.items():
            for _roi, val in rois_dict.items():
                total += 1
                if val is not None and np.isfinite(val):
                    finite += 1
    _log_dv_trace_dv_table_summary(
        subjects=subjects,
        conditions=conditions,
        rois_map=rois_map,
        all_subject_data=all_subject_data,
    )
    log_func(f"[DEBUG] Summed BCA finite cells: {finite}/{total}")
    log_func("Summed BCA data prep complete.")
    return all_subject_data
