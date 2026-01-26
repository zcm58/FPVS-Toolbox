"""
Worker jobs and runner for the Stats tool (model/service layer).

This module defines:
  * StatsWorker: QRunnable wrapper that executes a single stats job in a worker
    thread and emits signals back to the controller/view.
  * Job functions: pure computational routines for ANOVA, mixed models, group
    contrasts, harmonics, etc., used by the stats pipelines.

The functions and worker stay GUI-agnostic; StatsWindow triggers them through
StatsController.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import asdict
from typing import Any, Callable, Dict

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

import pandas as pd
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from Tools.Stats.Legacy.interpretation_helpers import generate_lme_summary
from Tools.Stats.Legacy.group_contrasts import compute_group_contrasts
from Tools.Stats.Legacy.mixed_effects_model import run_mixed_effects_model
from Tools.Stats.Legacy.mixed_group_anova import run_mixed_group_anova
from Tools.Stats.Legacy.posthoc_tests import run_interaction_posthocs
from Tools.Stats.Legacy.stats_analysis import (
    run_harmonic_check as run_harmonic_check_new,
    run_rm_anova as analysis_run_rm_anova,
    set_rois,
    SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
)
from Tools.Stats.PySide6.dv_policies import (
    ROSSION_POLICY_NAME,
    build_rossion_preview_payload,
    normalize_dv_policy,
    prepare_summed_bca_data,
)
from Tools.Stats.PySide6.dv_variants import compute_dv_variants_payload
from Tools.Stats.PySide6.stats_outlier_exclusion import (
    OutlierExclusionReport,
    OutlierExclusionSummary,
    apply_hard_dv_exclusion,
    merge_exclusion_reports,
)
from Tools.Stats.PySide6.stats_qc_exclusion import (
    QC_DEFAULT_THRESHOLD_MAXABS,
    QC_DEFAULT_THRESHOLD_SUMABS,
    QcExclusionReport,
    run_qc_exclusion,
)

logger = logging.getLogger("Tools.Stats")
RM_ANOVA_DIAG = os.getenv("FPVS_RM_ANOVA_DIAG", "0").strip() == "1"
DV_TRACE_ENV = "FPVS_STATS_DV_TRACE"

BETWEEN_STAGE_ORDER = (
    "BETWEEN_GROUP_ANOVA",
    "BETWEEN_GROUP_MIXED_MODEL",
    "GROUP_CONTRASTS",
    "HARMONIC_CHECK",
)


def _serialize_dv_variants_payload(payload) -> dict | None:
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    return asdict(payload)


def _variant_error_payload(
    dv_policy: dict | None,
    dv_variants: list[dict[str, object]] | None,
    exc: Exception,
) -> dict:
    selected_variants = []
    for item in dv_variants or []:
        if isinstance(item, dict) and item.get("name"):
            selected_variants.append(str(item.get("name")))
    return {
        "primary_name": str((dv_policy or {}).get("name", "")),
        "primary_df": pd.DataFrame(),
        "variant_dfs": {},
        "summary_df": pd.DataFrame(),
        "errors": [{"variant": "DV Variants", "error": str(exc)}],
        "selected_variants": selected_variants,
    }


def _dv_trace_enabled() -> bool:
    value = os.getenv(DV_TRACE_ENV, "").strip().lower()
    return value not in ("", "0", "false", "no", "off")


def _log_dv_trace_policy_snapshot(
    *,
    dv_policy: dict | None,
    base_freq: float,
    conditions: list[str],
    rois: dict | None,
    subjects: list[str],
) -> None:
    if not _dv_trace_enabled():
        return
    settings = normalize_dv_policy(dv_policy)
    roi_list = list(rois.keys()) if isinstance(rois, dict) else []
    logger.info(
        "DV_TRACE policy_snapshot policy_name=%s z_threshold=%s exclude_harmonic1=%s "
        "exclude_base_harmonics=%s base_freq=%s oddball_every_n=%s fixed_k=%s "
        "selected_conditions=%s selected_conditions_count=%d rois=%s rois_count=%d n_subjects=%d",
        settings.name,
        settings.z_threshold,
        settings.exclude_harmonic1,
        settings.exclude_base_harmonics,
        float(base_freq),
        SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
        settings.fixed_k,
        list(conditions),
        len(conditions),
        roi_list,
        len(roi_list),
        len(subjects),
    )


class StatsWorker(QRunnable):
    """
    QRunnable that executes a callable with (progress_emit, message_emit, *args, **kwargs)
    and emits results via signals. Drop-in compatible with the previous version.
    """

    class Signals(QObject):
        progress = Signal(int)
        message = Signal(str)
        error = Signal(str)
        finished = Signal(object)

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.setAutoDelete(True)  # avoid lingering runnables
        self.signals = self.Signals()
        self._fn: Callable[..., Any] = fn
        self._args = args
        # Optional op name for structured logs; removed from kwargs before calling fn
        self._op: str = kwargs.pop("_op", getattr(fn, "__name__", "stats_op"))
        self._step_id: str | None = kwargs.pop("_step_id", None)
        self._kwargs = kwargs

    @Slot()
    def run(self) -> None:
        t0 = time.perf_counter()
        logger.info("stats_run_start", extra={"op": self._op})
        progress_emit = self.signals.progress.emit
        message_emit = self.signals.message.emit
        try:
            result = self._fn(progress_emit, message_emit, *self._args, **self._kwargs)
            payload: Dict[str, Any] = result if isinstance(result, dict) else {"result": result}
            try:
                logger.info(
                    "stats_worker_emit_finished_enter",
                    extra={
                        "op": self._op,
                        "step_id": self._step_id,
                        "worker_thread_id": threading.get_ident(),
                        "payload_keys": list(payload.keys()),
                    },
                )
                self.signals.finished.emit(payload)
                logger.info(
                    "stats_worker_emit_finished_exit",
                    extra={
                        "op": self._op,
                        "step_id": self._step_id,
                        "worker_thread_id": threading.get_ident(),
                    },
                )
            except Exception as emit_exc:  # noqa: BLE001
                logger.exception(
                    "stats_run_emit_failed",
                    extra={
                        "op": self._op,
                        "step_id": self._step_id,
                        "callable": getattr(self._fn, "__name__", str(self._fn)),
                        "exc": repr(emit_exc),
                    },
                )
                step_label = self._step_id or self._op
                self.signals.error.emit(f"Worker emit failed for {step_label}: {emit_exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_run_failed",
                extra={"op": self._op, "exc_type": type(exc).__name__},
            )
            self.signals.error.emit(str(exc))
        finally:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            logger.info("stats_run_done", extra={"op": self._op, "elapsed_ms": dt_ms})


def _long_format_from_bca(
    all_subject_bca_data: Dict[str, Dict[str, Dict[str, float]]],
    subject_groups: dict[str, str | None] | None = None,
) -> pd.DataFrame:
    """Return a tidy dataframe for downstream models."""

    rows = []
    groups = subject_groups or {}
    for pid, cond_data in all_subject_bca_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    rows.append(
                        {
                            "subject": pid,
                            "condition": cond_name,
                            "roi": roi_name,
                            "value": value,
                            "group": groups.get(pid),
                        }
                    )
    return pd.DataFrame(rows)


def _apply_outlier_exclusion(
    df_long: pd.DataFrame,
    *,
    enabled: bool,
    abs_limit: float,
    message_cb,
) -> tuple[pd.DataFrame, OutlierExclusionReport]:
    if not enabled:
        summary = OutlierExclusionSummary(
            n_subjects_before=int(df_long["subject"].nunique()) if not df_long.empty else 0,
            n_subjects_excluded=0,
            n_subjects_after=int(df_long["subject"].nunique()) if not df_long.empty else 0,
            abs_limit=float(abs_limit),
        )
        return df_long, OutlierExclusionReport(summary=summary, participants=[])

    filtered_df, report = apply_hard_dv_exclusion(
        df_long,
        abs_limit,
        participant_col="subject",
        condition_col="condition",
        roi_col="roi",
        value_col="value",
    )

    excluded_ids = [p.participant_id for p in report.participants]
    message = (
        "Outlier exclusion enabled; "
        f"abs_limit={report.summary.abs_limit}; "
        f"excluded_pids={excluded_ids}; "
        f"n_before={report.summary.n_subjects_before} "
        f"n_after={report.summary.n_subjects_after}"
    )
    if message_cb:
        message_cb(message)
    logger.info(
        "stats_outlier_exclusion_summary",
        extra={
            "abs_limit": report.summary.abs_limit,
            "excluded_pids": excluded_ids,
            "n_before": report.summary.n_subjects_before,
            "n_after": report.summary.n_subjects_after,
        },
    )

    for participant in report.participants:
        logger.info(
            "stats_outlier_exclusion_participant",
            extra={
                "participant_id": participant.participant_id,
                "reasons": participant.reasons,
                "worst_value": participant.worst_value,
                "worst_condition": participant.worst_condition,
                "worst_roi": participant.worst_roi,
                "n_violations": participant.n_violations,
                "max_abs_dv": participant.max_abs_dv,
            },
        )

    return filtered_df, report


def _apply_qc_screening(
    *,
    subjects: list[str],
    subject_data: dict,
    subject_groups: dict[str, str | None] | None,
    conditions_all: list[str] | None,
    rois_all: dict | None,
    base_freq: float,
    message_cb,
    qc_config: dict | None,
    qc_state: dict | None,
) -> tuple[
    list[str],
    dict,
    dict[str, str | None] | None,
    QcExclusionReport | None,
]:
    if not subjects:
        return subjects, subject_data, subject_groups, None

    if qc_state is not None and isinstance(qc_state.get("report"), QcExclusionReport):
        excluded_pids = set(qc_state.get("excluded_pids", set()))
        qc_report = qc_state.get("report")
    else:
        config = qc_config or {}
        threshold_sumabs = float(config.get("threshold_sumabs", QC_DEFAULT_THRESHOLD_SUMABS))
        threshold_maxabs = float(config.get("threshold_maxabs", QC_DEFAULT_THRESHOLD_MAXABS))
        excluded_pids, qc_report = run_qc_exclusion(
            subjects=list(subjects),
            subject_data=subject_data,
            conditions_all=list(conditions_all or []),
            rois_all=rois_all or {},
            base_freq=base_freq,
            threshold_sumabs=threshold_sumabs,
            threshold_maxabs=threshold_maxabs,
            log_func=message_cb,
        )
        if qc_state is not None:
            qc_state["report"] = qc_report
            qc_state["excluded_pids"] = set(excluded_pids)

    excluded_ids = set(excluded_pids)
    if excluded_ids:
        message = (
            "QC screening excluded participants; "
            f"excluded_pids={sorted(excluded_ids)}; "
            f"n_before={len(subjects)} n_after={len(subjects) - len(excluded_ids)}"
        )
        if message_cb:
            message_cb(message)
        logger.info(
            "stats_qc_exclusion_summary",
            extra={
                "excluded_pids": sorted(excluded_ids),
                "n_before": len(subjects),
                "n_after": len(subjects) - len(excluded_ids),
            },
        )
        for participant in (qc_report.participants if qc_report else []):
            logger.info(
                "stats_qc_exclusion_participant",
                extra={
                    "participant_id": participant.participant_id,
                    "reasons": participant.reasons,
                    "worst_value": participant.worst_value,
                    "worst_condition": participant.worst_condition,
                    "worst_roi": participant.worst_roi,
                    "n_violations": participant.n_violations,
                    "robust_score": participant.robust_score,
                    "threshold_used": participant.threshold_used,
                },
            )

    filtered_subject_data = {
        pid: data for pid, data in subject_data.items() if pid not in excluded_ids
    }
    filtered_subjects = [pid for pid in subjects if pid not in excluded_ids]
    filtered_groups = subject_groups
    if isinstance(subject_groups, dict):
        filtered_groups = {
            pid: group for pid, group in subject_groups.items() if pid not in excluded_ids
        }

    return filtered_subjects, filtered_subject_data, filtered_groups, qc_report


def _empty_outlier_report(subjects: list[str], *, abs_limit: float) -> OutlierExclusionReport:
    summary = OutlierExclusionSummary(
        n_subjects_before=len(subjects),
        n_subjects_excluded=0,
        n_subjects_after=len(subjects),
        abs_limit=float(abs_limit),
    )
    return OutlierExclusionReport(summary=summary, participants=[])


def _validate_group_contrasts_input(
    df: pd.DataFrame,
    *,
    group_col: str,
    condition_col: str,
    roi_col: str,
    dv_col: str,
) -> None:
    """Validate long-format input for group contrasts.

    Raises:
        ValueError: If required columns are missing, data are non-numeric/non-finite,
            or if any (condition, ROI, group) cell has insufficient data or
            zero variance.
    """

    required_cols = {group_col, condition_col, roi_col, dv_col}
    missing = required_cols.difference(df.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(
            f"Group contrasts aborted: missing required columns: {missing_list}."
        )

    dv_series = df[dv_col]
    if not pd.api.types.is_numeric_dtype(dv_series):
        raise ValueError(
            f"Group contrasts aborted: DV column '{dv_col}' must be numeric."
        )

    dv_values = dv_series.to_numpy()
    if not np.isfinite(dv_values).all():
        raise ValueError("Group contrasts aborted: non-finite BCA values in DV column.")

    grouped = df.groupby([condition_col, roi_col, group_col])[dv_col]
    for (condition, roi, group), values in grouped:
        n = len(values)
        if n < 2:
            raise ValueError(
                "Group contrasts aborted: group "
                f"{group} condition {condition} ROI {roi} has fewer than 2 observations."
            )
        if values.var(ddof=0) == 0:
            raise ValueError(
                "Group contrasts aborted: group "
                f"{group} condition {condition} ROI {roi} has zero variance."
            )


def _diag_subject_data_structure(subject_data, subjects, conditions, rois, message_cb) -> None:
    if not RM_ANOVA_DIAG or not message_cb:
        return

    subject_list = list(subjects) if subjects else sorted(subject_data.keys(), key=repr)
    condition_list = list(conditions) if conditions else []
    if not condition_list:
        condition_list = sorted(
            {cond for subj in subject_data.values() for cond in (subj or {}).keys()},
            key=repr,
        )
    roi_list = []
    if isinstance(rois, dict):
        roi_list = sorted(rois.keys(), key=repr)
    if not roi_list:
        roi_list = sorted(
            {
                roi
                for subj in subject_data.values()
                for cond in (subj or {}).values()
                for roi in (cond or {}).keys()
            },
            key=repr,
        )

    expected_cells = len(subject_list) * len(condition_list) * len(roi_list)
    observed_cells = 0
    for subj in subject_data.values():
        for cond in (subj or {}).values():
            observed_cells += len((cond or {}).keys())

    message_cb("[RM_ANOVA DIAG] subject_data structure summary")
    message_cb(
        f"[RM_ANOVA DIAG] subjects={len(subject_list)} "
        f"conditions={len(condition_list)} rois={len(roi_list)} "
        f"expected_cells={expected_cells} observed_cells_in_dict={observed_cells}"
    )
    for subject in subject_list:
        subject_conditions = sorted((subject_data.get(subject) or {}).keys(), key=repr)
        message_cb(f"[RM_ANOVA DIAG] subject={subject!r} conditions={subject_conditions!r}")
        for condition in subject_conditions:
            roi_keys = sorted((subject_data.get(subject, {}).get(condition) or {}).keys(), key=repr)
            message_cb(
                f"[RM_ANOVA DIAG] subject={subject!r} condition={condition!r} rois={roi_keys!r}"
            )


def run_rm_anova(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    conditions_all=None,
    subject_data,
    base_freq,
    rois,
    rois_all=None,
    dv_policy: dict | None = None,
    dv_variants: list[dict[str, object]] | None = None,
    results_dir: str | None = None,
    outlier_exclusion_enabled: bool = True,
    outlier_abs_limit: float = 50.0,
    qc_config: dict | None = None,
    qc_state: dict | None = None,
):
    set_rois(rois)
    message_cb("Preparing data for Summed BCA RM-ANOVA…")
    _log_dv_trace_policy_snapshot(
        dv_policy=dv_policy,
        base_freq=base_freq,
        conditions=list(conditions) if conditions else [],
        rois=rois,
        subjects=list(subjects) if subjects else [],
    )
    subjects, subject_data, _subject_groups, qc_report = _apply_qc_screening(
        subjects=list(subjects) if subjects else [],
        subject_data=subject_data,
        subject_groups=None,
        conditions_all=list(conditions_all) if conditions_all else [],
        rois_all=rois_all or rois,
        base_freq=base_freq,
        message_cb=message_cb,
        qc_config=qc_config,
        qc_state=qc_state,
    )
    if not subjects:
        raise RuntimeError("All participants excluded by QC screening.")
    provenance_map = {} if RM_ANOVA_DIAG else None
    dv_metadata: dict[str, object] = {}
    all_subject_bca_data = prepare_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
        rois=rois,
        provenance_map=provenance_map,
        dv_policy=dv_policy,
        dv_metadata=dv_metadata,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")
    dv_variants_payload = None
    if dv_variants:
        try:
            dv_variants_payload = compute_dv_variants_payload(
                subjects=subjects,
                conditions=conditions,
                subject_data=subject_data,
                base_freq=base_freq,
                rois=rois,
                dv_policy=dv_policy,
                variant_policies=dv_variants,
                log_func=message_cb,
                primary_data=all_subject_bca_data,
            )
        except Exception as exc:  # noqa: BLE001
            message_cb(f"DV variants computation failed: {exc}")
            dv_variants_payload = _variant_error_payload(dv_policy, dv_variants, exc)
    df_long = _long_format_from_bca(all_subject_bca_data)
    df_long, exclusion_report = _apply_outlier_exclusion(
        df_long,
        enabled=outlier_exclusion_enabled,
        abs_limit=outlier_abs_limit,
        message_cb=message_cb,
    )
    exclusion_report = merge_exclusion_reports(exclusion_report, qc_report)
    excluded_ids = {p.participant_id for p in exclusion_report.participants}
    if excluded_ids:
        all_subject_bca_data = {
            pid: data for pid, data in all_subject_bca_data.items() if pid not in excluded_ids
        }
        if subjects is not None:
            subjects = [pid for pid in subjects if pid not in excluded_ids]
    if not all_subject_bca_data:
        raise RuntimeError("All participants excluded by outlier exclusion.")
    _diag_subject_data_structure(all_subject_bca_data, subjects, conditions, rois, message_cb)
    message_cb("Running RM-ANOVA…")
    output_text, anova_df_results = analysis_run_rm_anova(
        all_subject_bca_data,
        message_cb,
        subjects=list(subjects) if subjects else None,
        conditions=list(conditions) if conditions else None,
        rois=sorted(rois.keys()) if isinstance(rois, dict) else None,
        provenance_map=provenance_map,
        results_dir=results_dir,
    )
    return {
        "anova_df_results": anova_df_results,
        "output_text": output_text,
        "dv_metadata": dv_metadata,
        "dv_variants": _serialize_dv_variants_payload(dv_variants_payload),
        "dv_exclusion_report": exclusion_report,
    }


def run_between_group_anova(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    conditions_all=None,
    subject_data,
    base_freq,
    rois,
    rois_all=None,
    subject_groups: dict[str, str | None] | None = None,
    dv_policy: dict | None = None,
    dv_variants: list[dict[str, object]] | None = None,
    outlier_exclusion_enabled: bool = True,
    outlier_abs_limit: float = 50.0,
    qc_config: dict | None = None,
    qc_state: dict | None = None,
):
    set_rois(rois)
    message_cb("Preparing data for Between-Group RM-ANOVA…")
    subjects, subject_data, subject_groups, qc_report = _apply_qc_screening(
        subjects=list(subjects) if subjects else [],
        subject_data=subject_data,
        subject_groups=subject_groups,
        conditions_all=list(conditions_all) if conditions_all else [],
        rois_all=rois_all or rois,
        base_freq=base_freq,
        message_cb=message_cb,
        qc_config=qc_config,
        qc_state=qc_state,
    )
    if not subjects:
        raise RuntimeError("All participants excluded by QC screening.")
    dv_metadata: dict[str, object] = {}
    all_subject_bca_data = prepare_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
        rois=rois,
        dv_policy=dv_policy,
        dv_metadata=dv_metadata,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")
    dv_variants_payload = None
    if dv_variants:
        try:
            dv_variants_payload = compute_dv_variants_payload(
                subjects=subjects,
                conditions=conditions,
                subject_data=subject_data,
                base_freq=base_freq,
                rois=rois,
                dv_policy=dv_policy,
                variant_policies=dv_variants,
                log_func=message_cb,
                primary_data=all_subject_bca_data,
            )
        except Exception as exc:  # noqa: BLE001
            message_cb(f"DV variants computation failed: {exc}")
            dv_variants_payload = _variant_error_payload(dv_policy, dv_variants, exc)

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
    df_long, exclusion_report = _apply_outlier_exclusion(
        df_long,
        enabled=outlier_exclusion_enabled,
        abs_limit=outlier_abs_limit,
        message_cb=message_cb,
    )
    exclusion_report = merge_exclusion_reports(exclusion_report, qc_report)
    before = len(df_long)
    df_long = df_long.dropna(subset=["group"])
    dropped = before - len(df_long)
    if dropped:
        message_cb(f"Dropped {dropped} rows without group assignments for mixed ANOVA.")
    if df_long.empty:
        raise RuntimeError("No rows with valid group assignments for mixed ANOVA.")

    df_long["group"] = df_long["group"].astype(str)
    if df_long["group"].nunique() < 2:
        raise RuntimeError("Mixed ANOVA requires at least two groups with valid data.")

    message_cb("Running Between-Group RM-ANOVA…")
    results = run_mixed_group_anova(
        df_long,
        dv_col="value",
        subject_col="subject",
        within_cols=["condition", "roi"],
        between_col="group",
    )
    return {
        "anova_df_results": results,
        "dv_metadata": dv_metadata,
        "dv_variants": _serialize_dv_variants_payload(dv_variants_payload),
        "dv_exclusion_report": exclusion_report,
    }


def run_lmm(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    conditions_all=None,
    subject_data,
    base_freq,
    alpha,
    rois,
    rois_all=None,
    subject_groups: dict[str, str | None] | None = None,
    include_group: bool = False,
    dv_policy: dict | None = None,
    dv_variants: list[dict[str, object]] | None = None,
    outlier_exclusion_enabled: bool = True,
    outlier_abs_limit: float = 50.0,
    qc_config: dict | None = None,
    qc_state: dict | None = None,
):
    set_rois(rois)
    prep_label = "Mixed Effects Model" if not include_group else "Between-Group Mixed Model"
    message_cb(f"Preparing data for {prep_label}…")
    _log_dv_trace_policy_snapshot(
        dv_policy=dv_policy,
        base_freq=base_freq,
        conditions=list(conditions) if conditions else [],
        rois=rois,
        subjects=list(subjects) if subjects else [],
    )
    subjects, subject_data, subject_groups, qc_report = _apply_qc_screening(
        subjects=list(subjects) if subjects else [],
        subject_data=subject_data,
        subject_groups=subject_groups,
        conditions_all=list(conditions_all) if conditions_all else [],
        rois_all=rois_all or rois,
        base_freq=base_freq,
        message_cb=message_cb,
        qc_config=qc_config,
        qc_state=qc_state,
    )
    if not subjects:
        raise RuntimeError("All participants excluded by QC screening.")
    dv_metadata: dict[str, object] = {}
    all_subject_bca_data = prepare_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
        rois=rois,
        dv_policy=dv_policy,
        dv_metadata=dv_metadata,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")
    dv_variants_payload = None
    if dv_variants:
        try:
            dv_variants_payload = compute_dv_variants_payload(
                subjects=subjects,
                conditions=conditions,
                subject_data=subject_data,
                base_freq=base_freq,
                rois=rois,
                dv_policy=dv_policy,
                variant_policies=dv_variants,
                log_func=message_cb,
                primary_data=all_subject_bca_data,
            )
        except Exception as exc:  # noqa: BLE001
            message_cb(f"DV variants computation failed: {exc}")
            dv_variants_payload = _variant_error_payload(dv_policy, dv_variants, exc)

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
    df_long, exclusion_report = _apply_outlier_exclusion(
        df_long,
        enabled=outlier_exclusion_enabled,
        abs_limit=outlier_abs_limit,
        message_cb=message_cb,
    )
    exclusion_report = merge_exclusion_reports(exclusion_report, qc_report)
    if df_long.empty:
        raise RuntimeError("No valid rows for mixed model after filtering NaNs.")

    dropped = 0
    group_levels: list[str] = []
    if include_group:
        before = len(df_long)
        df_long = df_long.dropna(subset=["group"])
        dropped = before - len(df_long)
        df_long["group"] = df_long["group"].astype(str)
        group_levels = sorted(df_long["group"].unique())
        if dropped:
            message_cb(
                f"Dropped {dropped} rows without group assignments for between-group model."
            )
        if len(group_levels) < 2:
            raise RuntimeError(
                "Between-group mixed model requires at least two groups with valid data."
            )

    message_cb("Running Mixed Effects Model…")

    fixed_effects = ["condition * roi"]
    if include_group:
        fixed_effects = ["group * condition * roi"]

    mixed_results_df = run_mixed_effects_model(
        data=df_long,
        dv_col="value",
        group_col="subject",
        fixed_effects=fixed_effects,
    )

    output_text = "============================================================\n"
    if include_group:
        output_text += "       Between-Group Mixed-Effects Model Results\n"
    else:
        output_text += "       Linear Mixed-Effects Model Results\n"
    output_text += "       Analysis conducted on: Summed BCA Data\n"
    output_text += "============================================================\n\n"
    if include_group:
        output_text += (
            "Group was modeled as a between-subject factor interacting with condition\n"
            "and ROI. Only subjects with known group assignments were included.\n\n"
        )
    else:
        output_text += (
            "This model accounts for repeated observations from each subject by including\n"
            "a random intercept. Fixed effects assess how conditions and ROIs influence\n"
            "Summed BCA values, including their interaction.\n\n"
        )
    if mixed_results_df is not None and not mixed_results_df.empty:
        output_text += "--------------------------------------------\n"
        output_text += "                 FIXED EFFECTS TABLE\n"
        output_text += "--------------------------------------------\n"
        output_text += mixed_results_df.to_string(index=False) + "\n"
        output_text += generate_lme_summary(mixed_results_df, alpha=alpha)
    else:
        output_text += "Mixed effects model returned no rows.\n"

    return {
        "mixed_results_df": mixed_results_df,
        "output_text": output_text,
        "dv_metadata": dv_metadata,
        "dv_variants": _serialize_dv_variants_payload(dv_variants_payload),
        "dv_exclusion_report": exclusion_report,
    }


def run_posthoc(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    conditions_all=None,
    subject_data,
    base_freq,
    alpha,
    rois,
    rois_all=None,
    subject_groups: dict[str, str | None] | None = None,
    dv_policy: dict | None = None,
    dv_variants: list[dict[str, object]] | None = None,
    outlier_exclusion_enabled: bool = True,
    outlier_abs_limit: float = 50.0,
    qc_config: dict | None = None,
    qc_state: dict | None = None,
    **kwargs,
):
    set_rois(rois)
    message_cb("Preparing data for Interaction Post-hoc tests…")
    _log_dv_trace_policy_snapshot(
        dv_policy=dv_policy,
        base_freq=base_freq,
        conditions=list(conditions) if conditions else [],
        rois=rois,
        subjects=list(subjects) if subjects else [],
    )
    subjects, subject_data, subject_groups, qc_report = _apply_qc_screening(
        subjects=list(subjects) if subjects else [],
        subject_data=subject_data,
        subject_groups=subject_groups,
        conditions_all=list(conditions_all) if conditions_all else [],
        rois_all=rois_all or rois,
        base_freq=base_freq,
        message_cb=message_cb,
        qc_config=qc_config,
        qc_state=qc_state,
    )
    if not subjects:
        raise RuntimeError("All participants excluded by QC screening.")
    dv_metadata: dict[str, object] = {}
    all_subject_bca_data = prepare_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
        rois=rois,
        dv_policy=dv_policy,
        dv_metadata=dv_metadata,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")
    dv_variants_payload = None
    if dv_variants:
        try:
            dv_variants_payload = compute_dv_variants_payload(
                subjects=subjects,
                conditions=conditions,
                subject_data=subject_data,
                base_freq=base_freq,
                rois=rois,
                dv_policy=dv_policy,
                variant_policies=dv_variants,
                log_func=message_cb,
                primary_data=all_subject_bca_data,
            )
        except Exception as exc:  # noqa: BLE001
            message_cb(f"DV variants computation failed: {exc}")
            dv_variants_payload = _variant_error_payload(dv_policy, dv_variants, exc)

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
    df_long, exclusion_report = _apply_outlier_exclusion(
        df_long,
        enabled=outlier_exclusion_enabled,
        abs_limit=outlier_abs_limit,
        message_cb=message_cb,
    )
    exclusion_report = merge_exclusion_reports(exclusion_report, qc_report)
    if df_long.empty:
        raise RuntimeError("No valid rows for post-hoc tests after filtering NaNs.")

    message_cb("Running post-hoc tests…")
    output_text, results_df = run_interaction_posthocs(
        data=df_long,
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        alpha=alpha,
    )
    message_cb("Post-hoc interaction tests completed.")
    return {
        "results_df": results_df,
        "output_text": output_text,
        "dv_metadata": dv_metadata,
        "dv_variants": _serialize_dv_variants_payload(dv_variants_payload),
        "dv_exclusion_report": exclusion_report,
    }


def run_group_contrasts(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    conditions_all=None,
    subject_data,
    base_freq,
    alpha,
    rois,
    rois_all=None,
    subject_groups: dict[str, str | None] | None = None,
    dv_policy: dict | None = None,
    dv_variants: list[dict[str, object]] | None = None,
    outlier_exclusion_enabled: bool = True,
    outlier_abs_limit: float = 50.0,
    qc_config: dict | None = None,
    qc_state: dict | None = None,
):
    set_rois(rois)
    _ = alpha
    message_cb("Preparing data for Between-Group Contrasts…")
    subjects, subject_data, subject_groups, qc_report = _apply_qc_screening(
        subjects=list(subjects) if subjects else [],
        subject_data=subject_data,
        subject_groups=subject_groups,
        conditions_all=list(conditions_all) if conditions_all else [],
        rois_all=rois_all or rois,
        base_freq=base_freq,
        message_cb=message_cb,
        qc_config=qc_config,
        qc_state=qc_state,
    )
    if not subjects:
        raise RuntimeError("All participants excluded by QC screening.")
    dv_metadata: dict[str, object] = {}
    all_subject_bca_data = prepare_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
        rois=rois,
        dv_policy=dv_policy,
        dv_metadata=dv_metadata,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")
    dv_variants_payload = None
    if dv_variants:
        try:
            dv_variants_payload = compute_dv_variants_payload(
                subjects=subjects,
                conditions=conditions,
                subject_data=subject_data,
                base_freq=base_freq,
                rois=rois,
                dv_policy=dv_policy,
                variant_policies=dv_variants,
                log_func=message_cb,
                primary_data=all_subject_bca_data,
            )
        except Exception as exc:  # noqa: BLE001
            message_cb(f"DV variants computation failed: {exc}")
            dv_variants_payload = _variant_error_payload(dv_policy, dv_variants, exc)

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
    df_long, exclusion_report = _apply_outlier_exclusion(
        df_long,
        enabled=outlier_exclusion_enabled,
        abs_limit=outlier_abs_limit,
        message_cb=message_cb,
    )
    exclusion_report = merge_exclusion_reports(exclusion_report, qc_report)
    df_long = df_long.dropna(subset=["group"])
    if df_long.empty:
        raise RuntimeError("No rows with group assignments to compute contrasts.")
    df_long["group"] = df_long["group"].astype(str)
    if df_long["group"].nunique() < 2:
        raise RuntimeError("Group contrasts require at least two groups with data.")

    _validate_group_contrasts_input(
        df_long,
        group_col="group",
        condition_col="condition",
        roi_col="roi",
        dv_col="value",
    )

    message_cb("Running Between-Group Contrasts…")
    results_df = compute_group_contrasts(
        df_long,
        subject_col="subject",
        group_col="group",
        condition_col="condition",
        roi_col="roi",
        dv_col="value",
    )
    return {
        "results_df": results_df,
        "output_text": "",
        "dv_metadata": dv_metadata,
        "dv_variants": _serialize_dv_variants_payload(dv_variants_payload),
        "dv_exclusion_report": exclusion_report,
    }


def run_harmonics_preview(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    subject_data,
    base_freq,
    rois,
    dv_policy: dict | None = None,
):
    settings = dv_policy or {}
    policy_name = settings.get("name")
    if policy_name == ROSSION_POLICY_NAME:
        return build_rossion_preview_payload(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            rois=rois,
            log_func=message_cb,
            dv_policy=dv_policy,
        )
    raise RuntimeError("Preview requires the Rossion policy.")


def run_harmonic_check(
    progress_cb,
    message_cb,
    *,
    subject_data,
    subjects,
    conditions,
    selected_metric,
    mean_value_threshold,
    base_freq,
    alpha,
    rois,
    **kwargs,
):
    set_rois(rois)
    tail = "greater" if selected_metric in ("Z Score", "SNR") else "two-sided"
    message_cb("Running harmonic check…")
    output_text, findings = run_harmonic_check_new(
        subject_data=subject_data,
        subjects=subjects,
        conditions=conditions,
        selected_metric=selected_metric,
        mean_value_threshold=mean_value_threshold,
        base_freq=base_freq,
        log_func=message_cb,
        max_freq=None,
        correction_method="holm",
        tail=tail,
        min_subjects=3,
        do_wilcoxon_sensitivity=True,
    )
    message_cb("Harmonic check completed.")
    payload: Dict[str, Any] = {
        "output_text": output_text if output_text is not None else "",
        "findings": findings if findings is not None else [],
    }
    return payload


def _progress_from_stage(stage_name: str, *, done: bool) -> int:
    try:
        idx = BETWEEN_STAGE_ORDER.index(stage_name)
    except ValueError:
        return 0
    total = len(BETWEEN_STAGE_ORDER)
    completed = idx + (1 if done else 0)
    pct = int(completed / total * 100)
    return max(0, min(100, pct))


def run_between_group_process_task(
    progress_cb,
    message_cb,
    *,
    job_spec_path: str,
    python_executable: str | None = None,
):
    """Spawn the between-group CLI in a separate Python process.

    The CLI performs ANOVA → Mixed Model → Group Contrasts → Harmonic Check
    sequentially and writes a JSON summary. This wrapper executes it inside a
    worker thread, streaming stdout messages back to the GUI and enforcing
    subprocess isolation.
    """

    job_path = Path(job_spec_path)
    if not job_path.is_file():
        raise FileNotFoundError(f"Job spec not found: {job_spec_path}")

    spec_data = json.loads(job_path.read_text())
    qc_report = None
    qc_excluded = set()
    qc_config = spec_data.get("qc_config", {}) or {}
    original_subjects = list(spec_data.get("subjects", []))
    subjects = list(original_subjects)
    qc_excluded, qc_report = run_qc_exclusion(
        subjects=subjects,
        subject_data=spec_data.get("subject_data", {}),
        conditions_all=list(spec_data.get("conditions_all", [])),
        rois_all=spec_data.get("rois_all", spec_data.get("roi_map", {})),
        base_freq=float(spec_data.get("base_freq", 6.0)),
        threshold_sumabs=float(
            qc_config.get("threshold_sumabs", QC_DEFAULT_THRESHOLD_SUMABS)
        ),
        threshold_maxabs=float(
            qc_config.get("threshold_maxabs", QC_DEFAULT_THRESHOLD_MAXABS)
        ),
        log_func=message_cb,
    )
    if qc_excluded:
        spec_data["subjects"] = [pid for pid in subjects if pid not in qc_excluded]
        spec_data["subject_data"] = {
            pid: data
            for pid, data in spec_data.get("subject_data", {}).items()
            if pid not in qc_excluded
        }
        spec_data["subject_groups"] = {
            pid: group
            for pid, group in spec_data.get("subject_groups", {}).items()
            if pid not in qc_excluded
        }
        if not spec_data["subjects"]:
            raise RuntimeError("All participants excluded by QC screening.")
        job_path.write_text(json.dumps(spec_data, indent=2))

    dv_variants_payload = None
    if spec_data.get("dv_variants"):
        try:
            dv_variants_payload = compute_dv_variants_payload(
                subjects=list(spec_data.get("subjects", [])),
                conditions=list(spec_data.get("conditions", [])),
                subject_data=spec_data.get("subject_data", {}),
                base_freq=float(spec_data.get("base_freq", 6.0)),
                rois=spec_data.get("roi_map", {}),
                dv_policy=spec_data.get("dv_policy", {}),
                variant_policies=spec_data.get("dv_variants", []) or [],
                log_func=message_cb,
            )
        except Exception as exc:  # noqa: BLE001
            message_cb(f"DV variants computation failed: {exc}")
            dv_variants_payload = {
                "primary_name": str(spec_data.get("dv_policy", {}).get("name", "")),
                "primary_df": pd.DataFrame(),
                "variant_dfs": {},
                "summary_df": pd.DataFrame(),
                "errors": [{"variant": "DV Variants", "error": str(exc)}],
                "selected_variants": [
                    item.get("name")
                    for item in spec_data.get("dv_variants", [])
                    if isinstance(item, dict)
                ],
            }
    dv_variants_payload = _serialize_dv_variants_payload(dv_variants_payload)

    exe = python_executable or sys.executable
    cmd = [exe, "-m", "Tools.Stats.Legacy.between_groups_cli", str(job_path)]

    stdout_lines: list[str] = []
    stderr_output = ""

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    try:
        assert process.stdout is not None
        for line in process.stdout:
            if line is None:
                continue
            stripped = line.rstrip()
            stdout_lines.append(stripped)
            message_cb(stripped)

            if stripped.startswith("STAGE_START:"):
                stage_name = stripped.split(":", 1)[1]
                progress_cb(_progress_from_stage(stage_name, done=False))
            elif stripped.startswith("STAGE_DONE:"):
                stage_name = stripped.split(":", 1)[1]
                progress_cb(_progress_from_stage(stage_name, done=True))

        stderr_output = process.stderr.read() if process.stderr else ""
        process.wait()
    finally:
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()

    if process.returncode != 0:
        err_msg = stderr_output.strip() or f"Between-group CLI exited with {process.returncode}"
        raise RuntimeError(err_msg)

    summary_path = Path(spec_data.get("output", {}).get("summary_json", ""))
    if not summary_path.is_file():
        raise RuntimeError("Between-group CLI completed but summary file is missing.")

    summary = json.loads(summary_path.read_text())
    dv_exclusion_report = None
    if qc_report is not None:
        outlier_cfg = spec_data.get("outlier_exclusion", {}) or {}
        abs_limit = float(outlier_cfg.get("abs_limit", 50.0))
        dv_report = _empty_outlier_report(original_subjects, abs_limit=abs_limit)
        dv_exclusion_report = merge_exclusion_reports(dv_report, qc_report)
    return {
        "summary": summary,
        "stdout": stdout_lines,
        "stderr": stderr_output,
        "dv_variants": dv_variants_payload,
        "dv_exclusion_report": dv_exclusion_report,
    }
