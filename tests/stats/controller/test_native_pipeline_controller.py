from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from Tools.Stats.common.stats_core import PipelineId, StepId
from Tools.Stats.controller.stats_controller import (
    MULTI_PIPELINE_STEPS,
    SINGLE_PIPELINE_STEPS,
    StatsController,
)


class FakeView:
    def __init__(
        self,
        payloads: dict[StepId, object] | None = None,
        *,
        synchronous: bool = True,
        start_exception_step: StepId | None = None,
    ) -> None:
        self.payloads = payloads or {}
        self.synchronous = synchronous
        self.start_exception_step = start_exception_step
        self.logs: list[tuple[str, str, str]] = []
        self.busy_states: list[bool] = []
        self.started: list[PipelineId] = []
        self.finished: list[dict[str, object]] = []
        self.worker_calls: list[tuple[PipelineId, StepId, dict[str, object]]] = []
        self.handlers: list[StepId] = []
        self.pending_callbacks: list[
            tuple[
                PipelineId,
                StepId,
                Callable[[PipelineId, StepId, object], None],
                Callable[[PipelineId, StepId, str], None],
            ]
        ] = []
        self.pending_messages: list[Callable[[str], None] | None] = []
        self.ready_calls: list[tuple[PipelineId, bool]] = []
        self.cancel_calls: list[PipelineId] = []
        self.export_calls: list[PipelineId] = []
        self.summary_calls: list[PipelineId] = []

    def append_log(self, section: str, message: str, level: str = "info") -> None:
        self.logs.append((section, message, level))

    def set_busy(self, is_busy: bool) -> None:
        self.busy_states.append(is_busy)

    def start_step_worker(
        self,
        pipeline_id: PipelineId,
        step: Any,
        *,
        finished_cb: Callable[[PipelineId, StepId, object], None],
        error_cb: Callable[[PipelineId, StepId, str], None],
        message_cb: Callable[[str], None] | None = None,
    ) -> None:
        if step.id is self.start_exception_step:
            raise RuntimeError("worker submission failed")
        self.worker_calls.append((pipeline_id, step.id, dict(step.kwargs)))
        default_payload: dict[str, object] = {
            "status": "ok",
            "step": step.id.name,
        }
        if step.id is StepId.REPORT_BUNDLE:
            default_payload.update(
                {
                    "exported": True,
                    "numeric_exported": True,
                }
            )
        if self.synchronous:
            finished_cb(
                pipeline_id,
                step.id,
                self.payloads.get(step.id, default_payload),
            )
        else:
            self.pending_callbacks.append(
                (pipeline_id, step.id, finished_cb, error_cb)
            )
            self.pending_messages.append(message_cb)

    def on_pipeline_started(self, pipeline_id: PipelineId) -> None:
        self.started.append(pipeline_id)

    def on_analysis_finished(
        self,
        pipeline_id: PipelineId,
        success: bool,
        error_message: str | None,
        *,
        exports_ran: bool,
        cancelled: bool = False,
    ) -> None:
        self.finished.append(
            {
                "pipeline_id": pipeline_id,
                "success": success,
                "error_message": error_message,
                "exports_ran": exports_ran,
                "cancelled": cancelled,
            }
        )

    def ensure_pipeline_ready(
        self,
        pipeline_id: PipelineId,
        *,
        require_anova: bool = False,
    ) -> bool:
        self.ready_calls.append((pipeline_id, require_anova))
        return True

    def export_pipeline_results(self, pipeline_id: PipelineId) -> bool:
        self.export_calls.append(pipeline_id)
        return True

    def build_and_render_summary(self, pipeline_id: PipelineId) -> None:
        self.summary_calls.append(pipeline_id)

    def get_step_config(
        self,
        pipeline_id: PipelineId,
        step_id: StepId,
    ) -> tuple[dict[str, object], Callable[[dict], None]]:
        del pipeline_id

        def handler(_payload: dict) -> None:
            self.handlers.append(step_id)

        return {"configured_step": step_id.name}, handler

    def store_run_report(self, pipeline_id: PipelineId, report: object) -> None:
        del pipeline_id, report

    def cancel_active_worker(self, pipeline_id: PipelineId) -> None:
        self.cancel_calls.append(pipeline_id)


def _multigroup_payloads(prepared_payload: object) -> dict[StepId, object]:
    return {
        StepId.PREPARE_ANALYSIS: {
            "status": "ok",
            "prepared_payload": prepared_payload,
        },
        StepId.BASELINE_VS_ZERO: {
            "status": "ok",
            "responses": "grouped-response-result",
        },
        StepId.MULTIGROUP_MODEL: {"status": "ok", "model": "model-result"},
        StepId.SENSITIVITIES: {"status": "ok", "sensitivity": "robust-result"},
        StepId.REPORT_BUNDLE: {
            "status": "ok",
            "report": "bundle",
            "exported": True,
            "numeric_exported": True,
        },
    }


def test_multigroup_pipeline_order_and_prepared_payload_reuse() -> None:
    prepared = object()
    view = FakeView(_multigroup_payloads(prepared))
    controller = StatsController(view)

    controller.run_multigroup_analysis()

    assert [step_id for _pipeline, step_id, _kwargs in view.worker_calls] == list(
        MULTI_PIPELINE_STEPS
    )
    assert all(
        callable(kwargs["cancel_check"])
        for _pipeline, _step_id, kwargs in view.worker_calls
    )
    for _pipeline, step_id, kwargs in view.worker_calls[1:]:
        assert kwargs["prepared_payload"] is prepared, step_id

    report_kwargs = view.worker_calls[-1][2]
    prior_results = report_kwargs["prior_results"]
    assert list(prior_results) == list(MULTI_PIPELINE_STEPS[:-1])
    assert prior_results[StepId.MULTIGROUP_MODEL]["model"] == "model-result"
    assert view.handlers == list(MULTI_PIPELINE_STEPS)
    assert view.export_calls == []
    assert view.summary_calls == [PipelineId.MULTI]
    assert view.finished == [
        {
            "pipeline_id": PipelineId.MULTI,
            "success": True,
            "error_message": None,
            "exports_ran": True,
            "cancelled": False,
        }
    ]
    assert not controller.is_running()
    assert controller._states[PipelineId.MULTI].results == {}
    assert controller._states[PipelineId.MULTI].prepared_payload is None
    assert {section for section, _message, _level in view.logs} == {"Multi-group"}


def test_standard_single_pipeline_runs_positive_response_before_lmm() -> None:
    prepared = object()
    view = FakeView(
        {
            StepId.PREPARE_ANALYSIS: {
                "status": "ok",
                "prepared_payload": prepared,
            }
        }
    )
    controller = StatsController(view)

    controller.run_single_group_analysis()

    assert [step_id for _pipeline, step_id, _kwargs in view.worker_calls] == [
        StepId.PREPARE_ANALYSIS,
        StepId.BASELINE_VS_ZERO,
        StepId.MIXED_MODEL,
        StepId.SENSITIVITIES,
        StepId.REPORT_BUNDLE,
    ]
    assert list(SINGLE_PIPELINE_STEPS) == [
        StepId.PREPARE_ANALYSIS,
        StepId.BASELINE_VS_ZERO,
        StepId.MIXED_MODEL,
        StepId.SENSITIVITIES,
        StepId.REPORT_BUNDLE,
    ]
    assert all(
        kwargs["prepared_payload"] is prepared
        for _pipeline, _step_id, kwargs in view.worker_calls[1:]
    )
    assert view.export_calls == []
    assert view.summary_calls == [PipelineId.SINGLE]
    assert view.finished[-1]["success"] is True
    assert view.finished[-1]["cancelled"] is False
    assert {section for section, _message, _level in view.logs} == {"Single"}


def test_manual_followups_preserve_provenance_when_omnibus_gate_is_disabled() -> None:
    class ManualFollowupView(FakeView):
        def get_step_config(
            self,
            pipeline_id: PipelineId,
            step_id: StepId,
        ) -> tuple[dict[str, object], Callable[[dict], None]]:
            kwargs, handler = super().get_step_config(pipeline_id, step_id)
            if step_id is StepId.INTERACTION_POSTHOCS:
                kwargs.update(
                    {
                        "followup_provenance": "exploratory_manual",
                        "enforce_omnibus_gate": False,
                    }
                )
            return kwargs, handler

    prepared = object()
    view = ManualFollowupView(
        {
            StepId.PREPARE_ANALYSIS: {
                "status": "ok",
                "prepared_payload": prepared,
            },
            StepId.RM_ANOVA: {
                "status": "ok",
                "anova_df_results": None,
            },
        }
    )
    controller = StatsController(view)

    controller.run_single_group_analysis(
        step_ids=(
            StepId.RM_ANOVA,
            StepId.INTERACTION_POSTHOCS,
        ),
        run_exports=False,
        run_summary=False,
    )

    posthoc_kwargs = next(
        kwargs
        for _pipeline, step_id, kwargs in view.worker_calls
        if step_id is StepId.INTERACTION_POSTHOCS
    )
    assert posthoc_kwargs["followup_provenance"] == "exploratory_manual"
    assert posthoc_kwargs["enforce_omnibus_gate"] is False
    assert "omnibus_p_value" not in posthoc_kwargs
    assert "omnibus_significant" not in posthoc_kwargs


def test_explicit_single_queue_can_omit_all_sensitivity_work() -> None:
    prepared = object()
    view = FakeView(
        {
            StepId.PREPARE_ANALYSIS: {
                "status": "ok",
                "prepared_payload": prepared,
            }
        }
    )
    controller = StatsController(view)

    controller.run_single_group_analysis(
        step_ids=(
            StepId.PREPARE_ANALYSIS,
            StepId.RM_ANOVA,
            StepId.MIXED_MODEL,
            StepId.INTERACTION_POSTHOCS,
            StepId.BASELINE_VS_ZERO,
            StepId.REPORT_BUNDLE,
        ),
    )

    assert StepId.SENSITIVITIES not in [
        step_id for _pipeline, step_id, _kwargs in view.worker_calls
    ]
    assert view.finished[-1]["success"] is True


def test_single_step_only_run_still_prepares_once() -> None:
    prepared = object()
    view = FakeView(
        {
            StepId.PREPARE_ANALYSIS: {
                "status": "ok",
                "prepared_payload": prepared,
            }
        }
    )
    controller = StatsController(view)

    controller.run_single_group_analysis(
        step_ids=(StepId.MIXED_MODEL,),
        run_exports=False,
        run_summary=False,
    )

    assert [step_id for _pipeline, step_id, _kwargs in view.worker_calls] == [
        StepId.PREPARE_ANALYSIS,
        StepId.MIXED_MODEL,
    ]
    assert view.worker_calls[-1][2]["prepared_payload"] is prepared


def test_cancel_pipeline_stops_finalization_and_ignores_stale_completion() -> None:
    view = FakeView(
        _multigroup_payloads(object()),
        synchronous=False,
    )
    controller = StatsController(view)
    controller.run_multigroup_analysis()
    stale_finished = view.pending_callbacks[0][2]
    cancel_check = view.worker_calls[0][2]["cancel_check"]
    assert callable(cancel_check)
    assert cancel_check() is False

    assert controller.cancel_pipeline(PipelineId.MULTI) is True
    assert view.cancel_calls == [PipelineId.MULTI]
    assert cancel_check() is True
    assert view.export_calls == []
    assert view.summary_calls == []
    assert view.finished == []
    assert view.busy_states[-1] is True
    assert controller.is_running(PipelineId.MULTI)

    log_count = len(view.logs)
    message_cb = view.pending_messages[0]
    assert message_cb is not None
    message_cb("stale progress detail")
    assert len(view.logs) == log_count

    stale_finished(
        PipelineId.MULTI,
        StepId.PREPARE_ANALYSIS,
        {"status": "cancelled"},
    )
    assert view.finished[-1] == {
        "pipeline_id": PipelineId.MULTI,
        "success": False,
        "error_message": None,
        "exports_ran": False,
        "cancelled": True,
    }
    assert view.busy_states[-1] is False
    assert not controller.is_running()

    controller.run_multigroup_analysis()
    assert controller.is_running(PipelineId.MULTI)
    stale_finished(
        PipelineId.MULTI,
        StepId.PREPARE_ANALYSIS,
        {
            "status": "ok",
            "prepared_payload": object(),
        },
    )
    assert controller.is_running(PipelineId.MULTI)
    assert len(view.finished) == 1
    assert controller.cancel_pipeline() is True
    current_finished = view.pending_callbacks[-1][2]
    current_finished(
        PipelineId.MULTI,
        StepId.PREPARE_ANALYSIS,
        {"status": "cancelled"},
    )
    assert not controller.is_running()


def test_blocked_failed_and_cancelled_payloads_have_distinct_outcomes() -> None:
    cases = (
        (
            {"status": "blocked", "message": "Design blocked."},
            "warning",
            False,
            "Design blocked.",
            "blocked",
        ),
        (
            {"status": "failed", "message": "Model failed."},
            "error",
            False,
            "Model failed.",
            "failed",
        ),
        (
            {"status": "cancelled", "message": "Stopped."},
            "warning",
            True,
            None,
            "cancelled",
        ),
    )

    for (
        payload,
        expected_level,
        expected_cancelled,
        expected_error,
        expected_outcome,
    ) in cases:
        view = FakeView({StepId.PREPARE_ANALYSIS: payload})
        controller = StatsController(view)

        controller.run_multigroup_analysis()

        assert view.finished[-1]["success"] is False
        assert view.finished[-1]["cancelled"] is expected_cancelled
        assert view.finished[-1]["error_message"] == expected_error
        assert view.export_calls == []
        assert view.summary_calls == []
        assert any(level == expected_level for _section, _message, level in view.logs)
        assert (
            controller._states[PipelineId.MULTI].last_outcome
            == expected_outcome
        )


def test_report_failure_preserves_requested_numeric_export() -> None:
    payloads = _multigroup_payloads(object())
    payloads[StepId.REPORT_BUNDLE] = {
        "status": "failed",
        "message": "Narrative assembly failed.",
        "numeric_exported": True,
    }
    view = FakeView(payloads)
    controller = StatsController(view)

    controller.run_multigroup_analysis()

    assert view.handlers == list(MULTI_PIPELINE_STEPS[:-1])
    assert view.export_calls == []
    assert view.summary_calls == []
    assert view.finished[-1] == {
        "pipeline_id": PipelineId.MULTI,
        "success": False,
        "error_message": (
            "Report bundle failed: Narrative assembly failed. "
            "Completed numeric results were preserved."
        ),
        "exports_ran": True,
        "cancelled": False,
    }


@pytest.mark.parametrize(
    "step_ids, expected_message",
    [
        (
            (
                StepId.PREPARE_ANALYSIS,
                StepId.MULTIGROUP_MODEL,
                StepId.MULTIGROUP_MODEL,
            ),
            "Duplicate analysis steps",
        ),
        (
            (StepId.MULTIGROUP_MODEL, StepId.PREPARE_ANALYSIS),
            "PREPARE_ANALYSIS must be the first",
        ),
        (
            (StepId.REPORT_BUNDLE, StepId.MULTIGROUP_MODEL),
            "REPORT_BUNDLE must be the last",
        ),
        (
            (StepId.RM_ANOVA,),
            "MULTI does not support",
        ),
    ],
)
def test_invalid_multigroup_step_queues_are_rejected(
    step_ids: tuple[StepId, ...],
    expected_message: str,
) -> None:
    view = FakeView()
    controller = StatsController(view)

    controller.run_multigroup_analysis(step_ids=step_ids)

    assert view.worker_calls == []
    assert not controller.is_running()
    assert any(expected_message in message for _section, message, _level in view.logs)


def test_custom_exporting_run_appends_report_bundle_last() -> None:
    prepared = object()
    view = FakeView(
        {
            StepId.PREPARE_ANALYSIS: {
                "status": "ok",
                "prepared_payload": prepared,
            }
        }
    )
    controller = StatsController(view)

    controller.run_multigroup_analysis(
        step_ids=(StepId.MULTIGROUP_MODEL,),
        run_exports=True,
        run_summary=False,
    )

    assert [step_id for _pipeline, step_id, _kwargs in view.worker_calls] == [
        StepId.PREPARE_ANALYSIS,
        StepId.MULTIGROUP_MODEL,
        StepId.REPORT_BUNDLE,
    ]
    assert view.finished[-1]["success"] is True
    assert view.finished[-1]["exports_ran"] is True
    assert view.export_calls == []


def test_context_invalidation_waits_for_old_worker_then_rejects_its_payload() -> None:
    view = FakeView(synchronous=False)
    controller = StatsController(view)
    controller.run_multigroup_analysis()
    old_finished = view.pending_callbacks[0][2]
    old_message = view.pending_messages[0]

    assert controller.invalidate_context() is True
    assert controller.is_running(PipelineId.MULTI)
    assert view.busy_states[-1] is True
    assert view.cancel_calls == [PipelineId.MULTI]

    log_count = len(view.logs)
    assert old_message is not None
    old_message("message from old project")
    assert len(view.logs) == log_count

    old_finished(
        PipelineId.MULTI,
        StepId.PREPARE_ANALYSIS,
        {
            "status": "ok",
            "prepared_payload": object(),
        },
    )
    assert not controller.is_running()
    assert view.handlers == []
    assert view.finished[-1]["cancelled"] is True
    assert view.export_calls == []
    assert view.summary_calls == []


def test_stale_same_run_error_does_not_fail_the_active_step() -> None:
    view = FakeView(synchronous=False)
    controller = StatsController(view)
    controller.run_multigroup_analysis()
    prepare_finished = view.pending_callbacks[0][2]
    stale_error = view.pending_callbacks[0][3]
    prepare_finished(
        PipelineId.MULTI,
        StepId.PREPARE_ANALYSIS,
        {
            "status": "ok",
            "prepared_payload": object(),
        },
    )

    stale_error(
        PipelineId.MULTI,
        StepId.PREPARE_ANALYSIS,
        "late preparation error",
    )

    assert controller.is_running(PipelineId.MULTI)
    assert view.finished == []
    assert any(
        "Ignoring stale error" in message and level == "warning"
        for _section, message, level in view.logs
    )
    assert controller.cancel_pipeline() is True
    active_finished = view.pending_callbacks[-1][2]
    active_finished(
        PipelineId.MULTI,
        StepId.MULTIGROUP_MODEL,
        {"status": "cancelled"},
    )


def test_synchronous_worker_start_failure_releases_busy_state() -> None:
    view = FakeView(start_exception_step=StepId.PREPARE_ANALYSIS)
    controller = StatsController(view)

    controller.run_multigroup_analysis()

    assert not controller.is_running()
    assert view.busy_states == [True, False]
    assert view.finished[-1]["success"] is False
    assert "Unable to start Prepare Analysis" in str(
        view.finished[-1]["error_message"]
    )


def test_requested_export_requires_report_worker_confirmation() -> None:
    payloads = _multigroup_payloads(object())
    payloads[StepId.REPORT_BUNDLE] = {
        "status": "ok",
        "exported": False,
        "numeric_exported": False,
    }
    view = FakeView(payloads)
    controller = StatsController(view)

    controller.run_multigroup_analysis()

    assert view.export_calls == []
    assert view.finished[-1]["success"] is False
    assert view.finished[-1]["exports_ran"] is False
    assert "did not confirm" in str(view.finished[-1]["error_message"])


def test_only_one_pipeline_can_run_at_a_time() -> None:
    view = FakeView(synchronous=False)
    controller = StatsController(view)

    controller.run_single_group_analysis()
    controller.run_multigroup_analysis()

    assert view.started == [PipelineId.SINGLE]
    assert view.ready_calls == [(PipelineId.SINGLE, False)]
    assert any(
        section == "Multi-group"
        and "Single analysis is already running" in message
        and level == "warning"
        for section, message, level in view.logs
    )
    assert controller.cancel_pipeline() is True
    pending_finished = view.pending_callbacks[0][2]
    pending_finished(
        PipelineId.SINGLE,
        StepId.PREPARE_ANALYSIS,
        {"status": "cancelled"},
    )


class LegacyFinishedView(FakeView):
    def on_analysis_finished(  # type: ignore[override]
        self,
        pipeline_id: PipelineId,
        success: bool,
        error_message: str | None,
        *,
        exports_ran: bool,
    ) -> None:
        self.finished.append(
            {
                "pipeline_id": pipeline_id,
                "success": success,
                "error_message": error_message,
                "exports_ran": exports_ran,
            }
        )


def test_legacy_finished_callback_remains_supported() -> None:
    view = LegacyFinishedView(synchronous=False)
    controller = StatsController(view)
    controller.run_multigroup_analysis()

    assert controller.cancel_pipeline() is True
    pending_finished = view.pending_callbacks[0][2]
    pending_finished(
        PipelineId.MULTI,
        StepId.PREPARE_ANALYSIS,
        {"status": "cancelled"},
    )
    assert view.finished == [
        {
            "pipeline_id": PipelineId.MULTI,
            "success": False,
            "error_message": None,
            "exports_ran": False,
        }
    ]
