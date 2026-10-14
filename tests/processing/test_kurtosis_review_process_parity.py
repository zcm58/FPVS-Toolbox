"""Real spawned review jobs preserve the shared numerical/QC boundary, without Qt."""

from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from dataclasses import asdict
import hashlib
from multiprocessing import get_context
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from threadpoolctl import threadpool_info, threadpool_limits

from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
from Main_App.processing import prepared_fir as fir
from Main_App.processing import prepared_kurtosis_cache as checkpoints
from Main_App.processing.prepared_raw_codec import encode_state, raw_state
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.preprocess import (
    _build_preproc_fingerprint,
    prepare_kurtosis_review_evidence,
)
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol
from Main_App.workers import process_runner
from tests.processing.test_preprocess_kurtosis_gate import _params, _raw
from tests.processing.test_shared_load_utils import _write_sampling_bdf


_START_BARRIER = None


def _initialize_review_probe(cancel_event, progress_queue, barrier=None):
    from Main_App.workers.kurtosis_review_process import _review_worker_init

    global _START_BARRIER
    _START_BARRIER = barrier
    _review_worker_init(cancel_event, progress_queue)


def _exact_payload(value):
    arrays = {}
    encoded = encode_state(value, arrays)
    return encoded, {
        name: (array.dtype.str, array.shape, array.strides, array.tobytes())
        for name, array in arrays.items()
    }


def _prepared_source():
    raw = _raw()
    raw._data[-1, 0] = 1.0
    raw._data[-1, 100:601:50] = 55.0
    return raw


def _prepare_shared_probe(source, project_root):
    """Compare the public preparation with an empty and then populated cache."""
    params = _params(Path(source))
    params.update(
        high_pass=1.0, low_pass=30.0, downsample_rate=80.0,
        project_root=project_root, enable_kurtosis_checkpoint_cache=False,
    )
    baseline_source = _prepared_source()
    before = _exact_payload({"state": raw_state(baseline_source), "samples": baseline_source._data})
    baseline_logs = []
    baseline = prepare_kurtosis_review_evidence(
        baseline_source, params, baseline_logs.append, Path(source).name,
    )
    assert before == _exact_payload({"state": raw_state(baseline_source), "samples": baseline_source._data})
    cache = process_runner._WORKER_FIR_CACHE
    variants = []
    for _ in range(2):
        logs = []
        with fir.prepared_fir_scope(cache):
            actual = prepare_kurtosis_review_evidence(_prepared_source(), params, logs.append, Path(source).name)
        variants.append((_exact_payload(actual), logs))
    # Checkpoints hold the exact pre-interpolation state and never approve QC.
    checkpoint_params = {**params, "enable_kurtosis_checkpoint_cache": True}
    checkpoint_source = _prepared_source()
    identity = checkpoints.checkpoint_identity(
        checkpoint_source, checkpoint_params, _build_preproc_fingerprint(checkpoint_params),
    )
    assert identity is not None
    with fir.prepared_fir_scope(cache):
        prepared = prepare_kurtosis_review_evidence(checkpoint_source, checkpoint_params, lambda *_: None)
    saved = checkpoints.load_checkpoint(identity)
    assert saved is not None
    saved_state = _exact_payload({"state": raw_state(saved.raw), "samples": saved.raw._data})
    saved.raw.close()
    with fir.prepared_fir_scope(cache):
        reused = prepare_kurtosis_review_evidence(_prepared_source(), checkpoint_params, lambda *_: None)
    saved_again = checkpoints.load_checkpoint(identity)
    assert saved_again is not None
    assert saved_state == _exact_payload({"state": raw_state(saved_again.raw), "samples": saved_again.raw._data})
    assert not saved_again.raw.info["projs"]
    assert not any("decision" in key or "approved" in key for key in saved_again.params)
    assert prepared["decision_plan"]["ready_for_interpolation"] is False
    assert prepared == reused
    saved_again.raw.close()
    baseline_source.close()
    return {
        "baseline": (_exact_payload(baseline), baseline_logs), "variants": variants,
        "hits": cache.hits, "misses": cache.misses, "bytes": cache.retained_bytes,
        "adapter": cache.adapter_available, "pools": threadpool_info(),
        "scope_reset": fir.current_prepared_fir_cache() is None,
    }


def _run_review_probe(info, settings, event_map, plans):
    from Main_App.workers.kurtosis_review_process import _run_one_review

    if _START_BARRIER is not None:
        _START_BARRIER.wait(timeout=30)
    result = _run_one_review(info, settings, event_map, plans, None)
    cache = process_runner._WORKER_FIR_CACHE
    return {
        "result": result,
        "exact": _exact_payload(asdict(result)),
        "pid": os.getpid(), "hits": cache.hits, "misses": cache.misses,
        "scope_reset": fir.current_prepared_fir_cache() is None,
        "pools": threadpool_info(),
    }


def _prepare_native_policy_probe(source, native_threads):
    """Measure policy drift without treating cross-policy bit equality as a contract."""
    params = _params(Path(source))
    params.update(high_pass=1.0, low_pass=30.0, downsample_rate=80.0,
                  enable_kurtosis_checkpoint_cache=False)
    raw = _prepared_source()
    try:
        with threadpool_limits(limits=native_threads), fir.prepared_fir_scope(None):
            prepared = prepare_kurtosis_review_evidence(raw, params, lambda *_: None, copy_raw=False)
            samples = raw._data.copy()
            policy = threadpool_info()
        return {
            "samples": samples, "prepared": _exact_payload(prepared), "pools": policy,
            "channels": tuple(raw.ch_names), "sfreq": float(raw.info["sfreq"]),
            "first_samp": int(raw.first_samp),
        }
    finally:
        raw.close()


def _small_bdf(path):
    labels = ("EXG1", "EXG2", *BIOSEMI64_CHANNELS, "Status")
    sample_count = 1000
    header_bytes = _write_sampling_bdf(path, labels=labels, samples=(sample_count,) * len(labels), duration="10")
    values = np.random.default_rng(77191).normal(scale=1.0, size=(len(labels), sample_count))
    values[2] *= .02
    values[2, ::50] = 500.0
    values[-1] = 0.0
    events = np.asarray([[1, 0, 1], *[[100 + index * 50, 0, 55] for index in range(11)]], dtype=int)
    values[-1, events[:, 0]] = events[:, 2]
    digital = np.rint(values * 32).astype(np.int64)
    # MNE reads status as digital values; EEG uses the fixture's 1/32 uV scale.
    digital[-1] = values[-1].astype(np.int64)
    packed = np.stack([(digital >> shift) & 255 for shift in (0, 8, 16)], axis=-1).astype(np.uint8)
    with path.open("r+b") as stream:
        stream.seek(header_bytes)
        stream.write(packed.tobytes())
    return events


def test_spawned_shared_preparation_cache_and_checkpoint_are_exact(tmp_path, monkeypatch):
    source = tmp_path / "P001.bdf"
    source.write_bytes(b"Immutable synthetic RawArray source identity")
    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    parent_pools = threadpool_info()
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    context = get_context("spawn")
    queue = context.Queue()
    try:
        with ProcessPoolExecutor(
            max_workers=1, mp_context=context, initializer=_initialize_review_probe,
            initargs=(context.Event(), queue),
        ) as pool:
            outcome = pool.submit(_prepare_shared_probe, str(source), str(tmp_path)).result(timeout=60)
    finally:
        queue.close()
        queue.join_thread()
    assert all(variant == outcome["baseline"] for variant in outcome["variants"])
    assert outcome["scope_reset"]
    assert all(item["num_threads"] == 1 for item in outcome["pools"])
    if fir._supported_runtime():
        assert outcome["adapter"]
        assert outcome["misses"] == 1 and outcome["hits"] >= 2
        assert 0 < outcome["bytes"] <= 4 * 1024 * 1024
    assert threadpool_info() == parent_pools
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_digest


def test_actual_bdf_review_serial_and_concurrent_processes_preserve_full_evidence(tmp_path, monkeypatch):
    protocol = FrequencyProtocol.from_recurrence(
        10, 5, expected_analyzed_oddball_cycles=10,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    infos, plans, hashes = [], {}, {}
    for index in (1, 2):
        path = tmp_path / f"P00{index}.bdf"
        events = _small_bdf(path)
        participant = f"P00{index}"
        infos.append(SimpleNamespace(
            path=path, subject_id=participant, recording_id=f"{participant}_session-1",
            session_id="session-1", session_label="Visit 1", visit_index=1,
        ))
        plans[str(path)] = plan_preflight_qc_events(
            events=events, event_map={"Condition": 1}, sfreq=100.0, n_times=1000,
            first_samp=0, frequency_protocol=protocol,
        ).to_payload()
        hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    settings = deepcopy(_params(infos[0].path))
    settings.update(
        frequency_protocol=protocol, high_pass=1.0, low_pass=30.0, downsample_rate=80.0,
        enable_kurtosis_checkpoint_cache=False, removed_electrode_detection_mode="off",
    )
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    parent_pools = threadpool_info()
    context = get_context("spawn")
    queue = context.Queue()
    try:
        with ProcessPoolExecutor(
            max_workers=1, mp_context=context, initializer=_initialize_review_probe,
            initargs=(context.Event(), queue),
        ) as pool:
            serial = [pool.submit(_run_review_probe, info, settings, {"Condition": 1}, plans).result(timeout=60)
                      for info in infos]
        with ProcessPoolExecutor(
            max_workers=2, mp_context=context, initializer=_initialize_review_probe,
            initargs=(context.Event(), queue, context.Barrier(2)),
        ) as pool:
            futures = [pool.submit(_run_review_probe, info, settings, {"Condition": 1}, plans) for info in infos]
            concurrent = [future.result(timeout=60) for future in futures]
    finally:
        queue.close()
        queue.join_thread()
    assert len({item["pid"] for item in serial}) == 1
    assert len({item["pid"] for item in concurrent}) == 2
    assert [item["exact"] for item in serial] == [item["exact"] for item in concurrent]
    for item in serial + concurrent:
        assert not item["result"].errors
        assert item["result"].results
        assert item["result"].results[0].evidence["fingerprint"]
        assert item["scope_reset"]
        assert all(native["num_threads"] == 1 for native in item["pools"])
    if fir._supported_runtime():
        assert serial[0]["misses"] == 1 and serial[0]["hits"] == 0
        assert serial[1]["misses"] == 1 and serial[1]["hits"] == 1
    assert threadpool_info() == parent_pools
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in hashes} == hashes


def test_native_policy_characterization_preserves_grid_and_bounds_numeric_drift(tmp_path, record_testsuite_property):
    source = tmp_path / "P001.bdf"
    source.write_bytes(b"Native-policy characterization source")
    parent_pools = threadpool_info()
    context = get_context("spawn")
    queue = context.Queue()
    try:
        with ProcessPoolExecutor(
            max_workers=1, mp_context=context, initializer=_initialize_review_probe,
            initargs=(context.Event(), queue),
        ) as pool:
            worker = pool.submit(_prepare_native_policy_probe, str(source), 1).result(timeout=60)
            parent_policy = pool.submit(_prepare_native_policy_probe, str(source), 24).result(timeout=60)
    finally:
        queue.close()
        queue.join_thread()
    assert worker["channels"] == parent_policy["channels"]
    assert worker["sfreq"] == parent_policy["sfreq"] == 80.0
    assert worker["first_samp"] == parent_policy["first_samp"]
    assert worker["samples"].shape == parent_policy["samples"].shape
    assert worker["samples"].dtype == parent_policy["samples"].dtype == np.float64
    difference = np.abs(worker["samples"] - parent_policy["samples"])
    maximum = float(difference.max())
    scale = float(np.abs(worker["samples"][:-1]).max())
    assert np.isfinite(difference).all()
    assert maximum <= max(1e-20, scale * 1e-12)
    record_testsuite_property("native_threads_compared", "1 versus 24")
    record_testsuite_property("maximum_sample_difference_volts", maximum)
    record_testsuite_property("changed_sample_count", int(np.count_nonzero(difference)))
    record_testsuite_property("full_evidence_bits_equal", worker["prepared"] == parent_policy["prepared"])
    assert all(native["num_threads"] == 1 for native in worker["pools"])
    assert all(native["num_threads"] == 24 for native in parent_policy["pools"])
    assert threadpool_info() == parent_pools
