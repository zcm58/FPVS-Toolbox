from __future__ import annotations

import json
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
