from __future__ import annotations

import json
from pathlib import Path

import pytest

from Main_App.projects.project import Project


ANATOMICAL = "anatomical_labels"
AB = "biosemi64_1020_ab_v1"


def _project(tmp_path: Path, profile: str = AB) -> Project:
    project = Project.load(tmp_path / "Project")
    project.preprocessing["electrode_mapping_profile"] = profile
    project.save()
    return project


def _save_profile(project_root: Path, profile: str) -> None:
    project = Project.load(project_root)
    project.preprocessing["electrode_mapping_profile"] = profile
    project.save()


def _saved_manifest(project: Project) -> dict:
    return json.loads((project.project_root / "project.json").read_text(encoding="utf-8"))


def test_stale_project_save_preserves_newer_geometry_and_worker_metadata(tmp_path) -> None:
    project = _project(tmp_path)
    _save_profile(project.project_root, ANATOMICAL)
    path = project.project_root / "project.json"
    disk = _saved_manifest(project)
    disk["tools"] = {"frequency_domain_qc": {"review": "latest worker receipt"}}
    path.write_text(json.dumps(disk), encoding="utf-8")

    project.name = "Renamed project"
    project.preprocessing["low_pass"] = 42
    project.save()

    saved = _saved_manifest(project)
    assert saved["preprocessing"]["electrode_mapping_profile"] == ANATOMICAL
    assert saved["preprocessing"]["electrode_montage"] == "biosemi64"
    assert saved["preprocessing"]["low_pass"] == 42
    assert saved["name"] == "Renamed project"
    assert saved["tools"] == disk["tools"]
    assert project.preprocessing["electrode_mapping_profile"] == ANATOMICAL


@pytest.mark.parametrize("disk_already_matches", [False, True])
def test_explicit_local_geometry_save_rebases_after_write_or_noop(
    tmp_path, disk_already_matches
) -> None:
    project = _project(tmp_path, ANATOMICAL)
    project.preprocessing["electrode_mapping_profile"] = AB
    if disk_already_matches:
        _save_profile(project.project_root, AB)

    project.save()
    assert _saved_manifest(project)["preprocessing"]["electrode_mapping_profile"] == AB

    _save_profile(project.project_root, ANATOMICAL)
    project.name = "An unrelated later edit"
    project.save()
    assert _saved_manifest(project)["preprocessing"]["electrode_mapping_profile"] == ANATOMICAL


def test_refresh_geometry_repeatedly_adopts_disk_without_saving_other_settings(tmp_path) -> None:
    project = _project(tmp_path)
    project.preprocessing["low_pass"] = 42
    project.name = "Unsaved name"
    path = project.project_root / "project.json"

    for profile in (ANATOMICAL, AB, ANATOMICAL):
        _save_profile(project.project_root, profile)
        before = path.read_bytes()
        project.refresh_electrode_geometry_settings()
        assert project.preprocessing["electrode_mapping_profile"] == profile
        assert project.preprocessing["electrode_montage"] == "biosemi64"
        assert project.preprocessing["low_pass"] == 42
        assert project.name == "Unsaved name"
        assert path.read_bytes() == before


def test_refresh_geometry_preserves_deliberate_local_edit(tmp_path) -> None:
    project = _project(tmp_path, ANATOMICAL)
    project.preprocessing["electrode_mapping_profile"] = AB

    project.refresh_electrode_geometry_settings()
    project.refresh_electrode_geometry_settings()
    assert project.preprocessing["electrode_mapping_profile"] == AB
    assert _saved_manifest(project)["preprocessing"]["electrode_mapping_profile"] == ANATOMICAL

    project.save()
    assert _saved_manifest(project)["preprocessing"]["electrode_mapping_profile"] == AB


@pytest.mark.parametrize("adopt_disk", [False, True])
def test_failed_save_does_not_rebase_or_adopt_geometry(tmp_path, monkeypatch, adopt_disk) -> None:
    project = _project(tmp_path, AB if adopt_disk else ANATOMICAL)
    if adopt_disk:
        _save_profile(project.project_root, ANATOMICAL)
    else:
        project.preprocessing["electrode_mapping_profile"] = AB
    project.name = "An unsaved edit"
    path = project.project_root / "project.json"
    before = path.read_bytes()
    original_write = Path.write_text

    def deny_manifest_write(target, *args, **kwargs):
        if target == path:
            raise PermissionError("manifest write denied")
        return original_write(target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text", deny_manifest_write)
        with pytest.raises(PermissionError, match="manifest write denied"):
            project.save()

    assert path.read_bytes() == before
    assert project.preprocessing["electrode_mapping_profile"] == AB
    if adopt_disk:
        _save_profile(project.project_root, AB)
    project.save()
    assert _saved_manifest(project)["preprocessing"]["electrode_mapping_profile"] == AB


@pytest.mark.parametrize("operation", ["save", "refresh_electrode_geometry_settings"])
@pytest.mark.parametrize(
    "invalid_manifest",
    [
        "{",
        "[]",
        '{"preprocessing": []}',
        '{"preprocessing": {"electrode_mapping_profile": "invalid"}}',
        '{"preprocessing": {"electrode_montage": "invalid"}}',
    ],
)
def test_geometry_reconciliation_rejects_invalid_disk_without_overwriting(
    tmp_path, operation, invalid_manifest
) -> None:
    project = _project(tmp_path)
    path = project.project_root / "project.json"
    path.write_text(invalid_manifest, encoding="utf-8")

    with pytest.raises(ValueError):
        getattr(project, operation)()

    assert path.read_text(encoding="utf-8") == invalid_manifest
    assert project.preprocessing["electrode_mapping_profile"] == AB


@pytest.mark.parametrize("operation", ["save", "refresh_electrode_geometry_settings"])
def test_geometry_reconciliation_propagates_unreadable_disk(tmp_path, monkeypatch, operation) -> None:
    project = _project(tmp_path)
    path = project.project_root / "project.json"
    before = path.read_bytes()
    original_read = Path.read_text

    def deny_manifest_read(target, *args, **kwargs):
        if target == path:
            raise PermissionError("manifest read denied")
        return original_read(target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", deny_manifest_read)
        with pytest.raises(PermissionError, match="manifest read denied"):
            getattr(project, operation)()

    assert path.read_bytes() == before
    assert project.preprocessing["electrode_mapping_profile"] == AB


def test_new_project_geometry_refresh_does_not_require_existing_manifest(tmp_path) -> None:
    project = Project.load(tmp_path / "Project")
    path = project.project_root / "project.json"
    assert not path.exists()

    project.refresh_electrode_geometry_settings()
    assert not path.exists()
    assert project.preprocessing["electrode_mapping_profile"] == ANATOMICAL
    project.save()
    assert _saved_manifest(project)["preprocessing"]["electrode_mapping_profile"] == ANATOMICAL


def test_legacy_manifest_without_geometry_uses_current_defaults_on_stale_save(tmp_path) -> None:
    project = _project(tmp_path)
    path = project.project_root / "project.json"
    disk = _saved_manifest(project)
    disk["preprocessing"].pop("electrode_mapping_profile")
    disk["preprocessing"].pop("electrode_montage")
    path.write_text(json.dumps(disk), encoding="utf-8")

    project.save()

    saved = _saved_manifest(project)["preprocessing"]
    assert saved["electrode_mapping_profile"] == ANATOMICAL
    assert saved["electrode_montage"] == "biosemi64"
