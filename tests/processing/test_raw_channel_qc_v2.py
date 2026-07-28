from __future__ import annotations

from collections.abc import Iterator

import mne
import numpy as np
import pytest

import Main_App.processing.raw_channel_qc as raw_channel_qc
from Main_App.processing.raw_channel_qc import (
    ConditionRawChannelQCBlock,
    ConditionRawChannelQCCancelled,
    combine_condition_raw_channel_qc_v2,
    evaluate_condition_raw_channel_qc_v2,
    evaluate_raw_channel_qc,
)


CHANNELS = (
    "Fp1",
    "AF7",
    "AF3",
    "F1",
    "F3",
    "F5",
    "F7",
    "FT7",
    "FC5",
    "FC3",
    "FC1",
    "C1",
    "C3",
    "C5",
    "T7",
    "TP7",
)
SETTINGS = {"stim_channel": "Status", "max_bad_chans": 20}


def _noise(n_samples: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(
        scale=500e-6,
        size=(len(CHANNELS), n_samples),
    )


def _block(
    condition_id: str,
    occurrence: int,
    start: int,
    data: np.ndarray,
    *,
    final: bool,
) -> ConditionRawChannelQCBlock:
    return ConditionRawChannelQCBlock(
        condition_id=condition_id,
        occurrence=occurrence,
        start_sample=start,
        stop_sample=start + data.shape[1],
        data=data,
        is_final=final,
    )


def _metric(result, channel: str):
    return next(
        row
        for row in result.conditions[0].channel_metrics
        if row.channel == channel
    )


def _extrema(result, channel: str):
    return next(item for item in result.transient_extrema if item.channel == channel)


def test_condition_qc_examines_every_block_and_includes_final_partial() -> None:
    first = _noise(20, 1)
    middle = _noise(20, 2)
    final_partial = _noise(3, 3)
    middle[0, 8] = 0.02
    final_partial[0] = np.array([-0.03, 0.0, 0.03])
    yielded: list[int] = []

    def blocks() -> Iterator[ConditionRawChannelQCBlock]:
        for index, block in enumerate(
            (
                _block("faces", 0, 100, first, final=False),
                _block("faces", 0, 120, middle, final=False),
                _block("faces", 0, 140, final_partial, final=True),
            )
        ):
            yielded.append(index)
            yield block

    result = evaluate_condition_raw_channel_qc_v2(
        blocks(),
        CHANNELS,
        SETTINGS,
        filename="p01.bdf",
        sfreq=2.0,
    )

    assert yielded == [0, 1, 2]
    assert result.n_blocks == 3
    assert result.n_samples == 43
    expected = np.concatenate((first[0], middle[0], final_partial[0]))
    assert _metric(result, "Fp1").full_p2p_uv == float(
        (np.nanmax(expected) - np.nanmin(expected)) * 1e6
    )
    loudest = _extrema(result, "Fp1").highest_amplitude_block
    assert (loudest.start_sample, loudest.stop_sample, loudest.block_index) == (140, 143, 2)


def test_condition_qc_vectorized_percentiles_are_bit_exact_with_v1_formulas() -> None:
    values = np.random.default_rng(44).normal(size=50).astype(np.float64) * 1e-4
    data = np.vstack([values + index * 1e-9 for index in range(len(CHANNELS))])

    result = evaluate_condition_raw_channel_qc_v2(
        [_block("words", 0, 0, data, final=True)],
        CHANNELS,
        SETTINGS,
        filename="p02.bdf",
        sfreq=5.0,
    )
    metrics = _metric(result, "Fp1")
    scalar_formula_values = (
        float(np.nanstd(values) * 1e6),
        float((np.nanpercentile(values, 99.5) - np.nanpercentile(values, 0.5)) * 1e6),
        float((np.nanpercentile(values, 99.95) - np.nanpercentile(values, 0.05)) * 1e6),
        float((np.nanmax(values) - np.nanmin(values)) * 1e6),
    )
    vectorized_values = (
        metrics.std_uv,
        metrics.p2p_99_uv,
        metrics.p2p_999_uv,
        metrics.full_p2p_uv,
    )

    assert tuple(np.float64(value).tobytes() for value in vectorized_values) == tuple(
        np.float64(value).tobytes() for value in scalar_formula_values
    )


def test_v2_metrics_preserve_explicit_float64_coercion() -> None:
    values = np.random.default_rng(0).normal(size=257).astype(np.float32)
    values64 = np.asarray(values, dtype=np.float64)

    metrics = raw_channel_qc._v2_channel_metrics("Fp1", values)
    expected = (
        float(np.nanstd(values64) * 1e6),
        float(
            (
                np.nanpercentile(values64, 99.5)
                - np.nanpercentile(values64, 0.5)
            )
            * 1e6
        ),
        float(
            (
                np.nanpercentile(values64, 99.95)
                - np.nanpercentile(values64, 0.05)
            )
            * 1e6
        ),
        float((np.nanmax(values64) - np.nanmin(values64)) * 1e6),
    )
    actual = (
        metrics.std_uv,
        metrics.p2p_99_uv,
        metrics.p2p_999_uv,
        metrics.full_p2p_uv,
    )

    assert tuple(np.float64(value).tobytes() for value in actual) == tuple(
        np.float64(value).tobytes() for value in expected
    )


def test_shared_condition_buffer_avoids_full_concatenation(monkeypatch) -> None:
    data = _noise(43, 45)
    blocks = [
        _block("faces", 0, 100, data[:, :20], final=False),
        _block("faces", 0, 120, data[:, 20:40], final=False),
        _block("faces", 0, 140, data[:, 40:], final=True),
    ]
    shared_view_calls = 0
    original_shared_view = raw_channel_qc._shared_full_condition_view

    def _record_shared_view(chunks):  # noqa: ANN001
        nonlocal shared_view_calls
        shared_view_calls += 1
        result = original_shared_view(chunks)
        assert result is data
        return result

    monkeypatch.setattr(raw_channel_qc, "_shared_full_condition_view", _record_shared_view)

    result = evaluate_condition_raw_channel_qc_v2(
        blocks,
        CHANNELS,
        SETTINGS,
        filename="p02b.bdf",
        sfreq=2.0,
    )

    assert result.n_samples == 43
    assert shared_view_calls == 1


def test_artifact_outside_submitted_condition_samples_is_irrelevant() -> None:
    clean_recording = _noise(60, 91)
    recording_with_outside_artifact = clean_recording.copy()
    recording_with_outside_artifact[0, :10] = 100.0
    recording_with_outside_artifact[0, 50:] = -100.0

    clean_result = evaluate_condition_raw_channel_qc_v2(
        [_block("objects", 0, 20, clean_recording[:, 20:40], final=True)],
        CHANNELS,
        SETTINGS,
        filename="p03.bdf",
        sfreq=2.0,
    )
    outside_artifact_result = evaluate_condition_raw_channel_qc_v2(
        [_block("objects", 0, 20, recording_with_outside_artifact[:, 20:40], final=True)],
        CHANNELS,
        SETTINGS,
        filename="p03.bdf",
        sfreq=2.0,
    )

    assert outside_artifact_result.to_payload() == clean_result.to_payload()


def test_condition_results_combine_deterministically_across_occurrences() -> None:
    first_block = _block("faces", 0, 100, _noise(20, 101), final=True)
    second_block = _block("words", 0, 300, _noise(7, 102), final=True)
    first = evaluate_condition_raw_channel_qc_v2(
        [first_block],
        CHANNELS,
        SETTINGS,
        filename="p04.bdf",
        sfreq=2.0,
    )
    second = evaluate_condition_raw_channel_qc_v2(
        [second_block],
        CHANNELS,
        SETTINGS,
        filename="p04.bdf",
        sfreq=2.0,
    )
    combined = combine_condition_raw_channel_qc_v2(
        [second, first],
        filename="p04.bdf",
    )
    direct = evaluate_condition_raw_channel_qc_v2(
        [second_block, first_block],
        CHANNELS,
        SETTINGS,
        filename="p04.bdf",
        sfreq=2.0,
    )

    assert combined.to_payload() == direct.to_payload()
    assert [(item.condition_id, item.start_sample) for item in combined.conditions] == [
        ("faces", 100),
        ("words", 300),
    ]


def test_condition_qc_checks_cancellation_before_consuming_next_block() -> None:
    yielded = 0

    def blocks() -> Iterator[ConditionRawChannelQCBlock]:
        nonlocal yielded
        for block in (
            _block("faces", 0, 0, _noise(20, 111), final=False),
            _block("faces", 0, 20, _noise(4, 112), final=True),
        ):
            yielded += 1
            yield block

    checks = iter((False, True))

    with pytest.raises(ConditionRawChannelQCCancelled):
        evaluate_condition_raw_channel_qc_v2(
            blocks(),
            CHANNELS,
            SETTINGS,
            filename="p05.bdf",
            sfreq=2.0,
            should_cancel=lambda: next(checks),
        )

    assert yielded == 1


def test_transient_findings_remain_review_only() -> None:
    first = _noise(20, 121)
    second = _noise(20, 122)
    first[0] = 0.0
    first[1] = 0.0
    second[1] = 0.0

    result = evaluate_condition_raw_channel_qc_v2(
        [
            _block("faces", 0, 0, first, final=False),
            _block("faces", 0, 20, second, final=True),
        ],
        CHANNELS,
        SETTINGS,
        filename="p06.bdf",
        sfreq=2.0,
    )

    assert result.transient_low_variance_channels == ()
    assert _extrema(result, "Fp1").lowest_variance_block.start_sample == 0
    assert "Fp1" not in result.persistent_low_variance_channels
    assert "Fp1" not in result.channels_to_interpolate
    assert "AF7" in result.persistent_low_variance_channels
    assert "AF7" in result.channels_to_interpolate
    assert result.excluded is False
    assert result.triggered_rules == ()
    assert result.review_only is True


def test_persistent_candidates_must_repeat_across_all_condition_occurrences() -> None:
    first = _noise(20, 125)
    second = _noise(20, 126)
    first[0] = 0.0

    result = evaluate_condition_raw_channel_qc_v2(
        [
            _block("faces", 0, 0, first, final=True),
            _block("words", 0, 100, second, final=True),
        ],
        CHANNELS,
        SETTINGS,
        filename="p06b.bdf",
        sfreq=2.0,
    )

    assert "Fp1" in result.conditions[0].low_variance_channels
    assert "Fp1" not in result.conditions[1].low_variance_channels
    assert result.transient_low_variance_channels == ()
    assert _extrema(result, "Fp1").lowest_variance_block.condition_id == "faces"
    assert "Fp1" not in result.persistent_low_variance_channels
    assert "Fp1" not in result.channels_to_interpolate
    assert "Fp1" not in result.to_payload()["low_variance_channels"]


def test_v1_raw_channel_qc_result_is_unchanged_after_v2_evaluation() -> None:
    data = _noise(2048, 131)
    raw = mne.io.RawArray(
        data,
        mne.create_info(CHANNELS, sfreq=256.0, ch_types=["eeg"] * len(CHANNELS)),
        verbose=False,
    )
    before = evaluate_raw_channel_qc(raw, SETTINGS, filename="p07.bdf")

    evaluate_condition_raw_channel_qc_v2(
        [_block("faces", 0, 0, data, final=True)],
        CHANNELS,
        SETTINGS,
        filename="p07.bdf",
        sfreq=256.0,
    )
    after = evaluate_raw_channel_qc(raw, SETTINGS, filename="p07.bdf")

    assert after == before
