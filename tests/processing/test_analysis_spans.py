from __future__ import annotations

import copy

import numpy as np
import pytest
import mne

from Main_App.processing.analysis_spans import (
    ANALYSIS_SPAN_PLAN_VERSION,
    AnalysisSpanPlanError,
    merge_relative_spans,
    read_source_analysis_span_plan,
    realize_target_analysis_span_plan,
    relative_spans_from_plan,
    restrict_source_analysis_span_plan_by_condition,
    validate_realized_target_analysis_span_plan,
    validate_source_analysis_span_context,
    validate_source_analysis_span_plan,
)
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.preprocess import _kurtosis_scoring_data
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol

pytestmark = pytest.mark.processing


def _protocol() -> FrequencyProtocol:
    return FrequencyProtocol.from_recurrence(
        6,
        3,
        expected_analyzed_oddball_cycles=4,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )


def _source_events(first_samp: int = 100) -> np.ndarray:
    return np.asarray(
        [
            [first_samp, 0, 1],
            [first_samp + 10, 0, 55],
            [first_samp + 16, 0, 55],
            [first_samp + 22, 0, 55],
            [first_samp + 28, 0, 55],
            [first_samp + 34, 0, 55],
        ],
        dtype=int,
    )


def _event_plan(first_samp: int = 100) -> dict[str, object]:
    return plan_preflight_qc_events(
        events=_source_events(first_samp),
        event_map={"Faces": 1},
        sfreq=12.0,
        n_times=60,
        first_samp=first_samp,
        frequency_protocol=_protocol(),
    ).to_payload()


def _two_condition_event_plan(first_samp: int = 100) -> dict[str, object]:
    events = np.asarray(
        [
            [first_samp, 0, 1],
            [first_samp + 10, 0, 55],
            [first_samp + 16, 0, 55],
            [first_samp + 22, 0, 55],
            [first_samp + 28, 0, 55],
            [first_samp + 34, 0, 55],
            [first_samp + 40, 0, 2],
            [first_samp + 50, 0, 55],
            [first_samp + 56, 0, 55],
            [first_samp + 62, 0, 55],
            [first_samp + 68, 0, 55],
            [first_samp + 74, 0, 55],
        ],
        dtype=int,
    )
    return plan_preflight_qc_events(
        events=events,
        event_map={"Faces": 1, "Objects": 2},
        sfreq=12.0,
        n_times=100,
        first_samp=first_samp,
        frequency_protocol=_protocol(),
    ).to_payload()


def test_source_plan_records_absolute_relative_and_nonzero_origin() -> None:
    event_plan = _event_plan()
    source_plan = validate_source_analysis_span_plan(
        event_plan_payload=event_plan,
        events=_source_events(),
        sampling_rate_hz=12,
        n_times=60,
        first_samp=100,
        event_map={"Faces": 1},
        protocol=_protocol(),
    )

    assert source_plan["version"] == ANALYSIS_SPAN_PLAN_VERSION
    assert source_plan["source_grid"] == {
        "sfreq_hz": 12.0,
        "n_times": 60,
        "first_samp": 100,
        "sample_origin": "raw.first_samp",
    }
    coordinates = source_plan["spans"][0]["source_coordinates"]
    assert coordinates == {
        "first_samp": 100,
        "start_sample": 110,
        "stop_sample": 134,
        "start_relative_sample": 10,
        "stop_relative_sample": 34,
    }
    assert relative_spans_from_plan(source_plan) == ((10, 34),)


def test_target_realization_uses_actual_grid_and_half_up_rounding() -> None:
    source_plan = read_source_analysis_span_plan(_event_plan())
    target_plan = realize_target_analysis_span_plan(
        source_plan,
        target_sfreq_hz=6,
        target_n_times=30,
        target_first_samp=50,
    )

    coordinates = target_plan["spans"][0]["target_coordinates"]
    assert coordinates == {
        "first_samp": 50,
        "start_sample": 55,
        "stop_sample": 67,
        "start_relative_sample": 5,
        "stop_relative_sample": 17,
    }
    assert relative_spans_from_plan(target_plan) == ((5, 17),)
    assert validate_realized_target_analysis_span_plan(
        target_plan,
        source_plan=source_plan,
        target_sfreq_hz=6,
        target_n_times=30,
        target_first_samp=50,
    ) == target_plan


def test_condition_exclusion_derives_a_fingerprinted_analyzed_subset() -> None:
    parent = read_source_analysis_span_plan(_two_condition_event_plan())

    restricted = restrict_source_analysis_span_plan_by_condition(
        parent,
        excluded_condition_labels=["objects"],
        exclusion_scope={"participant_id": "P01", "recording_id": "P01__visit-1"},
    )

    assert [span["condition_label"] for span in restricted["spans"]] == ["Faces"]
    assert restricted["condition_selection"] == {
        "version": "manual_condition_exclusion_v1",
        "parent_source_plan_fingerprint": parent["fingerprint"],
        "excluded_condition_labels": ["objects"],
        "scope": {"participant_id": "P01", "recording_id": "P01__visit-1"},
    }
    assert restricted["fingerprint"] != parent["fingerprint"]
    target = realize_target_analysis_span_plan(
        restricted,
        target_sfreq_hz=6,
        target_n_times=50,
        target_first_samp=50,
    )
    assert target["condition_selection"] == restricted["condition_selection"]
    assert [span["condition_label"] for span in target["spans"]] == ["Faces"]


def test_condition_exclusion_can_account_for_an_all_condition_no_output_state() -> None:
    parent = read_source_analysis_span_plan(_two_condition_event_plan())

    restricted = restrict_source_analysis_span_plan_by_condition(
        parent,
        excluded_condition_labels=["Faces", "Objects"],
        exclusion_scope={"participant_id": "P01"},
    )

    assert restricted["spans"] == []
    assert relative_spans_from_plan(restricted) == ()
    with pytest.raises(AnalysisSpanPlanError, match="No retained analyzed"):
        realize_target_analysis_span_plan(
            restricted,
            target_sfreq_hz=6,
            target_n_times=50,
            target_first_samp=50,
        )


def test_unique_union_never_weights_overlapping_samples_twice() -> None:
    assert merge_relative_spans(
        [(20, 30), (0, 10), (5, 25), (40, 45)],
        n_times=50,
    ) == ((0, 30), (40, 45))


def test_source_validation_rejects_changed_events_and_sample_origin() -> None:
    event_plan = _event_plan()
    changed_events = _source_events()
    changed_events[-1, 0] += 1
    with pytest.raises(ValueError, match="digest is stale"):
        validate_source_analysis_span_plan(
            event_plan_payload=event_plan,
            events=changed_events,
            sampling_rate_hz=12,
            n_times=60,
            first_samp=100,
            event_map={"Faces": 1},
            protocol=_protocol(),
        )
    with pytest.raises(ValueError, match="sample origin is stale"):
        validate_source_analysis_span_plan(
            event_plan_payload=event_plan,
            events=_source_events(),
            sampling_rate_hz=12,
            n_times=60,
            first_samp=99,
            event_map={"Faces": 1},
            protocol=_protocol(),
        )


def test_source_context_rejects_stale_protocol_and_condition_map() -> None:
    event_plan = _event_plan()
    assert validate_source_analysis_span_context(
        event_plan_payload=event_plan,
        event_map={"Faces": 1},
        protocol=_protocol(),
    )["fingerprint"]

    changed_protocol = FrequencyProtocol.from_recurrence(
        12,
        6,
        expected_analyzed_oddball_cycles=4,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    with pytest.raises(AnalysisSpanPlanError, match="protocol is stale"):
        validate_source_analysis_span_context(
            event_plan_payload=event_plan,
            event_map={"Faces": 1},
            protocol=changed_protocol,
        )
    with pytest.raises(AnalysisSpanPlanError, match="event map is stale"):
        validate_source_analysis_span_context(
            event_plan_payload=event_plan,
            event_map={"Objects": 1},
            protocol=_protocol(),
        )


def test_source_and_target_fingerprints_fail_closed_on_tampering() -> None:
    event_plan = _event_plan()
    stale_event_plan = copy.deepcopy(event_plan)
    stale_event_plan["spans"][0]["time_start_sample"] += 1
    with pytest.raises(AnalysisSpanPlanError, match="event-plan fingerprint"):
        read_source_analysis_span_plan(stale_event_plan)

    source_plan = read_source_analysis_span_plan(event_plan)
    target_plan = realize_target_analysis_span_plan(
        source_plan,
        target_sfreq_hz=6,
        target_n_times=30,
        target_first_samp=50,
    )
    stale_target = copy.deepcopy(target_plan)
    stale_target["spans"][0]["target_coordinates"]["start_relative_sample"] += 1
    with pytest.raises(AnalysisSpanPlanError, match="missing or stale"):
        validate_realized_target_analysis_span_plan(
            stale_target,
            source_plan=source_plan,
            target_sfreq_hz=6,
            target_n_times=30,
            target_first_samp=50,
        )


def test_kurtosis_input_uses_only_realized_target_samples() -> None:
    source_plan = read_source_analysis_span_plan(_event_plan())
    target_plan = realize_target_analysis_span_plan(
        source_plan,
        target_sfreq_hz=6,
        target_n_times=30,
        target_first_samp=50,
    )
    data = np.arange(60, dtype=float).reshape(2, 30)
    raw = mne.io.RawArray(
        data,
        mne.create_info(["Cz", "Pz"], sfreq=6.0, ch_types=["eeg", "eeg"]),
        first_samp=50,
        verbose=False,
    )
    outside_changed = raw.copy()
    outside_changed._data[:, :5] = -1_000_000
    outside_changed._data[:, 17:] = 1_000_000
    params = {
        "_fpvs_require_analysis_spans": True,
        "_fpvs_realized_analysis_span_plan": target_plan,
    }

    expected = data[:, 5:17]
    assert np.array_equal(
        _kurtosis_scoring_data(raw, picks=[0, 1], params=params),
        expected,
    )
    assert np.array_equal(
        _kurtosis_scoring_data(
            outside_changed,
            picks=[0, 1],
            params=params,
        ),
        expected,
    )


def test_actual_raw_resample_realizes_nonzero_origin_half_sample_boundaries() -> None:
    protocol = FrequencyProtocol.from_recurrence(
        4,
        2,
        expected_analyzed_oddball_cycles=2,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    first_samp = 101
    events = np.asarray(
        [
            [first_samp, 0, 1],
            [first_samp + 1, 0, 55],
            [first_samp + 3, 0, 55],
            [first_samp + 5, 0, 55],
        ],
        dtype=int,
    )
    event_plan = plan_preflight_qc_events(
        events=events,
        event_map={"Faces": 1},
        sfreq=4,
        n_times=12,
        first_samp=first_samp,
        frequency_protocol=protocol,
    ).to_payload()
    source_plan = validate_source_analysis_span_plan(
        event_plan_payload=event_plan,
        events=events,
        sampling_rate_hz=4,
        n_times=12,
        first_samp=first_samp,
        event_map={"Faces": 1},
        protocol=protocol,
    )
    raw = mne.io.RawArray(
        np.arange(12, dtype=float).reshape(1, 12),
        mne.create_info(["Cz"], sfreq=4, ch_types=["eeg"]),
        first_samp=first_samp,
        verbose=False,
    )

    raw.resample(2, npad="auto", window="hann", verbose=False)
    target_plan = realize_target_analysis_span_plan(
        source_plan,
        target_sfreq_hz=raw.info["sfreq"],
        target_n_times=raw.n_times,
        target_first_samp=raw.first_samp,
    )

    assert raw.first_samp == 50  # MNE rounds the absolute origin independently.
    assert raw.n_times == 6
    assert target_plan["spans"][0]["target_coordinates"] == {
        "first_samp": 50,
        "start_sample": 51,
        "stop_sample": 53,
        "start_relative_sample": 1,
        "stop_relative_sample": 3,
    }
    assert relative_spans_from_plan(target_plan) == ((1, 3),)
    target_coordinates = target_plan["spans"][0]["target_coordinates"]
    assert (
        target_coordinates["stop_relative_sample"]
        - target_coordinates["start_relative_sample"]
        == protocol.expected_analyzed_samples(2)
    )
