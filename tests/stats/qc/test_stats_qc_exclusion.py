from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

import Tools.Stats.qc.stats_qc_exclusion as qc_exclusion
from Tools.Stats.analysis.dv_policies import (
    FIXED_PREDEFINED_POLICY_NAME,
    prepare_summed_bca_data,
)
from Tools.Stats.io import excel_io
from Tools.Stats.qc.stats_qc_exclusion import (
    QC_REASON_MAXABS,
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


def test_qc_exclusion_independent_of_selected_conditions(monkeypatch, tmp_path) -> None:
    paths = {
        name: tmp_path / name
        for name in (
            "P1_A.xlsx",
            "P1_B.xlsx",
            "P2_A.xlsx",
            "P2_B.xlsx",
            "P3_A.xlsx",
            "P3_B.xlsx",
        )
    }
    for name, path in paths.items():
        _write_bca_workbook(path, _make_bca_df(1000.0 if name == "P3_B.xlsx" else 0.1))

    subject_data = {
        "P1": {"A": str(paths["P1_A.xlsx"]), "B": str(paths["P1_B.xlsx"])},
        "P2": {"A": str(paths["P2_A.xlsx"]), "B": str(paths["P2_B.xlsx"])},
        "P3": {"A": str(paths["P3_A.xlsx"]), "B": str(paths["P3_B.xlsx"])},
    }
    conditions_all = ["A", "B"]
    rois = {"Occipital": ["O1", "O2"]}

    def _fail_full_workbook_read(*_args, **_kwargs):
        raise AssertionError("QC should use the selective .xlsx reader")

    selected_electrode_filters: list[set[str] | None] = []
    original_selected_read = qc_exclusion.read_xlsx_sheet_selected_columns

    def _record_selected_read(*args, **kwargs):
        selected_electrode_filters.append(kwargs.get("included_electrodes_upper"))
        return original_selected_read(*args, **kwargs)

    monkeypatch.setattr(excel_io, "safe_read_excel", _fail_full_workbook_read)
    monkeypatch.setattr(
        qc_exclusion,
        "read_xlsx_sheet_selected_columns",
        _record_selected_read,
    )

    report = run_qc_exclusion(
        subjects=list(subject_data.keys()),
        subject_data=subject_data,
        conditions_all=conditions_all,
        rois_all=rois,
        base_freq=6.0,
        warn_threshold=1.0,
        log_func=None,
    )

    assert report.summary.n_subjects_flagged == 1
    assert any(
        QC_REASON_MAXABS in participant.reasons
        for participant in report.participants
        if participant.participant_id == "P3"
    )
    assert selected_electrode_filters
    assert all(
        electrode_filter == {"O1", "O2"}
        for electrode_filter in selected_electrode_filters
    )

    dv_data = prepare_summed_bca_data(
        subjects=list(subject_data.keys()),
        conditions=["A"],
        subject_data=subject_data,
        base_freq=6.0,
        log_func=lambda _m: None,
        rois=rois,
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
    )

    assert dv_data is not None
    assert set(dv_data.keys()) == set(subject_data.keys())
    assert set(dv_data["P1"].keys()) == {"A"}


def test_qc_keeps_full_reader_fallback_for_non_xlsx(
    monkeypatch,
    tmp_path,
) -> None:
    workbook = tmp_path / "legacy_results.xls"
    workbook.write_bytes(b"test placeholder")
    read_calls: list[tuple[str, str, str | None]] = []

    def _fake_read_excel(path, sheet_name, *, index_col=None, use_cache=True):
        _ = use_cache
        read_calls.append((str(path), str(sheet_name), index_col))
        return _make_bca_df(0.1)

    monkeypatch.setattr(excel_io, "safe_read_excel", _fake_read_excel)

    report = run_qc_exclusion(
        subjects=["P1"],
        subject_data={"P1": {"A": str(workbook)}},
        conditions_all=["A"],
        rois_all={"Occipital": ["O1", "O2"]},
        base_freq=6.0,
        log_func=None,
    )

    assert read_calls == [(str(workbook), "BCA (uV)", "Electrode")]
    assert report.summary.n_subjects_before == 1
    assert report.summary.n_subjects_flagged == 0


def test_qc_reports_missing_mapping_without_attempting_a_read(
    monkeypatch,
) -> None:
    messages: list[str] = []

    def _fail_read(*_args, **_kwargs):
        raise AssertionError("No workbook read should be attempted")

    monkeypatch.setattr(excel_io, "safe_read_excel", _fail_read)
    monkeypatch.setattr(
        qc_exclusion,
        "read_xlsx_sheet_header",
        _fail_read,
    )

    report = run_qc_exclusion(
        subjects=["P1"],
        subject_data={"P1": {}},
        conditions_all=["A"],
        rois_all={"Occipital": ["O1", "O2"]},
        base_freq=6.0,
        log_func=messages.append,
    )

    assert any("QC: Missing file for P1 A" in message for message in messages)
    assert report.summary.n_subjects_before == 1
    assert report.summary.n_subjects_flagged == 0


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


def test_managed_stats_reuses_recording_aware_qc17_evidence(monkeypatch, tmp_path) -> None:
    import Main_App.processing.frequency_domain_qc as project_qc

    rows = tuple(
        {
            "recording_id": recording_id,
            "participant_id": "P1",
            "condition": "Faces",
            "roi": "Right OT",
            "decision": "retain",
            "reason": "",
            "finding_fingerprint": f"finding-{recording_id}",
        }
        for recording_id in ("P1__V1", "P1__V2")
    )
    findings = [
        {
            "finding_type": "cohort_relative_summed_bca_context",
            "recording_id": row["recording_id"],
            "participant_id": "P1",
            "condition": "Faces",
            "roi": "Right OT",
            "metric": "sum_abs_roi_mean",
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
            "cohort_findings": findings,
            "ordinary_findings": [],
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
