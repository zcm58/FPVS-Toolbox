from __future__ import annotations

import json

import pandas as pd
import pytest

from Main_App.processing import frequency_domain_qc as frequency_qc
from Main_App.processing import full_fft_provenance
from Main_App.processing.frequency_domain_qc import (
    DECISION_EXCLUDE_CONDITION_ELECTRODE,
    DECISION_RETAIN,
    WARNING_REASON_UNUSUAL_VALUES,
    active_frequency_domain_exclusions,
    apply_frequency_domain_qc_decision,
    clear_manual_frequency_domain_participant_exclusions,
    load_current_frequency_qc_review_evidence,
    mark_frequency_domain_outputs_current,
    resolve_frequency_qc_coverage_decisions,
    run_frequency_domain_qc_review,
    sync_frequency_domain_qc_automatic_state,
)
from Main_App.processing.spectral_eligibility import resolve_spectral_eligibility
from Main_App.projects.project import Project
from Main_App.projects.frequency_protocol import (
    EXPECTED_CYCLES_SOURCE_MANUAL,
    FrequencyProtocol,
)
from Main_App.projects.preprocessing_settings import (
    FIXED_HARMONIC_SELECTION_PROFILE,
    HARMONIC_SELECTION_PROFILE_VERSION,
)
from Tools.Stats.analysis.dv_policy_settings import FIXED_PREDEFINED_POLICY_NAME


@pytest.fixture(autouse=True)
def _current_workbook_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_workbook_geometry",
        lambda _root, *, dataset_index=None: {},
    )
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_full_fft_provenance",
        lambda _root, *, dataset_index=None: object(),
    )


def test_frequency_domain_qc_is_review_only_and_reuses_explicit_retain(tmp_path):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)

    assert report["review_required"] is True
    assert report["review_reused"] is False
    assert report["auto_participant_exclusions"] == []
    assert report["auto_participant_electrode_exclusions"] == []
    assert report["flags"][0]["severity"] == "extreme"

    apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        review_decisions=_decisions(report, DECISION_RETAIN),
    )
    exclusions = active_frequency_domain_exclusions(project.project_root)
    assert exclusions.auto_excluded_electrodes_by_participant == {}
    assert exclusions.excluded_electrodes_by_participant_condition == {}
    assert exclusions.manual_excluded_participants == frozenset()
    assert exclusions.downstream_outputs_stale is True

    reviewed = run_frequency_domain_qc_review(project)
    assert reviewed["review_required"] is False
    assert reviewed["review_reused"] is True
    assert (project.project_root / "Quality Check" / "Frequency_Domain_QC_Review.txt").is_file()


def test_frequency_domain_qc_clear_manual_marks_outputs_stale(tmp_path):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        review_decisions=_decisions(report, DECISION_RETAIN),
        manual_participant_reasons={"P1": WARNING_REASON_UNUSUAL_VALUES},
    )

    cleared = clear_manual_frequency_domain_participant_exclusions(
        project.project_root,
        ["P1"],
    )

    assert cleared == ["P1"]
    exclusions = active_frequency_domain_exclusions(project.project_root)
    assert exclusions.manual_excluded_participants == frozenset()
    assert exclusions.downstream_outputs_stale is True


def test_frequency_domain_qc_sync_clears_stale_automatic_exclusions(tmp_path):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        review_decisions=_decisions(report, DECISION_RETAIN),
    )
    mark_frequency_domain_outputs_current(project.project_root)

    _write_bca_workbook(
        project.project_root / "1 - Excel Data Files" / "CondA" / "P1_CondA_Results.xlsx",
        {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)},
    )
    clean_report = run_frequency_domain_qc_review(project)

    assert clean_report["review_required"] is False
    assert clean_report["auto_participant_electrode_exclusions"] == []

    synced = sync_frequency_domain_qc_automatic_state(
        project.project_root,
        clean_report,
    )

    exclusions = active_frequency_domain_exclusions(project.project_root)
    assert exclusions.auto_excluded_electrodes_by_participant == {}
    assert exclusions.auto_excluded_participants == frozenset()
    assert exclusions.downstream_outputs_stale is False
    assert synced["review_evidence"]["version"] == (
        "frequency_qc_review_evidence_v1"
    )
    assert synced["last_review"]["evidence_fingerprint"] == synced[
        "review_evidence"
    ]["evidence_fingerprint"]
    assert load_current_frequency_qc_review_evidence(
        project.project_root
    ) == synced["review_evidence"]


def test_condition_electrode_decision_does_not_widen_to_other_condition(tmp_path):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        review_decisions=_decisions(
            report,
            DECISION_EXCLUDE_CONDITION_ELECTRODE,
            reason="Reviewed outcome-informed exclusion",
        ),
    )
    exclusions = active_frequency_domain_exclusions(project.project_root)
    assert exclusions.excluded_electrodes_by_participant_condition == {
        ("P1", "CondA"): frozenset({"O2"})
    }
    assert exclusions.auto_excluded_electrodes_by_participant == {}


def test_review_evidence_is_versioned_complete_and_current(tmp_path) -> None:
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)

    state = apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        review_decisions=_decisions(report, DECISION_RETAIN),
    )

    evidence = state["review_evidence"]
    assert evidence["version"] == "frequency_qc_review_evidence_v1"
    assert evidence["analysis_fingerprint"] == report["analysis_fingerprint"]
    assert evidence["ordinary_findings"] == report["flags"]
    assert evidence["cohort_findings"] == report["cohort_relative_flags"]
    assert evidence["cohort_rows"] == report["cohort_relative_rows"]
    assert evidence["technical_statuses"]
    assert evidence["frequency_protocol_fingerprint"]
    assert evidence["harmonic_selection_fingerprint"]
    assert evidence["roi_definition_fingerprint"]
    assert evidence["cohort_fingerprint"]
    assert evidence["source_fingerprint"]
    assert evidence["evidence_fingerprint"] == state["last_review"][
        "evidence_fingerprint"
    ]
    assert resolve_frequency_qc_coverage_decisions(
        project.project_root
    ).review_complete
    assert load_current_frequency_qc_review_evidence(
        project.project_root
    ) == evidence


@pytest.mark.parametrize(
    "mutation",
    (
        "delete_decision",
        "tamper_decision",
        "delete_manual_participant",
        "tamper_manual_participant",
    ),
)
def test_coverage_resolver_rejects_changed_decision_state(
    tmp_path,
    mutation: str,
) -> None:
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        review_decisions=_decisions(report, DECISION_RETAIN),
        manual_participant_reasons={
            "P2": "Reviewed whole-participant exclusion"
        },
    )
    manifest = json.loads(
        (project.project_root / "project.json").read_text(encoding="utf-8")
    )
    state = manifest["tools"]["frequency_domain_qc"]
    if mutation == "delete_decision":
        state["review_decisions"].pop()
    elif mutation == "tamper_decision":
        state["review_decisions"][0]["participant_id"] = "P9"
    elif mutation == "delete_manual_participant":
        state["manual_participant_exclusions"].clear()
    else:
        state["manual_participant_exclusions"][0]["reason"] = "Tampered reason"
    (project.project_root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    decisions = resolve_frequency_qc_coverage_decisions(project.project_root)

    assert decisions.review_complete is False
    assert decisions.decision_fingerprint == ""
    assert decisions.reviewed_decisions == ()
    assert decisions.excluded_participants == frozenset()
    with pytest.raises(RuntimeError, match="missing, stale, or tampered"):
        load_current_frequency_qc_review_evidence(project.project_root)


@pytest.mark.parametrize("mutation", ("tamper_evidence", "change_source"))
def test_stale_or_tampered_review_evidence_fails_closed(
    tmp_path,
    mutation: str,
) -> None:
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        review_decisions=_decisions(report, DECISION_RETAIN),
    )
    if mutation == "tamper_evidence":
        manifest_path = project.project_root / "project.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["tools"]["frequency_domain_qc"]["review_evidence"][
            "screening_status"
        ] = "tampered"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    else:
        workbook = (
            project.project_root
            / "1 - Excel Data Files"
            / "CondA"
            / "P1_CondA_Results.xlsx"
        )
        workbook.write_bytes(workbook.read_bytes() + b"changed")

    assert not resolve_frequency_qc_coverage_decisions(
        project.project_root
    ).review_complete
    with pytest.raises(RuntimeError, match="missing, stale, or tampered"):
        load_current_frequency_qc_review_evidence(project.project_root)


def test_reconfirmed_exclusion_changed_to_retain_clears_old_reason(tmp_path) -> None:
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        review_decisions=_decisions(
            report,
            DECISION_EXCLUDE_CONDITION_ELECTRODE,
            reason="Prior exclusion reason",
        ),
    )
    _write_bca_workbook(
        project.project_root
        / "1 - Excel Data Files"
        / "CondA"
        / "P1_CondA_Results.xlsx",
        {"O2": (151.0, 151.0), "PZ": (1.0, 1.0)},
    )
    changed = run_frequency_domain_qc_review(project)
    assert changed["reconfirmation_findings"]

    state = apply_frequency_domain_qc_decision(
        project.project_root,
        changed,
        review_decisions=_decisions(
            changed,
            DECISION_RETAIN,
            reason="Prior exclusion reason must not survive",
        ),
    )

    assert state["review_decisions"]
    assert {row["decision"] for row in state["review_decisions"]} == {
        DECISION_RETAIN
    }
    assert {row["reason"] for row in state["review_decisions"]} == {""}
    assert (
        active_frequency_domain_exclusions(
            project.project_root
        ).excluded_electrodes_by_participant_condition
        == {}
    )


def test_independent_qc_is_exact_context_and_changes_finding_identity() -> None:
    cell = {
        "fingerprint": "cell-fingerprint",
        "source_evidence": {
            "fingerprint": "source-evidence-fingerprint",
            "expected_scalp_channels": ["O1", "O2"],
            "observed_scalp_channels": ["O1", "O2"],
            "successfully_interpolated_channels": ["O2"],
        },
        "roi_memberships": [],
    }
    processing = {
        "interpolation_burden": {
            "status": "available",
            "fingerprint": "burden-fingerprint",
            "numerator": 1,
            "denominator": 2,
            "percentage": 50.0,
            "requires_review": True,
            "successfully_interpolated_channels": ["O2"],
        },
        "kurtosis_evidence_status": "current",
        "kurtosis_qc_evidence": {
            "fingerprint": "kurtosis-fingerprint",
            "channels": [{"channel": "O2", "exceeds_threshold": True}],
        },
        "kurtosis_decision_plan_status": "current",
        "kurtosis_decision_plan": {
            "fingerprint": "plan-fingerprint",
            "channel_decisions": [
                {"channel": "O2", "decision": "review_required"}
            ],
        },
    }
    context = frequency_qc._IndependentQcContext(
        source_identity={"status": "current", "fingerprint": "source-fingerprint"},
        cells={("p1__v1", "faces"): cell},
        processing_entries={"p1__v1": processing},
    )
    finding = {
        "finding_type": "absolute_electrode_summed_bca",
        "participant_id": "P1",
        "recording_id": "P1__V1",
        "condition": "Faces",
        "electrode": "O2",
        "summed_bca_uv": 300.0,
        "abs_summed_bca_uv": 300.0,
    }

    frequency_qc._attach_independent_qc_evidence(finding, context)
    first_fingerprint = frequency_qc._frequency_qc_finding_fingerprint(finding)

    assert finding["independent_qc_status"] == "available"
    assert finding["independent_qc_authority"] == "context_only"
    coverage, burden, kurtosis = finding["independent_qc"]
    assert coverage["in_retained_scalp"] is True
    assert coverage["observed_in_source"] is True
    assert coverage["successfully_interpolated"] is True
    assert burden["percentage"] == 50.0
    assert burden["target_interpolated_channels"] == ["O2"]
    assert kurtosis["channels"] == [
        {"channel": "O2", "exceeds_threshold": True}
    ]
    assert kurtosis["channel_decisions"] == [
        {"channel": "O2", "decision": "review_required"}
    ]
    assert all(row["authority"] == "context_only" for row in finding["independent_qc"])

    changed_processing = dict(processing)
    changed_burden = dict(processing["interpolation_burden"])
    changed_burden["percentage"] = 25.0
    changed_processing["interpolation_burden"] = changed_burden
    changed_context = frequency_qc._IndependentQcContext(
        source_identity=context.source_identity,
        cells=context.cells,
        processing_entries={"p1__v1": changed_processing},
    )
    changed_finding = {
        key: value
        for key, value in finding.items()
        if not key.startswith("independent_qc")
    }
    frequency_qc._attach_independent_qc_evidence(
        changed_finding,
        changed_context,
    )

    assert changed_finding["independent_qc_fingerprint"] != finding[
        "independent_qc_fingerprint"
    ]
    assert frequency_qc._frequency_qc_finding_fingerprint(
        changed_finding
    ) != first_fingerprint


def test_missing_exact_independent_qc_cell_is_not_reported_as_current() -> None:
    context = frequency_qc._IndependentQcContext(
        source_identity={
            "status": "current",
            "fingerprint": "source-fingerprint",
        },
        cells={},
        processing_entries={},
    )
    finding = {
        "finding_type": "absolute_electrode_summed_bca",
        "participant_id": "P1",
        "recording_id": "P1__V1",
        "condition": "Faces",
        "electrode": "O2",
        "summed_bca_uv": 300.0,
        "abs_summed_bca_uv": 300.0,
    }

    frequency_qc._attach_independent_qc_evidence(finding, context)

    assert finding["independent_qc_status"] == "current_source_cell_missing"
    assert finding["independent_qc_source_status"] == "current"
    assert finding["independent_qc"] == [
        {
            "source": "qc21_pre_review_coverage",
            "status": "current_source_cell_missing",
            "source_status": "current",
            "authority": "context_only",
            "reason": "",
            "source_fingerprint": "source-fingerprint",
        }
    ]


def _make_project(tmp_path):
    root = tmp_path / "Project"
    project = Project.load(root)
    project.event_map = {"CondA": 1, "CondB": 2}
    payload = dict(project.preprocessing)
    payload.update(
        {
            "harmonic_selection_policy": FIXED_PREDEFINED_POLICY_NAME,
            "harmonic_selection_profile": FIXED_HARMONIC_SELECTION_PROFILE,
            "harmonic_selection_profile_version": HARMONIC_SELECTION_PROFILE_VERSION,
            "fixed_harmonic_frequencies_hz": "1.2, 2.4",
            "fixed_harmonic_input_mode": "frequency_list",
            "fixed_harmonic_auto_exclude_base": True,
        }
    )
    project.update_preprocessing(payload)
    project.update_frequency_protocol(
        FrequencyProtocol.from_recurrence(
            6,
            5,
            expected_analyzed_oddball_cycles=12,
            expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
        )
    )
    project.save()

    _write_bca_workbook(
        root / "1 - Excel Data Files" / "CondA" / "P1_CondA_Results.xlsx",
        {"O2": (150.0, 150.0), "PZ": (1.0, 1.0)},
    )
    _write_bca_workbook(
        root / "1 - Excel Data Files" / "CondB" / "P1_CondB_Results.xlsx",
        {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)},
    )
    _write_bca_workbook(
        root / "1 - Excel Data Files" / "CondA" / "P2_CondA_Results.xlsx",
        {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)},
    )
    _write_bca_workbook(
        root / "1 - Excel Data Files" / "CondB" / "P2_CondB_Results.xlsx",
        {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)},
    )
    return project


def _write_bca_workbook(path, electrode_values):
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {
                "Electrode": electrode,
                "1.2000_Hz": values[0],
                "2.4000_Hz": values[1],
            }
            for electrode, values in electrode_values.items()
        ]
    )
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, sheet_name="BCA (uV)", index=False)
        eligibility = resolve_spectral_eligibility(
            protocol=FrequencyProtocol.from_recurrence(
                6,
                5,
                expected_analyzed_oddball_cycles=12,
                expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
            ),
            sampling_rate_hz=128,
            analyzed_samples=1280,
            requested_high_pass_hz=0.1,
            requested_low_pass_hz=50,
            applied_high_pass_hz=0.1,
            applied_low_pass_hz=50,
        )
        pd.DataFrame(eligibility.to_rows()).to_excel(
            writer,
            sheet_name="Spectral Eligibility",
            index=False,
        )


def _decisions(report, decision: str, *, reason: str = ""):
    return {
        str(item["finding_fingerprint"]): {
            "decision": decision,
            "reason": reason,
        }
        for item in report["review_findings"]
    }
