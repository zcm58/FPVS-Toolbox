from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import Tools.Stats.qc.stats_qc_exclusion as qc_exclusion
from Tools.Stats.analysis.dv_policies import (
    FIXED_PREDEFINED_POLICY_NAME,
    prepare_summed_bca_data,
)
from Tools.Stats.qc.stats_qc_exclusion import (
    QC_REASON_SUMABS,
    QcViolation,
    format_qc_violation,
    load_shared_frequency_qc_review,
    run_qc_exclusion,
)


def _make_bca_df(max_value: float) -> pd.DataFrame:
    data = {
        "1.2000_Hz": [0.1, 0.1],
        "2.4000_Hz": [0.1, 0.1],
        "3.6000_Hz": [0.1, 0.1],
        "4.8000_Hz": [0.1, 0.1],
        "7.2000_Hz": [max_value, max_value],
    }
    df = pd.DataFrame(data, index=["O1", "O2"])
    df.index.name = "Electrode"
    return df


@pytest.mark.parametrize("suffix", [".xlsx", ".xls", ".fpvs"])
def test_projectless_roi_qc_is_retired_without_source_reads(monkeypatch, tmp_path, suffix):
    from pathlib import Path

    def fail_read(*_args, **_kwargs):
        raise AssertionError("Retired ROI screening must not read source workbooks")

    monkeypatch.setattr(Path, "open", fail_read)
    messages = []
    report = run_qc_exclusion(
        subjects=["P1", "P2"],
        subject_data={"P1": {"A": str(tmp_path / ("extreme" + suffix))}, "P2": {}},
        conditions_all=["A", "B"],
        rois_all={"Occipital": ["O1", "O2"]},
        base_freq=6.0,
        warn_threshold=0.0001,
        log_func=messages.append,
    )
    assert report.source == "retired_roi_screen"
    assert report.screening_status == "not_performed"
    assert report.authority == "none"
    assert report.review_complete is False
    assert report.participants == []
    assert report.screened_rois == []
    assert report.screened_conditions == []
    assert report.excluded_pids == set()
    assert report.summary.n_subjects_before == report.summary.n_subjects_after == 2
    assert report.summary.n_subjects_flagged == 0
    assert any("retired" in message for message in messages)


def test_retiring_roi_screen_preserves_normal_roi_summed_bca(tmp_path):
    path = tmp_path / "P1_A.xlsx"
    _write_bca_workbook(path, _make_bca_df(1000.0))
    data = {"P1": {"A": str(path)}}
    report = run_qc_exclusion(
        subjects=["P1"], subject_data=data, conditions_all=["A"],
        rois_all={"Occipital": ["O1", "O2"]}, base_freq=6.0,
    )
    assert report.participants == []
    dv_data = prepare_summed_bca_data(
        subjects=["P1"], conditions=["A"], subject_data=data,
        base_freq=6.0, log_func=lambda _m: None,
        rois={"Occipital": ["O1", "O2"]},
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
    )
    assert dv_data["P1"]["A"]["Occipital"] == 1000.4


def _write_bca_workbook(path, frame: pd.DataFrame) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="BCA (uV)")


def test_format_qc_violation_is_human_readable() -> None:
    violation = QcViolation(
        condition="CondA",
        roi="ROI1",
        metric=QC_REASON_SUMABS,
        severity="WARNING",
        value=12.34,
        robust_center=1.23,
        robust_spread=0.45,
        robust_score=7.89,
        threshold_used=6.0,
        abs_floor_used=5.0,
        trigger_harmonic_hz=12.0,
        roi_mean_bca_at_trigger=0.1234,
    )

    text = format_qc_violation(violation)

    assert "Unusually large total response" in text
    assert "Condition: CondA" in text
    assert "ROI: ROI1" in text
    assert "value: 12.3400" in text
    assert "Robust score: 7.890" in text
    assert "threshold 6.00" in text


@pytest.mark.parametrize("threshold", [float("nan"), 250.0])
def test_shared_electrode_format_omits_retired_roi_robust_context(threshold):
    from Tools.Stats.qc.stats_outlier_exclusion import (
        format_flag_type_display, format_outlier_reason, format_worst_value_display,
    )

    metric = qc_exclusion.QC_REASON_ABSOLUTE_ELECTRODE
    violation = QcViolation(
        condition="Faces", roi="O2", metric=metric, severity="EXTREME",
        value=300.0, robust_center=float("nan"), robust_spread=float("nan"),
        robust_score=float("nan"), threshold_used=threshold, abs_floor_used=float("nan"),
        recording_id="P1__V2", decision="retain", source="shared_project_qc17_review",
    )
    text = format_qc_violation(violation)
    assert "Condition: Faces, Electrode: O2" in text
    assert "Summed-BCA magnitude: 300.0000 µV" in text
    assert "Recording: P1__V2" in text
    assert "Saved QC-17 decision: retain" in text
    assert "ROI" not in text
    assert "robust" not in text.casefold()
    assert "nan" not in text.casefold()
    assert ("Review threshold:" in text) == (threshold == 250.0)
    assert format_flag_type_display(metric) == "Large electrode summed BCA"
    assert format_outlier_reason(metric) == "Unusually large electrode summed BCA."
    assert format_worst_value_display(metric, 300.0) == (
        "Electrode summed-BCA magnitude: 300.0000 µV", None,
    )


def test_managed_stats_reuses_recording_aware_qc17_evidence(monkeypatch, tmp_path) -> None:
    import Main_App.processing.frequency_domain_qc as project_qc

    rows = tuple(
        {
            "recording_id": recording_id,
            "participant_id": "P1",
            "condition": "Faces",
            "roi": "",
            "electrode": "O2",
            "decision": "retain",
            "reason": "",
            "finding_fingerprint": f"finding-{recording_id}",
        }
        for recording_id in ("P1__V1", "P1__V2")
    )
    findings = [
        {
            "finding_type": "absolute_electrode_summed_bca",
            "recording_id": row["recording_id"],
            "participant_id": "P1",
            "condition": "Faces",
            "roi": "",
            "electrode": "O2",
            "value_uv": 12.0,
            "robust_center_uv": 2.0,
            "robust_spread_uv": 1.0,
            "robust_score": 10.0,
            "threshold_used": 10.0,
            "absolute_floor_used_uv": 10.0,
            "severity": "extreme",
            "finding_fingerprint": row["finding_fingerprint"],
            "harmonic_selection_fingerprint": "harmonic-fingerprint",
        }
        for row in rows
    ]
    monkeypatch.setattr(
        project_qc,
        "resolve_frequency_qc_coverage_decisions",
        lambda _root: SimpleNamespace(
            review_complete=True,
            decision_fingerprint="decision-fingerprint",
            reviewed_decisions=rows,
        ),
    )
    monkeypatch.setattr(
        project_qc,
        "load_current_frequency_qc_review_evidence",
        lambda _root: {
            "cohort_findings": [],
            "ordinary_findings": findings,
            "screening_settings": {
                "cohort_warning_robust_score": 6.0,
                "cohort_extreme_robust_score": 10.0,
            },
            "screening_status": "performed",
            "source_fingerprint": "source-fingerprint",
            "evidence_fingerprint": "evidence-fingerprint",
            "harmonic_selection_fingerprint": "harmonic-fingerprint",
        },
    )

    report = load_shared_frequency_qc_review(
        project_root=tmp_path,
        subjects=["P1__V1", "P1__V2"],
        conditions_all=["Faces"],
        rois_all={"Right OT": ["O2"]},
    )

    assert report.source == "shared_project_qc17_review"
    assert report.screened_rois == []
    assert all(v.metric == qc_exclusion.QC_REASON_ABSOLUTE_ELECTRODE
               for item in report.participants for v in item.violations)
    assert report.source_fingerprint == "source-fingerprint"
    assert report.decision_fingerprint == "decision-fingerprint"
    assert report.evidence_fingerprint == "evidence-fingerprint"
    assert report.harmonic_selection_fingerprint == "harmonic-fingerprint"
    assert [item.participant_id for item in report.participants] == [
        "P1__V1",
        "P1__V2",
    ]
    assert all(
        violation.source == "shared_project_qc17_review"
        for participant in report.participants
        for violation in participant.violations
    )
    assert all(
        violation.participant_id == "P1"
        and violation.decision == "retain"
        and violation.harmonic_selection_fingerprint == "harmonic-fingerprint"
        for participant in report.participants
        for violation in participant.violations
    )
    from Tools.Stats.qc.stats_outlier_exclusion import build_flagged_participants_tables

    summary, details = build_flagged_participants_tables(report, None)
    # Keep the existing workbook keys while making their displayed text exact.
    assert details["roi"].tolist() == ["O2", "O2"]
    assert summary["worst_roi"].tolist() == ["O2", "O2"]
    for text in [*details["reason_text"], *summary["reason_text"]]:
        assert "Electrode: O2" in text
        assert "ROI:" not in text
        assert "Robust score:" not in text


def test_managed_stats_preserves_stabilized_reconfirmation_only_exclusion(
    monkeypatch,
    tmp_path,
) -> None:
    import Main_App.processing.frequency_domain_qc as project_qc

    decision = {
        "recording_id": "P1__V1",
        "participant_id": "P1",
        "session_id": "visit_1",
        "condition": "Faces",
        "electrode": "O2",
        "roi": "",
        "decision": "exclude_condition_electrode",
        "reason": "Reviewed condition-specific artifact",
        "finding_fingerprint": "reconfirmation-finding",
        "evidence": {
            "finding_type": "prior_outcome_informed_exclusion_reconfirmation",
            "summed_bca_uv": 300.0,
            "abs_summed_bca_uv": 300.0,
            "severity": "reconfirmation",
            "band_crossed": "reconfirmation required; prior band extreme",
            "selected_harmonics_hz": [1.2, 2.4],
            "harmonic_selection_fingerprint": "harmonic-fingerprint",
            "independent_qc": [
                {
                    "source": "qc21_pre_review_coverage",
                    "status": "current",
                    "authority": "context_only",
                }
            ],
            "independent_qc_status": "available",
            "independent_qc_authority": "context_only",
            "independent_qc_fingerprint": "independent-fingerprint",
        },
    }
    monkeypatch.setattr(
        project_qc,
        "resolve_frequency_qc_coverage_decisions",
        lambda _root: SimpleNamespace(
            review_complete=True,
            decision_fingerprint="decision-fingerprint",
            reviewed_decisions=(decision,),
        ),
    )
    monkeypatch.setattr(
        project_qc,
        "load_current_frequency_qc_review_evidence",
        lambda _root: {
            "ordinary_findings": [],
            "cohort_findings": [],
            "reconfirmation_findings": [],
            "screening_settings": {},
            "screening_status": "performed",
            "source_fingerprint": "source-fingerprint",
            "evidence_fingerprint": "evidence-fingerprint",
            "harmonic_selection_fingerprint": "harmonic-fingerprint",
        },
    )

    report = load_shared_frequency_qc_review(
        project_root=tmp_path,
        subjects=["P1__V1"],
        conditions_all=["Faces"],
        rois_all={"Right OT": ["O2"]},
    )

    assert report.excluded_pids == set()
    assert len(report.participants) == 1
    violation = report.participants[0].violations[0]
    assert report.participants[0].participant_id == "P1__V1"
    assert violation.recording_id == "P1__V1"
    assert violation.participant_id == "P1"
    assert violation.condition == "Faces"
    assert violation.roi == "O2"
    assert violation.decision == "exclude_condition_electrode"
    assert violation.decision_reason == "Reviewed condition-specific artifact"
    assert violation.evidence_fingerprint == "reconfirmation-finding"
    assert violation.source == "shared_project_qc17_review"
    assert violation.shared_decision_fingerprint == "decision-fingerprint"
    assert violation.shared_source_fingerprint == "source-fingerprint"
    assert violation.shared_evidence_fingerprint == "evidence-fingerprint"
    assert violation.harmonic_selection_fingerprint == "harmonic-fingerprint"
    assert violation.authority == "review_only"


def test_managed_stats_rejects_incomplete_qc17_review(monkeypatch, tmp_path) -> None:
    import Main_App.processing.frequency_domain_qc as project_qc

    monkeypatch.setattr(
        project_qc,
        "load_frequency_domain_qc_state",
        lambda _root: {},
    )
    monkeypatch.setattr(
        project_qc,
        "resolve_frequency_qc_coverage_decisions",
        lambda _root: SimpleNamespace(review_complete=False),
    )

    with pytest.raises(RuntimeError, match="completed experimental summed-BCA review"):
        load_shared_frequency_qc_review(
            project_root=tmp_path,
            subjects=["P1"],
            conditions_all=["Faces"],
            rois_all={},
        )


def test_managed_stats_rejects_stale_qc17_evidence(monkeypatch, tmp_path) -> None:
    import Main_App.processing.frequency_domain_qc as project_qc

    monkeypatch.setattr(
        project_qc,
        "resolve_frequency_qc_coverage_decisions",
        lambda _root: SimpleNamespace(
            review_complete=True,
            decision_fingerprint="decision-fingerprint",
            reviewed_decisions=(),
        ),
    )
    monkeypatch.setattr(
        project_qc,
        "load_current_frequency_qc_review_evidence",
        lambda _root: (_ for _ in ()).throw(
            RuntimeError("Saved evidence is stale or tampered")
        ),
    )

    with pytest.raises(RuntimeError, match="stale or tampered"):
        load_shared_frequency_qc_review(
            project_root=tmp_path,
            subjects=["P1"],
            conditions_all=["Faces"],
            rois_all={},
        )


@pytest.mark.parametrize("legacy", [
    {"roi": "Right OT"},
    {"metric": "sum_abs_roi_mean"},
    {"metric": "peak_abs_roi_mean"},
    {"finding_type": "cohort_relative_summed_bca_context"},
])
def test_managed_stats_never_revives_legacy_roi_findings(monkeypatch, tmp_path, legacy):
    import Main_App.processing.frequency_domain_qc as project_qc

    decision = {"participant_id": "P1", "condition": "A",
                "decision": "exclude_participant", "finding_fingerprint": "old-decision",
                "evidence": {**legacy, "value_uv": 300.0}}
    monkeypatch.setattr(project_qc, "resolve_frequency_qc_coverage_decisions", lambda _root:
                        SimpleNamespace(review_complete=True, decision_fingerprint="current",
                                        reviewed_decisions=(decision,)))
    monkeypatch.setattr(project_qc, "load_current_frequency_qc_review_evidence", lambda _root: {
        "ordinary_findings": [{**legacy, "finding_fingerprint": "unreviewed-old"}],
        "cohort_findings": [{**legacy, "finding_fingerprint": "old-cohort"}],
        "reconfirmation_findings": [{**legacy, "finding_fingerprint": "old-reconfirmation"}],
        "technical_statuses": [{**legacy, "status": "unavailable"}],
        "screening_status": "performed",
    })
    report = load_shared_frequency_qc_review(
        project_root=tmp_path, subjects=["P1"], conditions_all=["A"],
        rois_all={"Right OT": ["O2"]},
    )
    assert report.participants == []
    assert report.excluded_pids == set()
    assert report.screened_rois == []
    assert report.technical_statuses == ()


def test_managed_stats_still_requires_exact_electrode_decision(monkeypatch, tmp_path):
    import Main_App.processing.frequency_domain_qc as project_qc

    monkeypatch.setattr(project_qc, "resolve_frequency_qc_coverage_decisions", lambda _root:
                        SimpleNamespace(review_complete=True, decision_fingerprint="current",
                                        reviewed_decisions=()))
    monkeypatch.setattr(project_qc, "load_current_frequency_qc_review_evidence", lambda _root: {
        "ordinary_findings": [{"finding_type": "absolute_electrode_summed_bca",
                               "electrode": "O2", "finding_fingerprint": "unreviewed"}],
    })
    with pytest.raises(RuntimeError, match="exact reviewed decision"):
        load_shared_frequency_qc_review(project_root=tmp_path, subjects=["P1"],
                                       conditions_all=["A"], rois_all={})


@pytest.mark.parametrize("filename", ["stats_workers.py", "multigroup_workers.py"])
def test_projectless_worker_cannot_reuse_cached_roi_qc_report(filename):
    import ast
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "src/Tools/Stats/workers" / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # Worker adapters must not load old ROI reports out of qc_state. Their only
    # report writes are the fresh shared-electrode or not-performed receipt.
    report_reads = [node for node in ast.walk(tree) if
                    isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
                    and isinstance(node.value, ast.Name) and node.value.id == "qc_state"
                    and isinstance(node.slice, ast.Constant) and node.slice.value == "report"]
    get_report_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                        and isinstance(node.func.value, ast.Name) and node.func.value.id == "qc_state"
                        and node.args and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "report"]
    assert not report_reads
    assert not get_report_calls


def test_retired_roi_receipt_preserves_nonfinite_dv_integrity():
    from Tools.Stats.qc.stats_outlier_exclusion import (
        apply_hard_dv_exclusion, build_outlier_summary_text, merge_exclusion_reports,
    )

    qc_report = run_qc_exclusion(subjects=["P1", "P2"], subject_data={},
        conditions_all=["A"], rois_all={"R": ["O1"]}, base_freq=6.0)
    frame = pd.DataFrame({"subject": ["P1", "P2"], "condition": ["A", "A"],
                          "roi": ["R", "R"], "value": [float("nan"), 300.0]})
    _filtered, dv_report = apply_hard_dv_exclusion(frame, 50.0)
    combined = merge_exclusion_reports(dv_report, qc_report)
    assert combined.summary.n_subjects_required_excluded == 1
    assert "no ROI screen was performed" in build_outlier_summary_text(combined)



def test_stats_startup_ignores_malformed_retired_roi_thresholds():
    import ast
    from pathlib import Path

    ui = Path(__file__).resolve().parents[3] / "src/Tools/Stats/ui"
    tree = ast.parse((ui / "stats_window_exclusions.py").read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                  and node.name == "_get_qc_exclusion_payload")
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "isolated_qc_payload", "exec"), namespace)
    historical = SimpleNamespace(qc_warn_threshold="broken", qc_critical_threshold=None,
        qc_warn_abs_floor_sumabs={}, qc_critical_abs_floor_sumabs=[],
        qc_warn_abs_floor_maxabs="invalid", qc_critical_abs_floor_maxabs=-1)
    assert namespace["_get_qc_exclusion_payload"](historical) == {}
    pipeline = ast.parse((ui / "stats_window_pipeline.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.Attribute) and node.attr == "_get_qc_settings"
                   for node in ast.walk(pipeline))
