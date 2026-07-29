from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from Tools.Stats.analysis.dv_policies import FIXED_PREDEFINED_POLICY_NAME
from Tools.Stats.analysis.dv_policies import GROUP_SIGNIFICANT_POLICY_NAME
from Tools.Stats.analysis.inference_contracts import (
    AnalysisProfile,
    AnalysisRunSpec,
    HarmonicProvenance,
)
from Tools.Stats.analysis.prepared_analysis import prepare_analysis_payload
from Tools.Stats.qc.stats_qc_exclusion import (
    QcExclusionReport,
    QcExclusionSummary,
)
from Tools.Stats.workers import multigroup_workers as workers


def _run_spec() -> AnalysisRunSpec:
    return AnalysisRunSpec(
        profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        harmonic_provenance=HarmonicProvenance.USER_FIXED_UNVERIFIED,
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


def _payload(*, mode: str = "multi"):
    groups = {
        f"P{index}": "control" if index <= 3 else "anxious"
        for index in range(1, 7)
    }
    return prepare_analysis_payload(
        _long_data(),
        mode=mode,
        run_spec=_run_spec(),
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        canonical_group_ids=groups if mode == "multi" else None,
        selected_group_pair=("anxious", "control") if mode == "multi" else None,
        preparation_id=f"{mode}-prepared",
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

    def fake_cells(data, **kwargs):
        seen.append(("cells", kwargs["subject_col"]))
        assert kwargs["group_pair"] == ("anxious", "control")
        return _FrameBundle()

    monkeypatch.setattr(workers, "run_multigroup_mixed_model", fake_model)
    monkeypatch.setattr(workers, "_run_group_cell_comparisons", fake_cells)
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

    assert seen == [
        ("model", "participant"),
        ("cells", "participant"),
    ]
    for result in (model, cells):
        assert result["status"] == "ok"
        assert result["prepared_payload"] is payload
        assert result["preparation_id"] == "multi-prepared"
        assert "Fake Results" in result["export_frames"]
        assert "Step Status" in result["export_frames"]
    assert progress[-1] == 100
    assert messages


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


@pytest.mark.parametrize(
    ("function_name", "patched_name", "expected_key"),
    [
        (
            "run_single_rm_anova_step",
            "run_repeated_measures_anova",
            "anova_df_results",
        ),
        (
            "run_single_posthoc_step",
            "run_interaction_posthocs",
            "results_df",
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

    result = workers.run_single_lmm_step(
        prepared_payload=payload,
        legacy_unused_setting=True,
    )

    assert result["status"] == "ok"
    assert result["mixed_results_df"] is frame
    assert result["mixed_model"] is fitted
    assert result["prepared_payload"] is payload


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
def test_project_adapter_reuses_qc_and_applies_manual_then_nonfinite_exclusions(
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
    assert frozen == ["P1"]
    assert frame["subject"].tolist() == ["P1"]
    assert metadata["qc_report"] is qc_report
    outlier_report = metadata["outlier_report"]
    assert outlier_report.summary.n_subjects_required_excluded == 1


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
