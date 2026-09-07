from __future__ import annotations

import json

import pandas as pd
import pytest

from Main_App.processing import frequency_domain_qc as frequency_qc
from Main_App.processing import full_fft_provenance
from Main_App.processing.frequency_domain_qc import (
    DECISION_EXCLUDE_CONDITION_ELECTRODE,
    DECISION_EXCLUDE_CONDITION,
    DECISION_INTERPOLATE_CONDITION_ELECTRODE,
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


@pytest.mark.parametrize("native", [False, True])
def test_frequency_domain_qc_is_review_only_and_reuses_explicit_retain(tmp_path, native):
    project = _make_project(tmp_path)
    if native:
        from Main_App.Shared.post_process_excel import write_results_workbook

        for workbook in (project.project_root / "1 - Excel Data Files").rglob("*.xlsx"):
            write_results_workbook(
                str(workbook.with_suffix(".fpvs")), pd.read_excel(workbook, sheet_name=None),
            )
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


def test_roi_definitions_do_not_generate_findings_or_reopen_unchanged_electrode_review(tmp_path, monkeypatch):
    from Main_App.processing import harmonic_selection_qc

    project = _make_project(tmp_path)
    for participant in ("P3", "P4", "P5"):
        for condition in ("CondA", "CondB"):
            _write_bca_workbook(
                project.project_root / "1 - Excel Data Files" / condition
                / f"{participant}_{condition}_Results.xlsx",
                {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)},
            )
    current_rois = {"Central": ["PZ"], "Test ROI": ["O2"]}
    monkeypatch.setattr(
        harmonic_selection_qc, "load_rois_from_settings",
        lambda: {name: list(channels) for name, channels in current_rois.items()},
    )
    original = run_frequency_domain_qc_review(project)
    assert original["flags"]
    assert original["cohort_relative_rows"] == []
    assert original["cohort_relative_flags"] == []
    assert all(row.get("electrode") for row in original["review_findings"])
    reviewed_state = apply_frequency_domain_qc_decision(
        project.project_root, original,
        review_decisions=_decisions(original, DECISION_RETAIN),
    )
    previous_history = reviewed_state["review_history"]
    del current_rois["Test ROI"]
    current_rois["Missing electrodes"] = ["CZ"]
    current = run_frequency_domain_qc_review(project)
    assert current["analysis_fingerprint"] == original["analysis_fingerprint"]
    assert current["source_fingerprint"] == original["source_fingerprint"]
    assert current["flags"] == original["flags"]
    assert current["review_reused"] is True
    assert current["review_required"] is False
    assert current["cohort_relative_rows"] == []
    assert current["cohort_relative_flags"] == []
    assert not any(frequency_qc.is_roi_frequency_qc_entry(row)
                   for row in frequency_qc._technical_status_rows(current))
    assert frequency_qc.load_frequency_domain_qc_state(project.project_root)[
        "review_history"
    ] == previous_history


def test_roi_only_outlier_below_electrode_warning_does_not_prompt(tmp_path, monkeypatch):
    from Main_App.processing import harmonic_selection_qc

    project = _make_project(tmp_path)
    monkeypatch.setattr(
        harmonic_selection_qc, "load_rois_from_settings",
        lambda: {"Occipital": ["O2"]},
    )
    # P1 would cross the retired ROI peak floor (3 uV) and summed floor
    # (6 uV), with zero cohort spread among the four other participants.
    # Every electrode remains below the unchanged 10 uV summed warning.
    for participant in ("P1", "P2", "P3", "P4", "P5"):
        amplitude = 3.0 if participant == "P1" else 0.1
        for condition in ("CondA", "CondB"):
            _write_bca_workbook(
                project.project_root / "1 - Excel Data Files" / condition
                / f"{participant}_{condition}_Results.xlsx",
                {"O2": (amplitude, amplitude), "PZ": (0.1, 0.1)},
            )

    report = run_frequency_domain_qc_review(project)

    assert report["screening_enabled"] is True
    assert len(report["subjects"]) == 5
    assert report["thresholds"]["warning_summed_bca_uv"] == 10.0
    assert report["flags"] == []
    assert report["cohort_relative_flags"] == []
    assert report["cohort_relative_rows"] == []
    assert report["review_findings"] == []
    assert report["review_required"] is False
    assert report["technical_integrity_failures"] == []
    assert report["unavailable_by_method"] == []
    assert report["qc_complete"] is True


def test_frequency_domain_qc_stage_progress_preserves_report(tmp_path, monkeypatch, caplog):
    project = _make_project(tmp_path)
    monkeypatch.setattr(frequency_qc, "_now_utc_iso", lambda: "2026-09-06T00:00:00Z")
    expected = run_frequency_domain_qc_review(project)
    messages = []
    with caplog.at_level("INFO", logger=frequency_qc.__name__):
        observed = run_frequency_domain_qc_review(project, log_func=messages.append)
    assert observed == expected
    assert [message for message in messages if message.startswith("Frequency-domain QC: ")] == [
        "Frequency-domain QC: Checking project inputs…",
        "Frequency-domain QC: Checking preprocessing evidence…",
        "Frequency-domain QC: Preparing candidate harmonics…",
        "Frequency-domain QC: Checking electrode amplitudes…",
        "Frequency-domain QC: Preparing review findings…",
    ]
    stages = [record for record in caplog.records
              if record.message.startswith("frequency_domain_qc_stage_complete ")]
    assert [record.stage for record in stages] == [
        "canonical_inputs", "independent_evidence", "provisional_harmonics",
        "absolute_screening", "report_integrity",
    ]
    assert all(record.elapsed_s >= 0 for record in stages)
    assert all(f"stage={record.stage} elapsed_s=" in record.message for record in stages)
    starts = [record for record in caplog.records
              if record.message.startswith("frequency_domain_qc_stage_started ")]
    assert [record.stage for record in starts] == [record.stage for record in stages]


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
    project.update_experimental_qc_settings(
        project.experimental_qc_settings.with_condition_specific_interpolation_enabled(True)
    )
    project.save()
    report = run_frequency_domain_qc_review(project)
    from Main_App.processing.processing_ledger import save_ledger

    raw_path = project.project_root / "P1.bdf"
    raw_path.write_bytes(b"reviewed source recording identity")
    stat = raw_path.stat()
    save_ledger(project.project_root, {"entries": {"P1": {
        "raw_file": str(raw_path), "raw_size": stat.st_size,
        "raw_mtime_ns": stat.st_mtime_ns,
    }}})
    decisions = _decisions(report, DECISION_INTERPOLATE_CONDITION_ELECTRODE)
    for decision in decisions.values():
        decision["artifact_confirmed"] = True
    apply_frequency_domain_qc_decision(
        project.project_root,
        report,
        review_decisions=decisions,
    )
    exclusions = active_frequency_domain_exclusions(project.project_root)
    assert exclusions.excluded_electrodes_by_participant_condition == {}
    assert exclusions.auto_excluded_electrodes_by_participant == {}
    manifest = json.loads((project.project_root / "project.json").read_text())
    assert manifest["tools"]["condition_electrode_interpolation"]["requests"] == {
        "P1": {"CondA": ["O2"]},
    }
    with pytest.raises(RuntimeError, match="[Pp]ending|[Ii]nterpolation|repair"):
        run_frequency_domain_qc_review(project)


def test_repair_rechecks_saved_toggle_before_persisting(tmp_path):
    project = _make_project(tmp_path)
    project.update_experimental_qc_settings(
        project.experimental_qc_settings.with_condition_specific_interpolation_enabled(True)
    )
    project.save()
    report = run_frequency_domain_qc_review(project)
    choices = _decisions(report, DECISION_INTERPOLATE_CONDITION_ELECTRODE)
    for choice in choices.values():
        choice["artifact_confirmed"] = True
    project.update_experimental_qc_settings(
        project.experimental_qc_settings.with_condition_specific_interpolation_enabled(False)
    )
    project.save()
    before = (project.project_root / "project.json").read_bytes()
    with pytest.raises(ValueError, match="was disabled"):
        apply_frequency_domain_qc_decision(project.project_root, report, review_decisions=choices)
    assert (project.project_root / "project.json").read_bytes() == before


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
    assert "roi_definition_fingerprint" not in evidence
    assert "cohort_fingerprint" not in evidence
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
            DECISION_RETAIN,
            reason="Prior exclusion reason",
        ),
    )
    # Simulate a valid row saved by the retired electrode-exclusion workflow.
    manifest_path = project.project_root / "project.json"
    manifest = json.loads(manifest_path.read_text())
    legacy_rows = manifest["tools"]["frequency_domain_qc"]["review_decisions"]
    for row in legacy_rows:
        row["decision"] = DECISION_EXCLUDE_CONDITION_ELECTRODE
        row["reason"] = "Prior exclusion reason"
        row["decision_fingerprint"] = frequency_qc._hash_payload({
            key: value for key, value in row.items()
            if key not in {"decision_fingerprint", "reviewed_at"}
        })
    manifest_path.write_text(json.dumps(manifest))
    assert frequency_qc.is_frequency_domain_output_stale(project.project_root)
    assert active_frequency_domain_exclusions(
        project.project_root
    ).excluded_electrodes_by_participant_condition == {}
    same_inputs = run_frequency_domain_qc_review(project)
    assert same_inputs["review_required"] is True
    assert same_inputs["reconfirmation_findings"]
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
    assert {row["reason"] for row in state["review_decisions"]} == {"No reason provided"}
    assert {row["decision_fingerprint"] for row in state["retired_review_decisions"]} == {
        row["decision_fingerprint"] for row in legacy_rows
    }
    assert (
        active_frequency_domain_exclusions(
            project.project_root
        ).excluded_electrodes_by_participant_condition
        == {}
    )


@pytest.mark.parametrize("reason", [None, "", " \t"])
def test_blank_frequency_comments_survive_review_reload_without_changing_scope(tmp_path, reason):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    decisions = _decisions(report, DECISION_EXCLUDE_CONDITION, reason=reason)
    state = apply_frequency_domain_qc_decision(
        project.project_root, report, review_decisions=decisions,
        manual_participant_reasons={"P2": reason},
    )
    assert {row["reason"] for row in state["review_decisions"]} == {"No reason provided"}
    assert state["manual_participant_exclusions"][0]["reason"] == "No reason provided"
    exclusions = active_frequency_domain_exclusions(project.project_root)
    assert exclusions.manual_excluded_participants == frozenset({"P2"})
    assert exclusions.excluded_electrodes_by_participant_condition == {}
    assert exclusions.excluded_participant_conditions == {("P1", "CondA")}
    assert load_current_frequency_qc_review_evidence(project.project_root) == state["review_evidence"]
    with pytest.raises(ValueError, match="explicit decision"):
        frequency_qc.validate_frequency_domain_qc_review_decisions(report, {})


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


def test_condition_exclusion_survives_review_resume_and_is_reported_as_excluded(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    context = frequency_qc._IndependentQcContext(
        source_identity={"status": "current", "fingerprint": "source-fingerprint"},
        cells={
            (pid.casefold(), condition.casefold()): {
                "participant_id": pid, "recording_id": pid,
                "condition_label": condition,
                "source_evidence": {"expected_scalp_channels": ["O2", "Pz"]},
            }
            for pid in ("P1", "P2") for condition in ("CondA", "CondB")
        },
        processing_entries={},
    )
    monkeypatch.setattr(frequency_qc, "_load_independent_qc_context", lambda _root: context)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project.project_root, report,
        review_decisions=_decisions(report, frequency_qc.DECISION_EXCLUDE_CONDITION),
    )
    source = project.project_root / "1 - Excel Data Files" / "CondA" / "P1_CondA_Results.xlsx"
    original_bytes = source.read_bytes()
    original_provisional = frequency_qc._provisional_harmonics
    passed_inputs = []

    def capture_inputs(**kwargs):
        passed_inputs.append(kwargs)
        return original_provisional(**kwargs)

    monkeypatch.setattr(frequency_qc, "_provisional_harmonics", capture_inputs)
    resumed = run_frequency_domain_qc_review(project)

    assert len(passed_inputs) == 1
    inputs = passed_inputs[0]
    assert set(inputs["subject_data"]["P1"]) == {"CondB"}
    assert inputs["expected_scalp_channels_by_subject_condition"] == {
        ("p1", "condb"): ("O2", "Pz"),
        ("p2", "conda"): ("O2", "Pz"),
        ("p2", "condb"): ("O2", "Pz"),
    }
    assert resumed["cohort_relative_rows"] == []
    assert source.read_bytes() == original_bytes
    assert resumed["technical_integrity_failed"] is False
    # A changed cohort can require the existing bounded reconfirmation, but
    # accepting that same scoped exclusion must settle instead of looping.
    assert resumed["review_required"] is True
    apply_frequency_domain_qc_decision(
        project.project_root, resumed,
        review_decisions=_decisions(resumed, frequency_qc.DECISION_EXCLUDE_CONDITION),
    )
    settled = run_frequency_domain_qc_review(project)
    assert settled["review_required"] is False
    assert settled["qc_complete"] is True
    assert active_frequency_domain_exclusions(project.project_root).excluded_participant_conditions == frozenset({("P1", "CondA")})
    sync_frequency_domain_qc_automatic_state(project.project_root, settled)
    final_decisions = resolve_frequency_qc_coverage_decisions(project.project_root)
    assert final_decisions.review_complete is True
    assert final_decisions.excluded_participant_conditions == frozenset({("P1", "CondA")})


@pytest.mark.parametrize("identity", ["P1", "P1__VISIT_1"])
def test_expected_sources_omit_only_explicit_condition_and_preserve_other_visit(identity):
    context = frequency_qc._IndependentQcContext(
        source_identity={"status": "current"},
        cells={
            (identity.casefold(), "faces"): {"source_evidence": {"expected_scalp_channels": ["Oz"]}},
            (identity.casefold(), "objects"): {"source_evidence": {"expected_scalp_channels": ["Oz"]}},
            ("p1__visit_2", "faces"): {"source_evidence": {"expected_scalp_channels": ["Oz"]}},
            ("p2", "faces"): {"source_evidence": {"expected_scalp_channels": ["Oz"]}},
        },
        processing_entries={},
    )
    original = frequency_qc._expected_scalp_channels_by_subject_condition(context)
    current = frequency_qc._expected_scalp_channels_by_subject_condition(
        context, excluded_conditions={(identity, "Faces")},
    )
    assert original is not None and current is not None
    assert current == {key: channels for key, channels in original.items()
                       if key != (identity.casefold(), "faces")}
    # No file discovery/intersection is involved: unexcluded cells remain
    # required even when their file is missing from a supplied dataset.
    assert current[("p2", "faces")] == ("Oz",)
    assert frequency_qc._expected_scalp_channels_by_subject_condition(context) == original


@pytest.mark.parametrize("marker", [
    {"roi": "Occipital"},
    {"roi": "Occipital", "electrode": "O2"},
    {"decision_scope": "recording_condition_roi"},
    {"finding_type": "cohort_relative_summed_bca_context"},
    {"metric": "sum_abs_roi_mean"},
    {"evidence": {"metric": "peak_abs_roi_mean"}},
])
def test_retired_roi_targets_are_detected_even_without_complete_identity(marker):
    assert frequency_qc.is_roi_frequency_qc_entry(marker)
    assert not frequency_qc.is_roi_frequency_qc_entry({
        "electrode": "O2", "evidence": {
            "finding_type": "cohort_relative_summed_bca_context",
        },
    })


def test_mixed_legacy_report_accepts_only_electrode_decisions(tmp_path):
    report = run_frequency_domain_qc_review(_make_project(tmp_path))
    electrode_choices = _decisions(report, DECISION_RETAIN)
    roi_finding = {
        "finding_fingerprint": "old-roi-finding", "participant_id": "P1",
        "condition": "CondA", "roi": "Occipital",
    }
    mixed = {**report, "review_findings": [*report["review_findings"], roi_finding]}
    assert frequency_qc.validate_frequency_domain_qc_review_decisions(
        mixed, electrode_choices,
    ) == frequency_qc.validate_frequency_domain_qc_review_decisions(report, electrode_choices)
    with pytest.raises(ValueError, match="ROI-level summed-BCA review"):
        frequency_qc.validate_frequency_domain_qc_review_decisions(
            mixed, {**electrode_choices, "old-roi-finding": DECISION_RETAIN},
        )


@pytest.mark.parametrize("action", [
    DECISION_RETAIN, DECISION_EXCLUDE_CONDITION,
    frequency_qc.DECISION_EXCLUDE_RECORDING,
    frequency_qc.DECISION_EXCLUDE_PARTICIPANT,
    DECISION_EXCLUDE_CONDITION_ELECTRODE,
    DECISION_INTERPOLATE_CONDITION_ELECTRODE,
])
def test_legacy_roi_decisions_are_inactive_and_archived_without_reconfirmation(tmp_path, action):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    state = apply_frequency_domain_qc_decision(
        project.project_root, report,
        review_decisions=_decisions(report, DECISION_RETAIN),
    )
    roi_decision = dict(state["review_decisions"][0])
    roi_decision.pop("decision_fingerprint")
    reviewed_at = roi_decision.pop("reviewed_at", None)
    roi_decision.update({
        "finding_fingerprint": "legacy-roi-finding", "electrode": "",
        "roi": "Occipital", "decision_scope": "participant_condition_roi",
        "decision": action, "recording_id": "P1__VISIT_1",
        "analysis_fingerprint": "legacy-roi-analysis",
    })
    roi_decision["decision_fingerprint"] = frequency_qc._hash_payload(roi_decision)
    if reviewed_at is not None:
        roi_decision["reviewed_at"] = reviewed_at
    state["review_decisions"].append(roi_decision)
    state["downstream_outputs_stale"] = False
    path = project.project_root / "project.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["tools"]["frequency_domain_qc"] = state
    path.write_text(json.dumps(manifest), encoding="utf-8")

    exclusions = active_frequency_domain_exclusions(project.project_root)
    assert not exclusions.excluded_participants
    assert not exclusions.excluded_recordings
    assert not exclusions.excluded_participant_conditions
    assert not exclusions.excluded_recording_conditions
    current = run_frequency_domain_qc_review(project)
    assert current["analysis_fingerprint"] == report["analysis_fingerprint"]
    assert current["current_decision_fingerprint"] == state["last_review"]["decision_fingerprint"]
    assert current["review_required"] is False
    assert current["reconfirmation_findings"] == []
    updated = sync_frequency_domain_qc_automatic_state(project.project_root, current)
    assert roi_decision in updated["retired_review_decisions"]
    assert roi_decision in frequency_qc._superseded_narrow_decisions(
        {**state, "review_complete": False}, current=[],
    )
    assert roi_decision not in updated["review_decisions"]
    assert updated["review_history"] == state["review_history"]
    if action in frequency_qc._BROAD_EXCLUSION_DECISIONS:
        assert updated["downstream_outputs_stale"] is True
    assert resolve_frequency_qc_coverage_decisions(project.project_root).review_complete


@pytest.mark.parametrize("legacy_evidence", [
    {"roi_definition_fingerprint": "old-roi-definitions"},
    {"cohort_fingerprint": "old-roi-cohort"},
    {"cohort_rows": [{"roi": "Occipital", "status": "complete"}]},
    {"technical_statuses": [{"roi": "Occipital", "status": "unavailable"}]},
])
def test_saved_roi_evidence_is_not_current_without_roi_decisions(tmp_path, legacy_evidence):
    project = _make_project(tmp_path)
    report = run_frequency_domain_qc_review(project)
    state = apply_frequency_domain_qc_decision(
        project.project_root, report,
        review_decisions=_decisions(report, DECISION_RETAIN),
    )
    evidence = dict(state["review_evidence"])
    evidence.pop("evidence_fingerprint")
    evidence.update(legacy_evidence)
    evidence["evidence_fingerprint"] = frequency_qc._hash_payload(evidence)
    state["review_evidence"] = evidence
    state["last_review"]["evidence_fingerprint"] = evidence["evidence_fingerprint"]
    state["method_version"] = "experimental_summed_bca_review_v4"
    assert frequency_qc._validated_review_evidence_from_state(project.project_root, state) is None


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
