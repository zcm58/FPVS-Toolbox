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
import time
from typing import Any, Callable, Dict

import numpy as np

import pandas as pd
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from Tools.Stats.Legacy.interpretation_helpers import generate_lme_summary
from Tools.Stats.Legacy.group_contrasts import compute_group_contrasts
from Tools.Stats.Legacy.mixed_effects_model import run_mixed_effects_model
from Tools.Stats.Legacy.mixed_group_anova import run_mixed_group_anova
from Tools.Stats.Legacy.posthoc_tests import run_interaction_posthocs
from Tools.Stats.Legacy.stats_analysis import (
    prepare_all_subject_summed_bca_data,
    run_harmonic_check as run_harmonic_check_new,
    run_rm_anova as analysis_run_rm_anova,
    set_rois,
)

logger = logging.getLogger("Tools.Stats")


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
                self.signals.finished.emit(payload)
            except Exception as emit_exc:  # noqa: BLE001
                logger.error(
                    "stats_run_emit_failed",
                    extra={
                        "op": self._op,
                        "callable": getattr(self._fn, "__name__", str(self._fn)),
                        "exc": repr(emit_exc),
                    },
                )
                self.signals.error.emit(f"Worker emit failed: {emit_exc}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("stats_run_failed", extra={"op": self._op, "exc_type": type(exc).__name__})
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


def run_rm_anova(progress_cb, message_cb, *, subjects, conditions, subject_data, base_freq, rois):
    set_rois(rois)
    message_cb("Preparing data for Summed BCA RM-ANOVA…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")
    message_cb("Running RM-ANOVA…")
    _, anova_df_results = analysis_run_rm_anova(all_subject_bca_data, message_cb)
    return {"anova_df_results": anova_df_results}


def run_between_group_anova(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    subject_data,
    base_freq,
    rois,
    subject_groups: dict[str, str | None] | None = None,
):
    set_rois(rois)
    message_cb("Preparing data for Between-Group RM-ANOVA…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
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
    return {"anova_df_results": results}


def run_lmm(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    subject_data,
    base_freq,
    alpha,
    rois,
    subject_groups: dict[str, str | None] | None = None,
    include_group: bool = False,
):
    set_rois(rois)
    prep_label = "Mixed Effects Model" if not include_group else "Between-Group Mixed Model"
    message_cb(f"Preparing data for {prep_label}…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
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

    return {"mixed_results_df": mixed_results_df, "output_text": output_text}


def run_posthoc(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    subject_data,
    base_freq,
    alpha,
    rois,
    subject_groups: dict[str, str | None] | None = None,
):
    set_rois(rois)
    message_cb("Preparing data for Interaction Post-hoc tests…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
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
    return {"results_df": results_df, "output_text": output_text}


def run_group_contrasts(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    subject_data,
    base_freq,
    alpha,
    rois,
    subject_groups: dict[str, str | None] | None = None,
):
    set_rois(rois)
    _ = alpha
    message_cb("Preparing data for Between-Group Contrasts…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
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
    }


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
    return {"output_text": output_text, "findings": findings}

