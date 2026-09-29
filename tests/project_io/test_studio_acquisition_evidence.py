from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from Main_App.io.studio_acquisition_evidence import (
    CONTRACT_STATUS,
    ReviewedRecordingAssociation,
    StudioAcquisitionEvidenceError,
    load_studio_acquisition_evidence,
    parse_studio_acquisition_evidence,
    reconcile_studio_marker_codes,
)


def _payload():
    return {
        "schema_version": "1.0",
        "contract_status": "candidate_receiver_validation_pending",
        "studio_version": "test-version",
        "execution_id": "execution-1",
        "project_id": "studio-project",
        "participant_number": "test-participant",
        "created_at_utc": "2026-09-28T10:00:00+00:00",
        "updated_at_utc": "2026-09-28T10:01:00Z",
        "wall_clock_meaning": "UTC evidence write time; not EEG synchronization",
        "callback_time_units": "seconds",
        "callback_time_origin": "per-run playback clock after warmup; not EEG time",
        "sent_status_meaning": "local transport submission only; receipt and disk logging unknown",
        "persistence_boundary": "between runs and on orderly failure; abrupt process loss may omit current run",
        "state": "completed",
        "recording": {
            "schema_version": 1,
            "selected_backend": "unicorn_udp",
            "effective_backend": "unicorn_udp",
            "selection_source": "local_settings",
            "udp_host": "127.0.0.1",
            "udp_port": 1000,
            "operator_confirmed_raw_bdf_recording": True,
            "recording_association": "operator hint, not a Toolbox recording ID",
            "receiver_validation": "pending",
            "recorded_marker_integrity": "unknown",
            "physical_timing": "uncharacterized",
            "acquisition_status": "unknown",
        },
        "runs": [{
            "run_id": "run-1",
            "condition_id": "condition-1",
            "condition_name": "Test condition",
            "code_map": [{"code": 55, "label": "oddball"}, {"code": 2, "label": "condition"}],
            "planned_event_count": 3,
            "attempted_events": [
                {"trigger_index": i, "frame_index": i * 50, "time_s": i * 0.8,
                 "code": code, "label": "oddball" if code == 55 else "condition",
                 "backend_name": "unicorn_udp", "status": "sent"}
                for i, code in enumerate([55, 55, 2])
            ],
            "state": "completed",
            "completed_frames": 150,
        }],
        "uninterpreted_extra": {"items": ["retained", {"value": 1}]},
    }


def _association(**updates):
    values = {"execution_id": "execution-1", "recording_id": "recording-1",
              "raw_sha256": "a" * 64, "review_id": "review-1"}
    return ReviewedRecordingAssociation(**(values | updates))


def test_candidate_envelope_preserves_order_repeats_clocks_and_immutable_raw_data():
    payload = _payload()
    evidence = parse_studio_acquisition_evidence(payload)
    assert evidence.schema_version == "1.0"
    assert evidence.recording["schema_version"] == 1
    assert evidence.contract_status == CONTRACT_STATUS
    assert [event.code for event in evidence.attempted_events] == [55, 55, 2]
    assert [event.time_s for event in evidence.attempted_events] == [0.0, 0.8, 1.6]
    assert evidence.runs[0].code_map == ((55, "oddball"), (2, "condition"))
    payload["runs"][0]["attempted_events"][0]["code"] = 99
    payload["uninterpreted_extra"]["items"].append("later")
    assert evidence.attempted_events[0].code == 55
    assert len(evidence.raw_payload["uninterpreted_extra"]["items"]) == 2
    with pytest.raises(TypeError):
        evidence.raw_payload["uninterpreted_extra"]["items"][1]["value"] = 2
    with pytest.raises(FrozenInstanceError):
        evidence.attempted_events[0].code = 99
    assert not hasattr(evidence.attempted_events[0], "sample")
    assert not hasattr(evidence, "timing_offset")


@pytest.mark.parametrize("field,value", [
    ("schema_version", 1), ("schema_version", "2.0"),
    ("contract_status", "qualified"), ("callback_time_origin", "EEG time"),
    ("sent_status_meaning", "received"), ("state", "unknown"),
    ("created_at_utc", "2026-09-28T10:00:00"),
    ("created_at_utc", "2026-09-28T10:00:00+01:00"),
    ("participant_session_number", True), ("participant_number", ""),
])
def test_rejects_unknown_or_ambiguous_envelope(field, value):
    payload = _payload()
    payload[field] = value
    with pytest.raises(StudioAcquisitionEvidenceError):
        parse_studio_acquisition_evidence(payload)


@pytest.mark.parametrize("field,value", [
    ("schema_version", "1"), ("schema_version", True),
    ("selected_backend", "serial"), ("effective_backend", "serial"),
    ("udp_host", "remote-host"), ("udp_port", True), ("udp_port", 65536),
    ("operator_confirmed_raw_bdf_recording", 1), ("receiver_validation", "passed"),
    ("recorded_marker_integrity", "verified"), ("physical_timing", "calibrated"),
])
def test_rejects_non_unicorn_or_promoted_recording_snapshot(field, value):
    payload = _payload()
    payload["recording"][field] = value
    with pytest.raises(StudioAcquisitionEvidenceError):
        parse_studio_acquisition_evidence(payload)


@pytest.mark.parametrize("field,value", [
    ("code", 0), ("code", 256), ("code", "55"), ("code", True),
    ("time_s", float("nan")), ("time_s", float("inf")), ("time_s", -1),
    ("time_s", True), ("frame_index", 1.5), ("trigger_index", -1),
    ("status", "skipped_disabled"), ("backend_name", "serial"),
])
def test_rejects_invalid_attempts_without_coercing_or_dropping_them(field, value):
    payload = _payload()
    payload["runs"][0]["attempted_events"][0][field] = value
    with pytest.raises(StudioAcquisitionEvidenceError):
        parse_studio_acquisition_evidence(payload)


def test_optional_none_fields_and_empty_message_are_preserved():
    payload = _payload()
    event = payload["runs"][0]["attempted_events"][0]
    event["time_s"] = None
    event["message"] = ""
    payload["session_id"] = None
    evidence = parse_studio_acquisition_evidence(payload)
    assert evidence.attempted_events[0].time_s is None
    assert evidence.attempted_events[0].message == ""


def test_load_is_read_only_and_duplicate_keys_are_rejected(tmp_path):
    path = tmp_path / "candidate.acquisition-v1.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    original = path.read_bytes()
    assert load_studio_acquisition_evidence(path).execution_id == "execution-1"
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
    path.write_text('{"schema_version":"1.0", "schema_version":"2.0"}', encoding="utf-8")
    with pytest.raises(StudioAcquisitionEvidenceError, match="Duplicate JSON key"):
        load_studio_acquisition_evidence(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(StudioAcquisitionEvidenceError, match="Cannot read"):
        load_studio_acquisition_evidence(path)
    with pytest.raises(StudioAcquisitionEvidenceError, match="Cannot read"):
        load_studio_acquisition_evidence(tmp_path / "missing.json")


def test_reconciliation_requires_review_and_never_promotes_candidate_state():
    evidence = parse_studio_acquisition_evidence(_payload())
    result = reconcile_studio_marker_codes(evidence, [55, 55, 2], association=_association())
    assert result.status == "code_sequence_match"
    assert result.code_sequence_equal
    assert result.attempted_count == result.recorded_count == 3
    assert evidence.recording["receiver_validation"] == "pending"
    assert evidence.recording["recorded_marker_integrity"] == "unknown"
    assert not hasattr(result, "scientific_eligible")
    assert reconcile_studio_marker_codes(evidence, [55, 2], association=_association()).status == "code_sequence_mismatch"
    for association in (None, _association(execution_id="different"),
                        _association(review_id=""), _association(raw_sha256="not-a-hash")):
        with pytest.raises(StudioAcquisitionEvidenceError):
            reconcile_studio_marker_codes(evidence, [55, 55, 2], association=association)
    with pytest.raises(StudioAcquisitionEvidenceError):
        reconcile_studio_marker_codes(evidence, [55, True, 2], association=_association())


def test_sender_error_is_not_discarded_even_when_sequence_matches():
    payload = _payload()
    payload["runs"][0]["attempted_events"][1]["status"] = "error"
    evidence = parse_studio_acquisition_evidence(payload)
    result = reconcile_studio_marker_codes(evidence, [55, 55, 2], association=_association())
    assert result.status == "sender_errors_unresolved"
    assert result.code_sequence_equal and result.send_error_count == 1
    assert evidence.attempted_events[1].status == "error"


@pytest.mark.parametrize("change", ["aborted", "count", "empty", "run_started"])
def test_partial_evidence_cannot_report_unqualified_match(change):
    payload = _payload()
    if change == "aborted":
        payload["state"] = "aborted"
    elif change == "count":
        payload["runs"][0]["planned_event_count"] = 4
    elif change == "run_started":
        payload["runs"][0]["state"] = "started"
    else:
        payload["runs"] = []
    evidence = parse_studio_acquisition_evidence(payload)
    codes = [event.code for event in evidence.attempted_events]
    result = reconcile_studio_marker_codes(evidence, codes, association=_association())
    assert result.code_sequence_equal
    assert result.status == "incomplete_sender_evidence"


def test_disabled_backend_remains_inspectable_but_not_reconcilable():
    payload = _payload()
    payload["recording"]["effective_backend"] = "null"
    payload["runs"][0]["attempted_events"] = []
    evidence = parse_studio_acquisition_evidence(payload)
    with pytest.raises(StudioAcquisitionEvidenceError, match="Disabled"):
        reconcile_studio_marker_codes(evidence, [], association=_association())


def test_duplicate_run_id_is_rejected_and_per_run_clocks_are_not_flattened():
    payload = _payload()
    second = _payload()["runs"][0]
    payload["runs"].append(second)
    with pytest.raises(StudioAcquisitionEvidenceError, match="Duplicate run_id"):
        parse_studio_acquisition_evidence(payload)
    second["run_id"] = "run-2"
    evidence = parse_studio_acquisition_evidence(payload)
    assert [event.time_s for event in evidence.attempted_events] == [0.0, 0.8, 1.6] * 2


def test_retained_receiver_fixture_preserves_all_426_samples_and_adjacent_repeats():
    path = Path(__file__).parents[1] / "fixtures" / "unicorn_receiver" / "retained_426_marker_receipt.json"
    text = path.read_text(encoding="utf-8")
    receipt = json.loads(text)
    events = receipt["events"]
    assert len(events) == receipt["recorded_markers"] == receipt["expected_markers"] == 426
    assert receipt["sampling_hz"] == 250
    assert receipt["sample_count"] == 22621
    assert receipt["exact_sequence_match"] and receipt["bdf_csv_trigger_samples_exact_match"]
    assert set(event["code"] for event in events) == set(range(1, 256))
    assert all(a["sample"] < b["sample"] for a, b in zip(events, events[1:]))
    repeated_adjacent = [a["sample"] for a, b in zip(events, events[1:])
                         if a["code"] == b["code"] and b["sample"] == a["sample"] + 1]
    assert repeated_adjacent == [16663, 16679, 16764, 16780]
    assert receipt["format"]["reserved"] == "24BIT"
    assert receipt["format"]["eeg_dimension"] == "?V"
    assert not receipt["format"]["bdf_plus_annotations_present"]
    assert "sender_monotonic_s" not in text and "bdf_header_date" not in text
    assert all(set(event) == {"sample", "code"} for event in events)
