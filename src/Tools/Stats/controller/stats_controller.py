"""Controller layer for coordinating native single- and multi-group pipelines."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Sequence

from Tools.Stats.analysis.repeated_m_anova import (
    resolve_rm_anova_interaction_gate,
)
from Tools.Stats.common.stats_core import PipelineId, PipelineStep, StepId
from Tools.Stats.reporting.stats_logging import format_step_event
from Tools.Stats.reporting.stats_run_report import StatsRunReport
from Tools.Stats.workers import multigroup_workers

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
        cancelled: bool = False,
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

    def cancel_active_worker(self, pipeline_id: PipelineId) -> None:
        ...


@dataclass
class SectionRunState:
    """Runtime state for one Stats pipeline run."""

    pipeline_id: PipelineId
    current_step_index: int = 0
    steps: Sequence[PipelineStep] = field(default_factory=tuple)
    running: bool = False
    failed: bool = False
    cancelled: bool = False
    cancellation_requested: bool = False
    cancellation_generation: int | None = None
    cancel_event: threading.Event | None = None
    start_ts: float = 0.0
    results: Dict[StepId, dict] = field(default_factory=dict)
    prepared_payload: object | None = None
    exports_ran: bool = False
    run_exports: bool = True
    run_summary: bool = True
    run_generation: int = 0
    last_outcome: str | None = None


SINGLE_PIPELINE_STEPS: Sequence[StepId] = (
    StepId.PREPARE_ANALYSIS,
    StepId.BASELINE_VS_ZERO,
    StepId.MIXED_MODEL,
    StepId.SENSITIVITIES,
    StepId.REPORT_BUNDLE,
)
"""Default ordered steps for the single-group pipeline."""

MULTI_PIPELINE_STEPS: Sequence[StepId] = (
    StepId.PREPARE_ANALYSIS,
    StepId.BASELINE_VS_ZERO,
    StepId.MULTIGROUP_MODEL,
    StepId.SENSITIVITIES,
    StepId.REPORT_BUNDLE,
)
"""Default ordered steps for the native multi-group pipeline."""

PIPELINE_ALLOWED_STEPS: Dict[PipelineId, frozenset[StepId]] = {
    PipelineId.SINGLE: frozenset(
        {
            *SINGLE_PIPELINE_STEPS,
            # Compatibility-only actions remain callable until the balanced
            # ANOVA check replaces the legacy advanced actions.
            StepId.RM_ANOVA,
            StepId.INTERACTION_POSTHOCS,
        }
    ),
    PipelineId.MULTI: frozenset(MULTI_PIPELINE_STEPS),
}

CANCELLABLE_STEPS: frozenset[StepId] = frozenset(
    {
        StepId.PREPARE_ANALYSIS,
        StepId.RM_ANOVA,
        StepId.MIXED_MODEL,
        StepId.INTERACTION_POSTHOCS,
        StepId.BASELINE_VS_ZERO,
        StepId.MULTIGROUP_MODEL,
        StepId.SENSITIVITIES,
        StepId.REPORT_BUNDLE,
    }
)

STEP_LABELS: Dict[StepId, str] = {
    StepId.RM_ANOVA: "RM-ANOVA",
    StepId.MIXED_MODEL: "Mixed Model",
    StepId.INTERACTION_POSTHOCS: "Interaction Post-hocs",
    StepId.BASELINE_VS_ZERO: "Baseline vs Zero",
    StepId.PREPARE_ANALYSIS: "Prepare Analysis",
    StepId.MULTIGROUP_MODEL: "Multi-group Model",
    StepId.GROUP_CELL_COMPARISONS: "Group Cell Comparisons",
    StepId.SENSITIVITIES: "Sensitivity Analyses",
    StepId.REPORT_BUNDLE: "Report Bundle",
}

WORKER_FN_BY_STEP: Dict[StepId, Callable[..., Any]] = {
    StepId.PREPARE_ANALYSIS: multigroup_workers.run_prepare_analysis,
    StepId.RM_ANOVA: multigroup_workers.run_single_rm_anova_step,
    StepId.MIXED_MODEL: multigroup_workers.run_single_lmm_step,
    StepId.INTERACTION_POSTHOCS: multigroup_workers.run_single_posthoc_step,
    StepId.BASELINE_VS_ZERO: multigroup_workers.run_baseline_step,
    StepId.MULTIGROUP_MODEL: multigroup_workers.run_multigroup_model_step,
    StepId.SENSITIVITIES: multigroup_workers.run_sensitivity_step,
    StepId.REPORT_BUNDLE: multigroup_workers.run_report_bundle_step,
}

PIPELINE_LABELS: Dict[PipelineId, str] = {
    PipelineId.SINGLE: "Single",
    PipelineId.MULTI: "Multi-group",
}

PIPELINE_COMPLETION_LABELS: Dict[PipelineId, str] = {
    PipelineId.SINGLE: "Single-Group",
    PipelineId.MULTI: "Multi-Group",
}


class StatsController:
    """Coordinate single- and multi-group Stats pipeline runs."""

    def __init__(self, view: StatsViewProtocol) -> None:
        self._view = view
        self._states: Dict[PipelineId, SectionRunState] = {
            PipelineId.SINGLE: SectionRunState(pipeline_id=PipelineId.SINGLE),
            PipelineId.MULTI: SectionRunState(pipeline_id=PipelineId.MULTI),
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

    def run_multigroup_analysis(
        self,
        *,
        step_ids: Optional[Sequence[StepId]] = None,
        run_exports: bool = True,
        run_summary: bool = True,
    ) -> None:
        """Run the native multi-group pipeline."""

        self._start_pipeline(
            PipelineId.MULTI,
            step_ids or MULTI_PIPELINE_STEPS,
            run_exports=run_exports,
            run_summary=run_summary,
        )

    def is_running(self, pipeline_id: PipelineId | None = None) -> bool:
        if pipeline_id is not None:
            return self._states[pipeline_id].running
        return any(state.running for state in self._states.values())

    @staticmethod
    def _normalize_step_ids(
        pipeline_id: PipelineId,
        step_ids: Sequence[StepId],
        *,
        require_report: bool,
    ) -> tuple[StepId, ...]:
        """Return one valid, deterministic step queue for a pipeline."""

        requested = tuple(step_ids)
        if not requested:
            return ()
        if any(not isinstance(step_id, StepId) for step_id in requested):
            raise ValueError("Every requested analysis step must be a StepId.")
        if len(set(requested)) != len(requested):
            raise ValueError("Duplicate analysis steps are not allowed.")

        invalid = [
            step_id
            for step_id in requested
            if step_id not in PIPELINE_ALLOWED_STEPS[pipeline_id]
        ]
        if invalid:
            labels = ", ".join(step_id.name for step_id in invalid)
            raise ValueError(
                f"{pipeline_id.name} does not support requested step(s): {labels}."
            )

        if StepId.PREPARE_ANALYSIS in requested:
            if requested[0] is not StepId.PREPARE_ANALYSIS:
                raise ValueError("PREPARE_ANALYSIS must be the first pipeline step.")
            normalized = requested
        else:
            normalized = (StepId.PREPARE_ANALYSIS, *requested)

        if StepId.REPORT_BUNDLE in normalized:
            if normalized[-1] is not StepId.REPORT_BUNDLE:
                raise ValueError("REPORT_BUNDLE must be the last pipeline step.")
        elif require_report:
            normalized = (*normalized, StepId.REPORT_BUNDLE)
        return normalized

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
        active_pipeline = self._active_pipeline()
        if active_pipeline is not None:
            active_label = self._section_label(active_pipeline)
            self._view.append_log(
                self._section_label(pipeline_id),
                f"{active_label} analysis is already running.",
                level="warning",
            )
            return
        if not self._view.ensure_pipeline_ready(pipeline_id, require_anova=require_anova):
            return
        try:
            normalized_step_ids = self._normalize_step_ids(
                pipeline_id,
                step_ids,
                require_report=bool(run_exports or run_summary),
            )
            steps = self._build_steps(pipeline_id, normalized_step_ids)
        except Exception as exc:  # noqa: BLE001
            self._view.append_log(
                self._section_label(pipeline_id),
                f"Unable to start analysis: {exc}",
                level="error",
            )
            return
        if not steps:
            self._view.append_log(
                self._section_label(pipeline_id),
                "No analysis steps were requested.",
                level="warning",
            )
            return

        state.current_step_index = 0
        state.steps = steps
        state.running = True
        state.failed = False
        state.cancelled = False
        state.cancellation_requested = False
        state.cancellation_generation = None
        state.cancel_event = threading.Event()
        state.results = {}
        state.prepared_payload = None
        state.exports_ran = False
        state.run_exports = run_exports
        state.run_summary = run_summary
        state.start_ts = time.perf_counter()
        state.run_generation += 1
        state.last_outcome = None
        for step in state.steps:
            if step.id in CANCELLABLE_STEPS:
                step.kwargs["cancel_check"] = state.cancel_event.is_set
        self._view.set_busy(True)
        self._view.on_pipeline_started(pipeline_id)
        self._run_next_step(pipeline_id)

    def _run_next_step(self, pipeline_id: PipelineId) -> None:
        state = self._states[pipeline_id]
        if not state.running or state.cancellation_requested:
            return
        if state.current_step_index >= len(state.steps):
            self._complete_pipeline(pipeline_id)
            return
        step = state.steps[state.current_step_index]
        if step.id is StepId.REPORT_BUNDLE:
            step.kwargs["prior_results"] = dict(state.results)
        section = self._section_label(pipeline_id)
        generation = state.run_generation
        self._view.append_log(
            section,
            format_step_event(
                pipeline_id,
                step.id,
                event="start",
                message=f"{step.name} started",
            ),
        )
        try:
            self._view.start_step_worker(
                pipeline_id,
                step,
                finished_cb=lambda pid, sid, payload: self._on_step_finished(
                    pid,
                    sid,
                    payload,
                    run_generation=generation,
                ),
                error_cb=lambda pid, sid, message: self._on_step_error(
                    pid,
                    sid,
                    message,
                    run_generation=generation,
                ),
                message_cb=lambda msg: self._on_step_message(
                    pipeline_id,
                    msg,
                    run_generation=generation,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_worker_start_error",
                extra={
                    "pipeline": pipeline_id.name,
                    "step": step.id.name,
                    "error": str(exc),
                },
            )
            self._on_step_error(
                pipeline_id,
                step.id,
                f"Unable to start {step.name}: {exc}",
                run_generation=generation,
            )

    def _on_step_message(
        self,
        pipeline_id: PipelineId,
        message: str,
        *,
        run_generation: int,
    ) -> None:
        """Ignore messages from cancelled, invalidated, or superseded workers."""

        state = self._states[pipeline_id]
        if (
            not state.running
            or state.cancellation_requested
            or run_generation != state.run_generation
        ):
            return
        self._view.append_log(self._section_label(pipeline_id), message)

    def _active_pipeline(self) -> PipelineId | None:
        return next(
            (
                pipeline_id
                for pipeline_id, state in self._states.items()
                if state.running
            ),
            None,
        )

    @staticmethod
    def _section_label(pipeline_id: PipelineId) -> str:
        return PIPELINE_LABELS[pipeline_id]

    def _on_step_finished(
        self,
        pipeline_id: PipelineId,
        step_id: StepId,
        payload: object,
        *,
        run_generation: int | None = None,
    ) -> None:
        state = self._states[pipeline_id]
        if not state.running:
            return
        if state.cancellation_requested:
            if self._is_cancellation_acknowledgement(state, run_generation):
                self._finish_cancelled(pipeline_id)
            return
        if run_generation is not None and run_generation != state.run_generation:
            return
        if state.current_step_index >= len(state.steps):
            self._on_step_error(
                pipeline_id,
                step_id,
                "Received completion with no pending step.",
                run_generation=run_generation,
            )
            return
        step = state.steps[state.current_step_index]
        if step.id is not step_id:
            self._on_step_error(
                pipeline_id,
                step_id,
                f"Received completion for {step_id.name} while {step.id.name} was pending.",
                run_generation=run_generation,
            )
            return
        status = self._payload_status(payload)
        if step_id is StepId.REPORT_BUNDLE:
            state.exports_ran = self._report_exports_ran(payload)
        if status == "blocked":
            blocked_message = self._payload_message(payload, "Analysis blocked.")
            if step_id is StepId.REPORT_BUNDLE:
                state.results[step_id] = self._result_mapping(payload)
                self._complete_after_reporting_failure(
                    pipeline_id,
                    blocked_message,
                )
                return
            self._view.append_log(
                self._section_label(pipeline_id),
                blocked_message,
                level="warning",
            )
            state.results[step_id] = self._result_mapping(payload)
            self._finalize_pipeline(
                pipeline_id,
                success=False,
                error_message=blocked_message,
                exports_ran=False,
                outcome="blocked",
            )
            return
        if status in {"failed", "error"}:
            self._on_step_error(
                pipeline_id,
                step_id,
                self._payload_message(payload, "Analysis step failed."),
                run_generation=run_generation,
            )
            return
        if status in {"cancelled", "canceled"}:
            self._finish_cancelled(pipeline_id)
            return

        try:
            step.handler(payload)
            state.results[step_id] = self._result_mapping(payload)
            if step_id is StepId.PREPARE_ANALYSIS:
                self._propagate_prepared_payload(state, payload)
            if step_id is StepId.RM_ANOVA and isinstance(payload, dict):
                self._propagate_interaction_gate(state, payload)
            run_report = payload.get("run_report") if isinstance(payload, dict) else None
            if isinstance(run_report, StatsRunReport):
                self._view.store_run_report(pipeline_id, run_report)
        except Exception as exc:  # noqa: BLE001
            logger.exception("stats_step_handler_error", extra={"step": step_id.name})
            self._on_step_error(
                pipeline_id,
                step_id,
                f"Step handler failed: {exc}",
                run_generation=run_generation,
            )
            return

        self._view.append_log(
            self._section_label(pipeline_id),
            format_step_event(
                pipeline_id,
                step.id,
                event="complete",
                message=f"{step.name} completed",
            ),
        )
        state.current_step_index += 1
        self._run_next_step(pipeline_id)

    @staticmethod
    def _payload_status(payload: object) -> str:
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("status", "")).strip().lower()

    @staticmethod
    def _is_cancellation_acknowledgement(
        state: SectionRunState,
        run_generation: int | None,
    ) -> bool:
        if run_generation is None:
            return True
        return run_generation in {
            state.run_generation,
            state.cancellation_generation,
        }

    @staticmethod
    def _report_exports_ran(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        return bool(payload.get("exported")) or bool(
            payload.get("numeric_exported")
        )

    @staticmethod
    def _payload_message(payload: object, default: str) -> str:
        if not isinstance(payload, dict):
            return default
        return str(payload.get("message") or payload.get("error") or default)

    @staticmethod
    def _result_mapping(payload: object) -> dict:
        return payload if isinstance(payload, dict) else {"result": payload}

    @staticmethod
    def _propagate_prepared_payload(
        state: SectionRunState,
        payload: object,
    ) -> None:
        """Reuse the preparation result for every pending native analysis step."""

        if not isinstance(payload, dict) or "prepared_payload" not in payload:
            raise ValueError(
                "Preparation step completed without a 'prepared_payload' result."
            )
        prepared_payload = payload["prepared_payload"]
        if prepared_payload is None:
            raise ValueError("Preparation step returned an empty prepared payload.")
        state.prepared_payload = prepared_payload
        for pending_step in state.steps[state.current_step_index + 1 :]:
            pending_step.kwargs["prepared_payload"] = prepared_payload

    @staticmethod
    def _propagate_interaction_gate(
        state: SectionRunState,
        payload: dict[str, object],
    ) -> None:
        """Pass the current RM-ANOVA interaction result to pending follow-ups."""

        pending = state.steps[state.current_step_index + 1 :]
        for pending_step in pending:
            if pending_step.id is not StepId.INTERACTION_POSTHOCS:
                continue
            if not bool(
                pending_step.kwargs.get("enforce_omnibus_gate", True)
            ):
                continue
            alpha = float(pending_step.kwargs.get("alpha", 0.05))
            gate = resolve_rm_anova_interaction_gate(
                payload.get("anova_df_results"),  # type: ignore[arg-type]
                alpha=alpha,
            )
            pending_step.kwargs.update(
                {
                    "followup_provenance": "omnibus_triggered",
                    "omnibus_p_value": gate.p_value,
                    "omnibus_significant": gate.significant,
                    "omnibus_gate_status": gate.status,
                }
            )

    def _on_step_error(
        self,
        pipeline_id: PipelineId,
        step_id: StepId,
        error_message: str,
        *,
        run_generation: int | None = None,
    ) -> None:
        state = self._states[pipeline_id]
        if not state.running:
            return
        if state.cancellation_requested:
            if self._is_cancellation_acknowledgement(state, run_generation):
                self._finish_cancelled(pipeline_id)
            return
        if run_generation is not None and run_generation != state.run_generation:
            return
        if state.current_step_index >= len(state.steps):
            return
        expected_step = state.steps[state.current_step_index]
        if expected_step.id is not step_id:
            self._view.append_log(
                self._section_label(pipeline_id),
                (
                    f"Ignoring stale error from {step_id.name}; "
                    f"{expected_step.id.name} is the active step."
                ),
                level="warning",
            )
            return
        if step_id is StepId.REPORT_BUNDLE:
            self._complete_after_reporting_failure(pipeline_id, error_message)
            return
        state.failed = True
        self._view.append_log(
            self._section_label(pipeline_id),
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
            outcome="failed",
        )

    def _complete_after_reporting_failure(
        self,
        pipeline_id: PipelineId,
        report_error: str,
    ) -> None:
        """Preserve export truth reported by the failed report worker."""

        state = self._states[pipeline_id]
        if not state.running:
            return
        message = f"Report bundle failed: {report_error}"
        if state.exports_ran:
            message = f"{message} Completed numeric results were preserved."
        elif state.run_exports:
            message = (
                f"{message} The report worker did not confirm a completed "
                "numeric export."
            )
        self._view.append_log(
            self._section_label(pipeline_id),
            message,
            level="error",
        )
        self._finalize_pipeline(
            pipeline_id,
            success=False,
            error_message=message,
            exports_ran=state.exports_ran,
            outcome="reporting_failed",
        )

    def _complete_pipeline(self, pipeline_id: PipelineId) -> None:
        state = self._states[pipeline_id]
        if not state.running:
            return
        if state.cancellation_requested:
            self._finish_cancelled(pipeline_id)
            return
        elapsed = time.perf_counter() - state.start_ts if state.start_ts else 0.0
        exports_ran = state.exports_ran
        success = True
        error_message: Optional[str] = None
        try:
            if state.run_exports and not exports_ran:
                success = False
                error_message = (
                    "The report worker did not confirm the requested export."
                )
                self._view.append_log(
                    self._section_label(pipeline_id),
                    error_message,
                    level="error",
                )
            if success and state.run_summary:
                self._view.build_and_render_summary(pipeline_id)
            if success:
                self._view.append_log(
                    self._section_label(pipeline_id),
                    (
                        f"{PIPELINE_COMPLETION_LABELS[pipeline_id]} Analysis "
                        f"finished in {elapsed:.1f} s"
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("stats_pipeline_complete_error", extra={"error": str(exc)})
            success = False
            error_message = error_message or f"Error during finalization: {exc}"
            self._view.append_log(
                self._section_label(pipeline_id),
                error_message,
                level="error",
            )
        finally:
            self._finalize_pipeline(
                pipeline_id,
                success=success,
                error_message=error_message,
                exports_ran=exports_ran,
                outcome="success" if success else "failed",
            )

    def cancel_pipeline(self, pipeline_id: PipelineId | None = None) -> bool:
        """Request cancellation and wait for the active worker to acknowledge it."""

        selected_pipeline = pipeline_id or self._active_pipeline()
        if selected_pipeline is None:
            return False
        state = self._states[selected_pipeline]
        if not state.running:
            return False
        if state.cancellation_requested:
            return True

        state.cancellation_requested = True
        state.cancellation_generation = state.run_generation
        if state.cancel_event is not None:
            state.cancel_event.set()
        self._view.append_log(
            self._section_label(selected_pipeline),
            f"{PIPELINE_COMPLETION_LABELS[selected_pipeline]} Analysis cancellation requested.",
            level="warning",
        )
        self._signal_worker_cancellation(selected_pipeline)
        return True

    def invalidate_context(self) -> bool:
        """Invalidate all callbacks when the project/data context is replaced."""

        active_pipeline = self._active_pipeline()
        for pipeline_id, state in self._states.items():
            if state.running:
                if not state.cancellation_requested:
                    state.cancellation_requested = True
                    state.cancellation_generation = state.run_generation
                    if state.cancel_event is not None:
                        state.cancel_event.set()
                    self._view.append_log(
                        self._section_label(pipeline_id),
                        (
                            f"{PIPELINE_COMPLETION_LABELS[pipeline_id]} Analysis "
                            "cancelled because the project context changed."
                        ),
                        level="warning",
                    )
                    self._signal_worker_cancellation(pipeline_id)
                state.run_generation += 1
            else:
                state.run_generation += 1
        return active_pipeline is not None

    def _signal_worker_cancellation(self, pipeline_id: PipelineId) -> None:
        cancel_worker = getattr(self._view, "cancel_active_worker", None)
        if not callable(cancel_worker):
            return
        try:
            cancel_worker(pipeline_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_cancel_worker_error",
                extra={
                    "pipeline": pipeline_id.name,
                    "error": str(exc),
                },
            )
            self._view.append_log(
                self._section_label(pipeline_id),
                f"Worker cancellation signal failed: {exc}",
                level="warning",
            )

    def _finish_cancelled(self, pipeline_id: PipelineId) -> None:
        state = self._states[pipeline_id]
        if not state.running:
            return
        state.cancelled = True
        self._view.append_log(
            self._section_label(pipeline_id),
            f"{PIPELINE_COMPLETION_LABELS[pipeline_id]} Analysis cancelled.",
            level="warning",
        )
        self._finalize_pipeline(
            pipeline_id,
            success=False,
            error_message=None,
            exports_ran=False,
            outcome="cancelled",
        )

    def _finalize_pipeline(
        self,
        pipeline_id: PipelineId,
        *,
        success: bool,
        error_message: Optional[str],
        exports_ran: bool = False,
        outcome: str | None = None,
    ) -> None:
        state = self._states[pipeline_id]
        was_cancelled = outcome == "cancelled"
        state.running = False
        state.last_outcome = outcome
        state.failed = outcome in {"failed", "reporting_failed"}
        state.cancelled = was_cancelled
        state.cancellation_requested = False
        state.cancellation_generation = None
        state.cancel_event = None
        state.current_step_index = 0
        state.steps = ()
        state.results = {}
        state.prepared_payload = None
        state.exports_ran = False
        state.run_exports = True
        state.run_summary = True
        state.start_ts = 0.0
        self._view.set_busy(False)
        try:
            self._notify_analysis_finished(
                pipeline_id,
                success=success,
                error_message=error_message,
                exports_ran=exports_ran,
                cancelled=was_cancelled,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "stats_finalize_view_error",
                extra={"pipeline": pipeline_id.name, "outcome": outcome or "unknown"},
            )

    def _notify_analysis_finished(
        self,
        pipeline_id: PipelineId,
        *,
        success: bool,
        error_message: Optional[str],
        exports_ran: bool,
        cancelled: bool,
    ) -> None:
        """Notify new views of cancellation while retaining the legacy callback."""

        callback = self._view.on_analysis_finished
        try:
            callback(
                pipeline_id,
                success=success,
                error_message=error_message,
                exports_ran=exports_ran,
                cancelled=cancelled,
            )
        except TypeError as exc:
            if "cancelled" not in str(exc):
                raise
            callback(
                pipeline_id,
                success=success,
                error_message=error_message,
                exports_ran=exports_ran,
            )


__all__ = [
    "MULTI_PIPELINE_STEPS",
    "PIPELINE_COMPLETION_LABELS",
    "PIPELINE_LABELS",
    "SINGLE_PIPELINE_STEPS",
    "STEP_LABELS",
    "WORKER_FN_BY_STEP",
    "StatsController",
    "SectionRunState",
    "StatsViewProtocol",
]
