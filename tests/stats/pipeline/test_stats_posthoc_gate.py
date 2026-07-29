from __future__ import annotations

import pandas as pd

from Tools.Stats.common.stats_core import PipelineId, PipelineStep, StepId
from Tools.Stats.controller.stats_controller import SectionRunState, StatsController


def _step(step_id: StepId, *, alpha: float = 0.05) -> PipelineStep:
    return PipelineStep(
        id=step_id,
        name=step_id.name,
        worker_fn=lambda *_args, **_kwargs: None,
        kwargs={"alpha": alpha} if step_id is StepId.INTERACTION_POSTHOCS else {},
        handler=lambda _payload: None,
    )


def test_current_rm_interaction_gate_is_propagated_to_pending_posthocs() -> None:
    rm_step = _step(StepId.RM_ANOVA)
    lmm_step = _step(StepId.MIXED_MODEL)
    posthoc_step = _step(StepId.INTERACTION_POSTHOCS)
    state = SectionRunState(
        pipeline_id=PipelineId.SINGLE,
        current_step_index=0,
        steps=(rm_step, lmm_step, posthoc_step),
        running=True,
    )
    table = pd.DataFrame(
        {
            "Effect": ["condition", "roi", "condition * roi"],
            "p_reported": [0.4, 0.2, 0.013],
            "reportable": [True, True, True],
            "inference_status": ["ok", "ok", "ok"],
        }
    )

    StatsController._propagate_interaction_gate(
        state,
        {"anova_df_results": table},
    )

    assert posthoc_step.kwargs["followup_provenance"] == "omnibus_triggered"
    assert posthoc_step.kwargs["omnibus_p_value"] == 0.013
    assert posthoc_step.kwargs["omnibus_significant"] is True
    assert posthoc_step.kwargs["omnibus_gate_status"] == "omnibus_reportable"


def test_blocked_rm_interaction_never_falls_back_to_raw_p() -> None:
    posthoc_step = _step(StepId.INTERACTION_POSTHOCS)
    state = SectionRunState(
        pipeline_id=PipelineId.SINGLE,
        current_step_index=0,
        steps=(_step(StepId.RM_ANOVA), posthoc_step),
        running=True,
    )
    table = pd.DataFrame(
        {
            "Effect": ["condition * roi"],
            "Pr > F": [0.001],
            "p_reported": [float("nan")],
            "reportable": [False],
            "inference_status": ["blocked_primary_correction_unavailable"],
        }
    )

    StatsController._propagate_interaction_gate(
        state,
        {"anova_df_results": table},
    )

    assert posthoc_step.kwargs["omnibus_p_value"] is None
    assert posthoc_step.kwargs["omnibus_significant"] is None
    assert (
        posthoc_step.kwargs["omnibus_gate_status"]
        == "blocked_primary_correction_unavailable"
    )
