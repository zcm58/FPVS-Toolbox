from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from Main_App.projects import (
    PROJECT_SCHEMA_VERSION,
    REPEATED_SESSION_PROJECT_SCHEMA_VERSION,
    Project,
    RecordingConfigurationError,
    load_project_recording_context,
    project_recording_context,
)
from Main_App.processing.interpolation_burden import (
    INTERPOLATION_BURDEN_DECISION_RETAIN,
    InterpolationBurdenReviewFinding,
    build_interpolation_burden_review_decision,
)


def _repeated_manifest(project_root: Path) -> dict[str, object]:
    return {
        "groups": {
            "birth_control": {
                "label": "Birth Control",
                "folder_name": "Birth Control",
                "raw_input_folder": "Raw/Birth Control",
            },
            "control": {
                "label": "No Birth Control",
                "folder_name": "Control",
                "raw_input_folder": "Raw/Control",
            },
        },
        "sessions": {
            "luteal": {"label": "Luteal", "visit_index": 1},
            "follicular": {"label": "Follicular", "visit_index": 2},
        },
        "recording_sources": {
            "bc_luteal": {
                "group_id": "birth_control",
                "session_id": "luteal",
                "raw_input_folder": "Raw/Birth Control/Luteal",
            },
            "bc_follicular": {
                "group_id": "birth_control",
                "session_id": "follicular",
                "raw_input_folder": "Raw/Birth Control/Follicular",
            },
            "control_luteal": {
                "group_id": "control",
                "session_id": "luteal",
                "raw_input_folder": "Raw/Control/Luteal",
            },
        },
        "participants": {
            "P01": {"group_id": "birth_control"},
            "P02": {"group_id": "control"},
        },
        "recordings": {
            "P01__luteal": {
                "participant_id": "P01",
                "session_id": "luteal",
                "source_id": "bc_luteal",
                "raw_file": "Raw/Birth Control/Luteal/P01_BC_L.bdf",
                "visit_index": 1,
                "days_from_baseline": 0,
            },
            "P01__follicular": {
                "participant_id": "P01",
                "session_id": "follicular",
                "source_id": "bc_follicular",
                "raw_file": "Raw/Birth Control/Follicular/P01_BC_F.bdf",
                "visit_index": 2,
                "days_from_baseline": 14,
            },
            "P02__luteal": {
                "participant_id": "P02",
                "session_id": "luteal",
                "source_id": "control_luteal",
                "raw_file": "Raw/Control/Luteal/P02_C_L.bdf",
                "visit_index": 1,
            },
        },
    }


def _registration_project(tmp_path: Path, *, locked: bool = True) -> Project:
    root = tmp_path / "Project"
    root.mkdir()
    manifest = _repeated_manifest(root)
    manifest["recordings"].pop("P01__follicular")
    manifest["recordings"]["P01__luteal"]["audit_note"] = "preserve verbatim"
    manifest["groups_locked"] = locked
    if locked:
        manifest["groups_locked_at"] = "2026-08-18T22:57:13Z"
    manifest["tools"] = {"unrelated": {"saved": True}, "processing": {"other": 42}}
    (root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    return Project(root, manifest)


def _new_visit(project: Project, participant: str = "P01") -> dict[str, object]:
    raw_file = project.recording_sources["bc_follicular"]["raw_input_folder"] / f"{participant}_BC_F.bdf"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.touch()
    return {
        "participant_id": participant, "session_id": "follicular",
        "source_id": "bc_follicular", "raw_file": raw_file, "visit_index": 2,
    }


def _registration_options(project: Project) -> dict[str, object]:
    return {
        "expected_manifest_sha256": hashlib.sha256(project.manifest_path.read_bytes()).hexdigest(),
        "tool_namespace_updates": {
            "frequency_domain_qc": {"downstream_outputs_stale": True, "stale_reason": "New inputs registered."},
            "processing": {"other": 42, "full_fft_provenance": {"status": "stale"}},
        },
    }


@pytest.mark.parametrize("locked", [False, True])
def test_approved_append_preserves_existing_entries_lock_and_updates_freshness(
    tmp_path: Path, locked: bool,
) -> None:
    project = _registration_project(tmp_path, locked=locked)
    before = json.loads(project.manifest_path.read_bytes())
    existing_visit = _new_visit(project)
    new_participant_visit = _new_visit(project, "P03")
    # The shell may retain this display-only compatibility field after save.
    project.input_folder = project.project_root / "Input"
    project.append_registered_inputs(
        participants={"P03": {"group_id": "birth_control"}},
        recordings={"P01__follicular": existing_visit, "P03__follicular": new_participant_visit},
        **_registration_options(project),
    )
    saved = json.loads(project.manifest_path.read_bytes())
    for name in ("groups", "sessions", "recording_sources", "groups_locked"):
        assert saved[name] == before[name]
    assert saved.get("groups_locked_at") == before.get("groups_locked_at")
    for name in ("participants", "recordings"):
        for key, entry in before[name].items():
            assert saved[name][key] == entry
    assert project.recordings["P01__follicular"]["raw_file"] == existing_visit["raw_file"]
    assert project.participants["P03"] == {"group_id": "birth_control"}
    assert saved["tools"]["unrelated"] == {"saved": True}
    assert saved["tools"]["processing"]["other"] == 42
    assert saved["tools"]["processing"]["full_fft_provenance"]["status"] == "stale"
    assert saved["tools"]["frequency_domain_qc"]["downstream_outputs_stale"] is True
    assert Project(project.project_root, saved).recordings == project.recordings
    if locked:
        assert saved["recordings_lock_fingerprint"] == project._recordings_lock_fingerprint
        project.recordings["P01__follicular"]["days_from_baseline"] = 99
        with pytest.raises(ValueError, match="Locked project session"):
            project.save()


@pytest.mark.parametrize("name", [
    "groups", "participants", "sessions", "recording_sources", "recordings",
    "groups_locked", "groups_locked_at",
])
def test_approved_append_rejects_unsaved_layout_or_registry_drift(tmp_path: Path, name: str) -> None:
    project = _registration_project(tmp_path)
    visit = _new_visit(project)
    before = project.manifest_path.read_bytes()
    if name == "groups_locked":
        project.groups_locked = False
    elif name == "groups_locked_at":
        project.groups_locked_at = "different"
    else:
        getattr(project, name).clear()
    state = deepcopy(project.__dict__)
    with pytest.raises(ValueError, match="changed before registration"):
        project.append_registered_inputs(
            participants={}, recordings={"P01__follicular": visit}, **_registration_options(project),
        )
    assert project.manifest_path.read_bytes() == before
    assert project.__dict__ == state


@pytest.mark.parametrize("case", [
    "existing-recording", "case-recording", "existing-participant", "case-participant",
    "group-drift", "duplicate-session", "duplicate-path", "wrong-source", "missing-file",
])
def test_approved_append_rejects_conflicting_inputs_without_writes(tmp_path: Path, case: str) -> None:
    project = _registration_project(tmp_path)
    visit = _new_visit(project)
    participants = {}
    recordings = {"P01__follicular": visit}
    if case == "existing-recording":
        recordings = {"P01__luteal": visit}
    elif case == "case-recording":
        recordings = {"p01__LUTEAL": visit}
    elif case == "existing-participant":
        participants = {"P01": {"group_id": "birth_control"}}
    elif case == "case-participant":
        participants = {"p01": {"group_id": "birth_control"}}
    elif case == "group-drift":
        visit["participant_id"] = "P02"
    elif case == "duplicate-session":
        visit.update(session_id="luteal", source_id="bc_luteal", visit_index=1)
        visit["raw_file"] = project.recording_sources["bc_luteal"]["raw_input_folder"] / "P01_second.bdf"
    elif case == "duplicate-path":
        participants = {"P03": {"group_id": "birth_control"}}
        recordings["P03__follicular"] = dict(visit, participant_id="P03")
    elif case == "wrong-source":
        visit["raw_file"] = project.project_root / "elsewhere.bdf"
    elif case == "missing-file":
        visit["raw_file"].unlink()
    before = project.manifest_path.read_bytes()
    state = deepcopy(project.__dict__)
    with pytest.raises(ValueError):
        project.append_registered_inputs(participants=participants, recordings=recordings, **_registration_options(project))
    assert project.manifest_path.read_bytes() == before
    assert project.__dict__ == state


@pytest.mark.parametrize("failure", ["write", "replace", "stale-before", "stale-during"])
def test_approved_append_keeps_memory_and_original_manifest_on_failed_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    import Main_App.projects.project as project_module

    project = _registration_project(tmp_path)
    visit = _new_visit(project)
    options = _registration_options(project)
    before = project.manifest_path.read_bytes()
    state = deepcopy(project.__dict__)
    external_bytes = before + b"\n"
    if failure == "stale-before":
        project.manifest_path.write_bytes(external_bytes)
    elif failure == "stale-during":
        monkeypatch.setattr(project_module.os, "fsync", lambda fd: project.manifest_path.write_bytes(external_bytes))
    elif failure == "write":
        def fail_fsync(fd):
            raise OSError("disk unavailable")
        monkeypatch.setattr(project_module.os, "fsync", fail_fsync)
    else:
        def fail_replace(self, target):
            raise OSError("replacement unavailable")
        monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises((OSError, ValueError)):
        project.append_registered_inputs(participants={}, recordings={"P01__follicular": visit}, **options)
    assert project.manifest_path.read_bytes() == (external_bytes if failure.startswith("stale") else before)
    assert project.__dict__ == state
    assert list(project.project_root.glob(".project.json.*.tmp")) == []


@pytest.mark.parametrize("locked", [False, True])
def test_approved_append_supports_new_flat_grouped_participant(tmp_path: Path, locked: bool) -> None:
    root = tmp_path / "Flat"
    root.mkdir()
    raw = root / "Raw"
    raw.mkdir()
    manifest = {
        "groups": {"control": {"label": "Control", "folder_name": "Control", "raw_input_folder": "Raw"}},
        "participants": {"P01": {"group_id": "control", "raw_file": "Raw/P01.bdf"}},
        "groups_locked": locked,
    }
    (root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    project = Project(root, manifest)
    new_file = raw / "P02.bdf"
    new_file.touch()
    project.input_folder = root / "Input"
    project.append_registered_inputs(
        participants={"P02": {"group_id": "control", "raw_file": new_file}},
        recordings={}, **_registration_options(project),
    )
    saved = json.loads(project.manifest_path.read_bytes())
    assert saved["participants"]["P01"] == manifest["participants"]["P01"]
    assert saved["participants"]["P02"]["raw_file"] == str(Path("Raw/P02.bdf"))
    assert "recordings" not in saved
    assert project.groups_locked == locked


def test_approved_append_rejects_changed_ungrouped_input_folder(tmp_path: Path) -> None:
    raw = tmp_path / "Raw"
    raw.mkdir()
    manifest = {"input_folder": "Raw"}
    (tmp_path / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    project = Project(tmp_path, manifest)
    new_file = raw / "P01.bdf"
    new_file.touch()
    project.input_folder = tmp_path / "Different"
    before = project.manifest_path.read_bytes()
    with pytest.raises(ValueError, match="input_folder changed before registration"):
        project.append_registered_inputs(
            participants={"P01": {"raw_file": new_file}}, recordings={},
            **_registration_options(project),
        )
    assert project.manifest_path.read_bytes() == before


@pytest.mark.parametrize("prior_registration", [False, True])
@pytest.mark.parametrize("refresh_tools_only", [False, True])
def test_old_project_save_cannot_erase_confirmed_registration(
    tmp_path: Path, prior_registration: bool, refresh_tools_only: bool,
) -> None:
    project = _registration_project(tmp_path)
    before = json.loads(project.manifest_path.read_bytes())
    if prior_registration:
        before["tools"]["processing"]["pending_raw_registration"] = {
            "version": 1, "processing_ids": ["P01__luteal"],
            "registration_fingerprint": "previous-registration",
        }
        project.manifest_path.write_text(json.dumps(before), encoding="utf-8")
        project = Project(project.project_root, deepcopy(before))
    stale_project = Project(project.project_root, deepcopy(before))
    visit = _new_visit(project)
    marker = {"version": 1, "processing_ids": ["P01__follicular", "P01__luteal"]}
    marker["registration_fingerprint"] = hashlib.sha256(
        json.dumps(marker, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    options = _registration_options(project)
    options["tool_namespace_updates"]["processing"]["pending_raw_registration"] = marker
    project.append_registered_inputs(
        participants={}, recordings={"P01__follicular": visit}, **options,
    )
    registered_bytes = project.manifest_path.read_bytes()
    if refresh_tools_only:
        # Mirrors processing_workflows._sync_project_tools_metadata: tools may
        # refresh while this object's participant/recording attributes are old.
        stale_project.manifest["tools"] = json.loads(registered_bytes)["tools"]

    stale_project.name = "An unrelated edit from the old project object"
    with pytest.raises(ValueError, match="Reload the project before saving"):
        stale_project.save()
    assert project.manifest_path.read_bytes() == registered_bytes

    project.name = "Current object edit"
    project.save()
    refreshed = Project(project.project_root, json.loads(project.manifest_path.read_bytes()))
    refreshed.name = "Refreshed object edit"
    refreshed.save()
    saved = json.loads(project.manifest_path.read_bytes())
    assert "P01__follicular" in saved["recordings"]
    assert saved["tools"]["processing"]["pending_raw_registration"] == marker
    assert saved["name"] == "Refreshed object edit"


def test_read_only_recording_context_exposes_canonical_lookups_without_writes(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = _repeated_manifest(project_root)
    (project_root / "project.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    context = load_project_recording_context(project_root)

    assert context.is_repeated_session is True
    assert [session.session_id for session in context.sessions] == [
        "luteal",
        "follicular",
    ]
    assert context.session("FOLLICULAR").visit_index == 2
    assert context.source("BC_LUTEAL").group_id == "birth_control"
    recording = context.recording("p01__LUTEAL")
    assert recording.participant_id == "P01"
    assert recording.days_from_baseline == 0.0
    assert context.recording_for_raw_path(recording.raw_file) == recording
    assert [row.recording_id for row in context.recordings_for_participant("p01")] == ["P01__luteal", "P01__follicular"]
    assert not (project_root / "Raw").exists()
    assert not (project_root / "1 - Excel Data Files").exists()


def test_project_roundtrips_optional_v22_recording_metadata(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    project = Project.load(
        project_root,
        manifest=_repeated_manifest(project_root),
    )

    assert project_recording_context(project).is_repeated_session is True

    project.save()
    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert saved["schema_version"] == REPEATED_SESSION_PROJECT_SCHEMA_VERSION
    assert saved["sessions"] == {
        "luteal": {"label": "Luteal", "visit_index": 1},
        "follicular": {"label": "Follicular", "visit_index": 2},
    }
    assert saved["recording_sources"]["bc_luteal"] == {
        "group_id": "birth_control",
        "session_id": "luteal",
        "raw_input_folder": str(Path("Raw/Birth Control/Luteal")),
    }
    assert saved["recordings"]["P01__follicular"] == {
        "participant_id": "P01",
        "session_id": "follicular",
        "source_id": "bc_follicular",
        "raw_file": str(Path("Raw/Birth Control/Follicular/P01_BC_F.bdf")),
        "visit_index": 2,
        "days_from_baseline": 14.0,
    }


def test_legacy_project_save_keeps_v21_shape_without_recording_fields(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Legacy"
    project_root.mkdir()
    raw_root = tmp_path / "Raw"
    project = Project.load(
        project_root,
        manifest={
            "groups": {
                "control": {
                    "label": "Control",
                    "folder_name": "Control",
                    "raw_input_folder": str(raw_root),
                }
            },
            "participants": {"P01": {"group_id": "control"}},
        },
    )

    project.save()
    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert saved["schema_version"] == PROJECT_SCHEMA_VERSION == "2.1.0"
    assert "sessions" not in saved
    assert "recording_sources" not in saved
    assert "recordings" not in saved
    assert "recordings_lock_fingerprint" not in saved
    assert project.sessions == {}
    assert project.recording_sources == {}
    assert project.recordings == {}


def test_recording_scoped_qc_persists_only_for_repeated_projects(
    tmp_path: Path,
) -> None:
    repeated_root = tmp_path / "Repeated"
    repeated_root.mkdir()
    repeated = Project.load(
        repeated_root,
        manifest=_repeated_manifest(repeated_root),
    )
    repeated.preprocessing.update(
        {
            "manual_removed_electrodes_by_recording": {
                "P01__follicular": ["Oz"],
            },
            "manual_excluded_recordings": ["P02__luteal"],
            "manual_excluded_recording_conditions": {
                "P01__luteal": ["Faces"],
            },
        }
    )
    repeated.save()
    repeated_saved = json.loads(
        (repeated_root / "project.json").read_text(encoding="utf-8")
    )

    assert repeated_saved["preprocessing"][
        "manual_removed_electrodes_by_recording"
    ] == {"P01__follicular": ["Oz"]}
    assert repeated_saved["preprocessing"]["manual_excluded_recordings"] == [
        "P02__luteal"
    ]
    assert repeated_saved["preprocessing"][
        "manual_excluded_recording_conditions"
    ] == {"P01__luteal": ["Faces"]}

    legacy_root = tmp_path / "Legacy QC"
    legacy_root.mkdir()
    legacy = Project.load(legacy_root)
    legacy.preprocessing["manual_excluded_recordings"] = ["P01__visit_1"]
    legacy.save()
    legacy_saved = json.loads(
        (legacy_root / "project.json").read_text(encoding="utf-8")
    )
    assert "manual_excluded_recordings" not in legacy_saved["preprocessing"]


def test_interpolation_burden_review_decision_survives_project_reload(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Burden review"
    project_root.mkdir()
    project = Project.load(project_root)
    finding = InterpolationBurdenReviewFinding(
        recording_id="P01",
        burden_fingerprint="c" * 64,
        successfully_interpolated_channels=("Fp1", "Fp2", "AF7", "AF3"),
        numerator=4,
        denominator=64,
        percentage=6.25,
        message="Review this participant.",
    )
    decision = build_interpolation_burden_review_decision(
        finding,
        participant_id="P01",
        decision=INTERPOLATION_BURDEN_DECISION_RETAIN,
        reason="Reviewed preprocessing evidence and retained the participant.",
        reviewed_at_utc="2026-09-02T12:00:00Z",
    ).to_payload()
    project.preprocessing["interpolation_burden_review_decisions"] = {
        "P01": decision,
    }

    project.save()
    reloaded = Project.load(project_root)

    assert reloaded.preprocessing["interpolation_burden_review_decisions"] == {
        "P01": decision,
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        pytest.param(
            lambda manifest: manifest["sessions"]["follicular"].update(visit_index=1),
            "same visit_index",
            id="duplicate-session-visit",
        ),
        pytest.param(
            lambda manifest: manifest["recording_sources"]["bc_luteal"].update(group_id="missing"),
            "Unknown group_id",
            id="unknown-source-group",
        ),
        pytest.param(
            lambda manifest: manifest["recording_sources"]["control_luteal"].update(
                raw_input_folder="Raw/Birth Control/Luteal"
            ),
            "same raw_input_folder",
            id="duplicate-source-folder",
        ),
        pytest.param(
            lambda manifest: manifest["recordings"]["P01__luteal"].update(participant_id="P99"),
            "unknown participant_id",
            id="unknown-recording-participant",
        ),
        pytest.param(
            lambda manifest: manifest["recordings"]["P01__luteal"].update(source_id="control_luteal"),
            "belongs to group",
            id="participant-source-group-mismatch",
        ),
        pytest.param(
            lambda manifest: manifest["recordings"]["P01__luteal"].update(session_id="follicular"),
            "does not match source",
            id="recording-source-session-mismatch",
        ),
        pytest.param(
            lambda manifest: manifest["recordings"]["P01__follicular"].update(
                session_id="luteal",
                source_id="bc_luteal",
                visit_index=1,
                raw_file="Raw/Birth Control/Luteal/P01_BC_L_repeat.bdf",
            ),
            "both assign participant",
            id="duplicate-participant-session",
        ),
        pytest.param(
            lambda manifest: manifest["recordings"]["P01__luteal"].update(raw_file="Raw/Birth Control/P01_BC_L.bdf"),
            "outside its declared source",
            id="raw-file-outside-source",
        ),
        pytest.param(
            lambda manifest: manifest["recordings"]["P01__luteal"].update(
                raw_file="Raw/Birth Control/Luteal/P01_BC_L.txt"
            ),
            "must be a .bdf",
            id="raw-file-not-bdf",
        ),
        pytest.param(
            lambda manifest: manifest["recordings"]["P01__luteal"].update(visit_index=2),
            "does not match session",
            id="recording-visit-mismatch",
        ),
        pytest.param(
            lambda manifest: (
                manifest["participants"].update({"P03": {"group_id": "birth_control"}}),
                manifest["recordings"].update(
                    {
                        "P03__luteal": {
                            "participant_id": "P03",
                            "session_id": "luteal",
                            "source_id": "bc_luteal",
                            "raw_file": "Raw/Birth Control/Luteal/P01_BC_L.bdf",
                            "visit_index": 1,
                        }
                    }
                ),
            ),
            "same raw_file",
            id="duplicate-recording-raw-file",
        ),
    ],
)
def test_recording_context_rejects_inconsistent_metadata(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = _repeated_manifest(project_root)
    mutate(manifest)
    (project_root / "project.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(RecordingConfigurationError, match=message):
        load_project_recording_context(project_root)


def test_locked_repeated_project_rejects_session_assignment_changes(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = _repeated_manifest(project_root)
    manifest["groups_locked"] = True
    project = Project.load(project_root, manifest=manifest)
    project.save()

    project.sessions["follicular"]["label"] = "Changed"

    with pytest.raises(ValueError, match="assignments cannot be changed"):
        project.save()


def test_locked_repeated_project_rejects_removing_recording_metadata(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = _repeated_manifest(project_root)
    manifest["groups_locked"] = True
    project = Project.load(project_root, manifest=manifest)
    project.save()

    project.sessions = {}
    project.recording_sources = {}
    project.recordings = {}

    with pytest.raises(ValueError, match="assignments cannot be changed"):
        project.save()
