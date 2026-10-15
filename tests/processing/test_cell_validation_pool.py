"""Native outcome bytes and independent live-admission/lifecycle controls."""
from copy import deepcopy
from dataclasses import replace
import os
from threading import Event, Lock, current_thread, main_thread
import time

import numpy as np
import pytest

from Main_App.processing import recording_condition_outcomes as outcomes
from Main_App.workers import cell_validation_pool as pool
from Main_App.workers.review_resource_budget import ReviewMemorySnapshot
from tests.processing.test_recording_condition_outcomes import _expected, _written_receipt

GIB = 1024**3
MIB = 1024**2


def _fixture(tmp_path):
    plans, receipts = [], []
    for index in range(4):
        path = tmp_path / f"cell{index}.fpvs"
        plan = _expected(path)
        condition = f"Condition{index}"
        recording = plan.recordings[0]
        recording = replace(recording, cells=(replace(recording.cells[0], condition_label=condition,
                                                     condition_code=index + 1),))
        plan = replace(plan, recordings=(recording,))
        receipt = _written_receipt(path, plan, with_companion=True)
        receipt["condition_label"] = condition
        for proof in receipt["finite_integrity"]:
            proof["condition_label"] = condition
            proof.pop("fingerprint")
            proof["fingerprint"] = outcomes._fingerprint(proof)
        receipt.pop("fingerprint")
        receipt["fingerprint"] = outcomes._fingerprint(receipt)
        plans.append(plan)
        receipts.append(receipt)
    plan = replace(plans[0], recordings=(replace(plans[0].recordings[0],
                   cells=tuple(p.recordings[0].cells[0] for p in plans)),))
    return plan, receipts


def _host(monkeypatch, *, cpu=24, total=128, available=112, commit=112, windows=True):
    monkeypatch.setattr(pool, "_usable_cpus", lambda: cpu)
    snapshot = ReviewMemorySnapshot(total * GIB, available * GIB,
                                    None if commit is None else commit * GIB, windows)
    monkeypatch.setattr(pool, "probe_memory_snapshot", lambda: snapshot)


@pytest.mark.parametrize("workers", [1, 2, 12])
def test_actual_native_payload_and_full_artifact_checks_are_exact(tmp_path, monkeypatch, workers):
    _host(monkeypatch)
    plan, receipts = _fixture(tmp_path)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    serial = outcomes.reconcile_recording_condition_outputs(plan, receipts)
    parallel = outcomes.reconcile_recording_condition_outputs(plan, receipts, validation_workers=workers)
    assert serial.is_pre_review_ready
    assert outcomes._canonical_json(parallel.to_payload()) == outcomes._canonical_json(serial.to_payload())
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("fault", ["missing", "duplicate", "fingerprint", "valid_npz_bit"])
def test_native_failures_and_valid_same_size_mtime_bit_mutation_still_block(tmp_path, monkeypatch, fault):
    _host(monkeypatch)
    plan, receipts = _fixture(tmp_path)
    if fault == "missing":
        receipts.pop(1)
    elif fault == "duplicate":
        receipts.append(deepcopy(receipts[1]))
    elif fault == "fingerprint":
        receipts[1]["retained_occurrence_count"] = 99
    else:
        path = tmp_path / receipts[1]["workbook_write"]["spectral_companion"]["path"]
        before = path.stat()
        with np.load(path, allow_pickle=False) as archive:
            arrays = {name: archive[name] for name in archive.files}
        values = next(value for name, value in arrays.items() if name.endswith("_values"))
        values.view(np.uint64).flat[0] ^= np.uint64(1)
        np.savez(path, **arrays)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert path.stat().st_size == before.st_size
        with np.load(path, allow_pickle=False) as archive:
            assert all(np.array_equal(archive[name], value) for name, value in arrays.items())
    serial = outcomes.reconcile_recording_condition_outputs(plan, receipts)
    parallel = outcomes.reconcile_recording_condition_outputs(plan, receipts, validation_workers=12)
    assert not serial.is_pre_review_ready
    assert outcomes._canonical_json(parallel.to_payload()) == outcomes._canonical_json(serial.to_payload())


def test_unexpected_identity_keeps_native_error_text(tmp_path, monkeypatch):
    _host(monkeypatch)
    plan, receipts = _fixture(tmp_path)
    receipts.append({"recording_id": "other", "condition_label": "other"})
    errors = []
    for workers in (1, 12):
        with pytest.raises(outcomes.RecordingConditionOutcomeError) as error:
            outcomes.reconcile_recording_condition_outputs(plan, receipts, validation_workers=workers)
        errors.append(str(error.value))
    assert errors[0] == errors[1]


def test_default_and_metadata_only_do_not_construct_threads_or_probe_memory(tmp_path, monkeypatch):
    plan, receipts = _fixture(tmp_path)
    monkeypatch.setattr(pool, "ThreadPoolExecutor", lambda **_: pytest.fail("Native serial path must stay serial"))
    monkeypatch.setattr(pool, "probe_memory_snapshot", lambda: pytest.fail("Native serial path must not probe"))
    assert outcomes.reconcile_recording_condition_outputs(plan, receipts).is_pre_review_ready
    assert outcomes.reconcile_recording_condition_outputs(
        plan, receipts, validate_artifacts=False, validation_workers=12,
    ).is_pre_review_ready


def test_credits_include_actual_small_metadata_but_never_load_dense_arrays(tmp_path, monkeypatch):
    plan, _receipts = _fixture(tmp_path)
    monkeypatch.setattr(np, "load", lambda *_a, **_kw: pytest.fail("Budgeting may inspect headers only"))
    credit = pool.cell_validation_credit(plan.recordings[0].cells[0].expected_workbook)
    assert type(credit) is int and 32 * MIB < credit < 34 * MIB
    assert pool.cell_validation_credit(tmp_path / "missing.fpvs") is None
    legacy = tmp_path / "legacy.xlsx"
    legacy.write_bytes(b"Unsupported budget domain; native reader retains authority")
    assert pool.cell_validation_credit(legacy) is None


def test_unbounded_npy_shape_is_not_granted_a_small_credit(tmp_path):
    _plan, receipts = _fixture(tmp_path)
    path = tmp_path / receipts[0]["workbook_write"]["spectral_companion"]["path"]
    import zipfile

    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    # Change a valid NPY metadata header shape while keeping its payload short.
    key = next(name for name in members if name.endswith("_electrodes.npy"))
    data = members[key]
    assert b"(1,)" in data
    members[key] = data.replace(b"(1,)", b"(9,)", 1)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    assert pool.cell_validation_credit(tmp_path / "cell0.fpvs") is None


def test_speculative_metadata_allocation_failure_keeps_native_serial_authority(tmp_path, monkeypatch):
    _host(monkeypatch)
    plan, receipts = _fixture(tmp_path)
    serial = outcomes.reconcile_recording_condition_outputs(plan, receipts)
    monkeypatch.setattr(pool, "_metadata_bytes", lambda *_a, **_kw: (_ for _ in ()).throw(MemoryError("Budget only")))
    assert pool.cell_validation_credit(tmp_path / "cell0.fpvs") is None
    observed = []
    native = outcomes._reconcile_cell

    def validate(**arguments):
        observed.append(current_thread())
        return native(**arguments)

    monkeypatch.setattr(outcomes, "_reconcile_cell", validate)
    actual = outcomes.reconcile_recording_condition_outputs(plan, receipts, validation_workers=12)
    assert actual == serial and set(observed) == {main_thread()}


@pytest.mark.parametrize("cpu,requested,expected", [
    (1, 12, 1), (2, 12, 1), (24, 12, 12), (24, 2, 2), (24, 23, 23),
])
def test_cpu_affinity_and_project_ceiling_bound_population(monkeypatch, cpu, requested, expected):
    _host(monkeypatch, cpu=cpu)
    native = pool.ThreadPoolExecutor
    populations = []

    def executor(**arguments):
        populations.append(arguments["max_workers"])
        return native(**arguments)

    monkeypatch.setattr(pool, "ThreadPoolExecutor", executor)
    assert pool.ordered_cell_validation(list(range(32)), lambda item: item, lambda _item: 32 * MIB,
                                        max_workers=requested) == list(range(32))
    assert populations == ([] if expected == 1 else [expected])


@pytest.mark.parametrize("total", [16, 32])
def test_small_ram_hosts_use_live_validation_headroom_instead_of_tier(monkeypatch, total):
    _host(monkeypatch, total=total, available=12, commit=12)
    native = pool.ThreadPoolExecutor
    populations = []

    def executor(**arguments):
        populations.append(arguments["max_workers"])
        return native(**arguments)

    monkeypatch.setattr(pool, "ThreadPoolExecutor", executor)
    assert pool.ordered_cell_validation(list(range(12)), lambda item: item, lambda _item: 32 * MIB,
                                        max_workers=12) == list(range(12))
    assert populations == [12]


@pytest.mark.parametrize("failure", ["commit_missing", "commit_pressure", "physical_pressure", "probe_failure"])
def test_unavailable_parallel_headroom_uses_native_serial_without_wait(monkeypatch, failure):
    _host(monkeypatch, available=0 if failure == "physical_pressure" else 112,
          commit=None if failure == "commit_missing" else 0 if failure == "commit_pressure" else 112)
    if failure == "probe_failure":
        monkeypatch.setattr(pool, "probe_memory_snapshot", lambda: (_ for _ in ()).throw(OSError("Unavailable")))
    threads = []
    result = pool.ordered_cell_validation(list(range(4)),
        lambda item: (threads.append(current_thread()), item)[1], lambda _item: 32 * MIB, max_workers=12)
    assert result == list(range(4)) and set(threads) == {main_thread()}


def test_background_decline_drains_before_serial_and_recovery_readmission(monkeypatch):
    _host(monkeypatch)
    release = Event()
    closed, entered = set(), []
    lock = Lock()
    probes = 0

    def snapshot():
        nonlocal probes
        probes += 1
        if probes >= 4 and len(closed) < 2:
            release.set()
            available = GIB  # Host margin8GiB means no new parallel credits.
        else:
            available = 112 * GIB
        return ReviewMemorySnapshot(128 * GIB, available, available, True)

    monkeypatch.setattr(pool, "probe_memory_snapshot", snapshot)

    def validate(item):
        with lock:
            entered.append((item, set(closed)))
        if item < 2:
            assert release.wait(5)
            time.sleep(0.005 * item)
        with lock:
            closed.add(item)
        return item

    assert pool.ordered_cell_validation(list(range(4)), validate, lambda _item: 32 * MIB,
                                        max_workers=12) == list(range(4))
    assert next(previous for item, previous in entered if item == 2) >= {0, 1}


def test_unknown_cell_runs_alone_after_current_readers_close(monkeypatch):
    _host(monkeypatch)
    closed, observed = set(), []

    def validate(item):
        if item < 2:
            time.sleep(0.01)
        observed.append((item, current_thread(), set(closed)))
        closed.add(item)
        return item

    assert pool.ordered_cell_validation(list(range(4)), validate,
                                        lambda item: None if item == 2 else 32 * MIB,
                                        max_workers=12) == list(range(4))
    _, thread, previous = next(row for row in observed if row[0] == 2)
    assert thread is main_thread() and previous >= {0, 1}


def test_first_native_order_failure_wins_and_all_read_owners_close(monkeypatch):
    _host(monkeypatch)
    later_failed = Event()
    closed = set()

    def validate(item):
        try:
            if item == 1:
                assert later_failed.wait(5)
                raise RuntimeError("canonical first failure")
            if item == 3:
                later_failed.set()
                raise RuntimeError("later failure")
            return item
        finally:
            closed.add(item)

    with pytest.raises(RuntimeError, match="^canonical first failure$"):
        pool.ordered_cell_validation(list(range(4)), validate, lambda _item: 32 * MIB, max_workers=12)
    assert closed == {0, 1, 2, 3}


def test_contexts_do_not_inherit_parent_mutable_validation_caches(tmp_path, monkeypatch):
    from Main_App.io import spectral_data
    from Main_App.processing import post_processing_context

    _host(monkeypatch)
    _plan, _receipts = _fixture(tmp_path)
    xlsx = spectral_data._xlsx._ACTIVE_XLSX_READ_CACHE
    post = post_processing_context._ACTIVE_READS
    tokens = xlsx.set(object()), post.set(object())
    try:
        parent = xlsx.get(), post.get()

        def validate(item):
            assert xlsx.get() is None and post.get() is None
            return item

        assert pool.ordered_cell_validation(list(range(4)), validate, lambda _item: 32 * MIB,
                                            max_workers=12) == list(range(4))
        assert (xlsx.get(), post.get()) == parent
    finally:
        xlsx.reset(tokens[0])
        post.reset(tokens[1])
