"""Source editor state and publication checks that do not instantiate Qt."""

from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.gui.project_protocol import build_manual_protocol
from Main_App.gui.trigger_maps_model import trigger_map_changes, trigger_map_editor_payload, trigger_recording_rows, validated_editor_maps
from Main_App.projects import FrequencyProtocol, ODDBALL_INPUT_MODE_RECURRENCE, Project, TriggerMapDraft
from Main_App.projects.manifest_store import project_manifest_transaction
from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings
from Main_App.processing.pipeline_settings_freshness import apply_pipeline_setup_freshness


@pytest.fixture
def mapped_project(tmp_path):
    project = Project.load(tmp_path)
    project.event_map = {"Angry": 11}
    project.groups = {
        "adolescents": {"label": "Adolescents", "output_folder": "Adolescents", "raw_input_folder": tmp_path / "Input" / "Adolescents"},
        "adults": {"label": "Adults", "output_folder": "Adults", "raw_input_folder": tmp_path / "Input" / "Adults"},
    }
    project.source_studies = {"acr": {"label": "ACR"}, "mcctr": {"label": "MCCTR"}}
    project.participants = {
        "ACRP1": {"group_id": "adolescents", "raw_file": "Input/Adolescents/p1.bdf", "source_study_id": "acr", "source_participant_id": "P1"},
        "MCCTRP1": {"group_id": "adults", "raw_file": "Input/Adults/p1.bdf", "source_study_id": "mcctr", "source_participant_id": "P1"},
    }
    project.update_frequency_protocol(FrequencyProtocol.from_recurrence(6, 5, expected_analyzed_oddball_cycles=144, expected_analyzed_oddball_cycles_source="manual"))
    project.save()
    maps = trigger_map_editor_payload(project)
    maps["profiles"]["adult"] = deepcopy(maps["profiles"]["source_1"])
    maps["profiles"]["adult"]["conditions"]["angry"]["onset_code"] = 12
    maps["recording_assignments"]["MCCTRP1"] = "adult"
    project.event_map = {}
    project.update_frequency_protocol(project.frequency_protocol.with_condition_trigger_maps(maps))
    project.save()
    return project


def test_two_source_p1_editor_rows_keep_canonical_ids(mapped_project):
    rows = trigger_recording_rows(mapped_project)
    assert {(row.recording_id, row.original_id, row.source_study) for row in rows} == {
        ("ACRP1", "P1", "ACR"), ("MCCTRP1", "P1", "MCCTR"),
    }


def test_qc_display_labels_keep_source_people_distinct_and_legacy_unchanged(mapped_project):
    from Main_App.gui.recording_qc_identity import participant_identity_label
    assert participant_identity_label("ACRP1", mapped_project) == "ACRP1 · ACR / P1"
    assert participant_identity_label("MCCTRP1", mapped_project.manifest) == "MCCTRP1 · MCCTR / P1"
    assert participant_identity_label("P01", {"participants": {"P01": {}}}) == "P01"
    assert participant_identity_label("P01") == "P01"


def test_saved_or_pending_source_maps_route_old_recording_editor_to_unified_editor(mapped_project):
    path = Path(__file__).resolve().parents[2] / "src/Main_App/gui/settings_panel.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog")
    method = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "_configure_recording_marker_schemas")
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    panel = SimpleNamespace(project=mapped_project, _trigger_maps_payload={}, _configure_trigger_maps=Mock())
    namespace[method.name](panel)
    panel._configure_trigger_maps.assert_called_once_with()


def test_editor_payload_cancel_and_group_default_are_detached(mapped_project):
    payload = trigger_map_editor_payload(mapped_project)
    before = deepcopy(payload)
    payload["registration_group_defaults"]["adults"] = "source_1"
    maps = validated_editor_maps(mapped_project, payload)
    assert dict(maps.recording_assignments)["MCCTRP1"] == "adult"
    assert mapped_project.frequency_protocol.condition_trigger_maps.to_manifest() == before
    assert len(trigger_map_changes(before, payload)) == 1


def test_timing_editor_preserves_source_maps_without_shared_marker(mapped_project):
    protocol = build_manual_protocol(
        presentation_rate_hz="6", oddball_input_mode=ODDBALL_INPUT_MODE_RECURRENCE, oddball_every_n="5",
        oddball_rate_hz="", expected_analyzed_oddball_cycles="144", oddball_marker_code="",
        existing_protocol=mapped_project.frequency_protocol, require_ready=True,
    )
    assert protocol.fingerprint == mapped_project.frequency_protocol.fingerprint
    assert protocol.oddball_marker_code is None


def _save_draft_function():
    path = Path(__file__).resolve().parents[2] / "src/Main_App/gui/trigger_maps_workflow.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "save_trigger_map_draft")
    namespace = dict(deepcopy=deepcopy, json=json, project_manifest_transaction=project_manifest_transaction,
                     apply_pipeline_setup_freshness=apply_pipeline_setup_freshness,
                     normalize_preprocessing_settings=normalize_preprocessing_settings)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["save_trigger_map_draft"]


def test_home_save_rebases_project_and_stale_draft_rejected(mapped_project):
    save = _save_draft_function()
    draft = TriggerMapDraft.from_project(mapped_project)
    stale = TriggerMapDraft.from_project(mapped_project)
    draft.payload["profiles"]["adult"]["conditions"]["angry"]["onset_code"] = 14
    save(mapped_project, draft)
    assert Project.load(mapped_project.project_root).frequency_protocol.fingerprint == mapped_project.frequency_protocol.fingerprint
    mapped_project.save()  # Must not reject the editor's own successful transaction.
    with pytest.raises(ValueError, match="changed"):
        save(mapped_project, stale)


def test_home_failed_publication_leaves_live_and_disk_unchanged(mapped_project, monkeypatch):
    from Main_App.projects import manifest_store
    draft = TriggerMapDraft.from_project(mapped_project)
    draft.payload["profiles"]["adult"]["conditions"]["angry"]["onset_code"] = 14
    before = mapped_project.manifest_path.read_bytes()
    protocol = mapped_project.frequency_protocol
    preprocessing = deepcopy(mapped_project.preprocessing)
    monkeypatch.setattr(manifest_store.ManifestTransaction, "write", lambda *_: (_ for _ in ()).throw(OSError("disk unavailable")))
    with pytest.raises(OSError, match="disk unavailable"):
        _save_draft_function()(mapped_project, draft)
    assert mapped_project.frequency_protocol is protocol
    assert mapped_project.preprocessing == preprocessing
    assert mapped_project.manifest_path.read_bytes() == before


@pytest.mark.parametrize("new_labels", [("Threat", "Happy"), ("Happy", "Angry")])
def test_home_condition_rename_or_swap_rebases_exclusions_before_later_save(mapped_project, new_labels):
    maps = mapped_project.frequency_protocol.condition_trigger_maps.to_manifest()
    mapped_project.sessions = {"visit1": {"label": "Visit 1", "visit_index": 1}}
    mapped_project.recording_sources = {}
    mapped_project.recordings = {}
    for participant_id, participant in mapped_project.participants.items():
        source_id = f"{participant['group_id']}_visit1"
        recording_id = f"{participant_id}_visit1"
        mapped_project.recording_sources[source_id] = {
            "group_id": participant["group_id"], "session_id": "visit1",
            "raw_input_folder": mapped_project.groups[participant["group_id"]]["raw_input_folder"],
        }
        mapped_project.recordings[recording_id] = {
            "participant_id": participant_id, "session_id": "visit1", "source_id": source_id,
            "raw_file": participant["raw_file"], "visit_index": 1,
        }
    maps["recording_assignments"] = {f"{participant_id}_visit1": profile_id for participant_id, profile_id in maps["recording_assignments"].items()}
    maps["canonical_conditions"]["happy"] = {"label": "Happy"}
    for profile in maps["profiles"].values():
        profile["conditions"]["happy"] = {"onset_code": 21, "oddball_code": 55}
    mapped_project.update_frequency_protocol(mapped_project.frequency_protocol.with_condition_trigger_maps(maps))
    mapped_project.save()
    mapped_project.update_preprocessing({
        **mapped_project.preprocessing,
        "manual_excluded_participant_conditions": {"ACRP1": ["Angry"], "MCCTRP1": ["Happy"]},
        "manual_excluded_recording_conditions": {"ACRP1_visit1": ["Angry"], "MCCTRP1_visit1": ["Happy"]},
    })
    mapped_project.save()
    draft = TriggerMapDraft.from_project(mapped_project)
    for condition_id, label in zip(("angry", "happy"), new_labels, strict=True):
        draft.payload["canonical_conditions"][condition_id]["label"] = label

    _save_draft_function()(mapped_project, draft)

    expected_by_key = {
        "manual_excluded_participant_conditions": {"ACRP1": [new_labels[0]], "MCCTRP1": [new_labels[1]]},
        "manual_excluded_recording_conditions": {"ACRP1_visit1": [new_labels[0]], "MCCTRP1_visit1": [new_labels[1]]},
    }
    for key, expected in expected_by_key.items():
        assert mapped_project.preprocessing[key] == expected
    mapped_project.name = "Harmless later project save"
    mapped_project.save()
    reopened = Project.load(mapped_project.project_root)
    for key, expected in expected_by_key.items():
        assert reopened.preprocessing[key] == expected
