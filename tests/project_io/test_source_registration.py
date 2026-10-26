"""Source identity and trigger assignments commit together before discovery."""

from copy import deepcopy
from pathlib import Path

import pytest

from Main_App.projects import FrequencyProtocol, Project
from Main_App.projects.raw_identity import propose_source_participant_id, registered_raw_identities
from Main_App.projects.source_registration import prepare_source_registration_review, commit_source_registration_review


@pytest.fixture
def project(tmp_path):
    project = Project.load(tmp_path)
    project.groups = {}
    project.source_studies = {"acr": {"label": "ACR"}, "mcctr": {"label": "MCCTR"}}
    project.participants = {}
    profiles, assignments = {}, {}
    for group, source, onset in (("adolescents", "acr", 11), ("adults", "mcctr", 12)):
        folder = tmp_path / group
        folder.mkdir()
        (folder / "p1.bdf").write_bytes(b"original source bytes")
        (folder / "p2.bdf").write_bytes(b"new source bytes")
        project.groups[group] = {"label": group, "output_folder": group, "raw_input_folder": folder}
        ident = propose_source_participant_id(source, "P1")
        project.participants[ident] = {"group_id": group, "raw_file": folder / "p1.bdf", "source_study_id": source, "source_participant_id": "P1"}
        profiles[source] = {"conditions": {"angry": {"onset_code": onset, "oddball_code": 55}}, "boundary_only_onset_codes": []}
        assignments[ident] = source
    protocol = FrequencyProtocol.from_recurrence(6, 5, expected_analyzed_oddball_cycles=144, expected_analyzed_oddball_cycles_source="manual")
    project.update_frequency_protocol(protocol.with_condition_trigger_maps({"schema_version": "1.0", "canonical_conditions": {"angry": {"label": "Angry"}}, "profiles": profiles, "recording_assignments": assignments}))
    project.groups_locked = True
    project.save()
    return project


def reviewed_rows(review):
    rows = review.editor_rows()
    for row in rows:
        if not row["existing"]:
            row["participant_id"] = propose_source_participant_id(row["source_study_id"], row["source_participant_id"])
    return rows


def test_same_p2_from_two_sources_allocates_before_discovery_and_appends_locked(project):
    before = deepcopy(project.participants)
    raw_bytes = {path: path.read_bytes() for path in Path(project.project_root).glob("*/p*.bdf")}
    review = prepare_source_registration_review(project)
    assert review.requires_source_review
    assert len(review.additions) == 2
    rows = reviewed_rows(review)
    assignments = {row["participant_id"]: row["source_study_id"] for row in rows if not row["existing"]}
    assert commit_source_registration_review(project, review, rows, trigger_map_assignments=assignments)
    assert set(project.participants) == {"ACRP1", "MCCTRP1", "ACRP2", "MCCTRP2"}
    assert {key: project.participants[key] for key in before} == before
    assert project.groups_locked
    reopened = Project.load(project.project_root)
    assert set(reopened.participants) == set(project.participants)
    assert reopened.frequency_protocol.condition_trigger_maps.resolve("ACRP2").event_map == {"Angry": 11}
    assert reopened.frequency_protocol.condition_trigger_maps.resolve("MCCTRP2").event_map == {"Angry": 12}
    assert len(registered_raw_identities(reopened)) == 4
    assert all(path.read_bytes() == data for path, data in raw_bytes.items())


def test_cancel_and_missing_assignment_leave_registry_unchanged(project):
    before = project.manifest_path.read_bytes()
    participants = deepcopy(project.participants)
    review = prepare_source_registration_review(project)
    rows = reviewed_rows(review)
    assert project.manifest_path.read_bytes() == before
    with pytest.raises(ValueError, match="every new"):
        commit_source_registration_review(project, review, rows)
    assert project.manifest_path.read_bytes() == before
    assert project.participants == participants


def test_changed_source_folder_rejects_stale_review(project):
    review = prepare_source_registration_review(project)
    (project.project_root / "adults" / "p3.bdf").write_bytes(b"late recording")
    with pytest.raises(ValueError, match="changed"):
        commit_source_registration_review(project, review, reviewed_rows(review))
    assert len(project.participants) == 2


def test_single_selection_does_not_register_other_new_recording(project):
    review = prepare_source_registration_review(project, selected_path=project.project_root / "adults" / "p2.bdf")
    assert len(review.additions) == 1
    rows = reviewed_rows(review)
    commit_source_registration_review(project, review, rows, trigger_map_assignments={"MCCTRP2": "mcctr"})
    assert "MCCTRP2" in project.participants and "ACRP2" not in project.participants


@pytest.mark.parametrize("colliding_id", ["ACR_P1", "ÁACRP1"])
def test_identity_collision_does_not_silently_suffix_or_rekey(project, colliding_id):
    review = prepare_source_registration_review(project)
    rows = reviewed_rows(review)
    new = next(row for row in rows if not row["existing"])
    new["participant_id"] = colliding_id
    with pytest.raises(ValueError, match="collides"):
        commit_source_registration_review(project, review, rows)
    assert set(project.participants) == {"ACRP1", "MCCTRP1"}


def test_disk_failure_preserves_live_registry_and_maps(project, monkeypatch):
    from Main_App.projects import project as owner
    review = prepare_source_registration_review(project)
    rows = reviewed_rows(review)
    before = deepcopy(vars(project))
    before_bytes = project.manifest_path.read_bytes()
    monkeypatch.setattr(owner, "_replace_reviewed_manifest", lambda *_: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        commit_source_registration_review(project, review, rows, trigger_map_assignments={"ACRP2": "acr", "MCCTRP2": "mcctr"})
    assert vars(project) == before
    assert project.manifest_path.read_bytes() == before_bytes


def test_legacy_participant_without_raw_registration_keeps_normal_workflow(tmp_path):
    project = Project.load(tmp_path)
    project.participants = {"P1": {}}
    project.save()
    project.input_folder.mkdir(parents=True, exist_ok=True)
    (project.input_folder / "p1.bdf").write_bytes(b"source")
    before = project.manifest_path.read_bytes()
    review = prepare_source_registration_review(project)
    assert not review.requires_source_review
    assert project.manifest_path.read_bytes() == before
