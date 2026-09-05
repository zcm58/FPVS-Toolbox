"""Exact numeric parity for bounded condition-window metric batching."""

from __future__ import annotations

from dataclasses import replace
import json
import warnings

import numpy as np
import pytest

from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
import Main_App.processing.raw_channel_qc as qc


def _baseline_rows(data, channel_names):
    """The independent, unbatched formulas from baseline ffebf3ab."""

    rows = []
    for row_index, channel in enumerate(channel_names):
        values = np.asarray(data[row_index], dtype=np.float64)
        percentiles = np.nanpercentile(values, [0.05, 0.5, 99.5, 99.95])
        rows.append(
            qc.RawChannelMetricSet(
                channel=str(channel),
                std_uv=float(np.nanstd(values) * 1e6),
                p2p_99_uv=float((percentiles[2] - percentiles[1]) * 1e6),
                p2p_999_uv=float((percentiles[3] - percentiles[0]) * 1e6),
                full_p2p_uv=float(
                    (np.nanmax(values) - np.nanmin(values)) * 1e6
                ),
            )
        )
    return tuple(rows)


def _metric_bits(rows):
    return np.asarray(
        [
            (row.std_uv, row.p2p_99_uv, row.p2p_999_uv, row.full_p2p_uv)
            for row in rows
        ],
        dtype=np.float64,
    ).view(np.uint64)


def _samples(kind, n_samples):
    rng = np.random.default_rng(88)
    backing = rng.normal(0.0, 1e-5, (8, n_samples * 2 + 5))
    data = backing[:, 3 : n_samples + 3]
    if kind == "contiguous":
        return data.copy()
    if kind == "sliced_window":
        return data
    if kind == "stepped":
        return backing[:, 3 : n_samples * 2 + 3 : 2]
    if kind == "reversed":
        return data[:, ::-1]
    if kind == "fortran":
        return np.asfortranarray(data)
    if kind == "constant":
        return np.full_like(data, 1e-5)
    if kind == "signed_zero":
        return rng.choice([0.0, -0.0], size=data.shape)
    if kind == "mixed_zero":
        return rng.choice([-1e-5, -0.0, 0.0, 1e-5], size=data.shape)
    if kind == "extreme":
        return data * 1e160
    if kind == "overflow":
        return rng.choice(
            [-np.finfo(np.float64).max, np.finfo(np.float64).max],
            size=data.shape,
        )
    if kind == "subnormal":
        return data * 1e-305
    if kind == "nonfinite":
        data = data.copy()
        data[0] = np.nan
        data[1, 0] = np.inf
        data[2, -1] = -np.inf
        data[3, ::2] = np.nan
        return data
    if kind == "float32":
        return data.astype(np.float32)
    if kind == "integer":
        return rng.integers(-100, 100, size=data.shape)
    raise AssertionError(kind)


@pytest.mark.parametrize("n_samples", [1, 257, 10_240])
@pytest.mark.parametrize(
    "kind",
    [
        "contiguous", "sliced_window", "stepped", "reversed", "fortran",
        "constant", "signed_zero", "mixed_zero", "extreme", "overflow",
        "subnormal", "nonfinite", "float32", "integer",
    ],
)
def test_metric_rows_are_bitwise_identical_to_baseline(kind, n_samples):
    data = _samples(kind, n_samples)
    before = data.tobytes()
    channels = BIOSEMI64_CHANNELS[: len(data)]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        expected = _baseline_rows(data, channels)
        actual = qc._v2_metric_rows(data, channels)
    assert tuple(row.channel for row in actual) == channels
    np.testing.assert_array_equal(_metric_bits(actual), _metric_bits(expected))
    assert data.tobytes() == before


def test_typical_64_channel_window_uses_batch_without_row_calls(monkeypatch):
    data = np.random.default_rng(88).normal(0.0, 1e-5, (64, 20_480))[
        :, 4_096:14_336
    ]
    expected = _baseline_rows(data, BIOSEMI64_CHANNELS)

    def unexpected_row(*_args):
        raise AssertionError("ordinary finite window should use the batch")

    monkeypatch.setattr(qc, "_v2_channel_metrics", unexpected_row)
    actual = qc._v2_metric_rows(data, BIOSEMI64_CHANNELS)
    np.testing.assert_array_equal(_metric_bits(actual), _metric_bits(expected))


@pytest.mark.parametrize(
    "kind", ["fortran", "stepped", "reversed", "nonfinite", "float32", "integer"]
)
def test_unsupported_inputs_retain_original_row_reductions(monkeypatch, kind):
    data = _samples(kind, 257)
    channels = BIOSEMI64_CHANNELS[: len(data)]
    visited = []
    original = qc._v2_channel_metrics

    def tracked(channel, values):
        visited.append(channel)
        return original(channel, values)

    monkeypatch.setattr(qc, "_v2_channel_metrics", tracked)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        actual = qc._v2_metric_rows(data, channels)
        expected = _baseline_rows(data, channels)
    assert visited == list(channels)
    np.testing.assert_array_equal(_metric_bits(actual), _metric_bits(expected))


def test_large_aggregate_keeps_row_bounded_scratch(monkeypatch):
    data = np.random.default_rng(88).normal(0.0, 1e-5, (64, 16_385))
    expected = _baseline_rows(data, BIOSEMI64_CHANNELS)
    original = qc._v2_channel_metrics
    visited = []

    def tracked(channel, values):
        visited.append(channel)
        return original(channel, values)

    monkeypatch.setattr(qc, "_v2_channel_metrics", tracked)
    actual = qc._v2_metric_rows(data, BIOSEMI64_CHANNELS)
    assert visited == list(BIOSEMI64_CHANNELS)
    np.testing.assert_array_equal(_metric_bits(actual), _metric_bits(expected))


@pytest.mark.parametrize("metric", ["std_uv", "p2p_99_uv"])
@pytest.mark.parametrize("direction", [-1, 0, 1])
def test_baseline_warning_at_adjacent_float_thresholds(metric, direction):
    signal = np.random.default_rng(99).normal(0.0, 1e-5, 1_024)
    data = np.tile(signal, (8, 1))
    channels = BIOSEMI64_CHANNELS[: len(data)]
    expected_rows = _baseline_rows(data, channels)
    boundary = getattr(expected_rows[0], metric)
    threshold = (
        boundary if direction == 0
        else float(np.nextafter(boundary, -np.inf if direction < 0 else np.inf))
    )
    thresholds = {
        "baseline_warning_median_std_uv": np.inf,
        "baseline_warning_median_p2p_99_uv": np.inf,
        "baseline_exclusion_median_std_uv": np.inf,
        "baseline_exclusion_median_p2p_99_uv": np.inf,
    }
    thresholds[f"baseline_warning_median_{metric}"] = threshold
    config = replace(
        qc.RawChannelQCConfig(),
        auto_detect_removed_electrodes=False,
        **thresholds,
    )
    expected = qc._classify_v2_metrics(expected_rows, config)
    actual = qc._classify_v2_metrics(qc._v2_metric_rows(data, channels), config)
    assert actual == expected
    assert actual.baseline_warning is (direction <= 0)


@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("detector_enabled", [False, True])
def test_condition_metrics_flags_and_sample_evidence_match_baseline(
    monkeypatch, overlap, detector_enabled,
):
    n_samples = 23_001 if overlap else 20_497
    data = np.random.default_rng(251).normal(0.0, 500e-6, (64, n_samples))
    data[0] *= 0.001
    data[1, 10_200:10_260] = 0.03
    data[2, -1] = -0.03
    starts = (0, 5_120, 10_240, 12_761) if overlap else (0, 10_240, 20_480)
    blocks = [
        qc.ConditionRawChannelQCBlock(
            condition_id="faces",
            occurrence=2,
            start_sample=4_099 + start,
            stop_sample=4_099 + min(start + 10_240, n_samples),
            data=data[:, start : start + 10_240],
            is_final=index == len(starts) - 1,
            window_kind=(
                "tail_aligned" if overlap and index == len(starts) - 1 else "regular"
            ),
        )
        for index, start in enumerate(starts)
    ]
    config = replace(
        qc.RawChannelQCConfig(),
        auto_detect_removed_electrodes=detector_enabled,
        spatial_qc_enabled=False,
    )
    monkeypatch.setattr(qc, "_config_from_settings", lambda _settings: config)

    def evaluate():
        return qc.evaluate_condition_raw_channel_qc_v2(
            blocks, BIOSEMI64_CHANNELS, {}, filename="metric-parity.bdf",
            sfreq=2_048.0, block_duration_s=5.0,
            window_hop_s=2.5 if overlap else 5.0,
        )

    actual = evaluate()
    monkeypatch.setattr(qc, "_v2_metric_rows", _baseline_rows)
    expected = evaluate()
    assert actual.n_samples == n_samples
    assert actual.n_blocks == len(starts)
    assert json.dumps(actual.to_payload(), sort_keys=True) == json.dumps(
        expected.to_payload(), sort_keys=True
    )
