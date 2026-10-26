from __future__ import annotations

import json
from pathlib import Path

import pytest

from Main_App.projects.project import Project
from Main_App.projects.raw_identity import (
    propose_source_participant_id,
    registered_raw_identities,
    resolve_registered_raw_identity,
)
from Main_App.processing.dataset_exclusions import load_dataset_exclusions
from Main_App.processing.processing_controller import prepare_batch_file_infos


def combined_project(tmp_path):
    groups = {}
    participants = {}
    for source, group in (("acr", "adolescents"), ("mcctr", "adults")):
        folder = tmp_path / "Input" / group
        folder.mkdir(parents=True)
        raw = folder / "P1.bdf"
        raw.write_bytes(b"unchanged raw fixture")
        groups[group] = {"label": group.title(), "folder_name": group.title(), "raw_input_folder": str(folder)}
        participants[source.upper() + "P1"] = {
            "group_id": group, "raw_file": str(raw), "source_study_id": source,
            "source_participant_id": "P1", "display_label": source.upper() + " / P1",
        }
    project = Project(tmp_path, {"groups": groups, "participants": participants,
                               "source_studies": {"acr": {"label": "ACR"}, "mcctr": {"label": "MCCTR"}}})
    project.save()
    return project


def test_two_source_p1s_roundtrip_discover_and_exclude_independently(tmp_path):
    project = combined_project(tmp_path)
    project.preprocessing["manual_excluded_participants"] = ["ACRP1"]
    project.save()
    loaded = Project.load(tmp_path)
    assert loaded.source_studies == project.source_studies
    assert loaded.participants == project.participants
    records = registered_raw_identities(loaded)
    assert {row.participant_id for row in records.values()} == {"ACRP1", "MCCTRP1"}
    assert {row.source_participant_id for row in records.values()} == {"P1"}
    assert {row.subject_id for row in prepare_batch_file_infos(loaded)} == {"ACRP1", "MCCTRP1"}
    snapshot = load_dataset_exclusions(tmp_path)
    by_person = {row.participant_id: row for row in snapshot.rows}
    assert by_person["ACRP1"].scope == "skip_processing"
    assert by_person["MCCTRP1"].scope == "include"
    manifest = json.loads(loaded.manifest_path.read_text(encoding="utf-8"))
    assert Path(manifest["participants"]["ACRP1"]["raw_file"]) == Path("Input/adolescents/P1.bdf")
    assert resolve_registered_raw_identity(manifest, tmp_path / "Input/adults/P1.bdf", project_root=tmp_path).participant_id == "MCCTRP1"


def test_source_identity_validation_rejects_partial_unknown_or_duplicate(tmp_path):
    project = combined_project(tmp_path)
    project.participants["ACRP1"].pop("source_participant_id")
    with pytest.raises(ValueError, match="both source"):
        project.save()
    project.participants["ACRP1"]["source_participant_id"] = "P1"
    project.participants["ACRP1"]["source_study_id"] = "missing"
    with pytest.raises(ValueError, match="unknown source"):
        project.save()
    project.participants["ACRP1"]["source_study_id"] = "mcctr"
    with pytest.raises(ValueError, match="assigned to both"):
        project.save()


def test_source_id_proposal_preserves_zeros_and_rejects_sanitized_collisions():
    assert propose_source_participant_id("acr", "P01") == "ACRP01"
    assert propose_source_participant_id("mcctr", "P1", ["ACRP1"]) == "MCCTRP1"
    with pytest.raises(ValueError, match="collides"):
        propose_source_participant_id("acr", "P1", ["ACR_P1"])


def test_legacy_project_does_not_gain_source_metadata(tmp_path):
    project = Project.load(tmp_path)
    project.save()
    assert "source_studies" not in json.loads(project.manifest_path.read_text(encoding="utf-8"))
