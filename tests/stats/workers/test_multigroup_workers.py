from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis.dv_policies import FIXED_PREDEFINED_POLICY_NAME
from Tools.Stats.analysis.dv_policies import GROUP_SIGNIFICANT_POLICY_NAME
from Tools.Stats.analysis.inference_contracts import (
    AnalysisProfile,
    AnalysisRunSpec,
    CorrectionMethod,
    FamilySpec,
    FollowupProvenance,
    HarmonicProvenance,
)
from Tools.Stats.analysis.prepared_analysis import prepare_analysis_payload
from Tools.Stats.qc.stats_qc_exclusion import (
    QcExclusionReport,
    QcExclusionSummary,
)
from Tools.Stats.workers import multigroup_workers as workers


def _run_spec(
    *,
    strict_omnibus: bool = False,
    followup_provenance: FollowupProvenance = (
        FollowupProvenance.OMNIBUS_TRIGGERED
    ),
) -> AnalysisRunSpec:
    families = [
        FamilySpec(
            family_id="planned_contrasts",
            family_label="LMM-derived factorial follow-up contrasts",
            method=CorrectionMethod.HOLM,
            alpha=0.05,
        )
    ]
    if strict_omnibus:
        families.append(
            FamilySpec(
                family_id="omnibus_effects_strict",
                family_label="Primary factorial omnibus effects",
                method=CorrectionMethod.HOLM,
                alpha=0.05,
            )
        )
    return AnalysisRunSpec(
        profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        harmonic_provenance=HarmonicProvenance.USER_FIXED_UNVERIFIED,
        families=tuple(families),
        followup_provenance=followup_provenance,
    )


def _long_data() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    participants = (
        ("P1", "control"),
        ("P2", "control"),
        ("P3", "control"),
        ("P4", "anxious"),
        ("P5", "anxious"),
        ("P6", "anxious"),
    )
    for participant_index, (participant, group) in enumerate(participants):
        for condition_index, condition in enumerate(("A", "B")):
            for roi_index, roi in enumerate(("R1", "R2")):
                rows.append(
                    {
                        "participant": participant,
                        "condition": condition,
                        "roi": roi,
                        "value": (
                            participant_index * 0.2
                            + condition_index * 0.4
                            + roi_index * 0.3
                            + (0.8 if group == "anxious" else 0.0)
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _payload(
    *,
    mode: str = "multi",
    strict_omnibus: bool = False,
    analysis_scope: str = "complete_core",
    followup_provenance: FollowupProvenance = (
        FollowupProvenance.OMNIBUS_TRIGGERED
    ),
):
    groups = {
        f"P{index}": "control" if index <= 3 else "anxious"
        for index in range(1, 7)
    }
    data = _long_data()
    if analysis_scope == "available_case":
        data = data.loc[
            ~(
                data["participant"].eq("P6")
                & data["condition"].eq("B")
                & data["roi"].eq("R2")
            )
        ].copy()
    return prepare_analysis_payload(
        data,
        mode=mode,
        run_spec=_run_spec(
            strict_omnibus=strict_omnibus,
            followup_provenance=followup_provenance,
        ),
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        canonical_group_ids=groups if mode == "multi" else None,
        selected_group_pair=("anxious", "control") if mode == "multi" else None,
        preparation_id=f"{mode}-prepared",
        analysis_scope=analysis_scope,
    )


def _fake_lmm_contrasts(
    contrast_type: str,
    p_values: tuple[float, ...],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contrast_id": f"{contrast_type}::{index}",
                "contrast_type": contrast_type,
                "p_raw": p_value,
                "reportable": True,
                "status": "estimated",
                "method_label": "LMM-derived model-estimated contrast",
                "inference_method": "Asymptotic Wald z test (two-sided)",
                "missing_values_imputed": False,
            }
            for index, p_value in enumerate(p_values)
        ]
    )


def _cached_qc_report() -> QcExclusionReport:
    return QcExclusionReport(
        summary=QcExclusionSummary(
            n_subjects_before=3,
            n_subjects_flagged=0,
            n_subjects_after=3,
            warn_threshold=6.0,
            critical_threshold=10.0,
            warn_abs_floor_sumabs=5.0,
            critical_abs_floor_sumabs=10.0,
            warn_abs_floor_maxabs=1.0,
            critical_abs_floor_maxabs=2.0,
        ),
        participants=[],
        screened_conditions=["A"],
        screened_rois=["R1"],
    )


@dataclass
class _FrameBundle:
    status: str = "ok"
    omnibus: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(
            [
                {
                    "effect_id": "any_group_related",
                    "p_value_chi2": 0.04,
                    "reportable": True,
                }
            ]
        )
    )

    def to_frames(self) -> dict[str, pd.DataFrame]:
        return {"Fake Results": pd.DataFrame([{"value": 1.0}])}


def test_prepare_reuses_exact_payload_without_calling_audit(monkeypatch) -> None:
    payload = _payload()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("the design audit must not run again")

    monkeypatch.setattr(
        "Tools.Stats.analysis.prepared_analysis.audit_complete_core_design",
        fail_if_called,
    )
    result = workers.run_prepare_analysis(prepared_payload=payload)

    assert result["status"] == "ready"
    assert result["prepared_payload"] is payload
    assert result["primary_object"] is payload
    assert result["preparation_id"] == payload.preparation_id
    assert "Prepared Analysis" in result["export_frames"]


def test_prepare_cancellation_before_project_work_returns_cancelled(
    monkeypatch,
) -> None:
    def fail_if_called(**_kwargs):
        raise AssertionError("project preparation continued after cancellation")

    monkeypatch.setattr(
        workers,
        "_prepare_project_long_data",
        fail_if_called,
    )

    result = workers.run_prepare_analysis(
        subjects=["P1"],
        conditions=["A"],
        subject_data={"P1": {}},
        base_freq=6.0,
        rois={"R1": ["Oz"]},
        cancel_check=lambda: True,
    )

    assert result["status"] == "cancelled"
    assert result["status_code"] == "cancelled_during_preparation"
    assert result["cancellation_stage"] == "before_preparation"
    assert result["prepared_payload"] is None
    assert result["export_frames"] == {}


def test_prepare_cancellation_before_design_audit_skips_audit(
    monkeypatch,
) -> None:
    calls = 0

    def cancel_before_audit() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 2

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("design audit continued after cancellation")

    monkeypatch.setattr(workers, "prepare_analysis_payload", fail_if_called)
    result = workers.run_prepare_analysis(
        data=_long_data(),
        mode="single",
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        cancel_check=cancel_before_audit,
    )

    assert result["status"] == "cancelled"
    assert result["cancellation_stage"] == "before_design_audit"
    assert result["prepared_payload"] is None


def test_callback_first_model_and_group_steps_reuse_payload_and_frames(
    monkeypatch,
) -> None:
    payload = _payload()
    seen: list[tuple[str, str]] = []

    def fake_model(data, **kwargs):
        seen.append(("model", kwargs["participant_col"]))
        assert set(data["condition"]) == {"A", "B"}
        return _FrameBundle()

    monkeypatch.setattr(workers, "run_multigroup_mixed_model", fake_model)
    progress: list[int] = []
    messages: list[str] = []

    model = workers.run_multigroup_model_step(
        progress.append,
        messages.append,
        prepared_payload=payload,
        subjects=["legacy", "fields", "are", "ignored"],
    )
    cells = workers.run_group_cell_step(
        progress.append,
        messages.append,
        prepared_payload=payload,
    )

    assert seen == [("model", "participant")]
    for result in (model, cells):
        assert result["prepared_payload"] is payload
        assert result["preparation_id"] == "multi-prepared"
        assert "Step Status" in result["export_frames"]
    assert model["status"] == "ok"
    assert "Fake Results" in model["export_frames"]
    assert "Group Cell Contrasts" in model["export_frames"]
    assert cells["status"] == "superseded"
    assert (
        cells["status_code"]
        == "group_cell_comparisons_packaged_with_lmm"
    )
    assert progress[-1] == 100
    assert messages


def test_available_case_scope_reaches_multigroup_model_and_cell_tests(
    monkeypatch,
) -> None:
    payload = _payload(analysis_scope="available_case")
    captured: dict[str, object] = {}

    def fake_model(_data, **kwargs):
        captured["model_scope"] = kwargs["analysis_scope"]
        return _FrameBundle()

    monkeypatch.setattr(workers, "run_multigroup_mixed_model", fake_model)

    model_result = workers.run_multigroup_model_step(payload)
    cell_result = workers.run_group_cell_step(payload)

    assert model_result["status"] == "ok"
    assert cell_result["status"] == "superseded"
    assert captured == {"model_scope": "available_case"}


def test_multigroup_model_packages_ungated_holm_lmm_group_cells(
    monkeypatch,
) -> None:
    payload = _payload(strict_omnibus=True)
    fitted_model = object()
    omnibus = pd.DataFrame(
        {
            "effect_id": [
                "any_group_related",
                "group_condition_roi_interaction",
                "group_condition_block",
                "group_roi_block",
            ],
            "p_value_chi2": [0.8, 0.9, 0.7, 0.6],
            "reportable": [True, True, True, True],
            "status": ["ok", "ok", "ok", "ok"],
        }
    )

    @dataclass(frozen=True)
    class ModelBundle:
        status: str
        omnibus: pd.DataFrame
        fitted_model: object

        @property
        def reportable(self) -> bool:
            return True

        def to_frames(self) -> dict[str, pd.DataFrame]:
            return {"Omnibus LRT": self.omnibus.copy()}

    captured: dict[str, object] = {}

    def fake_group_cells(model, observed, **kwargs):
        captured["model"] = model
        captured["observed"] = observed.copy()
        captured.update(kwargs)
        return pd.DataFrame(
            [
                {
                    "condition": condition,
                    "roi": roi,
                    "group_a": "anxious",
                    "group_b": "control",
                    "p_raw": p_value,
                    "reportable": True,
                    "status": "estimated",
                    "coverage": "available observations; no imputation",
                    "method_label": (
                        "LMM-derived model-estimated contrast"
                    ),
                    "inference_method": (
                        "Asymptotic Wald z test (two-sided)"
                    ),
                }
                for (condition, roi), p_value in zip(
                    (("A", "R1"), ("A", "R2"), ("B", "R1"), ("B", "R2")),
                    (0.01, 0.03, 0.20, 0.60),
                    strict=True,
                )
            ]
        )

    monkeypatch.setattr(
        workers,
        "run_multigroup_mixed_model",
        lambda *_args, **_kwargs: ModelBundle(
            "ok",
            omnibus,
            fitted_model,
        ),
    )
    monkeypatch.setattr(
        workers,
        "estimate_group_cell_contrasts",
        fake_group_cells,
    )

    result = workers.run_multigroup_model_step(payload)
    cells = result["export_frames"]["Group Cell Contrasts"]

    assert result["status"] == "ok"
    assert captured["model"] is fitted_model
    assert captured["observed"].equals(payload.primary_data)
    assert (captured["group_a"], captured["group_b"]) == (
        "anxious",
        "control",
    )
    assert tuple(captured["condition_levels"]) == ("A", "B")
    assert tuple(captured["roi_levels"]) == ("R1", "R2")
    assert cells["p_adjusted"].tolist() == pytest.approx(
        [0.04, 0.09, 0.40, 0.60]
    )
    assert cells["family_id"].eq("group_core_cells").all()
    assert cells["family_size"].eq(4).all()
    assert cells["adjustment_method"].eq("holm").all()
    assert cells["omnibus_gated"].eq(False).all()
    assert cells["headline_eligible"].eq(True).all()
    assert cells["coverage"].str.contains("no imputation").all()
    assert cells["method_label"].eq(
        "LMM-derived model-estimated contrast"
    ).all()
    assert cells["inference_method"].eq(
        "Asymptotic Wald z test (two-sided)"
    ).all()
    assert result["group_cell_contrasts"].equals(cells)


def test_strict_omnibus_family_corrects_multigroup_lrt_rows(monkeypatch) -> None:
    payload = _payload(strict_omnibus=True)
    omnibus = pd.DataFrame(
        {
            "effect_id": [
                "any_group_related",
                "group_condition_roi_interaction",
                "group_condition_block",
                "group_roi_block",
            ],
            "p_value_chi2": [0.01, 0.03, 0.20, 0.60],
            "reportable": [True, True, True, True],
            "status": ["ok", "ok", "ok", "ok"],
        }
    )

    @dataclass(frozen=True)
    class ModelBundle:
        status: str
        omnibus: pd.DataFrame

        def to_frames(self) -> dict[str, pd.DataFrame]:
            return {"Omnibus LRT": self.omnibus.copy()}

    monkeypatch.setattr(
        workers,
        "run_multigroup_mixed_model",
        lambda *_args, **_kwargs: ModelBundle("ok", omnibus),
    )

    result = workers.run_multigroup_model_step(payload)
    corrected = result["export_frames"]["Omnibus LRT"]

    assert corrected["p_raw"].tolist() == pytest.approx(
        omnibus["p_value_chi2"].tolist()
    )
    assert corrected["p_adjusted"].tolist() == pytest.approx(
        [0.04, 0.09, 0.40, 0.60]
    )
    assert corrected["family_id"].eq("omnibus_effects_strict").all()
    assert corrected["family_size"].eq(4).all()
    assert corrected["adjustment_method"].eq("holm").all()
    assert corrected["headline_eligible"].eq(True).all()


def test_unadjusted_multigroup_omnibus_headlines_only_joint_block(
    monkeypatch,
) -> None:
    payload = _payload(strict_omnibus=False)
    omnibus = pd.DataFrame(
        {
            "effect_id": [
                "any_group_related",
                "group_condition_roi_interaction",
            ],
            "p_value_chi2": [0.04, 0.01],
            "reportable": [True, True],
            "status": ["ok", "ok"],
        }
    )

    @dataclass(frozen=True)
    class ModelBundle:
        status: str
        omnibus: pd.DataFrame

        def to_frames(self) -> dict[str, pd.DataFrame]:
            return {"Omnibus LRT": self.omnibus.copy()}

    monkeypatch.setattr(
        workers,
        "run_multigroup_mixed_model",
        lambda *_args, **_kwargs: ModelBundle("ok", omnibus),
    )

    result = workers.run_multigroup_model_step(payload)
    labelled = result["export_frames"]["Omnibus LRT"]

    assert labelled["headline_eligible"].tolist() == [True, False]
    assert labelled["inference_role"].tolist() == ["primary", "exploratory"]
    assert labelled["adjustment_method"].eq("none").all()


def test_strict_omnibus_family_corrects_single_rm_anova_rows(
    monkeypatch,
) -> None:
    payload = _payload(mode="single", strict_omnibus=True)
    anova = pd.DataFrame(
        {
            "Effect": ["condition", "roi", "condition * roi"],
            "p_reported": [0.01, 0.03, 0.20],
            "reportable": [True, True, True],
            "inference_status": ["ok", "ok", "ok"],
        }
    )
    monkeypatch.setattr(
        workers,
        "run_repeated_measures_anova",
        lambda *_args, **_kwargs: anova.copy(),
    )

    result = workers.run_single_rm_anova_step(payload)
    corrected = result["anova_df_results"]

    assert corrected["p_raw"].tolist() == pytest.approx([0.01, 0.03, 0.20])
    assert corrected["p_adjusted"].tolist() == pytest.approx([0.03, 0.06, 0.20])
    assert corrected["reject_adjusted"].tolist() == [True, False, False]
    assert corrected["family_id"].eq("omnibus_effects_strict").all()
    assert corrected["family_size"].eq(3).all()


@pytest.mark.parametrize("analysis_scope", ["complete_core", "available_case"])
def test_single_lmm_is_primary_and_packages_one_corrected_contrast_family(
    monkeypatch,
    analysis_scope: str,
) -> None:
    payload = _payload(
        mode="single",
        strict_omnibus=True,
        analysis_scope=analysis_scope,
    )
    fixed = pd.DataFrame([{"Effect": "Intercept", "Coef.": 1.0}])
    lrt = pd.DataFrame(
        {
            "effect_id": [
                "condition_roi_interaction",
                "condition_related_block",
                "roi_related_block",
            ],
            "p_value_chi2": [0.01, 0.03, 0.20],
            "status": ["ok", "ok", "ok"],
            "reportable": [True, True, True],
        }
    )
    fixed.attrs["lrt_table"] = lrt
    fixed.attrs["model_diagnostics"] = pd.DataFrame(
        [{"check_id": "observed_row_set", "status": "ok"}]
    )
    fitted = object()
    monkeypatch.setattr(
        workers,
        "run_mixed_effects_model",
        lambda **_kwargs: (fixed, fitted),
    )
    observed_inputs: list[pd.DataFrame] = []

    def condition_contrasts(model, data, **kwargs):
        assert model is fitted
        assert kwargs["condition_levels"] == payload.retained_conditions
        assert kwargs["roi_levels"] == payload.selected_rois
        observed_inputs.append(data.copy())
        return _fake_lmm_contrasts(
            "condition_within_roi",
            (0.01, 0.02),
        )

    def roi_contrasts(model, data, **kwargs):
        assert model is fitted
        observed_inputs.append(data.copy())
        return _fake_lmm_contrasts(
            "roi_within_condition",
            (0.04, 0.20),
        )

    monkeypatch.setattr(
        workers,
        "estimate_condition_within_roi_contrasts",
        condition_contrasts,
    )
    monkeypatch.setattr(
        workers,
        "estimate_roi_within_condition_contrasts",
        roi_contrasts,
    )

    result = workers.run_single_lmm_step(payload)
    corrected = result["export_frames"]["Mixed Model LRT"]
    contrasts = result["export_frames"]["LMM Contrasts"]

    assert result["status"] == "ok"
    assert corrected["p_adjusted"].tolist() == pytest.approx(
        [0.03, 0.06, 0.20]
    )
    assert corrected["headline_eligible"].all()
    assert corrected["inference_role"].eq("primary").all()
    assert corrected["analysis_scope"].eq(analysis_scope).all()
    assert corrected["missing_values_imputed"].eq(False).all()
    assert contrasts["p_adjusted"].tolist() == pytest.approx(
        [0.04, 0.06, 0.08, 0.20]
    )
    assert contrasts["family_id"].eq("planned_contrasts").all()
    assert contrasts["family_size"].eq(4).all()
    assert contrasts["adjustment_method"].eq("holm").all()
    assert contrasts["method_label"].eq(
        "LMM-derived model-estimated contrast"
    ).all()
    assert contrasts["headline_eligible"].all()
    assert contrasts["omnibus_gate_status"].eq("omnibus_supported").all()
    assert contrasts["missing_values_imputed"].eq(False).all()
    pd.testing.assert_frame_equal(result["lmm_contrasts_df"], contrasts)
    assert "Mixed Model Diagnostics" in result["export_frames"]
    assert result["fit_status"]["prepared_complete_core"] is (
        analysis_scope == "complete_core"
    )
    assert result["fit_status"]["n_observations"] == len(
        payload.primary_data
    )
    assert len(observed_inputs) == 2
    assert all(
        len(observed) == len(payload.primary_data)
        for observed in observed_inputs
    )
    if analysis_scope == "available_case":
        for observed in observed_inputs:
            missing = (
                observed["participant"].eq("P6")
                & observed["condition"].eq("B")
                & observed["roi"].eq("R2")
            )
            assert not missing.any()


@pytest.mark.parametrize(
    ("provenance", "expected_headline", "expected_gate"),
    [
        (
            FollowupProvenance.OMNIBUS_TRIGGERED,
            False,
            "omnibus_not_significant",
        ),
        (FollowupProvenance.PLANNED, True, "planned_not_gated"),
        (
            FollowupProvenance.EXPLORATORY_MANUAL,
            False,
            "exploratory_manual_detailed_only",
        ),
    ],
)
def test_single_lmm_contrast_headlines_respect_interaction_and_provenance(
    monkeypatch,
    provenance: FollowupProvenance,
    expected_headline: bool,
    expected_gate: str,
) -> None:
    payload = _payload(
        mode="single",
        strict_omnibus=True,
        followup_provenance=provenance,
    )
    fixed = pd.DataFrame([{"Effect": "Intercept", "Coef.": 1.0}])
    fixed.attrs["lrt_table"] = pd.DataFrame(
        {
            "effect_id": [
                "condition_roi_interaction",
                "condition_related_block",
                "roi_related_block",
            ],
            "p_value_chi2": [0.04, 0.50, 0.60],
            "status": ["ok", "ok", "ok"],
            "reportable": [True, True, True],
        }
    )
    fitted = object()
    monkeypatch.setattr(
        workers,
        "run_mixed_effects_model",
        lambda **_kwargs: (fixed, fitted),
    )
    monkeypatch.setattr(
        workers,
        "estimate_condition_within_roi_contrasts",
        lambda *_args, **_kwargs: _fake_lmm_contrasts(
            "condition_within_roi",
            (0.01,),
        ),
    )
    monkeypatch.setattr(
        workers,
        "estimate_roi_within_condition_contrasts",
        lambda *_args, **_kwargs: _fake_lmm_contrasts(
            "roi_within_condition",
            (0.02,),
        ),
    )

    result = workers.run_single_lmm_step(payload)
    contrasts = result["lmm_contrasts_df"]

    assert len(contrasts) == 2
    assert contrasts["headline_eligible"].eq(expected_headline).all()
    assert contrasts["followup_provenance"].eq(provenance.value).all()
    assert contrasts["omnibus_gate_status"].eq(expected_gate).all()
    assert contrasts["automatic_explanation_supported"].eq(False).all()


def test_available_case_blocks_rm_anova_and_retires_paired_posthocs(
    monkeypatch,
) -> None:
    payload = _payload(mode="single", analysis_scope="available_case")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("complete-matrix method reached available-case data")

    monkeypatch.setattr(
        workers,
        "run_repeated_measures_anova",
        fail_if_called,
    )

    anova = workers.run_single_rm_anova_step(payload)
    posthoc = workers.run_single_posthoc_step(payload)

    assert anova["status_code"] == "rm_anova_requires_complete_core"
    assert (
        posthoc["status_code"]
        == "paired_posthocs_superseded_by_lmm_contrasts"
    )
    assert posthoc["primary_object"] is None


def test_blocked_audit_refuses_downstream_model(monkeypatch) -> None:
    blocked = prepare_analysis_payload(
        _long_data(),
        mode="multi",
        run_spec=_run_spec(),
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        canonical_group_ids={"P1": "control", "P4": "anxious"},
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("blocked input reached the model")

    monkeypatch.setattr(workers, "run_multigroup_mixed_model", fail_if_called)
    result = workers.run_multigroup_model_step(blocked)

    assert result["status"] == "blocked"
    assert result["status_code"] == "missing_group_assignments"
    assert result["primary_object"] is None
    assert result["prepared_payload"] is blocked


def test_resampling_cancellation_propagates_without_partial_p_values() -> None:
    payload = _payload()
    calls = 0

    def cancel_during_resampling() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 3

    result = workers.run_sensitivity_step(
        payload,
        config={
            "run_robust": False,
            "run_resampling": True,
            "run_stability": False,
            "n_resamples": 99,
            "exact_enumeration_limit": 1,
        },
        cancel_check=cancel_during_resampling,
    )

    assert result["status"] == "cancelled"
    assert result["status_code"] == "cancelled_during_resampling"
    resampling = result["export_frames"]["Resampling Cell Results"]
    assert resampling["inference_status"].eq("cancelled").all()
    assert resampling["p_adjusted_max_t"].isna().all()


def test_sensitivity_step_returns_robust_resampling_and_stability_frames() -> None:
    payload = _payload()
    result = workers.run_sensitivity_step(
        payload,
        config={
            "run_robust": True,
            "run_resampling": True,
            "run_stability": True,
            "n_resamples": 19,
            "exact_enumeration_limit": 1,
        },
    )

    assert result["status"] == "ok"
    assert {
        "Robust Sensitivity Results",
        "Resampling Cell Results",
        "Resampling Metadata",
        "LOO Omission Details",
        "LOO Stability Summary",
        "Sensitivity Settings",
    }.issubset(result["export_frames"])
    assert (
        result["export_frames"]["Sensitivity Settings"].iloc[0]["seed"]
        == 1729
    )


def test_available_case_suppresses_complete_matrix_resampling() -> None:
    payload = _payload(analysis_scope="available_case")

    result = workers.run_sensitivity_step(
        payload,
        config={
            "run_robust": False,
            "run_resampling": True,
            "run_stability": False,
            "n_resamples": 19,
        },
    )

    assert result["status"] == "ok"
    metadata = result["export_frames"]["Resampling Metadata"].iloc[0]
    assert metadata["overall_status"] == "not_run"
    assert (
        metadata["status_code"]
        == "incompatible_with_available_case_scope"
    )
    assert "Resampling Cell Results" not in result["export_frames"]
    settings = result["export_frames"]["Sensitivity Settings"].iloc[0]
    assert bool(settings["run_resampling"]) is True
    assert bool(settings["run_resampling_effective"]) is False


def test_available_case_scope_reaches_leave_one_out_stability(
    monkeypatch,
) -> None:
    payload = _payload(analysis_scope="available_case")
    captured: dict[str, object] = {}

    class FakeStability:
        def to_frames(self):
            return {"LOO Stability Summary": pd.DataFrame([{"status": "ok"}])}

    def fake_stability(_data, **kwargs):
        captured["scope"] = kwargs["analysis_scope"]
        return FakeStability()

    monkeypatch.setattr(
        workers,
        "run_two_group_leave_one_out_stability",
        fake_stability,
    )
    result = workers.run_sensitivity_step(
        payload,
        config={
            "run_robust": False,
            "run_resampling": False,
            "run_stability": True,
        },
    )

    assert result["status"] == "ok"
    assert captured["scope"] == "available_case"


@pytest.mark.parametrize(
    ("function_name", "patched_name", "expected_key"),
    [
        (
            "run_single_rm_anova_step",
            "run_repeated_measures_anova",
            "anova_df_results",
        ),
        (
            "run_single_baseline_step",
            "run_baseline_vs_zero_tests",
            "results_df",
        ),
    ],
)
def test_single_adapters_preserve_established_payload_keys(
    monkeypatch,
    function_name: str,
    patched_name: str,
    expected_key: str,
) -> None:
    payload = _payload(mode="single")
    frame = pd.DataFrame([{"Effect": "condition", "p_reported": 0.2}])
    if patched_name == "run_repeated_measures_anova":
        monkeypatch.setattr(workers, patched_name, lambda *_args, **_kwargs: frame)
    else:
        monkeypatch.setattr(
            workers,
            patched_name,
            lambda *_args, **_kwargs: ("plain-language output", frame),
        )

    result = getattr(workers, function_name)(
        lambda _percent: None,
        lambda _message: None,
        prepared_payload=payload,
        legacy_unused_setting=True,
    )

    assert result["status"] == "ok"
    assert result["prepared_payload"] is payload
    assert result["preparation_id"] == "single-prepared"
    assert result[expected_key] is frame


def test_single_lmm_adapter_preserves_mixed_results_key(monkeypatch) -> None:
    payload = _payload(mode="single")
    frame = pd.DataFrame([{"Term": "Intercept", "Estimate": 1.0}])
    fitted = object()
    monkeypatch.setattr(
        workers,
        "run_mixed_effects_model",
        lambda **_kwargs: (frame, fitted),
    )
    empty = pd.DataFrame(columns=["p_raw", "reportable"])
    monkeypatch.setattr(
        workers,
        "estimate_condition_within_roi_contrasts",
        lambda *_args, **_kwargs: empty.copy(),
    )
    monkeypatch.setattr(
        workers,
        "estimate_roi_within_condition_contrasts",
        lambda *_args, **_kwargs: empty.copy(),
    )

    result = workers.run_single_lmm_step(
        prepared_payload=payload,
        legacy_unused_setting=True,
    )

    assert result["status"] == "ok"
    assert result["mixed_results_df"] is frame
    assert result["mixed_model"] is fitted
    assert result["prepared_payload"] is payload


def test_single_baseline_uses_locked_greater_than_zero_run_spec(
    monkeypatch,
) -> None:
    payload = _payload(mode="single")
    captured: dict[str, object] = {}
    frame = pd.DataFrame([{"condition": "A", "roi": "R1"}])

    def fake_baseline(*_args, **kwargs):
        captured.update(kwargs)
        return "positive-response screening", frame

    monkeypatch.setattr(workers, "run_baseline_vs_zero_tests", fake_baseline)

    result = workers.run_single_baseline_step(payload)

    assert result["status"] == "ok"
    assert captured["run_spec"] is payload.run_spec
    assert captured["alternative"] is payload.run_spec.response_alternative
    assert payload.run_spec.response_alternative.value == "greater"
    assert result["metadata"]["alternative"] == "greater"


def test_multi_baseline_dispatches_to_grouped_global_response_family(
    monkeypatch,
) -> None:
    payload = _payload(mode="multi")
    captured: dict[str, object] = {}
    frame = pd.DataFrame(
        [{"group": "anxious", "condition": "A", "roi": "R1"}]
    )

    def fake_grouped(*_args, **kwargs):
        captured.update(kwargs)
        return "grouped positive-response screening", frame

    monkeypatch.setattr(
        workers,
        "run_grouped_baseline_vs_zero_tests",
        fake_grouped,
    )

    result = workers.run_baseline_step(payload)

    assert result["status"] == "ok"
    assert result["status_code"] == "multigroup_baseline_vs_zero_ok"
    assert captured["group_col"] == payload.group_col
    assert captured["run_spec"] is payload.run_spec
    assert captured["alternative"] is payload.run_spec.response_alternative
    assert result["metadata"]["mode"] == "multi"
    assert "does not test whether the groups differ" in result["metadata"][
        "response_interpretation"
    ]


def test_project_input_prepare_path_runs_inside_callback_first_worker(
    monkeypatch,
) -> None:
    long_data = _long_data().rename(columns={"participant": "subject"})
    long_data = long_data[
        ~(
            long_data["subject"].eq("P6")
            & long_data["condition"].eq("B")
            & long_data["roi"].eq("R2")
        )
    ].copy()
    captured: dict[str, object] = {}

    def fake_project_prepare(**kwargs):
        captured.update(kwargs)
        return (
            long_data,
            [f"P{index}" for index in range(1, 7)],
            {"dv_metadata": {"policy_name": "fixed"}, "project_input_prepared": True},
        )

    monkeypatch.setattr(workers, "_prepare_project_long_data", fake_project_prepare)
    progress: list[int] = []
    result = workers.run_prepare_analysis(
        progress.append,
        lambda _message: None,
        subjects=[f"P{index}" for index in range(1, 7)],
        conditions=["A", "B"],
        conditions_all=["A", "B"],
        subject_data={f"P{index}": {} for index in range(1, 7)},
        base_freq=6.0,
        rois={"R1": ["Oz"], "R2": ["POz"]},
        mode="single",
        dv_policy={},
        group_map={"P1": "Displayed cohort"},
    )

    payload = result["prepared_payload"]
    assert result["status"] == "ready"
    assert payload.settings["project_input_prepared"] is True
    assert payload.participant_display_labels["P1"] == "Displayed cohort"
    assert payload.complete_conditions == ("A",)
    assert payload.excluded_conditions == ("B",)
    assert set(payload.primary_data["condition"]) == {"A"}
    assert captured["base_freq"] == 6.0
    assert progress[-1] == 100


def test_project_prepare_passes_available_scope_into_payload(
    monkeypatch,
) -> None:
    project_long = _long_data().rename(
        columns={"participant": "subject"}
    )
    project_long = project_long.loc[
        ~(
            project_long["subject"].eq("P6")
            & project_long["condition"].eq("B")
            & project_long["roi"].eq("R2")
        )
    ].copy()
    captured: dict[str, object] = {}

    def fake_project_prepare(**kwargs):
        captured["analysis_scope"] = kwargs["analysis_scope"]
        return (
            project_long,
            [f"P{index}" for index in range(1, 7)],
            {"project_input_prepared": True},
        )

    monkeypatch.setattr(
        workers,
        "_prepare_project_long_data",
        fake_project_prepare,
    )
    result = workers.run_prepare_analysis(
        subjects=[f"P{index}" for index in range(1, 7)],
        conditions=["A", "B"],
        subject_data={f"P{index}": {} for index in range(1, 7)},
        base_freq=6.0,
        rois={"R1": ["Oz"], "R2": ["POz"]},
        mode="single",
        analysis_scope="available_case",
    )

    payload = result["prepared_payload"]
    assert captured["analysis_scope"] == "available_case"
    assert payload.analysis_scope == "available_case"
    assert payload.retained_conditions == ("A", "B")
    assert len(payload.primary_data) == len(project_long)


def test_project_prepare_accepts_canonical_and_display_group_aliases(
    monkeypatch,
) -> None:
    project_long = _long_data().rename(columns={"participant": "subject"})
    monkeypatch.setattr(
        workers,
        "_prepare_project_long_data",
        lambda **_kwargs: (
            project_long,
            [f"P{index}" for index in range(1, 7)],
            {"project_input_prepared": True},
        ),
    )
    canonical = {
        f"P{index}": "control" if index <= 3 else "anxious"
        for index in range(1, 7)
    }
    display = {
        participant: (
            "Non-anxious" if group == "control" else "Anxious"
        )
        for participant, group in canonical.items()
    }

    result = workers.run_prepare_analysis(
        lambda _percent: None,
        lambda _message: None,
        subjects=list(canonical),
        conditions=["A", "B"],
        subject_data={participant: {} for participant in canonical},
        base_freq=6.0,
        rois={"R1": ["Oz"], "R2": ["POz"]},
        analysis_mode="multi_group",
        participant_group_ids=canonical,
        participants_map=display,
        group_pair=("anxious", "control"),
    )

    payload = result["prepared_payload"]
    assert payload.canonical_group_ids == canonical
    assert payload.participant_display_labels == display
    assert payload.selected_group_pair == ("anxious", "control")
    assert set(payload.primary_data["group_id"]) == {"control", "anxious"}


@pytest.mark.parametrize(
    "invalid_value",
    [float("nan"), float("inf")],
    ids=["nan", "inf"],
)
def test_project_adapter_reuses_qc_and_defers_nonfinite_cells_to_scope_audit(
    monkeypatch,
    invalid_value,
) -> None:
    qc_report = _cached_qc_report()
    seen_subjects: list[str] = []

    def fail_qc(*_args, **_kwargs):
        raise AssertionError("cached QC report was not reused")

    def fake_summed_bca(**kwargs):
        seen_subjects.extend(kwargs["subjects"])
        return {
            "P1": {"A": {"R1": 1.0}},
            "P2": {"A": {"R1": invalid_value}},
        }

    monkeypatch.setattr(workers, "run_qc_exclusion", fail_qc)
    monkeypatch.setattr(workers, "prepare_summed_bca_data", fake_summed_bca)
    frame, frozen, metadata = workers._prepare_project_long_data(
        subjects=["P1", "P2", "P3"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={"P1": {}, "P2": {}, "P3": {}},
        base_freq=6.0,
        rois={"R1": ["Oz"]},
        rois_all=None,
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
        outlier_abs_limit=50.0,
        qc_config=None,
        qc_state={"report": qc_report},
        manual_excluded_pids=["P3"],
        max_freq=None,
        project_root=None,
        message_emit=lambda _message: None,
        progress_callback=None,
    )

    assert seen_subjects == ["P1", "P2"]
    assert frozen == ["P1", "P2"]
    assert frame["subject"].tolist() == ["P1", "P2"]
    assert not np.isfinite(
        frame.loc[frame["subject"].eq("P2"), "value"].iloc[0]
    )
    assert metadata["qc_report"] is qc_report
    assert metadata["nonfinite_dv_cells"] == 1
    assert metadata["nonfinite_dv_handling"] == "analysis_scope"
    outlier_report = metadata["outlier_report"]
    assert outlier_report.summary.n_subjects_required_excluded == 0


def test_available_case_missing_workbook_does_not_exclude_participant(
    monkeypatch,
    tmp_path,
) -> None:
    p1_a = tmp_path / "P1_A.xlsx"
    p1_b = tmp_path / "P1_B.xlsx"
    p2_a = tmp_path / "P2_A.xlsx"
    for path in (p1_a, p1_b, p2_a):
        path.touch()

    monkeypatch.setattr(
        workers,
        "prepare_summed_bca_data",
        lambda **_kwargs: {
            "P1": {"A": {"R1": 1.0}, "B": {"R1": 1.2}},
            "P2": {"A": {"R1": 0.9}, "B": {"R1": float("nan")}},
        },
    )

    frame, frozen, metadata = workers._prepare_project_long_data(
        subjects=["P1", "P2"],
        conditions=["A", "B"],
        conditions_all=["A", "B"],
        subject_data={
            "P1": {"A": str(p1_a), "B": str(p1_b)},
            "P2": {"A": str(p2_a)},
        },
        base_freq=6.0,
        rois={"R1": ["Oz"]},
        rois_all=None,
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
        outlier_abs_limit=50.0,
        qc_config=None,
        qc_state={"report": _cached_qc_report()},
        manual_excluded_pids=None,
        max_freq=None,
        project_root=None,
        message_emit=lambda _message: None,
        progress_callback=None,
        analysis_scope="available_case",
    )

    assert frozen == ["P1", "P2"]
    assert set(frame["subject"]) == {"P1", "P2"}
    assert not (
        frame["subject"].eq("P2") & frame["condition"].eq("B")
    ).any()
    assert metadata["analysis_scope"] == "available_case"
    assert metadata["missing_source_workbooks"] == [
        {
            "participant_id": "P2",
            "condition": "B",
            "reason": "source_workbook_absent",
            "source_path": "",
        }
    ]
    assert (
        metadata["outlier_report"].summary.n_subjects_required_excluded
        == 0
    )


def test_available_case_present_workbook_nonfinite_preserves_frozen_participant(
    monkeypatch,
    tmp_path,
) -> None:
    p1_a = tmp_path / "P1_A.xlsx"
    p2_a = tmp_path / "P2_A.xlsx"
    p1_a.touch()
    p2_a.touch()
    monkeypatch.setattr(
        workers,
        "prepare_summed_bca_data",
        lambda **_kwargs: {
            "P1": {"A": {"R1": 1.0}},
            "P2": {"A": {"R1": float("nan")}},
        },
    )

    frame, frozen, metadata = workers._prepare_project_long_data(
        subjects=["P1", "P2"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={
            "P1": {"A": str(p1_a)},
            "P2": {"A": str(p2_a)},
        },
        base_freq=6.0,
        rois={"R1": ["Oz"]},
        rois_all=None,
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
        outlier_abs_limit=50.0,
        qc_config=None,
        qc_state={"report": _cached_qc_report()},
        manual_excluded_pids=None,
        max_freq=None,
        project_root=None,
        message_emit=lambda _message: None,
        progress_callback=None,
        analysis_scope="available_case",
    )

    assert frozen == ["P1", "P2"]
    assert frame["subject"].tolist() == ["P1", "P2"]
    assert frame.loc[frame["subject"].eq("P2"), "value"].isna().all()
    assert (
        metadata["outlier_report"].summary.n_subjects_required_excluded
        == 0
    )


def test_complete_core_excludes_incomplete_condition_not_participants(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        workers,
        "prepare_summed_bca_data",
        lambda **_kwargs: {
            "P1": {"Shared": {"R1": 1.0}, "Partial": {"R1": 1.2}},
            "P2": {
                "Shared": {"R1": 0.9},
                "Partial": {"R1": float("nan")},
            },
        },
    )

    result = workers.run_prepare_analysis(
        subjects=["P1", "P2"],
        conditions=["Shared", "Partial"],
        conditions_all=["Shared", "Partial"],
        subject_data={"P1": {}, "P2": {}},
        base_freq=6.0,
        rois={"R1": ["Oz"]},
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
        qc_state={"report": _cached_qc_report()},
        mode="multi",
        canonical_group_ids={"P1": "control", "P2": "anxious"},
        selected_group_pair=("anxious", "control"),
        analysis_scope="complete_core",
    )

    payload = result["prepared_payload"]
    assert result["status"] == "ready"
    assert payload.frozen_participants == ("P1", "P2")
    assert payload.retained_conditions == ("Shared",)
    assert payload.excluded_conditions == ("Partial",)
    assert set(payload.primary_data["subject"]) == {"P1", "P2"}


def test_prepare_cancellation_after_adaptive_preflight_skips_summed_bca(
    monkeypatch,
) -> None:
    cancelled = False

    def cancel_check() -> bool:
        return cancelled

    def finish_preflight(**_kwargs):
        nonlocal cancelled
        cancelled = True

    def fail_summed_bca(**_kwargs):
        raise AssertionError("Summed-BCA continued after cancellation")

    class _CacheMiss:
        hit = None

    monkeypatch.setattr(
        workers,
        "build_group_harmonic_cache_request",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        workers,
        "lookup_cached_group_harmonic_selection",
        lambda _request: _CacheMiss(),
    )
    monkeypatch.setattr(
        workers,
        "preflight_group_significant_full_fft_columns",
        finish_preflight,
    )
    monkeypatch.setattr(
        workers,
        "prepare_summed_bca_data",
        fail_summed_bca,
    )

    result = workers.run_prepare_analysis(
        subjects=["P1", "P2"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={"P1": {}, "P2": {}},
        base_freq=6.0,
        rois={"R1": ["Oz"]},
        dv_policy={"name": GROUP_SIGNIFICANT_POLICY_NAME},
        qc_state={"report": _cached_qc_report()},
        cancel_check=cancel_check,
    )

    assert result["status"] == "cancelled"
    assert result["cancellation_stage"] == "after_adaptive_preflight"
    assert result["prepared_payload"] is None


def test_prepare_cancellation_after_summed_bca_skips_hard_filter(
    monkeypatch,
) -> None:
    cancelled = False

    def cancel_check() -> bool:
        return cancelled

    def finish_summed_bca(**_kwargs):
        nonlocal cancelled
        cancelled = True
        return {
            "P1": {"A": {"R1": 1.0}},
            "P2": {"A": {"R1": 2.0}},
        }

    def fail_hard_filter(*_args, **_kwargs):
        raise AssertionError("hard-DV filtering continued after cancellation")

    monkeypatch.setattr(
        workers,
        "prepare_summed_bca_data",
        finish_summed_bca,
    )
    monkeypatch.setattr(
        workers,
        "apply_hard_dv_exclusion",
        fail_hard_filter,
    )

    result = workers.run_prepare_analysis(
        subjects=["P1", "P2"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={"P1": {}, "P2": {}},
        base_freq=6.0,
        rois={"R1": ["Oz"]},
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
        qc_state={"report": _cached_qc_report()},
        cancel_check=cancel_check,
    )

    assert result["status"] == "cancelled"
    assert result["cancellation_stage"] == "after_summed_bca"
    assert result["prepared_payload"] is None


def test_prepare_cancellation_after_hard_filter_skips_design_audit(
    monkeypatch,
) -> None:
    cancelled = False
    real_hard_filter = workers.apply_hard_dv_exclusion

    def cancel_check() -> bool:
        return cancelled

    def finish_summed_bca(**_kwargs):
        return {
            "P1": {"A": {"R1": 1.0}},
            "P2": {"A": {"R1": 2.0}},
        }

    def finish_hard_filter(*args, **kwargs):
        nonlocal cancelled
        result = real_hard_filter(*args, **kwargs)
        cancelled = True
        return result

    def fail_design_audit(*_args, **_kwargs):
        raise AssertionError("design audit continued after cancellation")

    monkeypatch.setattr(
        workers,
        "prepare_summed_bca_data",
        finish_summed_bca,
    )
    monkeypatch.setattr(
        workers,
        "apply_hard_dv_exclusion",
        finish_hard_filter,
    )
    monkeypatch.setattr(
        workers,
        "prepare_analysis_payload",
        fail_design_audit,
    )

    result = workers.run_prepare_analysis(
        subjects=["P1", "P2"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={"P1": {}, "P2": {}},
        base_freq=6.0,
        rois={"R1": ["Oz"]},
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
        qc_state={"report": _cached_qc_report()},
        cancel_check=cancel_check,
    )

    assert result["status"] == "cancelled"
    assert result["cancellation_stage"] == "after_hard_dv_filter"
    assert result["prepared_payload"] is None


def test_report_worker_accepts_prepared_payload_and_prior_results() -> None:
    payload = _payload()
    result = workers.run_report_bundle_step(
        prepared_payload=payload,
        prior_results={"cells": {"frames": {"Cell": pd.DataFrame([{"p": 0.2}])}}},
    )

    assert result["status"] == "ok"
    assert result["prepared_payload"] is payload
    assert result["preparation_id"] == payload.preparation_id
    assert "At a Glance" in result["export_frames"]
    assert result["exported"] is False
    assert result["numeric_exported"] is False


class _FakeReportBundle:
    at_a_glance = "Simple report"
    detailed_methods = "Detailed methods"

    def to_frames(self, *, export_path=None):
        return {
            "Report": pd.DataFrame([{"path": str(export_path or "")}])
        }


def test_report_worker_exports_full_bundle_in_worker(monkeypatch, tmp_path) -> None:
    from Tools.Stats.reporting import inference_report

    payload = _payload()
    bundle = _FakeReportBundle()
    requested = tmp_path / "requested.xlsx"
    actual = tmp_path / "actual.xlsx"
    calls: list[tuple[object, object]] = []
    monkeypatch.setattr(
        inference_report,
        "build_native_inference_report",
        lambda **_kwargs: bundle,
    )

    def fake_write(candidate, path):
        calls.append((candidate, path))
        return actual

    monkeypatch.setattr(
        inference_report,
        "write_native_inference_workbook",
        fake_write,
    )

    result = workers.run_report_bundle_step(
        prepared_payload=payload,
        prior_results={"cells": {}},
        export_path=requested,
    )

    assert result["status"] == "ok"
    assert result["exported"] is True
    assert result["numeric_exported"] is True
    assert result["export_path"] == str(actual)
    assert result["prepared_payload"] is payload
    assert calls == [(bundle, requested)]


def test_report_worker_falls_back_to_numeric_export_on_workbook_failure(
    monkeypatch,
    tmp_path,
) -> None:
    from Tools.Stats.reporting import inference_report

    payload = _payload()
    bundle = _FakeReportBundle()
    requested = tmp_path / "requested.xlsx"
    actual = tmp_path / "numeric.xlsx"
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        inference_report,
        "build_native_inference_report",
        lambda **_kwargs: bundle,
    )

    def fail_full_export(_bundle, _path):
        raise OSError("full workbook unavailable")

    def numeric_fallback(prepared, prior, path, *, report_error):
        captured.update(
            {
                "prepared": prepared,
                "prior": prior,
                "path": path,
                "report_error": report_error,
            }
        )
        return actual

    monkeypatch.setattr(
        inference_report,
        "write_native_inference_workbook",
        fail_full_export,
    )
    monkeypatch.setattr(
        inference_report,
        "write_native_numeric_workbook",
        numeric_fallback,
    )

    prior = {"model": {"status": "ok"}}
    result = workers.run_report_bundle_step(
        prepared_payload=payload,
        prior_results=prior,
        export_path=requested,
    )

    assert result["status"] == "failed"
    assert result["status_code"] == "reporting_failed"
    assert result["exported"] is False
    assert result["numeric_exported"] is True
    assert result["export_path"] == str(actual)
    assert result["prepared_payload"] is payload
    assert captured["prepared"] is payload
    assert captured["prior"] == prior
    assert captured["path"] == requested
    assert "OSError" in str(captured["report_error"])


def test_report_worker_reports_both_workbook_export_failures(
    monkeypatch,
    tmp_path,
) -> None:
    from Tools.Stats.reporting import inference_report

    payload = _payload()
    bundle = _FakeReportBundle()
    monkeypatch.setattr(
        inference_report,
        "build_native_inference_report",
        lambda **_kwargs: bundle,
    )

    def fail_full_export(_bundle, _path):
        raise OSError("full workbook unavailable")

    def fail_numeric(*_args, **_kwargs):
        raise PermissionError("numeric workbook unavailable")

    monkeypatch.setattr(
        inference_report,
        "write_native_inference_workbook",
        fail_full_export,
    )
    monkeypatch.setattr(
        inference_report,
        "write_native_numeric_workbook",
        fail_numeric,
    )

    result = workers.run_report_bundle_step(
        prepared_payload=payload,
        prior_results={"model": {"status": "ok"}},
        export_path=tmp_path / "failed.xlsx",
    )

    assert result["status"] == "failed"
    assert result["status_code"] == "reporting_failed"
    assert result["exported"] is False
    assert result["numeric_exported"] is False
    assert result["export_path"] == ""
    assert "OSError" in result["report_error"]
    assert "PermissionError" in result["fallback_error"]
    assert result["prepared_payload"] is payload


def test_report_worker_falls_back_to_numeric_export_on_assembly_failure(
    monkeypatch,
    tmp_path,
) -> None:
    from Tools.Stats.reporting import inference_report

    payload = _payload()
    requested = tmp_path / "fallback.xlsx"
    actual = tmp_path / "numeric.xlsx"
    captured: dict[str, object] = {}

    def fail_report(**_kwargs):
        raise RuntimeError("plain-language rendering failed")

    def numeric_fallback(prepared, prior, path, *, report_error):
        captured.update(
            {
                "prepared": prepared,
                "prior": prior,
                "path": path,
                "report_error": report_error,
            }
        )
        return actual

    monkeypatch.setattr(
        inference_report,
        "build_native_inference_report",
        fail_report,
    )
    monkeypatch.setattr(
        inference_report,
        "write_native_numeric_workbook",
        numeric_fallback,
        raising=False,
    )

    prior = {"model": {"status": "ok"}}
    result = workers.run_report_bundle_step(
        prepared_payload=payload,
        prior_results=prior,
        export_path=requested,
    )

    assert result["status"] == "failed"
    assert result["status_code"] == "reporting_failed"
    assert result["exported"] is False
    assert result["numeric_exported"] is True
    assert result["export_path"] == str(actual)
    assert result["prepared_payload"] is payload
    assert captured["prepared"] is payload
    assert captured["prior"] == prior
    assert captured["path"] == requested
    assert "RuntimeError" in str(captured["report_error"])


def test_report_worker_reports_fallback_failure_and_import_error(
    monkeypatch,
    tmp_path,
) -> None:
    from Tools.Stats.reporting import inference_report

    payload = _payload()

    def missing_reporter(**_kwargs):
        raise ImportError("reporting dependency unavailable")

    def fail_numeric(*_args, **_kwargs):
        raise OSError("numeric workbook unavailable")

    monkeypatch.setattr(
        inference_report,
        "build_native_inference_report",
        missing_reporter,
    )
    monkeypatch.setattr(
        inference_report,
        "write_native_numeric_workbook",
        fail_numeric,
        raising=False,
    )

    result = workers.run_report_bundle_step(
        prepared_payload=payload,
        prior_results={"cells": {}},
        export_path=tmp_path / "failed.xlsx",
    )

    assert result["status"] == "failed"
    assert result["status_code"] == "reporting_failed"
    assert result["exported"] is False
    assert result["numeric_exported"] is False
    assert result["export_path"] == ""
    assert "ImportError" in result["report_error"]
    assert "OSError" in result["fallback_error"]
    assert result["prepared_payload"] is payload
