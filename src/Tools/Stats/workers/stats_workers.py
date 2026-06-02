"""Worker jobs and runner for the single-group Stats tool."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict

import pandas as pd
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from Tools.Stats.analysis.baseline_vs_zero import run_baseline_vs_zero_tests
from Tools.Stats.analysis.dv_policies import (
    GROUP_SIGNIFICANT_POLICY_NAME,
    normalize_dv_policy,
    prepare_summed_bca_data,
)
from Tools.Stats.analysis.dv_policy_fixed_predefined import build_fixed_predefined_preview_payload
from Tools.Stats.analysis.dv_policy_group_significant import preflight_group_significant_full_fft_columns
from Tools.Stats.analysis.dv_policy_settings import _resolve_max_freq
from Tools.Stats.data.group_harmonic_cache import (
    build_group_harmonic_cache_request,
    lookup_cached_group_harmonic_selection,
)
from Tools.Stats.analysis.interpretation_helpers import generate_lme_summary
from Tools.Stats.analysis.mixed_effects_model import run_mixed_effects_model
from Tools.Stats.analysis.posthoc_tests import run_interaction_posthocs
from Tools.Stats.analysis.stats_analysis import (
    SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
    run_rm_anova as analysis_run_rm_anova,
    set_rois,
)
from Tools.Stats.io.stats_ready_export import prepare_stats_ready_export
from Tools.Stats.qc.stats_outlier_exclusion import (
    DvViolation,
    OUTLIER_REASON_NONFINITE,
    OutlierExclusionReport,
    apply_hard_dv_exclusion,
    merge_exclusion_reports,
)
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
from Tools.Stats.reporting.lmm_reporting import (
    attach_lmm_run_metadata,
    build_lmm_run_contract,
    build_lmm_report_path,
    build_lmm_text_report,
    classify_lmm_fit_status,
    ensure_lmm_effect_columns,
    infer_lmm_diagnostics,
    repair_lmm_pvalues_from_z,
    resolve_lmm_formula,
)
from Tools.Stats.reporting.reporting_summary import (
    build_rm_anova_report_path,
    build_rm_anova_text_report,
)
from Tools.Stats.reporting.stats_run_report import StatsRunReport

logger = logging.getLogger("Tools.Stats")
RM_ANOVA_DIAG = os.getenv("FPVS_RM_ANOVA_DIAG", "0").strip() == "1"
DV_TRACE_ENV = "FPVS_STATS_DV_TRACE"


class StatsWorker(QRunnable):
    """QRunnable wrapper for Stats jobs."""

    class Signals(QObject):
        progress = Signal(int)
        message = Signal(str)
        error = Signal(str)
        report_ready = Signal(str)
        finished = Signal(object)

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = self.Signals()
        self._fn: Callable[..., Any] = fn
        self._args = args
        self._op: str = kwargs.pop("_op", getattr(fn, "__name__", "stats_op"))
        self._step_id: str | None = kwargs.pop("_step_id", None)
        self._kwargs = kwargs

    @Slot()
    def run(self) -> None:
        t0 = time.perf_counter()
        logger.info("stats_run_start", extra={"op": self._op})
        try:
            result = self._fn(
                self.signals.progress.emit,
                self.signals.message.emit,
                *self._args,
                **self._kwargs,
            )
            payload: Dict[str, Any] = result if isinstance(result, dict) else {"result": result}
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
            report_text = payload.get("report_text") if isinstance(payload, dict) else None
            if isinstance(report_text, str):
                self.signals.report_ready.emit(report_text)
            logger.info(
                "stats_worker_emit_finished_exit",
                extra={"op": self._op, "step_id": self._step_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_run_failed",
                extra={"op": self._op, "exc_type": type(exc).__name__},
            )
            self.signals.error.emit(str(exc))
        finally:
            dt_ms = (time.perf_counter() - t0) * 1000.0
            logger.info("stats_run_done", extra={"op": self._op, "elapsed_ms": dt_ms})


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
        "DV_TRACE policy_snapshot policy_name=%s fixed_harmonics_hz=%s "
        "auto_exclude_base=%s base_freq=%s oddball_every_n=%s "
        "group_z_threshold=%s selected_conditions=%s selected_conditions_count=%d "
        "rois=%s rois_count=%d n_subjects=%d",
        settings.name,
        settings.fixed_harmonic_frequencies_hz,
        settings.fixed_harmonic_auto_exclude_base,
        float(base_freq),
        SUMMED_BCA_ODDBALL_EVERY_N_DEFAULT,
        settings.group_significant_z_threshold,
        list(conditions),
        len(conditions),
        roi_list,
        len(roi_list),
        len(subjects),
    )


def _has_valid_project_group_harmonic_cache(
    *,
    project_root: str | None,
    subjects: list[str],
    conditions: list[str],
    subject_data: dict,
    base_freq: float,
    max_freq: float | None,
    settings,
) -> bool:
    request = build_group_harmonic_cache_request(
        project_root=project_root,
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_frequency_hz=base_freq,
        max_freq_hz=max_freq,
        settings=settings,
    )
    lookup = lookup_cached_group_harmonic_selection(request)
    return lookup.hit is not None


def _long_format_from_bca(
    all_subject_bca_data: Dict[str, Dict[str, Dict[str, float]]],
) -> pd.DataFrame:
    rows = []
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
    _ = enabled
    filtered_df, report = apply_hard_dv_exclusion(
        df_long,
        abs_limit,
        participant_col="subject",
        condition_col="condition",
        roi_col="roi",
        value_col="value",
    )
    excluded_ids = sorted({p.participant_id for p in report.participants if p.required_exclusion})
    if message_cb:
        message_cb(
            "DV flagging complete; "
            f"abs_limit={report.summary.abs_limit}; "
            f"required_exclusions={excluded_ids}; "
            f"n_before={report.summary.n_subjects_before} "
            f"n_after={report.summary.n_subjects_after}"
        )
    logger.info(
        "stats_outlier_exclusion_summary",
        extra={
            "abs_limit": report.summary.abs_limit,
            "excluded_pids": excluded_ids,
            "n_before": report.summary.n_subjects_before,
            "n_after": report.summary.n_subjects_after,
        },
    )
    return filtered_df, report


def _apply_qc_screening(
    *,
    subjects: list[str],
    subject_data: dict,
    conditions_all: list[str] | None,
    rois_all: dict | None,
    base_freq: float,
    message_cb,
    qc_config: dict | None,
    qc_state: dict | None,
) -> tuple[list[str], dict, QcExclusionReport | None]:
    if not subjects:
        return subjects, subject_data, None

    if qc_state is not None and isinstance(qc_state.get("report"), QcExclusionReport):
        qc_report = qc_state.get("report")
    else:
        config = qc_config or {}
        qc_report = run_qc_exclusion(
            subjects=list(subjects),
            subject_data=subject_data,
            conditions_all=list(conditions_all or []),
            rois_all=rois_all or {},
            base_freq=base_freq,
            warn_threshold=float(config.get("warn_threshold", QC_DEFAULT_WARN_THRESHOLD)),
            critical_threshold=float(config.get("critical_threshold", QC_DEFAULT_CRITICAL_THRESHOLD)),
            warn_abs_floor_sumabs=float(config.get("warn_abs_floor_sumabs", QC_DEFAULT_WARN_ABS_FLOOR_SUMABS)),
            critical_abs_floor_sumabs=float(config.get("critical_abs_floor_sumabs", QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS)),
            warn_abs_floor_maxabs=float(config.get("warn_abs_floor_maxabs", QC_DEFAULT_WARN_ABS_FLOOR_MAXABS)),
            critical_abs_floor_maxabs=float(config.get("critical_abs_floor_maxabs", QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS)),
            log_func=message_cb,
        )
        if qc_state is not None:
            qc_state["report"] = qc_report

    if qc_report and qc_report.participants and message_cb:
        message_cb(
            "QC screening flagged participants; "
            f"flagged_pids={sorted({p.participant_id for p in qc_report.participants})}; "
            f"n_before={len(subjects)} n_flagged={qc_report.summary.n_subjects_flagged}"
        )
    return subjects, subject_data, qc_report


def _apply_manual_exclusions(
    *,
    subjects: list[str],
    subject_data: dict,
    manual_excluded_pids: list[str] | None,
    message_cb,
) -> tuple[list[str], dict, list[str]]:
    manual_excluded = sorted({pid for pid in (manual_excluded_pids or []) if pid in set(subjects)})
    if not manual_excluded:
        return subjects, subject_data, []
    filtered_subjects = [pid for pid in subjects if pid not in manual_excluded]
    filtered_subject_data = {pid: data for pid, data in subject_data.items() if pid not in manual_excluded}
    if message_cb:
        message_cb(f"Manual exclusions applied: {manual_excluded}")
    logger.info(
        "stats_manual_exclusions_applied",
        extra={"excluded_pids": manual_excluded, "n_before": len(subjects)},
    )
    return filtered_subjects, filtered_subject_data, manual_excluded


def _extract_required_exclusions(report: OutlierExclusionReport) -> list[DvViolation]:
    required: list[DvViolation] = []
    for participant in report.participants:
        if participant.required_exclusion:
            required.extend(
                violation
                for violation in participant.dv_violations
                if violation.reason == OUTLIER_REASON_NONFINITE
            )
    return required


def run_stats_ready_export(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    conditions_all=None,
    subject_data,
    base_freq,
    rois,
    dv_policy: dict | None = None,
    group_map: dict | None = None,
    output_path: str,
    manual_excluded_pids: list[str] | None = None,
    max_freq: float | None = None,
    project_root: str | None = None,
) -> dict[str, object]:
    """Write the optional external-statistics Summed BCA workbook."""

    progress_cb(5)
    filtered_subjects, filtered_subject_data, manual_excluded = _apply_manual_exclusions(
        subjects=list(subjects) if subjects else [],
        subject_data=subject_data,
        manual_excluded_pids=manual_excluded_pids,
        message_cb=message_cb,
    )
    if not filtered_subjects:
        raise RuntimeError("All participants are manually excluded.")

    message_cb("Preparing stats-ready Summed BCA workbook.")
    progress_cb(25)
    export = prepare_stats_ready_export(
        subjects=filtered_subjects,
        conditions=list(conditions) if conditions else [],
        subject_data=filtered_subject_data,
        base_freq=base_freq,
        rois=rois or {},
        dv_policy=dv_policy,
        group_map=group_map or {},
        log_func=message_cb,
        save_path=output_path,
        max_freq=max_freq,
        selection_conditions=list(conditions or []),
        project_root=project_root,
    )
    progress_cb(100)
    return {
        "path": str(export.workbook_path) if export.workbook_path else "",
        "row_count": export.row_count,
        "sheet_names": list(export.frames.keys()),
        "manual_excluded_pids": manual_excluded,
    }


def _prepare_single_group_data(
    *,
    subjects,
    conditions,
    conditions_all,
    subject_data,
    base_freq,
    rois,
    rois_all,
    dv_policy,
    outlier_exclusion_enabled,
    outlier_abs_limit,
    qc_config,
    qc_state,
    manual_excluded_pids,
    message_cb,
    project_root: str | None = None,
) -> tuple[
    list[str],
    dict,
    dict,
    pd.DataFrame,
    dict,
    QcExclusionReport | None,
    OutlierExclusionReport,
    list[DvViolation],
    list[str],
]:
    all_subjects = list(subjects) if subjects else []
    settings = normalize_dv_policy(dv_policy)
    if settings.name == GROUP_SIGNIFICANT_POLICY_NAME:
        resolved_preflight_max = _resolve_max_freq(None)
        if _has_valid_project_group_harmonic_cache(
            project_root=project_root,
            subjects=all_subjects,
            conditions=list(conditions) if conditions else [],
            subject_data=subject_data,
            base_freq=base_freq,
            max_freq=resolved_preflight_max,
            settings=settings,
        ):
            message_cb(
                "Project metadata contains matching significant harmonics; "
                "skipping FullFFT preflight."
            )
        else:
            preflight_group_significant_full_fft_columns(
                subjects=all_subjects,
                conditions=list(conditions) if conditions else [],
                subject_data=subject_data,
                base_frequency_hz=base_freq,
                log_func=message_cb,
                max_freq=resolved_preflight_max,
            )
    subjects, subject_data, qc_report = _apply_qc_screening(
        subjects=all_subjects,
        subject_data=subject_data,
        conditions_all=list(conditions_all) if conditions_all else [],
        rois_all=rois_all or rois,
        base_freq=base_freq,
        message_cb=message_cb,
        qc_config=qc_config,
        qc_state=qc_state,
    )
    subjects, subject_data, manual_excluded = _apply_manual_exclusions(
        subjects=list(subjects) if subjects else [],
        subject_data=subject_data,
        manual_excluded_pids=manual_excluded_pids,
        message_cb=message_cb,
    )
    if not subjects:
        raise RuntimeError("All participants excluded by manual exclusions.")

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
        selection_conditions=list(conditions or []),
        project_root=project_root,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    df_long = _long_format_from_bca(all_subject_bca_data)
    df_long, exclusion_report = _apply_outlier_exclusion(
        df_long,
        enabled=outlier_exclusion_enabled,
        abs_limit=outlier_abs_limit,
        message_cb=message_cb,
    )
    exclusion_report = merge_exclusion_reports(exclusion_report, qc_report)
    required_exclusions = _extract_required_exclusions(exclusion_report)
    required_pids = {violation.participant_id for violation in required_exclusions}
    if required_pids:
        all_subject_bca_data = {
            pid: data for pid, data in all_subject_bca_data.items() if pid not in required_pids
        }
        subjects = [pid for pid in subjects if pid not in required_pids]
        df_long = df_long[~df_long["subject"].astype(str).isin(required_pids)].copy()
    if not subjects or df_long.empty:
        raise RuntimeError("All participants excluded by required non-finite DV checks.")

    return (
        subjects,
        subject_data,
        all_subject_bca_data,
        df_long,
        dv_metadata,
        qc_report,
        exclusion_report,
        required_exclusions,
        manual_excluded,
    )


def _diag_subject_data_structure(subject_data, subjects, conditions, rois, message_cb) -> None:
    if not RM_ANOVA_DIAG or not message_cb:
        return
    subject_list = list(subjects) if subjects else sorted(subject_data.keys(), key=repr)
    condition_list = list(conditions) if conditions else []
    roi_list = sorted(rois.keys(), key=repr) if isinstance(rois, dict) else []
    message_cb("[RM_ANOVA DIAG] subject_data structure summary")
    message_cb(
        f"[RM_ANOVA DIAG] subjects={len(subject_list)} conditions={len(condition_list)} rois={len(roi_list)}"
    )


def _summarize_dv_metadata_for_export(dv_metadata: dict[str, object]) -> dict[str, object]:
    """Return scalar DV metadata fields suitable for result metadata sheets."""
    summary: dict[str, object] = {}
    if not isinstance(dv_metadata, dict):
        return summary
    policy_name = dv_metadata.get("policy_name")
    if policy_name is not None:
        summary["dv_policy_name"] = str(policy_name)
    fixed_meta = dv_metadata.get("fixed_predefined_harmonics")
    if isinstance(fixed_meta, dict):
        included = fixed_meta.get("fixed_harmonic_included_frequencies_hz", []) or []
        summary.update(
            {
                "harmonic_policy": fixed_meta.get("harmonic_policy", ""),
                "harmonic_policy_label": fixed_meta.get("harmonic_policy_label", ""),
                "selected_harmonics_hz": ";".join(f"{float(freq):g}" for freq in included),
                "snr_used_for_statistics": bool(fixed_meta.get("snr_used_for_statistics", False)),
                "applied_uniformly_across_participants": bool(
                    fixed_meta.get("applied_uniformly_across_participants", False)
                ),
                "applied_uniformly_across_conditions": bool(
                    fixed_meta.get("applied_uniformly_across_conditions", False)
                ),
                "applied_uniformly_across_rois": bool(
                    fixed_meta.get("applied_uniformly_across_rois", False)
                ),
            }
        )
    group_meta = dv_metadata.get("group_significant_harmonics")
    if isinstance(group_meta, dict):
        included = group_meta.get("selected_harmonics_hz", []) or []
        summary.update(
            {
                "harmonic_policy": group_meta.get("harmonic_policy", ""),
                "harmonic_policy_label": group_meta.get("harmonic_policy_label", ""),
                "selected_harmonics_hz": ";".join(f"{float(freq):g}" for freq in included),
                "highest_significant_harmonic_hz": group_meta.get(
                    "highest_significant_harmonic_hz",
                    "",
                ),
                "highest_significant_harmonic_index": group_meta.get(
                    "highest_significant_harmonic_index",
                    "",
                ),
                "selection_cache_source": group_meta.get("selection_cache_source", ""),
                "selection_cache_saved_at": group_meta.get("selection_cache_saved_at", ""),
                "selection_cache_key": group_meta.get("selection_cache_key", ""),
                "selection_scope": group_meta.get("selection_scope", ""),
                "z_threshold": group_meta.get("z_threshold", ""),
                "snr_used_for_statistics": bool(group_meta.get("snr_used_for_statistics", False)),
                "applied_uniformly_across_participants": bool(
                    group_meta.get("applied_uniformly_across_participants", False)
                ),
                "applied_uniformly_across_conditions": bool(
                    group_meta.get("applied_uniformly_across_conditions", False)
                ),
                "applied_uniformly_across_rois": bool(
                    group_meta.get("applied_uniformly_across_rois", False)
                ),
            }
        )
    return summary


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
    results_dir: str | None = None,
    outlier_exclusion_enabled: bool = True,
    outlier_abs_limit: float = 50.0,
    qc_config: dict | None = None,
    qc_state: dict | None = None,
    manual_excluded_pids: list[str] | None = None,
    project_root: str | None = None,
):
    _ = progress_cb
    set_rois(rois)
    message_cb("Preparing data for Summed BCA RM-ANOVA...")
    _log_dv_trace_policy_snapshot(
        dv_policy=dv_policy,
        base_freq=base_freq,
        conditions=list(conditions) if conditions else [],
        rois=rois,
        subjects=list(subjects) if subjects else [],
    )
    (
        subjects,
        subject_data,
        all_subject_bca_data,
        _df_long,
        dv_metadata,
        qc_report,
        exclusion_report,
        required_exclusions,
        manual_excluded,
    ) = _prepare_single_group_data(
        subjects=subjects,
        conditions=conditions,
        conditions_all=conditions_all,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois,
        rois_all=rois_all,
        dv_policy=dv_policy,
        outlier_exclusion_enabled=outlier_exclusion_enabled,
        outlier_abs_limit=outlier_abs_limit,
        qc_config=qc_config,
        qc_state=qc_state,
        manual_excluded_pids=manual_excluded_pids,
        project_root=project_root,
        message_cb=message_cb,
    )
    _diag_subject_data_structure(all_subject_bca_data, subjects, conditions, rois, message_cb)
    message_cb("Running RM-ANOVA...")
    output_text, anova_df_results = analysis_run_rm_anova(
        all_subject_bca_data,
        message_cb,
        subjects=list(subjects) if subjects else None,
        conditions=list(conditions) if conditions else None,
        rois=sorted(rois.keys()) if isinstance(rois, dict) else None,
        results_dir=results_dir,
    )
    if results_dir and isinstance(anova_df_results, pd.DataFrame):
        try:
            now_local = datetime.now()
            report_text = build_rm_anova_text_report(
                anova_df=anova_df_results,
                generated_local=now_local,
                project_name=None,
            )
            report_path = build_rm_anova_report_path(results_dir, now_local)
            report_path.write_text(report_text, encoding="utf-8")
            message_cb(f"RM-ANOVA text report exported: {report_path}")
        except Exception as exc:  # noqa: BLE001
            message_cb(f"RM-ANOVA text report export failed (non-blocking): {exc}")
            logger.exception("rm_anova_text_export_failed", exc_info=True)

    return {
        "anova_df_results": anova_df_results,
        "output_text": output_text,
        "dv_metadata": dv_metadata,
        "run_report": StatsRunReport(
            manual_excluded_pids=manual_excluded,
            qc_report=qc_report,
            dv_report=exclusion_report,
            required_exclusions=required_exclusions,
            final_modeled_pids=list(subjects) if subjects else [],
        ),
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
    dv_policy: dict | None = None,
    outlier_exclusion_enabled: bool = True,
    outlier_abs_limit: float = 50.0,
    qc_config: dict | None = None,
    qc_state: dict | None = None,
    manual_excluded_pids: list[str] | None = None,
    results_dir: str | None = None,
    project_root: str | None = None,
):
    _ = progress_cb
    set_rois(rois)
    message_cb("Preparing data for Mixed Effects Model...")
    _log_dv_trace_policy_snapshot(
        dv_policy=dv_policy,
        base_freq=base_freq,
        conditions=list(conditions) if conditions else [],
        rois=rois,
        subjects=list(subjects) if subjects else [],
    )
    (
        subjects,
        subject_data,
        all_subject_bca_data,
        df_long,
        dv_metadata,
        qc_report,
        exclusion_report,
        required_exclusions,
        manual_excluded,
    ) = _prepare_single_group_data(
        subjects=subjects,
        conditions=conditions,
        conditions_all=conditions_all,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois,
        rois_all=rois_all,
        dv_policy=dv_policy,
        outlier_exclusion_enabled=outlier_exclusion_enabled,
        outlier_abs_limit=outlier_abs_limit,
        qc_config=qc_config,
        qc_state=qc_state,
        manual_excluded_pids=manual_excluded_pids,
        project_root=project_root,
        message_cb=message_cb,
    )
    df_long = df_long.dropna(subset=["value"]).copy()
    if df_long.empty:
        raise RuntimeError("No valid rows for mixed model after filtering NaNs.")

    message_cb("Running Mixed Effects Model...")
    fixed_effects = ["condition * roi"]
    method_requested = "reml"
    re_formula_requested = "1"
    model_rows_input = len(df_long)
    model_rows_used = int(df_long.dropna(subset=["value", "subject", "condition", "roi"]).shape[0])
    mixed_results_df, mixed_model = run_mixed_effects_model(
        data=df_long,
        dv_col="value",
        group_col="subject",
        fixed_effects=fixed_effects,
        re_formula=re_formula_requested,
        method=method_requested,
        contrast_map=None,
        return_model=True,
    )
    mixed_results_df = repair_lmm_pvalues_from_z(mixed_results_df)
    mixed_results_df = ensure_lmm_effect_columns(mixed_results_df)
    formula = resolve_lmm_formula(model=mixed_model, fallback_formula="value ~ condition * roi")
    formula_rhs = formula.split("~", maxsplit=1)[1].strip() if "~" in formula else fixed_effects[0]
    contract = build_lmm_run_contract(
        formula=formula,
        method_used="REML",
        re_formula_used=re_formula_requested,
    )
    contrast_map = dict(contract.get("coding_map", {})) if isinstance(contract.get("coding_map"), dict) else {}
    converged, singular, optimizer, model_warnings = infer_lmm_diagnostics(mixed_results_df, mixed_model)
    fit_status = classify_lmm_fit_status(
        mixed_results_df,
        converged=converged,
        singular=singular,
    )
    backed_off = bool(
        mixed_results_df.get("Note", pd.Series(dtype=str))
        .astype(str)
        .str.contains("Fell back to random intercept", case=False, na=False)
        .any()
    )
    lrt_table = mixed_results_df.attrs.get("lrt_table") if isinstance(mixed_results_df.attrs.get("lrt_table"), pd.DataFrame) else None
    attach_lmm_run_metadata(
        table=mixed_results_df,
        formula=formula,
        fixed_effects=[formula_rhs],
        contrast_map=contrast_map,
        method_requested=method_requested,
        method_used="REML",
        re_formula_requested=re_formula_requested,
        re_formula_used=re_formula_requested,
        backed_off_random_slopes=backed_off,
        converged=converged,
        singular=singular,
        optimizer_used=optimizer,
        fit_warnings=model_warnings,
        rows_input=int(model_rows_input),
        rows_used=int(model_rows_used),
        subjects_used=int(df_long["subject"].nunique()),
        lrt_table=lrt_table,
    )

    output_text = "============================================================\n"
    output_text += "       Linear Mixed-Effects Model Results\n"
    output_text += "       Analysis conducted on: Summed BCA Data\n"
    output_text += "============================================================\n\n"
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

    if results_dir and isinstance(mixed_results_df, pd.DataFrame):
        try:
            now_local = datetime.now().astimezone()
            report_text = build_lmm_text_report(
                lmm_df=mixed_results_df,
                generated_local=now_local,
                project_name=None,
            )
            report_path = build_lmm_report_path(results_dir, now_local)
            report_path.write_text(report_text, encoding="utf-8")
            message_cb(f"LMM text report exported: {report_path}")
        except Exception as exc:  # noqa: BLE001
            message_cb(f"LMM text report export failed (non-blocking): {exc}")
            logger.error("lmm_text_export_failed", extra={"path": str(results_dir or ""), "exception": str(exc)})

    return {
        "status": fit_status["status"],
        "mixed_results_df": mixed_results_df,
        "output_text": output_text,
        "dv_metadata": dv_metadata,
        "fit_status": fit_status,
        "run_report": StatsRunReport(
            manual_excluded_pids=manual_excluded,
            qc_report=qc_report,
            dv_report=exclusion_report,
            required_exclusions=required_exclusions,
            final_modeled_pids=sorted(df_long["subject"].unique().tolist()),
        ),
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
    dv_policy: dict | None = None,
    outlier_exclusion_enabled: bool = True,
    outlier_abs_limit: float = 50.0,
    qc_config: dict | None = None,
    qc_state: dict | None = None,
    manual_excluded_pids: list[str] | None = None,
    project_root: str | None = None,
    **kwargs,
):
    _ = progress_cb
    set_rois(rois)
    message_cb("Preparing data for Interaction Post-hoc tests...")
    _log_dv_trace_policy_snapshot(
        dv_policy=dv_policy,
        base_freq=base_freq,
        conditions=list(conditions) if conditions else [],
        rois=rois,
        subjects=list(subjects) if subjects else [],
    )
    (
        subjects,
        subject_data,
        all_subject_bca_data,
        df_long,
        dv_metadata,
        qc_report,
        exclusion_report,
        required_exclusions,
        manual_excluded,
    ) = _prepare_single_group_data(
        subjects=subjects,
        conditions=conditions,
        conditions_all=conditions_all,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois,
        rois_all=rois_all,
        dv_policy=dv_policy,
        outlier_exclusion_enabled=outlier_exclusion_enabled,
        outlier_abs_limit=outlier_abs_limit,
        qc_config=qc_config,
        qc_state=qc_state,
        manual_excluded_pids=manual_excluded_pids,
        project_root=project_root,
        message_cb=message_cb,
    )
    if df_long.empty:
        raise RuntimeError("No valid rows for post-hoc tests after filtering NaNs.")

    requested_direction = kwargs.get("direction", kwargs.get("posthoc_direction", "both"))
    message_cb("Running post-hoc tests...")
    output_text, results_df = run_interaction_posthocs(
        data=df_long,
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        alpha=alpha,
        direction=requested_direction,
    )
    message_cb("Post-hoc interaction tests completed.")
    return {
        "results_df": results_df,
        "output_text": output_text,
        "dv_metadata": dv_metadata,
        "run_report": StatsRunReport(
            manual_excluded_pids=manual_excluded,
            qc_report=qc_report,
            dv_report=exclusion_report,
            required_exclusions=required_exclusions,
            final_modeled_pids=sorted(df_long["subject"].unique().tolist()),
        ),
    }


def run_baseline_vs_zero(
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
    dv_policy: dict | None = None,
    outlier_exclusion_enabled: bool = True,
    outlier_abs_limit: float = 50.0,
    qc_config: dict | None = None,
    qc_state: dict | None = None,
    manual_excluded_pids: list[str] | None = None,
    alternative: str = "greater",
    correction: str = "fdr_bh",
    correction_scope: str = "global",
    project_root: str | None = None,
):
    _ = progress_cb
    set_rois(rois)
    message_cb("Preparing data for baseline-vs-zero tests...")
    _log_dv_trace_policy_snapshot(
        dv_policy=dv_policy,
        base_freq=base_freq,
        conditions=list(conditions) if conditions else [],
        rois=rois,
        subjects=list(subjects) if subjects else [],
    )
    (
        subjects,
        _subject_data,
        _all_subject_bca_data,
        df_long,
        dv_metadata,
        qc_report,
        exclusion_report,
        required_exclusions,
        manual_excluded,
    ) = _prepare_single_group_data(
        subjects=subjects,
        conditions=conditions,
        conditions_all=conditions_all,
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois,
        rois_all=rois_all,
        dv_policy=dv_policy,
        outlier_exclusion_enabled=outlier_exclusion_enabled,
        outlier_abs_limit=outlier_abs_limit,
        qc_config=qc_config,
        qc_state=qc_state,
        manual_excluded_pids=manual_excluded_pids,
        project_root=project_root,
        message_cb=message_cb,
    )
    if df_long.empty:
        raise RuntimeError("No rows available for baseline-vs-zero tests after exclusions.")

    message_cb("Running baseline-vs-zero tests...")
    output_text, results_df = run_baseline_vs_zero_tests(
        df_long,
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        alpha=alpha,
        alternative=alternative,
        correction=correction,
        correction_scope=correction_scope,
    )
    message_cb(output_text)
    result_metadata = {
        "dv_col": "value",
        "alpha": alpha,
        "alternative": alternative,
        "correction": correction,
        "correction_scope": correction_scope,
        "total_unique_subjects": int(df_long["subject"].nunique()),
    }
    result_metadata.update(_summarize_dv_metadata_for_export(dv_metadata))
    return {
        "results_df": results_df,
        "output_text": output_text,
        "metadata": result_metadata,
        "dv_metadata": dv_metadata,
        "run_report": StatsRunReport(
            manual_excluded_pids=manual_excluded,
            qc_report=qc_report,
            dv_report=exclusion_report,
            required_exclusions=required_exclusions,
            final_modeled_pids=sorted(df_long["subject"].unique().tolist()),
        ),
    }


def run_harmonics_preview(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    conditions_all=None,
    subject_data,
    base_freq,
    rois,
    dv_policy: dict | None = None,
):
    _ = progress_cb, conditions_all, rois
    return build_fixed_predefined_preview_payload(
        subjects=subjects,
        conditions=list(conditions or []),
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
        dv_policy=dv_policy,
    )


