# src/Tools/Stats/PySide6/stats_controller.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

from . import stats_workers
from .stats_core import PipelineId, PipelineStep, StepId
from .stats_logging import format_step_event

logger = logging.getLogger(__name__)


class StatsViewProtocol:
    """Minimal interface the controller expects from the view (StatsWindow)."""

    def append_log(self, section: str, message: str, level: str = "info") -> None: ...

    def set_busy(self, is_busy: bool) -> None: ...

    def start_step_worker(
        self,
        pipeline_id: PipelineId,
        step: PipelineStep,
        *,
        finished_cb: Callable[[PipelineId, StepId, dict], None],
        error_cb: Callable[[PipelineId, StepId, str], None],
    ) -> None: ...

    def on_pipeline_started(self, pipeline_id: PipelineId) -> None: ...

    def on_analysis_finished(
        self,
        pipeline_id: PipelineId,
        success: bool,
        error_message: Optional[str],
        *,
        exports_ran: bool,
    ) -> None: ...

    def ensure_pipeline_ready(
        self, pipeline_id: PipelineId, *, require_anova: bool = False
    ) -> bool: ...

    def export_pipeline_results(self, pipeline_id: PipelineId) -> bool: ...

    def build_and_render_summary(self, pipeline_id: PipelineId) -> None: ...

    def get_step_config(
        self, pipeline_id: PipelineId, step_id: StepId
    ) -> tuple[dict, Callable[[dict], None]]: ...


@dataclass
class SectionRunState:
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
)

BETWEEN_PIPELINE_STEPS: Sequence[StepId] = (
    StepId.BETWEEN_GROUP_ANOVA,
    StepId.BETWEEN_GROUP_MIXED_MODEL,
    StepId.GROUP_CONTRASTS,
)

STEP_LABELS: Dict[StepId, str] = {
    StepId.RM_ANOVA: "RM-ANOVA",
    StepId.MIXED_MODEL: "Mixed Model",
    StepId.INTERACTION_POSTHOCS: "Interaction Post-hocs",
    StepId.BETWEEN_GROUP_ANOVA: "Between-Group ANOVA",
    StepId.BETWEEN_GROUP_MIXED_MODEL: "Between-Group Mixed Model",
    StepId.GROUP_CONTRASTS: "Group Contrasts",
    StepId.HARMONIC_CHECK: "Harmonic Check",
}

WORKER_FN_BY_STEP: Dict[StepId, Callable[..., Any]] = {
    StepId.RM_ANOVA: stats_workers.run_rm_anova,
    StepId.MIXED_MODEL: stats_workers.run_lmm,
    StepId.INTERACTION_POSTHOCS: stats_workers.run_posthoc,
    StepId.BETWEEN_GROUP_ANOVA: stats_workers.run_between_group_anova,
    StepId.BETWEEN_GROUP_MIXED_MODEL: stats_workers.run_lmm,
    StepId.GROUP_CONTRASTS: stats_workers.run_group_contrasts,
    StepId.HARMONIC_CHECK: stats_workers.run_harmonic_check,
}


class StatsController:
    def __init__(self, view: StatsViewProtocol) -> None:
        self._view = view
        self._states: Dict[PipelineId, SectionRunState] = {
            PipelineId.SINGLE: SectionRunState(pipeline_id=PipelineId.SINGLE),
            PipelineId.BETWEEN: SectionRunState(pipeline_id=PipelineId.BETWEEN),
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

    def run_between_group_analysis(
        self,
        *,
        step_ids: Optional[Sequence[StepId]] = None,
        run_exports: bool = True,
        run_summary: bool = True,
    ) -> None:
        self._start_pipeline(
            PipelineId.BETWEEN,
            step_ids or BETWEEN_PIPELINE_STEPS,
            run_exports=run_exports,
            run_summary=run_summary,
        )

    def run_between_group_anova_only(self) -> None:
        self.run_between_group_analysis(
            step_ids=(StepId.BETWEEN_GROUP_ANOVA,),
            run_exports=False,
            run_summary=False,
        )

    def run_between_group_mixed_only(self) -> None:
        self.run_between_group_analysis(
            step_ids=(StepId.BETWEEN_GROUP_MIXED_MODEL,),
            run_exports=False,
            run_summary=False,
        )

    def run_between_group_contrasts_only(self) -> None:
        self.run_between_group_analysis(
            step_ids=(StepId.GROUP_CONTRASTS,),
            run_exports=False,
            run_summary=False,
        )

    def is_running(self, pipeline_id: PipelineId) -> bool:
        return self._states[pipeline_id].running

    def _start_pipeline(
        self,
        pipeline_id: PipelineId,
        step_ids: Sequence[StepId],
        *,
        run_exports: bool = True,
        run_summary: bool = True,
        require_anova: bool = False,
    ) -> None:
        state = self._states[pipeline_id]
        if state.running:
            self._view.append_log(
                self._section_label(pipeline_id),
                f"{self._section_name(pipeline_id)} already running; new request ignored.",
                level="warning",
            )
            return

        if not step_ids:
            self._view.append_log(
                self._section_label(pipeline_id),
                f"{self._section_name(pipeline_id)} requested with no steps; aborting.",
                level="error",
            )
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message="No steps to run",
                exports_ran=False,
            )
            return

        if not self._view.ensure_pipeline_ready(
            pipeline_id, require_anova=require_anova
        ):
            self._view.append_log(
                self._section_label(pipeline_id),
                f"{self._section_name(pipeline_id)} prerequisites not met; aborting.",
                level="error",
            )
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message="Precheck failed",
                exports_ran=False,
            )
            return

        try:
            state.steps = self._build_steps(pipeline_id, step_ids)
        except Exception as exc:  # noqa: BLE001
            logger.exception("stats_build_steps_failed", exc_info=True)
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message=f"Failed to prepare steps: {exc}",
                exports_ran=False,
            )
            return
        state.running = True
        state.failed = False
        state.current_step_index = 0
        state.results.clear()
        state.start_ts = time.perf_counter()
        state.run_exports = run_exports
        state.run_summary = run_summary

        self._view.set_busy(True)
        self._view.on_pipeline_started(pipeline_id)
        summary = f"{self._section_name(pipeline_id)} started with {len(state.steps)} steps"
        self._view.append_log(self._section_label(pipeline_id), summary)
        self._run_next_step(pipeline_id)

    def _build_steps(
        self, pipeline_id: PipelineId, step_ids: Sequence[StepId]
    ) -> Sequence[PipelineStep]:
        steps: list[PipelineStep] = []
        for step_id in step_ids:
            worker_fn = WORKER_FN_BY_STEP[step_id]
            kwargs, handler = self._view.get_step_config(pipeline_id, step_id)
            steps.append(
                PipelineStep(
                    step_id,
                    STEP_LABELS.get(step_id, step_id.name),
                    worker_fn,
                    kwargs,
                    handler,
                )
            )
        return tuple(steps)

    def _run_next_step(self, pipeline_id: PipelineId) -> None:
        state = self._states[pipeline_id]
        if not state.steps or state.current_step_index >= len(state.steps):
            self._complete_pipeline(pipeline_id)
            return

        step = state.steps[state.current_step_index]
        section = self._section_label(pipeline_id)
        logger.info(
            "stats_step_start",
            extra={"pipeline": pipeline_id.name, "step": step.id.name},
        )
        self._view.append_log(
            section,
            format_step_event(
                pipeline_id, step.id, event="start", message=f"Starting {step.name}"
            ),
        )
        self._view.start_step_worker(
            pipeline_id,
            step,
            finished_cb=self._on_step_finished,
            error_cb=self._on_step_error,
        )

    def _on_step_finished(self, pipeline_id: PipelineId, step_id: StepId, payload: dict) -> None:
        state = self._states[pipeline_id]
        if not state.running:
            return
        step = state.steps[state.current_step_index]
        try:
            step.handler(payload)
            state.results[step_id] = payload
        except Exception as exc:  # noqa: BLE001
            logger.exception("stats_step_failed", extra={"step": step_id.name})
            self._on_step_error(pipeline_id, step_id, str(exc))
            return

        logger.info(
            "stats_step_complete",
            extra={"pipeline": pipeline_id.name, "step": step_id.name},
        )
        self._view.append_log(
            self._section_label(pipeline_id),
            format_step_event(
                pipeline_id, step_id, event="complete", message=f"{step.name} completed"
            ),
        )
        state.current_step_index += 1
        self._run_next_step(pipeline_id)

    def _on_step_error(self, pipeline_id: PipelineId, step_id: StepId, error_message: str) -> None:
        state = self._states[pipeline_id]
        section = self._section_label(pipeline_id)
        state.failed = True
        logger.error(
            "stats_step_error",
            extra={
                "pipeline": pipeline_id.name,
                "step": step_id.name,
                "error": error_message,
            },
        )
        self._view.append_log(
            section,
            format_step_event(
                pipeline_id, step_id, event="error", message=f"ERROR: {error_message}"
            ),
            level="error",
        )
        self._finalize_pipeline(
            pipeline_id, success=False, error_message=error_message, exports_ran=False
        )

    def _complete_pipeline(self, pipeline_id: PipelineId) -> None:
        state = self._states[pipeline_id]
        section = self._section_label(pipeline_id)
        elapsed = time.perf_counter() - state.start_ts if state.start_ts else 0.0

        try:
            if state.run_exports:
                exported = self._view.export_pipeline_results(pipeline_id)
                if not exported:
                    self._view.append_log(
                        section,
                        "  • Export failed; see log for details",
                        level="error",
                    )
                    self._finalize_pipeline(
                        pipeline_id,
                        success=False,
                        error_message="Export failed",
                        exports_ran=False,
                    )
                    return

            if state.run_summary:
                self._view.build_and_render_summary(pipeline_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_pipeline_completion_failed",
                exc_info=True,
                extra={"pipeline": pipeline_id.name},
            )
            self._view.append_log(
                section,
                f"  • Error completing pipeline: {exc}",
                level="error",
            )
            self._finalize_pipeline(
                pipeline_id, success=False, error_message=str(exc), exports_ran=False
            )
            return

        self._view.append_log(
            section,
            f"{self._section_name(pipeline_id)} finished in {elapsed:.1f} s",
        )
        self._finalize_pipeline(
            pipeline_id,
            success=True,
            error_message=None,
            exports_ran=state.run_exports,
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
        state.failed = False
        state.steps = ()
        state.run_exports = True
        state.run_summary = True
        self._view.set_busy(False)
        self._view.on_analysis_finished(
            pipeline_id,
            success=success,
            error_message=error_message,
            exports_ran=exports_ran if success else False,
        )

    def _section_label(self, pipeline_id: PipelineId) -> str:
        return "Single" if pipeline_id is PipelineId.SINGLE else "Between"

    def _section_name(self, pipeline_id: PipelineId) -> str:
        return "Single Group Analysis" if pipeline_id is PipelineId.SINGLE else "Between-Group Analysis"


__all__ = ["StatsController", "SectionRunState", "StatsViewProtocol"]
