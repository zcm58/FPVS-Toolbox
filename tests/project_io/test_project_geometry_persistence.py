from __future__ import annotations

import json
from pathlib import Path

import pytest

from Main_App.projects import manifest_store
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
    original_replace = manifest_store.os.replace

    def deny_manifest_write(source, target):
        if target == path:
            raise PermissionError("manifest write denied")
        return original_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(manifest_store.os, "replace", deny_manifest_write)
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


@pytest.mark.parametrize("limit_key", ["max_chan_idx_keep", "max_idx_keep", "max_chan_idx"])
@pytest.mark.parametrize("reference_keys", [("ref_chan1", "ref_chan2"), ("ref_channel1", "ref_channel2")])
def test_legacy_policy_aliases_and_types_do_not_create_false_save_conflicts(tmp_path, limit_key, reference_keys):
    path = tmp_path / "project.json"
    path.write_text(json.dumps({"preprocessing": {
        limit_key: "32", reference_keys[0]: " Cz ", reference_keys[1]: " Pz ",
    }}), encoding="utf-8")
    project = Project.load(tmp_path)
    project.refresh_electrode_geometry_settings()
    assert project.preprocessing["max_chan_idx_keep"] == 32
    assert project.preprocessing["ref_chan1"] == "Cz"
    assert project.preprocessing["ref_chan2"] == "Pz"
    project.preprocessing.update(max_chan_idx_keep=48, ref_chan1="EXG1", ref_chan2="EXG2")
    project.save()
    reopened = Project.load(tmp_path)
    assert reopened.preprocessing["max_chan_idx_keep"] == 48
    assert reopened.preprocessing["ref_chan1"] == "EXG1"
    assert reopened.preprocessing["ref_chan2"] == "EXG2"


def test_geometry_save_preserves_fallback_for_unrelated_invalid_legacy_settings(tmp_path):
    path = tmp_path / "project.json"
    path.write_text(json.dumps({"preprocessing": {"low_pass": "invalid"}}), encoding="utf-8")
    project = Project.load(tmp_path)
    default_low_pass = project.preprocessing["low_pass"]
    project.preprocessing["electrode_mapping_profile"] = AB
    project.save()
    reopened = Project.load(tmp_path)
    assert reopened.preprocessing["low_pass"] == default_low_pass
    assert reopened.preprocessing["electrode_mapping_profile"] == AB


@pytest.mark.parametrize("invalid_settings", [
    {"max_chan_idx_keep": "invalid"}, {"max_idx_keep": "invalid"}, {"max_chan_idx": 128},
    {"ref_chan1": []}, {"ref_chan2": {}}, {"ref_channel1": []}, {"ref_channel2": {}},
])
def test_legacy_invalid_reference_and_limit_settings_keep_default_roundtrip(tmp_path, invalid_settings):
    path = tmp_path / "project.json"
    path.write_text(json.dumps({"preprocessing": invalid_settings}), encoding="utf-8")
    project = Project.load(tmp_path)
    project.refresh_electrode_geometry_settings()
    project.preprocessing["electrode_mapping_profile"] = AB
    project.save()
    reopened = Project.load(tmp_path)
    assert reopened.preprocessing["max_chan_idx_keep"] == 64
    assert reopened.preprocessing["ref_chan1"] == "EXG1"
    assert reopened.preprocessing["ref_chan2"] == "EXG2"
    assert reopened.preprocessing["electrode_mapping_profile"] == AB


@pytest.mark.parametrize("platform", ["biosemi", "brain_products"])
@pytest.mark.parametrize("operation", ["save", "refresh_electrode_geometry_settings"])
def test_explicit_hardware_invalid_limit_is_never_replaced_by_legacy_fallback(tmp_path, platform, operation):
    from Main_App.projects.hardware import confirm_hardware_selection

    project = _project(tmp_path)
    project.update_preprocessing(confirm_hardware_selection(project.preprocessing, platform, confirmed_change=True))
    project.save()
    path = project.project_root / "project.json"
    disk = _saved_manifest(project)
    disk["preprocessing"]["max_chan_idx_keep"] = "invalid"
    path.write_text(json.dumps(disk), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="Invalid integer"):
        getattr(project, operation)()
    assert path.read_bytes() == original
