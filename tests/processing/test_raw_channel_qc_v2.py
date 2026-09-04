from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import mne
import numpy as np
import pytest

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    attach_raw_biosemi64_geometry,
    cached_biosemi64_montage,
)
import Main_App.processing.raw_channel_qc as raw_channel_qc
from Main_App.processing.raw_channel_qc import (
    ConditionRawChannelQCBlock,
    ConditionRawChannelQCCancelled,
    RawChannelBlockMetrics,
    RawChannelMetricSet,
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
    window_kind: str = "regular",
) -> ConditionRawChannelQCBlock:
    return ConditionRawChannelQCBlock(
        condition_id=condition_id,
        occurrence=occurrence,
        start_sample=start,
        stop_sample=start + data.shape[1],
        data=data,
        is_final=final,
        window_kind=window_kind,
    )


def _metric(result, channel: str):
    return next(
        row
        for row in result.conditions[0].channel_metrics
        if row.channel == channel
    )


def _extrema(result, channel: str):
    return next(item for item in result.transient_extrema if item.channel == channel)


def _review_window(start: int, stop: int) -> RawChannelBlockMetrics:
    return RawChannelBlockMetrics(
        condition_id="faces",
        occurrence=0,
        block_index=start,
        start_sample=start,
        stop_sample=stop,
        metrics=RawChannelMetricSet(
            channel="Fp1",
            std_uv=1.0,
            p2p_99_uv=2.0,
            p2p_999_uv=3.0,
            full_p2p_uv=4.0,
        ),
        sampling_rate_hz=10.0,
        review_categories=("high_amplitude",),
    )


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


def test_overlapping_windows_count_full_occurrence_samples_once() -> None:
    data = _noise(23, 4)
    starts = (0, 5, 10, 13)
    blocks = [
        _block(
            "faces",
            0,
            100 + start,
            data[:, start : start + 10],
            final=index == len(starts) - 1,
            window_kind=("tail_aligned" if index == len(starts) - 1 else "regular"),
        )
        for index, start in enumerate(starts)
    ]

    result = evaluate_condition_raw_channel_qc_v2(
        blocks,
        CHANNELS,
        SETTINGS,
        filename="overlap.bdf",
        sfreq=2.0,
        block_duration_s=5.0,
        window_hop_s=2.5,
    )

    expected = raw_channel_qc._v2_channel_metrics("Fp1", data[0])
    assert result.n_blocks == 4
    assert result.n_samples == 23
    assert _metric(result, "Fp1") == expected
    assert result.transient_windowing["actual_window_samples"] == 10
    assert result.transient_windowing["actual_hop_samples"] == 5
    assert result.transient_windowing["full_occurrence_sample_counting"] == (
        "unique_samples_once"
    )


def test_overlapping_windows_preserve_cap_wide_amplitude_burst_with_detector_off() -> None:
    sfreq = 100.0
    data = np.random.default_rng(20260904).normal(
        scale=50e-6,
        size=(len(CHANNELS), 2_000),
    )
    data[:, 995:1_000] = np.random.default_rng(17).normal(
        scale=0.03,
        size=(len(CHANNELS), 5),
    )
    starts = tuple(range(0, 1_501, 250))
    blocks = [
        _block(
            "faces",
            0,
            start,
            data[:, start : start + 500],
            final=index == len(starts) - 1,
        )
        for index, start in enumerate(starts)
    ]

    result = evaluate_condition_raw_channel_qc_v2(
        blocks,
        CHANNELS,
        {
            **SETTINGS,
            "removed_electrode_detection_mode": "off",
            "auto_detect_removed_electrodes": False,
        },
        filename="transient-amplitude.bdf",
        sfreq=sfreq,
        block_duration_s=5.0,
        window_hop_s=2.5,
    )

    assert result.raw_baseline_warning is False
    assert result.excluded is False
    assert result.channels_to_interpolate == ()
    assert result.candidate_sources == {}
    assert result.review_rules == (
        "condition_transient_amplitude_baseline_warning",
    )
    assert len(result.transient_amplitude_review_findings) == 1
    finding = result.transient_amplitude_review_findings[0]
    assert finding["condition_label"] == "faces"
    assert finding["occurrence"] == 0
    assert finding["authority"] == "review_only"
    assert finding["scope"] == "overlapping_diagnostic_window_union"
    assert finding["diagnostic_window_count"] == 2
    assert finding["flagged_window_union_spans"] == [[500, 1_250]]
    assert finding["flagged_window_coverage_samples"] == 750
    assert finding["coverage_meaning"] == (
        "flagged_window_coverage_not_artifact_duration"
    )
    assert result.to_payload()["raw_amplitude_review_findings"] == [dict(finding)]


def test_repeated_overlapping_transient_flags_report_union_coverage() -> None:
    findings = raw_channel_qc._transient_review_findings(
        (_review_window(100, 150), _review_window(125, 175))
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding["diagnostic_window_count"] == 2
    assert finding["flagged_window_union_spans"] == [[100, 175]]
    assert finding["flagged_window_coverage_samples"] == 75
    assert finding["coverage_meaning"] == (
        "flagged_window_coverage_not_artifact_duration"
    )
    assert finding["authority"] == "review_only"


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


def test_v2_metrics_preserve_vector_percentile_signed_zero_bits() -> None:
    values = np.array(
        [0.0, 0.0, 0.0, 0.0, -0.0, -0.0],
        dtype=np.float64,
    )
    metrics = raw_channel_qc._v2_channel_metrics("Fp1", values)
    actual = (
        metrics.std_uv,
        metrics.p2p_99_uv,
        metrics.p2p_999_uv,
        metrics.full_p2p_uv,
    )

    assert tuple(np.float64(value).tobytes() for value in actual) == (
        np.float64(0.0).tobytes(),
        np.float64(-0.0).tobytes(),
        np.float64(-0.0).tobytes(),
        np.float64(0.0).tobytes(),
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


def test_occurrence_warning_names_one_flagged_scope_and_comparison_count() -> None:
    flagged = _noise(20, 127)
    flagged[0] = 0.0
    clean_a = _noise(20, 128)
    clean_b = _noise(20, 129)

    result = evaluate_condition_raw_channel_qc_v2(
        [
            _block("Condition A", 0, 0, flagged, final=True),
            _block("Condition A", 1, 100, clean_a, final=True),
            _block("Condition B", 0, 200, clean_b, final=True),
        ],
        CHANNELS,
        SETTINGS,
        filename="occurrence.bdf",
        sfreq=2.0,
    )

    finding = next(
        item
        for item in result.occurrence_review_findings
        if item["channel"] == "Fp1"
    )
    assert finding["condition_label"] == "Condition A"
    assert finding["occurrence_display"] == 1
    assert finding["evaluated_occurrence_count"] == 3
    assert finding["flagged_occurrence_count"] == 1
    assert finding["same_category_persistent"] is False
    assert finding["persistent_categories"] == []
    assert finding["statement"] == (
        "Fp1 was flagged as potentially bad in Condition A, occurrence 1 only. "
        "It was not flagged in the other 2 evaluated occurrences."
    )
    assert "Fp1" not in result.channels_to_interpolate


def test_occurrence_warnings_distinguish_persistent_and_varied_reasons() -> None:
    low_a = _noise(20, 130)
    low_b = _noise(20, 131)
    low_a[0] = 0.0
    low_b[0] = 0.0
    persistent = evaluate_condition_raw_channel_qc_v2(
        [
            _block("Condition A", 0, 0, low_a, final=True),
            _block("Condition B", 0, 100, low_b, final=True),
        ],
        CHANNELS,
        SETTINGS,
        filename="persistent.bdf",
        sfreq=2.0,
    )

    persistent_rows = [
        item
        for item in persistent.occurrence_review_findings
        if item["channel"] == "Fp1"
    ]
    assert len(persistent_rows) == 2
    assert all(item["same_category_persistent"] for item in persistent_rows)
    assert "Fp1" in persistent.channels_to_interpolate

    mixed_superset_conditions = (
        persistent.conditions[0],
        replace(
            persistent.conditions[1],
            spatial_outlier_channels=("Fp1",),
        ),
    )
    mixed_superset_rows = [
        item
        for item in raw_channel_qc._occurrence_review_findings(
            mixed_superset_conditions,
            CHANNELS,
        )
        if item["channel"] == "Fp1"
    ]
    assert all(item["same_category_persistent"] for item in mixed_superset_rows)
    assert all(
        item["persistent_categories"] == ["low_variance"]
        for item in mixed_superset_rows
    )

    high = _noise(20, 132)
    high[0] = np.random.default_rng(133).normal(scale=20_000e-6, size=20)
    varied = evaluate_condition_raw_channel_qc_v2(
        [
            _block("Condition A", 0, 0, low_a, final=True),
            _block("Condition B", 0, 100, high, final=True),
        ],
        CHANNELS,
        SETTINGS,
        filename="varied.bdf",
        sfreq=2.0,
    )
    varied_rows = [
        item
        for item in varied.occurrence_review_findings
        if item["channel"] == "Fp1"
    ]
    assert len(varied_rows) == 2
    assert all(item["all_evaluated_occurrences_flagged"] for item in varied_rows)
    assert all(item["reason_varied"] for item in varied_rows)
    assert all("reason varied" in item["statement"] for item in varied_rows)
    assert "Fp1" not in varied.channels_to_interpolate


def test_persistent_v2_candidate_cluster_is_review_only() -> None:
    channel_names = tuple(BIOSEMI64_CHANNELS)
    clustered = ("F7", "FT7", "FC5", "T7", "C5", "CP5")

    def occurrence(seed: int) -> np.ndarray:
        data = np.random.default_rng(seed).normal(
            scale=500e-6,
            size=(len(channel_names), 20),
        )
        for channel in clustered:
            data[channel_names.index(channel)] = 0.0
        return data

    result = evaluate_condition_raw_channel_qc_v2(
        [
            _block("Condition A", 0, 0, occurrence(140), final=True),
            _block("Condition B", 0, 100, occurrence(141), final=True),
        ],
        channel_names,
        {**SETTINGS, "max_bad_chans": 5},
        filename="persistent-cluster.bdf",
        sfreq=2.0,
    )

    assert result.excluded is False
    assert result.triggered_rules == ()
    assert set(result.channels_to_interpolate) == set(clustered)
    assert "candidate_count_review" in result.review_rules
    assert "candidate_cluster_review" in result.review_rules
    assert all(
        finding["authority"] == "review_only"
        for finding in result.burden_findings
    )


def test_detector_off_emits_no_occurrence_channel_findings() -> None:
    flagged = _noise(20, 134)
    flagged[0] = 0.0
    result = evaluate_condition_raw_channel_qc_v2(
        [_block("Condition A", 0, 0, flagged, final=True)],
        CHANNELS,
        {**SETTINGS, "auto_detect_removed_electrodes": False},
        filename="off.bdf",
        sfreq=2.0,
    )

    assert result.occurrence_review_findings == ()
    assert result.candidate_sources == {}
    assert result.channels_to_interpolate == ()
    assert result.thresholds["auto_detect_removed_electrodes"] is False


def test_v1_raw_channel_qc_result_is_unchanged_after_v2_evaluation() -> None:
    data = _noise(2048, 131)
    raw = mne.io.RawArray(
        data,
        mne.create_info(CHANNELS, sfreq=256.0, ch_types=["eeg"] * len(CHANNELS)),
        verbose=False,
    )
    raw.set_montage(cached_biosemi64_montage())
    attach_raw_biosemi64_geometry(
        raw,
        electrode_mapping_profile="anatomical_labels",
        retained_channels=CHANNELS,
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
