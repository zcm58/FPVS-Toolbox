"""Controller layer for coordinating the single-group Stats pipeline."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

from Tools.Stats.workers import stats_workers
from Tools.Stats.common.stats_core import PipelineId, PipelineStep, StepId
from Tools.Stats.reporting.stats_logging import format_step_event
from Tools.Stats.reporting.stats_run_report import StatsRunReport

logger = logging.getLogger(__name__)


class StatsViewProtocol:
    """Minimal interface the controller expects from the view."""

    def append_log(self, section: str, message: str, level: str = "info") -> None:
        ...

    def set_busy(self, is_busy: bool) -> None:
        ...

    def start_step_worker(
        self,
        pipeline_id: PipelineId,
        step: PipelineStep,
        *,
        finished_cb: Callable[[PipelineId, StepId, object], None],
        error_cb: Callable[[PipelineId, StepId, str], None],
        message_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        ...

    def on_pipeline_started(self, pipeline_id: PipelineId) -> None:
        ...

    def on_analysis_finished(
        self,
        pipeline_id: PipelineId,
        success: bool,
        error_message: Optional[str],
        *,
        exports_ran: bool,
    ) -> None:
        ...

    def ensure_pipeline_ready(
        self, pipeline_id: PipelineId, *, require_anova: bool = False
    ) -> bool:
        ...

    def export_pipeline_results(self, pipeline_id: PipelineId) -> bool:
        ...

    def build_and_render_summary(self, pipeline_id: PipelineId) -> None:
        ...

    def get_step_config(
        self, pipeline_id: PipelineId, step_id: StepId
    ) -> tuple[dict, Callable[[dict], None]]:
        ...

    def store_run_report(self, pipeline_id: PipelineId, report: StatsRunReport) -> None:
        ...

    def ensure_results_dir(self) -> str:
        ...

    def get_analysis_settings_snapshot(self) -> tuple[float, float, dict, list[str]]:
        ...


@dataclass
class SectionRunState:
    """Runtime state for one Stats pipeline run."""

    pipeline_id: PipelineId
    current_step_index: int = 0
    steps: Sequence[PipelineStep] = field(default_factory=tuple)
    running: bool = False
    failed: bool = False
    start_ts: float = 0.0
    results: Dict[StepId, dict] = field(default_factory=dict)
    run_exports: bool = True
    run_summary: bool = True


SINGLE_PIPELINE_STEPS: Sequence[StepId] = (
    StepId.RM_ANOVA,
    StepId.MIXED_MODEL,
    StepId.INTERACTION_POSTHOCS,
    StepId.BASELINE_VS_ZERO,
    StepId.HARMONIC_CHECK,
)
"""Default ordered steps for the single-group pipeline."""

STEP_LABELS: Dict[StepId, str] = {
    StepId.RM_ANOVA: "RM-ANOVA",
    StepId.MIXED_MODEL: "Mixed Model",
    StepId.INTERACTION_POSTHOCS: "Interaction Post-hocs",
    StepId.BASELINE_VS_ZERO: "Baseline vs Zero",
    StepId.HARMONIC_CHECK: "Harmonic Check",
}

WORKER_FN_BY_STEP: Dict[StepId, Callable[..., Any]] = {
    StepId.RM_ANOVA: stats_workers.run_rm_anova,
    StepId.MIXED_MODEL: stats_workers.run_lmm,
    StepId.INTERACTION_POSTHOCS: stats_workers.run_posthoc,
    StepId.BASELINE_VS_ZERO: stats_workers.run_baseline_vs_zero,
    StepId.HARMONIC_CHECK: stats_workers.run_harmonic_check,
}


class StatsController:
    """Coordinate single-group Stats pipeline runs."""

    def __init__(self, view: StatsViewProtocol) -> None:
        self._view = view
        self._states: Dict[PipelineId, SectionRunState] = {
            PipelineId.SINGLE: SectionRunState(pipeline_id=PipelineId.SINGLE),
        }

    def run_single_group_analysis(
        self,
        *,
        step_ids: Optional[Sequence[StepId]] = None,
        run_exports: bool = True,
        run_summary: bool = True,
        require_anova: bool = False,
    ) -> None:
        self._start_pipeline(
            PipelineId.SINGLE,
            step_ids or SINGLE_PIPELINE_STEPS,
            run_exports=run_exports,
            run_summary=run_summary,
            require_anova=require_anova,
        )

    def run_single_group_rm_anova_only(self) -> None:
        self.run_single_group_analysis(
            step_ids=(StepId.RM_ANOVA,), run_exports=False, run_summary=False
        )

    def run_single_group_mixed_model_only(self) -> None:
        self.run_single_group_analysis(
            step_ids=(StepId.MIXED_MODEL,), run_exports=False, run_summary=False
        )

    def run_single_group_posthoc_only(self) -> None:
        self.run_single_group_analysis(
            step_ids=(StepId.INTERACTION_POSTHOCS,),
            run_exports=False,
            run_summary=False,
            require_anova=True,
        )

    def run_harmonic_check_only(self) -> None:
        self._start_pipeline(
            PipelineId.SINGLE,
            (StepId.HARMONIC_CHECK,),
            run_exports=False,
            run_summary=False,
        )

    def is_running(self, pipeline_id: PipelineId | None = None) -> bool:
        if pipeline_id is not None:
            return self._states[pipeline_id].running
        return any(state.running for state in self._states.values())

    def _build_steps(
        self,
        pipeline_id: PipelineId,
        step_ids: Sequence[StepId],
    ) -> tuple[PipelineStep, ...]:
        steps: list[PipelineStep] = []
        for step_id in step_ids:
            worker_fn = WORKER_FN_BY_STEP[step_id]
            kwargs, handler = self._view.get_step_config(pipeline_id, step_id)
            steps.append(
                PipelineStep(
                    id=step_id,
                    name=STEP_LABELS[step_id],
                    worker_fn=worker_fn,
                    kwargs=kwargs,
                    handler=handler,
                )
            )
        return tuple(steps)

    def _start_pipeline(
        self,
        pipeline_id: PipelineId,
        step_ids: Sequence[StepId],
        *,
        run_exports: bool,
        run_summary: bool,
        require_anova: bool = False,
    ) -> None:
        state = self._states[pipeline_id]
        if state.running:
            self._view.append_log("Single", "Analysis is already running.", level="warning")
            return
        if not self._view.ensure_pipeline_ready(pipeline_id, require_anova=require_anova):
            return
        try:
            steps = self._build_steps(pipeline_id, step_ids)
        except Exception as exc:  # noqa: BLE001
            self._view.append_log("Single", f"Unable to start analysis: {exc}", level="error")
            return
        if not steps:
            self._view.append_log("Single", "No analysis steps were requested.", level="warning")
            return

        state.current_step_index = 0
        state.steps = steps
        state.running = True
        state.failed = False
        state.results = {}
        state.run_exports = run_exports
        state.run_summary = run_summary
        state.start_ts = time.perf_counter()
        self._view.set_busy(True)
        self._view.on_pipeline_started(pipeline_id)
        self._run_next_step(pipeline_id)

    def _run_next_step(self, pipeline_id: PipelineId) -> None:
        state = self._states[pipeline_id]
        if state.current_step_index >= len(state.steps):
            self._complete_pipeline(pipeline_id)
            return
        step = state.steps[state.current_step_index]
        self._view.append_log(
            "Single",
            format_step_event(
                pipeline_id,
                step.id,
                event="start",
                message=f"{step.name} started",
            ),
        )
        self._view.start_step_worker(
            pipeline_id,
            step,
            finished_cb=self._on_step_finished,
            error_cb=self._on_step_error,
            message_cb=lambda msg: self._view.append_log("Single", msg),
        )

    def _on_step_finished(self, pipeline_id: PipelineId, step_id: StepId, payload: object) -> None:
        state = self._states[pipeline_id]
        if not state.running:
            return
        if state.current_step_index >= len(state.steps):
            self._on_step_error(pipeline_id, step_id, "Received completion with no pending step.")
            return
        step = state.steps[state.current_step_index]
        try:
            if isinstance(payload, dict) and str(payload.get("status", "")).lower() == "blocked":
                blocked_message = str(payload.get("message") or "Analysis blocked.")
                self._view.append_log("Single", blocked_message, level="warning")
                state.results[step_id] = payload
                self._finalize_pipeline(
                    pipeline_id,
                    success=False,
                    error_message=blocked_message,
                    exports_ran=False,
                )
                return
            step.handler(payload)
            state.results[step_id] = payload if isinstance(payload, dict) else {"result": payload}
            run_report = payload.get("run_report") if isinstance(payload, dict) else None
            if isinstance(run_report, StatsRunReport):
                self._view.store_run_report(pipeline_id, run_report)
        except Exception as exc:  # noqa: BLE001
            logger.exception("stats_step_handler_error", extra={"step": step_id.name})
            self._on_step_error(pipeline_id, step_id, f"Step handler failed: {exc}")
            return

        self._view.append_log(
            "Single",
            format_step_event(
                pipeline_id,
                step.id,
                event="complete",
                message=f"{step.name} completed",
            ),
        )
        state.current_step_index += 1
        self._run_next_step(pipeline_id)

    def _on_step_error(self, pipeline_id: PipelineId, step_id: StepId, error_message: str) -> None:
        state = self._states[pipeline_id]
        state.failed = True
        self._view.append_log(
            "Single",
            format_step_event(
                pipeline_id,
                step_id,
                event="error",
                message=f"ERROR: {error_message}",
            ),
            level="error",
        )
        self._finalize_pipeline(
            pipeline_id,
            success=False,
            error_message=error_message,
            exports_ran=False,
        )

    def _complete_pipeline(self, pipeline_id: PipelineId) -> None:
        state = self._states[pipeline_id]
        elapsed = time.perf_counter() - state.start_ts if state.start_ts else 0.0
        exports_ran = False
        success = True
        error_message: Optional[str] = None
        try:
            if state.run_exports:
                exports_ran = bool(self._view.export_pipeline_results(pipeline_id))
                if not exports_ran:
                    success = False
                    error_message = "Export failed"
            if success and state.run_summary:
                self._view.build_and_render_summary(pipeline_id)
            if success:
                self._view.append_log("Single", f"Single-Group Analysis finished in {elapsed:.1f} s")
        except Exception as exc:  # noqa: BLE001
            logger.exception("stats_pipeline_complete_error", extra={"error": str(exc)})
            success = False
            error_message = error_message or f"Error during finalization: {exc}"
            self._view.append_log("Single", error_message, level="error")
        finally:
            self._finalize_pipeline(
                pipeline_id,
                success=success,
                error_message=error_message,
                exports_ran=exports_ran if success else False,
            )

    def _finalize_pipeline(
        self,
        pipeline_id: PipelineId,
        *,
        success: bool,
        error_message: Optional[str],
        exports_ran: bool = False,
    ) -> None:
        state = self._states[pipeline_id]
        state.running = False
        state.failed = not success
        state.steps = ()
        state.run_exports = True
        state.run_summary = True
        state.start_ts = 0.0
        self._view.set_busy(False)
        self._view.on_analysis_finished(
            pipeline_id,
            success=success,
            error_message=error_message,
            exports_ran=exports_ran if success else False,
        )


__all__ = [
    "SINGLE_PIPELINE_STEPS",
    "STEP_LABELS",
    "WORKER_FN_BY_STEP",
    "StatsController",
    "SectionRunState",
    "StatsViewProtocol",
]
