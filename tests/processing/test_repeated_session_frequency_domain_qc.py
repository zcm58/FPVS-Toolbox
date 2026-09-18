from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from Main_App.processing.frequency_domain_qc import (
    DECISION_EXCLUDE_CONDITION,
    DECISION_EXCLUDE_PARTICIPANT,
    DECISION_EXCLUDE_RECORDING,
    DECISION_RETAIN,
    WARNING_REASON_UNUSUAL_VALUES,
    active_frequency_domain_exclusions,
    apply_frequency_domain_qc_decision,
    filter_frequency_domain_recordings,
    frequency_domain_excluded_electrodes_for_recording,
    load_current_frequency_qc_review_evidence,
    resolve_frequency_qc_coverage_decisions,
    run_frequency_domain_qc_review,
)
from Main_App.processing.spectral_eligibility import resolve_spectral_eligibility
from Main_App.processing.frequency_qc_identity import (
    FrequencyQcReviewIdentityError,
    frequency_qc_review_rows,
    resolve_frequency_qc_recording_decisions,
)
from Main_App.projects import Project, load_project_dataset_index
from Main_App.projects.frequency_protocol import (
    EXPECTED_CYCLES_SOURCE_MANUAL,
    FrequencyProtocol,
)
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_PREDEFINED_POLICY_NAME,
    HARMONIC_PROFILE_FIXED_ID,
)


def test_bad_visit_is_recording_scoped_and_paired_visit_remains_available(
    tmp_path: Path,
) -> None:
    project_root = _write_repeated_project(tmp_path / "Project")
    project = Project.load(project_root)

    report = run_frequency_domain_qc_review(project)

    assert report["identity_scope"] == "recording"
    assert report["auto_participant_exclusions"] == []
    assert report["auto_recording_exclusions"] == []
    assert report["auto_recording_electrode_exclusions"] == []
    assert report["flags"][0]["recording_id"] == "P1__VISIT_1"

    apply_frequency_domain_qc_decision(
        project_root,
        report,
        review_decisions={
            str(item["finding_fingerprint"]): {
                "decision": DECISION_EXCLUDE_RECORDING,
                "reason": WARNING_REASON_UNUSUAL_VALUES,
            }
            for item in report["review_findings"]
        },
        manual_recording_reasons={
            "P1__visit_1": WARNING_REASON_UNUSUAL_VALUES,
        },
    )
    exclusions = active_frequency_domain_exclusions(project_root)

    assert exclusions.excluded_participants == frozenset()
    assert exclusions.manual_excluded_recordings == frozenset({"P1__VISIT_1"})
    assert exclusions.auto_excluded_electrodes_by_recording == {}
    assert frequency_domain_excluded_electrodes_for_recording(
        project_root,
        "p1__visit_1",
    ) == frozenset()

    index = load_project_dataset_index(project_root)
    recording_data = index.recording_data(require_group_assignment=True)
    kept, _data, removed = filter_frequency_domain_recordings(
        project_root,
        list(index.recording_ids),
        recording_data,
        recording_participant_ids={
            recording_id: recording.participant_id
            for recording_id, recording in index.recordings.items()
        },
    )
    assert "P1__visit_1" in removed
    assert "P1__visit_2" in kept


@pytest.mark.parametrize("exclusion", [
    DECISION_EXCLUDE_RECORDING, DECISION_EXCLUDE_PARTICIPANT, DECISION_EXCLUDE_CONDITION,
])
def test_excluded_visit_reconfirmation_retains_canonical_review_identity(
    tmp_path: Path, exclusion: str,
) -> None:
    project_root = _write_repeated_project(tmp_path / "Project")
    project = Project.load(project_root)
    initial = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project_root,
        initial,
        review_decisions={
            str(finding["finding_fingerprint"]): {
                "decision": exclusion,
                "reason": WARNING_REASON_UNUSUAL_VALUES,
            }
            for finding in initial["review_findings"]
        },
    )

    reviewed = run_frequency_domain_qc_review(project)
    assert reviewed["reconfirmation_findings"]
    rows = frequency_qc_review_rows(reviewed)
    row = next(row for row in rows if row["recording_id"] == "P1__visit_1")
    assert row["participant_id"] == "P1"
    assert row["session_id"] == "visit_1"
    assert row["session_label"] == "Visit 1"
    assert row["visit_index"] == 1
    assert row["group_id"] == "treated"
    assert row["source_id"] == "treated_visit_1"
    (decision,) = resolve_frequency_qc_recording_decisions(
        reviewed, {"p1__VISIT_1": "Keep this visit excluded."},
    )
    assert decision.identity.decision_key == "P1__visit_1"
    assert decision.identity.recording_id == "P1__visit_1"
    assert decision.identity.participant_id == "P1"
    assert decision.identity.session_id == "visit_1"
    assert decision.identity.session_label == "Visit 1"
    assert decision.identity.group_id == "treated"

    # The participant action deliberately excludes both visits; the recording
    # and condition actions preserve the sibling visit's scientific inputs.
    expected_recordings = {"P2__visit_1", "P2__visit_2"}
    if exclusion != DECISION_EXCLUDE_PARTICIPANT:
        expected_recordings.add("P1__visit_2")
    assert set(reviewed["recordings"]) == expected_recordings
    source_ids = {str(row["recording_id"]).casefold() for row in reviewed["source_workbooks"]}
    assert source_ids == {recording_id.casefold() for recording_id in expected_recordings}
    from Main_App.processing.harmonic_selection_qc import resolve_processing_harmonic_selection_inputs

    numeric = resolve_processing_harmonic_selection_inputs(project)
    assert set(numeric.subjects) == expected_recordings
    assert {key for key, data in numeric.subject_data.items() if data} == expected_recordings
    assert set(numeric.recording_assignments) == expected_recordings

    apply_frequency_domain_qc_decision(
        project_root,
        reviewed,
        review_decisions={
            str(finding["finding_fingerprint"]): {
                "decision": exclusion,
                "reason": WARNING_REASON_UNUSUAL_VALUES,
            }
            for finding in reviewed["review_findings"]
        },
    )
    settled = run_frequency_domain_qc_review(project)
    assert settled["review_required"] is False
    assert settled["review_reused"] or not settled["review_findings"]
    assert settled["reconfirmation_findings"] == []
    assert set(settled["recordings"]) == expected_recordings
    settled_sources = {str(row["recording_id"]).casefold() for row in settled["source_workbooks"]}
    assert settled_sources == {recording_id.casefold() for recording_id in expected_recordings}
    settled_numeric = resolve_processing_harmonic_selection_inputs(project)
    assert set(settled_numeric.subjects) == expected_recordings
    assert {key for key, data in settled_numeric.subject_data.items() if data} == expected_recordings
    assert set(settled_numeric.recording_assignments) == expected_recordings


def test_reconfirmation_rejects_recording_removed_from_canonical_registry(tmp_path: Path) -> None:
    project_root = _write_repeated_project(tmp_path / "Project")
    project = Project.load(project_root)
    initial = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project_root,
        initial,
        review_decisions={
            str(finding["finding_fingerprint"]): {
                "decision": DECISION_EXCLUDE_RECORDING,
                "reason": WARNING_REASON_UNUSUAL_VALUES,
            }
            for finding in initial["review_findings"]
        },
    )
    # Preserve the authentic saved exclusion receipt while simulating a stale
    # registry. Remove this fixture's workbook too, so workbook discovery is
    # otherwise coherent and the reconfirmation identity gate is exercised.
    index = load_project_dataset_index(project_root)
    for record in (*index.workbooks, *index.excluded_workbooks):
        if record.recording_id == "P1__visit_1":
            record.path.unlink()
    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["recordings"].pop("P1__visit_1")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    before = manifest_path.read_bytes()

    with pytest.raises(FrequencyQcReviewIdentityError, match="P1__VISIT_1"):
        run_frequency_domain_qc_review(Project.load(project_root))

    assert manifest_path.read_bytes() == before


@pytest.mark.parametrize("mutation", ("delete", "tamper"))
def test_changed_manual_recording_rows_fail_review_integrity(
    tmp_path: Path,
    mutation: str,
) -> None:
    project_root = _write_repeated_project(tmp_path / "RepeatedProject")
    project = Project.load(project_root)
    report = run_frequency_domain_qc_review(project)
    apply_frequency_domain_qc_decision(
        project_root,
        report,
        review_decisions={
            str(item["finding_fingerprint"]): {"decision": DECISION_RETAIN}
            for item in report["review_findings"]
        },
        manual_recording_reasons={
            "P2__visit_2": "Reviewed whole-recording exclusion"
        },
    )
    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest["tools"]["frequency_domain_qc"][
        "manual_recording_exclusions"
    ]
    if mutation == "delete":
        rows.clear()
    else:
        rows[0]["reason"] = "Tampered reason"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    decisions = resolve_frequency_qc_coverage_decisions(project_root)

    assert decisions.review_complete is False
    assert decisions.excluded_recordings == frozenset()
    with pytest.raises(RuntimeError, match="missing, stale, or tampered"):
        load_current_frequency_qc_review_evidence(project_root)


def test_blank_recording_comment_preserves_recording_scope_and_current_evidence(tmp_path):
    project_root = _write_repeated_project(tmp_path / "Project")
    report = run_frequency_domain_qc_review(Project.load(project_root))
    state = apply_frequency_domain_qc_decision(
        project_root, report,
        review_decisions={str(item["finding_fingerprint"]): {"decision": DECISION_EXCLUDE_RECORDING}
                          for item in report["review_findings"]},
        manual_recording_reasons={"P2__visit_2": " \t"},
    )
    assert {row["reason"] for row in state["review_decisions"]} == {"No reason provided"}
    assert state["manual_recording_exclusions"][0]["reason"] == "No reason provided"
    exclusions = active_frequency_domain_exclusions(project_root)
    assert exclusions.excluded_participants == frozenset()
    assert exclusions.manual_excluded_recordings == frozenset({"P1__VISIT_1", "P2__VISIT_2"})
    assert load_current_frequency_qc_review_evidence(project_root) == state["review_evidence"]


def _write_repeated_project(project_root: Path) -> Path:
    manifest = {
        "schema_version": "2.2.0",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "event_map": {"Faces": 1},
        "frequency_protocol": FrequencyProtocol.from_recurrence(
            6,
            5,
            expected_analyzed_oddball_cycles=12,
            expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
        ).to_manifest(),
        "preprocessing": {
            "harmonic_selection_policy": FIXED_PREDEFINED_POLICY_NAME,
            "harmonic_selection_profile": HARMONIC_PROFILE_FIXED_ID,
            "harmonic_selection_profile_version": "1.0",
            "fixed_harmonic_frequencies_hz": "1.2, 2.4",
            "fixed_harmonic_input_mode": "frequency_list",
        },
        "groups": {
            "treated": {
                "label": "Treated",
                "folder_name": "Treated",
                "raw_input_folder": "Raw/Treated",
            },
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": "Raw/Control",
            },
        },
        "sessions": {
            "visit_1": {"label": "Visit 1", "visit_index": 1},
            "visit_2": {"label": "Visit 2", "visit_index": 2},
        },
        "recording_sources": {},
        "participants": {
            "P1": {"group_id": "treated"},
            "P2": {"group_id": "control"},
        },
        "recordings": {},
    }
    for group_id, participant_id in (("treated", "P1"), ("control", "P2")):
        for visit_index, session_id in ((1, "visit_1"), (2, "visit_2")):
            source_id = f"{group_id}_{session_id}"
            recording_id = f"{participant_id}__{session_id}"
            manifest["recording_sources"][source_id] = {
                "group_id": group_id,
                "session_id": session_id,
                "raw_input_folder": f"Raw/{group_id}/{session_id}",
            }
            manifest["recordings"][recording_id] = {
                "participant_id": participant_id,
                "session_id": session_id,
                "source_id": source_id,
                "raw_file": f"Raw/{group_id}/{session_id}/{participant_id}.bdf",
                "visit_index": visit_index,
            }
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    for _group_id, group_folder, participant_id in (
        ("treated", "Treated", "P1"),
        ("control", "Control", "P2"),
    ):
        for session_id in ("visit_1", "visit_2"):
            recording_id = f"{participant_id}__{session_id}"
            values = (
                {"O2": (150.0, 150.0), "PZ": (1.0, 1.0)}
                if recording_id == "P1__visit_1"
                else {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)}
            )
            _write_bca_workbook(
                project_root
                / "1 - Excel Data Files"
                / "Faces"
                / group_folder
                / f"{recording_id}_Faces_Results.xlsx",
                values,
            )
    return project_root


def _write_bca_workbook(
    path: Path,
    electrode_values: dict[str, tuple[float, float]],
) -> None:
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
