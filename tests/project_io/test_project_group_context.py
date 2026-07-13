from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from Main_App.gui import tool_workflows
from Main_App.projects.grouping import (
    GroupConfigurationError,
    load_project_group_context,
    project_group_context,
    resolve_group_output_directory,
)
from Main_App.projects.project import Project


def test_read_only_group_context_resolves_manifest_without_creating_folders(
    tmp_path,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = {
        "groups": {
            "Control Group": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": "Raw/Control",
            },
            "treatment": {
                "label": "Treatment",
                "folder_name": "Treatment",
                "raw_input_folder": "Raw/Treatment",
            },
        },
        "participants": {
            "P01": {
                "group": "Control Group",
                "raw_file": "Raw/Control/P01.bdf",
            }
        },
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    context = load_project_group_context(project_root)

    assert context.has_group_metadata is True
    assert context.is_multi_group is True
    assert [group.group_id for group in context.groups] == [
        "control_group",
        "treatment",
    ]
    assert (
        context.group("control_group").raw_input_folder
        == (project_root / "Raw" / "Control").resolve()
    )
    assert context.participant("p01").group_id == "control_group"
    assert (
        context.participant("P01").raw_file
        == (project_root / "Raw" / "Control" / "P01.bdf").resolve()
    )
    assert not (project_root / "Raw").exists()
    assert not (project_root / "1 - Excel Data Files").exists()


def test_active_project_context_uses_same_canonical_group_identity(tmp_path) -> None:
    project_root = tmp_path / "Project"
    raw_folder = tmp_path / "Raw" / "Control"
    raw_folder.mkdir(parents=True)
    project = Project.load(
        project_root,
        manifest={
            "groups": {
                "Control Group": {
                    "raw_input_folder": str(raw_folder),
                }
            },
            "participants": {"P01": {"group": "Control Group"}},
        },
    )

    context = project_group_context(project)

    assert context.group("control_group").label == "Control Group"
    assert context.participant("P01").group_id == "control_group"
    assert project.input_folder is None


def test_epoch_averaging_does_not_use_grouped_input_fallback(
    tmp_path,
    monkeypatch,
) -> None:
    raw_folder = tmp_path / "Raw" / "Control"
    raw_folder.mkdir(parents=True)
    project = Project.load(
        tmp_path / "Project",
        manifest={
            "groups": {
                "control": {
                    "raw_input_folder": str(raw_folder),
                }
            }
        },
    )
    messages: list[str] = []
    monkeypatch.setattr(
        tool_workflows.QMessageBox,
        "critical",
        lambda _parent, _title, message: messages.append(message),
    )

    result = tool_workflows.resolve_epoch_averaging_paths(
        SimpleNamespace(currentProject=project)
    )

    assert result is None
    assert messages and "will not substitute" in messages[0]


def test_group_context_rejects_unknown_participant_group(tmp_path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = {
        "groups": {
            "control": {
                "raw_input_folder": "Raw/Control",
            }
        },
        "participants": {"P01": {"group_id": "treatment"}},
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(GroupConfigurationError, match="unknown group_id"):
        load_project_group_context(project_root)


def test_group_context_rejects_ambiguous_group_aliases(tmp_path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = {
        "groups": {
            "Group A": {
                "folder_name": "First",
                "raw_input_folder": "Raw/First",
            },
            "group_a": {
                "folder_name": "Second",
                "raw_input_folder": "Raw/Second",
            },
        }
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(GroupConfigurationError, match="alias.*ambiguous"):
        load_project_group_context(project_root)


def test_group_context_rejects_case_insensitive_participant_duplicates(
    tmp_path,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = {
        "groups": {
            "control": {
                "raw_input_folder": "Raw/Control",
            }
        },
        "participants": {
            "P01": {"group_id": "control"},
            "p01": {"group_id": "control"},
        },
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(GroupConfigurationError, match="differ only by case"):
        load_project_group_context(project_root)


@pytest.mark.parametrize(
    ("raw_file", "message"),
    [
        pytest.param("Raw/Other/P01.bdf", "outside its assigned group", id="outside"),
        pytest.param("Raw/Control/P01.txt", "must be a .bdf", id="not-bdf"),
    ],
)
def test_group_context_rejects_invalid_registered_raw_source(
    tmp_path,
    raw_file,
    message,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = {
        "groups": {
            "control": {
                "raw_input_folder": "Raw/Control",
            }
        },
        "participants": {
            "P01": {
                "group_id": "control",
                "raw_file": raw_file,
            }
        },
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(GroupConfigurationError, match=message):
        load_project_group_context(project_root)


@pytest.mark.parametrize(
    ("second_folder_name", "second_raw_folder", "message"),
    [
        pytest.param(
            "Control", "Raw/Treatment", "same folder_name", id="output-folder"
        ),
        pytest.param(
            "Treatment", "Raw/Control", "same raw_input_folder", id="raw-folder"
        ),
    ],
)
def test_group_context_rejects_colliding_group_paths(
    tmp_path,
    second_folder_name,
    second_raw_folder,
    message,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = {
        "groups": {
            "control": {
                "folder_name": "Control",
                "raw_input_folder": "Raw/Control",
            },
            "treatment": {
                "folder_name": second_folder_name,
                "raw_input_folder": second_raw_folder,
            },
        }
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(GroupConfigurationError, match=message):
        load_project_group_context(project_root)


def test_group_output_directory_requires_one_contained_component(tmp_path) -> None:
    condition_folder = tmp_path / "Condition"

    assert (
        resolve_group_output_directory(condition_folder, "Control")
        == (condition_folder / "Control").resolve()
    )
    with pytest.raises(GroupConfigurationError):
        resolve_group_output_directory(condition_folder, "../Outside")
