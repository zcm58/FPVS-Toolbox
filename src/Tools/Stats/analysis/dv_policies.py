"""Public facade for Summed BCA DV policies in the Stats tool."""
from __future__ import annotations

import copy
import json
import math
import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from Tools.Stats.analysis.dv_policy_fixed_predefined import _prepare_fixed_predefined_bca_data
from Tools.Stats.analysis.dv_policy_group_significant import _prepare_group_significant_bca_data
from Tools.Stats.analysis.dv_policy_settings import (
    DVPolicySettings,
    FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
    FIXED_PREDEFINED_POLICY_NAME,
    GROUP_SIGNIFICANT_POLICY_NAME,
    HARMONIC_SELECTION_PROFILES,
    NEW_PROJECT_HARMONIC_PROFILE_ID,
    LOCKED_ODDBALL_FREQUENCY_HZ,
    _resolve_max_freq,
    dv_policy_payload_from_selection_metadata,
    new_project_dv_policy_settings,
    normalize_dv_policy,
)
from Tools.Stats.data.group_harmonic_cache import project_processing_signature_hash
from Main_App.processing.post_processing_context import post_processing_validation_scope
from Tools.Stats.analysis.canonical_harmonics import (
    CANONICAL_HARMONIC_SOURCE,
    CUSTOM_HARMONIC_SOURCE,
    SharedHarmonicSelection,
    load_project_processing_harmonics,
)

__all__ = [
    "DVPolicySettings",
    "FIXED_PREDEFINED_POLICY_NAME",
    "FIXED_PREDEFINED_DEFAULT_FREQUENCIES",
    "GROUP_SIGNIFICANT_POLICY_NAME",
    "LOCKED_ODDBALL_FREQUENCY_HZ",
    "HARMONIC_SELECTION_PROFILES",
    "NEW_PROJECT_HARMONIC_PROFILE_ID",
    "CANONICAL_HARMONIC_SOURCE",
    "CUSTOM_HARMONIC_SOURCE",
    "SharedHarmonicSelection",
    "normalize_dv_policy",
    "dv_policy_payload_from_selection_metadata",
    "new_project_dv_policy_settings",
    "prepare_summed_bca_data",
    "load_project_processing_harmonics",
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
    project_processing_hash: str | None,
    canonical_selection_fingerprint: str | None,
    source_workbook_identities: tuple,
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
        settings.harmonic_selection_profile,
        settings.harmonic_selection_profile_version,
        settings.fixed_harmonic_frequencies_hz,
        settings.fixed_harmonic_input_mode,
        settings.fixed_harmonic_upper_harmonic_index,
        settings.fixed_harmonic_upper_frequency_hz,
        settings.fixed_harmonic_auto_exclude_base,
        float(settings.fixed_harmonic_base_tolerance_hz),
        float(settings.fixed_harmonic_matching_tolerance_hz),
        float(settings.group_significant_z_threshold),
        settings.group_significant_electrode_scope,
        tuple(settings.group_significant_selection_electrodes),
        settings.group_significant_summation_method,
        float(settings.group_significant_oddball_frequency_hz),
        project_processing_hash,
        canonical_selection_fingerprint,
        source_workbook_identities,
    )


def _source_workbook_identities(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
) -> tuple:
    """Freeze current source identity so in-process DV cache cannot outlive files."""

    from Main_App.io.condition_data import condition_companion_identity
    from Main_App.io.spectral_data import spectral_companion_identity

    identities: list[tuple[object, ...]] = []
    for subject in subjects:
        for condition in conditions:
            raw_path = (subject_data.get(subject, {}) or {}).get(condition)
            if not raw_path:
                identities.append((str(subject), str(condition), "", None, None))
                continue
            path = Path(raw_path).resolve(strict=False)
            try:
                stat = path.stat()
            except OSError:
                size_bytes = None
                mtime_ns = None
            else:
                size_bytes = int(stat.st_size)
                mtime_ns = int(stat.st_mtime_ns)
            companion = (
                spectral_companion_identity(path) if size_bytes is not None else None
            )
            condition_companion = (
                condition_companion_identity(path) if size_bytes is not None else None
            )
            identities.append(
                (
                    str(subject),
                    str(condition),
                    str(path),
                    size_bytes,
                    mtime_ns,
                    *(
                        (json.dumps(companion, sort_keys=True, separators=(",", ":")),)
                        if companion is not None
                        else ()
                    ),
                    *(
                        (json.dumps(condition_companion, sort_keys=True, separators=(",", ":")),)
                        if condition_companion is not None
                        else ()
                    ),
                )
            )
    return tuple(sorted(identities))


@post_processing_validation_scope()
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
    project_root: str | None = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """Handle the prepare summed bca data step for the Stats workflow."""
    settings = normalize_dv_policy(dv_policy)
    resolved_max_freq = _resolve_max_freq(max_freq)
    if project_root not in (None, ""):
        from Main_App.processing.frequency_domain_qc import (
            filter_frequency_domain_subjects,
        )

        subjects, subject_data, excluded = filter_frequency_domain_subjects(
            project_root,
            subjects,
            subject_data,
        )
        if excluded:
            log_func(
                "Frequency-domain participant exclusions applied: "
                + ", ".join(excluded)
            )
    canonical_selection_fingerprint: str | None = None
    if project_root not in (None, ""):
        canonical = load_project_processing_harmonics(
            project_root=project_root,
            log_func=log_func,
        )
        canonical_base_frequency_hz = _required_canonical_rate(
            canonical.metadata,
            "base_frequency_hz",
        )
        canonical_oddball_frequency_hz = _required_canonical_rate(
            canonical.metadata,
            "oddball_frequency_hz",
        )
        if not math.isclose(
            float(base_freq),
            canonical_base_frequency_hz,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise RuntimeError(
                "The Stats base frequency does not match the accepted project "
                "harmonic selection. Reload the project before analysis."
            )
        base_freq = canonical_base_frequency_hz
        settings = normalize_dv_policy(
            dv_policy_payload_from_selection_metadata(canonical.metadata)
        )
        if not math.isclose(
            settings.group_significant_oddball_frequency_hz,
            canonical_oddball_frequency_hz,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            raise RuntimeError(
                "The accepted harmonic selection has inconsistent oddball-rate "
                "metadata. Use Settings > Recalculate Harmonics."
            )
        # The processing-owned selection already contains the exact canonical
        # list. A caller-supplied or historical upper bound is provenance only.
        resolved_max_freq = None
        canonical_selection_fingerprint = str(
            canonical.metadata.get("selection_fingerprint") or ""
        )
        if not canonical_selection_fingerprint:
            raise RuntimeError(
                "The accepted processing-time harmonic selection has no canonical "
                "selection fingerprint. Use Settings > Recalculate Harmonics."
            )
    meta_target: dict[str, object] | None = dv_metadata if dv_metadata is not None else {}
    if meta_target is not None and resolved_max_freq is not None:
        meta_target["max_frequency_hz"] = float(resolved_max_freq)
    cache_key = None
    if provenance_map is None:
        processing_hash = project_processing_signature_hash(project_root)
        workbook_identities = _source_workbook_identities(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
        )
        cache_key = _build_cache_key(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            rois=rois,
            settings=settings,
            max_freq=resolved_max_freq,
            selection_conditions=selection_conditions,
            project_processing_hash=processing_hash,
            canonical_selection_fingerprint=canonical_selection_fingerprint,
            source_workbook_identities=workbook_identities,
        )
        with _DV_DATA_CACHE_LOCK:
            cached = _DV_DATA_CACHE.get(cache_key)
        if cached is not None:
            cached_data, cached_meta = cached
            if dv_metadata is not None:
                dv_metadata.update(copy.deepcopy(cached_meta))
            return cached_data
    if settings.name == GROUP_SIGNIFICANT_POLICY_NAME:
        data = _prepare_group_significant_bca_data(
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
            project_root=project_root,
        )
    else:
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
            project_root=project_root,
            use_accepted_processing_selection=project_root not in (None, ""),
        )
    if cache_key is not None and data is not None:
        if meta_target is None:
            meta_target = {}
        with _DV_DATA_CACHE_LOCK:
            if len(_DV_DATA_CACHE) >= _DV_DATA_CACHE_MAX:
                _DV_DATA_CACHE.pop(next(iter(_DV_DATA_CACHE)))
            _DV_DATA_CACHE[cache_key] = (data, copy.deepcopy(meta_target))
    return data


def _required_canonical_rate(
    metadata: dict[str, object],
    field_name: str,
) -> float:
    try:
        value = float(metadata[field_name])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "The accepted processing-time harmonic selection lacks current "
            f"{field_name} metadata. Use Settings > Recalculate Harmonics."
        ) from exc
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError(
            "The accepted processing-time harmonic selection has invalid "
            f"{field_name} metadata. Use Settings > Recalculate Harmonics."
        )
    return value
