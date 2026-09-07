"""Group-level significant-harmonic Summed BCA DV policy helpers."""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from Main_App.processing.roi_settings import build_roi_definition_snapshot
from Main_App.processing.spectral_eligibility import (
    QC14_NOISE_CANDIDATE_OFFSETS,
    SPECTRAL_ELIGIBILITY_METHOD_VERSION,
)
from Tools.Stats.analysis.dv_policy_settings import (
    DVPolicySettings,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN,
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
    HARMONIC_PROFILE_LEGACY_ID,
    GROUP_SIGNIFICANT_POLICY_ID,
    GROUP_SIGNIFICANT_POLICY_LABEL,
    GROUP_SIGNIFICANT_POLICY_NAME,
    GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY,
    GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
    GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES,
    LOCKED_ODDBALL_FREQUENCY_HZ,
)
from Tools.Stats.analysis.harmonic_pooling import (
    BalancedHarmonicPool,
    HarmonicPoolingCell,
    normalize_group_structure,
    pool_group_condition_spectra,
    pool_group_session_condition_spectra,
)
from Tools.Stats.analysis.stats_analysis import _current_rois_map
from Tools.Stats.data.group_harmonic_cache import (
    GROUP_HARMONIC_METHOD_VERSION,
    REPEATED_SESSION_POOLING_METHOD_VERSION,
    GroupHarmonicCacheRequest,
    build_group_harmonic_cache_request,
    lookup_cached_group_harmonic_selection,
    save_cached_group_harmonic_selection,
)
from Tools.Stats.io.xlsx_selected_reader import (
    MissingXlsxColumnsError,
    read_xlsx_sheet_header,
    read_xlsx_sheet_selected_columns,
)

logger = logging.getLogger("Tools.Stats")

FULL_FFT_AMPLITUDE_SHEET_NAME = "FullFFT Amplitude (uV)"
GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ = 0.01
GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ = 0.01
GROUP_SIGNIFICANT_NOISE_WINDOW_BINS = 10
GROUP_SIGNIFICANT_FULLFFT_PROGRESS_INTERVAL = 5
GROUP_SIGNIFICANT_BCA_PROGRESS_INTERVAL = 10
GROUP_SIGNIFICANT_SELECTION_CACHE_MAX_ENTRIES = 8
GROUP_SIGNIFICANT_FREQUENCY_DECIMALS = 10
GROUP_SIGNIFICANT_MAX_INTERVENING_NONBASE_HARMONICS = 10
GROUP_SIGNIFICANT_SUMMATION_GAP_GUARD_RULE = (
    "exclude_isolated_highest_when_more_than_10_intervening_nonbase_harmonics_v1"
)
_GROUP_SELECTION_CACHE_LOCK = threading.Lock()
_GROUP_SELECTION_CACHE: dict[
    "GroupSignificantSelectionCacheKey",
    "GroupSignificantHarmonicSelection",
] = {}


@dataclass(frozen=True)
class GroupSignificantHarmonicRow:
    harmonic_index: int
    target_frequency_hz: float
    matched_frequency_hz: float | None
    matched_column: str | None
    matched_bin_index: int | None
    z_score: float | None
    selected: bool
    excluded_base_rate: bool
    exclusion_reason: str
    warning: str
    evaluated: bool = True
    target_amplitude_uv: float | None = None
    noise_mean_uv: float | None = None
    noise_std_uv: float | None = None
    noise_bin_indices: tuple[int, ...] = ()
    noise_frequencies_hz: tuple[float, ...] = ()
    noise_amplitudes_uv: tuple[float, ...] = ()
    noise_used_bin_indices: tuple[int, ...] = ()
    noise_used_frequencies_hz: tuple[float, ...] = ()
    noise_used_amplitudes_uv: tuple[float, ...] = ()
    included_in_summation: bool = False
    condition_z_scores: tuple[tuple[str, float | None], ...] = ()


@dataclass(frozen=True)
class GroupSignificantNoiseStats:
    mean_uv: float
    std_uv: float
    candidate_bin_indices: tuple[int, ...]
    used_bin_indices: tuple[int, ...]


@dataclass(frozen=True)
class _SummationGapGuardDecision:
    enabled: bool
    applied: bool
    intervening_nonbase_harmonic_count: int
    lower_significant_harmonic_hz: float | None
    highest_significant_harmonic_hz: float | None
    retained_cutoff_harmonic_index: int | None


@dataclass(frozen=True)
class _TwoConsecutiveFailureDecision:
    cutoff_harmonic_index: int | None
    evaluated_harmonic_indices: tuple[int, ...]
    stopping_harmonics_hz: tuple[float, ...]
    stopping_reason: str


@dataclass(frozen=True)
class GroupSignificantHarmonicSelection:
    harmonic_domain_hz: list[float]
    selected_harmonics_hz: list[float]
    selected_columns: list[str]
    selected_bin_indices: list[int]
    detected_significant_harmonics_hz: list[float]
    detected_significant_columns: list[str]
    detected_significant_bin_indices: list[int]
    z_by_harmonic: dict[float, float]
    excluded_base_harmonics_hz: list[float]
    oddball_frequency_hz: float
    base_frequency_hz: float
    z_threshold: float
    electrode_scope: str
    summation_method: str
    selection_scope: str
    selection_conditions: list[str]
    selection_subjects: list[str]
    selection_spectra_count: int
    selection_electrode_count: int
    frequency_resolution_hz: float | None
    base_overlap_tolerance_hz: float
    matching_tolerance_hz: float
    noise_window_bins: int
    rows: list[GroupSignificantHarmonicRow]
    method_profile_id: str = HARMONIC_PROFILE_LEGACY_ID
    method_profile_version: str = "1.0"
    method_profile_label: str = "Legacy FPVS Toolbox"
    method_citation: str = "FPVS Toolbox legacy behavior retained for reproducibility"
    same_sample_adaptive: bool = True
    pooling_method: str = "equal_available_workbook_amplitude_mean"
    pooling_cells: tuple[HarmonicPoolingCell, ...] = ()
    declared_group_ids: tuple[str, ...] = ()
    condition_z_by_harmonic: dict[str, dict[float, float | None]] = field(
        default_factory=dict
    )
    selection_electrode_mask: tuple[str, ...] = ()
    stopping_rule: str = "highest_detected_with_one_pass_gap_guard"
    stopping_reason: str = "highest_detected_harmonic"
    stopping_harmonics_hz: tuple[float, ...] = ()
    cutoff_harmonic_hz: float | None = None
    source_workbook_fingerprints: tuple[dict[str, object], ...] = ()
    selection_fingerprint: str | None = None
    selection_cache_source: str = "computed_this_run"
    selection_cache_saved_at: str | None = None
    selection_cache_key: str | None = None
    declared_session_ids: tuple[str, ...] = ()
    analysis_condition_ids: tuple[str, ...] = ()
    recording_assignments: tuple[dict[str, object], ...] = ()
    eligible_harmonic_orders: tuple[int, ...] = ()
    spectral_eligibility_method_version: str | None = None
    spectral_eligibility_fingerprint: str | None = None

    def to_metadata(self) -> dict[str, object]:
        harmonic_domain = _canonical_harmonic_frequency_list(self.harmonic_domain_hz)
        detected_harmonics = _canonical_harmonic_frequency_list(
            self.detected_significant_harmonics_hz
        )
        selected_harmonics = _canonical_harmonic_frequency_list(self.selected_harmonics_hz)
        excluded_base = _canonical_harmonic_frequency_list(self.excluded_base_harmonics_hz)
        highest_meta = _highest_selected_harmonic_metadata(
            detected_harmonics,
            oddball_hz=self.oddball_frequency_hz,
            prefix="highest_significant_harmonic",
        )
        highest_included_meta = _highest_selected_harmonic_metadata(
            selected_harmonics,
            oddball_hz=self.oddball_frequency_hz,
            prefix="highest_included_harmonic",
        )
        gap_guard = _summation_gap_guard_decision(
            rows=self.rows,
            detected_freqs=detected_harmonics,
            summation_method=self.summation_method,
        )
        repeated_session = bool(self.declared_session_ids)
        metadata: dict[str, object] = {
            "harmonic_policy": GROUP_SIGNIFICANT_POLICY_ID,
            "harmonic_policy_label": GROUP_SIGNIFICANT_POLICY_LABEL,
            "harmonic_selection_profile": self.method_profile_id,
            "harmonic_selection_profile_version": self.method_profile_version,
            "harmonic_selection_profile_label": self.method_profile_label,
            "harmonic_selection_profile_citation": self.method_citation,
            "same_sample_adaptive": self.same_sample_adaptive,
            "selection_provenance": (
                "same_sample_adaptive" if self.same_sample_adaptive else "independent_fixed"
            ),
            "dependent_variable": "summed_bca",
            "selection_source_sheet": FULL_FFT_AMPLITUDE_SHEET_NAME,
            "selection_amplitude_summary": (
                "grand_average_raw_amplitude_spectrum"
                if self.method_profile_id == HARMONIC_PROFILE_LEGACY_ID
                else (
                    "participant_cell_means_then_equal_group_session_condition_spectra"
                    if repeated_session
                    else "participant_cell_means_then_equal_group_condition_spectra"
                )
            ),
            "selection_scope": self.selection_scope,
            "selection_conditions": list(self.selection_conditions),
            "selection_subjects": list(self.selection_subjects),
            "selection_spectra_count": int(self.selection_spectra_count),
            "selection_electrode_count": int(self.selection_electrode_count),
            "selection_electrode_mask": list(self.selection_electrode_mask),
            "electrode_scope": self.electrode_scope,
            "summation_method": self.summation_method,
            "pooling_method": self.pooling_method,
            "pooling_cells": [cell.to_metadata() for cell in self.pooling_cells],
            "pooling_cell_sample_sizes": {
                f"{cell.group_id}::{cell.condition}": cell.participant_count
                for cell in self.pooling_cells
            },
            "declared_group_ids": list(self.declared_group_ids),
            "condition_z_by_harmonic": {
                str(condition): {
                    str(_canonical_harmonic_frequency(freq)): value
                    for freq, value in values.items()
                }
                for condition, values in self.condition_z_by_harmonic.items()
            },
            "stopping_rule": self.stopping_rule,
            "stopping_reason": self.stopping_reason,
            "stopping_harmonics_hz": list(self.stopping_harmonics_hz),
            "cutoff_harmonic_hz": self.cutoff_harmonic_hz,
            "summation_gap_guard_rule": (
                GROUP_SIGNIFICANT_SUMMATION_GAP_GUARD_RULE
                if self.method_profile_id == HARMONIC_PROFILE_LEGACY_ID
                else None
            ),
            "summation_gap_guard_enabled": gap_guard.enabled,
            "summation_gap_guard_max_intervening_nonbase_harmonics": (
                GROUP_SIGNIFICANT_MAX_INTERVENING_NONBASE_HARMONICS
                if self.method_profile_id == HARMONIC_PROFILE_LEGACY_ID
                else None
            ),
            "summation_gap_guard_applied": gap_guard.applied,
            "summation_gap_guard_intervening_nonbase_harmonic_count": (
                gap_guard.intervening_nonbase_harmonic_count
            ),
            "summation_gap_guard_lower_significant_harmonic_hz": (
                gap_guard.lower_significant_harmonic_hz
            ),
            "summation_gap_guard_dropped_highest_significant_harmonic_hz": (
                gap_guard.highest_significant_harmonic_hz
                if gap_guard.applied
                else None
            ),
            "z_threshold": float(self.z_threshold),
            "z_score_source": (
                "computed_from_grand_averaged_amplitude_spectrum"
                if self.method_profile_id == HARMONIC_PROFILE_LEGACY_ID
                else (
                    "session_condition_local_z_then_equal_weight_cell_z_mean"
                    if repeated_session
                    else "condition_local_z_then_equal_weight_condition_z_mean"
                )
            ),
            "noise_window_bins": int(self.noise_window_bins),
            "base_frequency_hz": float(self.base_frequency_hz),
            "oddball_frequency_hz": float(self.oddball_frequency_hz),
            "base_overlap_exclusion_enabled": True,
            "base_overlap_tolerance_hz": float(self.base_overlap_tolerance_hz),
            "matching_tolerance_hz": float(self.matching_tolerance_hz),
            "frequency_resolution_hz": self.frequency_resolution_hz,
            "eligible_harmonic_orders": list(self.eligible_harmonic_orders),
            "spectral_eligibility_method_version": (
                self.spectral_eligibility_method_version
            ),
            "spectral_eligibility_fingerprint": (
                self.spectral_eligibility_fingerprint
            ),
            "harmonic_domain_hz": harmonic_domain,
            "evaluated_harmonics_hz": harmonic_domain,
            "detected_significant_harmonics_hz": detected_harmonics,
            "detected_significant_columns": list(self.detected_significant_columns),
            "detected_significant_bin_indices": list(
                self.detected_significant_bin_indices
            ),
            "included_harmonics_hz": selected_harmonics,
            "common_harmonics_hz": selected_harmonics,
            "selected_harmonics_hz": selected_harmonics,
            **highest_meta,
            **highest_included_meta,
            "selected_columns": list(self.selected_columns),
            "selected_bin_indices": list(self.selected_bin_indices),
            "selection_z_by_harmonic": {
                _canonical_harmonic_frequency(freq): value
                for freq, value in self.z_by_harmonic.items()
            },
            "excluded_base_harmonics_hz": excluded_base,
            "base_overlap_excluded_harmonics_hz": excluded_base,
            "applied_uniformly_across_participants": True,
            "applied_uniformly_across_conditions": True,
            "applied_uniformly_across_rois": True,
            "snr_used_for_statistics": False,
            "bca_negative_values_retained": True,
            "bca_near_zero_values_retained": True,
            "selection_rows": [
                {
                    "harmonic_index": row.harmonic_index,
                    "target_frequency_hz": _canonical_harmonic_frequency(
                        row.target_frequency_hz
                    ),
                    "matched_frequency_hz": _canonical_optional_frequency(
                        row.matched_frequency_hz
                    ),
                    "matched_column": row.matched_column,
                    "matched_bin_index": row.matched_bin_index,
                    "z_score": row.z_score,
                    "selected": row.selected,
                    "excluded_base_rate": row.excluded_base_rate,
                    "exclusion_reason": row.exclusion_reason,
                    "warning": row.warning,
                    "evaluated": row.evaluated,
                    "target_amplitude_uv": row.target_amplitude_uv,
                    "noise_mean_uv": row.noise_mean_uv,
                    "noise_std_uv": row.noise_std_uv,
                    "noise_bin_indices": list(row.noise_bin_indices),
                    "noise_frequencies_hz": list(row.noise_frequencies_hz),
                    "noise_amplitudes_uv": list(row.noise_amplitudes_uv),
                    "noise_used_bin_indices": list(row.noise_used_bin_indices),
                    "noise_used_frequencies_hz": list(row.noise_used_frequencies_hz),
                    "noise_used_amplitudes_uv": list(row.noise_used_amplitudes_uv),
                    "included_in_summation": bool(row.included_in_summation),
                    "condition_z_scores": {
                        condition: value for condition, value in row.condition_z_scores
                    },
                }
                for row in self.rows
            ],
            "selection_cache_source": self.selection_cache_source,
            "selection_cache_saved_at": self.selection_cache_saved_at,
            "selection_cache_key": self.selection_cache_key,
            "source_workbook_fingerprints": list(self.source_workbook_fingerprints),
            "methods_summary": _methods_summary(self),
        }
        if repeated_session:
            metadata.update(
                {
                    "selection_identity_level": "recording",
                    "declared_session_ids": list(self.declared_session_ids),
                    "analysis_session_condition_ids": list(
                        self.analysis_condition_ids
                    ),
                    "recording_assignments": [
                        dict(row) for row in self.recording_assignments
                    ],
                    "selection_recordings": [
                        str(row.get("recording_id") or "")
                        for row in self.recording_assignments
                    ],
                    "repeated_session_pooling_version": (
                        REPEATED_SESSION_POOLING_METHOD_VERSION
                    ),
                    "applied_uniformly_across_sessions": True,
                }
            )
        from Tools.Stats.analysis.canonical_harmonics import (
            compute_selection_fingerprint,
        )

        metadata["selection_fingerprint"] = (
            self.selection_fingerprint or compute_selection_fingerprint(metadata)
        )
        return metadata


@dataclass(frozen=True)
class RequiredFullFftColumns:
    usecols: list[str]
    frequency_columns: list[tuple[float, str, int]]
    candidate_indices: list[int]
    excluded_base_indices: list[int]
    required_indices: list[int]
    oddball_frequency_hz: float = LOCKED_ODDBALL_FREQUENCY_HZ
    canonical_eligibility_domain: bool = False


@dataclass(frozen=True)
class WorkbookSignature:
    subject: str
    condition: str
    path: str
    size_bytes: int | None
    mtime_ns: int | None
    spectral_companion_json: str | None = None
    condition_companion_json: str | None = None


@dataclass(frozen=True)
class GroupSignificantSelectionCacheKey:
    method_version: str
    subjects: tuple[str, ...]
    conditions: tuple[str, ...]
    workbooks: tuple[WorkbookSignature, ...]
    rois: tuple[tuple[str, tuple[str, ...]], ...]
    base_frequency_hz: float
    oddball_frequency_hz: float | None
    max_freq_hz: float | None
    z_threshold: float
    electrode_scope: str
    summation_method: str
    method_profile_id: str
    method_profile_version: str
    selection_electrodes: tuple[str, ...]
    group_assignments: tuple[tuple[str, str], ...]
    declared_group_ids: tuple[str, ...]
    project_processing_signature_hash: str | None = None
    recording_assignments: tuple[tuple[object, ...], ...] = ()
    declared_session_ids: tuple[str, ...] = ()
    eligible_harmonic_orders: tuple[int, ...] = ()
    spectral_eligibility_fingerprint: str | None = None
    electrode_exclusions_by_subject_condition: tuple[
        tuple[str, str, tuple[str, ...]], ...
    ] = ()
    expected_scalp_channels_by_subject_condition: tuple[
        tuple[str, str, tuple[str, ...]], ...
    ] = ()


def clear_group_significant_selection_cache() -> None:
    with _GROUP_SELECTION_CACHE_LOCK:
        _GROUP_SELECTION_CACHE.clear()


def _canonical_harmonic_frequency(value: float) -> float:
    return round(float(value), GROUP_SIGNIFICANT_FREQUENCY_DECIMALS)


def _canonical_optional_frequency(value: float | None) -> float | None:
    if value is None:
        return None
    return _canonical_harmonic_frequency(value)


def _canonical_harmonic_frequency_list(values: Iterable[float]) -> list[float]:
    return [_canonical_harmonic_frequency(value) for value in values]


def _canonical_harmonic_frequency_for_index(
    harmonic_index: int,
    oddball_hz: float,
) -> float:
    return float(Decimal(str(oddball_hz)) * Decimal(int(harmonic_index)))


def _format_harmonic_frequency(value: float) -> str:
    return f"{_canonical_harmonic_frequency(value):g}"


def _format_harmonic_frequency_list(values: Iterable[float]) -> str:
    return "[" + ", ".join(_format_harmonic_frequency(value) for value in values) + "]"


def preflight_group_significant_full_fft_columns(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_frequency_hz: float,
    log_func: Callable[[str], None],
    max_freq: float | None = None,
    oddball_frequency_hz: float | None = None,
    eligible_harmonic_orders: Sequence[int] | None = None,
) -> int:
    """Validate exact FullFFT harmonic columns before expensive Stats reads."""
    required = _plan_required_full_fft_columns(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_frequency_hz=base_frequency_hz,
        max_freq=max_freq,
        log_func=log_func,
        oddball_frequency_hz=oddball_frequency_hz,
        eligible_harmonic_orders=eligible_harmonic_orders,
    )
    return _preflight_required_full_fft_columns(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        required=required,
        log_func=log_func,
    )


def _get_cached_group_significant_selection(
    cache_key: GroupSignificantSelectionCacheKey,
) -> GroupSignificantHarmonicSelection | None:
    with _GROUP_SELECTION_CACHE_LOCK:
        return _GROUP_SELECTION_CACHE.get(cache_key)


def _store_group_significant_selection(
    cache_key: GroupSignificantSelectionCacheKey,
    selection: GroupSignificantHarmonicSelection,
) -> None:
    with _GROUP_SELECTION_CACHE_LOCK:
        if (
            cache_key not in _GROUP_SELECTION_CACHE
            and len(_GROUP_SELECTION_CACHE) >= GROUP_SIGNIFICANT_SELECTION_CACHE_MAX_ENTRIES
        ):
            oldest_key = next(iter(_GROUP_SELECTION_CACHE))
            _GROUP_SELECTION_CACHE.pop(oldest_key, None)
        _GROUP_SELECTION_CACHE[cache_key] = selection


def _resolve_profile_group_structure(
    *,
    subjects: Sequence[str],
    settings: DVPolicySettings,
    project_root: str | Path | None,
    participant_group_ids: Mapping[str, str] | None,
    declared_group_ids: Sequence[str] | None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    if settings.harmonic_selection_profile == HARMONIC_PROFILE_LEGACY_ID:
        return {}, ()
    if participant_group_ids is not None or declared_group_ids is not None:
        return normalize_group_structure(
            subjects=subjects,
            participant_group_ids=participant_group_ids,
            declared_group_ids=declared_group_ids,
        )
    if project_root not in (None, ""):
        from Main_App.projects import load_project_dataset_index

        dataset_index = load_project_dataset_index(Path(project_root))
        if dataset_index.has_group_metadata:
            return normalize_group_structure(
                subjects=subjects,
                participant_group_ids=dataset_index.participant_group_id_map(
                    uppercase_keys=True,
                    include_legacy_aliases=True,
                ),
                declared_group_ids=tuple(
                    sorted(dataset_index.groups.keys(), key=str.casefold)
                ),
            )
    return normalize_group_structure(
        subjects=subjects,
        participant_group_ids=None,
        declared_group_ids=None,
    )


def _group_significant_selection_cache_key(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    rois: Dict[str, List[str]],
    base_frequency_hz: float,
    max_freq: float | None,
    settings: DVPolicySettings,
    participant_group_ids: Mapping[str, str] | None = None,
    declared_group_ids: Sequence[str] | None = None,
    project_processing_signature_hash: str | None = None,
    recording_assignments: Mapping[str, Mapping[str, object]] | None = None,
    declared_session_ids: Sequence[str] | None = None,
    oddball_frequency_hz: float | None = None,
    eligible_harmonic_orders: Sequence[int] | None = None,
    spectral_eligibility_fingerprint: str | None = None,
    electrode_exclusions_by_subject_condition: Mapping[
        tuple[str, str], frozenset[str]
    ]
    | None = None,
    expected_scalp_channels_by_subject_condition: Mapping[
        tuple[str, str], Sequence[str]
    ]
    | None = None,
) -> GroupSignificantSelectionCacheKey:
    subject_key = tuple(str(subject) for subject in subjects)
    condition_key = tuple(str(condition) for condition in conditions)
    workbook_signatures = tuple(
        _workbook_signature(
            subject=subject,
            condition=condition,
            file_path=subject_data.get(subject, {}).get(condition),
        )
        for subject in subject_key
        for condition in condition_key
    )
    rois_key = (
        tuple(
            (str(roi_name), tuple(str(channel).upper().strip() for channel in channels or ()))
            for roi_name, channels in sorted((rois or {}).items())
        )
        if settings.harmonic_selection_profile == HARMONIC_PROFILE_LEGACY_ID
        else ()
    )
    return GroupSignificantSelectionCacheKey(
        method_version=(
            GROUP_HARMONIC_METHOD_VERSION
            if settings.harmonic_selection_profile == HARMONIC_PROFILE_LEGACY_ID
            else (
                "group_significant_harmonic_profiles_"
                f"{settings.harmonic_selection_profile}_v"
                f"{settings.harmonic_selection_profile_version}"
            )
        ),
        subjects=subject_key,
        conditions=condition_key,
        workbooks=workbook_signatures,
        rois=rois_key,
        base_frequency_hz=float(base_frequency_hz),
        oddball_frequency_hz=float(
            LOCKED_ODDBALL_FREQUENCY_HZ
            if oddball_frequency_hz is None
            else oddball_frequency_hz
        ),
        max_freq_hz=float(max_freq) if max_freq is not None else None,
        z_threshold=float(settings.group_significant_z_threshold),
        electrode_scope=str(settings.group_significant_electrode_scope),
        summation_method=str(settings.group_significant_summation_method),
        method_profile_id=settings.harmonic_selection_profile,
        method_profile_version=settings.harmonic_selection_profile_version,
        selection_electrodes=tuple(settings.group_significant_selection_electrodes),
        group_assignments=tuple(
            sorted(
                (
                    (str(subject), str(group_id))
                    for subject, group_id in (participant_group_ids or {}).items()
                ),
                key=lambda item: item[0].casefold(),
            )
        ),
        declared_group_ids=tuple(str(group_id) for group_id in (declared_group_ids or ())),
        project_processing_signature_hash=project_processing_signature_hash,
        recording_assignments=tuple(
            sorted(
                (
                    (
                        str(recording_id),
                        str(row.get("participant_id") or ""),
                        str(row.get("group_id") or ""),
                        str(row.get("session_id") or ""),
                        str(row.get("source_id") or ""),
                        _metadata_optional_int(row.get("visit_index")),
                        _metadata_optional_float(row.get("days_from_baseline")),
                    )
                    for recording_id, row in (recording_assignments or {}).items()
                ),
                key=lambda item: item[0].casefold(),
            )
        ),
        declared_session_ids=tuple(
            str(session_id) for session_id in (declared_session_ids or ())
        ),
        eligible_harmonic_orders=_normalize_eligible_harmonic_orders(
            eligible_harmonic_orders,
            allow_unspecified=True,
        ),
        spectral_eligibility_fingerprint=(
            str(spectral_eligibility_fingerprint).strip()
            if spectral_eligibility_fingerprint
            else None
        ),
        electrode_exclusions_by_subject_condition=tuple(
            sorted(
                (
                    str(subject).upper(),
                    str(condition).casefold(),
                    tuple(sorted(str(channel).upper() for channel in channels)),
                )
                for (subject, condition), channels in (
                    electrode_exclusions_by_subject_condition or {}
                ).items()
            )
        ),
        expected_scalp_channels_by_subject_condition=tuple(
            sorted(
                (
                    str(subject).upper(),
                    str(condition).casefold(),
                    tuple(str(channel).upper() for channel in channels),
                )
                for (subject, condition), channels in (
                    expected_scalp_channels_by_subject_condition or {}
                ).items()
            )
        ),
    )


def _log_project_cache_warnings(
    cache_request: GroupHarmonicCacheRequest | None,
    log_func: Callable[[str], None],
) -> None:
    if cache_request is None:
        return
    for warning in cache_request.ledger_warnings:
        log_func(f"Warning: {warning}")


def _load_project_cached_selection(
    cache_request: GroupHarmonicCacheRequest | None,
    log_func: Callable[[str], None],
) -> GroupSignificantHarmonicSelection | None:
    lookup = lookup_cached_group_harmonic_selection(cache_request)
    if lookup.hit is None:
        reason = lookup.reason
        if reason and reason != "No saved group-significant harmonics.":
            log_func(f"Project harmonic cache miss: {reason}")
        return None
    try:
        selection = group_significant_selection_from_metadata(
            lookup.hit.selection_metadata,
        )
    except Exception as exc:  # noqa: BLE001
        log_func(
            "Project harmonic cache entry could not be read; recalculating "
            f"group-level significant harmonics. Error: {exc}"
        )
        logger.warning("stats_group_harmonics_project_cache_invalid", exc_info=True)
        return None
    return replace(
        selection,
        selection_cache_source="saved_project_metadata",
        selection_cache_saved_at=lookup.hit.saved_at,
        selection_cache_key=lookup.hit.cache_key,
    )


def _save_project_cached_selection(
    cache_request: GroupHarmonicCacheRequest | None,
    selection: GroupSignificantHarmonicSelection,
    log_func: Callable[[str], None],
) -> GroupSignificantHarmonicSelection:
    if cache_request is None:
        return selection
    try:
        saved_at = save_cached_group_harmonic_selection(
            cache_request,
            selection.to_metadata(),
        )
    except Exception as exc:  # noqa: BLE001
        log_func(
            "Warning: could not save selected significant harmonics to project metadata; "
            f"future exports may need to recalculate. Error: {exc}"
        )
        logger.warning("stats_group_harmonics_project_cache_save_failed", exc_info=True)
        return selection
    if not saved_at:
        return selection
    log_func(
        "Saved group-level significant harmonics to project metadata for future exports."
    )
    return replace(
        selection,
        selection_cache_source="computed_this_run_saved_project_metadata",
        selection_cache_saved_at=saved_at,
        selection_cache_key=cache_request.cache_key,
    )


def _repair_project_cache_for_in_memory_selection(
    cache_request: GroupHarmonicCacheRequest | None,
    selection: GroupSignificantHarmonicSelection,
    log_func: Callable[[str], None],
) -> GroupSignificantHarmonicSelection:
    if cache_request is None:
        return selection
    if lookup_cached_group_harmonic_selection(cache_request).hit is not None:
        return selection
    log_func(
        "Project harmonic metadata was missing for an in-memory selection; "
        "restoring the durable cache entry."
    )
    return _save_project_cached_selection(cache_request, selection, log_func)


def group_significant_selection_from_metadata(
    metadata: Dict[str, object],
) -> GroupSignificantHarmonicSelection:
    """Rehydrate a saved group-significant selection from manifest metadata."""

    if not isinstance(metadata, dict):
        raise TypeError("selection metadata must be a dictionary")
    selected_harmonics = _canonical_harmonic_frequency_list(
        _metadata_float_list(
            metadata.get("selected_harmonics_hz")
            if metadata.get("selected_harmonics_hz") not in (None, "")
            else metadata.get("included_harmonics_hz")
        )
    )
    if not selected_harmonics:
        raise ValueError("saved selection contains no selected harmonics")
    detected_harmonics = (
        _canonical_harmonic_frequency_list(
            _metadata_float_list(metadata.get("detected_significant_harmonics_hz"))
        )
        or list(selected_harmonics)
    )
    oddball = _metadata_float(
        metadata.get("oddball_frequency_hz"),
        default=LOCKED_ODDBALL_FREQUENCY_HZ,
    )
    rows = [
        _group_significant_row_from_metadata(row_data)
        for row_data in (metadata.get("selection_rows") or [])
        if isinstance(row_data, dict)
    ]
    selected_columns = [
        str(column)
        for column in _metadata_sequence(metadata.get("selected_columns"))
        if str(column).strip()
    ]
    if not selected_columns:
        selected_columns = [f"{freq:.4f}_Hz" for freq in selected_harmonics]
    detected_columns = [
        str(column)
        for column in _metadata_sequence(metadata.get("detected_significant_columns"))
        if str(column).strip()
    ] or [f"{freq:.4f}_Hz" for freq in detected_harmonics]
    return GroupSignificantHarmonicSelection(
        harmonic_domain_hz=_canonical_harmonic_frequency_list(
            _metadata_float_list(metadata.get("harmonic_domain_hz"))
        ),
        selected_harmonics_hz=selected_harmonics,
        selected_columns=selected_columns,
        selected_bin_indices=_metadata_int_list(metadata.get("selected_bin_indices")),
        detected_significant_harmonics_hz=detected_harmonics,
        detected_significant_columns=detected_columns,
        detected_significant_bin_indices=_metadata_int_list(
            metadata.get("detected_significant_bin_indices")
        ) or _metadata_int_list(metadata.get("selected_bin_indices")),
        z_by_harmonic={
            _canonical_harmonic_frequency(freq): value
            for freq, value in _metadata_float_map(
                metadata.get("selection_z_by_harmonic")
            ).items()
        },
        excluded_base_harmonics_hz=_canonical_harmonic_frequency_list(
            _metadata_float_list(metadata.get("excluded_base_harmonics_hz"))
        ),
        oddball_frequency_hz=oddball,
        base_frequency_hz=_metadata_float(metadata.get("base_frequency_hz"), default=np.nan),
        z_threshold=_metadata_float(metadata.get("z_threshold"), default=np.nan),
        electrode_scope=str(metadata.get("electrode_scope") or ""),
        summation_method=str(
            metadata.get("summation_method")
            or GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY
        ),
        selection_scope=str(metadata.get("selection_scope") or ""),
        selection_conditions=[
            str(value) for value in _metadata_sequence(metadata.get("selection_conditions"))
        ],
        selection_subjects=[
            str(value) for value in _metadata_sequence(metadata.get("selection_subjects"))
        ],
        selection_spectra_count=_metadata_int(metadata.get("selection_spectra_count"), default=0),
        selection_electrode_count=_metadata_int(
            metadata.get("selection_electrode_count"),
            default=0,
        ),
        frequency_resolution_hz=_metadata_optional_float(
            metadata.get("frequency_resolution_hz")
        ),
        base_overlap_tolerance_hz=_metadata_float(
            metadata.get("base_overlap_tolerance_hz"),
            default=GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ,
        ),
        matching_tolerance_hz=_metadata_float(
            metadata.get("matching_tolerance_hz"),
            default=GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ,
        ),
        noise_window_bins=_metadata_int(
            metadata.get("noise_window_bins"),
            default=GROUP_SIGNIFICANT_NOISE_WINDOW_BINS,
        ),
        rows=rows,
        method_profile_id=str(
            metadata.get("harmonic_selection_profile") or HARMONIC_PROFILE_LEGACY_ID
        ),
        method_profile_version=str(
            metadata.get("harmonic_selection_profile_version") or "1.0"
        ),
        method_profile_label=str(
            metadata.get("harmonic_selection_profile_label") or "Legacy FPVS Toolbox"
        ),
        method_citation=str(
            metadata.get("harmonic_selection_profile_citation")
            or "FPVS Toolbox legacy behavior retained for reproducibility"
        ),
        same_sample_adaptive=bool(metadata.get("same_sample_adaptive", True)),
        pooling_method=str(
            metadata.get("pooling_method") or "equal_available_workbook_amplitude_mean"
        ),
        pooling_cells=_pooling_cells_from_metadata(metadata.get("pooling_cells")),
        declared_group_ids=tuple(
            _metadata_string_list(metadata.get("declared_group_ids"))
        ),
        condition_z_by_harmonic=_metadata_nested_float_map(
            metadata.get("condition_z_by_harmonic")
        ),
        selection_electrode_mask=tuple(
            _metadata_string_list(metadata.get("selection_electrode_mask"))
        ),
        stopping_rule=str(metadata.get("stopping_rule") or ""),
        stopping_reason=str(metadata.get("stopping_reason") or ""),
        stopping_harmonics_hz=tuple(
            _metadata_float_list(metadata.get("stopping_harmonics_hz"))
        ),
        cutoff_harmonic_hz=_metadata_optional_float(
            metadata.get("cutoff_harmonic_hz")
        ),
        source_workbook_fingerprints=tuple(
            dict(item)
            for item in _metadata_sequence(metadata.get("source_workbook_fingerprints"))
            if isinstance(item, dict)
        ),
        selection_fingerprint=(
            str(metadata.get("selection_fingerprint"))
            if metadata.get("selection_fingerprint") not in (None, "")
            else None
        ),
        selection_cache_source=str(metadata.get("selection_cache_source") or "saved_project_metadata"),
        selection_cache_saved_at=(
            str(metadata.get("selection_cache_saved_at"))
            if metadata.get("selection_cache_saved_at") not in (None, "")
            else None
        ),
        selection_cache_key=(
            str(metadata.get("selection_cache_key"))
            if metadata.get("selection_cache_key") not in (None, "")
            else None
        ),
        declared_session_ids=tuple(
            _metadata_string_list(metadata.get("declared_session_ids"))
        ),
        analysis_condition_ids=tuple(
            _metadata_string_list(metadata.get("analysis_session_condition_ids"))
        ),
        recording_assignments=tuple(
            dict(item)
            for item in _metadata_sequence(metadata.get("recording_assignments"))
            if isinstance(item, dict)
        ),
        eligible_harmonic_orders=tuple(
            _metadata_int_list(metadata.get("eligible_harmonic_orders"))
        ),
        spectral_eligibility_method_version=(
            str(metadata.get("spectral_eligibility_method_version"))
            if metadata.get("spectral_eligibility_method_version") not in (None, "")
            else None
        ),
        spectral_eligibility_fingerprint=(
            str(metadata.get("spectral_eligibility_fingerprint"))
            if metadata.get("spectral_eligibility_fingerprint") not in (None, "")
            else None
        ),
    )


def _group_significant_row_from_metadata(row_data: dict[str, object]) -> GroupSignificantHarmonicRow:
    return GroupSignificantHarmonicRow(
        harmonic_index=_metadata_int(row_data.get("harmonic_index"), default=0),
        target_frequency_hz=_canonical_harmonic_frequency(
            _metadata_float(row_data.get("target_frequency_hz"), default=np.nan)
        ),
        matched_frequency_hz=_canonical_optional_frequency(
            _metadata_optional_float(row_data.get("matched_frequency_hz"))
        ),
        matched_column=(
            str(row_data.get("matched_column"))
            if row_data.get("matched_column") not in (None, "")
            else None
        ),
        matched_bin_index=_metadata_optional_int(row_data.get("matched_bin_index")),
        z_score=_metadata_optional_float(row_data.get("z_score")),
        selected=bool(row_data.get("selected")),
        excluded_base_rate=bool(row_data.get("excluded_base_rate")),
        exclusion_reason=str(row_data.get("exclusion_reason") or ""),
        warning=str(row_data.get("warning") or ""),
        evaluated=bool(row_data.get("evaluated", True)),
        target_amplitude_uv=_metadata_optional_float(row_data.get("target_amplitude_uv")),
        noise_mean_uv=_metadata_optional_float(row_data.get("noise_mean_uv")),
        noise_std_uv=_metadata_optional_float(row_data.get("noise_std_uv")),
        noise_bin_indices=tuple(_metadata_int_list(row_data.get("noise_bin_indices"))),
        noise_frequencies_hz=tuple(_metadata_float_list(row_data.get("noise_frequencies_hz"))),
        noise_amplitudes_uv=tuple(_metadata_float_list(row_data.get("noise_amplitudes_uv"))),
        noise_used_bin_indices=tuple(
            _metadata_int_list(row_data.get("noise_used_bin_indices"))
        ),
        noise_used_frequencies_hz=tuple(
            _metadata_float_list(row_data.get("noise_used_frequencies_hz"))
        ),
        noise_used_amplitudes_uv=tuple(
            _metadata_float_list(row_data.get("noise_used_amplitudes_uv"))
        ),
        included_in_summation=bool(
            row_data.get("included_in_summation", row_data.get("selected", False))
        ),
        condition_z_scores=tuple(
            (str(condition), _metadata_optional_float(value))
            for condition, value in (
                row_data.get("condition_z_scores", {}).items()
                if isinstance(row_data.get("condition_z_scores"), dict)
                else ()
            )
        ),
    )


def _metadata_sequence(value: object) -> list[object]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return []


def _metadata_float(value: object, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return float(number) if np.isfinite(number) else float(default)


def _metadata_optional_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return float(number) if np.isfinite(number) else None


def _metadata_int(value: object, *, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return int(default)
    return int(number)


def _metadata_optional_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metadata_float_list(value: object) -> list[float]:
    out: list[float] = []
    for item in _metadata_sequence(value):
        number = _metadata_optional_float(item)
        if number is not None:
            out.append(float(number))
    return out


def _metadata_int_list(value: object) -> list[int]:
    out: list[int] = []
    for item in _metadata_sequence(value):
        number = _metadata_optional_int(item)
        if number is not None:
            out.append(int(number))
    return out


def _metadata_float_map(value: object) -> dict[float, float]:
    if not isinstance(value, dict):
        return {}
    out: dict[float, float] = {}
    for raw_key, raw_value in value.items():
        key = _metadata_optional_float(raw_key)
        map_value = _metadata_optional_float(raw_value)
        if key is not None and map_value is not None:
            out[float(key)] = float(map_value)
    return out


def _metadata_string_list(value: object) -> list[str]:
    return [
        str(item)
        for item in _metadata_sequence(value)
        if str(item).strip()
    ]


def _metadata_nested_float_map(
    value: object,
) -> dict[str, dict[float, float | None]]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict[float, float | None]] = {}
    for condition, raw_values in value.items():
        if not isinstance(raw_values, dict):
            continue
        condition_values: dict[float, float | None] = {}
        for raw_freq, raw_z in raw_values.items():
            freq = _metadata_optional_float(raw_freq)
            if freq is None:
                continue
            condition_values[_canonical_harmonic_frequency(freq)] = (
                _metadata_optional_float(raw_z)
            )
        out[str(condition)] = condition_values
    return out


def _pooling_cells_from_metadata(value: object) -> tuple[HarmonicPoolingCell, ...]:
    cells: list[HarmonicPoolingCell] = []
    for raw_cell in _metadata_sequence(value):
        if not isinstance(raw_cell, dict):
            continue
        cells.append(
            HarmonicPoolingCell(
                group_id=str(raw_cell.get("group_id") or ""),
                condition=str(raw_cell.get("condition") or ""),
                participant_ids=tuple(
                    _metadata_string_list(raw_cell.get("participant_ids"))
                ),
                participant_count=_metadata_int(
                    raw_cell.get("participant_count"), default=0
                ),
                participant_weight_within_cell=_metadata_float(
                    raw_cell.get("participant_weight_within_cell"), default=0.0
                ),
                group_weight_within_condition=_metadata_float(
                    raw_cell.get("group_weight_within_condition"), default=0.0
                ),
                condition_weight=_metadata_float(
                    raw_cell.get("condition_weight"), default=0.0
                ),
                effective_participant_weight=_metadata_float(
                    raw_cell.get("effective_participant_weight"), default=0.0
                ),
                session_id=(
                    str(raw_cell.get("session_id"))
                    if raw_cell.get("session_id") not in (None, "")
                    else None
                ),
                recording_ids=tuple(
                    _metadata_string_list(raw_cell.get("recording_ids"))
                ),
                session_weight=_metadata_optional_float(
                    raw_cell.get("session_weight")
                ),
                task_condition_weight=_metadata_optional_float(
                    raw_cell.get("task_condition_weight")
                ),
                cell_weight=_metadata_optional_float(raw_cell.get("cell_weight")),
            )
        )
    return tuple(cells)


def _workbook_signature(
    *,
    subject: str,
    condition: str,
    file_path: str | None,
) -> WorkbookSignature:
    from Main_App.io.condition_data import condition_companion_identity
    from Main_App.io.spectral_data import spectral_companion_identity

    if not file_path:
        return WorkbookSignature(
            subject=str(subject),
            condition=str(condition),
            path="",
            size_bytes=None,
            mtime_ns=None,
        )
    path = Path(file_path)
    try:
        resolved = str(path.resolve(strict=False))
    except OSError:
        resolved = str(path)
    try:
        stat = path.stat()
    except OSError:
        return WorkbookSignature(
            subject=str(subject),
            condition=str(condition),
            path=resolved,
            size_bytes=None,
            mtime_ns=None,
        )
    companion = spectral_companion_identity(path)
    condition_companion = condition_companion_identity(path)
    return WorkbookSignature(
        subject=str(subject),
        condition=str(condition),
        path=resolved,
        size_bytes=int(stat.st_size),
        mtime_ns=int(stat.st_mtime_ns),
        spectral_companion_json=(
            json.dumps(companion, sort_keys=True, separators=(",", ":"))
            if companion is not None
            else None
        ),
        condition_companion_json=(
            json.dumps(condition_companion, sort_keys=True, separators=(",", ":"))
            if condition_companion is not None
            else None
        ),
    )


def build_group_significant_harmonic_selection(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_frequency_hz: float,
    rois: Dict[str, List[str]],
    log_func: Callable[[str], None],
    settings: DVPolicySettings,
    max_freq: float | None = None,
    project_root: str | Path | None = None,
    force_recalculate: bool = False,
    participant_group_ids: Mapping[str, str] | None = None,
    declared_group_ids: Sequence[str] | None = None,
    recording_assignments: Mapping[str, Mapping[str, object]] | None = None,
    declared_session_ids: Sequence[str] | None = None,
    electrode_exclusions_by_subject: Mapping[str, frozenset[str]] | None = None,
    electrode_exclusions_by_subject_condition: Mapping[
        tuple[str, str], frozenset[str]
    ]
    | None = None,
    expected_scalp_channels_by_subject_condition: Mapping[
        tuple[str, str], Sequence[str]
    ]
    | None = None,
    oddball_frequency_hz: float | None = None,
    eligible_harmonic_orders: Sequence[int] | None = None,
    spectral_eligibility_fingerprint: str | None = None,
) -> GroupSignificantHarmonicSelection:
    started = perf_counter()
    repeated_session = bool(recording_assignments)
    resolved_electrode_exclusions: dict[str, frozenset[str]] = {
        str(subject).upper(): frozenset(
            str(electrode).upper() for electrode in electrodes
        )
        for subject, electrodes in (electrode_exclusions_by_subject or {}).items()
    }
    resolved_condition_electrode_exclusions: dict[
        tuple[str, str], frozenset[str]
    ] = {
        (str(subject).upper(), str(condition).casefold()): frozenset(
            str(electrode).upper() for electrode in electrodes
        )
        for (subject, condition), electrodes in (
            electrode_exclusions_by_subject_condition or {}
        ).items()
    }
    resolved_expected_scalp_channels: dict[tuple[str, str], tuple[str, ...]] = {
        (str(subject).upper(), str(condition).casefold()): tuple(
            str(electrode).strip().upper() for electrode in electrodes
        )
        for (subject, condition), electrodes in (
            expected_scalp_channels_by_subject_condition or {}
        ).items()
    }
    for key, expected_channels in resolved_expected_scalp_channels.items():
        if not expected_channels or len(expected_channels) != len(set(expected_channels)):
            raise RuntimeError(
                "Harmonic-selection QC-21 source membership must be a nonempty "
                f"unique scalp set for {key[0]}/{key[1]}."
            )
    if project_root not in (None, ""):
        from Main_App.processing.frequency_domain_qc import (
            active_frequency_domain_exclusions,
            filter_frequency_domain_recordings,
            filter_frequency_domain_subjects,
        )

        if repeated_session:
            recording_participants = {
                str(recording_id): str(row.get("participant_id") or "")
                for recording_id, row in (recording_assignments or {}).items()
            }
            subjects, subject_data, frequency_excluded = (
                filter_frequency_domain_recordings(
                    project_root,
                    subjects,
                    subject_data,
                    recording_participant_ids=recording_participants,
                )
            )
        else:
            subjects, subject_data, frequency_excluded = (
                filter_frequency_domain_subjects(
                    project_root,
                    subjects,
                    subject_data,
                )
            )
        if frequency_excluded:
            log_func(
                "Frequency-domain "
                + ("recording" if repeated_session else "participant")
                + " exclusions applied before group "
                "harmonic selection: " + ", ".join(frequency_excluded)
            )
        if (
            not resolved_electrode_exclusions
            and not resolved_condition_electrode_exclusions
        ):
            exclusions = active_frequency_domain_exclusions(project_root)
            resolved_condition_electrode_exclusions = dict(
                exclusions.excluded_electrodes_by_recording_condition
                if repeated_session
                else exclusions.excluded_electrodes_by_participant_condition
            )
    if repeated_session and settings.harmonic_selection_profile != HARMONIC_PROFILE_LEGACY_ID:
        selected_participants = tuple(
            dict.fromkeys(
                str((recording_assignments or {})[recording_id].get("participant_id") or "")
                for recording_id in subjects
                if recording_id in (recording_assignments or {})
            )
        )
        resolved_group_ids, resolved_declared_groups = normalize_group_structure(
            subjects=selected_participants,
            participant_group_ids=participant_group_ids,
            declared_group_ids=declared_group_ids,
        )
    else:
        resolved_group_ids, resolved_declared_groups = _resolve_profile_group_structure(
            subjects=subjects,
            settings=settings,
            project_root=project_root,
            participant_group_ids=participant_group_ids,
            declared_group_ids=declared_group_ids,
        )
    cache_request = build_group_harmonic_cache_request(
        project_root=project_root,
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        rois=rois,
        base_frequency_hz=base_frequency_hz,
        max_freq_hz=max_freq,
        settings=settings,
        recording_assignments=recording_assignments,
        declared_session_ids=declared_session_ids,
        oddball_frequency_hz=oddball_frequency_hz,
    )
    _log_project_cache_warnings(cache_request, log_func)
    cache_key = _group_significant_selection_cache_key(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        rois=rois,
        base_frequency_hz=base_frequency_hz,
        max_freq=max_freq,
        settings=settings,
        participant_group_ids=resolved_group_ids,
        declared_group_ids=resolved_declared_groups,
        recording_assignments=recording_assignments,
        declared_session_ids=declared_session_ids,
        oddball_frequency_hz=oddball_frequency_hz,
        eligible_harmonic_orders=eligible_harmonic_orders,
        spectral_eligibility_fingerprint=spectral_eligibility_fingerprint,
        electrode_exclusions_by_subject_condition=(
            resolved_condition_electrode_exclusions
        ),
        expected_scalp_channels_by_subject_condition=(
            resolved_expected_scalp_channels
        ),
        project_processing_signature_hash=(
            cache_request.project_processing_signature_hash
            if cache_request is not None
            else None
        ),
    )
    if force_recalculate:
        log_func(
            "Forced harmonic recalculation requested; existing in-memory and "
            "saved selections will be ignored until a replacement is ready."
        )
    else:
        cached = _get_cached_group_significant_selection(cache_key)
        if cached is not None:
            cached = _repair_project_cache_for_in_memory_selection(
                cache_request,
                cached,
                log_func,
            )
            elapsed = perf_counter() - started
            log_func(
                "[PERF] Group harmonic selection cache hit: "
                f"reusing {len(cached.selected_harmonics_hz)} selected harmonics "
                f"for {len(subjects) * len(conditions)} planned workbooks "
                f"in {elapsed:.2f}s."
            )
            logger.debug(
                "stats_group_harmonics_selection_cache_hit",
                extra={
                    "elapsed_s": elapsed,
                    "subjects": len(subjects),
                    "conditions": len(conditions),
                    "selected_harmonics": _format_harmonic_frequency_list(
                        cached.selected_harmonics_hz
                    ),
                },
            )
            return cached
        project_cached = _load_project_cached_selection(cache_request, log_func)
        if project_cached is not None:
            elapsed = perf_counter() - started
            log_func(
                "[PERF] Project harmonic cache hit: "
                f"using {len(project_cached.selected_harmonics_hz)} saved harmonics "
                f"for {len(subjects) * len(conditions)} planned workbooks "
                f"in {elapsed:.2f}s."
            )
            logger.debug(
                "stats_group_harmonics_project_cache_hit",
                extra={
                    "elapsed_s": elapsed,
                    "subjects": len(subjects),
                    "conditions": len(conditions),
                    "selected_harmonics": _format_harmonic_frequency_list(
                        project_cached.selected_harmonics_hz
                    ),
                },
            )
            _store_group_significant_selection(cache_key, project_cached)
            return project_cached
    log_func(
        "[PERF] Group harmonic selection cache miss: "
        "building selection from FullFFT amplitude spectra."
    )
    logger.debug(
        "stats_group_harmonics_selection_cache_miss",
        extra={"subjects": len(subjects), "conditions": len(conditions)},
    )
    base = float(base_frequency_hz)
    oddball = _resolve_group_oddball_frequency(
        base_frequency_hz=base,
        oddball_frequency_hz=oddball_frequency_hz,
    )
    required = _plan_required_full_fft_columns(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_frequency_hz=base,
        max_freq=max_freq,
        log_func=log_func,
        oddball_frequency_hz=oddball,
        eligible_harmonic_orders=eligible_harmonic_orders,
    )
    planned_workbook_count = _preflight_required_full_fft_columns(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        required=required,
        log_func=log_func,
    )
    log_func(
        "[PERF] Group harmonic selection column plan: "
        f"{len(required.usecols) - 1} FullFFT frequency columns needed "
        f"from {len(required.frequency_columns)} available columns "
        f"across {planned_workbook_count} workbooks."
    )
    logger.debug(
        "stats_group_harmonics_column_plan",
        extra={
            "needed_frequency_columns": len(required.usecols) - 1,
            "available_frequency_columns": len(required.frequency_columns),
            "candidate_indices": len(required.candidate_indices),
        },
    )
    balanced_pool: BalancedHarmonicPool | None = None
    condition_spectra: dict[str, pd.Series] = {}
    analysis_conditions = list(conditions)
    used_electrodes: set[str] = set()
    if settings.harmonic_selection_profile == HARMONIC_PROFILE_LEGACY_ID:
        grand_average, columns, bin_indices, spectra_count, electrode_count = (
            _build_grand_average_amplitude(
                subjects=subjects,
                conditions=conditions,
                subject_data=subject_data,
                rois=rois,
                electrode_scope=settings.group_significant_electrode_scope,
                log_func=log_func,
                frequency_columns=required.frequency_columns,
                required_indices=required.required_indices,
                excluded_electrodes_by_subject=resolved_electrode_exclusions,
                excluded_electrodes_by_subject_condition=(
                    resolved_condition_electrode_exclusions
                ),
                expected_scalp_channels_by_subject_condition=(
                    resolved_expected_scalp_channels
                    if expected_scalp_channels_by_subject_condition is not None
                    else None
                ),
                selection_electrodes=(
                    settings.group_significant_selection_electrodes
                ),
                used_electrodes_out=used_electrodes,
            )
        )
    else:
        (
            balanced_pool,
            columns,
            bin_indices,
            electrode_count,
            used_electrodes,
        ) = _build_balanced_condition_amplitudes(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            rois=rois,
            electrode_scope=settings.group_significant_electrode_scope,
            selection_electrodes=settings.group_significant_selection_electrodes,
            participant_group_ids=resolved_group_ids,
            declared_group_ids=resolved_declared_groups,
            log_func=log_func,
            frequency_columns=required.frequency_columns,
            required_indices=required.required_indices,
            excluded_electrodes_by_subject=resolved_electrode_exclusions,
            excluded_electrodes_by_subject_condition=(
                resolved_condition_electrode_exclusions
            ),
            expected_scalp_channels_by_subject_condition=(
                resolved_expected_scalp_channels
                if expected_scalp_channels_by_subject_condition is not None
                else None
            ),
            recording_assignments=recording_assignments,
            declared_session_ids=declared_session_ids,
        )
        condition_spectra = dict(balanced_pool.condition_spectra)
        analysis_conditions = list(
            balanced_pool.analysis_condition_ids or tuple(conditions)
        )
        grand_average = pd.concat(
            [condition_spectra[condition] for condition in analysis_conditions],
            axis=1,
        ).mean(axis=1, skipna=True).sort_index()
        spectra_count = balanced_pool.workbook_count
    if grand_average.empty:
        raise RuntimeError("Group-level harmonic selection found no usable amplitude spectra.")

    frequency_resolution = _frequency_resolution(
        [freq for freq, _column, _idx in required.frequency_columns]
    )
    amplitude_by_bin = {
        int(bin_idx): float(value)
        for bin_idx, value in zip(bin_indices, grand_average.to_numpy(dtype=float))
        if np.isfinite(value)
    }
    condition_amplitudes_by_bin = {
        str(condition): {
            int(bin_idx): float(value)
            for bin_idx, value in zip(
                bin_indices,
                condition_spectra[str(condition)].to_numpy(dtype=float),
            )
            if np.isfinite(value)
        }
        for condition in analysis_conditions
        if str(condition) in condition_spectra
    }
    selected_bin_indices = set(bin_indices)
    column_by_bin = {
        int(bin_idx): str(column)
        for _freq, column, bin_idx in required.frequency_columns
        if int(bin_idx) in selected_bin_indices
    }
    freq_by_bin = {
        int(bin_idx): float(freq)
        for freq, _column, bin_idx in required.frequency_columns
        if int(bin_idx) in selected_bin_indices
    }
    rows: list[GroupSignificantHarmonicRow] = []
    harmonic_domain: list[float] = []
    detected_freqs: list[float] = []
    detected_columns: list[str] = []
    detected_indices: list[int] = []
    z_by_harmonic: dict[float, float] = {}
    condition_z_by_harmonic: dict[str, dict[float, float | None]] = {
        str(condition): {} for condition in analysis_conditions
    }
    excluded_base: list[float] = []
    seen_indices: set[int] = set()
    require_complete_qc14_window = required.canonical_eligibility_domain

    for matched_idx in required.candidate_indices:
        matched_freq = freq_by_bin.get(int(matched_idx))
        if matched_freq is None:
            continue
        harmonic_index = int(round(matched_freq / oddball))
        target_freq = _canonical_harmonic_frequency_for_index(
            harmonic_index,
            oddball,
        )
        diff = abs(float(matched_freq) - target_freq)
        if diff > GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ:
            rows.append(
                GroupSignificantHarmonicRow(
                    harmonic_index=harmonic_index,
                    target_frequency_hz=_canonical_harmonic_frequency(target_freq),
                    matched_frequency_hz=_canonical_harmonic_frequency(matched_freq),
                    matched_column=None,
                    matched_bin_index=matched_idx,
                    z_score=None,
                    selected=False,
                    excluded_base_rate=False,
                    exclusion_reason="no_full_fft_bin_within_tolerance",
                    warning=(
                        f"Nearest full-spectrum bin differs by {diff:g} Hz, "
                        f"above tolerance {GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ:g} Hz."
                    ),
                )
            )
            continue
        if matched_idx in seen_indices:
            continue
        seen_indices.add(matched_idx)
        matched_column = column_by_bin.get(int(matched_idx), f"{matched_freq:.4f}_Hz")
        is_base_overlap = _is_base_overlap(
            matched_freq,
            base,
            GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ,
        )
        if is_base_overlap:
            excluded_base.append(_canonical_harmonic_frequency(matched_freq))
            rows.append(
                GroupSignificantHarmonicRow(
                    harmonic_index=harmonic_index,
                    target_frequency_hz=_canonical_harmonic_frequency(target_freq),
                    matched_frequency_hz=_canonical_harmonic_frequency(matched_freq),
                    matched_column=matched_column,
                    matched_bin_index=matched_idx,
                    z_score=None,
                    selected=False,
                    excluded_base_rate=True,
                    exclusion_reason="base_rate_overlap",
                    warning="Base-rate overlap excluded from oddball summation.",
                )
            )
            continue

        selected_frequency = _canonical_harmonic_frequency(target_freq)
        noise_stats = _compute_noise_stats_for_planned_bin(
            amplitude_by_bin,
            matched_idx,
            window_size=GROUP_SIGNIFICANT_NOISE_WINDOW_BINS,
            min_bins=4,
            require_complete_window=require_complete_qc14_window,
        )
        target_amp = amplitude_by_bin.get(int(matched_idx), np.nan)
        noise_mean = noise_stats.mean_uv
        noise_std = noise_stats.std_uv
        condition_z_scores: list[tuple[str, float | None]] = []
        if condition_amplitudes_by_bin:
            for condition in analysis_conditions:
                condition_key = str(condition)
                condition_amplitudes = condition_amplitudes_by_bin.get(
                    condition_key,
                    {},
                )
                condition_noise = _compute_noise_stats_for_planned_bin(
                    condition_amplitudes,
                    matched_idx,
                    window_size=GROUP_SIGNIFICANT_NOISE_WINDOW_BINS,
                    min_bins=4,
                    require_complete_window=require_complete_qc14_window,
                )
                condition_target = condition_amplitudes.get(int(matched_idx), np.nan)
                condition_z = (
                    (condition_target - condition_noise.mean_uv) / condition_noise.std_uv
                    if condition_noise.std_uv > 1e-12
                    else np.nan
                )
                condition_value = (
                    float(condition_z) if np.isfinite(condition_z) else None
                )
                condition_z_scores.append((condition_key, condition_value))
                condition_z_by_harmonic[condition_key][selected_frequency] = (
                    condition_value
                )
            finite_condition_z = [
                value for _condition, value in condition_z_scores if value is not None
            ]
            z_value = (
                float(np.mean(finite_condition_z))
                if len(finite_condition_z) == len(analysis_conditions)
                else np.nan
            )
        else:
            z_score = (
                (target_amp - noise_mean) / noise_std
                if noise_std > 1e-12
                else np.nan
            )
            z_value = float(z_score) if np.isfinite(z_score) else np.nan
        noise_bin_indices = noise_stats.candidate_bin_indices
        noise_used_bin_indices = noise_stats.used_bin_indices
        noise_frequencies = tuple(
            float(freq_by_bin[idx])
            for idx in noise_bin_indices
            if idx in freq_by_bin
        )
        noise_amplitudes = tuple(
            float(amplitude_by_bin[idx])
            for idx in noise_bin_indices
            if idx in amplitude_by_bin
        )
        noise_used_frequencies = tuple(
            float(freq_by_bin[idx])
            for idx in noise_used_bin_indices
            if idx in freq_by_bin
        )
        noise_used_amplitudes = tuple(
            float(amplitude_by_bin[idx])
            for idx in noise_used_bin_indices
            if idx in amplitude_by_bin
        )
        harmonic_domain.append(selected_frequency)
        z_by_harmonic[selected_frequency] = z_value
        z_is_defined = bool(np.isfinite(z_value))
        selected = bool(
            z_is_defined and z_value > settings.group_significant_z_threshold
        )
        if selected:
            detected_freqs.append(selected_frequency)
            detected_columns.append(matched_column)
            detected_indices.append(matched_idx)
        rows.append(
            GroupSignificantHarmonicRow(
                harmonic_index=harmonic_index,
                target_frequency_hz=selected_frequency,
                matched_frequency_hz=_canonical_harmonic_frequency(matched_freq),
                matched_column=matched_column,
                matched_bin_index=matched_idx,
                z_score=z_value if np.isfinite(z_value) else None,
                selected=selected,
                excluded_base_rate=False,
                exclusion_reason=(
                    ""
                    if selected
                    else "z_below_threshold"
                    if z_is_defined
                    else "undefined_z_score"
                ),
                warning=(
                    ""
                    if selected
                    else "Z-score did not exceed threshold."
                    if z_is_defined
                    else "Z-score was undefined and cannot be classified."
                ),
                target_amplitude_uv=(
                    float(target_amp)
                    if not condition_amplitudes_by_bin and np.isfinite(target_amp)
                    else None
                ),
                noise_mean_uv=(
                    float(noise_mean)
                    if not condition_amplitudes_by_bin and np.isfinite(noise_mean)
                    else None
                ),
                noise_std_uv=(
                    float(noise_std)
                    if not condition_amplitudes_by_bin and np.isfinite(noise_std)
                    else None
                ),
                noise_bin_indices=(
                    noise_bin_indices if not condition_amplitudes_by_bin else ()
                ),
                noise_frequencies_hz=(
                    noise_frequencies if not condition_amplitudes_by_bin else ()
                ),
                noise_amplitudes_uv=(
                    noise_amplitudes if not condition_amplitudes_by_bin else ()
                ),
                noise_used_bin_indices=(
                    noise_used_bin_indices if not condition_amplitudes_by_bin else ()
                ),
                noise_used_frequencies_hz=(
                    noise_used_frequencies if not condition_amplitudes_by_bin else ()
                ),
                noise_used_amplitudes_uv=(
                    noise_used_amplitudes if not condition_amplitudes_by_bin else ()
                ),
                condition_z_scores=tuple(condition_z_scores),
            )
        )

    two_failure_decision: _TwoConsecutiveFailureDecision | None = None
    if (
        settings.group_significant_summation_method
        == GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES
    ):
        rows, two_failure_decision = _apply_two_failure_evaluation_domain(rows)
        evaluated_rows = [
            row
            for row in rows
            if row.evaluated and not row.excluded_base_rate and row.matched_column
        ]
        harmonic_domain = [
            _canonical_harmonic_frequency(row.target_frequency_hz)
            for row in evaluated_rows
        ]
        evaluated_set = set(harmonic_domain)
        z_by_harmonic = {
            freq: value for freq, value in z_by_harmonic.items() if freq in evaluated_set
        }
        condition_z_by_harmonic = {
            condition: {
                freq: value for freq, value in values.items() if freq in evaluated_set
            }
            for condition, values in condition_z_by_harmonic.items()
        }
        detected_rows = [row for row in evaluated_rows if row.selected]
        detected_freqs = [
            _canonical_harmonic_frequency(row.target_frequency_hz)
            for row in detected_rows
        ]
        detected_columns = [
            str(row.matched_column) for row in detected_rows if row.matched_column
        ]
        detected_indices = [
            int(row.matched_bin_index)
            for row in detected_rows
            if row.matched_bin_index is not None
        ]
        excluded_base = [
            _canonical_harmonic_frequency(row.target_frequency_hz)
            for row in rows
            if row.evaluated and row.excluded_base_rate
        ]
        if not two_failure_decision.stopping_harmonics_hz:
            candidate_summary = _format_candidate_z_summary(rows)
            log_func(
                "Two-consecutive-failures harmonic selection could not establish "
                "a cutoff because technical spectral support ended before two "
                f"consecutive eligible failures. Tested candidates: {candidate_summary}."
            )
            _log_candidate_diagnostics(rows, log_func)
            raise RuntimeError(
                "The Dzhelyova/Poncet two-consecutive-failures profile reached the "
                "end of the canonical filter/Nyquist/neighbor-bin eligibility domain "
                "before its stopping criterion was met. Review the applied filter and "
                "analyzed duration, or choose a fixed/preregistered harmonic profile. "
                f"Tested candidates: {candidate_summary}."
            )

    if not detected_freqs:
        candidate_summary = _format_candidate_z_summary(rows)
        log_func(
            "[PERF] Group harmonic selection found no significant harmonics. "
            f"Threshold z>{settings.group_significant_z_threshold:g}; "
            f"tested candidates: {candidate_summary}."
        )
        _log_candidate_diagnostics(rows, log_func)
        logger.warning(
            "stats_group_harmonics_no_selection",
            extra={
                "z_threshold": settings.group_significant_z_threshold,
                "candidate_summary": candidate_summary,
                "candidate_rows": [
                    {
                        "harmonic_index": row.harmonic_index,
                        "target_frequency_hz": row.target_frequency_hz,
                        "matched_frequency_hz": row.matched_frequency_hz,
                        "z_score": row.z_score,
                        "excluded_base_rate": row.excluded_base_rate,
                        "exclusion_reason": row.exclusion_reason,
                    }
                    for row in rows
                ],
            },
        )
        raise RuntimeError(
            "Group-level significant harmonic selection found no oddball harmonics "
            f"above z>{settings.group_significant_z_threshold:g}. "
            f"Tested candidates: {candidate_summary}. "
            "Use the fixed/predefined policy or inspect the regenerated full-spectrum workbooks."
        )
    selected_freqs, selected_columns, selected_indices, rows = _resolve_summation_harmonics(
        rows=rows,
        detected_freqs=detected_freqs,
        summation_method=settings.group_significant_summation_method,
    )
    gap_guard = _summation_gap_guard_decision(
        rows=rows,
        detected_freqs=detected_freqs,
        summation_method=settings.group_significant_summation_method,
    )
    if gap_guard.applied:
        log_func(
            "Highest-harmonic gap guard applied: excluded the isolated "
            f"{gap_guard.highest_significant_harmonic_hz:g} Hz detection and stopped "
            f"summation at {gap_guard.lower_significant_harmonic_hz:g} Hz because "
            f"{gap_guard.intervening_nonbase_harmonic_count} eligible non-base "
            "harmonics lay between them."
        )
    elapsed = perf_counter() - started
    log_func(
        "[PERF] Group harmonic selection finished: "
        f"{spectra_count} spectra, {electrode_count} electrodes/spectrum max, "
        f"{len(detected_freqs)} significant harmonics, "
        f"{len(selected_freqs)} included harmonics in {elapsed:.2f}s."
    )
    logger.debug(
        "stats_group_harmonics_selection_done",
        extra={
            "elapsed_s": elapsed,
            "spectra_count": spectra_count,
            "selected_harmonics": _format_harmonic_frequency_list(selected_freqs),
            "detected_significant_harmonics": _format_harmonic_frequency_list(
                detected_freqs
            ),
            "summation_gap_guard_applied": gap_guard.applied,
            "summation_gap_guard_intervening_nonbase_harmonic_count": (
                gap_guard.intervening_nonbase_harmonic_count
            ),
            "summation_gap_guard_dropped_highest_significant_harmonic_hz": (
                gap_guard.highest_significant_harmonic_hz
                if gap_guard.applied
                else None
            ),
        },
    )

    if (
        settings.group_significant_summation_method
        == GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES
    ):
        assert two_failure_decision is not None
        stopping_rule = "stop_after_two_consecutive_eligible_z_failures"
        stopping_reason = two_failure_decision.stopping_reason
        stopping_harmonics = two_failure_decision.stopping_harmonics_hz
    elif (
        settings.group_significant_summation_method
        == GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY
    ):
        stopping_rule = "evaluate_prespecified_domain_include_local_z_detections_only"
        stopping_reason = "prespecified_search_domain_evaluated"
        stopping_harmonics = ()
    else:
        stopping_rule = "highest_detected_with_one_pass_gap_guard"
        stopping_reason = (
            "isolated_highest_gap_guard_applied"
            if gap_guard.applied
            else "highest_detected_harmonic"
        )
        stopping_harmonics = ()
    cutoff_harmonic = max(selected_freqs) if selected_freqs else None
    if settings.group_significant_electrode_scope == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN:
        electrode_mask = tuple(settings.group_significant_selection_electrodes)
    elif settings.group_significant_electrode_scope == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION:
        electrode_mask = tuple(
            sorted(
                _wanted_electrodes_for_scope(
                    rois=rois,
                    electrode_scope=settings.group_significant_electrode_scope,
                )
                or (),
            )
        )
    else:
        electrode_mask = tuple(sorted(used_electrodes))
    source_fingerprints = _selection_source_workbook_fingerprints(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        cache_request=cache_request,
    )
    active_recording_assignments = tuple(
        {
            "recording_id": str(recording_id),
            "participant_id": str(row.get("participant_id") or ""),
            "group_id": str(row.get("group_id") or ""),
            "session_id": str(row.get("session_id") or ""),
            "source_id": str(row.get("source_id") or ""),
            "visit_index": _metadata_optional_int(row.get("visit_index")),
            "days_from_baseline": _metadata_optional_float(
                row.get("days_from_baseline")
            ),
        }
        for recording_id in subjects
        for row in ((recording_assignments or {}).get(recording_id),)
        if isinstance(row, Mapping)
    )
    selection_subjects = (
        list(
            dict.fromkeys(
                str(row.get("participant_id") or "")
                for row in active_recording_assignments
                if str(row.get("participant_id") or "")
            )
        )
        if repeated_session
        else list(subjects)
    )
    profile = settings.profile
    selection = GroupSignificantHarmonicSelection(
        harmonic_domain_hz=harmonic_domain,
        selected_harmonics_hz=selected_freqs,
        selected_columns=selected_columns,
        selected_bin_indices=selected_indices,
        detected_significant_harmonics_hz=detected_freqs,
        detected_significant_columns=detected_columns,
        detected_significant_bin_indices=detected_indices,
        z_by_harmonic=z_by_harmonic,
        excluded_base_harmonics_hz=excluded_base,
        oddball_frequency_hz=float(oddball),
        base_frequency_hz=base,
        z_threshold=float(settings.group_significant_z_threshold),
        electrode_scope=str(settings.group_significant_electrode_scope),
        summation_method=str(settings.group_significant_summation_method),
        selection_scope=_selection_scope_label(settings.group_significant_electrode_scope),
        selection_conditions=list(conditions),
        selection_subjects=selection_subjects,
        selection_spectra_count=int(spectra_count),
        selection_electrode_count=int(electrode_count),
        frequency_resolution_hz=frequency_resolution,
        base_overlap_tolerance_hz=GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ,
        matching_tolerance_hz=GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ,
        noise_window_bins=GROUP_SIGNIFICANT_NOISE_WINDOW_BINS,
        rows=rows,
        method_profile_id=profile.method_id,
        method_profile_version=profile.version,
        method_profile_label=profile.label,
        method_citation=profile.citation,
        same_sample_adaptive=profile.same_sample,
        pooling_method=(
            REPEATED_SESSION_POOLING_METHOD_VERSION
            if repeated_session
            and settings.harmonic_selection_profile != HARMONIC_PROFILE_LEGACY_ID
            else profile.pooling_method
        ),
        pooling_cells=(balanced_pool.cells if balanced_pool is not None else ()),
        declared_group_ids=(
            balanced_pool.declared_group_ids if balanced_pool is not None else ()
        ),
        condition_z_by_harmonic=condition_z_by_harmonic,
        selection_electrode_mask=electrode_mask,
        stopping_rule=stopping_rule,
        stopping_reason=stopping_reason,
        stopping_harmonics_hz=tuple(stopping_harmonics),
        cutoff_harmonic_hz=cutoff_harmonic,
        source_workbook_fingerprints=source_fingerprints,
        declared_session_ids=(
            balanced_pool.declared_session_ids
            if balanced_pool is not None
            else tuple(str(value) for value in (declared_session_ids or ()))
        ),
        analysis_condition_ids=(
            balanced_pool.analysis_condition_ids
            if balanced_pool is not None and balanced_pool.is_repeated_session
            else ()
        ),
        recording_assignments=active_recording_assignments,
        eligible_harmonic_orders=_normalize_eligible_harmonic_orders(
            eligible_harmonic_orders,
            allow_unspecified=True,
        ),
        spectral_eligibility_method_version=(
            SPECTRAL_ELIGIBILITY_METHOD_VERSION
            if eligible_harmonic_orders is not None
            else None
        ),
        spectral_eligibility_fingerprint=(
            str(spectral_eligibility_fingerprint).strip()
            if spectral_eligibility_fingerprint
            else None
        ),
    )
    selection = replace(
        selection,
        selection_fingerprint=str(selection.to_metadata()["selection_fingerprint"]),
    )
    selection = _save_project_cached_selection(cache_request, selection, log_func)
    _store_group_significant_selection(cache_key, selection)
    return selection


def _selection_scope_label(electrode_scope: str) -> str:
    if electrode_scope == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION:
        return "group_level_union_roi_electrodes_all_selected_conditions"
    if electrode_scope == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN:
        return "group_level_frozen_selection_electrodes_all_selected_conditions"
    return "group_level_all_scalp_electrodes_all_selected_conditions"


def _selection_source_workbook_fingerprints(
    *,
    subjects: Sequence[str],
    conditions: Sequence[str],
    subject_data: Mapping[str, Mapping[str, str]],
    cache_request: GroupHarmonicCacheRequest | None,
) -> tuple[dict[str, object], ...]:
    if cache_request is not None:
        raw = cache_request.fingerprint.get("source_workbooks")
        if isinstance(raw, list):
            return tuple(dict(item) for item in raw if isinstance(item, Mapping))
    return tuple(
        {
            "subject": signature.subject,
            "condition": signature.condition,
            "path": signature.path,
            "size_bytes": signature.size_bytes,
            "mtime_ns": signature.mtime_ns,
            **(
                {"spectral_companion": json.loads(signature.spectral_companion_json)}
                if signature.spectral_companion_json is not None
                else {}
            ),
            **(
                {"condition_companion": json.loads(signature.condition_companion_json)}
                if signature.condition_companion_json is not None
                else {}
            ),
        }
        for subject in subjects
        for condition in conditions
        for signature in (
            _workbook_signature(
                subject=str(subject),
                condition=str(condition),
                file_path=(subject_data.get(str(subject), {}) or {}).get(str(condition)),
            ),
        )
    )


def _resolve_summation_harmonics(
    *,
    rows: list[GroupSignificantHarmonicRow],
    detected_freqs: list[float],
    summation_method: str,
) -> tuple[list[float], list[str], list[int], list[GroupSignificantHarmonicRow]]:
    """Return the harmonic list included in Summed BCA for the selected policy."""
    detected_set = {_canonical_harmonic_frequency(freq) for freq in detected_freqs}
    if summation_method == GROUP_SIGNIFICANT_SUMMATION_SIGNIFICANT_ONLY:
        included_set = set(detected_set)
    elif summation_method == GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES:
        decision = _two_consecutive_failure_decision(rows)
        included_set = {
            _canonical_harmonic_frequency(row.target_frequency_hz)
            for row in rows
            if _is_summation_eligible(row)
            and decision.cutoff_harmonic_index is not None
            and row.harmonic_index <= decision.cutoff_harmonic_index
        }
    else:
        gap_guard = _summation_gap_guard_decision(
            rows=rows,
            detected_freqs=detected_freqs,
            summation_method=summation_method,
        )
        cutoff_index = gap_guard.retained_cutoff_harmonic_index
        included_set = {
            _canonical_harmonic_frequency(row.target_frequency_hz)
            for row in rows
            if _is_summation_eligible(row)
            and cutoff_index is not None
            and row.harmonic_index <= cutoff_index
        }

    updated_rows = [
        replace(
            row,
            included_in_summation=_canonical_harmonic_frequency(row.target_frequency_hz)
            in included_set,
        )
        for row in rows
    ]
    included_rows = [
        row
        for row in sorted(updated_rows, key=lambda item: (item.harmonic_index, item.target_frequency_hz))
        if row.included_in_summation
        and row.matched_column
        and row.matched_bin_index is not None
    ]
    included_freqs = [
        _canonical_harmonic_frequency(row.target_frequency_hz) for row in included_rows
    ]
    included_columns = [str(row.matched_column) for row in included_rows]
    included_indices = [int(row.matched_bin_index) for row in included_rows]
    return included_freqs, included_columns, included_indices, updated_rows


def _two_consecutive_failure_decision(
    rows: Sequence[GroupSignificantHarmonicRow],
) -> _TwoConsecutiveFailureDecision:
    eligible = [
        row
        for row in sorted(rows, key=lambda item: (item.harmonic_index, item.target_frequency_hz))
        if row.evaluated
        and not row.excluded_base_rate
        and row.matched_column
        and row.matched_bin_index is not None
    ]
    consecutive_failures: list[GroupSignificantHarmonicRow] = []
    evaluated: list[GroupSignificantHarmonicRow] = []
    for row in eligible:
        if row.z_score is None or not np.isfinite(row.z_score):
            undefined_conditions = [
                condition
                for condition, value in row.condition_z_scores
                if value is None or not np.isfinite(value)
            ]
            condition_text = (
                " Missing/undefined condition Z values: "
                + ", ".join(undefined_conditions)
                + "."
                if undefined_conditions
                else ""
            )
            raise RuntimeError(
                "The Dzhelyova/Poncet two-consecutive-failures profile cannot "
                f"classify {row.target_frequency_hz:g} Hz because its Z-score is "
                "undefined; an undefined value is not a nonsignificant failure."
                f"{condition_text} Ensure every condition has a common FFT grid, "
                "finite target/noise amplitudes, enough neighboring noise bins, "
                "and non-zero local noise SD; regenerate the frequency-domain "
                "workbooks or choose a fixed/preregistered harmonic profile."
            )
        evaluated.append(row)
        if row.selected:
            consecutive_failures.clear()
            continue
        consecutive_failures.append(row)
        if len(consecutive_failures) < 2:
            continue
        first_failure = consecutive_failures[-2]
        first_position = evaluated.index(first_failure)
        cutoff = (
            int(evaluated[first_position - 1].harmonic_index)
            if first_position > 0
            else None
        )
        return _TwoConsecutiveFailureDecision(
            cutoff_harmonic_index=cutoff,
            evaluated_harmonic_indices=tuple(
                int(candidate.harmonic_index) for candidate in evaluated
            ),
            stopping_harmonics_hz=tuple(
                _canonical_harmonic_frequency(candidate.target_frequency_hz)
                for candidate in consecutive_failures[-2:]
            ),
            stopping_reason="two_consecutive_eligible_harmonics_at_or_below_threshold",
        )
    return _TwoConsecutiveFailureDecision(
        cutoff_harmonic_index=(int(evaluated[-1].harmonic_index) if evaluated else None),
        evaluated_harmonic_indices=tuple(
            int(candidate.harmonic_index) for candidate in evaluated
        ),
        stopping_harmonics_hz=(),
        stopping_reason="search_domain_exhausted_before_two_consecutive_failures",
    )


def _apply_two_failure_evaluation_domain(
    rows: list[GroupSignificantHarmonicRow],
) -> tuple[list[GroupSignificantHarmonicRow], _TwoConsecutiveFailureDecision]:
    decision = _two_consecutive_failure_decision(rows)
    evaluated_indices = set(decision.evaluated_harmonic_indices)
    if not decision.stopping_harmonics_hz:
        return rows, decision
    highest_evaluated = max(evaluated_indices, default=0)
    updated: list[GroupSignificantHarmonicRow] = []
    for row in rows:
        if row.harmonic_index <= highest_evaluated:
            updated.append(row)
            continue
        updated.append(
            replace(
                row,
                evaluated=False,
                selected=False,
                exclusion_reason="not_evaluated_after_stopping_rule",
                warning="Not evaluated after two consecutive eligible failures.",
                included_in_summation=False,
            )
        )
    return updated, decision


def _summation_gap_guard_decision(
    *,
    rows: Sequence[GroupSignificantHarmonicRow],
    detected_freqs: Sequence[float],
    summation_method: str,
) -> _SummationGapGuardDecision:
    """Apply the one-pass isolated-highest guard to the through-highest rule."""

    enabled = summation_method == GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST
    detected_set = {
        _canonical_harmonic_frequency(freq)
        for freq in detected_freqs
    }
    detected_rows_by_index = {
        int(row.harmonic_index): row
        for row in rows
        if _is_summation_eligible(row)
        and _canonical_harmonic_frequency(row.target_frequency_hz) in detected_set
    }
    detected_rows = [
        detected_rows_by_index[index]
        for index in sorted(detected_rows_by_index)
    ]
    if not detected_rows:
        return _SummationGapGuardDecision(
            enabled=enabled,
            applied=False,
            intervening_nonbase_harmonic_count=0,
            lower_significant_harmonic_hz=None,
            highest_significant_harmonic_hz=None,
            retained_cutoff_harmonic_index=None,
        )

    highest = detected_rows[-1]
    if len(detected_rows) < 2:
        return _SummationGapGuardDecision(
            enabled=enabled,
            applied=False,
            intervening_nonbase_harmonic_count=0,
            lower_significant_harmonic_hz=None,
            highest_significant_harmonic_hz=_canonical_harmonic_frequency(
                highest.target_frequency_hz
            ),
            retained_cutoff_harmonic_index=int(highest.harmonic_index),
        )

    lower = detected_rows[-2]
    intervening_indices = {
        int(row.harmonic_index)
        for row in rows
        if _is_summation_eligible(row)
        and int(lower.harmonic_index) < int(row.harmonic_index) < int(highest.harmonic_index)
    }
    intervening_count = len(intervening_indices)
    applied = bool(
        enabled
        and intervening_count > GROUP_SIGNIFICANT_MAX_INTERVENING_NONBASE_HARMONICS
    )
    return _SummationGapGuardDecision(
        enabled=enabled,
        applied=applied,
        intervening_nonbase_harmonic_count=intervening_count,
        lower_significant_harmonic_hz=_canonical_harmonic_frequency(
            lower.target_frequency_hz
        ),
        highest_significant_harmonic_hz=_canonical_harmonic_frequency(
            highest.target_frequency_hz
        ),
        retained_cutoff_harmonic_index=int(
            lower.harmonic_index if applied else highest.harmonic_index
        ),
    )


def _is_summation_eligible(row: GroupSignificantHarmonicRow) -> bool:
    return bool(
        row.evaluated
        and not row.excluded_base_rate
        and row.matched_column
        and row.matched_bin_index is not None
    )


def _prepare_group_significant_bca_data(
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
    project_root: str | Path | None = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None
    electrode_exclusions_by_subject: dict[str, frozenset[str]] = {}
    final_coverage = None
    if project_root not in (None, ""):
        from Main_App.processing.frequency_domain_qc import (
            active_frequency_domain_exclusions,
            filter_frequency_domain_subjects,
        )

        subjects, subject_data, frequency_excluded = filter_frequency_domain_subjects(
            project_root,
            subjects,
            subject_data,
        )
        if frequency_excluded:
            log_func(
                "Frequency-domain participant exclusions applied before Summed BCA: "
                + ", ".join(frequency_excluded)
            )
        electrode_exclusions_by_subject = (
            active_frequency_domain_exclusions(
                project_root
            ).auto_excluded_electrodes_by_participant
        )
        from Main_App.processing.roi_coverage import require_project_final_release

        _outcomes, final_coverage, _receipt = require_project_final_release(
            project_root
        )

    rois_map = rois if rois is not None else _current_rois_map()
    if not rois_map:
        log_func("No ROIs defined or available.")
        return None
    if final_coverage is not None:
        frozen_rois = {
            roi.name: list(roi.electrodes)
            for roi in final_coverage.roi_snapshot.rois
        }
        normalized_rois = build_roi_definition_snapshot(rois_map).as_mapping()
        if normalized_rois != frozen_rois:
            raise RuntimeError(
                "Group Summed BCA ROI definitions differ from the current frozen "
                "QC-21 snapshot. Rerun post-processing."
            )
        rois_map = normalized_rois

    coverage_cells: dict[tuple[str, str], object] = {}
    released_subject_data: dict[str, dict[str, str]] = {}
    if final_coverage is not None:
        for pid in subjects:
            for cond_name in conditions:
                coverage_cell = final_coverage.cell_for(pid, cond_name)
                if coverage_cell is None:
                    raise RuntimeError(
                        "Group Summed BCA lacks final QC-21 coverage for "
                        f"{pid}/{cond_name}."
                    )
                coverage_cells[(str(pid).casefold(), str(cond_name).casefold())] = (
                    coverage_cell
                )
                if (
                    coverage_cell.source_evidence is None
                    or coverage_cell.downstream_cell_excluded
                ):
                    continue
                released_subject_data.setdefault(pid, {})[cond_name] = (
                    _require_matching_coverage_workbook(
                        coverage_cell,
                        subject_data.get(pid, {}).get(cond_name),
                        context="Group Summed BCA",
                    )
                )

    started = perf_counter()
    if project_root in (None, ""):
        raise RuntimeError(
            "Group-significant harmonics must be loaded from processing-time project "
            "metadata. Reprocess the project, then run Stats from the project GUI."
        )

    from Main_App.processing.harmonic_selection_qc import (
        load_processing_harmonic_selection,
    )
    from Main_App.projects.project import Project

    selection = load_processing_harmonic_selection(
        Project.load(Path(project_root)),
        log_func=log_func,
    )
    log_func(
        "Group-level significant harmonics detected: "
        + ", ".join(f"{freq:g} Hz" for freq in selection.detected_significant_harmonics_hz)
    )
    log_func(
        "Harmonics included in Summed BCA: "
        + ", ".join(f"{freq:g} Hz" for freq in selection.selected_harmonics_hz)
    )
    highest_meta = _highest_selected_harmonic_metadata(
        selection.detected_significant_harmonics_hz,
        oddball_hz=selection.oddball_frequency_hz,
        prefix="highest_significant_harmonic",
    )
    highest_hz = highest_meta.get("highest_significant_harmonic_hz")
    highest_index = highest_meta.get("highest_significant_harmonic_index")
    if highest_hz is not None and np.isfinite(float(highest_hz)):
        if highest_index is not None:
            log_func(
                "Highest significant oddball harmonic: "
                f"{float(highest_hz):g} Hz (index {int(highest_index)})."
            )
        else:
            log_func(f"Highest significant oddball harmonic: {float(highest_hz):g} Hz.")

    log_func(
        "[PERF] Group harmonic selection phase complete in "
        f"{perf_counter() - started:.2f}s."
    )

    bca_started = perf_counter()
    all_subject_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    bca_tasks = [
        (pid, cond_name, subject_data.get(pid, {}).get(cond_name))
        for pid in subjects
        for cond_name in conditions
    ]
    total_bca_tasks = len(bca_tasks)
    log_func(
        "[PERF] Group policy BCA aggregation started: "
        f"{total_bca_tasks} workbook reads across {len(rois_map)} ROIs."
    )
    for task_index, (pid, cond_name, file_path) in enumerate(bca_tasks, start=1):
        all_subject_data.setdefault(pid, {})
        all_subject_data[pid].setdefault(cond_name, {})
        read_started = perf_counter()
        coverage_cell = coverage_cells.get(
            (str(pid).casefold(), str(cond_name).casefold())
        )
        if final_coverage is not None and coverage_cell is not None:
            if (
                coverage_cell.source_evidence is None
                or coverage_cell.downstream_cell_excluded
            ):
                roi_values = {roi_name: np.nan for roi_name in rois_map}
                roi_provenance = _unavailable_coverage_provenance(
                    coverage_cell,
                    rois=rois_map,
                    selected_columns=list(selection.selected_columns),
                )
                log_func(
                    "Group Summed BCA did not read an unavailable released cell: "
                    f"{pid}/{cond_name}."
                )
                for roi_name in rois_map:
                    all_subject_data[pid][cond_name][roi_name] = np.nan
                    if provenance_map is not None:
                        provenance_map[(pid, cond_name, roi_name)] = (
                            roi_provenance[roi_name]
                        )
                continue
            file_path = released_subject_data[pid][cond_name]
        cell_exclusions = electrode_exclusions_by_subject.get(
            str(pid).upper(),
            frozenset(),
        )
        if final_coverage is not None:
            if (
                coverage_cell is None
                or coverage_cell.source_evidence is None
                or coverage_cell.whole_scalp_normalization is None
            ):
                raise RuntimeError(
                    "Group Summed BCA lacks final QC-21 coverage for "
                    f"{pid}/{cond_name}."
                )
            cell_exclusions = frozenset(
                coverage_cell.whole_scalp_normalization.excluded_channels
            )
        roi_values, roi_provenance = _aggregate_bca_for_all_rois(
            file_path=file_path,
            rois=rois_map,
            log_func=log_func,
            harmonic_freqs=list(selection.selected_harmonics_hz),
            provenance_enabled=provenance_map is not None,
            excluded_electrodes_upper=cell_exclusions,
            strict_source=final_coverage is not None,
        )
        read_elapsed = perf_counter() - read_started
        for roi_name in rois_map.keys():
            all_subject_data[pid][cond_name][roi_name] = roi_values.get(roi_name, np.nan)
            if provenance_map is not None:
                provenance = roi_provenance.get(
                    roi_name,
                    {
                        "source_file": file_path,
                        "sheet": "BCA (uV)",
                        "row_label": None,
                        "col_label": list(selection.selected_columns),
                        "raw_cell": None,
                        "harmonic_policy": GROUP_SIGNIFICANT_POLICY_ID,
                    },
                )
                provenance["harmonic_policy"] = GROUP_SIGNIFICANT_POLICY_ID
                provenance_map[(pid, cond_name, roi_name)] = provenance
        if _should_log_progress(
            task_index,
            total_bca_tasks,
            GROUP_SIGNIFICANT_BCA_PROGRESS_INTERVAL,
        ):
            elapsed = perf_counter() - bca_started
            log_func(
                "[PERF] Group policy BCA aggregation progress: "
                f"{task_index}/{total_bca_tasks} workbooks "
                f"(participant={pid}, condition={cond_name}, "
                f"last_read={read_elapsed:.2f}s, elapsed={elapsed:.2f}s)."
            )
            logger.debug(
                "stats_group_harmonics_bca_progress",
                extra={
                    "index": task_index,
                    "total": total_bca_tasks,
                    "participant": pid,
                    "condition": cond_name,
                    "last_read_s": read_elapsed,
                    "elapsed_s": elapsed,
                },
            )
    log_func(
        "[PERF] Group policy BCA aggregation finished: "
        f"{len(subjects) * len(conditions)} workbook reads for "
        f"{len(rois_map)} ROIs in {perf_counter() - bca_started:.2f}s."
    )

    if dv_metadata is not None:
        dv_metadata.update(
            settings.to_metadata(base_freq=base_freq, selected_conditions=conditions)
        )
        dv_metadata["policy_name"] = GROUP_SIGNIFICANT_POLICY_NAME
        dv_metadata["group_significant_harmonics"] = selection.to_metadata()

    total = 0
    finite = 0
    for _pid, conds in all_subject_data.items():
        for _cond, rois_dict in conds.items():
            for _roi, val in rois_dict.items():
                total += 1
                if val is not None and np.isfinite(val):
                    finite += 1
    log_func(f"[DEBUG] Summed BCA finite cells: {finite}/{total}")
    log_func(f"Summed BCA data prep complete in {perf_counter() - started:.2f}s.")
    return all_subject_data


def _build_grand_average_amplitude(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    rois: Dict[str, List[str]],
    electrode_scope: str,
    log_func: Callable[[str], None],
    frequency_columns: list[tuple[float, str, int]],
    required_indices: list[int],
    excluded_electrodes_by_subject: Mapping[str, frozenset[str]] | None = None,
    excluded_electrodes_by_subject_condition: Mapping[
        tuple[str, str], frozenset[str]
    ]
    | None = None,
    expected_scalp_channels_by_subject_condition: Mapping[
        tuple[str, str], Sequence[str]
    ]
    | None = None,
    selection_electrodes: Sequence[str] = (),
    used_electrodes_out: set[str] | None = None,
) -> tuple[pd.Series, list[str], list[int], int, int]:
    started = perf_counter()
    spectra: list[pd.Series] = []
    columns: list[str] = []
    bin_indices: list[int] = []
    electrode_count = 0
    read_elapsed = 0.0
    max_frequency_columns_read = 0
    fft_tasks = [
        (pid, cond_name, subject_data.get(pid, {}).get(cond_name))
        for pid in subjects
        for cond_name in conditions
    ]
    total_fft_tasks = len(fft_tasks)
    log_func(
        "[PERF] FullFFT grand-average read started: "
        f"{total_fft_tasks} workbook reads; "
        f"{len(required_indices)} planned frequency columns per reference grid."
    )
    for task_index, (pid, cond_name, file_path) in enumerate(fft_tasks, start=1):
        cell_key = (str(pid).upper(), str(cond_name).casefold())
        if not file_path or not Path(file_path).exists():
            if (
                expected_scalp_channels_by_subject_condition is not None
                and cell_key in expected_scalp_channels_by_subject_condition
            ):
                raise RuntimeError(
                    f"Released harmonic-selection workbook is missing for {pid}/{cond_name}."
                )
            log_func(f"Missing file for {pid} {cond_name}: {file_path}")
            continue
        expected_scalp_channels = (
            expected_scalp_channels_by_subject_condition or {}
        ).get(cell_key)
        if expected_scalp_channels_by_subject_condition is not None and (
            cell_key not in expected_scalp_channels_by_subject_condition
        ):
            raise RuntimeError(
                "Harmonic selection lacks released QC-21 source membership for "
                f"{pid}/{cond_name}."
            )
        read_started = perf_counter()
        cell_exclusions = (
            excluded_electrodes_by_subject_condition or {}
        ).get(
            (str(pid).upper(), str(cond_name).casefold()),
            (excluded_electrodes_by_subject or {}).get(
                str(pid).upper(),
                frozenset(),
            ),
        )
        series, file_columns, n_electrodes = _load_mean_amplitude_series(
            file_path,
            rois=rois,
            electrode_scope=electrode_scope,
            reference_frequency_columns=frequency_columns,
            required_indices=required_indices,
            excluded_electrodes_upper=cell_exclusions,
            expected_scalp_channels=expected_scalp_channels,
            selection_electrodes=selection_electrodes,
            used_electrodes_out=used_electrodes_out,
        )
        file_read_elapsed = perf_counter() - read_started
        read_elapsed += file_read_elapsed
        if series.empty:
            log_func(f"No usable full-spectrum amplitude data for {pid} {cond_name}.")
            continue
        spectra.append(series)
        max_frequency_columns_read = max(max_frequency_columns_read, len(file_columns))
        if not columns:
            columns = file_columns
            bin_lookup = {column: int(idx) for _freq, column, idx in frequency_columns}
            bin_indices = [bin_lookup[column] for column in file_columns if column in bin_lookup]
        electrode_count = max(electrode_count, int(n_electrodes))
        if _should_log_progress(
            task_index,
            total_fft_tasks,
            GROUP_SIGNIFICANT_FULLFFT_PROGRESS_INTERVAL,
        ):
            elapsed = perf_counter() - started
            log_func(
                "[PERF] FullFFT grand-average read progress: "
                f"{task_index}/{total_fft_tasks} workbooks "
                f"(participant={pid}, condition={cond_name}, "
                f"columns={len(file_columns)}, electrodes={n_electrodes}, "
                f"spectra={len(spectra)}, last_read={file_read_elapsed:.2f}s, "
                f"elapsed={elapsed:.2f}s)."
            )
            logger.debug(
                "stats_group_harmonics_fullfft_progress",
                extra={
                    "index": task_index,
                    "total": total_fft_tasks,
                    "participant": pid,
                    "condition": cond_name,
                    "columns": len(file_columns),
                    "electrodes": n_electrodes,
                    "spectra_count": len(spectra),
                    "last_read_s": file_read_elapsed,
                    "elapsed_s": elapsed,
                },
            )

    if not spectra:
        raise RuntimeError(
            "Group-level significant harmonic selection requires workbooks with a "
            f"'{FULL_FFT_AMPLITUDE_SHEET_NAME}' sheet for included participants and conditions."
        )
    frame = pd.concat(spectra, axis=1)
    grand_average = frame.mean(axis=1, skipna=True).sort_index()
    columns = [f"{float(freq):.4f}_Hz" for freq in grand_average.index]
    bin_lookup = {column: idx for _freq, column, idx in frequency_columns}
    bin_indices = [int(bin_lookup[column]) for column in columns if column in bin_lookup]
    elapsed = perf_counter() - started
    log_func(
        "[PERF] FullFFT grand-average read: "
        f"{len(spectra)} workbooks x up to {max_frequency_columns_read} frequency columns "
        f"in {elapsed:.2f}s (read phase {read_elapsed:.2f}s)."
    )
    logger.debug(
        "stats_group_harmonics_fullfft_read_done",
        extra={
            "elapsed_s": elapsed,
            "read_elapsed_s": read_elapsed,
            "spectra_count": len(spectra),
            "frequency_columns": max_frequency_columns_read,
        },
    )
    return grand_average, columns, bin_indices, len(spectra), electrode_count


def _build_balanced_condition_amplitudes(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    rois: Dict[str, List[str]],
    electrode_scope: str,
    selection_electrodes: Sequence[str],
    participant_group_ids: Mapping[str, str],
    declared_group_ids: Sequence[str],
    log_func: Callable[[str], None],
    frequency_columns: list[tuple[float, str, int]],
    required_indices: list[int],
    excluded_electrodes_by_subject: Mapping[str, frozenset[str]] | None = None,
    excluded_electrodes_by_subject_condition: Mapping[
        tuple[str, str], frozenset[str]
    ]
    | None = None,
    expected_scalp_channels_by_subject_condition: Mapping[
        tuple[str, str], Sequence[str]
    ]
    | None = None,
    recording_assignments: Mapping[str, Mapping[str, object]] | None = None,
    declared_session_ids: Sequence[str] | None = None,
) -> tuple[BalancedHarmonicPool, list[str], list[int], int, set[str]]:
    """Read participant spectra and apply the declared balanced estimand."""

    started = perf_counter()
    spectra: dict[tuple[str, str], pd.Series] = {}
    electrode_count = 0
    used_electrodes: set[str] = set()
    read_elapsed = 0.0
    fft_tasks = [
        (str(pid), str(condition), subject_data.get(pid, {}).get(condition))
        for pid in subjects
        for condition in conditions
    ]
    log_func(
        "[PERF] Balanced FullFFT pooling started: "
        f"{len(fft_tasks)} planned workbook reads."
    )
    for task_index, (pid, condition, file_path) in enumerate(fft_tasks, start=1):
        cell_key = (pid.upper(), condition.casefold())
        if not file_path or not Path(file_path).exists():
            if (
                expected_scalp_channels_by_subject_condition is not None
                and cell_key in expected_scalp_channels_by_subject_condition
            ):
                raise RuntimeError(
                    f"Released harmonic-selection workbook is missing for {pid}/{condition}."
                )
            log_func(f"Missing file for {pid} {condition}: {file_path}")
            continue
        expected_scalp_channels = (
            expected_scalp_channels_by_subject_condition or {}
        ).get(cell_key)
        if expected_scalp_channels_by_subject_condition is not None and (
            cell_key not in expected_scalp_channels_by_subject_condition
        ):
            raise RuntimeError(
                "Harmonic selection lacks released QC-21 source membership for "
                f"{pid}/{condition}."
            )
        read_started = perf_counter()
        cell_exclusions = (
            excluded_electrodes_by_subject_condition or {}
        ).get(
            (pid.upper(), condition.casefold()),
            (excluded_electrodes_by_subject or {}).get(
                pid.upper(),
                frozenset(),
            ),
        )
        series, _file_columns, n_electrodes = _load_mean_amplitude_series(
            file_path,
            rois=rois,
            electrode_scope=electrode_scope,
            reference_frequency_columns=frequency_columns,
            required_indices=required_indices,
            excluded_electrodes_upper=cell_exclusions,
            expected_scalp_channels=expected_scalp_channels,
            selection_electrodes=selection_electrodes,
            used_electrodes_out=used_electrodes,
        )
        file_read_elapsed = perf_counter() - read_started
        read_elapsed += file_read_elapsed
        if series.empty:
            log_func(f"No usable full-spectrum amplitude data for {pid} {condition}.")
            continue
        spectra[(pid, condition)] = series
        electrode_count = max(electrode_count, int(n_electrodes))
        if _should_log_progress(
            task_index,
            len(fft_tasks),
            GROUP_SIGNIFICANT_FULLFFT_PROGRESS_INTERVAL,
        ):
            log_func(
                "[PERF] Balanced FullFFT pooling progress: "
                f"{task_index}/{len(fft_tasks)} workbooks "
                f"(participant={pid}, condition={condition}, "
                f"electrodes={n_electrodes}, elapsed={perf_counter() - started:.2f}s)."
            )

    if recording_assignments:
        pool = pool_group_session_condition_spectra(
            spectra=spectra,
            recording_ids=subjects,
            conditions=conditions,
            recording_participant_ids={
                str(recording_id): str(row.get("participant_id") or "")
                for recording_id, row in recording_assignments.items()
            },
            recording_session_ids={
                str(recording_id): str(row.get("session_id") or "")
                for recording_id, row in recording_assignments.items()
            },
            participant_group_ids=participant_group_ids,
            declared_group_ids=declared_group_ids,
            declared_session_ids=tuple(declared_session_ids or ()),
        )
    else:
        pool = pool_group_condition_spectra(
            spectra=spectra,
            subjects=subjects,
            conditions=conditions,
            participant_group_ids=participant_group_ids,
            declared_group_ids=declared_group_ids,
        )
    if not pool.condition_spectra:
        raise RuntimeError("Balanced harmonic selection found no usable condition spectra.")
    first_spectrum = next(iter(pool.condition_spectra.values()))
    columns = [f"{float(freq):.4f}_Hz" for freq in first_spectrum.index]
    bin_lookup = {str(column): int(idx) for _freq, column, idx in frequency_columns}
    bin_indices = [bin_lookup[column] for column in columns if column in bin_lookup]
    log_func(
        "[PERF] Balanced FullFFT pooling finished: "
        f"{pool.workbook_count} participant-condition spectra, "
        f"{len(pool.cells)} complete group x "
        + ("session x " if pool.is_repeated_session else "")
        + "condition cells in "
        f"{perf_counter() - started:.2f}s (read phase {read_elapsed:.2f}s)."
    )
    return pool, columns, bin_indices, electrode_count, used_electrodes


def _plan_required_full_fft_columns(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_frequency_hz: float,
    max_freq: float | None,
    log_func: Callable[[str], None],
    oddball_frequency_hz: float | None = None,
    eligible_harmonic_orders: Sequence[int] | None = None,
) -> RequiredFullFftColumns:
    started = perf_counter()
    base = float(base_frequency_hz)
    oddball = _resolve_group_oddball_frequency(
        base_frequency_hz=base,
        oddball_frequency_hz=oddball_frequency_hz,
    )
    header_columns = _find_first_full_fft_columns(subjects, conditions, subject_data)
    frequency_columns = _parse_frequency_columns(header_columns)
    if not frequency_columns:
        raise RuntimeError(
            "Group-level significant harmonic selection found no frequency columns "
            f"in '{FULL_FFT_AMPLITUDE_SHEET_NAME}'."
        )

    freq_axis = np.asarray([freq for freq, _column, _idx in frequency_columns], dtype=float)
    canonical_orders = _normalize_eligible_harmonic_orders(
        eligible_harmonic_orders,
        allow_unspecified=True,
    )
    canonical_domain = eligible_harmonic_orders is not None
    if canonical_domain:
        if not canonical_orders:
            raise RuntimeError(
                "Canonical spectral eligibility contains no harmonics available for "
                "standard local-Z selection. Regenerate the workbooks and inspect "
                "their Spectral Eligibility sheets."
            )
        harmonic_orders: Sequence[int] = canonical_orders
    else:
        max_limit = (
            float(max_freq) if max_freq is not None else float(np.nanmax(freq_axis))
        )
        highest_k = int(np.floor(max_limit / oddball))
        harmonic_orders = range(1, highest_k + 1)
    candidate_indices: list[int] = []
    excluded_base_indices: list[int] = []
    required_indices: set[int] = set()
    all_indices = {int(idx) for _freq, _column, idx in frequency_columns}

    for harmonic_index in harmonic_orders:
        target_freq = _canonical_harmonic_frequency_for_index(
            harmonic_index,
            oddball,
        )
        exact_match = _find_exact_frequency_column(frequency_columns, target_freq)
        if exact_match is None:
            if canonical_domain:
                raise RuntimeError(
                    "A harmonic declared eligible by the canonical spectral resolver "
                    f"has no exact FullFFT column ({target_freq:g} Hz, oddball "
                    f"harmonic {harmonic_index}). Regenerate the frequency-domain "
                    "workbook; nearest-bin substitution is disabled."
                )
            continue
        matched_freq, _column, matched_idx = exact_match
        candidate_indices.append(int(matched_idx))
        required_indices.add(int(matched_idx))
        if _is_base_overlap(matched_freq, base, GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ):
            excluded_base_indices.append(int(matched_idx))
            continue
        noise_indices = _noise_indices_for_bin(
            int(matched_idx),
            available_indices=all_indices,
            window_size=GROUP_SIGNIFICANT_NOISE_WINDOW_BINS,
        )
        if canonical_domain and len(noise_indices) != len(QC14_NOISE_CANDIDATE_OFFSETS):
            raise RuntimeError(
                "A harmonic declared eligible by the canonical spectral resolver "
                f"does not have its complete +/-10-bin FullFFT neighborhood "
                f"({target_freq:g} Hz). Regenerate the frequency-domain workbook."
            )
        for noise_idx in noise_indices:
            required_indices.add(int(noise_idx))

    if not candidate_indices:
        raise RuntimeError(
            "Group-level significant harmonic selection requires exact nominal "
            "oddball harmonic columns in the FullFFT sheet. Regenerate workbooks "
            "with FFT crop/on-bin output; fixed-epoch fallback workbooks cannot "
            "be used for this selection method."
        )

    column_by_idx = {int(idx): str(column) for _freq, column, idx in frequency_columns}
    ordered_columns = [
        column_by_idx[idx]
        for idx in sorted(required_indices)
        if idx in column_by_idx
    ]
    usecols = ["Electrode", *ordered_columns]
    log_func(
        "[PERF] FullFFT required-column plan built in "
        f"{perf_counter() - started:.2f}s: "
        f"{len(candidate_indices)} candidate oddball bins, "
        f"{len(ordered_columns)} frequency columns to read."
    )
    return RequiredFullFftColumns(
        usecols=usecols,
        frequency_columns=frequency_columns,
        candidate_indices=candidate_indices,
        excluded_base_indices=excluded_base_indices,
        required_indices=sorted(required_indices),
        oddball_frequency_hz=oddball,
        canonical_eligibility_domain=canonical_domain,
    )


def _require_matching_coverage_workbook(
    coverage_cell: Any,
    supplied_path: object,
    *,
    context: str,
) -> str:
    if not supplied_path:
        raise RuntimeError(
            f"{context} requires the released workbook path for "
            f"{coverage_cell.recording_id}/{coverage_cell.condition_label}."
        )
    expected = Path(str(coverage_cell.workbook_path)).expanduser().resolve(
        strict=False
    )
    supplied = Path(str(supplied_path)).expanduser().resolve(strict=False)
    if supplied != expected:
        raise RuntimeError(
            f"{context} received a workbook path different from final QC-21 "
            f"coverage for {coverage_cell.recording_id}/"
            f"{coverage_cell.condition_label}."
        )
    if not expected.is_file():
        raise RuntimeError(f"{context} released workbook is missing: {expected}")
    return str(expected)


def _unavailable_coverage_provenance(
    coverage_cell: Any,
    *,
    rois: Mapping[str, Sequence[str]],
    selected_columns: Sequence[str],
) -> dict[str, dict[str, object]]:
    reasons = tuple(coverage_cell.decision_reason_codes) or (
        f"recording_condition_{coverage_cell.outcome_status}",
    )
    membership_by_name = {
        membership.roi_name.casefold(): membership
        for membership in coverage_cell.roi_memberships
    }
    result: dict[str, dict[str, object]] = {}
    for roi_name, channels in rois.items():
        expected = [str(channel).strip().upper() for channel in channels]
        membership = membership_by_name.get(str(roi_name).casefold())
        result[str(roi_name)] = {
            "source_file": coverage_cell.workbook_path or None,
            "sheet": "BCA (uV)",
            "row_label": expected,
            "col_label": list(selected_columns),
            "raw_cell": None,
            "harmonic_policy": GROUP_SIGNIFICANT_POLICY_ID,
            "roi_coverage_status": "unavailable",
            "expected_electrodes": expected,
            "excluded_electrodes": list(
                membership.excluded_channels if membership is not None else ()
            ),
            "used_electrodes": [],
            "decision_reason_codes": list(reasons),
        }
    return result


def _resolve_group_oddball_frequency(
    *,
    base_frequency_hz: float,
    oddball_frequency_hz: float | None = None,
) -> float:
    base = float(base_frequency_hz)
    if not np.isfinite(base) or base <= 0:
        raise RuntimeError(
            "Group-level significant harmonic selection requires a positive finite "
            f"base frequency. Received base_frequency_hz={base_frequency_hz!r}."
        )
    oddball = float(
        LOCKED_ODDBALL_FREQUENCY_HZ
        if oddball_frequency_hz is None
        else oddball_frequency_hz
    )
    if not np.isfinite(oddball) or oddball <= 0:
        raise RuntimeError(
            "Group-level significant harmonic selection requires a positive finite "
            f"oddball frequency. Received oddball_frequency_hz={oddball_frequency_hz!r}."
        )
    if oddball >= base:
        raise RuntimeError(
            "Group-level significant harmonic selection requires the oddball "
            "frequency to be lower than the presentation/base frequency. "
            f"Received base_frequency_hz={base:g} and oddball_frequency_hz={oddball:g}. "
            "Check Settings > FPVS base frequency."
        )
    if _is_base_overlap(oddball, base, GROUP_SIGNIFICANT_BASE_TOLERANCE_HZ):
        raise RuntimeError(
            "Group-level significant harmonic selection requires an oddball "
            "frequency that is not itself a base-rate overlap. "
            f"Received base_frequency_hz={base:g} and oddball_frequency_hz={oddball:g}. "
            "Check Settings > FPVS base frequency."
        )
    return float(oddball)


def _normalize_eligible_harmonic_orders(
    values: Sequence[int] | None,
    *,
    allow_unspecified: bool,
) -> tuple[int, ...]:
    if values is None:
        if allow_unspecified:
            return ()
        raise RuntimeError("Canonical spectral eligibility was not supplied.")
    orders: set[int] = set()
    for value in values:
        if isinstance(value, bool):
            raise RuntimeError("Eligible harmonic orders must be positive integers.")
        try:
            order = int(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError(
                "Eligible harmonic orders must be positive integers."
            ) from exc
        if order <= 0 or float(order) != float(value):
            raise RuntimeError("Eligible harmonic orders must be positive integers.")
        orders.add(order)
    return tuple(sorted(orders))


def _preflight_required_full_fft_columns(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    required: RequiredFullFftColumns,
    log_func: Callable[[str], None],
) -> int:
    reference_grid = _locked_full_fft_grid_identity(
        required.frequency_columns,
        oddball_frequency_hz=required.oddball_frequency_hz,
    )
    if reference_grid is None:
        raise RuntimeError(
            "Group-level significant harmonic selection requires matching FullFFT "
            "candidate and neighboring-noise columns on one common locked FFT "
            "grid/bin spacing in every included workbook before reading amplitude "
            "or BCA data. The reference FullFFT header is not a valid uniform "
            "zero-based grid with one exact project oddball-frequency bin."
        )
    candidate_columns = _columns_for_required_indices(
        required.frequency_columns,
        required.candidate_indices,
    )
    required_columns = _columns_for_required_indices(
        required.frequency_columns,
        required.required_indices,
    )
    planned_workbooks = 0

    for pid in subjects:
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            if not file_path or not Path(file_path).exists():
                continue
            planned_workbooks += 1
            header_columns = _read_full_fft_header(file_path)
            header_names = {
                str(column)
                for column in header_columns
                if isinstance(column, str)
            }

            missing_candidates = [
                column
                for column in candidate_columns
                if column not in header_names
            ]
            if missing_candidates:
                raise RuntimeError(
                    "Group-level significant harmonic selection requires exact "
                    "nominal oddball harmonic columns in every included "
                    "FullFFT sheet before reading amplitude or BCA data. "
                    f"Missing candidate columns in {file_path}: "
                    f"{missing_candidates[:8]}"
                )

            missing_required = [
                column
                for column in required_columns
                if column not in header_names
            ]
            if missing_required:
                raise RuntimeError(
                    "Group-level significant harmonic selection requires matching "
                    "FullFFT candidate and neighboring-noise columns in every "
                    "included workbook before reading amplitude or BCA data. "
                    f"Missing columns in {file_path}: {missing_required[:8]}"
                )

            workbook_frequency_columns = _parse_frequency_columns(header_columns)
            workbook_grid = _locked_full_fft_grid_identity(
                workbook_frequency_columns,
                oddball_frequency_hz=required.oddball_frequency_hz,
            )
            if workbook_grid != reference_grid:
                reference_bin, reference_spacing = reference_grid
                observed_grid = (
                    "invalid or non-uniform"
                    if workbook_grid is None
                    else (
                        f"{required.oddball_frequency_hz:g} Hz bin={workbook_grid[0]}, "
                        f"df={workbook_grid[1]:.9g} Hz"
                    )
                )
                raise RuntimeError(
                    "Group-level significant harmonic selection requires matching "
                    "FullFFT candidate and neighboring-noise columns on one common "
                    "locked FFT grid/bin spacing in every included workbook before "
                    "reading amplitude or BCA data. "
                    f"Reference grid: {required.oddball_frequency_hz:g} Hz "
                    f"bin={reference_bin}, "
                    f"df={reference_spacing:.9g} Hz; grid in {file_path}: "
                    f"{observed_grid}. Reprocess or exclude participant-condition "
                    "workbooks with a different usable FFT crop length."
                )

    if planned_workbooks <= 0:
        raise RuntimeError(
            "Group-level significant harmonic selection requires workbooks with a "
            f"'{FULL_FFT_AMPLITUDE_SHEET_NAME}' sheet for included participants and conditions."
        )

    log_func(
        "[PERF] FullFFT exact-column preflight passed: "
        f"{planned_workbooks} workbooks, "
        f"{len(candidate_columns)} exact oddball harmonic columns, "
        f"{len(required_columns)} total candidate/noise columns."
    )
    return planned_workbooks


def _columns_for_required_indices(
    frequency_columns: Sequence[tuple[float, str, int]],
    required_indices: Sequence[int],
) -> list[str]:
    requested = {int(idx) for idx in required_indices}
    return [
        str(column)
        for _freq, column, idx in frequency_columns
        if int(idx) in requested
    ]


def _find_first_full_fft_columns(
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
) -> list[object]:
    for pid in subjects:
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            if not file_path or not Path(file_path).exists():
                continue
            try:
                return read_xlsx_sheet_header(
                    file_path,
                    sheet_name=FULL_FFT_AMPLITUDE_SHEET_NAME,
                )
            except ValueError as exc:
                raise RuntimeError(
                    "Group-level significant harmonic selection requires regenerated "
                    f"workbooks with a '{FULL_FFT_AMPLITUDE_SHEET_NAME}' sheet: {file_path}"
                ) from exc
    return []


def _mean_full_fft_columns_exact(
    frame: pd.DataFrame,
    columns: Sequence[str],
) -> np.ndarray:
    """Return established finite-only column means with a guarded batch path."""

    column_list = list(columns)
    selected = (
        frame.loc[:, column_list]
        if column_list and all(column in frame.columns for column in column_list)
        else pd.DataFrame()
    )
    if (
        len(selected.index) > 0
        and len(selected.columns) > 0
        and all(dtype == np.dtype(np.float64) for dtype in selected.dtypes)
    ):
        matrix = selected.to_numpy(dtype=float, copy=False)
        absolute_values = np.abs(matrix)
        row_count = max(1, matrix.shape[0])
        if (
            np.all(np.isfinite(absolute_values))
            and np.all(absolute_values != 0.0)
            and np.all(
                absolute_values
                <= np.finfo(np.float64).max / float(row_count)
            )
        ):
            # The transpose-copy gives each original column the same contiguous
            # one-dimensional value order used by the scalar expression below.
            return np.ascontiguousarray(matrix.T).mean(axis=1)

    means: list[float] = []
    for column in column_list:
        column_values = pd.to_numeric(
            frame.get(column, pd.Series(dtype=float)),
            errors="coerce",
        ).to_numpy(dtype=float)
        finite_values = column_values[np.isfinite(column_values)]
        means.append(
            float(finite_values.mean()) if finite_values.size else np.nan
        )
    return np.asarray(means, dtype=float)


def _load_mean_amplitude_series(
    file_path: str,
    *,
    rois: Dict[str, List[str]],
    electrode_scope: str,
    reference_frequency_columns: list[tuple[float, str, int]],
    required_indices: list[int],
    excluded_electrodes_upper: Iterable[str] = (),
    expected_scalp_channels: Sequence[str] | None = None,
    selection_electrodes: Sequence[str] = (),
    used_electrodes_out: set[str] | None = None,
) -> tuple[pd.Series, list[str], int]:
    try:
        header_columns = read_xlsx_sheet_header(
            file_path,
            sheet_name=FULL_FFT_AMPLITUDE_SHEET_NAME,
        )
    except ValueError as exc:
        raise RuntimeError(
            "Group-level significant harmonic selection requires regenerated "
            f"workbooks with a '{FULL_FFT_AMPLITUDE_SHEET_NAME}' sheet: {file_path}"
        ) from exc

    if not header_columns:
        return pd.Series(dtype=float), [], 0

    usecols, local_to_reference = _plan_workbook_full_fft_usecols_from_header(
        header_columns,
        reference_frequency_columns=reference_frequency_columns,
        required_indices=required_indices,
    )
    required_index_set = set(required_indices)
    required_columns = [
        str(column)
        for _freq, column, idx in reference_frequency_columns
        if int(idx) in required_index_set
    ]
    matched_reference_columns = {
        str(reference_column)
        for reference_items in local_to_reference.values()
        for _reference_freq, reference_column in reference_items
    }
    missing_columns = [
        column
        for column in required_columns
        if column not in matched_reference_columns
    ]
    if missing_columns:
        raise RuntimeError(
            "Group-level significant harmonic selection requires matching "
            f"FullFFT columns in every included workbook. Missing columns in {file_path}: "
            f"{missing_columns[:8]}"
        )

    header_names = {
        column
        for column in header_columns
        if isinstance(column, str)
    }
    ordered_local_columns = [
        column
        for column in usecols[1:]
        if column in header_names
    ]
    if not ordered_local_columns:
        raise RuntimeError(
            "Group-level significant harmonic selection requires matching "
            f"FullFFT columns in every included workbook: {file_path}"
        )

    wanted_electrodes = _wanted_electrodes_for_scope(
        rois=rois,
        electrode_scope=electrode_scope,
        selection_electrodes=selection_electrodes,
    )
    try:
        df_fft = read_xlsx_sheet_selected_columns(
            file_path,
            sheet_name=FULL_FFT_AMPLITUDE_SHEET_NAME,
            required_columns=["Electrode", *ordered_local_columns],
        )
    except MissingXlsxColumnsError as exc:
        raise RuntimeError(
            "Group-level significant harmonic selection requires matching "
            f"FullFFT columns in every included workbook. Missing columns in {file_path}: "
            f"{exc.missing_columns[:8]}"
        ) from exc

    if "Electrode" not in df_fft.columns:
        raise RuntimeError(
            "Group-level significant harmonic selection requires matching "
            f"FullFFT columns in every included workbook. Missing columns in {file_path}: "
            "['Electrode']"
        )

    # The reader returns an owned frame; source provenance is validated separately.
    # This reducer uses only its values. Drop unused metadata here so pandas does
    # not deepcopy the complete spectral grid during each column operation.
    df_fft.attrs = {}

    electrodes = (
        df_fft["Electrode"]
        .where(df_fft["Electrode"].notna(), "")
        .astype(str)
        .str.upper()
        .str.strip()
    )
    duplicate_electrodes = sorted(
        set(electrodes[electrodes.ne("") & electrodes.duplicated(keep=False)])
    )
    if duplicate_electrodes:
        raise RuntimeError(
            "Harmonic-selection source validation found duplicate electrode "
            f"rows in {file_path}: {duplicate_electrodes[:8]}"
        )
    observed = {electrode for electrode in electrodes.tolist() if electrode}
    if expected_scalp_channels is not None:
        expected = tuple(
            str(electrode).strip().upper()
            for electrode in expected_scalp_channels
        )
        if not expected or len(expected) != len(set(expected)):
            raise RuntimeError(
                "Harmonic-selection QC-21 source membership must be nonempty and unique."
            )
        missing = sorted(set(expected).difference(observed))
        extra = sorted(observed.difference(expected))
        blank_count = int(electrodes.eq("").sum())
        if missing or extra or blank_count:
            details: list[str] = []
            if missing:
                details.append("missing retained row(s): " + ", ".join(missing))
            if extra:
                details.append("extra or unknown row(s): " + ", ".join(extra))
            if blank_count:
                details.append(f"blank electrode row(s): {blank_count}")
            raise RuntimeError(
                "Harmonic-selection source validation failed before QC exclusions "
                f"for {file_path}: " + "; ".join(details)
            )
    excluded = {str(electrode).strip().upper() for electrode in excluded_electrodes_upper}
    if wanted_electrodes is not None:
        requested = set(wanted_electrodes)
        missing = sorted(requested.difference(observed))
        if missing:
            raise RuntimeError(
                "Harmonic-selection source validation failed for "
                f"{file_path}: frozen electrode row(s) are missing before QC exclusions: "
                + ", ".join(missing)
                + ". Regenerate the workbook or correct the frozen mask."
            )
    include_mask = electrodes != ""
    if wanted_electrodes is not None:
        include_mask = include_mask & electrodes.isin(wanted_electrodes)
    if excluded:
        include_mask = include_mask & ~electrodes.isin(excluded)
    df_fft = df_fft.loc[include_mask].copy()
    electrode_count = len(df_fft)
    if electrode_count == 0:
        raise RuntimeError(
            f"Harmonic selection has no eligible electrode rows in {file_path}."
        )
    numeric_block = df_fft.loc[:, ordered_local_columns].apply(
        pd.to_numeric,
        errors="coerce",
    )
    if not np.isfinite(numeric_block.to_numpy(dtype=float)).all():
        raise RuntimeError(
            "Harmonic-selection source validation requires finite FullFFT "
            f"values for every eligible electrode and planned bin: {file_path}"
        )
    df_fft.loc[:, ordered_local_columns] = numeric_block
    if used_electrodes_out is not None:
        used_electrodes_out.update(
            electrode
            for electrode in electrodes.loc[include_mask].tolist()
            if electrode
        )

    values: dict[float, float] = {}
    reference_columns: list[str] = []
    column_means = _mean_full_fft_columns_exact(
        df_fft,
        ordered_local_columns,
    )
    for local_column, column_mean in zip(
        ordered_local_columns,
        column_means,
    ):
        value = float(column_mean)
        for reference_freq, reference_column in local_to_reference.get(local_column, []):
            values[reference_freq] = value
            reference_columns.append(reference_column)

    series = pd.Series(values, dtype=float)
    return pd.to_numeric(series, errors="coerce"), reference_columns, electrode_count


def _plan_workbook_full_fft_usecols_from_header(
    header_columns: Sequence[object],
    *,
    reference_frequency_columns: list[tuple[float, str, int]],
    required_indices: list[int],
) -> tuple[list[str], dict[str, list[tuple[float, str]]]]:
    local_frequency_columns = _parse_frequency_columns(header_columns)
    if not local_frequency_columns:
        return ["Electrode"], {}

    required_index_set = set(required_indices)
    reference_by_idx = {
        int(idx): (float(freq), str(column))
        for freq, column, idx in reference_frequency_columns
        if int(idx) in required_index_set
    }
    local_by_column = {str(column): float(freq) for freq, column, _idx in local_frequency_columns}
    local_to_reference: dict[str, list[tuple[float, str]]] = {}
    for required_idx in sorted(required_index_set):
        reference = reference_by_idx.get(int(required_idx))
        if reference is None:
            continue
        reference_freq, reference_column = reference
        local_freq = local_by_column.get(reference_column)
        if local_freq is None:
            continue
        if abs(float(local_freq) - reference_freq) > GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ:
            continue
        local_to_reference.setdefault(str(reference_column), []).append(
            (reference_freq, reference_column)
        )

    return ["Electrode", *local_to_reference.keys()], local_to_reference


def _read_full_fft_header(file_path: str | Path) -> list[object]:
    try:
        return read_xlsx_sheet_header(
            file_path,
            sheet_name=FULL_FFT_AMPLITUDE_SHEET_NAME,
        )
    except ValueError as exc:
        raise RuntimeError(
            "Group-level significant harmonic selection requires regenerated "
            f"workbooks with a '{FULL_FFT_AMPLITUDE_SHEET_NAME}' sheet: {file_path}"
        ) from exc


def _aggregate_bca_for_all_rois(
    *,
    file_path: str | None,
    rois: Dict[str, List[str]],
    log_func: Callable[[str], None],
    harmonic_freqs: List[float],
    provenance_enabled: bool,
    excluded_electrodes_upper: Iterable[str] = (),
    strict_source: bool = False,
) -> tuple[dict[str, float], dict[str, dict[str, object]]]:
    values = {roi_name: np.nan for roi_name in rois.keys()}
    provenance: dict[str, dict[str, object]] = {}
    if not file_path or not Path(file_path).exists():
        if strict_source:
            raise RuntimeError(
                f"Group Summed BCA released source is missing: {file_path}"
            )
        log_func(f"Missing file: {file_path}")
        return values, provenance

    started = perf_counter()
    cols_to_sum = [f"{float(freq_val):.4f}_Hz" for freq_val in harmonic_freqs]
    try:
        df_bca = read_xlsx_sheet_selected_columns(
            file_path,
            sheet_name="BCA (uV)",
            required_columns=["Electrode", *cols_to_sum],
        )
    except MissingXlsxColumnsError as exc:
        missing_bca_columns = [column for column in cols_to_sum if column in exc.missing_columns]
        if missing_bca_columns:
            raise RuntimeError(
                "Group-level significant harmonic summation requires exact selected "
                f"BCA harmonic columns in every included workbook. Missing columns in {file_path}: "
                f"{missing_bca_columns[:8]}"
            ) from exc
        if strict_source:
            raise RuntimeError(
                f"Group Summed BCA could not read the released BCA source {file_path}: {exc}"
            ) from exc
        log_func(f"Error reading BCA sheet for {file_path}: {exc}")
        return values, provenance
    except Exception as exc:  # noqa: BLE001
        if strict_source:
            raise RuntimeError(
                f"Group Summed BCA could not read the released BCA source {file_path}: {exc}"
            ) from exc
        log_func(f"Error reading BCA sheet for {file_path}: {exc}")
        return values, provenance

    read_elapsed = perf_counter() - started
    if "Electrode" not in df_bca.columns:
        if strict_source:
            raise RuntimeError(
                f"Group Summed BCA released source lacks the Electrode column: {file_path}"
            )
        log_func(f"Error reading BCA sheet for {file_path}: missing Electrode column")
        return values, provenance
    df_bca["Electrode"] = df_bca["Electrode"].astype(str).str.upper().str.strip()
    duplicate_electrodes = sorted(
        set(df_bca.loc[df_bca["Electrode"].duplicated(keep=False), "Electrode"])
    )
    if duplicate_electrodes:
        raise RuntimeError(
            "Group harmonic summation requires one source row per electrode. "
            f"Duplicate rows in {file_path}: {duplicate_electrodes[:8]}"
        )
    df_bca = df_bca.set_index("Electrode")
    missing_bca_columns = [column for column in cols_to_sum if column not in df_bca.columns]
    if missing_bca_columns:
        raise RuntimeError(
            "Group-level significant harmonic summation requires exact selected "
            f"BCA harmonic columns in every included workbook. Missing columns in {file_path}: "
            f"{missing_bca_columns[:8]}"
        )

    numeric_bca = (
        df_bca[cols_to_sum]
        .apply(pd.to_numeric, errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
    )
    excluded = {str(electrode).strip().upper() for electrode in excluded_electrodes_upper}
    for roi_name, roi_channels in rois.items():
        roi_chans = [
            str(ch).strip().upper()
            for ch in (roi_channels or [])
            if str(ch).strip()
        ]
        if not roi_chans:
            log_func(f"ROI {roi_name} not defined.")
            continue
        if len(set(roi_chans)) != len(roi_chans):
            raise RuntimeError(
                f"ROI {roi_name!r} repeats an electrode and cannot be averaged."
            )
        missing_members = [
            channel for channel in roi_chans if channel not in numeric_bca.index
        ]
        if missing_members:
            raise RuntimeError(
                f"ROI {roi_name!r} requires its complete electrode set in "
                f"{file_path}. Missing: {missing_members}"
            )
        excluded_members = [channel for channel in roi_chans if channel in excluded]
        if excluded_members:
            log_func(
                f"ROI {roi_name} was not calculated for {file_path}; reviewed "
                "required-electrode exclusion(s): " + ", ".join(excluded_members)
            )
            if provenance_enabled:
                provenance[roi_name] = _empty_provenance(
                    file_path,
                    row_label=roi_chans,
                    col_label=cols_to_sum,
                )
                provenance[roi_name].update(
                    {
                        "roi_coverage_status": "unavailable",
                        "expected_electrodes": roi_chans,
                        "excluded_electrodes": excluded_members,
                        "used_electrodes": [],
                    }
                )
            continue
        df_roi = numeric_bca.loc[roi_chans]
        if not np.isfinite(df_roi.to_numpy(dtype=float)).all():
            raise RuntimeError(
                f"ROI {roi_name!r} has a nonfinite computable selected-harmonic "
                f"BCA value in {file_path}; partial harmonic sums are forbidden."
            )
        bca_vals = df_roi.sum(axis=1, min_count=len(cols_to_sum))
        bca_vals = pd.to_numeric(bca_vals, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if len(bca_vals) != len(roi_chans) or not np.isfinite(
            bca_vals.to_numpy(dtype=float)
        ).all():
            raise RuntimeError(
                f"ROI {roi_name!r} did not produce one finite complete-harmonic "
                f"sum per configured electrode in {file_path}."
            )
        values[roi_name] = float(bca_vals.mean(skipna=False))
        if provenance_enabled:
            provenance[roi_name] = {
                "source_file": file_path,
                "sheet": "BCA (uV)",
                "row_label": roi_chans,
                "col_label": cols_to_sum,
                "raw_cell": df_roi.to_dict(orient="index"),
                "harmonic_policy": GROUP_SIGNIFICANT_POLICY_ID,
                "roi_coverage_status": "available",
                "expected_electrodes": roi_chans,
                "excluded_electrodes": [],
                "used_electrodes": roi_chans,
            }
    logger.debug(
        "stats_group_harmonics_bca_workbook_done",
        extra={
            "elapsed_s": perf_counter() - started,
            "read_elapsed_s": read_elapsed,
            "path": str(file_path),
            "roi_count": len(rois),
            "harmonic_count": len(cols_to_sum),
        },
    )
    return values, provenance


def _finite_harmonic_values(values: Sequence[object]) -> list[float]:
    finite_values: list[float] = []
    if values is None:
        return finite_values
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(number):
            finite_values.append(number)
    return finite_values


def _harmonic_index_for_frequency(frequency_hz: float, oddball_hz: float) -> int | None:
    try:
        frequency = float(frequency_hz)
        oddball = float(oddball_hz)
    except (TypeError, ValueError):
        return None
    if not (np.isfinite(frequency) and np.isfinite(oddball)) or frequency <= 0 or oddball <= 0:
        return None
    harmonic_index = int(round(frequency / oddball))
    if harmonic_index <= 0:
        return None
    canonical_freq = _canonical_harmonic_frequency_for_index(harmonic_index, oddball)
    if abs(canonical_freq - frequency) > GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ:
        return None
    return harmonic_index


def _highest_selected_harmonic_metadata(
    values: Sequence[object],
    *,
    oddball_hz: float,
    prefix: str,
) -> dict[str, object]:
    finite_values = _finite_harmonic_values(values)
    if not finite_values:
        return {
            f"{prefix}_hz": np.nan,
            f"{prefix}_index": None,
        }
    highest_hz = float(max(finite_values))
    return {
        f"{prefix}_hz": highest_hz,
        f"{prefix}_index": _harmonic_index_for_frequency(highest_hz, oddball_hz),
    }


def _empty_provenance(
    file_path: str | None,
    *,
    row_label: list[str],
    col_label: list[str],
) -> dict[str, object]:
    return {
        "source_file": file_path,
        "sheet": "BCA (uV)",
        "row_label": row_label,
        "col_label": col_label,
        "raw_cell": None,
        "harmonic_policy": GROUP_SIGNIFICANT_POLICY_ID,
    }


def _noise_indices_for_bin(
    target_idx: int,
    *,
    available_indices: set[int],
    window_size: int,
) -> list[int]:
    low = max(0, int(target_idx) - int(window_size))
    high = int(target_idx) + int(window_size)
    excluded = {int(target_idx) - 1, int(target_idx), int(target_idx) + 1}
    return [
        idx
        for idx in range(low, high + 1)
        if idx in available_indices and idx not in excluded
    ]


def _compute_noise_stats_for_planned_bin(
    amplitude_by_bin: dict[int, float],
    target_idx: int,
    *,
    window_size: int,
    min_bins: int,
    require_complete_window: bool = False,
) -> GroupSignificantNoiseStats:
    indices = _noise_indices_for_bin(
        int(target_idx),
        available_indices=set(amplitude_by_bin.keys()),
        window_size=window_size,
    )
    required_count = len(QC14_NOISE_CANDIDATE_OFFSETS)
    if require_complete_window and len(indices) != required_count:
        return GroupSignificantNoiseStats(
            mean_uv=np.nan,
            std_uv=np.nan,
            candidate_bin_indices=tuple(indices),
            used_bin_indices=(),
        )
    if len(indices) < min_bins:
        return GroupSignificantNoiseStats(
            mean_uv=0.0,
            std_uv=0.0,
            candidate_bin_indices=tuple(indices),
            used_bin_indices=(),
        )
    finite_pairs = [
        (idx, amplitude_by_bin[idx])
        for idx in indices
        if np.isfinite(amplitude_by_bin.get(idx, np.nan))
    ]
    if require_complete_window and len(finite_pairs) != required_count:
        return GroupSignificantNoiseStats(
            mean_uv=np.nan,
            std_uv=np.nan,
            candidate_bin_indices=tuple(idx for idx, _value in finite_pairs),
            used_bin_indices=(),
        )
    if len(finite_pairs) < min_bins:
        return GroupSignificantNoiseStats(
            mean_uv=0.0,
            std_uv=0.0,
            candidate_bin_indices=tuple(idx for idx, _value in finite_pairs),
            used_bin_indices=(),
        )
    used_pairs = list(finite_pairs)
    if len(used_pairs) > 2:
        noise_vals = np.asarray([value for _idx, value in used_pairs], dtype=float)
        max_idx = int(noise_vals.argmax())
        min_idx = int(noise_vals.argmin())
        used_pairs = [
            pair
            for pair_index, pair in enumerate(used_pairs)
            if pair_index not in {max_idx, min_idx}
        ]
    if not used_pairs:
        return GroupSignificantNoiseStats(
            mean_uv=0.0,
            std_uv=0.0,
            candidate_bin_indices=tuple(idx for idx, _value in finite_pairs),
            used_bin_indices=(),
        )
    used_values = np.asarray([value for _idx, value in used_pairs], dtype=float)
    return GroupSignificantNoiseStats(
        mean_uv=float(used_values.mean()),
        std_uv=float(used_values.std(ddof=0)),
        candidate_bin_indices=tuple(idx for idx, _value in finite_pairs),
        used_bin_indices=tuple(idx for idx, _value in used_pairs),
    )


def _electrodes_for_scope(
    df_fft: pd.DataFrame,
    *,
    rois: Dict[str, List[str]],
    electrode_scope: str,
    selection_electrodes: Sequence[str] = (),
) -> list[str]:
    wanted = _wanted_electrodes_for_scope(
        rois=rois,
        electrode_scope=electrode_scope,
        selection_electrodes=selection_electrodes,
    )
    if wanted is not None:
        return [
            idx
            for idx in df_fft.index.astype(str)
            if str(idx).strip().upper() in wanted
        ]
    _ = rois
    return list(df_fft.index.astype(str))


def _wanted_electrodes_for_scope(
    *,
    rois: Dict[str, List[str]],
    electrode_scope: str,
    selection_electrodes: Sequence[str] = (),
) -> set[str] | None:
    if electrode_scope == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN:
        return {
            str(electrode).strip().upper()
            for electrode in selection_electrodes
            if str(electrode).strip()
        }
    if electrode_scope != GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION:
        return None
    wanted = {
        str(ch).strip().upper()
        for channels in (rois or {}).values()
        for ch in (channels or [])
        if str(ch).strip()
    }
    return wanted or None


def _parse_frequency_columns(columns: Sequence[object]) -> list[tuple[float, str, int]]:
    out: list[tuple[float, str, int]] = []
    freq_idx = 0
    for col_name in columns:
        if not isinstance(col_name, str) or not col_name.endswith("_Hz"):
            continue
        try:
            out.append((float(col_name[:-3]), col_name, freq_idx))
            freq_idx += 1
        except ValueError:
            continue
    return sorted(out, key=lambda item: item[0])


def _locked_full_fft_grid_identity(
    frequency_columns: Sequence[tuple[float, str, int]],
    *,
    oddball_frequency_hz: float = LOCKED_ODDBALL_FREQUENCY_HZ,
) -> tuple[int, float] | None:
    """Return the exact oddball-bin index and spacing for one valid FullFFT grid."""

    frequencies = [float(freq) for freq, _column, _idx in frequency_columns]
    if len(frequencies) < 2 or abs(frequencies[0]) > 5e-5:
        return None

    oddball_hz = float(oddball_frequency_hz)
    target_positions = [
        index
        for index, frequency in enumerate(frequencies)
        if abs(frequency - oddball_hz) <= 5e-5
    ]
    if len(target_positions) != 1 or target_positions[0] <= 0:
        return None

    oddball_bin = int(target_positions[0])
    spacing_hz = oddball_hz / oddball_bin
    if any(
        abs(frequency - index * spacing_hz) > 6e-5
        for index, frequency in enumerate(frequencies)
    ):
        return None
    return oddball_bin, spacing_hz


def _find_exact_frequency_column(
    frequency_columns: Sequence[tuple[float, str, int]],
    target_freq: float,
) -> tuple[float, str, int] | None:
    for freq, column, idx in frequency_columns:
        if abs(float(freq) - float(target_freq)) <= 1e-9:
            return float(freq), str(column), int(idx)
    return None


def _should_log_progress(index: int, total: int, interval: int) -> bool:
    if total <= 0:
        return False
    if index in {1, total}:
        return True
    return interval > 0 and index % interval == 0


def _numeric_or_nan(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return np.nan
    return number if np.isfinite(number) else np.nan


def _frequency_resolution(freqs: Sequence[float]) -> float | None:
    unique = sorted(set(float(freq) for freq in freqs))
    if len(unique) < 2:
        return None
    diffs = np.diff(np.asarray(unique, dtype=float))
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    if diffs.size == 0:
        return None
    return float(np.median(diffs))


def _format_candidate_z_summary(rows: Sequence[GroupSignificantHarmonicRow]) -> str:
    parts: list[str] = []
    for row in rows:
        if not row.evaluated:
            parts.append(f"{row.target_frequency_hz:.4f} Hz not evaluated after stopping rule")
            continue
        if row.excluded_base_rate:
            parts.append(f"{row.target_frequency_hz:.4f} Hz excluded base overlap")
            continue
        if row.z_score is None:
            reason = row.exclusion_reason or "not tested"
            parts.append(f"{row.target_frequency_hz:.4f} Hz {reason}")
            continue
        parts.append(f"{row.target_frequency_hz:.4f} Hz z={row.z_score:.3f}")
    return "; ".join(parts) if parts else "none"


def _log_candidate_diagnostics(
    rows: Sequence[GroupSignificantHarmonicRow],
    log_func: Callable[[str], None],
) -> None:
    for row in rows:
        if not row.evaluated:
            log_func(
                "[DEBUG] Group harmonic candidate "
                f"{row.target_frequency_hz:.4f} Hz not evaluated after stopping rule."
            )
            continue
        if row.excluded_base_rate:
            log_func(
                "[DEBUG] Group harmonic candidate "
                f"{row.target_frequency_hz:.4f} Hz skipped: base-rate overlap "
                f"(column={row.matched_column}, bin={row.matched_bin_index})."
            )
            continue
        if row.target_amplitude_uv is None:
            log_func(
                "[DEBUG] Group harmonic candidate "
                f"{row.target_frequency_hz:.4f} Hz not tested: "
                f"{row.exclusion_reason or row.warning or 'missing amplitude'} "
                f"(column={row.matched_column}, bin={row.matched_bin_index})."
            )
            continue
        log_func(
            "[DEBUG] Group harmonic candidate "
            f"{row.target_frequency_hz:.4f} Hz "
            f"(column={row.matched_column}, bin={row.matched_bin_index}, "
            f"matched={_format_optional_float(row.matched_frequency_hz)} Hz): "
            f"grand_avg_amp_uv={row.target_amplitude_uv:.10g}, "
            f"noise_mean_uv={_format_optional_float(row.noise_mean_uv)}, "
            f"noise_std_uv={_format_optional_float(row.noise_std_uv)}, "
            f"z={_format_optional_float(row.z_score)}, "
            f"noise_bins={_format_noise_pairs(row.noise_frequencies_hz, row.noise_amplitudes_uv)}, "
            f"noise_used_bins={_format_noise_pairs(row.noise_used_frequencies_hz, row.noise_used_amplitudes_uv)}."
        )


def _format_optional_float(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "nan"
    return f"{float(value):.10g}"


def _format_noise_pairs(freqs: Sequence[float], amplitudes: Sequence[float]) -> str:
    if not freqs or not amplitudes:
        return "[]"
    parts = [
        f"{float(freq):.4f}:{float(amplitude):.10g}"
        for freq, amplitude in zip(freqs, amplitudes)
    ]
    return "[" + ", ".join(parts) + "]"


def _is_base_overlap(freq: float, base: float, tolerance_hz: float) -> bool:
    if base <= 0:
        return False
    multiple = round(float(freq) / float(base))
    if multiple <= 0:
        return False
    return abs(float(freq) - multiple * float(base)) < float(tolerance_hz)


def _methods_summary(selection: GroupSignificantHarmonicSelection) -> str:
    detected = ", ".join(f"{freq:g}" for freq in selection.detected_significant_harmonics_hz)
    included = ", ".join(f"{freq:g}" for freq in selection.selected_harmonics_hz)
    excluded = ", ".join(f"{freq:g}" for freq in selection.excluded_base_harmonics_hz)
    if selection.electrode_scope == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION:
        scope = "the union of predefined ROI electrodes"
    elif selection.electrode_scope == GROUP_SIGNIFICANT_ELECTRODE_SCOPE_FROZEN:
        scope = "the frozen a-priori harmonic-selection electrode mask"
    else:
        scope = "all retained scalp electrodes"
    if selection.summation_method == GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST:
        gap_guard = _summation_gap_guard_decision(
            rows=selection.rows,
            detected_freqs=selection.detected_significant_harmonics_hz,
            summation_method=selection.summation_method,
        )
        if gap_guard.applied:
            summation_text = (
                "The isolated highest significant harmonic "
                f"({gap_guard.highest_significant_harmonic_hz:g} Hz) and all "
                "intervening harmonics above the next-highest significant harmonic "
                f"({gap_guard.lower_significant_harmonic_hz:g} Hz) were excluded "
                f"because the gap contained {gap_guard.intervening_nonbase_harmonic_count} "
                "eligible non-base harmonics, exceeding the locked maximum of "
                f"{GROUP_SIGNIFICANT_MAX_INTERVENING_NONBASE_HARMONICS}. All eligible "
                "non-base oddball harmonics through the retained cutoff were included "
                f"in the Summed BCA ({included} Hz)."
            )
        else:
            summation_text = (
                "All eligible non-base oddball harmonics up to the highest significant "
                f"harmonic were included in the Summed BCA ({included} Hz). The "
                "isolated-highest gap guard excludes the upper peak only when more than "
                f"{GROUP_SIGNIFICANT_MAX_INTERVENING_NONBASE_HARMONICS} eligible "
                "non-base harmonics lie between the two highest significant peaks; "
                "the guard was not triggered."
            )
    elif (
        selection.summation_method
        == GROUP_SIGNIFICANT_SUMMATION_TWO_CONSECUTIVE_FAILURES
    ):
        stopping = ", ".join(
            f"{freq:g}" for freq in selection.stopping_harmonics_hz
        )
        if selection.stopping_harmonics_hz:
            stopping_text = (
                f"Selection stopped after consecutive failures at {stopping} Hz"
            )
        else:
            stopping_text = (
                "The configured search domain ended before two consecutive failures"
            )
        summation_text = (
            f"{stopping_text}; eligible harmonics through the preceding cutoff were "
            f"included in Summed BCA ({included} Hz)."
        )
    else:
        summation_text = (
            f"Only z-significant oddball harmonics were included in the Summed BCA ({included} Hz)."
        )
    if selection.pooling_cells:
        if selection.declared_session_ids:
            selection_text = (
                "Recordings were averaged within participant inside each declared "
                "group x session x task-condition cell, participants were averaged "
                "within cell, groups were weighted equally, local Z-scores were "
                "calculated separately by session and task condition, and all "
                "session-condition Z-scores were weighted equally"
            )
        else:
            selection_text = (
                "Participants were averaged within each declared group x condition "
                "cell, group spectra were weighted equally within condition, local "
                "Z-scores were calculated separately by condition, and condition "
                "Z-scores were weighted equally"
            )
    else:
        selection_text = "Available participant-condition spectra were averaged equally"
    return (
        f"Using the {selection.method_profile_label} profile, {selection_text} "
        f"over {scope}; z-significant harmonics were "
        f"{detected} Hz. Candidate oddball harmonics "
        f"were tested against neighboring-bin noise with z>{selection.z_threshold:g}; "
        "base-rate overlaps were excluded"
        + (f" ({excluded} Hz)." if excluded else ".")
        + f" {summation_text} "
        + " The same selected harmonic list was applied to every participant, "
        "condition, and ROI. SNR values were not used as the primary dependent variable."
    )
