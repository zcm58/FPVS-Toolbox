"""Reviewed cohort release to an immutable lab-scoped receipt, using a synthetic service."""

import csv
import hashlib
import io
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from Main_App.exports import analysis_ready_workbook as audit
from Main_App.exports.reporting_csv import export_reporting_csv
from Main_App.processing import artifact_freshness, expected_processing_ledger, processing_ledger, roi_coverage
from Main_App.projects.project import Project
from Main_App.reporting import client
from Main_App.reporting.provenance import reporting_scope
from Main_App.reporting.snapshots import load_snapshot, queue_snapshot, read_state, save_scope


@pytest.fixture
def released(tmp_path, monkeypatch):
    source, website = str(uuid4()), str(uuid4())
    execution, deferred = "a" * 32, "b" * 32
    target = artifact_freshness.canonical_artifact_path(tmp_path, "analysis_ready_full_audit")
    target.parent.mkdir(parents=True)
    recording = SimpleNamespace(
        recording_id="reviewed-recording",
        processing_id="reviewed-recording",
        participant_id="001",
        session_id="v1",
        visit_index=1,
        raw_file_identity={"raw_file": str(tmp_path / "raw" / "private.bdf"), "raw_size": 100, "raw_mtime_ns": 27},
    )
    rows = [
        {
            "PID": "001",
            "Recording ID": recording.recording_id,
            "Session ID": "v1",
            "Visit Index": 1,
            "Group": "cohort",
            "Condition": "faces",
            "ROI": "Occipital",
            "Raw Summed BCA": -0.125,
            "Current Toolbox Exclusion": "No",
        }
    ]
    pd.DataFrame(rows).to_excel(target, sheet_name=audit.ROI_LONG_SHEET, index=False)
    revision, fingerprint = "1" * 64, "5" * 64
    cohort = {
        "study_id": source,
        "roster_revision": revision,
        "versions": ["v1"],
        "raw_folder": str(tmp_path / "raw"),
        "website_study": {
            "project_id": website,
            "experiment_id": "faces",
            "experiment_version": "1.0",
            "protocol_sha256": "2" * 64,
        },
        "visits": {
            execution: {
                "decision": "matched",
                "in_source_roster": True,
                "execution_id": execution,
                "participant_number": "001",
                "recording_id": recording.recording_id,
                "raw_file": "private.bdf",
                "file_identity": [100, 27],
                "manual_removed_electrodes": [],
            },
            deferred: {"decision": "awaiting_eeg", "in_source_roster": True},
        },
        "current_result": {
            "roster_revision": revision,
            "processing_run_id": "run",
            "versions": ["v1"],
            "release_fingerprint": fingerprint,
            "included": [execution],
            "excluded": [],
            "awaiting_eeg": [deferred],
            "workbook": target.relative_to(tmp_path).as_posix(),
            "workbook_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        },
    }
    project = SimpleNamespace(preprocessing={}, manifest={"tools": {"studio_cohort": cohort}})
    release = SimpleNamespace(fingerprint=fingerprint)
    coverage = SimpleNamespace(
        cells=[
            SimpleNamespace(recording_id=recording.recording_id, source_evidence=True, downstream_cell_excluded=False)
        ],
        roi_snapshot=SimpleNamespace(rois=[SimpleNamespace(name="Occipital", electrodes=["O1", "Oz"])]),
    )
    plan = SimpleNamespace(
        run_id="run",
        fingerprint="3" * 64,
        processing_fingerprint="4" * 64,
        processing_fingerprint_version="v1",
        recordings=[recording],
    )
    entry = {
        **recording.raw_file_identity,
        "recording_id": recording.recording_id,
        "participant_id": "001",
        "session_id": "v1",
        "visit_index": 1,
        "processing_fingerprint": plan.processing_fingerprint,
        "processing_fingerprint_version": "v1",
        "native_sampling_rate_hz": 2048,
        "analysis_sampling_rate_hz": 250,
    }
    monkeypatch.setattr(Project, "load", lambda _root: project)
    monkeypatch.setattr(
        roi_coverage,
        "require_project_final_release",
        lambda _root: (SimpleNamespace(expected_plan_fingerprint=plan.fingerprint), coverage, release),
    )
    monkeypatch.setattr(expected_processing_ledger, "load_expected_recording_condition_plan", lambda _root: plan)
    monkeypatch.setattr(processing_ledger, "load_ledger", lambda _root: {"entries": {recording.recording_id: entry}})
    monkeypatch.setattr(
        artifact_freshness,
        "require_current_artifact",
        lambda *_args: SimpleNamespace(built_from_selection_fingerprint="6" * 64),
    )
    monkeypatch.setattr(audit, "_load_current_processing_selection_metadata", lambda _root: {})
    monkeypatch.setattr(
        audit,
        "_load_selection_frames",
        lambda *_args, **_kwargs: ({"Harmonic_Selection": pd.DataFrame({"requested_harmonic_hz": [1.2]})}, "saved"),
    )
    monkeypatch.setattr(audit, "_selected_harmonics_from_frames", lambda _: [1.2])
    return tmp_path, project, cohort, execution, target


def test_private_full_audit_to_lab_scoped_retry(released):
    root, project, cohort, execution, _ = released
    scope = reporting_scope(project)
    save_scope(root, scope, {"approval_status": "approved", "upload_enabled": True})
    manifest, results_csv = export_reporting_csv(root, scope)
    expected = hashlib.sha256(f"openfpvs-visit-v1\n{cohort['study_id']}\n{execution}".encode()).hexdigest()
    assert manifest["schema_version"] == "1.2"
    assert manifest["roster_coverage"]["included"] == [expected]
    assert len(manifest["roster_coverage"]["awaiting_eeg"]) == 1
    record = manifest["electrode_exclusions"]["recordings"][0]
    assert record["studio_execution_id"] == execution and record["studio_removed_electrodes"] == []
    assert record["toolbox_interpolated_electrodes"] is None
    assert list(csv.DictReader(io.StringIO(results_csv)))[0]["summed_bca_uv"] == "-0.125"
    assert str(root) not in str(manifest) and "reviewed-recording" not in results_csv
    file = queue_snapshot(root, manifest, results_csv)
    original = load_snapshot(root, file.stem)
    with pytest.raises(ValueError, match="already pending"):
        queue_snapshot(root, manifest, results_csv)
    store = SimpleNamespace(load=lambda: "f" * 64)

    def offline(*_args):
        raise client.ReportingError("delivery_unavailable")

    assert client.deliver_pending(root, store=store, transport=offline) == "delivery_unavailable"

    def accept(route, payload, token):
        assert route == "/analysis/v1/snapshots" and token == "f" * 64 and payload == original
        keys = ("study_id", "dataset_id", "snapshot_id", "snapshot_sha256")
        return {"schema_version": "1.0", "status": "accepted", **{key: payload["manifest"][key] for key in keys}}

    assert client.deliver_pending(root, store=store, transport=accept, retry=True) == "delivered"
    assert read_state(root)["pending"] == []
    assert load_snapshot(root, file.stem) == original
    with pytest.raises(ValueError, match="already accepted"):
        queue_snapshot(root, manifest, results_csv)


def test_release_and_recognized_research_visits_are_required(released):
    root, project, cohort, execution, target = released
    scope = reporting_scope(project)
    cohort["visits"][execution]["file_identity"] = [44, 27]
    with pytest.raises(ValueError, match="differs from the reviewed"):
        export_reporting_csv(root, scope)
    cohort["visits"][execution]["file_identity"] = [100, 27]
    cohort["current_result"]["roster_revision"] = "8" * 64
    with pytest.raises(ValueError, match="full-audit release"):
        export_reporting_csv(root, scope)
    cohort["current_result"]["roster_revision"] = cohort["roster_revision"]
    target.write_bytes(b"other workbook")
    with pytest.raises(ValueError, match="workbook changed"):
        export_reporting_csv(root, scope)


def test_lost_enrollment_response_reuses_the_same_secure_device_key(released):
    root, project, *_ = released
    scope = reporting_scope(project)
    secret = []
    store = SimpleNamespace(load=lambda: secret[0] if secret else None, save=secret.append)
    issued = []

    def transport(route, payload):
        assert route == "/analysis/v1/enroll" and payload["code"] == "synthetic-lab-code"
        issued.append(payload["device_token"])
        if len(issued) == 1:
            raise client.ReportingError("delivery_unavailable")
        return {
            "schema_version": "1.0",
            "study_id": scope["study_id"],
            "approval_status": "pending",
            "upload_enabled": False,
        }

    with pytest.raises(client.ReportingError):
        client.enroll(root, scope, "synthetic-lab-code", store=store, transport=transport)
    client.enroll(root, scope, "synthetic-lab-code", store=store, transport=transport)
    assert issued[0] == issued[1] == secret[0]
    state = read_state(root)
    assert secret[0] not in str(state) and "synthetic-lab-code" not in str(state)
    assert state["pending"] == [] and state["enrollment"]["approval_status"] == "pending"
