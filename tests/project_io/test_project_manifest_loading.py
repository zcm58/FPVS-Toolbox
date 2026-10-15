"""Invalid project documents never become editable default projects."""

import pytest

from Main_App.projects import Project
from Main_App.projects.project_metadata import enumerate_project_metadata, read_project_metadata


_INVALID_MANIFESTS = [b"{broken", b"", b"[]", b"null", b"42", b'"name"', b'[["name", "Unexpected"]]', b"\xff"]


@pytest.mark.parametrize("payload", _INVALID_MANIFESTS)
def test_invalid_manifest_fails_before_creating_managed_directories(tmp_path, payload):
    root = tmp_path / "project"
    root.mkdir()
    manifest = root / "project.json"
    manifest.write_bytes(payload)
    sentinel = root / "retained.txt"
    sentinel.write_text("user data", encoding="utf-8")

    with pytest.raises(ValueError, match="Project manifest"):
        Project.load(root)

    assert manifest.read_bytes() == payload
    assert sentinel.read_text(encoding="utf-8") == "user data"
    assert {path.name for path in root.iterdir()} == {"project.json", "retained.txt"}


@pytest.mark.parametrize("payload", _INVALID_MANIFESTS)
def test_metadata_marks_every_invalid_document_unopenable_without_loading(tmp_path, payload):
    root = tmp_path / "project"
    root.mkdir()
    manifest = root / "project.json"
    manifest.write_bytes(payload)

    metadata = read_project_metadata(root)

    assert metadata.parse_error
    assert metadata.manifest == {}
    assert metadata.name == root.name
    assert enumerate_project_metadata(tmp_path) == [metadata]
    assert manifest.read_bytes() == payload
    assert list(root.iterdir()) == [manifest]


@pytest.mark.parametrize("manifest", [[], [("name", "Unexpected")], "name", 42])
def test_supplied_nonobject_manifest_fails_before_creating_project(tmp_path, manifest):
    root = tmp_path / "new-project"
    with pytest.raises(ValueError, match="must contain a JSON object"):
        Project.load(root, manifest=manifest)
    assert not root.exists()


def test_missing_manifest_still_initializes_a_legitimate_new_project(tmp_path):
    root = tmp_path / "new-project"

    project = Project.load(root)

    assert project.project_root == root.resolve()
    assert project.input_folder.is_dir()
    assert all((project.project_root / name).is_dir() for name in project.subfolders.values())
    assert not project.manifest_path.exists()
    project.name = "New project"
    project.save()
    assert Project.load(root).name == "New project"


def test_valid_empty_manifest_remains_a_legacy_project_without_rewrite(tmp_path):
    root = tmp_path / "legacy-project"
    root.mkdir()
    manifest = root / "project.json"
    manifest.write_bytes(b"{ }\n")

    metadata = read_project_metadata(root)
    project = Project.load(root, manifest=metadata.manifest, manifest_path=metadata.manifest_path)

    assert not metadata.parse_error
    assert project.name == root.name
    assert project.input_folder.is_dir()
    assert manifest.read_bytes() == b"{ }\n"
