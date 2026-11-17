"""Scientific compatibility is independent of the producer application version."""

from copy import deepcopy

import pytest

from Main_App.projects.studio_handoff import normalize_studio_handoff


@pytest.fixture
def handoff():
    return {
        "format": "fpvs-handoff", "format_version": 2, "kind": "setup",
        "producer": {"application": "FPVS Studio", "version": "2.8.2"},
        "project": {"project_id": "example", "name": "Example"},
        "conditions": [{"condition_id": "faces", "name": "Faces", "trigger_code": 1,
                        "sequence_count": 1, "oddball_cycle_repeats_per_sequence": 146}],
        "protocol": {"base_hz": 6, "oddball_every_n": 5},
        "triggers": {"oddball_trigger_code": 55},
    }


def test_optional_metadata_and_app_releases_do_not_select_new_format(handoff):
    handoff["producer"]["version"] = "99.0.1"
    handoff["metadata"] = {"future_note": {"text": "descriptive only"}}
    original = deepcopy(handoff)
    result = normalize_studio_handoff(handoff)
    assert result == original
    result["metadata"]["future_note"]["text"] = "changed"
    assert handoff == original


@pytest.mark.parametrize("version", [True, "2", 2.0, 1, 3, None])
def test_revision_requires_exact_supported_integer(handoff, version):
    handoff["format_version"] = version
    with pytest.raises(ValueError, match="format revision"):
        normalize_studio_handoff(handoff)


@pytest.mark.parametrize("key", ["format", "kind", "producer", "protocol"])
def test_current_required_envelope_fields_cannot_default(handoff, key):
    del handoff[key]
    with pytest.raises(ValueError):
        normalize_studio_handoff(handoff)


def test_mixed_envelope_rejected(handoff):
    handoff["schema_version"] = "1.2.0"
    with pytest.raises(ValueError, match="cannot mix"):
        normalize_studio_handoff(handoff)


@pytest.mark.parametrize("version", [f"1.{minor}.0" for minor in range(16)])
def test_historical_revision_is_preserved_for_protocol_default_adapter(handoff, version):
    for key in ("format", "format_version", "kind", "producer"):
        del handoff[key]
    handoff["schema_version"] = version
    handoff["participants"] = {"P01": {"removed_electrodes": ["Oz"]}}
    assert normalize_studio_handoff(handoff) == handoff


@pytest.mark.parametrize("version", ["1.16.0", "2.0.0", None, {"version": "1.2.0"}])
def test_unknown_historical_revision_rejected(version):
    with pytest.raises(ValueError, match="Unsupported FPVS config schema"):
        normalize_studio_handoff({"schema_version": version})


@pytest.mark.parametrize("location", ["top", "protocol", "condition", "defaults", "triggers", "project", "session"])
def test_unknown_scientific_fields_rejected(handoff, location):
    target = {"top": handoff, "protocol": handoff["protocol"],
              "condition": handoff["conditions"][0],
              "defaults": handoff.setdefault("condition_defaults", {}),
              "triggers": handoff["triggers"], "project": handoff["project"],
              "session": handoff.setdefault("session", {})}[location]
    target["new_scientific_rule"] = "different"
    with pytest.raises(ValueError, match="Unsupported Studio fields"):
        normalize_studio_handoff(handoff)


def test_equal_condition_rate_is_compatible(handoff):
    handoff["conditions"][0]["base_hz"] = 6.0
    handoff["conditions"][0]["presentation_count"] = 3
    assert normalize_studio_handoff(handoff) == handoff


@pytest.mark.parametrize("identity", [None, "", [], 12])
def test_current_condition_identity_is_required_text(handoff, identity):
    handoff["conditions"][0]["condition_id"] = identity
    with pytest.raises(ValueError, match="condition_id"):
        normalize_studio_handoff(handoff)


def test_current_condition_id_cannot_identify_two_conditions(handoff):
    handoff["conditions"].append({**handoff["conditions"][0], "name": "Other", "trigger_code": 2})
    with pytest.raises(ValueError, match="Duplicate Studio condition_id"):
        normalize_studio_handoff(handoff)


def test_canonical_condition_defaults_and_known_duty_cycles_remain_compatible(handoff):
    handoff["condition_defaults"] = {
        "duty_cycle_mode": "blank_50", "sequence_count": 1,
        "oddball_cycle_repeats_per_sequence": 146, "target_repeats_per_image": 7,
        "presentation_count": 3,
    }
    handoff["conditions"][0]["duty_cycle_mode"] = "sinusoidal"
    assert normalize_studio_handoff(handoff) == handoff


def test_unknown_duty_cycle_cannot_be_silently_ignored(handoff):
    handoff["conditions"][0]["duty_cycle_mode"] = "new-timing"
    with pytest.raises(ValueError, match="duty-cycle"):
        normalize_studio_handoff(handoff)


@pytest.mark.parametrize("value", [3, float("nan"), float("inf"), True])
def test_changed_or_malformed_condition_rate_rejected(handoff, value):
    handoff["conditions"][0]["base_hz"] = value
    with pytest.raises(ValueError, match="frequenc"):
        normalize_studio_handoff(handoff)


@pytest.mark.parametrize("location", ["conditions", "condition_defaults"])
def test_explicit_duration_requires_supported_window_semantics(handoff, location):
    target = handoff[location][0] if location == "conditions" else handoff.setdefault(location, {})
    target["stream_duration_seconds"] = 120
    with pytest.raises(ValueError, match="stream-duration overrides"):
        normalize_studio_handoff(handoff)


@pytest.mark.parametrize("value", [0, True, 1.5, "3"])
def test_occurrence_counts_are_strict(handoff, value):
    handoff["conditions"][0]["presentation_count"] = value
    with pytest.raises(ValueError, match="positive integer"):
        normalize_studio_handoff(handoff)


@pytest.mark.parametrize("kind", ["masking", "catch", "ab"])
def test_unsupported_scientific_designs_have_specific_errors(handoff, kind):
    if kind == "masking":
        handoff["condition_modifiers"] = [{"masking": {"variant": "forward"}}]
    elif kind == "catch":
        handoff["conditions"][0]["masking_catch"] = True
    else:
        handoff["experiment_category"] = "attentional_blink"
    with pytest.raises(ValueError, match="masking/catch|experiment category"):
        normalize_studio_handoff(handoff)


@pytest.mark.parametrize("field,value", [("project_title", "Other"), ("event_map", {"Faces": 2}),
                                        ("oddball_trigger_code", 88)])
def test_redundant_toolbox_summary_cannot_disagree(handoff, field, value):
    handoff["toolbox"] = {field: value}
    with pytest.raises(ValueError, match="conflicts"):
        normalize_studio_handoff(handoff)


def _completion(handoff):
    handoff["kind"] = "completed_session"
    completed = {
        "session_id": "session-1", "execution_id": "execution-1", "participant_number": "007",
        "participant_session_number": 2, "manual_removed_electrodes": ["Oz"],
        "ordered_runs": [{"run_id": "run-1", "condition_id": "faces", "condition_name": "Faces"}],
    }
    completed["acquisition_evidence"] = {
        "schema_version": "1.0", "state": "completed", "project_id": "example",
        "contract_status": "candidate_receiver_validation_pending",
        "session_id": "session-1", "execution_id": "execution-1", "participant_number": "007",
        "participant_session_number": 2,
        "recording": {"schema_version": 1, "selected_backend": "serial", "effective_backend": "serial"},
        "runs": [{"run_id": "run-1", "state": "completed", "condition_id": "faces", "condition_name": "Faces"}],
    }
    handoff["completed_session"] = completed
    return completed


@pytest.mark.parametrize("electrodes", [None, [], ["Oz", "P9"]])
def test_completed_identity_and_electrode_states_are_preserved_unbound(handoff, electrodes):
    completed = _completion(handoff)
    completed["manual_removed_electrodes"] = electrodes
    result = normalize_studio_handoff(handoff)
    assert result["completed_session"]["participant_number"] == "007"
    assert result["completed_session"]["manual_removed_electrodes"] == electrodes
    assert "participants" not in result


def test_active_three_retains_its_serial_transport(handoff):
    completed = _completion(handoff)
    handoff["recording"] = {"recording_backend": "biosemi_active_three"}
    completed["acquisition_evidence"]["recording"]["selected_backend"] = "biosemi_active_three"
    assert normalize_studio_handoff(handoff) == handoff


@pytest.mark.parametrize("failure", ["project_backend", "transport", "profile"])
def test_acquisition_hardware_declarations_must_agree(handoff, failure):
    evidence = _completion(handoff)["acquisition_evidence"]
    if failure == "project_backend":
        handoff["recording"] = {"recording_backend": "unicorn_udp"}
    elif failure == "transport":
        evidence["recording"]["effective_backend"] = "unicorn_udp"
    else:
        evidence["acquisition_profile"] = {"id": "first"}
        evidence["recording"]["acquisition_profile"] = {"id": "second"}
    with pytest.raises(ValueError, match="conflict"):
        normalize_studio_handoff(handoff)


@pytest.mark.parametrize("field,value", [("session_id", "wrong"), ("execution_id", "wrong"),
    ("participant_number", "P007"), ("participant_session_number", 1), ("project_id", "other"),
    ("state", "interrupted"), ("export_error", "failed"), ("schema_version", "2.0")])
def test_completed_acquisition_mismatches_rejected(handoff, field, value):
    completed = _completion(handoff)
    completed["acquisition_evidence"][field] = value
    with pytest.raises(ValueError):
        normalize_studio_handoff(handoff)


@pytest.mark.parametrize("field,value", [("participant_number", 7), ("participant_session_number", True),
    ("manual_removed_electrodes", "Oz"), ("manual_removed_electrodes", [""])])
def test_malformed_completed_identity_and_electrodes_rejected(handoff, field, value):
    completed = _completion(handoff)
    completed[field] = value
    with pytest.raises(ValueError):
        normalize_studio_handoff(handoff)


@pytest.mark.parametrize("failure", ["missing", "unfinished", "wrong_order", "wrong_condition", "pilot"])
def test_completed_run_evidence_must_agree(handoff, failure):
    completed = _completion(handoff)
    evidence = completed["acquisition_evidence"]
    if failure == "missing":
        evidence["runs"] = []
    elif failure == "unfinished":
        evidence["runs"][0]["state"] = "started"
    elif failure == "wrong_order":
        completed["ordered_runs"][0]["run_id"] = "other"
    elif failure == "wrong_condition":
        evidence["runs"][0]["condition_name"] = "Other"
    else:
        evidence["recording"]["effective_backend"] = "null"
    with pytest.raises(ValueError):
        normalize_studio_handoff(handoff)


def test_setup_and_completed_kinds_require_matching_content(handoff):
    handoff["kind"] = "completed_session"
    with pytest.raises(ValueError, match="kind must agree"):
        normalize_studio_handoff(handoff)
    _completion(handoff)
    handoff["kind"] = "setup"
    with pytest.raises(ValueError, match="kind must agree"):
        normalize_studio_handoff(handoff)
