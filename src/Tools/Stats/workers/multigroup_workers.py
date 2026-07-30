"""GUI-neutral worker functions for prepared native Stats inference.

These functions accept one :class:`PreparedAnalysisPayload` and never inspect
the project, rerun the design audit, or import Qt.  Every returned dictionary
contains the same payload object and ``preparation_id`` so pipeline/controller
code can prove that all steps used one frozen analysis cohort.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from Tools.Stats.analysis.baseline_vs_zero import run_baseline_vs_zero_tests
from Tools.Stats.analysis.dv_policies import (
    GROUP_SIGNIFICANT_POLICY_NAME,
    normalize_dv_policy,
    prepare_summed_bca_data,
)
from Tools.Stats.analysis.dv_policy_group_significant import (
    preflight_group_significant_full_fft_columns,
)
from Tools.Stats.analysis.group_comparisons import (
    run_group_cell_comparisons as _run_group_cell_comparisons,
)
from Tools.Stats.analysis.inference_contracts import (
    AnalysisProfile,
    AnalysisRunSpec,
    CorrectionMethod,
    FamilySpec,
    FollowupProvenance,
    HarmonicProvenance,
)
from Tools.Stats.analysis.lmm_contrasts import (
    estimate_condition_within_roi_contrasts,
    estimate_roi_within_condition_contrasts,
)
from Tools.Stats.analysis.mixed_effects_model import run_mixed_effects_model
from Tools.Stats.analysis.multiple_comparisons import apply_family_correction
from Tools.Stats.analysis.multigroup_model import (
    run_multigroup_mixed_model,
)
from Tools.Stats.analysis.prepared_analysis import (
    AnalysisMode,
    PreparedAnalysisPayload,
    prepare_analysis_payload,
)
from Tools.Stats.analysis.repeated_m_anova import (
    run_repeated_measures_anova,
)
from Tools.Stats.analysis.resampling import (
    DEFAULT_EXACT_ENUMERATION_LIMIT,
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    run_group_label_permutation_max_t,
    run_one_sample_sign_flip_max_t,
)
from Tools.Stats.analysis.robust_tests import (
    DEFAULT_TRIM_FRACTION,
    run_one_sample_trimmed_mean_test,
    run_one_sample_wilcoxon_test,
    run_two_group_trimmed_mean_test,
)
from Tools.Stats.analysis.stability import (
    run_one_sample_leave_one_out_stability,
    run_two_group_leave_one_out_stability,
)
from Tools.Stats.qc.stats_outlier_exclusion import apply_hard_dv_exclusion
from Tools.Stats.qc.stats_qc_exclusion import (
    QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS,
    QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS,
    QC_DEFAULT_CRITICAL_THRESHOLD,
    QC_DEFAULT_WARN_ABS_FLOOR_MAXABS,
    QC_DEFAULT_WARN_ABS_FLOOR_SUMABS,
    QC_DEFAULT_WARN_THRESHOLD,
    QcExclusionReport,
    run_qc_exclusion,
)
from Tools.Stats.data.group_harmonic_cache import (
    build_group_harmonic_cache_request,
    lookup_cached_group_harmonic_selection,
)


PREPARED_WORKER_SCHEMA_VERSION = 2
MAX_SENSITIVITY_RESAMPLES = 100_000
MAX_ROBUST_CELLS = 512
ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]
STRICT_OMNIBUS_FAMILY_ID = "omnibus_effects_strict"
SINGLE_FOLLOWUP_FAMILY_ID = "planned_contrasts"


def _standard_holm_family(
    payload: PreparedAnalysisPayload,
    *,
    family_id: str,
    family_label: str,
) -> FamilySpec:
    """Return the declared screening family or its locked Holm fallback."""

    declared = payload.run_spec.family_map.get(family_id)
    if declared is not None:
        return declared
    return FamilySpec(
        family_id=family_id,
        family_label=family_label,
        method=CorrectionMethod.HOLM,
        alpha=payload.run_spec.alpha,
    )


def _apply_single_primary_omnibus_correction(
    payload: PreparedAnalysisPayload,
    table: pd.DataFrame,
) -> pd.DataFrame:
    """Correct and promote the primary single-group LMM screening blocks."""

    family = _standard_holm_family(
        payload,
        family_id=STRICT_OMNIBUS_FAMILY_ID,
        family_label="Primary LMM factorial screening blocks",
    )
    corrected = apply_family_correction(
        table,
        family,
        p_col="p_value_chi2",
    )
    corrected["inference_role"] = "primary"
    headline = pd.to_numeric(
        corrected["p_adjusted"],
        errors="coerce",
    ).notna()
    if "reportable" in corrected.columns:
        headline &= corrected["reportable"].fillna(False).astype(bool)
    if "status" in corrected.columns:
        headline &= corrected["status"].astype(str).eq("ok")
    corrected["headline_eligible"] = headline
    corrected["analysis_scope"] = payload.analysis_scope
    corrected["missing_values_imputed"] = False
    return corrected


def _corrected_single_interaction_result(
    lrt_table: pd.DataFrame | None,
) -> tuple[bool, float | None, str]:
    """Resolve the corrected Condition x ROI interaction decision."""

    if not isinstance(lrt_table, pd.DataFrame) or lrt_table.empty:
        return False, None, "omnibus_result_unavailable"
    if "effect_id" not in lrt_table.columns:
        return False, None, "omnibus_result_unavailable"
    interaction = lrt_table.loc[
        lrt_table["effect_id"].astype(str).eq(
            "condition_roi_interaction"
        )
    ]
    if len(interaction) != 1:
        return False, None, "omnibus_result_unavailable"
    row = interaction.iloc[0]
    if "status" in interaction.columns and str(row["status"]) != "ok":
        return False, None, "omnibus_result_unavailable"
    if "reportable" in interaction.columns and not bool(row["reportable"]):
        return False, None, "omnibus_result_unavailable"
    adjusted = pd.to_numeric(
        pd.Series([row.get("p_adjusted")]),
        errors="coerce",
    ).iloc[0]
    p_adjusted = float(adjusted) if np.isfinite(adjusted) else None
    if "reject_adjusted" in interaction.columns:
        supported = bool(row["reject_adjusted"])
    elif p_adjusted is not None:
        alpha = pd.to_numeric(
            pd.Series([row.get("alpha")]),
            errors="coerce",
        ).iloc[0]
        supported = bool(
            np.isfinite(alpha) and p_adjusted <= float(alpha)
        )
    else:
        supported = False
    return (
        supported,
        p_adjusted,
        "omnibus_supported" if supported else "omnibus_not_significant",
    )


def _resolve_single_followup_provenance(
    payload: PreparedAnalysisPayload,
    explicit: object | None,
) -> FollowupProvenance:
    """Resolve why the fitted-model simple contrasts were included."""

    candidate = (
        explicit
        if explicit is not None
        else payload.run_spec.followup_provenance
    )
    if candidate is None:
        return FollowupProvenance.OMNIBUS_TRIGGERED
    return FollowupProvenance.coerce(candidate)


def _single_lmm_contrast_frame(
    payload: PreparedAnalysisPayload,
    fitted_model: object,
    corrected_lrt: pd.DataFrame | None,
    *,
    ci_level: float,
    followup_provenance: object | None,
) -> pd.DataFrame:
    """Build one Holm family of simple contrasts from the fitted LMM."""

    data = payload.primary_data
    shared = {
        "participant_col": payload.subject_col,
        "dv_col": payload.dv_col,
        "condition_col": payload.condition_col,
        "roi_col": payload.roi_col,
        "condition_levels": payload.retained_conditions,
        "roi_levels": payload.selected_rois,
        "ci_level": float(ci_level),
    }
    condition_within_roi = estimate_condition_within_roi_contrasts(
        fitted_model,
        data,
        **shared,
    )
    roi_within_condition = estimate_roi_within_condition_contrasts(
        fitted_model,
        data,
        **shared,
    )
    contrasts = pd.concat(
        [condition_within_roi, roi_within_condition],
        ignore_index=True,
    )
    family = _standard_holm_family(
        payload,
        family_id=SINGLE_FOLLOWUP_FAMILY_ID,
        family_label="LMM-derived factorial follow-up contrasts",
    )
    contrasts = apply_family_correction(
        contrasts,
        family,
        p_col="p_raw",
    )

    provenance = _resolve_single_followup_provenance(
        payload,
        followup_provenance,
    )
    (
        interaction_supported,
        interaction_p_adjusted,
        interaction_status,
    ) = _corrected_single_interaction_result(corrected_lrt)
    reportable = (
        contrasts["reportable"].fillna(False).astype(bool)
        if "reportable" in contrasts.columns
        else pd.Series(False, index=contrasts.index, dtype=bool)
    )
    if provenance is FollowupProvenance.PLANNED:
        headline_eligible = reportable
        gate_status = "planned_not_gated"
    elif provenance is FollowupProvenance.OMNIBUS_TRIGGERED:
        headline_eligible = reportable & interaction_supported
        gate_status = interaction_status
    else:
        headline_eligible = pd.Series(
            False,
            index=contrasts.index,
            dtype=bool,
        )
        gate_status = "exploratory_manual_detailed_only"

    contrasts["followup_provenance"] = provenance.value
    contrasts["omnibus_effect_id"] = "condition_roi_interaction"
    contrasts["omnibus_p_adjusted"] = interaction_p_adjusted
    contrasts["omnibus_significant"] = interaction_supported
    contrasts["omnibus_gate_status"] = gate_status
    contrasts["automatic_explanation_supported"] = (
        interaction_supported
    )
    contrasts["headline_eligible"] = headline_eligible
    contrasts["inference_role"] = np.where(
        headline_eligible,
        "primary",
        "exploratory",
    )
    contrasts["analysis_scope"] = payload.analysis_scope
    contrasts["missing_values_imputed"] = False
    contrasts.attrs.update(
        {
            "family_scope": "all_single_factorial_followups",
            "followup_provenance": provenance.value,
            "omnibus_effect_id": "condition_roi_interaction",
            "omnibus_p_adjusted": interaction_p_adjusted,
            "omnibus_significant": interaction_supported,
            "omnibus_gate_status": gate_status,
            "missing_values_imputed": False,
        }
    )
    return contrasts


def _apply_strict_omnibus_correction(
    payload: PreparedAnalysisPayload,
    table: pd.DataFrame,
    *,
    p_col: str,
) -> pd.DataFrame:
    """Apply the declared omnibus family, or label unadjusted decomposition rows."""

    family = payload.run_spec.family_map.get(STRICT_OMNIBUS_FAMILY_ID)
    if family is not None:
        corrected = apply_family_correction(table, family, p_col=p_col)
        corrected["inference_role"] = "primary"
        corrected["headline_eligible"] = True
        return corrected

    # The unadjusted path only appends interpretation metadata and preserves
    # the established result-frame identity used by legacy single-step callers.
    output = table
    output["family_id"] = pd.NA
    output["family_label"] = pd.NA
    output["family_size"] = 0
    output["adjustment_method"] = "none"
    if "effect_id" in output.columns:
        joint = output["effect_id"].astype(str).eq("any_group_related")
        output["inference_role"] = "exploratory"
        output.loc[joint, "inference_role"] = "primary"
        output["headline_eligible"] = joint
    else:
        output["inference_role"] = "exploratory"
        output["headline_eligible"] = False
    return output


@dataclass(frozen=True)
class SensitivityConfig:
    """Bounded configuration for optional sensitivity analyses."""

    run_robust: bool = True
    run_resampling: bool = True
    run_stability: bool = True
    trim_fraction: float = DEFAULT_TRIM_FRACTION
    n_resamples: int = DEFAULT_RESAMPLES
    seed: int = DEFAULT_SEED
    exact_enumeration_limit: int = DEFAULT_EXACT_ENUMERATION_LIMIT
    max_robust_cells: int = MAX_ROBUST_CELLS
    selection_nesting_attested: bool = False

    def __post_init__(self) -> None:
        if not any((self.run_robust, self.run_resampling, self.run_stability)):
            raise ValueError("At least one sensitivity method must be enabled.")
        trim = float(self.trim_fraction)
        if not 0.0 <= trim < 0.5:
            raise ValueError("trim_fraction must be at least 0 and below 0.5.")
        if (
            isinstance(self.n_resamples, bool)
            or int(self.n_resamples) != self.n_resamples
            or not 1 <= int(self.n_resamples) <= MAX_SENSITIVITY_RESAMPLES
        ):
            raise ValueError(
                f"n_resamples must be between 1 and "
                f"{MAX_SENSITIVITY_RESAMPLES:,}."
            )
        if (
            isinstance(self.seed, bool)
            or int(self.seed) != self.seed
            or int(self.seed) < 0
        ):
            raise ValueError("seed must be a non-negative integer.")
        if (
            isinstance(self.exact_enumeration_limit, bool)
            or int(self.exact_enumeration_limit)
            != self.exact_enumeration_limit
            or int(self.exact_enumeration_limit) < 1
        ):
            raise ValueError(
                "exact_enumeration_limit must be a positive integer."
            )
        if (
            isinstance(self.max_robust_cells, bool)
            or int(self.max_robust_cells) != self.max_robust_cells
            or not 1 <= int(self.max_robust_cells) <= MAX_ROBUST_CELLS
        ):
            raise ValueError(
                f"max_robust_cells must be between 1 and {MAX_ROBUST_CELLS}."
            )
        object.__setattr__(self, "trim_fraction", trim)
        object.__setattr__(self, "n_resamples", int(self.n_resamples))
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(
            self,
            "exact_enumeration_limit",
            int(self.exact_enumeration_limit),
        )
        object.__setattr__(
            self,
            "max_robust_cells",
            int(self.max_robust_cells),
        )


def _require_payload(
    prepared_payload: PreparedAnalysisPayload,
) -> PreparedAnalysisPayload:
    if not isinstance(prepared_payload, PreparedAnalysisPayload):
        raise TypeError(
            "prepared_payload must be a PreparedAnalysisPayload produced by "
            "run_prepare_analysis."
        )
    return prepared_payload


def _copy_frames(
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    return {str(name): frame.copy(deep=True) for name, frame in frames.items()}


def _step_status_frame(
    *,
    payload: PreparedAnalysisPayload,
    step: str,
    status: str,
    status_code: str,
    message: str,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "prepared_worker_schema_version": PREPARED_WORKER_SCHEMA_VERSION,
                "preparation_id": payload.preparation_id,
                "step": step,
                "status": status,
                "status_code": status_code,
                "message": message,
            }
        ]
    )


def _response(
    *,
    payload: PreparedAnalysisPayload,
    step: str,
    status: str,
    status_code: str,
    message: str,
    frames: Mapping[str, pd.DataFrame] | None = None,
    primary_object: object | None = None,
) -> dict[str, object]:
    export_frames = _copy_frames(frames or payload.to_frames())
    export_frames["Step Status"] = _step_status_frame(
        payload=payload,
        step=step,
        status=status,
        status_code=status_code,
        message=message,
    )
    return {
        "status": status,
        "status_code": status_code,
        "message": message,
        "step": step,
        "preparation_id": payload.preparation_id,
        "prepared_payload": payload,
        "primary_object": primary_object,
        "result": primary_object,
        "export_frames": export_frames,
        "frames": _copy_frames(export_frames),
    }


def _blocked_response(
    payload: PreparedAnalysisPayload,
    *,
    step: str,
) -> dict[str, object] | None:
    if payload.ready:
        return None
    return _response(
        payload=payload,
        step=step,
        status="blocked",
        status_code=payload.status_code,
        message=(
            "The prepared design audit blocked downstream inference: "
            f"{payload.message}"
        ),
    )


def _mode_blocked_response(
    payload: PreparedAnalysisPayload,
    *,
    step: str,
    required_mode: AnalysisMode,
) -> dict[str, object] | None:
    if payload.mode is required_mode:
        return None
    return _response(
        payload=payload,
        step=step,
        status="blocked",
        status_code="analysis_mode_mismatch",
        message=(
            f"{step} requires {required_mode.value!r} mode, but the prepared "
            f"payload is {payload.mode.value!r}."
        ),
    )


def _is_cancelled(
    cancel_check: CancelCheck | None = None,
    cancel_token: object | None = None,
) -> bool:
    if cancel_check is not None and bool(cancel_check()):
        return True
    if cancel_token is None:
        return False
    if callable(cancel_token):
        return bool(cancel_token())
    for attribute in ("is_cancelled", "is_set", "cancelled"):
        if not hasattr(cancel_token, attribute):
            continue
        value = getattr(cancel_token, attribute)
        return bool(value() if callable(value) else value)
    return False


class _PreparationCancelled(RuntimeError):
    """Internal cooperative-cancellation sentinel for preparation."""

    def __init__(self, stage: str) -> None:
        self.stage = str(stage)
        super().__init__(self.stage)


def _raise_if_preparation_cancelled(
    cancel_check: CancelCheck | None,
    *,
    stage: str,
) -> None:
    if _is_cancelled(cancel_check):
        raise _PreparationCancelled(stage)


def _preparation_cancelled_response(stage: str) -> dict[str, object]:
    readable_stage = str(stage).replace("_", " ")
    return {
        "status": "cancelled",
        "status_code": "cancelled_during_preparation",
        "message": f"Analysis preparation was cancelled during {readable_stage}.",
        "step": "prepare_analysis",
        "cancellation_stage": str(stage),
        "preparation_id": "",
        "prepared_payload": None,
        "primary_object": None,
        "result": None,
        "export_frames": {},
        "frames": {},
    }


def _emit_progress(
    callback: ProgressCallback | None,
    completed: int,
    total: int,
) -> None:
    if callback is not None:
        callback(int(completed), int(total))


def _merged_frames(
    payload: PreparedAnalysisPayload,
    result_frames: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    frames = payload.to_frames()
    frames.update(_copy_frames(result_frames))
    return frames


def _worker_progress_adapter(
    progress_emit: Callable[[int], None] | None,
) -> ProgressCallback | None:
    if progress_emit is None:
        return None

    def adapted(completed: int, total: int) -> None:
        denominator = max(1, int(total))
        percent = int(round(100 * int(completed) / denominator))
        progress_emit(max(0, min(100, percent)))

    return adapted


def _resolve_step_invocation(
    progress_or_payload: object | None,
    message_emit: Callable[[str], None] | None,
    *,
    prepared_payload: PreparedAnalysisPayload | None,
    progress_callback: ProgressCallback | None,
) -> tuple[
    PreparedAnalysisPayload,
    ProgressCallback | None,
    Callable[[str], None],
]:
    if isinstance(progress_or_payload, PreparedAnalysisPayload):
        if prepared_payload is not None:
            raise ValueError(
                "prepared_payload was supplied both positionally and by keyword."
            )
        payload = progress_or_payload
        effective_progress = progress_callback
    else:
        if prepared_payload is None:
            raise TypeError("prepared_payload is required.")
        payload = prepared_payload
        effective_progress = progress_callback
        if effective_progress is None and callable(progress_or_payload):
            effective_progress = _worker_progress_adapter(progress_or_payload)
    message_callback = message_emit if callable(message_emit) else lambda _text: None
    return _require_payload(payload), effective_progress, message_callback


def _long_format_from_bca(
    nested: Mapping[object, Mapping[object, Mapping[object, object]]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for participant, conditions in nested.items():
        for condition, rois in conditions.items():
            for roi, value in rois.items():
                rows.append(
                    {
                        "subject": str(participant),
                        "condition": str(condition),
                        "roi": str(roi),
                        "value": (
                            float("nan") if pd.isna(value) else value
                        ),
                    }
                )
    return pd.DataFrame(
        rows,
        columns=["subject", "condition", "roi", "value"],
    )


def _default_run_spec(dv_policy: Mapping[str, object] | None) -> AnalysisRunSpec:
    policy = normalize_dv_policy(dict(dv_policy or {}))
    provenance = (
        HarmonicProvenance.SAME_SAMPLE_ADAPTIVE
        if policy.name == GROUP_SIGNIFICANT_POLICY_NAME
        else HarmonicProvenance.USER_FIXED_UNVERIFIED
    )
    return AnalysisRunSpec(
        profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        harmonic_provenance=provenance,
    )


def _normalized_preparation_kwargs(
    raw: Mapping[str, object],
    *,
    dv_policy: Mapping[str, object] | None,
) -> dict[str, object]:
    values = dict(raw)
    aliases = {
        "analysis_mode": "mode",
        "participant_group_ids": "canonical_group_ids",
        "canonical_groups": "canonical_group_ids",
        "group_pair": "selected_group_pair",
        "group_labels": "group_display_labels",
        "participants_map": "participant_display_labels",
        "group_map": "participant_display_labels",
    }
    for alias, canonical in aliases.items():
        if canonical not in values and alias in values:
            values[canonical] = values[alias]
        values.pop(alias, None)
    alpha = values.pop("alpha", None)
    profile = values.pop("analysis_profile", None)
    provenance = values.pop("harmonic_provenance", None)
    if "run_spec" not in values:
        run_spec = _default_run_spec(dv_policy)
        changes: dict[str, object] = {}
        if alpha is not None:
            changes["alpha"] = float(alpha)
        if profile is not None:
            changes["profile"] = profile
        if provenance is not None:
            changes["harmonic_provenance"] = provenance
        values["run_spec"] = replace(run_spec, **changes)
    values.setdefault(
        "mode",
        (
            AnalysisMode.MULTI.value
            if values.get("canonical_group_ids")
            else AnalysisMode.SINGLE.value
        ),
    )
    allowed = {
        "mode",
        "run_spec",
        "dv_col",
        "subject_col",
        "condition_col",
        "roi_col",
        "group_col",
        "frozen_participants",
        "selected_conditions",
        "selected_rois",
        "canonical_group_ids",
        "group_display_labels",
        "participant_display_labels",
        "selected_group_pair",
        "settings",
        "preparation_id",
        "analysis_scope",
    }
    return {key: value for key, value in values.items() if key in allowed}


def _prepare_project_long_data(
    *,
    subjects: Sequence[object],
    conditions: Sequence[object],
    conditions_all: Sequence[object] | None,
    subject_data: Mapping[object, object],
    base_freq: float,
    rois: Mapping[object, object],
    rois_all: Mapping[object, object] | None,
    dv_policy: Mapping[str, object] | None,
    outlier_abs_limit: float,
    qc_config: Mapping[str, object] | None,
    qc_state: dict[str, object] | None,
    manual_excluded_pids: Sequence[object] | None,
    max_freq: float | None,
    project_root: str | None,
    message_emit: Callable[[str], None],
    progress_callback: ProgressCallback | None,
    cancel_check: CancelCheck | None = None,
    analysis_scope: str = "complete_core",
) -> tuple[pd.DataFrame, list[str], dict[str, object]]:
    scope = str(analysis_scope).strip().casefold().replace("-", "_")
    if scope not in {"complete_core", "available_case"}:
        raise ValueError(
            "analysis_scope must be 'complete_core' or 'available_case'."
        )
    selected_subjects = [str(value) for value in subjects]
    excluded = {
        str(value)
        for value in (manual_excluded_pids or ())
        if str(value) in set(selected_subjects)
    }
    selected_subjects = [
        participant
        for participant in selected_subjects
        if participant not in excluded
    ]
    if not selected_subjects:
        raise RuntimeError("All participants are manually excluded.")
    selected_subject_data = {
        str(participant): value
        for participant, value in subject_data.items()
        if str(participant) in set(selected_subjects)
    }
    _raise_if_preparation_cancelled(cancel_check, stage="before_qc")
    _emit_progress(progress_callback, 1, 5)
    config = dict(qc_config or {})
    if (
        qc_state is not None
        and isinstance(qc_state.get("report"), QcExclusionReport)
    ):
        qc_report = qc_state["report"]
    else:
        qc_report = run_qc_exclusion(
            subjects=selected_subjects,
            subject_data=selected_subject_data,
            conditions_all=[str(value) for value in (conditions_all or ())],
            rois_all=dict(rois_all or rois),
            base_freq=float(base_freq),
            warn_threshold=float(
                config.get("warn_threshold", QC_DEFAULT_WARN_THRESHOLD)
            ),
            critical_threshold=float(
                config.get(
                    "critical_threshold",
                    QC_DEFAULT_CRITICAL_THRESHOLD,
                )
            ),
            warn_abs_floor_sumabs=float(
                config.get(
                    "warn_abs_floor_sumabs",
                    QC_DEFAULT_WARN_ABS_FLOOR_SUMABS,
                )
            ),
            critical_abs_floor_sumabs=float(
                config.get(
                    "critical_abs_floor_sumabs",
                    QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS,
                )
            ),
            warn_abs_floor_maxabs=float(
                config.get(
                    "warn_abs_floor_maxabs",
                    QC_DEFAULT_WARN_ABS_FLOOR_MAXABS,
                )
            ),
            critical_abs_floor_maxabs=float(
                config.get(
                    "critical_abs_floor_maxabs",
                    QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS,
                )
            ),
            log_func=message_emit,
        )
        if qc_state is not None:
            qc_state["report"] = qc_report
    _raise_if_preparation_cancelled(cancel_check, stage="after_qc")
    settings = normalize_dv_policy(dict(dv_policy or {}))
    if settings.name == GROUP_SIGNIFICANT_POLICY_NAME:
        _raise_if_preparation_cancelled(
            cancel_check,
            stage="before_adaptive_preflight",
        )
        request = build_group_harmonic_cache_request(
            project_root=project_root,
            subjects=selected_subjects,
            conditions=[str(value) for value in conditions],
            subject_data=selected_subject_data,
            rois=dict(rois),
            base_frequency_hz=float(base_freq),
            max_freq_hz=max_freq,
            settings=settings,
        )
        if lookup_cached_group_harmonic_selection(request).hit is None:
            preflight_group_significant_full_fft_columns(
                subjects=selected_subjects,
                conditions=[str(value) for value in conditions],
                subject_data=selected_subject_data,
                base_frequency_hz=float(base_freq),
                log_func=message_emit,
                max_freq=max_freq,
            )
        else:
            message_emit(
                "Project metadata contains matching significant harmonics; "
                "skipping FullFFT preflight."
            )
        _raise_if_preparation_cancelled(
            cancel_check,
            stage="after_adaptive_preflight",
        )
    _emit_progress(progress_callback, 2, 5)
    _raise_if_preparation_cancelled(
        cancel_check,
        stage="before_summed_bca",
    )
    dv_metadata: dict[str, object] = {}
    nested = prepare_summed_bca_data(
        subjects=selected_subjects,
        conditions=[str(value) for value in conditions],
        subject_data=selected_subject_data,
        base_freq=float(base_freq),
        log_func=message_emit,
        rois=dict(rois),
        dv_policy=dict(dv_policy or {}),
        dv_metadata=dv_metadata,
        max_freq=max_freq,
        selection_conditions=[str(value) for value in conditions],
        project_root=project_root,
    )
    _raise_if_preparation_cancelled(
        cancel_check,
        stage="after_summed_bca",
    )
    if not nested:
        raise RuntimeError("Summed-BCA preparation returned no data.")
    _emit_progress(progress_callback, 3, 5)
    long_data = _long_format_from_bca(nested)
    missing_source_pairs: list[dict[str, str]] = []
    if scope == "available_case":
        available_pairs: set[tuple[str, str]] = set()
        for participant in selected_subjects:
            participant_sources = selected_subject_data.get(participant, {})
            if not isinstance(participant_sources, Mapping):
                participant_sources = {}
            sources_by_condition = {
                str(key).strip().casefold(): value
                for key, value in participant_sources.items()
            }
            for condition in (str(value) for value in conditions):
                source = sources_by_condition.get(
                    condition.strip().casefold()
                )
                source_exists = bool(source) and Path(str(source)).is_file()
                if source_exists:
                    available_pairs.add(
                        (participant.casefold(), condition.casefold())
                    )
                else:
                    missing_source_pairs.append(
                        {
                            "participant_id": participant,
                            "condition": condition,
                            "reason": "source_workbook_absent",
                            "source_path": "" if source is None else str(source),
                        }
                    )
        row_pairs = pd.Series(
            list(
                zip(
                    long_data["subject"].astype(str).str.casefold(),
                    long_data["condition"].astype(str).str.casefold(),
                )
            ),
            index=long_data.index,
        )
        long_data = long_data.loc[
            row_pairs.map(lambda pair: pair in available_pairs)
        ].copy()
        if long_data.empty:
            raise RuntimeError(
                "No existing source workbooks contributed available-case "
                "Summed-BCA rows."
            )
    _raise_if_preparation_cancelled(
        cancel_check,
        stage="before_hard_dv_filter",
    )
    numeric_values = pd.to_numeric(long_data["value"], errors="coerce")
    finite_mask = np.isfinite(numeric_values.to_numpy(dtype=float))
    finite_data = long_data.loc[finite_mask].copy()
    _, outlier_report = apply_hard_dv_exclusion(
        finite_data,
        float(outlier_abs_limit),
        participant_col="subject",
        condition_col="condition",
        roi_col="roi",
        value_col="value",
    )
    _raise_if_preparation_cancelled(
        cancel_check,
        stage="after_hard_dv_filter",
    )
    nonfinite_cells = int((~finite_mask).sum())
    if finite_data.empty:
        raise RuntimeError(
            "Summed BCA produced no finite values for the selected "
            "conditions and ROIs."
        )
    if nonfinite_cells:
        message_emit(
            f"Summed BCA contains {nonfinite_cells} missing or non-finite "
            "Condition x ROI cell(s). The frozen participant cohort was "
            "preserved; the selected analysis scope will determine which "
            "conditions and finite observations are usable."
        )
    _emit_progress(progress_callback, 4, 5)
    preparation_metadata = {
        "dv_metadata": dv_metadata,
        "manual_excluded_pids": sorted(excluded),
        "qc_report": qc_report,
        "outlier_report": outlier_report,
        "project_input_prepared": True,
        "analysis_scope": scope,
        "nonfinite_dv_cells": nonfinite_cells,
        "nonfinite_dv_handling": "analysis_scope",
        "missing_source_workbooks": missing_source_pairs,
    }
    return long_data, selected_subjects, preparation_metadata


def run_prepare_analysis(
    progress_or_data: object | None = None,
    message_emit: Callable[[str], None] | None = None,
    *,
    data: pd.DataFrame | None = None,
    prepared_payload: PreparedAnalysisPayload | None = None,
    progress_callback: ProgressCallback | None = None,
    subjects: Sequence[object] | None = None,
    conditions: Sequence[object] | None = None,
    conditions_all: Sequence[object] | None = None,
    subject_data: Mapping[object, object] | None = None,
    base_freq: float | None = None,
    rois: Mapping[object, object] | None = None,
    rois_all: Mapping[object, object] | None = None,
    dv_policy: Mapping[str, object] | None = None,
    outlier_exclusion_enabled: bool = True,
    outlier_abs_limit: float = 50.0,
    qc_config: Mapping[str, object] | None = None,
    qc_state: dict[str, object] | None = None,
    manual_excluded_pids: Sequence[object] | None = None,
    max_freq: float | None = None,
    project_root: str | None = None,
    cancel_check: CancelCheck | None = None,
    **preparation_kwargs: object,
) -> dict[str, object]:
    """Build/reuse a payload from long data or project-level Stats inputs."""

    worker_progress = progress_callback
    message_callback = (
        message_emit if callable(message_emit) else lambda _text: None
    )
    if _is_cancelled(cancel_check):
        response = _preparation_cancelled_response("before_preparation")
        message_callback(str(response["message"]))
        return response
    if isinstance(progress_or_data, pd.DataFrame):
        if data is not None:
            raise ValueError("data was supplied both positionally and by keyword.")
        data = progress_or_data
    elif callable(progress_or_data) and worker_progress is None:
        worker_progress = _worker_progress_adapter(progress_or_data)
    try:
        if prepared_payload is not None:
            payload = _require_payload(prepared_payload)
            if data is not None or subjects is not None or preparation_kwargs:
                raise ValueError(
                    "Do not supply data or preparation settings when reusing an "
                    "existing prepared_payload."
                )
        else:
            if data is None:
                required_project = {
                    "subjects": subjects,
                    "conditions": conditions,
                    "subject_data": subject_data,
                    "base_freq": base_freq,
                    "rois": rois,
                }
                missing = [
                    name
                    for name, value in required_project.items()
                    if value is None
                ]
                if missing:
                    raise TypeError(
                        "Long-format data or complete project inputs are required; "
                        "missing: " + ", ".join(missing)
                    )
                data, frozen, project_metadata = _prepare_project_long_data(
                    subjects=subjects or (),
                    conditions=conditions or (),
                    conditions_all=conditions_all,
                    subject_data=subject_data or {},
                    base_freq=float(base_freq),
                    rois=rois or {},
                    rois_all=rois_all,
                    dv_policy=dv_policy,
                    outlier_abs_limit=float(outlier_abs_limit),
                    qc_config=qc_config,
                    qc_state=qc_state,
                    manual_excluded_pids=manual_excluded_pids,
                    max_freq=max_freq,
                    project_root=project_root,
                    message_emit=message_callback,
                    progress_callback=worker_progress,
                    cancel_check=cancel_check,
                    analysis_scope=str(
                        preparation_kwargs.get(
                            "analysis_scope",
                            "complete_core",
                        )
                    ),
                )
                preparation_kwargs.setdefault("dv_col", "value")
                preparation_kwargs.setdefault("subject_col", "subject")
                preparation_kwargs.setdefault("condition_col", "condition")
                preparation_kwargs.setdefault("roi_col", "roi")
                preparation_kwargs.setdefault("frozen_participants", frozen)
                preparation_kwargs.setdefault("selected_conditions", conditions)
                preparation_kwargs.setdefault(
                    "selected_rois",
                    list((rois or {}).keys()),
                )
                retained_settings = dict(
                    preparation_kwargs.get("settings", {}) or {}
                )
                retained_settings.update(project_metadata)
                retained_settings["outlier_exclusion_enabled"] = bool(
                    outlier_exclusion_enabled
                )
                preparation_kwargs["settings"] = retained_settings
            _raise_if_preparation_cancelled(
                cancel_check,
                stage="before_design_audit",
            )
            normalized_kwargs = _normalized_preparation_kwargs(
                preparation_kwargs,
                dv_policy=dv_policy,
            )
            payload = prepare_analysis_payload(data, **normalized_kwargs)
            _raise_if_preparation_cancelled(
                cancel_check,
                stage="after_design_audit",
            )
    except _PreparationCancelled as exc:
        response = _preparation_cancelled_response(exc.stage)
        message_callback(str(response["message"]))
        return response
    _emit_progress(worker_progress, 5, 5)
    return _response(
        payload=payload,
        step="prepare_analysis",
        status=payload.audit_status,
        status_code=payload.status_code,
        message=payload.message,
        primary_object=payload,
    )


def run_multigroup_model_step(
    progress_or_payload: object | None = None,
    message_emit: Callable[[str], None] | None = None,
    *,
    prepared_payload: PreparedAnalysisPayload | None = None,
    random_slope_formula: str | None = None,
    optimizers: Sequence[str] = ("lbfgs", "powell"),
    maxiter: int = 1000,
    singularity_tolerance: float = 1e-10,
    ci_level: float = 0.95,
    marginal_grid: pd.DataFrame | None = None,
    reference_group_id: object | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    **_ignored: object,
) -> dict[str, object]:
    """Run the native multi-group mixed model on one prepared payload."""

    payload, progress_callback, message_callback = _resolve_step_invocation(
        progress_or_payload,
        message_emit,
        prepared_payload=prepared_payload,
        progress_callback=progress_callback,
    )
    step = "multigroup_model"
    blocked = _blocked_response(payload, step=step)
    if blocked is not None:
        return blocked
    wrong_mode = _mode_blocked_response(
        payload,
        step=step,
        required_mode=AnalysisMode.MULTI,
    )
    if wrong_mode is not None:
        return wrong_mode
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step=step,
            status="cancelled",
            status_code="cancelled_before_start",
            message="The multi-group model was cancelled before it started.",
        )
    _emit_progress(progress_callback, 0, 1)
    message_callback("Running the prepared native multi-group mixed model.")
    try:
        result = run_multigroup_mixed_model(
            payload.primary_data,
            dv_col=payload.dv_col,
            participant_col=payload.subject_col,
            group_col=payload.group_col,
            condition_col=payload.condition_col,
            roi_col=payload.roi_col,
            known_group_ids=payload.canonical_group_levels,
            random_slope_formula=random_slope_formula,
            optimizers=optimizers,
            maxiter=maxiter,
            singularity_tolerance=singularity_tolerance,
            ci_level=ci_level,
            marginal_grid=marginal_grid,
            reference_group_id=reference_group_id,
            analysis_scope=payload.analysis_scope,
        )
        corrected_omnibus = _apply_strict_omnibus_correction(
            payload,
            result.omnibus,
            p_col="p_value_chi2",
        )
        result = replace(result, omnibus=corrected_omnibus)
    except Exception as exc:
        return _response(
            payload=payload,
            step=step,
            status="failed",
            status_code="multigroup_model_failed",
            message=f"{type(exc).__name__}: {exc}",
        )
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step=step,
            status="cancelled",
            status_code="cancelled_after_fit",
            message=(
                "Cancellation was requested during the model fit; fitted "
                "inference was not returned."
            ),
        )
    _emit_progress(progress_callback, 1, 1)
    message = (
        "The multi-group mixed model completed."
        if result.status == "ok"
        else f"The multi-group mixed model completed with status {result.status!r}."
    )
    return _response(
        payload=payload,
        step=step,
        status=result.status,
        status_code=f"multigroup_model_{result.status}",
        message=message,
        frames=_merged_frames(payload, result.to_frames()),
        primary_object=result,
    )


def run_group_cell_step(
    progress_or_payload: object | None = None,
    message_emit: Callable[[str], None] | None = None,
    *,
    prepared_payload: PreparedAnalysisPayload | None = None,
    group_pair: Sequence[object] | None = None,
    correction: object = "holm",
    alpha: float | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    **_ignored: object,
) -> dict[str, object]:
    """Run Welch cell contrasts under the prepared missing-data scope."""

    payload, progress_callback, message_callback = _resolve_step_invocation(
        progress_or_payload,
        message_emit,
        prepared_payload=prepared_payload,
        progress_callback=progress_callback,
    )
    step = "group_cell_comparisons"
    blocked = _blocked_response(payload, step=step)
    if blocked is not None:
        return blocked
    wrong_mode = _mode_blocked_response(
        payload,
        step=step,
        required_mode=AnalysisMode.MULTI,
    )
    if wrong_mode is not None:
        return wrong_mode
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step=step,
            status="cancelled",
            status_code="cancelled_before_start",
            message="Group-cell comparisons were cancelled before they started.",
        )
    _emit_progress(progress_callback, 0, 1)
    message_callback(
        f"Running prepared {payload.analysis_scope.replace('_', '-')} "
        "group-cell comparisons."
    )
    selected_pair = group_pair or payload.selected_group_pair
    try:
        result = _run_group_cell_comparisons(
            payload.primary_data,
            dv_col=payload.dv_col,
            subject_col=payload.subject_col,
            group_col=payload.group_col,
            condition_col=payload.condition_col,
            roi_col=payload.roi_col,
            group_pair=selected_pair,
            correction=correction,
            alpha=payload.run_spec.alpha if alpha is None else float(alpha),
            analysis_scope=payload.analysis_scope,
        )
    except Exception as exc:
        return _response(
            payload=payload,
            step=step,
            status="failed",
            status_code="group_cell_comparisons_failed",
            message=f"{type(exc).__name__}: {exc}",
        )
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step=step,
            status="cancelled",
            status_code="cancelled_after_comparisons",
            message=(
                "Cancellation was requested during group-cell comparisons; "
                "inferential results were not returned."
            ),
        )
    _emit_progress(progress_callback, 1, 1)
    return _response(
        payload=payload,
        step=step,
        status="ok",
        status_code="group_cell_comparisons_ok",
        message=(
            f"{payload.analysis_scope.replace('_', '-').title()} "
            "group-cell comparisons completed."
        ),
        frames=_merged_frames(payload, result.to_frames()),
        primary_object=result,
    )


def _resolve_sensitivity_config(
    payload: PreparedAnalysisPayload,
    config: SensitivityConfig | Mapping[str, object] | None,
    overrides: Mapping[str, object],
) -> SensitivityConfig:
    retained = payload.settings.get("sensitivity", {})
    values: dict[str, object] = {}
    if isinstance(retained, Mapping):
        values.update(retained)
    if isinstance(config, SensitivityConfig):
        resolved = config
    else:
        if config is not None:
            if not isinstance(config, Mapping):
                raise TypeError(
                    "config must be a SensitivityConfig or mapping."
                )
            values.update(config)
        allowed = set(SensitivityConfig.__dataclass_fields__)
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(
                "Unknown sensitivity settings: " + ", ".join(unknown)
            )
        resolved = SensitivityConfig(**values)
    selected_overrides = {
        key: value for key, value in overrides.items() if value is not None
    }
    if selected_overrides:
        resolved = replace(resolved, **selected_overrides)
    return resolved


def _resolve_pair(payload: PreparedAnalysisPayload) -> tuple[str, str]:
    if payload.selected_group_pair is not None:
        return payload.selected_group_pair
    groups = payload.canonical_group_levels
    if len(groups) != 2:
        raise ValueError(
            "A selected_group_pair is required when the prepared cohort "
            "contains other than two canonical groups."
        )
    return groups[0], groups[1]


def _robust_frames(
    payload: PreparedAnalysisPayload,
    *,
    config: SensitivityConfig,
    cancel_check: CancelCheck | None,
    progress_callback: ProgressCallback | None,
) -> tuple[dict[str, pd.DataFrame], bool]:
    data = payload.primary_data
    cell_groups = list(
        data.groupby(
            [payload.condition_col, payload.roi_col],
            sort=True,
            dropna=False,
        )
    )
    if len(cell_groups) > config.max_robust_cells:
        raise ValueError(
            f"The robust sensitivity requested {len(cell_groups)} cells, "
            f"above the configured bound of {config.max_robust_cells}."
        )
    result_rows: list[pd.DataFrame] = []
    inventory_rows: list[pd.DataFrame] = []
    warnings_rows: list[pd.DataFrame] = []
    total = max(1, len(cell_groups))
    pair = _resolve_pair(payload) if payload.mode is AnalysisMode.MULTI else None
    for index, ((condition, roi), cell) in enumerate(cell_groups):
        if _is_cancelled(cancel_check):
            return {}, True
        if pair is None:
            robust_results = (
                run_one_sample_trimmed_mean_test(
                    cell[payload.dv_col],
                    trim_fraction=config.trim_fraction,
                    run_spec=payload.run_spec,
                ),
                run_one_sample_wilcoxon_test(
                    cell[payload.dv_col],
                    run_spec=payload.run_spec,
                ),
            )
        else:
            group_a, group_b = pair
            normalized = (
                cell[payload.group_col].astype(str).str.strip().str.casefold()
            )
            robust_results = (
                run_two_group_trimmed_mean_test(
                    cell.loc[
                        normalized.eq(group_a.casefold()),
                        payload.dv_col,
                    ],
                    cell.loc[
                        normalized.eq(group_b.casefold()),
                        payload.dv_col,
                    ],
                    group_a_label=group_a,
                    group_b_label=group_b,
                    trim_fraction=config.trim_fraction,
                    run_spec=payload.run_spec,
                ),
            )
        for robust_result in robust_results:
            result_frame = robust_result.results.copy()
            result_frame.insert(0, "roi", roi)
            result_frame.insert(0, "condition", condition)
            result_rows.append(result_frame)
            metadata_frames = robust_result.analysis_metadata.to_frames()
            inventory = metadata_frames["Test Inventory"].copy()
            inventory.insert(0, "roi", roi)
            inventory.insert(0, "condition", condition)
            inventory_rows.append(inventory)
            warnings_frame = metadata_frames["Warnings"].copy()
            if not warnings_frame.empty:
                warnings_frame.insert(0, "roi", roi)
                warnings_frame.insert(0, "condition", condition)
                warnings_rows.append(warnings_frame)
        _emit_progress(progress_callback, index + 1, total)
    frames = {
        "Robust Sensitivity Results": (
            pd.concat(result_rows, ignore_index=True)
            if result_rows
            else pd.DataFrame()
        ),
        "Robust Test Inventory": (
            pd.concat(inventory_rows, ignore_index=True)
            if inventory_rows
            else pd.DataFrame()
        ),
        "Robust Warnings": (
            pd.concat(warnings_rows, ignore_index=True)
            if warnings_rows
            else pd.DataFrame(columns=["condition", "roi", "warning"])
        ),
    }
    return frames, False


def _resampling_frames(
    payload: PreparedAnalysisPayload,
    *,
    config: SensitivityConfig,
    cancel_check: CancelCheck | None,
    progress_callback: ProgressCallback | None,
) -> tuple[dict[str, pd.DataFrame], bool, object]:
    common = {
        "dv_col": payload.dv_col,
        "subject_col": payload.subject_col,
        "cell_cols": (payload.condition_col, payload.roi_col),
        "n_resamples": config.n_resamples,
        "seed": config.seed,
        "exact_enumeration_limit": config.exact_enumeration_limit,
        "alpha": payload.run_spec.alpha,
        "harmonic_provenance": payload.run_spec.harmonic_provenance,
        "selection_nesting_attested": config.selection_nesting_attested,
        "cancel_check": cancel_check,
        "progress_callback": progress_callback,
    }
    if payload.mode is AnalysisMode.MULTI:
        result = run_group_label_permutation_max_t(
            payload.primary_data,
            group_col=payload.group_col,
            group_pair=_resolve_pair(payload),
            **common,
        )
    else:
        result = run_one_sample_sign_flip_max_t(
            payload.primary_data,
            **common,
        )
    cancelled = bool(
        not result.metadata.empty
        and "overall_status" in result.metadata.columns
        and result.metadata["overall_status"].astype(str).eq("cancelled").any()
    )
    return result.to_frames(), cancelled, result


def _stability_frames(
    payload: PreparedAnalysisPayload,
) -> tuple[dict[str, pd.DataFrame], object]:
    common = {
        "dv_col": payload.dv_col,
        "subject_col": payload.subject_col,
        "condition_col": payload.condition_col,
        "roi_col": payload.roi_col,
        "alpha": payload.run_spec.alpha,
        "analysis_scope": payload.analysis_scope,
    }
    if payload.mode is AnalysisMode.MULTI:
        result = run_two_group_leave_one_out_stability(
            payload.primary_data,
            group_col=payload.group_col,
            group_pair=_resolve_pair(payload),
            **common,
        )
    else:
        result = run_one_sample_leave_one_out_stability(
            payload.primary_data,
            **common,
        )
    return result.to_frames(), result


def run_sensitivity_step(
    progress_or_payload: object | None = None,
    message_emit: Callable[[str], None] | None = None,
    *,
    prepared_payload: PreparedAnalysisPayload | None = None,
    config: SensitivityConfig | Mapping[str, object] | None = None,
    run_robust: bool | None = None,
    run_resampling: bool | None = None,
    run_stability: bool | None = None,
    trim_fraction: float | None = None,
    n_resamples: int | None = None,
    seed: int | None = None,
    exact_enumeration_limit: int | None = None,
    max_robust_cells: int | None = None,
    selection_nesting_attested: bool | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    **_ignored: object,
) -> dict[str, object]:
    """Run bounded robust, resampling, and leave-one-out sensitivities."""

    payload, progress_callback, message_callback = _resolve_step_invocation(
        progress_or_payload,
        message_emit,
        prepared_payload=prepared_payload,
        progress_callback=progress_callback,
    )
    step = "sensitivity_analyses"
    blocked = _blocked_response(payload, step=step)
    if blocked is not None:
        return blocked
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step=step,
            status="cancelled",
            status_code="cancelled_before_start",
            message="Sensitivity analyses were cancelled before they started.",
        )
    try:
        message_callback("Running requested prepared-data sensitivities.")
        resolved = _resolve_sensitivity_config(
            payload,
            config,
            {
                "run_robust": run_robust,
                "run_resampling": run_resampling,
                "run_stability": run_stability,
                "trim_fraction": trim_fraction,
                "n_resamples": n_resamples,
                "seed": seed,
                "exact_enumeration_limit": exact_enumeration_limit,
                "max_robust_cells": max_robust_cells,
                "selection_nesting_attested": selection_nesting_attested,
            },
        )
        enabled = [
            name
            for name, active in (
                ("robust", resolved.run_robust),
                (
                    "resampling",
                    resolved.run_resampling
                    and payload.analysis_scope != "available_case",
                ),
                ("stability", resolved.run_stability),
            )
            if active
        ]
        frames = payload.to_frames()
        resampling_suppressed = bool(
            resolved.run_resampling
            and payload.analysis_scope == "available_case"
        )
        if resampling_suppressed:
            frames["Resampling Metadata"] = pd.DataFrame(
                [
                    {
                        "overall_status": "not_run",
                        "status_code": (
                            "incompatible_with_available_case_scope"
                        ),
                        "status_message": (
                            "The current participant-level max-|t| "
                            "resampling method requires a complete "
                            "participant x Condition x ROI matrix. It was "
                            "not run on the available-case LMM cohort."
                        ),
                        "analysis_scope": payload.analysis_scope,
                        "missing_values_imputed": False,
                    }
                ]
            )
        primary_objects: dict[str, object] = {}
        for stage_index, method in enumerate(enabled):
            if _is_cancelled(cancel_check):
                return _response(
                    payload=payload,
                    step=step,
                    status="cancelled",
                    status_code="cancelled_between_methods",
                    message=(
                        "Sensitivity analyses were cancelled between methods; "
                        "partial results were not returned."
                    ),
                )

            def stage_progress(completed: int, total: int) -> None:
                if progress_callback is None:
                    return
                within = 0.0 if total <= 0 else completed / total
                scaled = int(round((stage_index + within) * 1000))
                progress_callback(scaled, len(enabled) * 1000)

            if method == "robust":
                robust_frames, cancelled = _robust_frames(
                    payload,
                    config=resolved,
                    cancel_check=cancel_check,
                    progress_callback=stage_progress,
                )
                if cancelled:
                    return _response(
                        payload=payload,
                        step=step,
                        status="cancelled",
                        status_code="cancelled_during_robust_tests",
                        message=(
                            "Robust sensitivity tests were cancelled; partial "
                            "results were not returned."
                        ),
                    )
                frames.update(robust_frames)
            elif method == "resampling":
                resampling_frames, cancelled, resampling_result = (
                    _resampling_frames(
                        payload,
                        config=resolved,
                        cancel_check=cancel_check,
                        progress_callback=stage_progress,
                    )
                )
                if cancelled:
                    return _response(
                        payload=payload,
                        step=step,
                        status="cancelled",
                        status_code="cancelled_during_resampling",
                        message=(
                            "Participant-level resampling was cancelled; "
                            "partial p-values were not returned."
                        ),
                        frames=_merged_frames(payload, resampling_frames),
                        primary_object={"resampling": resampling_result},
                    )
                frames.update(resampling_frames)
                primary_objects["resampling"] = resampling_result
            else:
                stability_frames, stability_result = _stability_frames(payload)
                frames.update(stability_frames)
                primary_objects["stability"] = stability_result
                stage_progress(1, 1)
        frames["Sensitivity Settings"] = pd.DataFrame(
            [
                {
                    "run_robust": resolved.run_robust,
                    "run_resampling": resolved.run_resampling,
                    "run_resampling_effective": (
                        resolved.run_resampling
                        and not resampling_suppressed
                    ),
                    "resampling_suppressed_reason": (
                        "incompatible_with_available_case_scope"
                        if resampling_suppressed
                        else ""
                    ),
                    "run_stability": resolved.run_stability,
                    "trim_fraction": resolved.trim_fraction,
                    "n_resamples": resolved.n_resamples,
                    "seed": resolved.seed,
                    "exact_enumeration_limit": (
                        resolved.exact_enumeration_limit
                    ),
                    "max_robust_cells": resolved.max_robust_cells,
                    "selection_nesting_attested": (
                        resolved.selection_nesting_attested
                    ),
                }
            ]
        )
    except Exception as exc:
        return _response(
            payload=payload,
            step=step,
            status="failed",
            status_code="sensitivity_analyses_failed",
            message=f"{type(exc).__name__}: {exc}",
        )
    _emit_progress(progress_callback, 1, 1)
    return _response(
        payload=payload,
        step=step,
        status="ok",
        status_code="sensitivity_analyses_ok",
        message="Requested sensitivity analyses completed.",
        frames=frames,
        primary_object=primary_objects,
    )


def _single_step_start(
    progress_or_payload: object | None,
    message_emit: Callable[[str], None] | None,
    *,
    prepared_payload: PreparedAnalysisPayload | None,
    progress_callback: ProgressCallback | None,
    step: str,
) -> tuple[
    PreparedAnalysisPayload,
    ProgressCallback | None,
    Callable[[str], None],
    dict[str, object] | None,
]:
    payload, progress, message = _resolve_step_invocation(
        progress_or_payload,
        message_emit,
        prepared_payload=prepared_payload,
        progress_callback=progress_callback,
    )
    blocked = _blocked_response(payload, step=step)
    if blocked is None:
        blocked = _mode_blocked_response(
            payload,
            step=step,
            required_mode=AnalysisMode.SINGLE,
        )
    return payload, progress, message, blocked


def _single_frames(
    payload: PreparedAnalysisPayload,
    **named_frames: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    return _merged_frames(payload, named_frames)


def run_single_rm_anova_step(
    progress_or_payload: object | None = None,
    message_emit: Callable[[str], None] | None = None,
    *,
    prepared_payload: PreparedAnalysisPayload | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    **_ignored: object,
) -> dict[str, object]:
    """Run RM-ANOVA directly on the frozen single-group complete core."""

    payload, progress, message, blocked = _single_step_start(
        progress_or_payload,
        message_emit,
        prepared_payload=prepared_payload,
        progress_callback=progress_callback,
        step="single_rm_anova",
    )
    if blocked is not None:
        return blocked
    if payload.analysis_scope == "available_case":
        return _response(
            payload=payload,
            step="single_rm_anova",
            status="blocked",
            status_code="rm_anova_requires_complete_core",
            message=(
                "RM-ANOVA was not run because available-case data may contain "
                "missing participant conditions. Use the mixed model result."
            ),
        )
    if len(payload.complete_conditions) < 2:
        return _response(
            payload=payload,
            step="single_rm_anova",
            status="blocked",
            status_code="rm_anova_requires_two_conditions",
            message=(
                "RM-ANOVA requires at least two conditions retained for the "
                "frozen participant cohort."
            ),
        )
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step="single_rm_anova",
            status="cancelled",
            status_code="cancelled_before_start",
            message="RM-ANOVA was cancelled before it started.",
        )
    _emit_progress(progress, 0, 1)
    message("Running RM-ANOVA on the prepared complete-core data.")
    try:
        result = run_repeated_measures_anova(
            payload.primary_data,
            dv_col=payload.dv_col,
            within_cols=[payload.condition_col, payload.roi_col],
            subject_col=payload.subject_col,
            raw_df=payload.primary_data,
            log_func=message,
        )
        result = _apply_strict_omnibus_correction(
            payload,
            result,
            p_col="p_reported",
        )
    except Exception as exc:
        return _response(
            payload=payload,
            step="single_rm_anova",
            status="failed",
            status_code="rm_anova_failed",
            message=f"{type(exc).__name__}: {exc}",
        )
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step="single_rm_anova",
            status="cancelled",
            status_code="cancelled_after_fit",
            message="Cancellation was requested during RM-ANOVA.",
        )
    _emit_progress(progress, 1, 1)
    response = _response(
        payload=payload,
        step="single_rm_anova",
        status="ok",
        status_code="rm_anova_ok",
        message="Prepared-data RM-ANOVA completed.",
        frames=_single_frames(payload, **{"RM ANOVA": result}),
        primary_object=result,
    )
    response.update(
        {
            "anova_df_results": result,
            "output_text": result.to_string(index=False),
            "dv_metadata": payload.settings.get("dv_metadata", {}),
            "design_frames": payload.design_frames,
        }
    )
    return response


def run_single_lmm_step(
    progress_or_payload: object | None = None,
    message_emit: Callable[[str], None] | None = None,
    *,
    prepared_payload: PreparedAnalysisPayload | None = None,
    alpha: float | None = None,
    re_formula: str = "1",
    method: str = "reml",
    ci_level: float = 0.95,
    followup_provenance: object | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    **_ignored: object,
) -> dict[str, object]:
    """Run the single-group LMM on the prepared analysis rows."""

    payload, progress, message, blocked = _single_step_start(
        progress_or_payload,
        message_emit,
        prepared_payload=prepared_payload,
        progress_callback=progress_callback,
        step="single_lmm",
    )
    if blocked is not None:
        return blocked
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step="single_lmm",
            status="cancelled",
            status_code="cancelled_before_start",
            message="The single-group mixed model was cancelled before it started.",
        )
    _emit_progress(progress, 0, 1)
    message("Running the single-group mixed model on prepared data.")
    try:
        mixed_results, fitted_model = run_mixed_effects_model(
            data=payload.primary_data,
            dv_col=payload.dv_col,
            group_col=payload.subject_col,
            fixed_effects=[
                f"{payload.condition_col} * {payload.roi_col}"
            ],
            re_formula=re_formula,
            method=method,
            ci_level=float(ci_level),
            return_model=True,
            do_lrt=True,
            analysis_scope=payload.analysis_scope,
            cell_cols=(
                payload.condition_col,
                payload.roi_col,
            ),
        )
    except Exception as exc:
        return _response(
            payload=payload,
            step="single_lmm",
            status="failed",
            status_code="single_lmm_failed",
            message=f"{type(exc).__name__}: {exc}",
        )
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step="single_lmm",
            status="cancelled",
            status_code="cancelled_after_fit",
            message="Cancellation was requested during the single-group model.",
        )
    _emit_progress(progress, 1, 1)
    lrt_table = mixed_results.attrs.get("lrt_table")
    frames = {"Mixed Model": mixed_results}
    if isinstance(lrt_table, pd.DataFrame):
        lrt_table = _apply_single_primary_omnibus_correction(
            payload,
            lrt_table,
        )
        mixed_results.attrs["lrt_table"] = lrt_table
        frames["Mixed Model LRT"] = lrt_table
    diagnostics = mixed_results.attrs.get("model_diagnostics")
    if isinstance(diagnostics, pd.DataFrame):
        frames["Mixed Model Diagnostics"] = diagnostics
    contrast_error: str | None = None
    try:
        lmm_contrasts = _single_lmm_contrast_frame(
            payload,
            fitted_model,
            lrt_table if isinstance(lrt_table, pd.DataFrame) else None,
            ci_level=float(ci_level),
            followup_provenance=followup_provenance,
        )
    except Exception as exc:  # noqa: BLE001 - preserve the completed LMM
        contrast_error = f"{type(exc).__name__}: {exc}"
        lmm_contrasts = pd.DataFrame(
            [
                {
                    "status": "failed",
                    "reportable": False,
                    "headline_eligible": False,
                    "inference_role": "exploratory",
                    "method_label": (
                        "LMM-derived model-estimated contrast"
                    ),
                    "inference_method": (
                        "Asymptotic Wald z test (two-sided)"
                    ),
                    "followup_provenance": (
                        _resolve_single_followup_provenance(
                            payload,
                            followup_provenance,
                        ).value
                    ),
                    "analysis_scope": payload.analysis_scope,
                    "missing_values_imputed": False,
                    "error": contrast_error,
                }
            ]
        )
    frames["LMM Contrasts"] = lmm_contrasts
    mixed_results.attrs["lmm_contrasts"] = lmm_contrasts

    model_has_warnings = (
        "partial"
        if "LRT Status" in mixed_results.columns
        and mixed_results["LRT Status"].astype(str).ne("ok").any()
        else "ok"
    )
    status = "partial" if contrast_error else model_has_warnings
    fit_status = {
        "status": status,
        "alpha": payload.run_spec.alpha if alpha is None else float(alpha),
        "analysis_scope": payload.analysis_scope,
        "prepared_complete_core": (
            payload.analysis_scope == "complete_core"
        ),
        "n_observations": int(len(payload.primary_data)),
        "n_frozen_participants": len(payload.frozen_participants),
        "n_contributing_participants": len(
            payload.contributing_participants
        ),
        "missing_values_imputed": False,
        "contrast_status": "failed" if contrast_error else "ok",
        "contrast_error": contrast_error or "",
    }
    response = _response(
        payload=payload,
        step="single_lmm",
        status=status,
        status_code=f"single_lmm_{status}",
        message=(
            "Prepared-data single-group mixed model completed."
            if status == "ok"
            else (
                "The single-group mixed model completed, but one or more "
                "screening outputs require review."
            )
        ),
        frames=_single_frames(payload, **frames),
        primary_object=(mixed_results, fitted_model),
    )
    response.update(
        {
            "mixed_results_df": mixed_results,
            "mixed_model": fitted_model,
            "lmm_contrasts_df": lmm_contrasts,
            "output_text": (
                mixed_results.to_string(index=False)
                + "\n\nLMM-derived model-estimated contrasts\n"
                + lmm_contrasts.to_string(index=False)
            ),
            "fit_status": fit_status,
            "dv_metadata": payload.settings.get("dv_metadata", {}),
        }
    )
    return response


def run_single_posthoc_step(
    progress_or_payload: object | None = None,
    message_emit: Callable[[str], None] | None = None,
    *,
    prepared_payload: PreparedAnalysisPayload | None = None,
    alpha: float | None = None,
    correction: str = "holm",
    direction: str = "both",
    posthoc_direction: str | None = None,
    followup_provenance: object = "exploratory_manual",
    omnibus_p_value: float | None = None,
    omnibus_significant: bool | None = None,
    enforce_omnibus_gate: bool = True,
    family_scope: str = "direction",
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    **_ignored: object,
) -> dict[str, object]:
    """Return the explicit compatibility status for retired paired post-hocs."""

    payload, progress, message, blocked = _single_step_start(
        progress_or_payload,
        message_emit,
        prepared_payload=prepared_payload,
        progress_callback=progress_callback,
        step="single_interaction_posthocs",
    )
    if blocked is not None:
        return blocked
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step="single_interaction_posthocs",
            status="cancelled",
            status_code="cancelled_before_start",
            message="Interaction follow-ups were cancelled before they started.",
        )
    _emit_progress(progress, 1, 1)
    message(
        "Paired post-hocs are superseded by contrasts from the fitted "
        "single-group mixed model."
    )
    return _response(
        payload=payload,
        step="single_interaction_posthocs",
        status="blocked",
        status_code="paired_posthocs_superseded_by_lmm_contrasts",
        message=(
            "Separate paired post-hocs were not run. Condition-within-ROI "
            "and ROI-within-Condition follow-ups are LMM-derived "
            "model-estimated contrasts packaged with the primary mixed model."
        ),
    )


def run_single_baseline_step(
    progress_or_payload: object | None = None,
    message_emit: Callable[[str], None] | None = None,
    *,
    prepared_payload: PreparedAnalysisPayload | None = None,
    alpha: float | None = None,
    alternative: object | None = None,
    correction: object = "holm",
    correction_scope: str = "global",
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    **_ignored: object,
) -> dict[str, object]:
    """Run baseline-versus-zero tests on prepared single-group rows."""

    payload, progress, message, blocked = _single_step_start(
        progress_or_payload,
        message_emit,
        prepared_payload=prepared_payload,
        progress_callback=progress_callback,
        step="single_baseline_vs_zero",
    )
    if blocked is not None:
        return blocked
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step="single_baseline_vs_zero",
            status="cancelled",
            status_code="cancelled_before_start",
            message="Baseline tests were cancelled before they started.",
        )
    _emit_progress(progress, 0, 1)
    message("Running baseline-versus-zero tests on prepared data.")
    try:
        output_text, results = run_baseline_vs_zero_tests(
            payload.primary_data,
            dv_col=payload.dv_col,
            subject_col=payload.subject_col,
            condition_col=payload.condition_col,
            roi_col=payload.roi_col,
            alpha=(
                payload.run_spec.alpha if alpha is None else float(alpha)
            ),
            alternative=(
                payload.run_spec.response_alternative
                if alternative is None
                else alternative
            ),
            correction=correction,
            correction_scope=correction_scope,
            run_spec=payload.run_spec,
        )
    except Exception as exc:
        return _response(
            payload=payload,
            step="single_baseline_vs_zero",
            status="failed",
            status_code="single_baseline_failed",
            message=f"{type(exc).__name__}: {exc}",
        )
    if _is_cancelled(cancel_check):
        return _response(
            payload=payload,
            step="single_baseline_vs_zero",
            status="cancelled",
            status_code="cancelled_after_tests",
            message="Cancellation was requested during baseline tests.",
        )
    _emit_progress(progress, 1, 1)
    metadata = {
        "dv_col": payload.dv_col,
        "alpha": payload.run_spec.alpha if alpha is None else float(alpha),
        "alternative": str(
            payload.run_spec.response_alternative.value
            if alternative is None
            else alternative
        ),
        "correction": str(correction),
        "correction_scope": correction_scope,
        "analysis_scope": payload.analysis_scope,
        "total_unique_subjects": len(
            payload.contributing_participants
        ),
        "n_frozen_participants": len(payload.frozen_participants),
        "n_contributing_participants": len(
            payload.contributing_participants
        ),
        "missing_values_imputed": False,
        "harmonic_provenance": (
            payload.run_spec.harmonic_provenance.value
        ),
        "preparation_id": payload.preparation_id,
    }
    response = _response(
        payload=payload,
        step="single_baseline_vs_zero",
        status="ok",
        status_code="single_baseline_ok",
        message="Prepared-data baseline-versus-zero tests completed.",
        frames=_single_frames(payload, **{"Baseline vs Zero": results}),
        primary_object=results,
    )
    response.update(
        {
            "results_df": results,
            "output_text": output_text,
            "metadata": metadata,
            "dv_metadata": payload.settings.get("dv_metadata", {}),
        }
    )
    return response


def run_report_bundle_step(
    progress_or_config: object | None = None,
    message_emit: Callable[[str], None] | None = None,
    *,
    config: Mapping[str, object] | None = None,
    prepared_payload: PreparedAnalysisPayload | None = None,
    cancel_token: object | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: ProgressCallback | None = None,
    export_path: str | Path | None = None,
    prior_results: Mapping[object, object] | None = None,
    step_results: Mapping[object, object] | None = None,
    **_ignored: object,
) -> dict[str, object]:
    """Build the reporting bundle, using a lazy import to avoid Qt coupling."""

    if isinstance(progress_or_config, Mapping) and config is None:
        config = progress_or_config
        if message_emit is not None and cancel_token is None:
            cancel_token = message_emit
            message_emit = None
    elif callable(progress_or_config) and progress_callback is None:
        progress_callback = _worker_progress_adapter(progress_or_config)
    message_callback = (
        message_emit if callable(message_emit) else lambda _text: None
    )
    resolved_config = dict(config or {})
    if export_path is not None:
        resolved_config["export_path"] = export_path
    if prepared_payload is not None:
        payload = _require_payload(prepared_payload)
        resolved_config.setdefault("prepared_payload", payload)
        resolved_config.setdefault("mode", payload.mode.value)
        resolved_config.setdefault("alpha", payload.run_spec.alpha)
    if prior_results is not None and step_results is not None:
        raise ValueError("Supply prior_results or step_results, not both.")
    results = prior_results if prior_results is not None else step_results
    effective_results = (
        results
        or resolved_config.get("prior_results")
        or resolved_config.get("step_payloads")
        or {}
    )
    if not isinstance(effective_results, Mapping):
        raise TypeError("prior_results/step_results must be a mapping.")
    identity_payload = prepared_payload
    configured_payload = resolved_config.get("prepared_payload")
    if identity_payload is None and isinstance(
        configured_payload,
        PreparedAnalysisPayload,
    ):
        identity_payload = configured_payload
    requested_export_path = resolved_config.get("export_path")
    identity = (
        None
        if identity_payload is None
        else identity_payload.preparation_id
    )
    if _is_cancelled(cancel_check, cancel_token):
        return {
            "status": "cancelled",
            "status_code": "cancelled_before_report_bundle",
            "message": "Report assembly was cancelled before it started.",
            "config": resolved_config,
            "prior_results": dict(effective_results),
            "export_frames": {},
            "frames": {},
            "prepared_payload": identity_payload,
            "preparation_id": identity,
            "exported": False,
            "numeric_exported": False,
            "export_path": "",
        }
    total_progress = 2 if requested_export_path else 1
    _emit_progress(progress_callback, 0, total_progress)
    message_callback("Assembling the native inference report bundle.")
    try:
        from Tools.Stats.reporting.inference_report import (
            build_native_inference_report,
        )

        bundle = build_native_inference_report(
            mode=str(resolved_config.get("mode", "multi")),
            prepared_payload=resolved_config.get("prepared_payload"),
            prior_results=effective_results,
            alpha=float(resolved_config.get("alpha", 0.05)),
            export_path=requested_export_path,
        )
        to_frames = getattr(bundle, "to_frames", None)
        if not callable(to_frames):
            raise TypeError(
                "build_native_inference_report did not return an exportable "
                "report bundle."
            )
        bundle_frames = to_frames(
            export_path=requested_export_path
        )
    except Exception as report_exc:
        report_error = f"{type(report_exc).__name__}: {report_exc}"
        fallback_path = ""
        numeric_exported = False
        fallback_error = ""
        if requested_export_path and not _is_cancelled(
            cancel_check,
            cancel_token,
        ):
            message_callback(
                "Report assembly failed; attempting numeric-only workbook export."
            )
            try:
                from Tools.Stats.reporting.inference_report import (
                    write_native_numeric_workbook,
                )

                actual_fallback_path = write_native_numeric_workbook(
                    identity_payload,
                    effective_results,
                    requested_export_path,
                    report_error=report_error,
                )
                fallback_path = str(actual_fallback_path)
                numeric_exported = True
            except Exception as fallback_exc:
                fallback_error = (
                    f"{type(fallback_exc).__name__}: {fallback_exc}"
                )
        if _is_cancelled(cancel_check, cancel_token):
            return {
                "status": "cancelled",
                "status_code": "cancelled_during_report_bundle",
                "message": "Report assembly was cancelled.",
                "config": resolved_config,
                "prior_results": dict(effective_results),
                "export_frames": {},
                "frames": {},
                "prepared_payload": identity_payload,
                "preparation_id": identity,
                "exported": False,
                "numeric_exported": False,
                "export_path": "",
            }
        message = f"Native report assembly failed: {report_error}"
        if numeric_exported:
            message += (
                "; a numeric-only workbook was exported successfully."
            )
        elif requested_export_path:
            message += (
                "; numeric-only workbook export also failed"
                + (f": {fallback_error}" if fallback_error else ".")
            )
        return {
            "status": "failed",
            "status_code": "reporting_failed",
            "message": message,
            "report_error": report_error,
            "fallback_error": fallback_error,
            "config": resolved_config,
            "prior_results": dict(effective_results),
            "export_frames": {},
            "frames": {},
            "prepared_payload": identity_payload,
            "preparation_id": identity,
            "exported": False,
            "numeric_exported": numeric_exported,
            "export_path": fallback_path,
        }

    if _is_cancelled(cancel_check, cancel_token):
        return {
            "status": "cancelled",
            "status_code": "cancelled_after_report_assembly",
            "message": "Report export was cancelled after report assembly.",
            "config": resolved_config,
            "prior_results": dict(effective_results),
            "export_frames": {},
            "frames": {},
            "prepared_payload": identity_payload,
            "preparation_id": identity,
            "exported": False,
            "numeric_exported": False,
            "export_path": "",
        }

    actual_export_path = ""
    exported = False
    if requested_export_path:
        message_callback("Writing the native inference workbook.")
        try:
            from Tools.Stats.reporting.inference_report import (
                write_native_inference_workbook,
            )

            actual_export_path = str(
                write_native_inference_workbook(
                    bundle,
                    requested_export_path,
                )
            )
            exported = True
        except Exception as export_exc:
            export_error = f"{type(export_exc).__name__}: {export_exc}"
            fallback_path = ""
            numeric_exported = False
            fallback_error = ""
            if not _is_cancelled(cancel_check, cancel_token):
                message_callback(
                    "Full report workbook export failed; attempting "
                    "numeric-only workbook export."
                )
                try:
                    from Tools.Stats.reporting.inference_report import (
                        write_native_numeric_workbook,
                    )

                    actual_fallback_path = write_native_numeric_workbook(
                        identity_payload,
                        effective_results,
                        requested_export_path,
                        report_error=export_error,
                    )
                    fallback_path = str(actual_fallback_path)
                    numeric_exported = True
                except Exception as fallback_exc:
                    fallback_error = (
                        f"{type(fallback_exc).__name__}: {fallback_exc}"
                    )
            message = (
                "Native report assembly succeeded, but workbook export "
                f"failed: {export_error}"
            )
            if numeric_exported:
                message += (
                    "; a numeric-only workbook was exported successfully."
                )
            elif fallback_error:
                message += (
                    "; numeric-only workbook export also failed: "
                    f"{fallback_error}"
                )
            return {
                "status": "failed",
                "status_code": "reporting_failed",
                "message": message,
                "report_error": export_error,
                "fallback_error": fallback_error,
                "config": resolved_config,
                "prior_results": dict(effective_results),
                "primary_object": bundle,
                "result": bundle,
                "report_bundle": bundle,
                "export_frames": _copy_frames(bundle_frames),
                "frames": _copy_frames(bundle_frames),
                "prepared_payload": identity_payload,
                "preparation_id": identity,
                "exported": False,
                "numeric_exported": numeric_exported,
                "export_path": fallback_path,
            }
    _emit_progress(progress_callback, total_progress, total_progress)
    return {
        "status": "ok",
        "status_code": "report_bundle_ok",
        "message": (
            "Report bundle assembled and workbook exported."
            if exported
            else "Report bundle assembled."
        ),
        "config": resolved_config,
        "prior_results": dict(effective_results),
        "primary_object": bundle,
        "result": bundle,
        "report_bundle": bundle,
        "report_text": str(getattr(bundle, "at_a_glance", "")),
        "detailed_methods": str(getattr(bundle, "detailed_methods", "")),
        "export_frames": _copy_frames(bundle_frames),
        "frames": _copy_frames(bundle_frames),
        "prepared_payload": identity_payload,
        "preparation_id": identity,
        "exported": exported,
        "numeric_exported": exported,
        "export_path": actual_export_path,
    }


run_multigroup_model = run_multigroup_model_step
run_group_cell_comparisons = run_group_cell_step
run_sensitivities = run_sensitivity_step


__all__ = [
    "MAX_ROBUST_CELLS",
    "MAX_SENSITIVITY_RESAMPLES",
    "PREPARED_WORKER_SCHEMA_VERSION",
    "SensitivityConfig",
    "run_group_cell_comparisons",
    "run_group_cell_step",
    "run_multigroup_model",
    "run_multigroup_model_step",
    "run_prepare_analysis",
    "run_report_bundle_step",
    "run_sensitivities",
    "run_sensitivity_step",
    "run_single_baseline_step",
    "run_single_lmm_step",
    "run_single_posthoc_step",
    "run_single_rm_anova_step",
]
