from __future__ import annotations

import copy
import hashlib
import json
import pickle
from dataclasses import FrozenInstanceError, replace

import pytest

from Main_App.projects import (
    CONDITION_TRIGGER_MAPS_PROTOCOL_VERSION,
    ConditionTriggerMaps,
    FrequencyProtocol,
    FrequencyProtocolError,
    Project,
    TriggerMapDraft,
    TriggerMapError,
    migrate_legacy_trigger_maps,
    project_conditions,
    resolve_recording_event_schema,
    validate_project_trigger_maps,
    validate_protocol_condition_codes,
)

pytestmark = pytest.mark.project_io


@pytest.fixture
def payload():
    return {
        "schema_version": "1.0",
        "canonical_conditions": {"angry": {"label": "Neutral Angry"}, "happy": {"label": "Neutral Happy"}},
        "profiles": {
            "acr": {"label": "ACR", "conditions": {
                "angry": {"onset_code": 11, "oddball_code": 55},
                "happy": {"onset_code": 13, "oddball_code": 55},
            }, "boundary_only_onset_codes": [12, 31], "boundary_labels": {"12": "Fear", "31": "Angry Neutral"}},
            "mcctr": {"label": "MCCTR", "conditions": {
                "angry": {"onset_code": 12, "oddball_code": 55},
                "happy": {"onset_code": 11, "oddball_code": 56},
            }, "boundary_only_onset_codes": [3]},
        },
        "recording_assignments": {"ACRP1": "acr", "MCCTRP1": "mcctr"},
        "registration_group_defaults": {"adolescents": "acr", "adults": "mcctr"},
    }


def _protocol():
    return FrequencyProtocol.from_recurrence(6, 5, expected_analyzed_oddball_cycles=144,
                                             expected_analyzed_oddball_cycles_source="manual")


def _manifest(protocol):
    return {
        "frequency_protocol": protocol.to_manifest(), "event_map": {},
        "groups": {"adolescents": {}, "adults": {}},
        "participants": {"ACRP1": {"group_id": "adolescents"}, "MCCTRP1": {"group_id": "adults"}},
    }


def test_native_codes_resolve_by_registered_identity_never_group_or_source_p1(payload):
    protocol = _protocol().with_condition_trigger_maps(payload)
    adolescent = resolve_recording_event_schema(protocol, "ACRP1")
    adult = resolve_recording_event_schema(protocol, "MCCTRP1")
    assert adolescent.event_map == {"Neutral Angry": 11, "Neutral Happy": 13}
    assert adult.event_map == {"Neutral Angry": 12, "Neutral Happy": 11}
    assert adolescent.canonical_condition_ids == adult.canonical_condition_ids == {"Neutral Angry": "angry", "Neutral Happy": "happy"}
    assert adolescent.boundary_only_onset_codes == (12, 31)
    assert adult.boundary_only_onset_codes == (3,)
    assert protocol.oddball_marker_code_for_condition(11, recording_id="MCCTRP1") == 56
    with pytest.raises((TriggerMapError, FrequencyProtocolError), match="assigned"):
        resolve_recording_event_schema(protocol, "P1")
    with pytest.raises(FrequencyProtocolError, match="canonical recording ID"):
        protocol.oddball_marker_code_for_condition(11)


def test_snapshots_are_detached_immutable_and_pickleable(payload):
    maps = ConditionTriggerMaps.from_manifest(payload)
    payload["profiles"]["acr"]["conditions"]["angry"]["onset_code"] = 99
    assert maps.resolve("ACRP1").event_map["Neutral Angry"] == 11
    snapshot = pickle.loads(pickle.dumps(maps.resolve("MCCTRP1")))
    assert snapshot == maps.resolve("MCCTRP1")
    snapshot.event_map["Neutral Angry"] = 999
    assert snapshot.event_map["Neutral Angry"] == 12
    with pytest.raises(FrozenInstanceError):
        maps.profiles = ()
    assert pickle.loads(pickle.dumps(_protocol().with_condition_trigger_maps(maps))).condition_trigger_maps == maps


def test_roundtrip_retains_cosmetics_but_semantic_projection_ignores_them(payload):
    original = _protocol().with_condition_trigger_maps(payload)
    changed = copy.deepcopy(payload)
    changed["profiles"]["acr"]["label"] = "Adolescent source"
    changed["profiles"]["acr"]["boundary_labels"]["12"] = "Neutral Fear"
    changed["registration_group_defaults"]["adults"] = "acr"
    cosmetic = _protocol().with_condition_trigger_maps(changed)
    assert original.fingerprint == cosmetic.fingerprint
    assert original.to_manifest() != cosmetic.to_manifest()
    assert FrequencyProtocol.from_manifest(cosmetic.to_manifest()) == cosmetic
    assert resolve_recording_event_schema(cosmetic, "MCCTRP1").profile_id == "mcctr"


@pytest.mark.parametrize("change", ["label", "code", "oddball", "boundary", "assignment"])
def test_scientific_changes_invalidate_whole_project_semantics(payload, change):
    original = _protocol().with_condition_trigger_maps(payload)
    if change == "label":
        payload["canonical_conditions"]["angry"]["label"] = "Angry faces"
    elif change == "code":
        payload["profiles"]["acr"]["conditions"]["angry"]["onset_code"] = 19
    elif change == "oddball":
        payload["profiles"]["acr"]["conditions"]["angry"]["oddball_code"] = 56
    elif change == "boundary":
        payload["profiles"]["acr"]["boundary_only_onset_codes"].append(41)
    else:
        payload["recording_assignments"]["ACRP1"] = "mcctr"
    changed = _protocol().with_condition_trigger_maps(payload)
    assert original.fingerprint != changed.fingerprint
    assert original.condition_trigger_maps.resolve("MCCTRP1").fingerprint != changed.condition_trigger_maps.resolve("MCCTRP1").fingerprint


@pytest.mark.parametrize("case", ["missing", "unknown", "duplicate_onset", "onset_odd", "boundary_selected", "boundary_odd", "fraction", "bool", "negative", "too_large", "duplicate_id", "unknown_assignment", "duplicate_label", "unsafe_label"])
def test_rejects_ambiguous_or_unsupported_maps(payload, case):
    profile = payload["profiles"]["acr"]
    if case == "missing":
        del profile["conditions"]["angry"]
    elif case == "unknown":
        profile["conditions"]["extra"] = {"onset_code": 45, "oddball_code": 55}
    elif case == "duplicate_onset":
        profile["conditions"]["happy"]["onset_code"] = 11
    elif case == "onset_odd":
        profile["conditions"]["happy"]["oddball_code"] = 11
    elif case == "boundary_selected":
        profile["boundary_only_onset_codes"].append(11)
    elif case == "boundary_odd":
        profile["boundary_only_onset_codes"].append(55)
    elif case in {"fraction", "bool", "negative", "too_large"}:
        profile["conditions"]["happy"]["onset_code"] = {"fraction": 1.2, "bool": True, "negative": -2, "too_large": 2147483648}[case]
    elif case == "duplicate_id":
        payload["recording_assignments"]["acrp1"] = "acr"
    elif case == "unknown_assignment":
        payload["recording_assignments"]["ACRP1"] = "unknown"
    elif case == "duplicate_label":
        payload["canonical_conditions"]["happy"]["label"] = "neutral angry"
    else:
        payload["canonical_conditions"]["happy"]["label"] = "../escape"
    with pytest.raises(TriggerMapError):
        ConditionTriggerMaps.from_manifest(payload)


def test_complete_assignment_coverage_includes_excluded_recordings_and_no_global_fallback(payload):
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    assert validate_project_trigger_maps(manifest) is not None
    manifest["participants"]["ACRP2"] = {"group_id": "adolescents"}
    manifest["preprocessing"] = {"manual_excluded_participants": ["ACRP2"]}
    with pytest.raises(TriggerMapError, match="missing.*acrp2"):
        validate_project_trigger_maps(manifest)
    del manifest["participants"]["ACRP2"]
    manifest["event_map"] = {"Neutral Angry": 11}
    with pytest.raises(TriggerMapError, match="active global event_map"):
        validate_project_trigger_maps(manifest)


def test_repeated_recording_assignments_use_recording_ids_not_person_ids(payload):
    payload["recording_assignments"] = {"ACRP1_visit1": "acr", "ACRP1_visit2": "acr", "MCCTRP1_visit1": "mcctr"}
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    manifest["recordings"] = {key: {} for key in payload["recording_assignments"]}
    assert validate_project_trigger_maps(manifest) is not None
    with pytest.raises(TriggerMapError):
        resolve_recording_event_schema(manifest, "ACRP1")


def test_mapped_version_refuses_downgrade_and_competing_marker_fields(payload):
    protocol = _protocol().with_condition_trigger_maps(payload)
    assert protocol.version == CONDITION_TRIGGER_MAPS_PROTOCOL_VERSION
    assert protocol.oddball_marker_code is None
    for field, value in (("version", "1.4.0"), ("oddball_marker_code", 55),
                         ("condition_oddball_marker_codes", {11: 55}),
                         ("recording_oddball_marker_codes", {"ACRP1": {11: 55}})):
        manifest = protocol.to_manifest()
        manifest[field] = value
        with pytest.raises(FrequencyProtocolError):
            FrequencyProtocol.from_manifest(manifest)
    with pytest.raises(FrequencyProtocolError, match="cannot be disabled"):
        protocol.with_condition_trigger_maps(None)
    with pytest.raises(FrequencyProtocolError, match="source trigger maps"):
        protocol.with_oddball_marker_code(55, source="manual")


def test_maps_preserved_by_duration_cycle_and_window_updates(payload):
    protocol = _protocol().with_condition_trigger_maps(payload)
    windowed = protocol.with_analyzed_duration(120, target_sampling_rate_hz=256)
    assert windowed.version == "1.5.0"
    assert windowed.condition_trigger_maps == protocol.condition_trigger_maps
    assert FrequencyProtocol.from_manifest(windowed.to_manifest()) == windowed
    cycles = windowed.with_expected_cycles(120, source="manual")
    assert cycles.version == "1.5.0"
    assert cycles.condition_trigger_maps == protocol.condition_trigger_maps
    assert cycles.analysis_window is None


def test_legacy_semantic_identity_exactly_preserved():
    protocol = _protocol()
    expected = {"version": "1.1.0", "status": "ready", "presentation_rate_hz": "6",
                "oddball_input_mode": "oddball_every_n", "oddball_every_n": 5,
                "oddball_rate_hz": "1.2", "expected_analyzed_oddball_cycles": 144,
                "expected_analyzed_oddball_cycles_source": "manual", "oddball_marker_code": 55,
                "oddball_marker_code_source": "manual"}
    assert protocol.canonical_payload() == expected
    assert protocol.fingerprint == hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert "condition_trigger_maps" not in protocol.to_manifest()
    legacy = {"frequency_protocol": protocol.to_manifest(), "event_map": {"Angry": 11}}
    assert [(item.condition_id, item.label) for item in project_conditions(legacy)] == [("Angry", "Angry")]
    assert resolve_recording_event_schema(legacy, "P1").event_map == {"Angry": 11}


def test_explicit_legacy_migration_preserves_distinct_recording_oddball_schemas():
    protocol = _protocol().with_recording_oddball_marker_codes({"ACRP1": {11: 55}, "MCCTRP1": {11: 56}})
    manifest = _manifest(protocol)
    manifest["event_map"] = {"Neutral Angry": 11}
    original = copy.deepcopy(manifest)
    maps = migrate_legacy_trigger_maps(manifest)
    assert len(maps.profiles) == 2
    assert maps.resolve("ACRP1").oddball_marker_codes == {11: 55}
    assert maps.resolve("MCCTRP1").oddball_marker_codes == {11: 56}
    draft = TriggerMapDraft.from_project(manifest)
    result = draft.apply_to_manifest(manifest)
    assert manifest == original
    assert result["event_map"] == {}
    assert result["tools"]["trigger_map_migration"]["legacy_event_map"] == original["event_map"]
    assert result["tools"]["trigger_map_migration"]["legacy_protocol"] == protocol.to_manifest()
    assert validate_project_trigger_maps(result) == maps


def test_draft_cancel_failed_validation_and_stale_baseline_leave_original_unchanged(payload):
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    original = copy.deepcopy(manifest)
    draft = TriggerMapDraft.from_project(manifest)
    draft.payload["profiles"]["acr"]["conditions"]["angry"]["onset_code"] = 13
    with pytest.raises(TriggerMapError):
        draft.apply_to_manifest(manifest)
    assert manifest == original
    draft = TriggerMapDraft.from_project(manifest)
    manifest["frequency_protocol"]["expected_analyzed_oddball_cycles"] = 120
    with pytest.raises(TriggerMapError, match="changed after"):
        draft.apply_to_manifest(manifest)


def test_empty_project_draft_can_be_edited_but_never_saved_incomplete():
    manifest = _manifest(_protocol())
    draft = TriggerMapDraft.from_project(manifest, allow_empty=True)
    assert draft.payload["canonical_conditions"] == {}
    with pytest.raises(TriggerMapError, match="at least one"):
        draft.apply_to_manifest(manifest)


def test_local_validation_uses_the_assigned_profile(payload):
    protocol = _protocol().with_condition_trigger_maps(payload)
    validate_protocol_condition_codes(protocol, [12, 11], recording_id="MCCTRP1")
    with pytest.raises(FrequencyProtocolError, match="assigned source"):
        validate_protocol_condition_codes(protocol, [11, 13], recording_id="MCCTRP1")
    with pytest.raises(FrequencyProtocolError):
        replace(protocol, condition_trigger_maps=None)


def _registered_project(tmp_path, payload):
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    manifest["source_studies"] = {"acr": {"label": "ACR"}, "mcctr": {"label": "MCCTR"}}
    for person, row in manifest["participants"].items():
        group = row["group_id"]
        source = "acr" if group == "adolescents" else "mcctr"
        folder = tmp_path / "Input" / group
        folder.mkdir(parents=True)
        (folder / "p1.bdf").write_bytes(b"native source bytes")
        row.update(raw_file=f"Input/{group}/p1.bdf", source_study_id=source, source_participant_id="P1")
        manifest["groups"][group] = {"label": group.title(), "folder_name": group.title(), "raw_input_folder": f"Input/{group}"}
    manifest["tools"] = {"processing": {"full_fft_provenance": {"status": "current"}}}
    (tmp_path / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    return Project.load(tmp_path)


def _append_kwargs(project):
    new_raw = project.project_root / "Input" / "adults" / "p2.bdf"
    new_raw.write_bytes(b"new source bytes")
    return {
        "participants": {"OTHERP1": {"group_id": "adults", "raw_file": str(new_raw),
                                     "source_study_id": "other", "source_participant_id": "P1"}},
        "recordings": {}, "source_studies": {"other": {"label": "Other source"}},
        "trigger_map_assignments": {"OTHERP1": "mcctr"},
        "expected_manifest_sha256": hashlib.sha256(project.manifest_path.read_bytes()).hexdigest(),
        "tool_namespace_updates": {},
    }


def test_reviewed_append_commits_new_identity_map_and_freshness_together(tmp_path, payload):
    project = _registered_project(tmp_path, payload)
    prior_fingerprint = project.frequency_protocol.fingerprint
    project.append_registered_inputs(**_append_kwargs(project))
    loaded = Project.load(tmp_path)
    assert loaded.participants == project.participants
    assert loaded.source_studies == project.source_studies
    assert loaded.frequency_protocol == project.frequency_protocol
    assert loaded.frequency_protocol.fingerprint != prior_fingerprint
    assert loaded.frequency_protocol.condition_trigger_maps.resolve("OTHERP1").profile_id == "mcctr"
    assert loaded.participants["OTHERP1"]["source_participant_id"] == loaded.participants["MCCTRP1"]["source_participant_id"] == "P1"
    assert loaded.manifest["tools"]["processing"]["full_fft_provenance"]["status"] == "stale"
    assert loaded.manifest["tools"]["processing"]["pipeline_setup_requirements"]["version"] == 1
    project.save()  # The successful append rebases the same open project's guard.


@pytest.mark.parametrize("case", ["missing_assignment", "unknown_profile", "replace_assignment", "replace_source", "save_failed"])
def test_reviewed_append_failures_leave_manifest_identity_and_maps_unchanged(tmp_path, payload, monkeypatch, case):
    project = _registered_project(tmp_path, payload)
    kwargs = _append_kwargs(project)
    prior_bytes = project.manifest_path.read_bytes()
    prior_state = copy.deepcopy(project.__dict__)
    if case == "missing_assignment":
        kwargs.pop("trigger_map_assignments")
    elif case == "unknown_profile":
        kwargs["trigger_map_assignments"]["OTHERP1"] = "missing"
    elif case == "replace_assignment":
        kwargs["trigger_map_assignments"]["ACRP1"] = "mcctr"
    elif case == "replace_source":
        kwargs["source_studies"]["acr"] = {"label": "New meaning"}
    else:
        import Main_App.projects.project as owner

        def fail(*args, **kwargs):
            raise OSError("simulated write failure")

        monkeypatch.setattr(owner, "_replace_reviewed_manifest", fail)
    with pytest.raises((ValueError, OSError)):
        project.append_registered_inputs(**kwargs)
    assert project.manifest_path.read_bytes() == prior_bytes
    assert project.__dict__ == prior_state


def test_project_save_invalidates_scientific_maps_but_not_cosmetic_defaults(tmp_path, payload):
    project = _registered_project(tmp_path, payload)
    maps = project.frequency_protocol.condition_trigger_maps.to_manifest()
    maps["profiles"]["acr"]["label"] = "Renamed source"
    maps["registration_group_defaults"]["adults"] = "acr"
    project.update_frequency_protocol(project.frequency_protocol.with_condition_trigger_maps(maps))
    project.save()
    saved = json.loads(project.manifest_path.read_text(encoding="utf-8"))
    assert saved["tools"]["processing"]["full_fft_provenance"]["status"] == "current"
    assert "pipeline_setup_requirements" not in saved["tools"]["processing"]
    maps["profiles"]["acr"]["conditions"]["angry"]["onset_code"] = 19
    project.update_frequency_protocol(project.frequency_protocol.with_condition_trigger_maps(maps))
    project.save()
    saved = json.loads(project.manifest_path.read_text(encoding="utf-8"))
    assert saved["tools"]["processing"]["full_fft_provenance"]["status"] == "stale"
    assert saved["tools"]["processing"]["pipeline_setup_requirements"]["version"] == 1


def test_stale_project_cannot_overwrite_new_source_maps(tmp_path, payload):
    first = _registered_project(tmp_path, payload)
    stale = Project.load(tmp_path)
    maps = first.frequency_protocol.condition_trigger_maps.to_manifest()
    maps["profiles"]["acr"]["conditions"]["angry"]["onset_code"] = 19
    first.update_frequency_protocol(first.frequency_protocol.with_condition_trigger_maps(maps))
    first.save()
    saved_bytes = first.manifest_path.read_bytes()
    stale.name = "A harmless edit in an old window"
    with pytest.raises(ValueError, match="changed after"):
        stale.save()
    assert first.manifest_path.read_bytes() == saved_bytes


@pytest.mark.parametrize("replacement", ["Angry faces", "neutral angry", "Neutral Happy"])
def test_draft_rename_remaps_both_exclusion_scopes_once_by_stable_id(payload, replacement):
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    manifest["preprocessing"] = {
        "manual_excluded_participant_conditions": {"ACRP1": ["NEUTRAL ANGRY", "Unselected"]},
        "manual_excluded_recording_conditions": {"visit1": ["Neutral Angry"], "visit2": ["Neutral Happy"]},
    }
    original = copy.deepcopy(manifest)
    draft = TriggerMapDraft.from_project(manifest)
    draft.payload["canonical_conditions"]["angry"]["label"] = replacement
    happy_label = "Neutral Happy"
    if replacement == happy_label:
        happy_label = "Neutral Angry"
        draft.payload["canonical_conditions"]["happy"]["label"] = happy_label
    result = draft.apply_to_manifest(manifest)
    assert manifest == original
    assert set(result["preprocessing"]["manual_excluded_participant_conditions"]["ACRP1"]) == {replacement, "Unselected"}
    assert result["preprocessing"]["manual_excluded_recording_conditions"] == {
        "visit1": [replacement], "visit2": [happy_label],
    }
    assert TriggerMapDraft.from_project(result).apply_to_manifest(result) == result


def _remove_or_replace_condition(payload, *, replace_id):
    old = payload["canonical_conditions"].pop("angry")
    if replace_id:
        payload["canonical_conditions"]["different_meaning"] = old
    for profile in payload["profiles"].values():
        triggers = profile["conditions"].pop("angry")
        if replace_id:
            profile["conditions"]["different_meaning"] = triggers


@pytest.mark.parametrize("scope", ["manual_excluded_participant_conditions", "manual_excluded_recording_conditions"])
@pytest.mark.parametrize("replace_id", [False, True])
def test_referenced_condition_cannot_be_deleted_or_replaced_with_same_label(payload, scope, replace_id):
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    manifest["preprocessing"] = {scope: {"owner": ["Neutral Angry"]}}
    original = copy.deepcopy(manifest)
    draft = TriggerMapDraft.from_project(manifest)
    _remove_or_replace_condition(draft.payload, replace_id=replace_id)
    with pytest.raises(TriggerMapError, match="saved exclusions.*cannot be removed"):
        draft.apply_to_manifest(manifest)
    assert manifest == original


def test_unreferenced_condition_can_be_removed_without_changing_other_exclusions(payload):
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    manifest["preprocessing"] = {"manual_excluded_participant_conditions": {"ACRP1": ["Neutral Happy"]}}
    draft = TriggerMapDraft.from_project(manifest)
    _remove_or_replace_condition(draft.payload, replace_id=False)
    result = draft.apply_to_manifest(manifest)
    assert result["preprocessing"] == manifest["preprocessing"]
    assert {item.condition_id for item in project_conditions(result)} == {"happy"}


def test_historical_unknown_exclusion_cannot_transfer_to_a_new_catalog_label(payload):
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    manifest["preprocessing"] = {"manual_excluded_participant_conditions": {"ACRP1": ["Old removed condition"]}}
    draft = TriggerMapDraft.from_project(manifest)
    draft.payload["canonical_conditions"]["angry"]["label"] = "Old removed condition"
    with pytest.raises(TriggerMapError, match="no condition ID in the previous catalog"):
        draft.apply_to_manifest(manifest)


def test_accepted_electrode_repair_is_not_silently_moved_to_a_new_label(payload):
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    manifest["tools"] = {"condition_electrode_interpolation": {"requests": {"ACRP1": {"Neutral Angry": ["O1"]}}}}
    draft = TriggerMapDraft.from_project(manifest)
    draft.payload["canonical_conditions"]["angry"]["label"] = "Angry faces"
    with pytest.raises(TriggerMapError, match="saved condition-electrode repair requests"):
        draft.apply_to_manifest(manifest)


def test_legacy_opt_in_rename_preserves_explicit_exclusion():
    manifest = _manifest(_protocol())
    manifest["event_map"] = {"Neutral Angry": 11, "Neutral Happy": 13}
    manifest["preprocessing"] = {"manual_excluded_participant_conditions": {"ACRP1": ["Neutral Angry"]}}
    draft = TriggerMapDraft.from_project(manifest)
    draft.payload["canonical_conditions"]["neutral_angry"]["label"] = "Angry faces"
    result = draft.apply_to_manifest(manifest)
    assert result["preprocessing"]["manual_excluded_participant_conditions"] == {"ACRP1": ["Angry faces"]}


def test_alias_exclusions_are_resolved_before_a_catalog_rename(payload):
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    manifest["preprocessing"] = {"excluded_participant_conditions": {"ACRP1": ["Neutral Angry"]}}
    draft = TriggerMapDraft.from_project(manifest)
    draft.payload["canonical_conditions"]["angry"]["label"] = "Angry faces"
    result = draft.apply_to_manifest(manifest)
    assert result["preprocessing"]["manual_excluded_participant_conditions"] == {"ACRP1": ["Angry faces"]}


def test_removal_rejection_cannot_be_bypassed_by_clearing_exclusions_in_same_candidate(payload):
    from Main_App.projects.condition_trigger_maps import apply_condition_catalog_transition
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    manifest["preprocessing"] = {"manual_excluded_participant_conditions": {"ACRP1": ["Neutral Angry"]}}
    updated = copy.deepcopy(payload)
    _remove_or_replace_condition(updated, replace_id=True)
    candidate = copy.deepcopy(manifest)
    candidate["preprocessing"]["manual_excluded_participant_conditions"] = {}
    candidate["frequency_protocol"] = _protocol().with_condition_trigger_maps(updated).to_manifest()
    before = copy.deepcopy(candidate)
    with pytest.raises(TriggerMapError, match="separate save"):
        apply_condition_catalog_transition(candidate, manifest)
    assert candidate == before


def test_renamed_catalog_rejects_prior_processing_receipts(tmp_path, payload):
    from Main_App.processing.pipeline_settings_freshness import (
        PipelineSettingsChangedError, apply_pipeline_setup_freshness,
        pipeline_settings_identity, require_current_pipeline_settings,
    )
    project = _registered_project(tmp_path, payload)
    previous = copy.deepcopy(project.manifest)
    draft = TriggerMapDraft.from_project(previous)
    draft.payload["canonical_conditions"]["angry"]["label"] = "Angry faces"
    candidate = draft.apply_to_manifest(previous)
    assert apply_pipeline_setup_freshness(candidate, previous)
    ledger = {"entries": {identity: {
        "status": "completed", "participant_id": identity,
        "pipeline_settings_identity": pipeline_settings_identity(previous),
    } for identity in project.participants}}
    with pytest.raises(PipelineSettingsChangedError, match="settings changed"):
        require_current_pipeline_settings(tmp_path, ledger=ledger, manifest=candidate)


def test_draft_uses_latest_exclusions_at_atomic_transition(payload):
    manifest = _manifest(_protocol().with_condition_trigger_maps(payload))
    draft = TriggerMapDraft.from_project(manifest)
    draft.payload["canonical_conditions"]["angry"]["label"] = "Angry faces"
    manifest["preprocessing"] = {"manual_excluded_participant_conditions": {"ACRP1": ["Neutral Angry"]}}
    result = draft.apply_to_manifest(manifest)
    assert result["preprocessing"]["manual_excluded_participant_conditions"] == {"ACRP1": ["Angry faces"]}


@pytest.mark.parametrize("swap", [False, True])
def test_project_save_transitions_exclusions_then_rebases_without_double_remap(tmp_path, payload, swap):
    project = _registered_project(tmp_path, payload)
    project.update_preprocessing({**project.preprocessing, "manual_excluded_participant_conditions": {
        "ACRP1": ["Neutral Angry"], "MCCTRP1": ["Neutral Happy"],
    }})
    project.save()
    updated = copy.deepcopy(payload)
    updated["canonical_conditions"]["angry"]["label"] = "Neutral Happy" if swap else "Angry faces"
    if swap:
        updated["canonical_conditions"]["happy"]["label"] = "Neutral Angry"
    project.update_frequency_protocol(project.frequency_protocol.with_condition_trigger_maps(updated))
    project.save()
    expected = {
        "ACRP1": ["Neutral Happy" if swap else "Angry faces"],
        "MCCTRP1": ["Neutral Angry" if swap else "Neutral Happy"],
    }
    assert project.preprocessing["manual_excluded_participant_conditions"] == expected
    project.save()
    assert Project.load(tmp_path).preprocessing["manual_excluded_participant_conditions"] == expected


def test_failed_project_write_does_not_publish_remapped_exclusions(tmp_path, payload, monkeypatch):
    import Main_App.projects.project as owner
    project = _registered_project(tmp_path, payload)
    project.update_preprocessing({**project.preprocessing, "manual_excluded_participant_conditions": {"ACRP1": ["Neutral Angry"]}})
    project.save()
    before = project.manifest_path.read_bytes()
    updated = copy.deepcopy(payload)
    updated["canonical_conditions"]["angry"]["label"] = "Angry faces"
    project.update_frequency_protocol(project.frequency_protocol.with_condition_trigger_maps(updated))

    def fail(*args, **kwargs):
        raise OSError("simulated failed write")

    monkeypatch.setattr(owner, "_write_manifest_if_changed", fail)
    with pytest.raises(OSError, match="simulated failed write"):
        project.save()
    assert project.manifest_path.read_bytes() == before
    assert project.preprocessing["manual_excluded_participant_conditions"] == {"ACRP1": ["Neutral Angry"]}


def test_project_save_rejects_replacing_an_excluded_condition_id(tmp_path, payload):
    project = _registered_project(tmp_path, payload)
    project.update_preprocessing({**project.preprocessing, "manual_excluded_participant_conditions": {"ACRP1": ["Neutral Angry"]}})
    project.save()
    before = project.manifest_path.read_bytes()
    updated = copy.deepcopy(payload)
    _remove_or_replace_condition(updated, replace_id=True)
    project.update_frequency_protocol(project.frequency_protocol.with_condition_trigger_maps(updated))
    with pytest.raises(TriggerMapError, match="different condition ID"):
        project.save()
    assert project.manifest_path.read_bytes() == before


@pytest.mark.parametrize("second_label", ["Faces", "faces"])
def test_catalog_rejects_labels_sharing_normalized_output_folder(payload, second_label):
    payload["canonical_conditions"]["angry"]["label"] = "1 - Faces"
    payload["canonical_conditions"]["happy"]["label"] = second_label
    with pytest.raises(TriggerMapError, match="same output name"):
        ConditionTriggerMaps.from_manifest(payload)
