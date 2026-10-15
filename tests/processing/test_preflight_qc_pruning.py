from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import errno
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import Main_App.processing.preflight_qc_cache as cache
import Main_App.processing.preflight_qc_pruning as pruning


def _parts(tmp_path, namespace=""):
    source = tmp_path / "P1.bdf"
    if not source.exists():
        source.write_bytes(b"source samples")
    info = source.stat()
    return {
        "file_identity": {"resolved_path": str(source.resolve()), "recording_id": "P1-r1",
                          "size": info.st_size, "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns},
        "settings": {"recording_scope": {"participant_id": "P1", "recording_id": "P1-r1"}, "threshold": 5},
        "method": {"name": "condition_aware_preflight_qc", "version": cache.PREFLIGHT_QC_CACHE_METHOD_DIRECTORY,
                   "event_extractor": "mne_shortest_1_annotation_fallback_v1", "evidence_codec": "typed_float64_v1"},
        "event_plan": {"span": {"condition_id": 1, "condition_label": "Faces", "repetition_index": 0,
                               "onset_sample": 100, "time_start_sample": 300, "time_stop_sample": 940}},
        "namespace": namespace,
    }


def _save(tmp_path, parts):
    return cache.save_preflight_qc_cache(tmp_path, result={"complete": True}, **parts)


@pytest.mark.parametrize("namespace", ["", "events", "occurrences", "raw_diagnostics"])
def test_cold_publication_writes_one_complete_index(tmp_path, monkeypatch, namespace):
    writes = []
    atomic_json = pruning._atomic_json

    def capture(path, value):
        if "slot" in value:
            writes.append((path, deepcopy(value)))
        atomic_json(path, value)

    monkeypatch.setattr(pruning, "_atomic_json", capture)
    parts = _parts(tmp_path, namespace)
    destination = _save(tmp_path, parts)
    assert len(writes) == 1
    index_path, index_payload = writes[0]
    assert json.loads(index_path.read_text()) == index_payload
    assert index_payload["entries"] == [
        {"name": destination.name, "stat": pruning._stat_identity(destination)}
    ]
    assert cache.load_preflight_qc_cache(tmp_path, **parts) == {"complete": True}


@pytest.mark.parametrize("namespace", ["", "events", "occurrences", "raw_diagnostics"])
def test_replacement_prunes_previous_settings_only_after_success(tmp_path, namespace):
    parts = _parts(tmp_path, namespace)
    old = _save(tmp_path, parts)
    changed = deepcopy(parts)
    changed["settings"]["threshold"] = 10
    changed["event_plan"]["span"]["time_stop_sample"] = 1200
    new = _save(tmp_path, changed)
    assert new.exists()
    assert not old.exists()
    assert cache.load_preflight_qc_cache(tmp_path, **changed) == {"complete": True}


@pytest.mark.parametrize("difference", ["condition", "repetition", "onset", "recording", "source"])
def test_other_logical_occurrences_are_preserved(tmp_path, difference):
    parts = _parts(tmp_path, "occurrences")
    old = _save(tmp_path, parts)
    changed = deepcopy(parts)
    span = changed["event_plan"]["span"]
    if difference == "condition":
        span.update(condition_id=2, condition_label="Objects")
    elif difference == "repetition":
        span["repetition_index"] = 1
    elif difference == "onset":
        span["onset_sample"] = 2000
    elif difference == "recording":
        changed["file_identity"]["recording_id"] = "P1-r2"
    else:
        other = tmp_path / "P9.bdf"
        other.write_bytes(b"other source")
        info = other.stat()
        changed["file_identity"].update(resolved_path=str(other.resolve()), size=info.st_size,
                                        mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)
    new = _save(tmp_path, changed)
    assert old.exists() and new.exists()


def test_full_recording_context_change_is_not_an_assumed_replacement(tmp_path):
    parts = _parts(tmp_path)
    old = _save(tmp_path, parts)
    parts["settings"]["recording_scope"]["participant_id"] = "P9"
    assert _save(tmp_path, parts).exists()
    assert old.exists()


def test_failed_replacement_keeps_all_previous_evidence(tmp_path, monkeypatch):
    parts = _parts(tmp_path)
    old = _save(tmp_path, parts)
    parts["settings"]["threshold"] = 10

    def failed(*_args):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(cache, "_publish_cache_file", failed)
    with pytest.raises(OSError, match="simulated"):
        _save(tmp_path, parts)
    assert old.exists()
    assert list(old.parent.glob("[0-9a-f]*.json")) == [old]


def test_source_changed_during_publication_keeps_predecessor(tmp_path, monkeypatch):
    parts = _parts(tmp_path)
    old = _save(tmp_path, parts)
    parts["settings"]["threshold"] = 10
    publish = cache._publish_cache_file

    def changed_source(*args):
        publish(*args)
        (tmp_path / "P1.bdf").write_bytes(b"source changed during cache publication")

    monkeypatch.setattr(cache, "_publish_cache_file", changed_source)
    new = _save(tmp_path, parts)
    assert old.exists() and new.exists()


def test_existing_generations_are_indexed_once_then_pruned_on_replacement(tmp_path, monkeypatch):
    parts = _parts(tmp_path, "occurrences")
    old_paths = []
    with monkeypatch.context() as patch:
        patch.setattr(cache, "prepare_pruning_candidates", lambda *_args, **_kwargs: None)
        for threshold in (5, 6, 7):
            parts["settings"]["threshold"] = threshold
            old_paths.append(_save(tmp_path, parts))
    parts["settings"]["threshold"] = 8
    current = _save(tmp_path, parts)
    assert all(not path.exists() for path in old_paths)
    assert current.exists()
    with monkeypatch.context() as patch:
        patch.setattr(Path, "iterdir", lambda *_args: pytest.fail("namespace was rescanned"))
        parts["settings"]["threshold"] = 9
        latest = _save(tmp_path, parts)
    assert latest.exists() and not current.exists()


@pytest.mark.parametrize("damage", ["checksum", "schema", "key", "name"])
def test_corrupt_or_unrecognized_entries_are_never_deleted(tmp_path, damage):
    parts = _parts(tmp_path)
    old = _save(tmp_path, parts)
    if damage == "name":
        unknown = old.with_name("user-notes.json")
        old.rename(unknown)
        old = unknown
    else:
        data = json.loads(old.read_text())
        if damage == "checksum":
            data["result"]["complete"] = False
        elif damage == "schema":
            data["schema_version"] = 99
        else:
            data["key"]["settings"]["threshold"] = -1
        old.write_text(json.dumps(data))
    parts["settings"]["threshold"] = 10
    assert _save(tmp_path, parts).exists()
    assert old.exists()


def test_changed_candidate_is_not_removed(tmp_path, monkeypatch):
    parts = _parts(tmp_path)
    old = _save(tmp_path, parts)
    publish = cache._publish_cache_file
    parts["settings"]["threshold"] = 10

    def changed_candidate(*args):
        publish(*args)
        old.write_text(old.read_text() + "\n")

    monkeypatch.setattr(cache, "_publish_cache_file", changed_candidate)
    _save(tmp_path, parts)
    assert old.exists()


def test_locked_predecessor_is_retried_without_blocking_other_cleanup(tmp_path, monkeypatch):
    parts = _parts(tmp_path, "occurrences")
    with monkeypatch.context() as patch:
        patch.setattr(cache, "prepare_pruning_candidates", lambda *_args, **_kwargs: None)
        locked = _save(tmp_path, parts)
        parts["settings"]["threshold"] = 6
        other = _save(tmp_path, parts)
    real_unlink = Path.unlink

    def locked_unlink(path, *args, **kwargs):
        if path == locked:
            raise PermissionError("file held open")
        return real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", locked_unlink)
        parts["settings"]["threshold"] = 7
        replacement = _save(tmp_path, parts)
    assert locked.exists() and replacement.exists() and not other.exists()
    parts["settings"]["threshold"] = 8
    latest = _save(tmp_path, parts)
    assert latest.exists() and not locked.exists() and not replacement.exists()


def test_concurrent_publications_keep_one_valid_latest_generation(tmp_path):
    parts = _parts(tmp_path, "occurrences")
    variants = []
    for threshold in range(8):
        changed = deepcopy(parts)
        changed["settings"]["threshold"] = threshold
        variants.append(changed)
    with ThreadPoolExecutor(max_workers=4) as executor:
        paths = list(executor.map(lambda item: _save(tmp_path, item), variants))
    existing = [path for path in paths if path.exists()]
    assert len(existing) == 1
    assert any(cache.load_preflight_qc_cache(tmp_path, **item) == {"complete": True} for item in variants)


def test_advisory_lock_is_nonblocking_and_survives_body_exception(tmp_path):
    directory = tmp_path / "cache"
    directory.mkdir()
    with pytest.raises(RuntimeError, match="body"):
        with pruning.namespace_cache_publication_lock(directory) as acquired:
            assert acquired
            with pruning.namespace_cache_publication_lock(directory) as second:
                assert not second
            raise RuntimeError("body")
    with pruning.namespace_cache_publication_lock(directory) as acquired:
        assert acquired
    assert (directory / ".publication.lock").exists()


def test_process_exit_does_not_leave_a_stuck_lock(tmp_path):
    directory = tmp_path / "cache"
    directory.mkdir()
    script = (
        "import importlib.util,os,sys; from pathlib import Path; "
        "spec=importlib.util.spec_from_file_location('cache_lock_probe',sys.argv[2]); "
        "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
        "lock=module.namespace_cache_publication_lock(Path(sys.argv[1])); "
        "acquired=lock.__enter__(); os._exit(0 if acquired else 1)"
    )
    subprocess.run([sys.executable, "-c", script, str(directory), pruning.__file__], check=True, timeout=15)
    with pruning.namespace_cache_publication_lock(directory) as acquired:
        assert acquired


def test_symlink_boundary_blocks_cache_write_and_cleanup(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    try:
        (project / ".fpvs_processing").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    parts = _parts(project)
    with pytest.raises(OSError, match="safe project-local"):
        _save(project, parts)
    assert list(outside.iterdir()) == []


def test_symlink_candidate_is_preserved_and_target_untouched(tmp_path):
    parts = _parts(tmp_path)
    old = _save(tmp_path, parts)
    target = tmp_path / "keep.json"
    target.write_text(old.read_text())
    old.unlink()
    try:
        old.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    expected = target.read_bytes()
    parts["settings"]["threshold"] = 10
    _save(tmp_path, parts)
    assert old.is_symlink() and target.read_bytes() == expected


def test_windows_reparse_candidate_is_preserved_without_following_it(tmp_path, monkeypatch):
    parts = _parts(tmp_path)
    old = _save(tmp_path, parts)
    original_lstat = Path.lstat

    def reparse_lstat(path, *args, **kwargs):
        info = original_lstat(path, *args, **kwargs)
        if path == old:
            return SimpleNamespace(st_mode=info.st_mode, st_nlink=info.st_nlink,
                                   st_file_attributes=0x400)
        return info

    with monkeypatch.context() as patch:
        patch.setattr(Path, "lstat", reparse_lstat)
        parts["settings"]["threshold"] = 10
        _save(tmp_path, parts)
    assert old.exists()


@pytest.mark.parametrize("stage", ["started", "complete", "slot"])
def test_transient_index_sharing_denial_retries_without_losing_generation(
    tmp_path, monkeypatch, stage,
):
    parts = _parts(tmp_path, "occurrences")
    expected_bytes = _save(tmp_path / "baseline", parts).read_bytes()
    replace = pruning.os.replace
    failures = []
    waits = []

    def sharing_denial(temporary, target):
        is_stage = target.parent.name == ".slots" and (
            target.name != "index-state.json" if stage == "slot" else
            target.name == "index-state.json" and json.loads(temporary.read_text())["state"] == stage
        )
        if is_stage and not failures:
            failures.append(target)
            error = PermissionError(errno.EACCES, "simulated brief index sharing denial", str(target))
            error.winerror = 5
            raise error
        replace(temporary, target)

    with monkeypatch.context() as patch:
        patch.setattr(pruning.os, "replace", sharing_denial)
        patch.setattr(pruning.time, "sleep", waits.append)
        old = _save(tmp_path, parts)
    assert len(failures) == 1
    assert old.read_bytes() == expected_bytes
    slots = old.parent / ".slots"
    assert json.loads((slots / "index-state.json").read_text())["state"] == "complete"
    indexes = [path for path in slots.glob("*.json") if path.name != "index-state.json"]
    assert len(indexes) == 1
    assert json.loads(indexes[0].read_text())["entries"][0]["name"] == old.name
    assert not list(slots.glob("*.tmp"))
    assert waits and waits[0] == 0.01

    parts["settings"]["threshold"] = 10
    latest = _save(tmp_path, parts)
    assert latest.exists() and not old.exists()
    assert cache.load_preflight_qc_cache(tmp_path, **parts) == {"complete": True}


def test_persistent_index_denial_is_bounded_and_keeps_previous_evidence(
    tmp_path, monkeypatch, caplog,
):
    parts = _parts(tmp_path, "occurrences")
    with monkeypatch.context() as patch:
        patch.setattr(cache, "prepare_pruning_candidates", lambda *_args, **_kwargs: None)
        old = _save(tmp_path, parts)
    old_bytes = old.read_bytes()
    replace = pruning.os.replace
    attempts = []
    waits = []

    def persistent_denial(temporary, target):
        if target.parent.name == ".slots":
            attempts.append(target)
            raise PermissionError(errno.EACCES, "simulated persistent index sharing denial", str(target))
        replace(temporary, target)

    parts["settings"]["threshold"] = 10
    with monkeypatch.context() as patch:
        patch.setattr(pruning.os, "replace", persistent_denial)
        patch.setattr(pruning.time, "sleep", waits.append)
        latest = _save(tmp_path, parts)
    assert len(attempts) == 6
    assert waits == [0.01, 0.02, 0.05, 0.1, 0.1]
    assert old.read_bytes() == old_bytes and latest.exists()
    assert cache.load_preflight_qc_cache(tmp_path, **parts) == {"complete": True}
    assert "preflight_cache_index_unavailable" in caplog.text
    assert "simulated persistent index sharing denial" in caplog.text
    assert not list((latest.parent / ".slots").glob("*.tmp"))

    parts["settings"]["threshold"] = 11
    recovered = _save(tmp_path, parts)
    assert recovered.exists() and not old.exists() and not latest.exists()


def test_nonpermission_index_failure_preserves_target_without_retry(tmp_path, monkeypatch):
    path = tmp_path / "index.json"
    previous = b'{"previous":true}'
    path.write_bytes(previous)
    attempts = []
    waits = []

    def disk_full(temporary, target):
        attempts.append(target)
        raise OSError(errno.ENOSPC, "simulated full disk", str(target))

    monkeypatch.setattr(pruning.os, "replace", disk_full)
    monkeypatch.setattr(pruning.time, "sleep", waits.append)
    with pytest.raises(OSError, match="simulated full disk"):
        pruning._atomic_json(path, {"replacement": True})
    assert attempts == [path] and waits == []
    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]
