"""Public facade for Summed BCA DV policies in the Stats tool."""
from __future__ import annotations

import copy
import threading
from typing import Callable, Dict, List, Optional

from Tools.Stats.analysis.dv_policy_fixed_predefined import _prepare_fixed_predefined_bca_data
from Tools.Stats.analysis.dv_policy_settings import (
    DVPolicySettings,
    FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
    FIXED_PREDEFINED_POLICY_NAME,
    _resolve_max_freq,
    normalize_dv_policy,
)

__all__ = [
    "DVPolicySettings",
    "FIXED_PREDEFINED_POLICY_NAME",
    "FIXED_PREDEFINED_DEFAULT_FREQUENCIES",
    "normalize_dv_policy",
    "prepare_summed_bca_data",
]

_DV_DATA_CACHE: dict[tuple, tuple[Dict[str, Dict[str, Dict[str, float]]], dict]] = {}
_DV_DATA_CACHE_LOCK = threading.Lock()
_DV_DATA_CACHE_MAX = 8


def _freeze_nested_mapping(mapping: Dict[str, Dict[str, str]]) -> tuple:
    """Handle the freeze nested mapping step for the Stats workflow."""
    frozen = []
    for key, inner in sorted(mapping.items(), key=lambda item: item[0]):
        inner_items = tuple(sorted((inner or {}).items()))
        frozen.append((key, inner_items))
    return tuple(frozen)


def _freeze_rois(rois: Optional[Dict[str, List[str]]]) -> tuple:
    """Handle the freeze rois step for the Stats workflow."""
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
    selection_conditions: Optional[List[str]],
) -> tuple:
    """Handle the build cache key step for the Stats workflow."""
    return (
        tuple(subjects),
        tuple(conditions),
        tuple(selection_conditions or conditions),
        _freeze_nested_mapping(subject_data),
        float(base_freq),
        _freeze_rois(rois),
        float(max_freq) if max_freq is not None else None,
        settings.name,
        settings.fixed_harmonic_frequencies_hz,
        settings.fixed_harmonic_auto_exclude_base,
        float(settings.fixed_harmonic_base_tolerance_hz),
        float(settings.fixed_harmonic_matching_tolerance_hz),
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
    selection_conditions: Optional[List[str]] = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """Handle the prepare summed bca data step for the Stats workflow."""
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
            selection_conditions=selection_conditions,
        )
        with _DV_DATA_CACHE_LOCK:
            cached = _DV_DATA_CACHE.get(cache_key)
        if cached is not None:
            cached_data, cached_meta = cached
            if dv_metadata is not None:
                dv_metadata.update(copy.deepcopy(cached_meta))
            return cached_data
    data = _prepare_fixed_predefined_bca_data(
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
    if cache_key is not None and data is not None:
        if meta_target is None:
            meta_target = {}
        with _DV_DATA_CACHE_LOCK:
            if len(_DV_DATA_CACHE) >= _DV_DATA_CACHE_MAX:
                _DV_DATA_CACHE.pop(next(iter(_DV_DATA_CACHE)))
            _DV_DATA_CACHE[cache_key] = (data, copy.deepcopy(meta_target))
    return data
