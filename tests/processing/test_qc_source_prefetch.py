"""Run-owned prefetch must be optional, exclusive, bounded, and disposable."""

from pathlib import Path
from copy import deepcopy
import gc
import hashlib
import os
from threading import Event, Thread, get_ident
from types import SimpleNamespace

import numpy as np
import pytest

from Main_App.processing import qc_source_prefetch as prefetch


class _Raw:
    def __init__(self, preload_path):
        self._data = np.memmap(preload_path, dtype=np.float64, mode="w+", shape=(2, 4))
        self._data[:] = np.arange(8).reshape(2, 4)
        self.close_count = 0

    def close(self):
        self.close_count += 1


@pytest.fixture
def recordings(tmp_path, monkeypatch):
    infos = []
    for folder in ("visit1", "visit2", "visit3"):
        source = tmp_path / folder / "participant.bdf"
        source.parent.mkdir()
        source.write_bytes(b"x" * 128)
        infos.append(SimpleNamespace(path=source, subject_id=f"P{len(infos) + 1:02d}"))
    created = []

    def load(_app, _source, **kwargs):
        raw = _Raw(kwargs["preload_path"])
        created.append((raw, Path(kwargs["preload_path"]), kwargs))
        return raw

    monkeypatch.setattr(prefetch.load_utils, "load_eeg_file", load)
    monkeypatch.setattr(prefetch.shutil, "disk_usage", lambda _path: SimpleNamespace(free=100 * 1024**3))
    return tmp_path, infos, created


def test_construction_does_no_io_and_close_before_run_is_safe(recordings, monkeypatch):
    root, infos, _created = recordings

    def forbidden(*_args, **_kwargs):
        pytest.fail("GUI-side construction performed filesystem I/O")

    with monkeypatch.context() as patched:
        patched.setattr(Path, "resolve", forbidden)
        patched.setattr(Path, "stat", forbidden)
        patched.setattr(prefetch.tempfile, "mkdtemp", forbidden)
        session = prefetch.QcSourcePrefetch(root, infos, {})
        session.close()
        session.run()
    assert session.finished.is_set()
    assert session.take(infos[0].path, settings={}) is None
    assert not (root / ".fpvs_processing").exists()


@pytest.mark.parametrize("exclusions", [["p01"], {"P01": True}, '[" P01 "]'])
def test_initial_exclusions_use_participant_identity_for_every_recording(recordings, monkeypatch, exclusions):
    root, infos, created = recordings
    infos[1].subject_id = "p01"
    # This filename resembles an excluded participant, but its actual identity
    # is P03 and must remain eligible.
    infos[2].path = infos[2].path.with_name("P01.bdf")
    infos[2].path.write_bytes(b"x" * 128)
    source_identity = prefetch._source_identity

    def only_eligible(path):
        assert path == infos[2].path
        return source_identity(path)

    monkeypatch.setattr(prefetch, "_source_identity", only_eligible)
    session = prefetch.QcSourcePrefetch(root, infos, {"manual_excluded_participants": exclusions})
    session.run()
    assert len(created) == 1
    assert session.take(infos[0].path, settings={}) is None
    assert session.take(infos[1].path, settings={}) is None
    raw = session.take(infos[2].path, settings={})
    assert raw is created[0][0]
    session.release(raw)
    session.close()
    assert all(info.path.exists() for info in infos)


def test_initially_excluded_sources_do_no_io_and_unexclude_uses_normal_fallback(recordings, monkeypatch):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {"manual_excluded_participants": ["P01"]})
    session.update_participant_exclusions([])
    with monkeypatch.context() as patched:
        patched.setattr(Path, "resolve", lambda *_args, **_kwargs: pytest.fail("Excluded source caused I/O"))
        patched.setattr(prefetch, "_source_sha256", lambda *_args: pytest.fail("Excluded source was hashed"))
        session.run()
    assert session.take(infos[0].path, settings={}) is None
    session.close()
    assert not created
    assert not (root / ".fpvs_processing").exists()


@pytest.mark.parametrize("begin_consumption", [False, True])
def test_active_and_pending_excluded_sources_cannot_publish_or_be_taken(recordings, monkeypatch, begin_consumption):
    root, infos, created = recordings
    infos[0].subject_id = "P02"
    infos[1].subject_id = infos[2].subject_id = "P01"
    loading, allow_load = Event(), Event()
    loader = prefetch.load_utils.load_eeg_file

    def blocked_second(app, source, **kwargs):
        if source == str(infos[1].path):
            loading.set()
            assert allow_load.wait(5)
        return loader(app, source, **kwargs)

    monkeypatch.setattr(prefetch.load_utils, "load_eeg_file", blocked_second)
    session = prefetch.QcSourcePrefetch(root, infos, {})
    producer = Thread(target=session.run)
    producer.start()
    retained = None
    try:
        assert loading.wait(5)
        session.update_participant_exclusions(["p01"])
        assert session.take(infos[1].path, settings={}) is None
        assert session.take(infos[2].path, settings={}) is None
        if begin_consumption:
            assert session.begin_consumption() is True
        assert producer.is_alive()
        retained = session.take(infos[0].path, settings={})
        assert retained is created[0][0]
        allow_load.set()
        producer.join(5)
        assert not producer.is_alive()
        assert len(created) == 2
        assert created[1][0].close_count == 1
        assert not created[1][1].exists()
        assert session.begin_consumption() is False
        assert session.take(infos[1].path, settings={}) is None
    finally:
        allow_load.set()
        producer.join(5)
        if retained is not None:
            session.release(retained)
        session.close()


def test_ready_exclusion_update_is_io_free_and_background_retirement_preserves_other_sources(recordings, monkeypatch):
    root, infos, created = recordings
    infos[1].subject_id = "p01"
    session = prefetch.QcSourcePrefetch(root, infos, {})
    session.run()
    closed_threads = []
    for raw, _path, _kwargs in created:
        close = raw.close

        def observed_close(close=close):
            closed_threads.append(get_ident())
            close()

        raw.close = observed_close
    with monkeypatch.context() as patched:
        patched.setattr(Path, "stat", lambda *_args: pytest.fail("GUI update performed I/O"))
        patched.setattr(Path, "unlink", lambda *_args, **_kwargs: pytest.fail("GUI update removed data"))
        session.update_participant_exclusions("P01")
    assert closed_threads == []
    assert session.take(infos[0].path, settings={}) is None
    maintenance = Thread(target=session.maintain)
    maintenance.start()
    maintenance.join(5)
    assert not maintenance.is_alive()
    assert closed_threads == [maintenance.ident, maintenance.ident]
    assert session._retained_bytes == created[2][0]._data.nbytes
    assert not created[0][1].exists() and not created[1][1].exists()
    raw = session.take(infos[2].path, settings={})
    assert raw is created[2][0]
    session.release(raw)
    session.close()


def test_new_exclusion_does_not_close_borrowed_raw_or_mutate_its_samples(recordings):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    raw = session.take(infos[0].path, settings={})
    before = raw._data.tobytes()
    session.update_participant_exclusions(["P01"])
    session.maintain()
    assert raw.close_count == 0 and created[0][1].exists()
    assert raw._data.tobytes() == before
    assert session.source_content_identity_for(raw) is not None
    session.release(raw)
    assert raw.close_count == 1
    assert session._retained_bytes == 0
    session.close()


def test_exclusion_during_take_validation_vetoes_handoff_and_consumer_releases(recordings, monkeypatch):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    hashing, allow_hash = Event(), Event()
    source_hash = prefetch._source_sha256
    results = []

    def blocked_hash(path, should_cancel):
        hashing.set()
        assert allow_hash.wait(5)
        return source_hash(path, should_cancel)

    monkeypatch.setattr(prefetch, "_source_sha256", blocked_hash)
    consumer = Thread(target=lambda: results.append(session.take(infos[0].path, settings={})))
    consumer.start()
    try:
        assert hashing.wait(5)
        session.update_participant_exclusions(["P01"])
        session.maintain()
        assert created[0][0].close_count == 0
        assert created[0][1].exists()
        allow_hash.set()
        consumer.join(5)
        assert not consumer.is_alive()
        assert results == [None]
        assert created[0][0].close_count == 1
        assert not created[0][1].exists()
        assert session._borrowed == {} and session._retained_bytes == 0
    finally:
        allow_hash.set()
        consumer.join(5)
        session.close()


def test_retirement_reclaims_budget_before_the_next_source(recordings, monkeypatch):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos, {}, max_prefetch_bytes=550)
    prepare = session._prepare

    def exclude_after_first(entry, index):
        prepare(entry, index)
        if index == 0:
            session.update_participant_exclusions(["P01"])

    monkeypatch.setattr(session, "_prepare", exclude_after_first)
    session.run()
    assert len(created) == 2
    assert created[0][0].close_count == 1
    assert not created[0][1].exists()
    raw = session.take(infos[1].path, settings={})
    assert raw is created[1][0]
    session.release(raw)
    session.close()


def test_close_waits_for_active_retirement_and_disposes_only_once(recordings):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    closing, allow_close, finished = Event(), Event(), Event()
    raw = created[0][0]
    original_close = raw.close

    def blocked_close():
        closing.set()
        assert allow_close.wait(5)
        original_close()

    raw.close = blocked_close
    session.update_participant_exclusions(["P01"])
    maintenance = Thread(target=session.maintain)
    closer = Thread(target=lambda: (session.close(), finished.set()))
    maintenance.start()
    try:
        assert closing.wait(5)
        closer.start()
        assert not finished.wait(0.05)
        allow_close.set()
        maintenance.join(5)
        closer.join(5)
        assert finished.is_set()
        assert raw.close_count == 1
        assert session._retained_bytes == 0
        assert not created[0][1].parent.exists()
    finally:
        allow_close.set()
        maintenance.join(5)
        if closer.ident is not None:
            closer.join(5)
        session.close()


def test_close_disposes_queued_retirement_even_without_maintenance_loop(recordings):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    session.update_participant_exclusions(["P01"])
    session.update_participant_exclusions([])
    assert session.take(infos[0].path, settings={}) is None
    session.close()
    assert created[0][0].close_count == 1
    assert not created[0][1].parent.exists()


def test_handoff_is_exact_single_use_and_same_stems_have_unique_paths(recordings):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos, {})
    session.run()
    paths = [path for _raw, path, _kwargs in created]
    assert len(set(paths)) == len(infos)
    assert all(path.is_relative_to(root / ".fpvs_processing") for path in paths)
    for info, (expected, path, _kwargs) in zip(infos, created):
        raw = session.take(info.path, settings={"high_pass": 1.0, "reject_thresh": 5})
        assert raw is expected
        np.testing.assert_array_equal(raw._data, np.arange(8).reshape(2, 4))
        assert session.take(info.path, settings={}) is None
        session.release(raw)
        session.release(raw)
        assert raw.close_count == 1
        assert not path.exists()
    session.close()
    session.close()
    assert not paths[0].parent.exists()
    assert all(source.path.exists() for source in infos)


def test_source_content_identity_is_only_available_after_validated_exclusive_take(recordings, monkeypatch):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    expected_raw = created[0][0]
    raw_attributes = set(vars(expected_raw))
    assert session.source_content_identity_for(expected_raw) is None
    source_hash = prefetch._source_sha256

    def verify(path, should_cancel):
        assert session.source_content_identity_for(expected_raw) is None
        return source_hash(path, should_cancel)

    monkeypatch.setattr(prefetch, "_source_sha256", verify)
    raw = session.take(infos[0].path, settings={})
    assert raw is expected_raw
    assert set(vars(raw)) == raw_attributes
    expected = {"path": str(infos[0].path.resolve()), "size_bytes": 128,
                "sha256": hashlib.sha256(b"x" * 128).hexdigest()}
    with monkeypatch.context() as patched:
        patched.setattr(Path, "stat", lambda *_args: pytest.fail("identity accessor performed I/O"))
        actual = session.source_content_identity_for(raw)
        assert actual == expected
        actual["sha256"] = "changed by caller"
        assert session.source_content_identity_for(raw) == expected
        assert session.source_content_identity_for(object()) is None
    session.release(raw)
    assert session.source_content_identity_for(raw) is None
    session.close()


@pytest.mark.parametrize("changed", [
    {"ref_channel1": "EXG3"}, {"ref_channel2": "EXG4"},
    {"stim_channel": "Trigger"}, {"max_idx_keep": 32},
    {"electrode_mapping_profile": "biosemi_a1_b32"},
])
def test_changed_loader_settings_are_a_miss(recordings, changed):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    assert session.take(infos[0].path, settings=changed) is None
    session.close()
    assert created[0][0].close_count == 1
    assert not created[0][1].parent.exists()


def test_equivalent_loader_aliases_can_reuse_source(recordings):
    root, infos, _created = recordings
    settings = {"ref_ch1": "EXG3", "ref_chan2": "EXG4", "stim": "Trigger", "max_chan_idx_keep": 32}
    session = prefetch.QcSourcePrefetch(root, infos[:1], settings)
    session.run()
    raw = session.take(infos[0].path, settings={
        "ref_channel1": "EXG3", "ref_channel2": "EXG4", "stim_channel": "Trigger", "max_idx_keep": 32,
    })
    assert raw is not None
    session.release(raw)
    session.close()


def test_source_changed_after_prefetch_is_closed_and_reloaded_normally(recordings):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    infos[0].path.write_bytes(b"changed source")
    assert session.take(infos[0].path, settings={}) is None
    assert created[0][0].close_count == 1
    assert not created[0][1].exists()
    session.close()


def test_source_changed_during_load_is_never_published(recordings, monkeypatch):
    root, infos, created = recordings
    loader = prefetch.load_utils.load_eeg_file

    def changed_load(app, source, **kwargs):
        raw = loader(app, source, **kwargs)
        Path(source).write_bytes(b"changed during read")
        return raw

    monkeypatch.setattr(prefetch.load_utils, "load_eeg_file", changed_load)
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    assert session.take(infos[0].path, settings={}) is None
    assert created[0][0].close_count == 1
    session.close()


@pytest.mark.parametrize("during_load", [False, True])
def test_same_size_content_change_with_restored_timestamps_is_a_miss(recordings, monkeypatch, during_load):
    root, infos, created = recordings
    source = infos[0].path
    before = source.stat()
    identity = prefetch._source_identity(source)
    # Windows ctime is creation time. Model its unchanged stat identity on
    # every platform so this regression specifically requires content binding.
    monkeypatch.setattr(prefetch, "_source_identity", lambda _path: identity)

    def overwrite_with_restored_mtime():
        source.write_bytes(b"y" * before.st_size)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert source.stat().st_size == before.st_size
        assert source.stat().st_mtime_ns == before.st_mtime_ns

    if during_load:
        loader = prefetch.load_utils.load_eeg_file

        def changed_load(app, filename, **kwargs):
            raw = loader(app, filename, **kwargs)
            overwrite_with_restored_mtime()
            return raw

        monkeypatch.setattr(prefetch.load_utils, "load_eeg_file", changed_load)
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    if not during_load:
        overwrite_with_restored_mtime()
    assert session.take(source, settings={}) is None
    assert created[0][0].close_count == 1
    assert not created[0][1].exists()
    session.close()


def test_take_content_hash_cancels_between_chunks_and_releases_source(recordings, monkeypatch):
    root, infos, created = recordings
    monkeypatch.setattr(prefetch, "_HASH_CHUNK_BYTES", 16)
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    checks = 0

    def cancel_during_hash():
        nonlocal checks
        checks += 1
        return checks >= 4

    assert session.take(infos[0].path, settings={}, should_cancel=cancel_during_hash) is None
    assert checks == 4
    assert created[0][0].close_count == 1
    assert not created[0][1].exists()
    session.close()


def test_unexpected_take_hash_error_never_strands_borrowed_ownership(recordings, monkeypatch):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()

    def fail_hash(*_args, **_kwargs):
        raise MemoryError("injected hash allocation failure")

    monkeypatch.setattr(prefetch, "_source_sha256", fail_hash)
    with pytest.raises(MemoryError, match="injected"):
        session.take(infos[0].path, settings={})
    session.close()
    assert created[0][0].close_count == 1
    assert not created[0][1].parent.exists()


def test_pending_take_waits_for_producer_and_cancel_wakes_it(recordings, monkeypatch):
    root, infos, created = recordings
    loading, allow_load, consumer_done = Event(), Event(), Event()
    loader = prefetch.load_utils.load_eeg_file

    def blocked_load(app, source, **kwargs):
        loading.set()
        assert allow_load.wait(5)
        return loader(app, source, **kwargs)

    monkeypatch.setattr(prefetch.load_utils, "load_eeg_file", blocked_load)
    session = prefetch.QcSourcePrefetch(root, infos, {})
    producer = Thread(target=session.run)
    producer.start()
    assert loading.wait(5)
    results = []

    def take():
        results.append(session.take(infos[0].path, settings={}))
        consumer_done.set()

    consumer = Thread(target=take)
    consumer.start()
    try:
        assert not consumer_done.wait(0.05)
        session.cancel()
        assert consumer_done.wait(1)
        assert results == [None]
    finally:
        allow_load.set()
        consumer.join(5)
        producer.join(5)
        session.close()
    assert not producer.is_alive()
    assert len(created) == 1
    assert created[0][0].close_count == 1
    assert not created[0][1].parent.exists()


def test_consumer_cancellation_does_not_cancel_other_recordings(recordings, monkeypatch):
    root, infos, _created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    assert session.take(infos[0].path, settings={}, should_cancel=lambda: True) is None
    session.run()
    raw = session.take(infos[0].path, settings={})
    assert raw is not None
    session.release(raw)
    session.close()


def test_pending_take_adopts_the_completed_source_without_another_load(recordings, monkeypatch):
    root, infos, created = recordings
    loading, allow_load, consumer_done = Event(), Event(), Event()
    loader = prefetch.load_utils.load_eeg_file

    def blocked_load(app, source, **kwargs):
        loading.set()
        assert allow_load.wait(5)
        return loader(app, source, **kwargs)

    monkeypatch.setattr(prefetch.load_utils, "load_eeg_file", blocked_load)
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    results = []

    def take():
        results.append(session.take(infos[0].path, settings={}))
        consumer_done.set()

    producer, consumer = Thread(target=session.run), Thread(target=take)
    producer.start()
    assert loading.wait(5)
    consumer.start()
    try:
        assert loading.wait(5)
        assert not consumer_done.wait(0.05)
        allow_load.set()
        assert consumer_done.wait(5)
        assert results == [created[0][0]]
        assert len(created) == 1
    finally:
        allow_load.set()
        producer.join(5)
        consumer.join(5)
        for raw in results:
            session.release(raw)
        session.close()


def test_close_waits_until_borrowed_raw_is_released(recordings):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    raw = session.take(infos[0].path, settings={})
    closed = Event()

    def close():
        session.close()
        closed.set()

    closer = Thread(target=close)
    closer.start()
    try:
        assert not closed.wait(0.05)
        assert created[0][1].exists()
    finally:
        session.release(raw)
        closer.join(5)
    assert closed.is_set()
    assert not created[0][1].parent.exists()


def test_byte_budget_skips_unavailable_entries_without_waiting(recordings):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos, {}, max_prefetch_bytes=550)
    session.run()
    assert len(created) == 1
    assert session.take(infos[1].path, settings={}) is None
    assert session.take(infos[2].path, settings={}) is None
    session.close()


def test_disk_reserve_prevents_prefetch_and_keeps_fallback_ready(recordings, monkeypatch):
    root, infos, created = recordings
    monkeypatch.setattr(prefetch.shutil, "disk_usage", lambda _path: SimpleNamespace(free=prefetch._DISK_RESERVE_BYTES + 500))
    session = prefetch.QcSourcePrefetch(root, infos, {})
    session.run()
    assert session.finished.is_set()
    assert not created
    assert session.take(infos[0].path, settings={}) is None
    session.close()


def test_loader_failure_cleans_partial_file_and_other_sources_continue(recordings, monkeypatch):
    root, infos, created = recordings
    loader = prefetch.load_utils.load_eeg_file

    def sometimes_fails(app, source, **kwargs):
        if source == str(infos[0].path):
            Path(kwargs["preload_path"]).write_bytes(b"partial")
            raise OSError("injected disk error")
        return loader(app, source, **kwargs)

    monkeypatch.setattr(prefetch.load_utils, "load_eeg_file", sometimes_fails)
    session = prefetch.QcSourcePrefetch(root, infos, {})
    session.run()
    assert session.take(infos[0].path, settings={}) is None
    assert len(created) == 2
    assert len(list(created[0][1].parent.iterdir())) == 2
    session.close()
    assert not created[0][1].parent.exists()


def test_directory_failure_finishes_all_pending_entries(recordings, monkeypatch):
    root, infos, created = recordings

    def fail_directory(**_kwargs):
        raise OSError("injected permission error")

    monkeypatch.setattr(prefetch.tempfile, "mkdtemp", fail_directory)
    session = prefetch.QcSourcePrefetch(root, infos, {})
    session.run()
    assert session.finished.is_set()
    assert all(session.take(info.path, settings={}) is None for info in infos)
    session.close()
    assert not created


def test_raw_close_failure_still_releases_mmap_and_temporary_files(recordings):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    raw = session.take(infos[0].path, settings={})

    def fail_close():
        raise OSError("injected raw close failure")

    raw.close = fail_close
    session.release(raw)
    session.close()
    assert not created[0][1].parent.exists()


def test_begin_consumption_keeps_ready_and_active_sources_but_skips_pending(recordings, monkeypatch):
    root, infos, created = recordings
    loading, allow_load = Event(), Event()
    loader = prefetch.load_utils.load_eeg_file

    def blocked_second(app, source, **kwargs):
        if source == str(infos[1].path):
            loading.set()
            assert allow_load.wait(5)
        return loader(app, source, **kwargs)

    monkeypatch.setattr(prefetch.load_utils, "load_eeg_file", blocked_second)
    session = prefetch.QcSourcePrefetch(root, infos, {})
    producer = Thread(target=session.run)
    producer.start()
    try:
        assert loading.wait(5)
        assert session.begin_consumption() is True
        assert session.take(infos[2].path, settings={}) is None
        ready = session.take(infos[0].path, settings={})
        assert ready is not None
        session.release(ready)
        allow_load.set()
        producer.join(5)
        active = session.take(infos[1].path, settings={})
        assert active is not None
        session.release(active)
        assert session.begin_consumption() is False
        assert len(created) == 2
    finally:
        allow_load.set()
        producer.join(5)
        session.close()


def test_begin_consumption_before_producer_starts_is_an_immediate_miss(recordings):
    root, infos, created = recordings
    session = prefetch.QcSourcePrefetch(root, infos, {})
    assert session.begin_consumption() is False
    assert session.take(infos[0].path, settings={}) is None
    session.run()
    session.close()
    assert not created
    assert not (root / ".fpvs_processing").exists()


def test_rejected_cleanup_cannot_be_bypassed_by_mne_or_directory_finalizers(recordings, monkeypatch):
    from tests.processing.test_preprocess_kurtosis_gate import _raw

    root, infos, _created = recordings
    paths = []

    def load(_app, _source, **kwargs):
        raw = _raw()
        data = np.memmap(kwargs["preload_path"], mode="w+", dtype=np.float64, shape=raw._data.shape)
        data[:] = raw._data
        raw._data = data
        paths.append(Path(kwargs["preload_path"]))
        return raw

    monkeypatch.setattr(prefetch.load_utils, "load_eeg_file", load)
    session = prefetch.QcSourcePrefetch(root, infos[:1], {})
    session.run()
    raw = session.take(infos[0].path, settings={})
    mmap = raw._data._mmap
    preserved = paths[0].read_bytes()

    def reject_redirected_path(*_args, **_kwargs):
        raise ValueError("simulated redirected cache ancestor")

    monkeypatch.setattr(prefetch, "checked_path", reject_redirected_path)
    session.release(raw)
    assert raw._data is None
    assert mmap.closed
    del raw
    session.close()
    del session
    gc.collect()
    # Neither MNE Raw.__del__ nor TemporaryDirectory's implicit finalizer may
    # delete a filename after explicit cleanup rejects its ownership boundary.
    assert paths[0].read_bytes() == preserved
    assert paths[0].parent.is_dir()


@pytest.mark.parametrize("review_only", [True, False])
def test_real_preprocessing_is_exact_after_memmap_handoff(recordings, monkeypatch, review_only):
    from Main_App.processing import preprocess
    from tests.processing.test_preprocess_kurtosis_gate import _params, _raw

    root, infos, _created = recordings
    source = infos[0].path
    original = _raw()
    original._data[-1, 0] = 1.0
    original._data[-1, 100:601:50] = 55.0
    direct_bad = original.ch_names[3]
    settings = _params(source)
    settings.update(
        project_root=str(root), high_pass=0.5, low_pass=30.0,
        downsample_rate=80.0, enable_kurtosis_checkpoint_cache=False,
        kurtosis_auto_interpolate_all=True,
    )
    mapped = []

    def load(_app, _source, **kwargs):
        raw = original.copy()
        data = np.memmap(kwargs["preload_path"], mode="w+", dtype=np.float64, shape=raw._data.shape)
        data[:] = raw._data
        raw._data = data
        mapped.append((data._mmap, Path(kwargs["preload_path"])))
        return raw

    monkeypatch.setattr(prefetch.load_utils, "load_eeg_file", load)
    session = prefetch.QcSourcePrefetch(root, infos[:1], settings)
    session.run()
    acquired = session.take(source, settings=settings)
    assert acquired is not None
    reference = original.copy()
    actual_processed = expected_processed = None
    try:
        if review_only:
            expected = preprocess.prepare_kurtosis_review_evidence(
                reference, deepcopy(settings), lambda _message: None,
                source.name, direct_bad_channels=[direct_bad], copy_raw=False,
            )
            actual = preprocess.prepare_kurtosis_review_evidence(
                acquired, deepcopy(settings), lambda _message: None,
                source.name, direct_bad_channels=[direct_bad], copy_raw=False,
            )
            assert actual == expected
            assert acquired._data.shape == reference._data.shape
            assert acquired._data.dtype == reference._data.dtype
            assert acquired._data.tobytes() == reference._data.tobytes()
        else:
            expected_params, actual_params = deepcopy(settings), deepcopy(settings)
            reference.info["bads"] = [direct_bad]
            acquired.info["bads"] = [direct_bad]
            expected_processed, expected_count = preprocess.perform_preprocessing(
                reference, expected_params, lambda _message: None, source.name,
            )
            actual_processed, actual_count = preprocess.perform_preprocessing(
                acquired, actual_params, lambda _message: None, source.name,
            )
            assert actual_processed is not None
            assert expected_processed is not None
            assert actual_count == expected_count
            assert actual_processed._data.shape == expected_processed._data.shape
            assert actual_processed._data.dtype == expected_processed._data.dtype
            assert actual_processed._data.tobytes() == expected_processed._data.tobytes()
            assert actual_params["_fpvs_kurtosis_qc_evidence"] == expected_params["_fpvs_kurtosis_qc_evidence"]
            assert actual_params["_fpvs_kurtosis_decision_plan"] == expected_params["_fpvs_kurtosis_decision_plan"]
        assert acquired.info["sfreq"] == 80.0
        assert not isinstance(acquired._data, np.memmap)
    finally:
        if actual_processed is not None and actual_processed is not acquired:
            actual_processed.close()
        if expected_processed is not None and expected_processed is not reference:
            expected_processed.close()
        reference.close()
        session.release(acquired)
        session.close()
        original.close()
    assert mapped[0][0].closed
    assert not mapped[0][1].parent.exists()
