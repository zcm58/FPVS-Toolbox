"""Public facade for Summed BCA DV policies in the Stats tool."""
from __future__ import annotations

import copy
import threading
from typing import Callable, Dict, List, Optional

from Tools.Stats.Legacy.stats_analysis import prepare_all_subject_summed_bca_data
from Tools.Stats.PySide6.analysis.dv_policy_fixed_k import _prepare_fixed_k_bca_data
from Tools.Stats.PySide6.analysis.dv_policy_fixed_shared import (
    _prepare_fixed_harmonics_by_roi_bca_data,
    compute_fixed_harmonic_dv_table,
)
from Tools.Stats.PySide6.analysis.dv_policy_rossion import (
    _prepare_rossion_bca_data,
    apply_empty_union_policy,
    build_rossion_preview_payload,
)
from Tools.Stats.PySide6.analysis.dv_policy_settings import (
    DVPolicySettings,
    EMPTY_LIST_ERROR,
    EMPTY_LIST_FALLBACK_FIXED_K,
    EMPTY_LIST_SET_ZERO,
    FIXED_K_POLICY_NAME,
    FIXED_SHARED_POLICY_NAME,
    GROUP_MEAN_Z_POLICY_NAME,
    LEGACY_POLICY_NAME,
    ROSSION_POLICY_NAME,
    _resolve_max_freq,
    normalize_dv_policy,
)

__all__ = [
    "DVPolicySettings",
    "LEGACY_POLICY_NAME",
    "FIXED_K_POLICY_NAME",
    "ROSSION_POLICY_NAME",
    "GROUP_MEAN_Z_POLICY_NAME",
    "FIXED_SHARED_POLICY_NAME",
    "EMPTY_LIST_FALLBACK_FIXED_K",
    "EMPTY_LIST_SET_ZERO",
    "EMPTY_LIST_ERROR",
    "normalize_dv_policy",
    "prepare_summed_bca_data",
    "compute_fixed_harmonic_dv_table",
    "apply_empty_union_policy",
    "build_rossion_preview_payload",
]

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
    max_freq: float | None,
) -> tuple:
    """Handle the build cache key step for the Stats PySide6 workflow."""
    return (
        tuple(subjects),
        tuple(conditions),
        _freeze_nested_mapping(subject_data),
        float(base_freq),
        _freeze_rois(rois),
        float(max_freq) if max_freq is not None else None,
        settings.name,
        settings.fixed_k,
        settings.exclude_harmonic1,
        settings.exclude_base_harmonics,
        float(settings.z_threshold),
        settings.empty_list_policy,
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
    max_freq: float | None = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """Handle the prepare summed bca data step for the Stats PySide6 workflow."""
    settings = normalize_dv_policy(dv_policy)
    resolved_max_freq = _resolve_max_freq(max_freq)
    meta_target: dict[str, object] | None = dv_metadata if dv_metadata is not None else {}
    if meta_target is not None and resolved_max_freq is not None:
        meta_target["max_frequency_hz"] = float(resolved_max_freq)
    cache_key = None
    if provenance_map is None:
        cache_key = _build_cache_key(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            rois=rois,
            settings=settings,
            max_freq=resolved_max_freq,
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
            max_freq=resolved_max_freq,
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
            max_freq=resolved_max_freq,
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
            max_freq=resolved_max_freq,
        )
    if cache_key is not None and data is not None:
        if meta_target is None:
            meta_target = {}
        with _DV_DATA_CACHE_LOCK:
            if len(_DV_DATA_CACHE) >= _DV_DATA_CACHE_MAX:
                _DV_DATA_CACHE.pop(next(iter(_DV_DATA_CACHE)))
            _DV_DATA_CACHE[cache_key] = (data, copy.deepcopy(meta_target))
    return data
