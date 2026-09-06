from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path

import pytest

from Main_App.processing import toolbox_cache as service
from Main_App.processing import toolbox_cache_paths as paths

KEY = "a" * 64


@pytest.fixture(autouse=True)
def isolated_app_cache(monkeypatch):
    monkeypatch.setattr(paths, "app_cache_locations", lambda: ())


def _write(path, content=b"cache"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _project(root):
    _write(root / "project.json", json.dumps({"name": "Test", "preprocessing": {"reject_thresh": 5}}).encode())
    return root


def _preflight(root):
    return _write(root / ".fpvs_processing" / "preflight_qc" / "v7_analyzed_condition_scope" / f"{KEY}.json")


def _prepared(root):
    return _write(root / ".fpvs_cache" / "preprocessed" / f"participant_{'b' * 16}_raw.fif")


def test_inventory_and_clear_only_owned_caches_preserving_science(tmp_path):
    root = _project(tmp_path / "project")
    files = [_prepared(root), _preflight(root)]
    for relative in (
        f".fpvs_cache/prepared_kurtosis/{'c' * 24}/{KEY}.{'d' * 20}.npz",
        f".fpvs_cache/prepared_kurtosis/{'c' * 24}/latest.json",
        f".fpvs_processing/preflight_qc/v7_analyzed_condition_scope/events/{KEY}.json",
        f".fpvs_processing/preflight_qc/v7_analyzed_condition_scope/.slots/{KEY}.json",
        ".fpvs_processing/preflight_qc/v7_analyzed_condition_scope/.slots/index-state.json",
        ".fpvs_processing/preflight_qc/v7_analyzed_condition_scope/.slots/.index-stale.tmp",
        f".fpvs_processing/source_psd_cache/v1/{KEY}.npz",
        f"1 - Excel Data Files/Condition/_individual_detectability_cache/P1__{'a' * 16}__{'b' * 16}.npz",
    ):
        files.append(_write(root / relative))
    preserved = [_write(root / relative, b"keep") for relative in (
        "raw/participant.bdf", "1 - Excel Data Files/Condition/output.metrics.npz",
        "1 - Excel Data Files/Condition/output.spectra.npz", "Stats-ready.xlsx",
        ".fpvs_processing/processing_ledger.json", ".fpvs_processing/processing_runs.jsonl",
        ".fpvs_processing/review_decisions.json", ".fpvs_cache/mne/fsaverage/template.fif",
        ".fpvs_cache/preprocessed/user-notes.txt", ".fpvs_cache/preprocessed/input.bdf",
    )]
    manifest = (root / "project.json").read_bytes()
    inventory = service.inspect_toolbox_caches(active_project_root=root)
    assert inventory.file_count == len(files)
    assert inventory.total_bytes == sum(path.stat().st_size for path in files)
    assert all(path.exists() for path in files)
    result = service.clear_toolbox_caches(inventory)
    assert not result.errors
    assert result.removed_files == len(files)
    assert result.removed_bytes == inventory.total_bytes
    assert all(not path.exists() for path in files)
    assert all(path.read_bytes() == b"keep" for path in preserved)
    assert (root / "project.json").read_bytes() == manifest
    assert (root / ".fpvs_processing/preflight_qc/v7_analyzed_condition_scope/.publication.lock").exists()
    assert service.inspect_toolbox_caches(active_project_root=root).file_count == 0


def test_registered_projects_are_direct_children_plus_active_only(tmp_path):
    configured = tmp_path / "projects"
    first, second = _project(configured / "A"), _project(configured / "B")
    active = _project(tmp_path / "elsewhere")
    nested = _project(configured / "unregistered" / "nested")
    for root in (first, second, active, nested):
        _prepared(root)
    inventory = service.inspect_toolbox_caches(active_project_root=active, projects_root=configured)
    assert set(inventory.project_roots) == {first, second, active}
    assert inventory.file_count == 3
    service.clear_toolbox_caches(inventory)
    assert next((nested / ".fpvs_cache/preprocessed").iterdir()).is_file()


@pytest.mark.parametrize("bad", ["relative", "missing", "not_project", "anchor", "bad_manifest"])
def test_reject_mispointed_active_roots(tmp_path, bad):
    choices = {"relative": Path("relative"), "missing": tmp_path / "missing",
               "not_project": tmp_path, "anchor": Path(tmp_path.anchor), "bad_manifest": tmp_path}
    if bad == "bad_manifest":
        _write(tmp_path / "project.json", b"[]")
    with pytest.raises(service.ToolboxCacheError):
        service.inspect_toolbox_caches(active_project_root=choices[bad])


def test_redirected_location_kept_without_blocking_other_locations(tmp_path, monkeypatch):
    root = _project(tmp_path / "project")
    rejected = _prepared(root)
    valid = _preflight(root)
    original = getattr(Path, "is_junction", lambda _: False)
    monkeypatch.setattr(Path, "is_junction", lambda self: self == rejected.parent or original(self), raising=False)
    inventory = service.inspect_toolbox_caches(active_project_root=root)
    assert inventory.warnings
    assert inventory.file_count == 1
    result = service.clear_toolbox_caches(inventory)
    assert not result.errors
    assert rejected.exists() and not valid.exists()


def test_symlink_escape_is_never_followed(tmp_path):
    root = _project(tmp_path / "project")
    outside = _write(tmp_path / "outside" / f"participant_{'b' * 16}_raw.fif", b"keep")
    linked = root / ".fpvs_cache/preprocessed"
    linked.parent.mkdir(parents=True)
    try:
        linked.symlink_to(outside.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is unavailable in this Windows test environment")
    inventory = service.inspect_toolbox_caches(active_project_root=root)
    assert inventory.file_count == 0 and inventory.warnings
    service.clear_toolbox_caches(inventory)
    assert outside.read_bytes() == b"keep"
    assert linked.is_symlink()


@pytest.mark.parametrize("change", ["file", "manifest", "forged", "new_file"])
def test_changed_inventory_rejected_before_any_deletion(tmp_path, change):
    root = _project(tmp_path / "project")
    first = _prepared(root)
    second = _preflight(root)
    inventory = service.inspect_toolbox_caches(active_project_root=root)
    if change == "file":
        first.write_bytes(b"new cache")
    elif change == "manifest":
        (root / "project.json").write_text('{"name":"Changed"}')
    elif change == "new_file":
        _write(second.with_name(f"{'e' * 64}.json"))
    else:
        inventory = replace(inventory, targets=())
    with pytest.raises(service.ToolboxCacheChangedError):
        service.clear_toolbox_caches(inventory)
    assert first.exists() and second.exists()


def test_partial_file_failure_returns_exact_counts(tmp_path, monkeypatch):
    root = _project(tmp_path / "project")
    failed, successful = _prepared(root), _preflight(root)
    inventory = service.inspect_toolbox_caches(active_project_root=root)
    original = Path.unlink

    def fail_one(self, *args, **kwargs):
        if self == failed:
            raise PermissionError("locked file")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_one)
    result = service.clear_toolbox_caches(inventory)
    assert result.removed_files == 1 and result.removed_bytes == 5
    assert len(result.errors) == 1 and "locked file" in result.errors[0]
    assert failed.exists() and not successful.exists()


def test_inspection_and_removal_can_be_cancelled(tmp_path):
    root = _project(tmp_path / "project")
    path = _prepared(root)
    with pytest.raises(service.ToolboxCacheError, match="cancelled"):
        service.inspect_toolbox_caches(active_project_root=root, should_cancel=lambda: True)
    inventory = service.inspect_toolbox_caches(active_project_root=root)
    result = service.clear_toolbox_caches(inventory, should_cancel=lambda: True)
    assert result.cancelled and result.removed_files == 0 and path.exists()


def test_busy_namespace_and_persistent_lock_are_kept(tmp_path, monkeypatch):
    root = _project(tmp_path / "project")
    path = _preflight(root)
    lock = _write(path.parent / ".publication.lock", b"0")
    inventory = service.inspect_toolbox_caches(active_project_root=root)

    @contextmanager
    def busy(_namespace):
        yield False

    monkeypatch.setattr(service, "_publication_lock", busy)
    result = service.clear_toolbox_caches(inventory)
    assert result.removed_files == 0 and "busy" in result.errors[0]
    assert path.exists() and lock.read_bytes() == b"0"


def test_embedded_stats_cache_only_clears_disposable_namespace(tmp_path):
    root = _project(tmp_path / "project")
    manifest = {"name": "Test", "preprocessing": {"reject_thresh": 5}, "tools": {
        "processing": {"harmonic_selection": {"accepted": [1.2, 2.4]}},
        "stats": {"roi_definitions": ["Oz"], "group_significant_harmonics_cache": {
            "schema_version": 1, "entries": {"cached": {"some": "calculation"}}}}}}
    (root / "project.json").write_text(json.dumps(manifest))
    inventory = service.inspect_toolbox_caches(active_project_root=root)
    assert inventory.manifest_cache_entries == 1 and inventory.file_count == 0
    result = service.clear_toolbox_caches(inventory)
    assert not result.errors and result.cleared_project_roots == (root,)
    actual = json.loads((root / "project.json").read_text())
    assert actual["tools"]["stats"]["group_significant_harmonics_cache"]["entries"] == {}
    assert actual["tools"]["processing"] == manifest["tools"]["processing"]
    assert actual["preprocessing"] == manifest["preprocessing"]
    assert actual["tools"]["stats"]["roi_definitions"] == ["Oz"]


def test_app_cache_allowlist_keeps_live_maps_partial_updates_and_templates(tmp_path, monkeypatch):
    root = tmp_path / "app"
    locations = tuple(paths.CacheLocation(kind, root, root / kind, kind)
                      for kind in ("updates", "memmap", "meshes", "mri_templates"))
    monkeypatch.setattr(paths, "app_cache_locations", lambda: locations)
    monkeypatch.setattr(paths, "process_is_alive", lambda pid: pid == 123)
    disposable = [_write(root / relative) for relative in (
        "updates/FPVSToolbox-3.0.exe", "memmap/pid_456/participant_raw.dat",
        f"meshes/{KEY}.npz", f"mri_templates/{KEY}/brain_0p5mm.nii")]
    kept = [_write(root / relative, b"keep") for relative in (
        "updates/FPVSToolbox-3.0.exe.part", "updates/unrelated.exe",
        "memmap/pid_123/participant_raw.dat", "mne/fsaverage/mri/brain.mgz", "settings/settings.ini")]
    inventory = service.inspect_toolbox_caches()
    result = service.clear_toolbox_caches(inventory)
    assert result.removed_files == 4 and not result.errors
    assert all(not path.exists() for path in disposable)
    assert all(path.read_bytes() == b"keep" for path in kept)


def test_nonfinite_scientific_manifest_metadata_is_not_rewritten(tmp_path):
    root = _project(tmp_path / "project")
    data = {"name": "Test", "scientific_metadata": float("nan"), "tools": {"stats": {
        "group_significant_harmonics_cache": {"entries": {"cache": {"value": 1}}}}}}
    original = json.dumps(data).encode()
    (root / "project.json").write_bytes(original)
    result = service.clear_toolbox_caches(service.inspect_toolbox_caches(active_project_root=root))
    assert result.errors and not result.cleared_project_roots
    assert (root / "project.json").read_bytes() == original


def test_harmonic_helper_silent_failure_is_reported(tmp_path, monkeypatch):
    from Tools.Stats.data import group_harmonic_cache
    root = _project(tmp_path / "project")
    data = {"name": "Test", "tools": {"stats": {
        "group_significant_harmonics_cache": {"entries": {"cache": {"value": 1}}}}}}
    (root / "project.json").write_text(json.dumps(data))
    monkeypatch.setattr(group_harmonic_cache, "clear_cached_group_harmonic_selections", lambda _: 0)
    result = service.clear_toolbox_caches(service.inspect_toolbox_caches(active_project_root=root))
    assert result.errors and not result.cleared_project_roots


def test_cleanup_error_does_not_lose_actual_removed_counts(tmp_path, monkeypatch):
    root = _project(tmp_path / "project")
    _prepared(root)
    def failed_cleanup(*_args):
        raise ValueError("Directory changed")
    monkeypatch.setattr(service, "_remove_empty_cache_dirs", failed_cleanup)
    result = service.clear_toolbox_caches(service.inspect_toolbox_caches(active_project_root=root))
    assert result.removed_files == 1 and result.removed_bytes == 5
    assert result.errors


def test_cancel_during_removal_returns_truthful_partial_counts(tmp_path, monkeypatch):
    root = _project(tmp_path / "project")
    _prepared(root)
    _preflight(root)
    inventory = service.inspect_toolbox_caches(active_project_root=root)
    original = Path.unlink
    stopped = False
    def stop_after_one(self, *args, **kwargs):
        nonlocal stopped
        original(self, *args, **kwargs)
        stopped = True
    monkeypatch.setattr(Path, "unlink", stop_after_one)
    result = service.clear_toolbox_caches(inventory, should_cancel=lambda: stopped)
    assert result.cancelled and result.removed_files == 1 and result.removed_bytes == 5


def test_redirect_after_confirmation_aborts_before_any_deletion(tmp_path, monkeypatch):
    root = _project(tmp_path / "project")
    first, second = _prepared(root), _preflight(root)
    inventory = service.inspect_toolbox_caches(active_project_root=root)
    original = getattr(Path, "is_junction", lambda _: False)
    monkeypatch.setattr(Path, "is_junction", lambda self: self == first.parent or original(self), raising=False)
    with pytest.raises(service.ToolboxCacheChangedError):
        service.clear_toolbox_caches(inventory)
    assert first.exists() and second.exists()


@pytest.mark.parametrize("redirect", ["junction", "dangling_symlink"])
def test_redirected_pending_manifest_is_refused(tmp_path, monkeypatch, redirect):
    root = _project(tmp_path / "project")
    manifest = root / "project.json"
    original = json.dumps({"name": "Test", "tools": {"stats": {
        "group_significant_harmonics_cache": {"entries": {"cache": {"value": 1}}}}}}).encode()
    manifest.write_bytes(original)
    temporary = root / "project.json.tmp"
    external = tmp_path / "external.json"
    if redirect == "dangling_symlink":
        try:
            temporary.symlink_to(external)
        except OSError:
            pytest.skip("Symlink creation is unavailable in this Windows test environment")
        assert not temporary.exists()
    else:
        is_junction = getattr(Path, "is_junction", lambda _: False)
        monkeypatch.setattr(Path, "is_junction", lambda self: self == temporary or is_junction(self), raising=False)
    inventory = service.inspect_toolbox_caches(active_project_root=root)
    result = service.clear_toolbox_caches(inventory)
    assert result.errors and not result.cleared_project_roots
    assert "redirected" in result.errors[0]
    assert manifest.read_bytes() == original
    assert not manifest.is_symlink() and not external.exists()
