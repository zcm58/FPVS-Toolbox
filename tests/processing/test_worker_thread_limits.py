"""Exercise the production initializer in real spawned workers, without Qt."""

from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
import importlib.util
import os
from queue import Queue

import mne
import numpy as np
from scipy.stats import kurtosis
from threadpoolctl import threadpool_info

from Main_App.workers.process_runner import _worker_init
from Main_App.workers import process_runner
from Main_App.processing.fft_multinotch import apply_fft_multinotch


if importlib.util.find_spec("numexpr") is not None:
    import numexpr
else:
    numexpr = None

# This import-time snapshot precedes ProcessPoolExecutor's initializer.
POOLS_BEFORE_INIT = threadpool_info()


def _initialize_worker_with_loaded_libraries():
    # Importing this initializer's module loads the probe's optional libraries
    # before the production initializer applies the process-local limit.
    _worker_init()


def _fail_worker_init():
    raise RuntimeError("injected worker initialization failure")


def _scientific_probe():
    data = np.random.default_rng(812).normal(size=(4, 8192)) * 1e-6
    raw = mne.io.RawArray(data, mne.create_info(["Fz", "Cz", "Pz", "Oz"], 512, "eeg"), verbose=False)
    raw.filter(1.0, 100.0, filter_length="auto", phase="zero-double", n_jobs=1, verbose=False)
    apply_fft_multinotch(raw, fundamental_hz=60.0, low_pass=100.0, stim_channel=None)
    raw.resample(256, n_jobs=1, verbose=False)
    values = raw.get_data()
    values -= values.mean(axis=0)
    spectrum = np.abs(np.fft.rfft(values, axis=-1))
    metrics = kurtosis(values, axis=-1, fisher=True, bias=True)
    arrays = [values, spectrum, metrics]
    return {
        "pid": os.getpid(),
        "before": POOLS_BEFORE_INIT,
        "after": threadpool_info(),
        "numexpr_threads": None if numexpr is None else numexpr.get_num_threads(),
        "scientific": [(array.dtype.str, array.shape, array.tobytes()) for array in arrays],
    }


def test_spawned_worker_limits_existing_pools_and_preserves_scientific_results(monkeypatch):
    parent_pools = threadpool_info()
    for variable in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        monkeypatch.setenv(variable, "8")
    context = get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
        baseline = pool.submit(_scientific_probe).result(timeout=60)
    with ProcessPoolExecutor(max_workers=1, mp_context=context, initializer=_initialize_worker_with_loaded_libraries) as pool:
        limited = pool.submit(_scientific_probe).result(timeout=60)
        repeated = pool.submit(_scientific_probe).result(timeout=60)
    assert limited["pid"] != os.getpid()
    assert repeated["pid"] == limited["pid"]
    assert limited["before"]
    assert any(pool["num_threads"] > 1 for pool in limited["before"])
    assert all(pool["num_threads"] == 1 for pool in limited["after"])
    assert all(pool["num_threads"] == 1 for pool in repeated["after"])
    assert limited["numexpr_threads"] in (None, 1)
    assert limited["scientific"] == repeated["scientific"] == baseline["scientific"]
    assert threadpool_info() == parent_pools


def test_spawned_initializer_failure_finishes_the_controller(monkeypatch, tmp_path):
    monkeypatch.setattr(process_runner, "_worker_init", _fail_worker_init)
    params = process_runner.RunParams(
        tmp_path, [tmp_path / f"p{i}.bdf" for i in range(3)], {}, {}, tmp_path,
        max_workers=1, memory_soft_limit_ratio=None,
    )
    queue = Queue()
    terminal = process_runner.run_project_parallel(params, queue)
    assert [item for item in queue.queue if item["type"] == "done"] == [terminal]
    assert terminal["status"] == "error"
    assert terminal["results"] == []
    assert "BrokenProcessPool" in terminal["controller_error"]
    assert {result["file"] for result in terminal["errors"]} == {str(path) for path in params.data_files}
