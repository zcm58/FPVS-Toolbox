from __future__ import annotations

from copy import deepcopy

import mne
import numpy as np
import pytest

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    attach_raw_biosemi64_geometry,
    cached_biosemi64_montage,
)
from Main_App.processing import preprocess
from Main_App.processing.analysis_spans import (
    AnalysisSpanPlanError,
    read_source_analysis_span_plan,
)
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol

pytestmark = pytest.mark.processing


def _recording(first_samp: int = 0) -> tuple[mne.io.RawArray, dict]:
    """Place the first oddball away from both an integer and a half sample."""

    scalp = list(BIOSEMI64_CHANNELS[:20])
    names = [*scalp, "EXG1", "EXG2", "Status"]
    data = np.random.default_rng(505).normal(scale=1e-6, size=(len(names), 1_000))
    data[-1] = 0.0
    data[-1, 10] = 1
    data[-1, 103 + np.arange(11) * 50] = 55
    raw = mne.io.RawArray(
        data,
        mne.create_info(names, 100.0, ["eeg"] * 22 + ["stim"]),
        first_samp=first_samp,
        verbose=False,
    )
    raw.set_montage(cached_biosemi64_montage(), on_missing="ignore", verbose=False)
    attach_raw_biosemi64_geometry(
        raw,
        electrode_mapping_profile="anatomical_labels",
        retained_channels=scalp,
        reference_channels=("EXG1", "EXG2"),
        stim_channel="Status",
    )
    protocol = FrequencyProtocol.from_recurrence(
        10,
        5,
        expected_analyzed_oddball_cycles=10,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    event_plan = plan_preflight_qc_events(
        events=mne.find_events(raw, stim_channel="Status", shortest_event=1, verbose=False),
        event_map={"Condition": 1},
        sfreq=100.0,
        n_times=raw.n_times,
        first_samp=raw.first_samp,
        frequency_protocol=protocol,
    ).to_payload()
    return raw, read_source_analysis_span_plan(event_plan)


def _params(source_plan: dict) -> dict:
    return {
        "downsample_rate": 25,
        "low_pass": None,
        "high_pass": None,
        "line_noise_filter_enabled": False,
        "reject_thresh": 1e12,
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "max_idx_keep": 20,
        "stim_channel": "Status",
        "_fpvs_source_analysis_span_plan": source_plan,
        "_fpvs_require_analysis_spans": True,
        "_fpvs_participant_id": "P001",
        "_fpvs_recording_id": "P001",
    }


@pytest.mark.parametrize("first_samp", [0, 73])
def test_preprocessing_scores_from_actual_v3_resampled_trigger(first_samp: int) -> None:
    raw, source_plan = _recording(first_samp)
    original_source_plan = deepcopy(source_plan)
    # Exercise the exact v3 Raw resampling call independently of span mapping.
    reference = raw.copy().resample(25, npad="auto", window="hann", verbose=False)
    observed_events = mne.find_events(
        reference, stim_channel="Status", shortest_event=1, verbose=False
    )
    observed_start = int(observed_events[observed_events[:, 2] == 55][0, 0])
    assert observed_start - reference.first_samp == 25
    assert round(103 * 25 / 100) == 26

    params = _params(source_plan)
    processed, rejected = preprocess.perform_preprocessing(
        raw, params, lambda _message: None, "P001.bdf"
    )

    assert processed is not None, params.get("_fpvs_preprocessing_error")
    assert rejected == 0
    target_plan = params["_fpvs_realized_analysis_span_plan"]
    coordinates = target_plan["spans"][0]["target_coordinates"]
    assert coordinates["start_sample"] == observed_start
    assert coordinates["stop_sample"] - coordinates["start_sample"] == 125
    assert params["_fpvs_analysis_scoring_sample_count"] == 125
    assert params["_fpvs_kurtosis_qc_evidence"]["scoring_scope"]["unique_sample_count"] == 125
    np.testing.assert_array_equal(
        mne.find_events(processed, stim_channel="Status", shortest_event=1, verbose=False),
        observed_events,
    )
    assert source_plan == original_source_plan
    assert target_plan["spans"][0]["source_coordinates"] == source_plan["spans"][0]["source_coordinates"]


@pytest.mark.parametrize("changed_boundary", ["missing", "shifted"])
def test_changed_resampled_boundary_blocks_before_scoring_or_interpolation(
    monkeypatch: pytest.MonkeyPatch, changed_boundary: str
) -> None:
    raw, source_plan = _recording()
    original_source_plan = deepcopy(source_plan)
    raw._data[-1, 103] = 0
    if changed_boundary == "shifted":
        raw._data[-1, 107] = 55
    reached: list[str] = []

    def unexpected_scoring(*_args, **_kwargs):
        reached.append("scoring")
        raise AssertionError("A mismatched trigger must block before kurtosis scoring.")

    def unexpected_interpolation(*_args, **_kwargs):
        reached.append("interpolation")
        raise AssertionError("A mismatched trigger must block before interpolation.")

    monkeypatch.setattr(preprocess, "evaluate_kurtosis_qc", unexpected_scoring)
    monkeypatch.setattr(preprocess, "_interpolate_current_bads", unexpected_interpolation)
    params = _params(source_plan)

    processed, rejected = preprocess.perform_preprocessing(
        raw, params, lambda _message: None, "P001.bdf"
    )

    assert processed is None
    assert rejected == 0
    assert "no longer matches an actual oddball marker" in params["_fpvs_preprocessing_error"]
    assert reached == []
    assert "_fpvs_realized_analysis_span_plan" not in params
    assert "_fpvs_kurtosis_qc_evidence" not in params
    assert source_plan == original_source_plan


def test_downsampled_annotation_only_recording_requires_recorded_stimulus() -> None:
    raw, source_plan = _recording()
    raw.set_annotations(mne.Annotations([1.03], [0.0], ["55"]))
    raw.drop_channels(["Status"])
    raw.resample(25, npad="auto", window="hann", verbose=False)
    params = _params(source_plan)

    with pytest.raises(AnalysisSpanPlanError, match="recorded stimulus channel"):
        preprocess._realize_analysis_spans_for_raw(raw, params)

    assert "_fpvs_realized_analysis_span_plan" not in params


def test_downsampled_concatenated_recording_requires_single_segment() -> None:
    raw, source_plan = _recording()
    raw.append(raw.copy())
    raw.resample(25, npad="auto", window="hann", verbose=False)
    params = _params(source_plan)

    with pytest.raises(AnalysisSpanPlanError, match="single recording segment"):
        preprocess._realize_analysis_spans_for_raw(raw, params)

    assert "_fpvs_realized_analysis_span_plan" not in params
