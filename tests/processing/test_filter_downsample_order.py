from __future__ import annotations

import numpy as np
import pytest

mne = pytest.importorskip("mne")

from Main_App.processing.preprocess import (  # noqa: E402
    PREPROCESSING_ORDER_VERSION,
    _build_preproc_fingerprint,
    perform_preprocessing,
)


def _comparison_raw() -> mne.io.RawArray:
    sfreq = 512.0
    samples = int(sfreq * 40)
    rng = np.random.RandomState(20260526)
    t = np.arange(samples) / sfreq
    ch_names = ["EXG1", "EXG2", "E1", "E2", "E3", "E4", "Status"]
    ch_types = ["eeg", "eeg", "eeg", "eeg", "eeg", "eeg", "stim"]
    data = np.zeros((len(ch_names), samples), dtype=float)
    data[0] = 0.03 * np.sin(2 * np.pi * 0.7 * t) + 0.004 * rng.randn(samples)
    data[1] = -0.02 * np.sin(2 * np.pi * 0.5 * t) + 0.004 * rng.randn(samples)
    for idx, freq in enumerate([1.2, 6.0, 12.0, 48.0], start=2):
        data[idx] = 1e-6 * (
            np.sin(2 * np.pi * freq * t)
            + 0.2 * np.sin(2 * np.pi * 70 * t)
            + 0.05 * rng.randn(samples)
        )
    data[-1, [512, 2048, 4096, 8192, 12288, 16384]] = [21, 22, 21, 22, 21, 22]
    info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types=ch_types)
    return mne.io.RawArray(data, info, verbose=False)


def _params() -> dict[str, object]:
    return {
        "downsample": 256,
        "downsample_rate": 256,
        "low_pass": 50.0,
        "high_pass": 0.1,
        "reject_thresh": None,
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "max_idx_keep": 4,
        "stim_channel": "Status",
    }


def _legacy_downsample_then_filter(raw: mne.io.BaseRaw) -> mne.io.BaseRaw:
    raw = raw.copy()
    raw.set_eeg_reference(ref_channels=["EXG1", "EXG2"], projection=False, verbose=False)
    raw.drop_channels(["EXG1", "EXG2"])
    raw.pick_channels(["E1", "E2", "E3", "E4", "Status"], ordered=False)
    raw.resample(256, npad="auto", window="hann", verbose=False)
    raw.filter(
        0.1,
        50.0,
        method="fir",
        phase="zero-double",
        fir_window="hamming",
        fir_design="firwin",
        l_trans_bandwidth=0.1,
        h_trans_bandwidth=0.1,
        filter_length=8449,
        skip_by_annotation="edge",
        verbose=False,
    )
    raw.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    raw.apply_proj(verbose=False)
    return raw


def test_filter_runs_before_downsample_and_only_changes_numerics() -> None:
    raw = _comparison_raw()
    logs: list[str] = []

    processed, rejected = perform_preprocessing(
        raw.copy(),
        _params(),
        logs.append,
        "order_compare.bdf",
    )
    assert processed is not None
    assert rejected == 0

    filter_idx = next(i for i, msg in enumerate(logs) if msg.startswith("FILTER_SNAPSHOT"))
    downsample_idx = next(i for i, msg in enumerate(logs) if msg.startswith("Downsample check"))
    assert filter_idx < downsample_idx
    assert "sfreq=512.0" in logs[filter_idx]
    assert "filter_length=16897" in logs[filter_idx]
    assert any(msg == "Filter OK for order_compare.bdf." for msg in logs)

    old_order = _legacy_downsample_then_filter(raw)
    new_data = processed.get_data()
    old_data = old_order.get_data()

    assert processed.ch_names == old_order.ch_names
    assert processed.info["sfreq"] == old_order.info["sfreq"] == 256
    assert new_data.shape == old_data.shape

    diff = new_data - old_data
    assert np.linalg.norm(diff) > 1e-8
    assert not np.allclose(new_data, old_data, rtol=1e-7, atol=1e-10)


def test_filter_then_downsample_order_is_fingerprint_guarded() -> None:
    assert PREPROCESSING_ORDER_VERSION == "filter_then_downsample_v1"

    fingerprint = _build_preproc_fingerprint(_params())

    assert fingerprint.startswith("order=filter_then_downsample_v1|")
