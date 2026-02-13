"""Summed BCA DV policies for the Stats tool."""
from __future__ import annotations

import copy
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

from Tools.Stats.Legacy.excel_io import safe_read_excel
from Tools.Stats.Legacy.stats_analysis import (
    SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
    SUMMED_BCA_STOP_AFTER_N_CONSEC_NONSIG_DEFAULT,
    _current_rois_map,
    _match_freq_column,
    filter_to_oddball_harmonics,
    get_included_freqs,
    prepare_all_subject_summed_bca_data,
)
from Tools.Stats.PySide6.group_harmonics import (
    build_rossion_harmonics_summary,
    select_rossion_harmonics_by_roi,
)

logger = logging.getLogger("Tools.Stats")
_DV_TRACE_ENV = "FPVS_STATS_DV_TRACE"

LEGACY_POLICY_NAME = "Current (Legacy)"
FIXED_K_POLICY_NAME = "Fixed-K harmonics"
ROSSION_POLICY_NAME = "Rossion Method (Significant-only; stop after 2 failures)"
GROUP_MEAN_Z_POLICY_NAME = ROSSION_POLICY_NAME
FIXED_SHARED_POLICY_NAME = "Fixed harmonics by ROI (Shared)"

EMPTY_LIST_FALLBACK_FIXED_K = "Fallback to Fixed-K"
EMPTY_LIST_SET_ZERO = "Set DV=0"
EMPTY_LIST_ERROR = "Error"

_DV_DATA_CACHE: dict[tuple, tuple[Dict[str, Dict[str, Dict[str, float]]], dict]] = {}
_DV_DATA_CACHE_LOCK = threading.Lock()
_DV_DATA_CACHE_MAX = 8


def _freeze_nested_mapping(mapping: Dict[str, Dict[str, str]]) -> tuple:
    """Handle the freeze nested mapping step for the Stats PySide6 workflow."""
    frozen = []
    for key, inner in sorted(mapping.items(), key=lambda item: item[0]):
        inner_items = tuple(sorted((inner or {}).items()))
        frozen.append((key, inner_items))
    return tuple(frozen)


def _freeze_rois(rois: Optional[Dict[str, List[str]]]) -> tuple:
    """Handle the freeze rois step for the Stats PySide6 workflow."""
    if not rois:
        return tuple()
    return tuple(
        (roi, tuple(sorted(channels)))
        for roi, channels in sorted(rois.items(), key=lambda item: item[0])
    )


def _build_cache_key(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    rois: Optional[Dict[str, List[str]]],
    settings: DVPolicySettings,
) -> tuple:
    """Handle the build cache key step for the Stats PySide6 workflow."""
    return (
        tuple(subjects),
        tuple(conditions),
        _freeze_nested_mapping(subject_data),
        float(base_freq),
        _freeze_rois(rois),
        settings.name,
        settings.fixed_k,
        settings.exclude_harmonic1,
        settings.exclude_base_harmonics,
        float(settings.z_threshold),
        settings.empty_list_policy,
    )


@dataclass(frozen=True)
class DVPolicySettings:
    """Represent the DVPolicySettings part of the Stats PySide6 tool."""
    name: str = LEGACY_POLICY_NAME
    fixed_k: int = 5
    exclude_harmonic1: bool = True
    exclude_base_harmonics: bool = True
    z_threshold: float = 1.64
    empty_list_policy: str = EMPTY_LIST_FALLBACK_FIXED_K

    def to_metadata(self, *, base_freq: float, selected_conditions: List[str]) -> dict:
        """Handle the to metadata step for the Stats PySide6 workflow."""
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
    """Handle the normalize dv policy step for the Stats PySide6 workflow."""
    if not settings:
        return DVPolicySettings()
    name = str(settings.get("name", LEGACY_POLICY_NAME))
    if name not in (
        LEGACY_POLICY_NAME,
        FIXED_K_POLICY_NAME,
        ROSSION_POLICY_NAME,
        FIXED_SHARED_POLICY_NAME,
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


def _dv_trace_enabled() -> bool:
    """Handle the dv trace enabled step for the Stats PySide6 workflow."""
    value = os.getenv(_DV_TRACE_ENV, "").strip().lower()
    return value not in ("", "0", "false", "no", "off")


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
    """Handle the prepare summed bca data step for the Stats PySide6 workflow."""
    settings = normalize_dv_policy(dv_policy)
    meta_target: dict[str, object] | None = dv_metadata if dv_metadata is not None else {}
    cache_key = None
    if provenance_map is None:
        cache_key = _build_cache_key(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            rois=rois,
            settings=settings,
        )
        with _DV_DATA_CACHE_LOCK:
            cached = _DV_DATA_CACHE.get(cache_key)
        if cached is not None:
            cached_data, cached_meta = cached
            if dv_metadata is not None:
                dv_metadata.update(copy.deepcopy(cached_meta))
            return cached_data
    harmonics_by_roi_policy = (dv_policy or {}).get("harmonics_by_roi", {}) if dv_policy else {}
    if settings.name == FIXED_SHARED_POLICY_NAME or harmonics_by_roi_policy:
        data = _prepare_fixed_harmonics_by_roi_bca_data(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            log_func=log_func,
            rois=rois,
            harmonics_by_roi=harmonics_by_roi_policy if isinstance(harmonics_by_roi_policy, dict) else {},
            provenance_map=provenance_map,
            dv_metadata=meta_target,
            settings=settings,
        )
    elif settings.name == ROSSION_POLICY_NAME:
        data = _prepare_rossion_bca_data(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            log_func=log_func,
            rois=rois,
            provenance_map=provenance_map,
            settings=settings,
            dv_metadata=meta_target,
        )
    elif settings.name == FIXED_K_POLICY_NAME:
        if meta_target is not None:
            meta_target.update(
                settings.to_metadata(
                    base_freq=base_freq, selected_conditions=conditions
                )
            )
        data = _prepare_fixed_k_bca_data(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            log_func=log_func,
            rois=rois,
            provenance_map=provenance_map,
            settings=settings,
        )
    else:
        if meta_target is not None:
            meta_target.update(
                settings.to_metadata(base_freq=base_freq, selected_conditions=conditions)
            )
        data = prepare_all_subject_summed_bca_data(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            log_func=log_func,
            rois=rois,
            provenance_map=provenance_map,
        )
    if cache_key is not None and data is not None:
        if meta_target is None:
            meta_target = {}
        with _DV_DATA_CACHE_LOCK:
            if len(_DV_DATA_CACHE) >= _DV_DATA_CACHE_MAX:
                _DV_DATA_CACHE.pop(next(iter(_DV_DATA_CACHE)))
            _DV_DATA_CACHE[cache_key] = (data, copy.deepcopy(meta_target))
    return data


def _parse_freqs_from_columns(
    all_col_names: Iterable[object],
    log_func: Callable[[str], None],
) -> List[float]:
    """Handle the parse freqs from columns step for the Stats PySide6 workflow."""
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
    """Handle the is base multiple step for the Stats PySide6 workflow."""
    return abs(freq_val / base_freq - round(freq_val / base_freq)) < tol


def _determine_fixed_k_freqs(
    *,
    columns: Sequence[object],
    base_freq: float,
    settings: DVPolicySettings,
    log_func: Callable[[str], None],
) -> List[float]:
    """Handle the determine fixed k freqs step for the Stats PySide6 workflow."""
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
    base_freq: float,
    log_func: Callable[[str], None],
) -> Optional[pd.Index]:
    """Handle the find first bca columns step for the Stats PySide6 workflow."""
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
    """Handle the aggregate bca sum harmonics step for the Stats PySide6 workflow."""
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
    """Handle the prepare fixed k bca data step for the Stats PySide6 workflow."""
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


def _normalize_harmonics_by_roi(
    harmonics_by_roi: dict[str, list[float]] | None,
    *,
    rois: dict[str, list[str]],
) -> dict[str, list[float]]:
    """Handle the normalize harmonics by roi step for the Stats PySide6 workflow."""
    normalized: dict[str, list[float]] = {}
    source = harmonics_by_roi or {}
    for roi_name in rois.keys():
        raw_freqs = source.get(str(roi_name), [])
        cleaned = sorted({float(freq) for freq in (raw_freqs or [])})
        normalized[str(roi_name)] = cleaned
    return normalized


def _aggregate_bca_sum_harmonics_fixed(
    *,
    file_path: str,
    participant_id: str,
    condition: str,
    roi_name: str,
    log_func: Callable[[str], None],
    harmonic_freqs: list[float],
    rois: dict[str, list[str]],
    diag_meta: Optional[dict[str, object]] = None,
) -> tuple[float, list[float]]:
    """Handle the aggregate bca sum harmonics fixed step for the Stats PySide6 workflow."""
    try:
        if diag_meta is not None:
            diag_meta.setdefault("source_file", file_path)
            diag_meta.setdefault("sheet", "BCA (uV)")
            diag_meta.setdefault("row_label", None)
            diag_meta.setdefault("col_label", None)
            diag_meta.setdefault("raw_cell", None)

        df_bca = safe_read_excel(file_path, sheet_name="BCA (uV)", index_col="Electrode")
        df_bca.index = df_bca.index.astype(str).str.upper().str.strip()

        roi_channels = [str(ch).strip().upper() for ch in rois.get(roi_name, [])]
        if not roi_channels:
            log_func(f"ROI {roi_name} not defined.")
            return np.nan, list(harmonic_freqs)

        roi_chans = [ch for ch in roi_channels if ch in df_bca.index]
        if not roi_chans:
            log_func(f"No overlapping BCA data for ROI {roi_name} in {file_path}.")
            return np.nan, list(harmonic_freqs)
        if diag_meta is not None:
            diag_meta["row_label"] = roi_chans

        df_bca_roi = df_bca.loc[roi_chans].dropna(how="all")
        if df_bca_roi.empty:
            log_func(f"No data for ROI {roi_name} in {file_path}.")
            return np.nan, list(harmonic_freqs)

        cols_to_sum: List[str] = []
        missing_hz: list[float] = []
        for freq_val in harmonic_freqs:
            col_bca = _match_freq_column(df_bca_roi.columns, freq_val)
            if col_bca:
                cols_to_sum.append(col_bca)
            else:
                missing_hz.append(float(freq_val))

        if missing_hz:
            warning_payload = {
                "subject": str(participant_id),
                "condition": str(condition),
                "roi": str(roi_name),
                "missing_hz": missing_hz,
                "file_path": str(file_path),
            }
            log_func(f"Fixed harmonic DV warning: {warning_payload}")
            return np.nan, missing_hz

        if not cols_to_sum:
            return np.nan, list(harmonic_freqs)

        if diag_meta is not None:
            diag_meta["col_label"] = cols_to_sum
            diag_meta["raw_cell"] = df_bca_roi[cols_to_sum].to_dict(orient="index")

        bca_block = (
            df_bca_roi[cols_to_sum]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )
        bca_vals = bca_block.sum(axis=1, min_count=1)
        bca_vals = pd.to_numeric(bca_vals, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if not bca_vals.notna().any():
            return np.nan, []

        out = float(bca_vals.mean(skipna=True))
        return (out if np.isfinite(out) else np.nan), []
    except Exception as exc:  # noqa: BLE001
        log_func(f"Error aggregating fixed-harmonic BCA for {file_path}, ROI {roi_name}: {exc}")
        return np.nan, list(harmonic_freqs)


def _prepare_fixed_harmonics_by_roi_bca_data(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    log_func: Callable[[str], None],
    rois: Optional[Dict[str, List[str]]] = None,
    harmonics_by_roi: Optional[dict[str, list[float]]] = None,
    provenance_map: Optional[dict[tuple[str, str, str], dict[str, object]]] = None,
    dv_metadata: Optional[dict[str, object]] = None,
    settings: Optional[DVPolicySettings] = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """Handle the prepare fixed harmonics by roi bca data step for the Stats PySide6 workflow."""
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    rois_map = rois if rois is not None else _current_rois_map()
    if not rois_map:
        log_func("No ROIs defined or available.")
        return None

    normalized_harmonics = _normalize_harmonics_by_roi(harmonics_by_roi, rois=rois_map)
    if not any(normalized_harmonics.values()):
        raise RuntimeError(
            "Fixed-harmonic DV policy requires harmonics_by_roi with at least one harmonic."
        )

    all_subject_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    missing_records: list[dict[str, object]] = []
    for pid in subjects:
        all_subject_data[pid] = {}
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            all_subject_data[pid].setdefault(cond_name, {})
            for roi_name in rois_map.keys():
                harmonics = normalized_harmonics.get(roi_name, [])
                sum_val = np.nan
                diag_meta: Optional[dict[str, object]] = None
                if provenance_map is not None:
                    diag_meta = {}
                missing_hz: list[float] = []
                if file_path and Path(file_path).exists():
                    sum_val, missing_hz = _aggregate_bca_sum_harmonics_fixed(
                        file_path=file_path,
                        participant_id=pid,
                        condition=cond_name,
                        roi_name=roi_name,
                        log_func=log_func,
                        harmonic_freqs=harmonics,
                        rois=rois_map,
                        diag_meta=diag_meta,
                    )
                else:
                    log_func(f"Missing file for {pid} {cond_name}: {file_path}")
                    missing_hz = list(harmonics)
                all_subject_data[pid][cond_name][roi_name] = sum_val
                if missing_hz:
                    missing_records.append(
                        {
                            "subject": str(pid),
                            "condition": str(cond_name),
                            "roi": str(roi_name),
                            "missing_hz": sorted(float(freq) for freq in missing_hz),
                            "file_path": str(file_path or ""),
                        }
                    )
                if provenance_map is not None:
                    provenance = {
                        "source_file": file_path,
                        "sheet": "BCA (uV)",
                        "row_label": None,
                        "col_label": None,
                        "raw_cell": None,
                        "missing_hz": sorted(float(freq) for freq in missing_hz),
                    }
                    if diag_meta:
                        provenance.update(diag_meta)
                    provenance_map[(pid, cond_name, roi_name)] = provenance

    if dv_metadata is not None:
        if settings is not None:
            dv_metadata.update(
                settings.to_metadata(
                    base_freq=float(base_freq),
                    selected_conditions=conditions,
                )
            )
        dv_metadata["harmonics_by_roi"] = normalized_harmonics
        dv_metadata["missing_harmonics"] = missing_records

    return all_subject_data


def compute_fixed_harmonic_dv_table(
    *,
    subjects: list[str],
    conditions: list[str],
    subject_data: dict[str, dict[str, str]],
    rois: dict[str, list[str]],
    harmonics_by_roi: dict[str, list[float]],
    log_func: Callable[[str], None],
) -> dict[str, object]:
    """Compute fixed-harmonic Summed BCA DV values without model execution."""

    metadata: dict[str, object] = {}
    nested = _prepare_fixed_harmonics_by_roi_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=0.0,
        log_func=log_func,
        rois=rois,
        harmonics_by_roi=harmonics_by_roi,
        dv_metadata=metadata,
        settings=DVPolicySettings(name=FIXED_SHARED_POLICY_NAME),
    )
    if nested is None:
        raise RuntimeError("Failed to compute fixed-harmonic DV table.")

    rows: list[dict[str, object]] = []
    for pid in subjects:
        for condition in conditions:
            roi_values = (nested.get(pid, {}) or {}).get(condition, {}) or {}
            for roi_name in rois.keys():
                rows.append(
                    {
                        "subject": str(pid),
                        "condition": str(condition),
                        "roi": str(roi_name),
                        "dv_value": roi_values.get(roi_name, np.nan),
                    }
                )

    dv_df = pd.DataFrame(rows, columns=["subject", "condition", "roi", "dv_value"])
    missing_records = metadata.get("missing_harmonics", [])
    return {
        "dv_df": dv_df,
        "nested": nested,
        "harmonics_by_roi": metadata.get("harmonics_by_roi", {}),
        "missing_harmonics": missing_records if isinstance(missing_records, list) else [],
    }


def apply_empty_union_policy(
    union_harmonics: dict[str, list[float]],
    *,
    policy: str,
    fallback_freqs: list[float],
) -> tuple[dict[str, list[float]], dict[str, dict[str, object]]]:
    """Handle the apply empty union policy step for the Stats PySide6 workflow."""
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


def build_rossion_preview_payload(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    rois: Dict[str, List[str]],
    log_func: Callable[[str], None],
    dv_policy: dict[str, object] | None = None,
) -> dict[str, object]:
    """Handle the build rossion preview payload step for the Stats PySide6 workflow."""
    settings = normalize_dv_policy(dv_policy)
    if settings.name != ROSSION_POLICY_NAME:
        raise RuntimeError("Rossion preview requires the Rossion policy.")

    summary = build_rossion_harmonics_summary(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois,
        z_threshold=settings.z_threshold,
        exclude_harmonic1=settings.exclude_harmonic1,
        log_func=log_func,
    )
    selected_map, stop_meta = select_rossion_harmonics_by_roi(
        summary,
        rois=rois.keys(),
        z_threshold=settings.z_threshold,
        stop_after_n=SUMMED_BCA_STOP_AFTER_N_CONSEC_NONSIG_DEFAULT,
    )
    fallback_freqs = _determine_fixed_k_freqs(
        columns=summary.columns,
        base_freq=base_freq,
        settings=settings,
        log_func=log_func,
    )
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
        "stop_metadata_by_roi": stop_meta,
        "mean_z_table": summary.mean_z_table,
        "harmonic_domain": summary.harmonic_freqs,
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
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """Handle the prepare rossion bca data step for the Stats PySide6 workflow."""
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    rois_map = rois if rois is not None else _current_rois_map()
    if not rois_map:
        log_func("No ROIs defined or available.")
        return None

    summary = build_rossion_harmonics_summary(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois_map,
        z_threshold=settings.z_threshold,
        exclude_harmonic1=settings.exclude_harmonic1,
        log_func=log_func,
    )
    selected_map, stop_meta = select_rossion_harmonics_by_roi(
        summary,
        rois=rois_map.keys(),
        z_threshold=settings.z_threshold,
        stop_after_n=SUMMED_BCA_STOP_AFTER_N_CONSEC_NONSIG_DEFAULT,
    )
    fallback_freqs = _determine_fixed_k_freqs(
        columns=summary.columns,
        base_freq=base_freq,
        settings=settings,
        log_func=log_func,
    )
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
            "union_harmonics_by_roi": final_map,
            "fallback_info_by_roi": fallback_info,
            "mean_z_table": summary.mean_z_table,
            "stop_metadata_by_roi": stop_meta,
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
