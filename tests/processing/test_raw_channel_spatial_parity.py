"""Bitwise spatial-QC parity against the pre-step-1 optimization formulas."""

from __future__ import annotations

from dataclasses import replace
import warnings

import numpy as np
import pytest

from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
import Main_App.processing.raw_channel_qc as qc


def _baseline_zscore_rows(data):
    """Frozen implementation from ed089e9d; do not simplify these reductions."""

    centered = data - np.nanmedian(data, axis=1, keepdims=True)
    scale = np.nanstd(centered, axis=1)
    safe_scale = np.where(scale > 0.0, scale, np.nan)
    return centered / safe_scale[:, None], scale


def _baseline_spatial_scores(
    data, channels, *, neighbor_map, donor_exclusions, config,
):
    """Preserve donor order, finite-index copies and native BLAS operations."""

    if not neighbor_map:
        return {}
    channel_lookup = {channel: index for index, channel in enumerate(channels)}
    excluded = {str(channel) for channel in donor_exclusions}
    z_data, row_scale = _baseline_zscore_rows(data)
    scores = {}
    for channel in channels:
        row_index = channel_lookup[channel]
        if not np.isfinite(row_scale[row_index]) or row_scale[row_index] <= 0.0:
            continue
        neighbor_indices = [
            channel_lookup[neighbor]
            for neighbor in neighbor_map.get(channel, ())
            if neighbor not in excluded
            and neighbor in channel_lookup
            and np.isfinite(row_scale[channel_lookup[neighbor]])
            and row_scale[channel_lookup[neighbor]] > 0.0
        ]
        if len(neighbor_indices) < config.spatial_min_neighbors:
            continue
        prediction = np.nanmean(z_data[neighbor_indices], axis=0)
        observed = z_data[row_index]
        finite = np.isfinite(observed) & np.isfinite(prediction)
        if int(np.sum(finite)) < config.spatial_min_neighbors:
            continue
        obs = observed[finite]
        pred = prediction[finite]
        denom = float(np.linalg.norm(obs) * np.linalg.norm(pred))
        if denom <= 0.0 or not np.isfinite(denom):
            continue
        scores[channel] = float(abs(np.dot(obs, pred) / denom))
    return scores


def _bits_tree(value):
    if isinstance(value, float):
        return np.float64(value).tobytes()
    if isinstance(value, dict):
        # Keep key order as well as list/tuple order and every float bit.
        return tuple((key, _bits_tree(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(_bits_tree(item) for item in value)
    return value


def _data(kind, n_samples):
    rng = np.random.default_rng(9182)
    base = rng.normal(0.0, 20e-6, (12, n_samples))
    if kind == "contiguous":
        return base
    if kind == "gapped":
        return np.tile(base, (1, 2))[:, :n_samples]
    if kind == "fortran":
        return np.asfortranarray(base)
    if kind == "reversed":
        return base[:, ::-1]
    if kind == "stepped":
        return np.repeat(base, 2, axis=1)[:, ::2]
    if kind == "signed_zero":
        return rng.choice([-0.0, 0.0], base.shape)
    if kind == "mixed_zero":
        return rng.choice([-1.0, -0.0, 0.0, 1.0], base.shape)
    if kind == "subnormal":
        return base * 1e-305
    if kind == "extreme":
        return base * 1e155
    if kind == "float_max":
        return rng.choice([-np.finfo(float).max, np.finfo(float).max], base.shape)
    if kind == "invalid_rows":
        base[0] = np.nan
        base[1, ::2] = np.nan
        base[2, 0] = np.inf
        base[3, -1] = -np.inf
        base[4] = -0.0
        return base
    if kind == "flat_donor":
        base[0] = 0.0
        return base
    if kind == "float32":
        return base.astype(np.float32)
    raise AssertionError(kind)


@pytest.mark.parametrize("n_samples", [1, 2, 257, 1_201])
@pytest.mark.parametrize(
    "kind",
    [
        "contiguous", "gapped", "fortran", "reversed", "stepped",
        "signed_zero", "mixed_zero", "subnormal", "extreme", "float_max",
        "invalid_rows", "flat_donor", "float32",
    ],
)
def test_spatial_arrays_scales_and_scores_preserve_every_float_bit(kind, n_samples):
    data = _data(kind, n_samples)
    before = data.tobytes()
    data.flags.writeable = False
    channels = BIOSEMI64_CHANNELS[:len(data)]
    # Reversed donor order deliberately detects any new sorting/reduction order.
    neighbors = {
        channel: tuple(name for name in reversed(channels) if name != channel)
        for channel in channels
    }
    kwargs = dict(
        neighbor_map=neighbors,
        donor_exclusions=(channels[2], "not-present"),
        config=qc.RawChannelQCConfig(),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        expected_arrays = _baseline_zscore_rows(data)
        actual_arrays = qc._zscore_rows(data)
        expected_scores = _baseline_spatial_scores(data, channels, **kwargs)
        actual_scores = qc._spatial_predictability_scores_with_neighbors(
            data, channels, **kwargs,
        )
    assert tuple(value.tobytes() for value in actual_arrays) == tuple(
        value.tobytes() for value in expected_arrays
    )
    assert _bits_tree(actual_scores) == _bits_tree(expected_scores)
    assert data.tobytes() == before


@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("manual_removed", [(), ("Fp1", "AF7")])
def test_spatial_enabled_condition_payload_matches_frozen_baseline(
    monkeypatch, overlap, manual_removed,
):
    rng = np.random.default_rng(1122)
    n_samples = 3_003
    shared = rng.normal(0.0, 30e-6, n_samples)
    data = shared + rng.normal(0.0, 3e-6, (64, n_samples))
    data[0] = 0.0
    data[8] = rng.normal(0.0, 30e-6, n_samples)
    data[9, 1_300:1_330] = 0.01
    hop = 640 if overlap else 1_280
    starts = list(range(0, n_samples - 1_280 + 1, hop))
    if overlap:
        starts.append(n_samples - 1_280)
    else:
        starts.append(starts[-1] + hop)
    blocks = tuple(
        qc.ConditionRawChannelQCBlock(
            condition_id="faces",
            occurrence=1,
            start_sample=7_007 + start,
            stop_sample=7_007 + min(start + 1_280, n_samples),
            data=data[:, start:start + 1_280],
            is_final=index == len(starts) - 1,
            window_kind=(
                "tail_aligned" if overlap and index == len(starts) - 1 else "regular"
            ),
        )
        for index, start in enumerate(starts)
    )
    config = replace(
        qc.RawChannelQCConfig(),
        auto_detect_removed_electrodes=True,
        spatial_qc_enabled=True,
        manual_removed_electrodes=manual_removed,
    )
    monkeypatch.setattr(qc, "_config_from_settings", lambda _settings: config)

    def evaluate():
        return qc.evaluate_condition_raw_channel_qc_v2(
            blocks, BIOSEMI64_CHANNELS, {}, filename="spatial-parity.bdf",
            sfreq=256.0, block_duration_s=5.0,
            window_hop_s=2.5 if overlap else 5.0,
        )

    actual = evaluate()
    monkeypatch.setattr(qc, "_zscore_rows", _baseline_zscore_rows)
    monkeypatch.setattr(
        qc, "_spatial_predictability_scores_with_neighbors", _baseline_spatial_scores,
    )
    expected = evaluate()
    assert actual.n_samples == n_samples
    assert actual.conditions[0].spatial_outlier_channels
    assert _bits_tree(actual.to_payload()) == _bits_tree(expected.to_payload())
