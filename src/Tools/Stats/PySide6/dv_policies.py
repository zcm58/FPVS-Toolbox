"""Summed BCA DV policies for the Stats tool."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from Tools.Stats.Legacy.excel_io import safe_read_excel
from Tools.Stats.Legacy.stats_analysis import (
    SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
    _current_rois_map,
    _match_freq_column,
    filter_to_oddball_harmonics,
    get_included_freqs,
    prepare_all_subject_summed_bca_data,
)
from Tools.Stats.PySide6.group_harmonics import (
    GroupMeanZSummary,
    build_group_mean_z_summary,
    compute_union_harmonics_by_roi,
)

LEGACY_POLICY_NAME = "Current (Legacy)"
FIXED_K_POLICY_NAME = "Fixed-K harmonics"
GROUP_MEAN_Z_POLICY_NAME = (
    "Group Mean-Z (Union within ROI across selected conditions)"
)

EMPTY_LIST_FALLBACK_FIXED_K = "Fallback to Fixed-K"
EMPTY_LIST_SET_ZERO = "Set DV=0"
EMPTY_LIST_ERROR = "Error"


@dataclass(frozen=True)
class DVPolicySettings:
    name: str = LEGACY_POLICY_NAME
    fixed_k: int = 5
    exclude_harmonic1: bool = True
    exclude_base_harmonics: bool = True
    z_threshold: float = 1.64
    empty_list_policy: str = EMPTY_LIST_FALLBACK_FIXED_K

    def to_metadata(self, *, base_freq: float, selected_conditions: List[str]) -> dict:
        return {
            "policy_name": self.name,
            "fixed_k": int(self.fixed_k),
            "exclude_harmonic1": bool(self.exclude_harmonic1),
            "exclude_base_harmonics": bool(self.exclude_base_harmonics),
            "z_threshold": float(self.z_threshold),
            "empty_list_policy": str(self.empty_list_policy),
            "base_frequency_hz": float(base_freq),
            "selected_conditions": list(selected_conditions),
        }


def normalize_dv_policy(settings: dict[str, object] | None) -> DVPolicySettings:
    if not settings:
        return DVPolicySettings()
    name = str(settings.get("name", LEGACY_POLICY_NAME))
    if name not in (
        LEGACY_POLICY_NAME,
        FIXED_K_POLICY_NAME,
        GROUP_MEAN_Z_POLICY_NAME,
    ):
        name = LEGACY_POLICY_NAME
    fixed_k = int(settings.get("fixed_k", 5))
    if fixed_k < 1:
        fixed_k = 1
    empty_list_policy = str(
        settings.get("empty_list_policy", EMPTY_LIST_FALLBACK_FIXED_K)
    )
    if empty_list_policy not in (
        EMPTY_LIST_FALLBACK_FIXED_K,
        EMPTY_LIST_SET_ZERO,
        EMPTY_LIST_ERROR,
    ):
        empty_list_policy = EMPTY_LIST_FALLBACK_FIXED_K
    z_threshold = float(settings.get("z_threshold", 1.64))
    return DVPolicySettings(
        name=name,
        fixed_k=fixed_k,
        exclude_harmonic1=bool(settings.get("exclude_harmonic1", True)),
        exclude_base_harmonics=bool(settings.get("exclude_base_harmonics", True)),
        z_threshold=z_threshold,
        empty_list_policy=empty_list_policy,
    )


def prepare_summed_bca_data(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    log_func: Callable[[str], None],
    rois: Optional[Dict[str, List[str]]] = None,
    provenance_map: Optional[dict[tuple[str, str, str], dict[str, object]]] = None,
    dv_policy: dict[str, object] | None = None,
    dv_metadata: Optional[dict[str, object]] = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    settings = normalize_dv_policy(dv_policy)
    if settings.name == GROUP_MEAN_Z_POLICY_NAME:
        return _prepare_group_mean_z_union_bca_data(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            log_func=log_func,
            rois=rois,
            provenance_map=provenance_map,
            settings=settings,
            dv_metadata=dv_metadata,
        )
    if settings.name == FIXED_K_POLICY_NAME:
        if dv_metadata is not None:
            dv_metadata.update(
                settings.to_metadata(
                    base_freq=base_freq, selected_conditions=conditions
                )
            )
        return _prepare_fixed_k_bca_data(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            log_func=log_func,
            rois=rois,
            provenance_map=provenance_map,
            settings=settings,
        )
    if dv_metadata is not None:
        dv_metadata.update(settings.to_metadata(base_freq=base_freq, selected_conditions=conditions))
    return prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=log_func,
        rois=rois,
        provenance_map=provenance_map,
    )


def _parse_freqs_from_columns(
    all_col_names: Iterable[object],
    log_func: Callable[[str], None],
) -> List[float]:
    numeric_freqs: List[float] = []
    for col_name in all_col_names:
        if isinstance(col_name, str) and col_name.endswith("_Hz"):
            try:
                numeric_freqs.append(float(col_name[:-3]))
            except ValueError:
                log_func(f"Could not parse freq from col: {col_name}")
    if not numeric_freqs:
        return []
    return sorted(set(numeric_freqs))


def _is_base_multiple(freq_val: float, base_freq: float, tol: float = 1e-6) -> bool:
    return abs(freq_val / base_freq - round(freq_val / base_freq)) < tol


def _determine_fixed_k_freqs(
    *,
    columns: Sequence[object],
    base_freq: float,
    settings: DVPolicySettings,
    log_func: Callable[[str], None],
) -> List[float]:
    if settings.exclude_base_harmonics:
        freq_candidates = get_included_freqs(base_freq, columns, log_func)
    else:
        freq_candidates = _parse_freqs_from_columns(columns, log_func)
    if not freq_candidates:
        return []

    oddball_list = filter_to_oddball_harmonics(
        freq_candidates,
        base_freq,
        every_n=SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
        tol=1e-3,
    )
    if settings.exclude_base_harmonics:
        oddball_list = [
            item for item in oddball_list if not _is_base_multiple(item[0], base_freq)
        ]
    if settings.exclude_harmonic1:
        oddball_list = [item for item in oddball_list if item[1] != 1]

    if not oddball_list:
        return []
    return [freq for freq, _k in oddball_list[: settings.fixed_k]]


def _find_first_bca_columns(
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    log_func: Callable[[str], None],
) -> Optional[pd.Index]:
    for pid in subjects:
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            if not file_path:
                continue
            try:
                df_bca = safe_read_excel(
                    file_path, sheet_name="BCA (uV)", index_col="Electrode"
                )
                return df_bca.columns
            except Exception as exc:  # noqa: BLE001
                log_func(f"Failed to read BCA columns from {file_path}: {exc}")
    return None


def _aggregate_bca_sum_harmonics(
    file_path: str,
    roi_name: str,
    log_func: Callable[[str], None],
    harmonic_freqs: List[float],
    rois: Optional[Dict[str, List[str]]] = None,
    diag_meta: Optional[dict[str, object]] = None,
) -> float:
    try:
        if diag_meta is not None:
            diag_meta.setdefault("source_file", file_path)
            diag_meta.setdefault("sheet", "BCA (uV)")
            diag_meta.setdefault("row_label", None)
            diag_meta.setdefault("col_label", None)
            diag_meta.setdefault("raw_cell", None)

        df_bca = safe_read_excel(file_path, sheet_name="BCA (uV)", index_col="Electrode")
        df_bca.index = df_bca.index.astype(str).str.upper().str.strip()

        if rois is not None:
            roi_map = rois
        else:
            roi_map = _current_rois_map()

        roi_channels = [str(ch).strip().upper() for ch in roi_map.get(roi_name, [])]
        if not roi_channels:
            log_func(f"ROI {roi_name} not defined.")
            return np.nan

        roi_chans = [ch for ch in roi_channels if ch in df_bca.index]
        if not roi_chans:
            log_func(f"No overlapping BCA data for ROI {roi_name} in {file_path}.")
            return np.nan
        if diag_meta is not None:
            diag_meta["row_label"] = roi_chans

        df_bca_roi = df_bca.loc[roi_chans].dropna(how="all")
        if df_bca_roi.empty:
            log_func(f"No data for ROI {roi_name} in {file_path}.")
            return np.nan

        cols_to_sum: List[str] = []
        for freq_val in harmonic_freqs:
            col_bca = _match_freq_column(df_bca_roi.columns, freq_val)
            if col_bca:
                cols_to_sum.append(col_bca)

        if not cols_to_sum:
            log_func(f"No harmonics found for ROI {roi_name} in {file_path}.")
            if diag_meta is not None:
                diag_meta["col_label"] = []
            return np.nan

        if diag_meta is not None:
            diag_meta["col_label"] = cols_to_sum
            diag_meta["raw_cell"] = df_bca_roi[cols_to_sum].to_dict(orient="index")

        bca_block = (
            df_bca_roi[cols_to_sum]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )
        bca_vals = bca_block.sum(axis=1, min_count=1)

        bca_vals = pd.to_numeric(bca_vals, errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        if not bca_vals.notna().any():
            log_func(
                f"Warning: All-NaN BCA values after summation for ROI {roi_name} "
                f"({file_path})."
            )
            return np.nan

        out = float(bca_vals.mean(skipna=True))
        return out if np.isfinite(out) else np.nan

    except Exception as exc:  # noqa: BLE001
        log_func(f"Error aggregating fixed-k BCA for {file_path}, ROI {roi_name}: {exc}")
        return np.nan


def _prepare_fixed_k_bca_data(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    log_func: Callable[[str], None],
    rois: Optional[Dict[str, List[str]]] = None,
    provenance_map: Optional[dict[tuple[str, str, str], dict[str, object]]] = None,
    settings: DVPolicySettings,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    rois_map = rois if rois is not None else _current_rois_map()
    if not rois_map:
        log_func("No ROIs defined or available.")
        return None

    columns = _find_first_bca_columns(subjects, conditions, subject_data, log_func)
    if columns is None:
        log_func("Unable to read any BCA columns to build fixed-k harmonics.")
        return None

    harmonic_freqs = _determine_fixed_k_freqs(
        columns=columns, base_freq=base_freq, settings=settings, log_func=log_func
    )
    if not harmonic_freqs:
        raise RuntimeError(
            "Fixed-K harmonics selection produced an empty list. "
            "Adjust exclusions or verify the data files."
        )

    log_func(
        "Fixed-K harmonics selected: "
        + ", ".join(f"{freq:g} Hz" for freq in harmonic_freqs)
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
                if file_path and Path(file_path).exists():
                    sum_val = _aggregate_bca_sum_harmonics(
                        file_path,
                        roi_name,
                        log_func,
                        harmonic_freqs,
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

    total = 0
    finite = 0
    for pid, conds in all_subject_data.items():
        for _cond, rois_dict in conds.items():
            for _roi, val in rois_dict.items():
                total += 1
                if val is not None and np.isfinite(val):
                    finite += 1
    log_func(f"[DEBUG] Summed BCA finite cells: {finite}/{total}")
    log_func("Summed BCA data prep complete.")
    return all_subject_data


def apply_empty_union_policy(
    union_harmonics: dict[str, list[float]],
    *,
    policy: str,
    fallback_freqs: list[float],
) -> tuple[dict[str, list[float]], dict[str, dict[str, object]]]:
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


def build_group_mean_z_preview_payload(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    rois: Dict[str, List[str]],
    log_func: Callable[[str], None],
    dv_policy: dict[str, object] | None = None,
) -> dict[str, object]:
    settings = normalize_dv_policy(dv_policy)
    if settings.name != GROUP_MEAN_Z_POLICY_NAME:
        raise RuntimeError("Group Mean-Z preview requires the Group Mean-Z policy.")

    summary = build_group_mean_z_summary(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois,
        z_threshold=settings.z_threshold,
        log_func=log_func,
    )
    union_map = compute_union_harmonics_by_roi(
        summary.mean_z_table, conditions=conditions, z_threshold=settings.z_threshold
    )
    for roi_name in rois.keys():
        union_map.setdefault(roi_name, [])
    fallback_freqs = _determine_fixed_k_freqs(
        columns=summary.columns,
        base_freq=base_freq,
        settings=settings,
        log_func=log_func,
    )
    final_union_map, fallback_info = apply_empty_union_policy(
        union_map, policy=settings.empty_list_policy, fallback_freqs=fallback_freqs
    )

    if settings.empty_list_policy == EMPTY_LIST_ERROR:
        empty_rois = [roi for roi, freqs in union_map.items() if not freqs]
        if empty_rois:
            missing = ", ".join(sorted(empty_rois))
            raise RuntimeError(
                "Group Mean-Z union harmonics empty for ROI(s): "
                f"{missing}. Adjust threshold or policy."
            )

    return {
        "union_harmonics_by_roi": final_union_map,
        "fallback_info_by_roi": fallback_info,
        "mean_z_table": summary.mean_z_table,
        "harmonic_domain": summary.harmonic_freqs,
    }


def _prepare_group_mean_z_union_bca_data(
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
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    rois_map = rois if rois is not None else _current_rois_map()
    if not rois_map:
        log_func("No ROIs defined or available.")
        return None

    summary: GroupMeanZSummary = build_group_mean_z_summary(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois_map,
        z_threshold=settings.z_threshold,
        log_func=log_func,
    )
    union_map = compute_union_harmonics_by_roi(
        summary.mean_z_table, conditions=conditions, z_threshold=settings.z_threshold
    )
    for roi_name in rois_map.keys():
        union_map.setdefault(roi_name, [])

    fallback_freqs = _determine_fixed_k_freqs(
        columns=summary.columns,
        base_freq=base_freq,
        settings=settings,
        log_func=log_func,
    )

    final_union_map, fallback_info = apply_empty_union_policy(
        union_map, policy=settings.empty_list_policy, fallback_freqs=fallback_freqs
    )

    if settings.empty_list_policy == EMPTY_LIST_ERROR:
        empty_rois = [roi for roi, freqs in union_map.items() if not freqs]
        if empty_rois:
            missing = ", ".join(sorted(empty_rois))
            raise RuntimeError(
                "Group Mean-Z union harmonics empty for ROI(s): "
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
                harmonics = final_union_map.get(roi_name, [])
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
        dv_metadata["group_mean_z"] = {
            "z_threshold": float(settings.z_threshold),
            "empty_list_policy": settings.empty_list_policy,
            "harmonic_domain": list(summary.harmonic_freqs),
            "union_harmonics_by_roi": final_union_map,
            "fallback_info_by_roi": fallback_info,
            "mean_z_table": summary.mean_z_table,
        }

    total = 0
    finite = 0
    for pid, conds in all_subject_data.items():
        for _cond, rois_dict in conds.items():
            for _roi, val in rois_dict.items():
                total += 1
                if val is not None and np.isfinite(val):
                    finite += 1
    log_func(f"[DEBUG] Summed BCA finite cells: {finite}/{total}")
    log_func("Summed BCA data prep complete.")
    return all_subject_data
