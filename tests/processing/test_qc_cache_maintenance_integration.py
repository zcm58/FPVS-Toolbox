"""Automatic retention and explicit clearing share cache ownership boundaries."""

from __future__ import annotations

import json

from Main_App.processing import toolbox_cache_paths
from Main_App.processing.preflight_qc_cache import (
    PREFLIGHT_QC_CACHE_METHOD_DIRECTORY,
    load_preflight_qc_cache,
    preflight_qc_cache_directory,
    save_preflight_qc_cache,
)
from Main_App.processing.preflight_qc_pruning import namespace_cache_publication_lock
from Main_App.processing.toolbox_cache import clear_toolbox_caches, inspect_toolbox_caches


def _key(source, threshold):
    stat = source.stat()
    return {
        "file_identity": {
            "resolved_path": str(source.resolve()), "recording_id": "P1-r1",
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "ctime_ns": stat.st_ctime_ns,
        },
        "settings": {
            "recording_scope": {"participant_id": "P1", "recording_id": "P1-r1"},
            "threshold": threshold,
        },
        "method": {"name": "condition_aware_preflight_qc", "version": PREFLIGHT_QC_CACHE_METHOD_DIRECTORY},
        "event_plan": {},
    }


def test_clear_then_repopulate_preserves_outputs_and_resets_retention_index(tmp_path, monkeypatch):
    monkeypatch.setattr(toolbox_cache_paths, "app_cache_locations", lambda: ())
    manifest = tmp_path / "project.json"
    manifest.write_text(json.dumps({"name": "Cache integration", "schema_version": 1}), encoding="utf-8")
    source = tmp_path / "P1.bdf"
    source.write_bytes(b"original recording")
    companion = tmp_path / "analysis.npy"
    companion.write_bytes(b"authoritative analysis companion")
    ledger = tmp_path / ".fpvs_processing" / "processing_ledger.json"
    ledger.parent.mkdir()
    ledger.write_bytes(b"reviewed processing ledger")
    originals = {path: path.read_bytes() for path in (source, manifest, companion, ledger)}

    first = save_preflight_qc_cache(tmp_path, **_key(source, 5), result={"metric": 1.25})
    second = save_preflight_qc_cache(tmp_path, **_key(source, 6), result={"metric": 1.25})
    assert not first.exists()
    assert second.exists()
    namespace = preflight_qc_cache_directory(tmp_path)
    assert (namespace / ".slots" / "index-state.json").exists()

    inventory = inspect_toolbox_caches(active_project_root=tmp_path)
    result = clear_toolbox_caches(inventory)
    assert not result.errors
    assert result.removed_files == inventory.file_count
    assert not second.exists()
    assert not (namespace / ".slots" / "index-state.json").exists()
    assert (namespace / ".publication.lock").exists()
    for path, content in originals.items():
        assert path.read_bytes() == content

    third = save_preflight_qc_cache(tmp_path, **_key(source, 7), result={"metric": 1.25})
    assert third.exists()
    assert load_preflight_qc_cache(tmp_path, **_key(source, 7)) == {"metric": 1.25}
    assert (namespace / ".slots" / "index-state.json").exists()


def test_explicit_clear_keeps_namespace_when_publication_is_busy(tmp_path, monkeypatch):
    monkeypatch.setattr(toolbox_cache_paths, "app_cache_locations", lambda: ())
    (tmp_path / "project.json").write_text('{"name":"Study"}', encoding="utf-8")
    source = tmp_path / "P1.bdf"
    source.write_bytes(b"recording")
    entry = save_preflight_qc_cache(tmp_path, **_key(source, 5), result={"metric": 1.25})
    inventory = inspect_toolbox_caches(active_project_root=tmp_path)
    with namespace_cache_publication_lock(entry.parent) as acquired:
        assert acquired
        result = clear_toolbox_caches(inventory)
    assert result.removed_files == 0
    assert result.errors
    assert entry.exists()
