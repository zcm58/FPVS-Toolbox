"""Reviewed cohort release to an immutable lab-scoped receipt, using a synthetic service."""

import csv
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pandas as pd
import pytest

from Main_App.exports import analysis_ready_workbook as audit
from Main_App.exports.reporting_csv import export_reporting_csv
from Main_App.processing import artifact_freshness, expected_processing_ledger, processing_ledger, roi_coverage
from Main_App.projects.project import Project
from Main_App.reporting import client, publish
from Main_App.reporting.provenance import reporting_scope
from Main_App.reporting.snapshots import SNAPSHOT_DIRECTORY, load_snapshot, queue_snapshot, read_state, save_scope, state_path


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

    assert client.deliver_pending(root, expected_scope=scope, store=store, transport=accept, retry=True) == "delivered"
    assert read_state(root)["pending"] == []
    assert load_snapshot(root, file.stem) == original
    with pytest.raises(ValueError, match="already accepted"):
        queue_snapshot(root, manifest, results_csv)


@pytest.mark.parametrize("mismatch", [
    "displayed", "live", "outbox_scope", "snapshot_scope", "outbox_dataset", "live_during_snapshot_read",
])
def test_retry_checks_all_destinations_before_accessing_credentials(released, mismatch, monkeypatch):
    root, project, cohort, *_ = released
    displayed = reporting_scope(project)
    save_scope(root, displayed, {"approval_status": "approved", "upload_enabled": True})
    manifest, csv_text = export_reporting_csv(root, displayed)
    queued = queue_snapshot(root, manifest, csv_text)
    original_request = queued.read_bytes()
    state = read_state(root)
    changed_scope = {**displayed, "experiment_version": "2.0"}
    if mismatch == "displayed":
        displayed = changed_scope
    elif mismatch == "live":
        cohort["website_study"]["project_id"] = str(uuid4())
    elif mismatch == "outbox_scope":
        state["scope"] = changed_scope
    elif mismatch == "snapshot_scope":
        cohort["website_study"]["experiment_version"] = "2.0"
        displayed = changed_scope
        state["scope"] = changed_scope
    elif mismatch == "live_during_snapshot_read":
        def load_before_project_restore(*args):
            payload = load_snapshot(*args)
            cohort["website_study"]["experiment_version"] = "2.0"
            return payload

        monkeypatch.setattr(client, "load_snapshot", load_before_project_restore)
    else:
        state["dataset_id"] = str(uuid4())
    state_path(root).write_text(json.dumps(state), encoding="utf-8")
    store, transport = Mock(), Mock()
    with pytest.raises(client.ReportingError, match="snapshot_scope_conflict"):
        client.deliver_pending(root, expected_scope=displayed, store=store, transport=transport, retry=True)
    store.load.assert_not_called()
    transport.assert_not_called()
    assert read_state(root) == state and queued.read_bytes() == original_request


@pytest.mark.parametrize("when_changed", ["before_share", "during_export", "dataset_during_export"])
def test_share_refuses_changed_destination_before_queue_or_delivery(released, monkeypatch, when_changed):
    root, project, cohort, *_ = released
    displayed = reporting_scope(project)
    save_scope(root, displayed, {"approval_status": "approved", "upload_enabled": True})
    if when_changed == "before_share":
        cohort["website_study"]["experiment_version"] = "2.0"
        exporter = Mock(side_effect=AssertionError("Should refuse before exporting"))
    else:
        def changed_after_export(*args):
            result = export_reporting_csv(*args)
            if when_changed == "during_export":
                cohort["website_study"]["experiment_version"] = "2.0"
            else:
                state = read_state(root)
                state["dataset_id"] = str(uuid4())
                state_path(root).write_text(json.dumps(state), encoding="utf-8")
            return result

        exporter = Mock(side_effect=changed_after_export)
    monkeypatch.setattr(publish, "export_reporting_csv", exporter)
    deliver = Mock()
    monkeypatch.setattr(publish, "deliver_pending", deliver)
    with pytest.raises(ValueError):
        publish.publish_current(root, expected_scope=displayed)
    if when_changed == "before_share":
        exporter.assert_not_called()
    else:
        exporter.assert_called_once_with(root, displayed)
    deliver.assert_not_called()
    assert read_state(root)["pending"] == []
    assert not list((root / SNAPSHOT_DIRECTORY).glob("*.json"))


def test_brainvision_reporting_requires_matching_reviewed_companions(released):
    from Main_App.io.recording_sources import companion_identity

    root, project, cohort, execution, _ = released
    scope = reporting_scope(project)
    raw = root / "raw"
    raw.mkdir()
    header = raw / "private.vhdr"
    header.write_text("[Common Infos]\nDataFile=private.eeg\nMarkerFile=private.vmrk\n", encoding="utf-8")
    (raw / "private.vmrk").write_text("[Common Infos]\nDataFile=private.eeg\n", encoding="utf-8")
    data = raw / "private.eeg"
    data.write_bytes(b"synthetic")
    visit = cohort["visits"][execution]
    visit["raw_file"] = header.name
    visit["file_identity"] = [header.stat().st_size, header.stat().st_mtime_ns]
    record = expected_processing_ledger.load_expected_recording_condition_plan(root).recordings[0]
    record.raw_file_identity.update(
        raw_file=str(header), raw_size=visit["file_identity"][0], raw_mtime_ns=visit["file_identity"][1],
    )
    entry = processing_ledger.load_ledger(root)["entries"][record.recording_id]
    entry.update(record.raw_file_identity)
    with pytest.raises(ValueError, match="(?i)review"):
        export_reporting_csv(root, scope)

    from Main_App.reporting.electrode_exclusions import build_electrode_exclusions
    plan = expected_processing_ledger.load_expected_recording_condition_plan(root)
    excluded = {**entry, "status": "excluded", "exclusion_reason": "all_conditions_excluded_from_analysis"}
    evidence = build_electrode_exclusions(project, plan, {record.processing_id: excluded}, str(uuid4()), set())
    assert evidence["recordings"][0]["studio_evidence_source"] == "unknown"
    assert evidence["recordings"][0]["toolbox_interpolated_electrodes"] is None

    components = companion_identity(header)
    visit.update(components)
    record.raw_file_identity.update(components)
    entry.update(components)
    hashes = {row["path"]: hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest()
              for row in components["recording_sources"]}
    with pytest.raises(ValueError, match="(?i)review"):
        export_reporting_csv(root, scope)
    visit["source_sha256_by_file"] = hashes
    with pytest.raises(ValueError, match="Reprocess"):
        export_reporting_csv(root, scope)
    entry["source_sha256_by_file"] = {**hashes, str(data): "0" * 64}
    with pytest.raises(ValueError, match="Reprocess"):
        export_reporting_csv(root, scope)
    entry["source_sha256_by_file"] = dict(hashes)
    manifest, _ = export_reporting_csv(root, scope)
    assert manifest["electrode_exclusions"]["recordings"][0]["studio_execution_id"] == execution
    assert str(header) not in str(manifest) and hashes[str(data)] not in str(manifest)
    data.write_bytes(b"new synthetic data")
    record.raw_file_identity.update(companion_identity(header))
    entry.update(record.raw_file_identity)
    with pytest.raises(ValueError, match="review"):
        export_reporting_csv(root, scope)


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
