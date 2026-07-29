from __future__ import annotations

import pytest

from Tools.Stats.analysis.inference_contracts import (
    Alternative,
    AnalysisProfile,
    CorrectionMethod,
    FollowupProvenance,
    HarmonicProvenance,
)
from Tools.Stats.analysis.prepared_analysis import AnalysisMode
from Tools.Stats.common.stats_core import PipelineId, StepId
from Tools.Stats.ui.inference_view_model import (
    NativeInferenceOptions,
    coerce_analysis_mode,
    infer_harmonic_provenance,
    overall_progress,
    phase_label,
    pipeline_steps_for_options,
)


def test_native_options_build_one_shared_run_spec_and_sensitivity_config() -> None:
    options = NativeInferenceOptions(
        mode=AnalysisMode.MULTI,
        profile=AnalysisProfile.CONFIRMATORY,
        correction=CorrectionMethod.HOLM,
        alternative=Alternative.TWO_SIDED,
        harmonic_provenance=HarmonicProvenance.INDEPENDENTLY_SELECTED,
        alpha=0.05,
        selected_group_pair=("anxious", "non_anxious"),
        strict_omnibus_family=True,
        n_resamples=2_000,
    )

    run_spec = options.build_run_spec()

    assert run_spec.profile is AnalysisProfile.CONFIRMATORY
    assert run_spec.response_alternative is Alternative.TWO_SIDED
    assert run_spec.followup_provenance is FollowupProvenance.OMNIBUS_TRIGGERED
    assert {family.family_id for family in run_spec.families} == {
        "response_core_cells",
        "group_core_cells",
        "planned_contrasts",
    }
    assert all(
        family.method is CorrectionMethod.HOLM for family in run_spec.families
    )
    assert options.sensitivity_config() == {
        "run_robust": True,
        "run_resampling": True,
        "run_stability": True,
        "n_resamples": 2_000,
        "seed": 20_250_521,
        "selection_nesting_attested": False,
    }


def test_mode_and_harmonic_provenance_follow_explicit_contracts() -> None:
    assert (
        coerce_analysis_mode("", project_is_multigroup=True)
        is AnalysisMode.MULTI
    )
    assert (
        coerce_analysis_mode("single", project_is_multigroup=True)
        is AnalysisMode.SINGLE
    )
    assert (
        infer_harmonic_provenance(
            independently_selected=False,
            same_sample_adaptive=True,
        )
        is HarmonicProvenance.SAME_SAMPLE_ADAPTIVE
    )
    assert (
        infer_harmonic_provenance(
            independently_selected=True,
            same_sample_adaptive=True,
        )
        is HarmonicProvenance.SAME_SAMPLE_ADAPTIVE
    )


def test_single_mode_rejects_group_pair_and_invalid_scope() -> None:
    common = {
        "mode": AnalysisMode.SINGLE,
        "profile": AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        "correction": CorrectionMethod.HOLM,
        "alternative": Alternative.TWO_SIDED,
        "harmonic_provenance": HarmonicProvenance.USER_FIXED_UNVERIFIED,
        "alpha": 0.05,
    }

    with pytest.raises(ValueError, match="only valid in multi-group"):
        NativeInferenceOptions(
            **common,
            selected_group_pair=("a", "b"),
        )
    with pytest.raises(ValueError, match="complete-core"):
        NativeInferenceOptions(
            **common,
            analysis_scope="available_case",
        )


def test_pipeline_progress_maps_each_step_into_the_full_run() -> None:
    assert overall_progress(
        PipelineId.MULTI,
        StepId.PREPARE_ANALYSIS,
        0,
    ) == 0
    assert overall_progress(
        PipelineId.MULTI,
        StepId.PREPARE_ANALYSIS,
        100,
    ) == 20
    assert overall_progress(
        PipelineId.MULTI,
        StepId.REPORT_BUNDLE,
        100,
    ) == 100
    assert "condition" in phase_label(
        StepId.GROUP_CELL_COMPARISONS
    ).casefold()


def test_single_queue_omits_sensitivities_only_when_all_are_disabled() -> None:
    common = {
        "mode": AnalysisMode.SINGLE,
        "profile": AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        "correction": CorrectionMethod.HOLM,
        "alternative": Alternative.TWO_SIDED,
        "harmonic_provenance": HarmonicProvenance.USER_FIXED_UNVERIFIED,
        "alpha": 0.05,
    }
    enabled = NativeInferenceOptions(**common)
    disabled = NativeInferenceOptions(
        **common,
        run_robust=False,
        run_resampling=False,
        run_stability=False,
    )

    assert StepId.SENSITIVITIES in pipeline_steps_for_options(enabled)
    assert StepId.SENSITIVITIES not in pipeline_steps_for_options(disabled)
    assert pipeline_steps_for_options(disabled)[0] is StepId.PREPARE_ANALYSIS
    assert pipeline_steps_for_options(disabled)[-1] is StepId.REPORT_BUNDLE
