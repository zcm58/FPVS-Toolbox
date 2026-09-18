from __future__ import annotations

import json
import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from Main_App.projects import manifest_store, project_manifest_transaction
from Main_App.projects.project import Project


def _worker_update(root, kind, ready, start):
    """Use actual independent runtime writers, with overlapping read windows."""
    if kind == "frequency":
        from Main_App.processing import frequency_domain_qc as module

        name = "_read_manifest"
        update = module.mark_frequency_domain_outputs_stale
    else:
        from Main_App.processing import artifact_freshness as module

        name = "_read_manifest_required"
        update = module.mark_selection_derivatives_stale
    original = getattr(module, name)

    def slow_read(path):
        payload = original(path)
        time.sleep(0.1)
        return payload

    setattr(module, name, slow_read)
    try:
        ready.put(kind)
        if not start.wait(20):
            raise TimeoutError("Concurrent writer did not start")
        update(root, reason=kind)
    finally:
        setattr(module, name, original)


def _crash_with_lock(path, ready):
    with project_manifest_transaction(path):
        ready.set()
        os._exit(7)


def _failed_write_in_process(path):
    before = path.read_bytes()

    def fail_fsync(_descriptor):
        raise OSError("injected worker disk failure")

    manifest_store.os.fsync = fail_fsync
    with pytest.raises(OSError, match="injected worker disk failure"):
        with project_manifest_transaction(path) as transaction:
            transaction.write({"must_not_publish": True})
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".project.json.*.tmp"))


def _hold_lock(path, ready, release):
    with project_manifest_transaction(path):
        ready.set()
        if not release.wait(20):
            raise TimeoutError("Lock contention test did not release")


@pytest.mark.parametrize("failure", ["partial_write", "replace"])
def test_project_save_failure_preserves_manifest_and_releases_transaction(tmp_path, monkeypatch, failure):
    project = Project.load(tmp_path)
    project.save()
    path = tmp_path / "project.json"
    before = path.read_bytes()
    project.name = "Pending local edit"
    original_fdopen = manifest_store.os.fdopen

    class InterruptedWrite:
        def __init__(self, *args, **kwargs):
            self.stream = original_fdopen(*args, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def write(self, payload):
            self.stream.write(payload[:len(payload) // 2])
            self.stream.flush()
            raise OSError("injected partial write")

    def denied(_source, _target):
        raise OSError("injected replace failure")

    with monkeypatch.context() as patch:
        if failure == "partial_write":
            patch.setattr(manifest_store.os, "fdopen", InterruptedWrite)
        else:
            patch.setattr(manifest_store.os, "replace", denied)
        with pytest.raises(OSError, match="injected"):
            project.save()
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".project.json.*.tmp"))
    project.save()
    assert json.loads(path.read_bytes())["name"] == "Pending local edit"


@pytest.mark.parametrize("execution", ["threads", "spawn"])
def test_independent_worker_metadata_survives_concurrent_updates(tmp_path, execution):
    project = Project.load(tmp_path)
    project.save()
    path = tmp_path / "project.json"
    with project_manifest_transaction(path) as transaction:
        payload = json.loads(path.read_bytes())
        payload["tools"] = {"unrelated": {"keep": [1, 2]}}
        transaction.write(payload)
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    if execution == "threads":
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_worker_update, tmp_path, kind, ready, start)
                       for kind in ("frequency", "artifacts")]
            for _ in futures:
                ready.get(timeout=30)
            start.set()
            for future in futures:
                future.result(timeout=30)
    else:
        children = [context.Process(target=_worker_update, args=(tmp_path, kind, ready, start))
                    for kind in ("frequency", "artifacts")]
        try:
            for child in children:
                child.start()
            for _ in children:
                ready.get(timeout=30)
            start.set()
            for child in children:
                child.join(timeout=30)
                assert child.exitcode == 0
        finally:
            for child in children:
                if child.is_alive():
                    child.terminate()
                child.join(timeout=5)
    ready.close()
    ready.join_thread()
    # An older GUI model must also retain both independently saved worker namespaces.
    project.name = "After worker updates"
    project.save()
    saved = json.loads(path.read_bytes())
    assert saved["name"] == "After worker updates"
    assert saved["tools"]["unrelated"] == {"keep": [1, 2]}
    assert saved["tools"]["frequency_domain_qc"]["stale_reason"] == "frequency"
    registry = saved["tools"]["post_processing"]["artifact_freshness"]
    assert registry["artifacts"]
    assert all(row["reason"] == "artifacts" for row in registry["artifacts"].values())


def test_spawned_process_exit_releases_manifest_lock(tmp_path):
    path = tmp_path / "project.json"
    path.write_text('{"preserved": true}', encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    child = context.Process(target=_crash_with_lock, args=(path, ready))
    child.start()
    try:
        assert ready.wait(20)
        child.join(timeout=20)
        assert child.exitcode == 7
        with project_manifest_transaction(path) as transaction:
            transaction.write({"preserved": True, "recovered": True})
        assert json.loads(path.read_bytes())["recovered"] is True
    finally:
        if child.is_alive():
            child.terminate()
        child.join(timeout=5)


def test_spawned_write_failure_preserves_manifest_and_allows_next_writer(tmp_path):
    path = tmp_path / "project.json"
    path.write_text('{"preserved": true}', encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    child = context.Process(target=_failed_write_in_process, args=(path,))
    child.start()
    try:
        child.join(timeout=20)
        assert child.exitcode == 0
        with project_manifest_transaction(path) as transaction:
            transaction.write({"preserved": True, "recovered": True})
        assert json.loads(path.read_bytes())["recovered"] is True
    finally:
        if child.is_alive():
            child.terminate()
        child.join(timeout=5)


def test_process_lock_contention_has_an_explicit_timeout(tmp_path, monkeypatch):
    path = tmp_path / "project.json"
    path.write_text("{}", encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    child = context.Process(target=_hold_lock, args=(path, ready, release))
    child.start()
    try:
        assert ready.wait(20)
        ticks = iter((0.0, 31.0))
        with monkeypatch.context() as patch:
            patch.setattr(manifest_store.time, "monotonic", lambda: next(ticks))
            with pytest.raises(TimeoutError, match="Timed out.*project.json"):
                with project_manifest_transaction(path):
                    pytest.fail("A second process acquired the held manifest lock")
    finally:
        release.set()
        child.join(timeout=20)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
    assert child.exitcode == 0


def test_transaction_rejects_invalid_disk_manifest_without_replacing_it(tmp_path):
    path = tmp_path / "project.json"
    path.write_text("{", encoding="utf-8")
    with project_manifest_transaction(path) as transaction:
        with pytest.raises(json.JSONDecodeError):
            transaction.write({"guess": "must not overwrite unreadable data"})
    assert path.read_text(encoding="utf-8") == "{"


@pytest.mark.parametrize("before,after", [(0, False), (1, True), (1, 1.0)])
def test_transaction_publishes_json_type_changes(tmp_path, before, after):
    path = tmp_path / "project.json"
    path.write_text(json.dumps({"value": before}), encoding="utf-8")
    with project_manifest_transaction(path) as transaction:
        assert transaction.write({"value": after}) is True
    saved = json.loads(path.read_bytes())["value"]
    assert type(saved) is type(after)
    assert saved == after


def test_transaction_preserves_bytes_for_key_order_and_whitespace_only_changes(tmp_path):
    path = tmp_path / "project.json"
    original = b'{"z": {"b": 2, "a": 1}, "a": true}\n'
    path.write_bytes(original)
    with project_manifest_transaction(path) as transaction:
        assert transaction.write_bytes(b'{\n "a": true, "z": {"a": 1, "b": 2}\n}') is False
    assert path.read_bytes() == original


@pytest.mark.parametrize("root_exists", [False, True])
def test_optional_manifest_updates_leave_missing_projects_untouched(tmp_path, root_exists):
    from Main_App.processing.frequency_domain_qc import (
        clear_manual_frequency_domain_participant_exclusions,
        clear_manual_frequency_domain_recording_exclusions,
    )
    from Tools.Stats.data.group_harmonic_cache import (
        GroupHarmonicCacheRequest,
        clear_cached_group_harmonic_selections,
        save_cached_group_harmonic_selection,
    )

    root = tmp_path / "unmanaged"
    if root_exists:
        root.mkdir()
    request = GroupHarmonicCacheRequest(root, root / "project.json", "unused", {}, {}, "unused")
    assert clear_cached_group_harmonic_selections(root) == 0
    assert save_cached_group_harmonic_selection(request, {}) is None
    assert clear_manual_frequency_domain_participant_exclusions(root, ["P01"]) == []
    assert clear_manual_frequency_domain_recording_exclusions(root, ["P01_visit1"]) == []
    assert root.exists() is root_exists
    if root_exists:
        assert list(root.iterdir()) == []
