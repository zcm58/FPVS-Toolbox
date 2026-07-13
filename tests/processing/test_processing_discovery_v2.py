from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Main_App.gui.processing_inputs import validate_inputs
from Main_App.processing.processing_controller import (
    RawFileInfo,
    discover_raw_files,
    participant_review_rows,
    prepare_batch_files,
    raw_file_info_for_path,
    register_participants,
)
from Main_App.projects.project import Project


def _build_group_project(tmp_path: Path, groups: dict[str, dict[str, Any]]) -> Project:
    project_root = tmp_path / "project"
    project_root.mkdir()
    project = Project.load(project_root)
    first_group = next(iter(groups.values()))
    first_folder = first_group["raw_input_folder"]
    project.input_folder = first_folder
    project.groups = groups
    project.participants = {}
    project.save()
    return project


def test_prepare_batch_files_multigroup_does_not_fallback_to_input_folder(tmp_path) -> None:
    fallback_input = tmp_path / "fallback"
    fallback_input.mkdir()
    (fallback_input / "P99.bdf").write_bytes(b"")
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)

    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )
    project.input_folder = fallback_input

    assert prepare_batch_files(project) == []


def test_discover_raw_files_enumerates_every_registered_group(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    treatment_dir = tmp_path / "raw" / "Treatment"
    control_dir.mkdir(parents=True)
    treatment_dir.mkdir()
    control_file = control_dir / "P01.bdf"
    treatment_file = treatment_dir / "P02.bdf"
    control_file.write_bytes(b"")
    treatment_file.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
            "treatment": {
                "label": "Treatment",
                "folder_name": "Treatment",
                "raw_input_folder": treatment_dir,
            },
        },
    )

    files = discover_raw_files(project)

    assert [(info.path, info.subject_id, info.group) for info in files] == [
        (control_file.resolve(), "P01", "control"),
        (treatment_file.resolve(), "P02", "treatment"),
    ]


def test_discover_raw_files_rejects_duplicate_subjects_same_folder(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)
    (control_dir / "P01.bdf").write_bytes(b"")
    (control_dir / "P01_run2.bdf").write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )

    with pytest.raises(ValueError, match="Duplicate participant ID"):
        discover_raw_files(project)


def test_discover_raw_files_rejects_duplicate_subjects_across_groups(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    treatment_dir = tmp_path / "raw" / "Treatment"
    control_dir.mkdir(parents=True)
    treatment_dir.mkdir()
    (control_dir / "P01.bdf").write_bytes(b"")
    (treatment_dir / "P01.bdf").write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
            "treatment": {
                "label": "Treatment",
                "folder_name": "Treatment",
                "raw_input_folder": treatment_dir,
            },
        },
    )

    with pytest.raises(ValueError, match="Duplicate participant ID"):
        discover_raw_files(project)


def test_discover_raw_files_ignores_appledouble_bdf_sidecars(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)
    p01 = control_dir / "P01.bdf"
    p02 = control_dir / "SC_P02.bdf"
    sidecar = control_dir / "._P03.bdf"
    p01.write_bytes(b"")
    p02.write_bytes(b"")
    sidecar.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )

    files = discover_raw_files(project)

    assert [info.path for info in files] == [p01.resolve(), p02.resolve()]


def test_discover_raw_files_rejects_locked_group_assignment_drift(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    treatment_dir = tmp_path / "raw" / "Treatment"
    control_dir.mkdir(parents=True)
    treatment_dir.mkdir()
    (treatment_dir / "P01.bdf").write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
            "treatment": {
                "label": "Treatment",
                "folder_name": "Treatment",
                "raw_input_folder": treatment_dir,
            },
        },
    )
    project.groups_locked = True
    project.participants = {"P01": {"group_id": "control"}}

    with pytest.raises(ValueError, match="registered in group 'control'"):
        discover_raw_files(project)


@pytest.mark.parametrize("groups_locked", [False, True])
def test_discover_raw_files_rejects_missing_known_raw_file(
    tmp_path,
    groups_locked,
) -> None:
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)
    p02 = control_dir / "P02.bdf"
    p02.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )
    project.groups_locked = groups_locked
    project.participants = {
        "P01": {"group_id": "control", "raw_file": control_dir / "P01.bdf"}
    }

    with pytest.raises(FileNotFoundError, match="missing raw .bdf file"):
        discover_raw_files(project)


@pytest.mark.parametrize("groups_locked", [False, True])
def test_discover_raw_files_rejects_any_missing_registered_group_folder(
    tmp_path,
    groups_locked,
) -> None:
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)
    (control_dir / "P01.bdf").write_bytes(b"")
    missing_dir = tmp_path / "raw" / "Treatment"
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
            "treatment": {
                "label": "Treatment",
                "folder_name": "Treatment",
                "raw_input_folder": missing_dir,
            },
        },
    )
    project.groups_locked = groups_locked

    with pytest.raises(FileNotFoundError, match="Registered raw input folder is missing"):
        discover_raw_files(project)


def test_discover_raw_files_rejects_registered_file_excluded_from_discovery(
    tmp_path,
) -> None:
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)
    sidecar = control_dir / "._P01.bdf"
    sidecar.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )
    project.participants = {
        "P01": {"group_id": "control", "raw_file": sidecar}
    }

    with pytest.raises(ValueError, match="not found by canonical group discovery"):
        discover_raw_files(project)


def test_prepare_batch_files_does_not_persist_before_review(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)
    p01 = control_dir / "P01.bdf"
    p01.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )

    assert prepare_batch_files(project) == [p01.resolve()]
    saved = json.loads((project.project_root / "project.json").read_text(encoding="utf-8"))

    assert "participants" not in saved

def test_register_participants_persists_group_id_and_raw_file(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)
    p01 = control_dir / "P01.bdf"
    p01.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )
    files = list(discover_raw_files(project))

    assert [row.status for row in participant_review_rows(project, files)] == [
        "New participant"
    ]
    assert register_participants(project, files) is True
    saved = json.loads((project.project_root / "project.json").read_text(encoding="utf-8"))

    assert saved["participants"]["P01"] == {
        "group_id": "control",
        "raw_file": str(p01),
    }


def test_register_participants_hard_fails_group_assignment_conflict(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    treatment_dir = tmp_path / "raw" / "Treatment"
    control_dir.mkdir(parents=True)
    treatment_dir.mkdir()
    control_file = control_dir / "P01.bdf"
    treatment_file = treatment_dir / "P01.bdf"
    control_file.write_bytes(b"")
    treatment_file.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
            "treatment": {
                "label": "Treatment",
                "folder_name": "Treatment",
                "raw_input_folder": treatment_dir,
            },
        },
    )
    project.participants = {
        "P01": {"group_id": "control", "raw_file": control_file}
    }

    with pytest.raises(ValueError, match="already assigned to group 'control'"):
        register_participants(
            project,
            [RawFileInfo(treatment_file.resolve(), "P01", "treatment")],
        )


def test_raw_file_info_for_path_rejects_unregistered_group_source(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    outside_dir = tmp_path / "outside"
    control_dir.mkdir(parents=True)
    outside_dir.mkdir()
    outside_file = outside_dir / "P01.bdf"
    outside_file.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )

    with pytest.raises(ValueError, match="outside the registered raw folders"):
        raw_file_info_for_path(project, outside_file)


def test_raw_file_info_for_path_accepts_registered_group_source(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)
    p01 = control_dir / "P01.bdf"
    p01.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )

    info = raw_file_info_for_path(project, p01)

    assert info.path == p01.resolve()
    assert info.subject_id == "P01"
    assert info.group == "control"


def test_validate_inputs_reviews_and_registers_batch_participants(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)
    p01 = control_dir / "P01.bdf"
    p01.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )
    reviewed_rows = []

    class Settings:
        @staticmethod
        def debug_enabled() -> bool:
            return False

    def review(_parent, rows) -> bool:
        reviewed_rows.extend(rows)
        return True

    host = SimpleNamespace(
        currentProject=project,
        file_mode=SimpleNamespace(get=lambda: "Batch"),
        data_paths=[],
        settings=Settings(),
        log=lambda *args, **kwargs: None,
        _build_validated_params=lambda: {"event_id_map": {"Condition": 1}},
        review_participants_for_processing=review,
        run_preprocessing_qc_workflow=lambda *_args, **_kwargs: True,
    )

    assert validate_inputs(host) is True
    saved = json.loads((project.project_root / "project.json").read_text(encoding="utf-8"))

    assert [row.participant_id for row in reviewed_rows] == ["P01"]
    assert host.data_paths == [str(p01.resolve())]
    assert saved["participants"]["P01"] == {
        "group_id": "control",
        "raw_file": str(p01),
    }


def test_validate_inputs_cancelled_review_does_not_register_participants(tmp_path) -> None:
    control_dir = tmp_path / "raw" / "Control"
    control_dir.mkdir(parents=True)
    p01 = control_dir / "P01.bdf"
    p01.write_bytes(b"")
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": control_dir,
            },
        },
    )

    class Settings:
        @staticmethod
        def debug_enabled() -> bool:
            return False

    host = SimpleNamespace(
        currentProject=project,
        file_mode=SimpleNamespace(get=lambda: "Batch"),
        data_paths=[],
        settings=Settings(),
        log=lambda *args, **kwargs: None,
        _build_validated_params=lambda: {"event_id_map": {"Condition": 1}},
        review_participants_for_processing=lambda _parent, _rows: False,
    )

    assert validate_inputs(host) is False
    saved = json.loads((project.project_root / "project.json").read_text(encoding="utf-8"))

    assert "participants" not in saved
