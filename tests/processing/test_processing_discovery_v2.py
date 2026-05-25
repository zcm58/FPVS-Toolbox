from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from Main_App.gui.processing_inputs import validate_inputs
from Main_App.processing.processing_controller import (
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


def test_discover_raw_files_warns_for_missing_known_raw_file(tmp_path, caplog) -> None:
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
    project.groups_locked = True
    project.participants = {
        "P01": {"group_id": "control", "raw_file": control_dir / "P01.bdf"}
    }

    with caplog.at_level(logging.WARNING):
        files = discover_raw_files(project)

    assert [info.path for info in files] == [p02.resolve()]
    assert "missing raw .bdf file" in caplog.text


def test_discover_raw_files_rejects_missing_registered_folder_after_lock(tmp_path) -> None:
    missing_dir = tmp_path / "raw" / "Missing"
    project = _build_group_project(
        tmp_path,
        {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": missing_dir,
            },
        },
    )
    project.groups_locked = True

    with pytest.raises(FileNotFoundError, match="Registered raw input folder is missing"):
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
