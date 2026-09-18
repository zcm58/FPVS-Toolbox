"""Synthetic verification of review-only MNE diagnostic adapters and scope."""

from dataclasses import replace
import gc
import json

import mne
import numpy as np
import pytest

from Main_App.io.eeg_geometry import canonical_biosemi64_head_coordinates
from Main_App.processing import qc_review_diagnostics as qc


def _report(data, *, sfreq=100.0, occurrences=None, channels=None, **kwargs):
    channels = channels or [f"C{index}" for index in range(len(data))]
    return qc.build_qc_review_diagnostics(
        data, sfreq=sfreq, channels=channels,
        occurrences=occurrences or [{"start_sample": 0, "stop_sample": data.shape[1], "condition_label": "Faces", "occurrence": 0}],
        positions={}, signal_stage="loaded_raw_before_reference", **kwargs,
    )


def test_mne_adapter_localizes_flat_plateau_and_jump_without_mutating_input(monkeypatch):
    rng = np.random.default_rng(82)
    data = rng.normal(0, 2e-6, (1, 1000))
    data[0, 100:180] = 0.0
    data[0, 260:267] = 150e-6
    data[0, 500:800] += 300e-6
    before = data.tobytes()
    calls = []
    original = mne.preprocessing.annotate_amplitude

    def spy(raw, **kwargs):
        calls.append(kwargs)
        assert raw.n_times <= 129
        return original(raw, **kwargs)

    monkeypatch.setattr(mne.preprocessing, "annotate_amplitude", spy)
    report = _report(data, sample_offset=1000, settings=qc.QCReviewDiagnosticSettings(chunk_samples=128))
    assert calls and all(call["bad_percent"] == 100 for call in calls)
    assert data.tobytes() == before
    events = report["localized_events"]
    flat = next(event for event in events if event["kind"] == "exact_flatline")
    assert (flat["start_sample"], flat["stop_sample"]) == (1100, 1180)
    assert flat["pattern_duration_s"] == pytest.approx(0.79)
    patterns = report["channel_summaries"][0]["pattern_summaries"]
    assert patterns["exact_flatline"]["observed_pattern_duration_s"] == pytest.approx(0.79)
    assert patterns["abrupt_jump"]["observed_pattern_duration_s"] < 0.1
    jumps = [(row["start_sample"], row["stop_sample"]) for row in events if row["kind"] == "abrupt_jump"]
    assert (1499, 1501) in jumps and (1799, 1801) in jumps
    # The short plateau is not the occurrence's extreme because the later DC
    # shift is higher: avoid claiming every repeated value is clipping.
    assert not any(row["kind"] == "candidate_clipping_plateau" for row in events)
    json.dumps(report, allow_nan=False)


def test_extreme_plateau_is_a_candidate_not_proven_adc_clipping():
    data = np.random.default_rng(2).normal(0, 2e-6, (1, 1000))
    data[0, 200:208] = 500e-6
    report = _report(data)
    row = next(row for row in report["localized_events"] if row["kind"] == "candidate_clipping_plateau")
    assert (row["start_sample"], row["stop_sample"]) == (200, 208)
    assert "not established" in row["interpretation"]
    assert row["authority"] == "review_only"


def test_nonzero_source_first_sample_keeps_recording_relative_event_clock():
    report = _report(np.zeros((1, 200)), sample_offset=1300, source_first_samp=1000)
    row = report["localized_events"][0]
    assert (row["start_sample"], row["stop_sample"]) == (1300, 1500)
    assert (row["start_s"], row["stop_s"]) == (3.0, 5.0)
    assert report["event_time_origin"] == "recording_start"


@pytest.mark.parametrize("sfreq", [100.0, 500.0, 1000.0])
def test_constant_signal_all_bad_mne_return_still_preserves_exact_support(sfreq):
    data = np.full((1, int(sfreq * 2)), 4e-6)
    report = _report(data, sfreq=sfreq, settings=qc.QCReviewDiagnosticSettings(chunk_samples=127))
    flat = [row for row in report["localized_events"] if row["kind"] == "exact_flatline"]
    assert len(flat) == 1
    assert (flat[0]["start_sample"], flat[0]["stop_sample"]) == (0, data.shape[1])
    assert flat[0]["left_boundary_censored"] and flat[0]["right_boundary_censored"]
    assert report["channel_summaries"][0]["jump_scale_status"] == "insufficient_or_degenerate"
    assert not any(row["kind"] == "candidate_clipping_plateau" for row in report["localized_events"])


@pytest.mark.parametrize("seed", [1, 8, 20])
def test_clean_noise_plus_expected_fpvs_signal_does_not_trigger_synthetic_patterns(seed):
    sfreq = 500
    time = np.arange(sfreq * 5) / sfreq
    data = np.random.default_rng(seed).normal(0, 2e-6, (2, len(time)))
    data += 10e-6 * np.sin(2 * np.pi * 10 * time)
    report = _report(data, sfreq=sfreq)
    assert report["localized_events"] == []
    assert "not a clean-data classification" in qc.format_qc_review_diagnostics(report)


def test_scope_and_same_pattern_recurrence_never_grant_whole_recording_repair():
    data = np.random.default_rng(32).normal(0, 2e-6, (1, 400))
    data[0, 50:130] = 0
    data[0, 250:330] = 0
    occurrences = [{"start_sample": 0, "stop_sample": 200, "occurrence_key": "one"},
                   {"start_sample": 200, "stop_sample": 400, "occurrence_key": "two"}]
    for scope in ("displayed_window", "supplied_occurrences", "all_analyzed_occurrences"):
        report = _report(data, occurrences=occurrences, evaluation_scope=scope)
        shadow = report["shadow_evidence"]
        row = shadow["channels"][0]
        assert row["same_pattern_in_every_supplied_occurrence"] == ["exact_flatline"]
        assert row["recording_scope_supported"] is (scope == "all_analyzed_occurrences")
        assert row["whole_recording_repair_supported"] is False
        assert shadow["eligible_kurtosis_corroborator"] is False
        text = qc.format_qc_review_diagnostics(report, channel="C0")
        assert ("recurred somewhere in every analyzed occurrence" in text) is (scope == "all_analyzed_occurrences")


def test_one_analyzed_occurrence_does_not_establish_recurrence():
    report = _report(np.zeros((1, 200)), evaluation_scope="all_analyzed_occurrences")
    assert report["shadow_evidence"]["channels"][0]["persistence_status"] == "insufficient_repeated_occurrences"
    assert "recurred" not in qc.format_qc_review_diagnostics(report)


def test_occurrence_boundaries_are_not_joined_and_source_changes_change_fingerprint():
    data = np.zeros((1, 80))
    occurrences = [{"start_sample": 0, "stop_sample": 40}, {"start_sample": 40, "stop_sample": 80}]
    first = _report(data, occurrences=occurrences)
    assert first["localized_events"] == []  # each 0.39-s span is below the 0.5-s rule
    data[0, 0] = 1e-6
    second = _report(data, occurrences=occurrences)
    assert first["fingerprint"] != second["fingerprint"]


def test_nonfinite_and_short_signals_preserve_unknown_evidence():
    data = np.full((1, 100), np.nan)
    report = _report(data, evaluation_scope="all_analyzed_occurrences")
    assert report["channel_summaries"][0]["status"] == "unavailable"
    assert report["shadow_evidence"]["channels"][0]["recording_scope_supported"] is False
    assert report["localized_events"] == []
    short = _report(np.array([[1e-6, 2e-6, 3e-6]]))
    assert short["channel_summaries"][0]["jump_threshold_uv"] is None
    json.dumps(report, allow_nan=False)


def test_localization_and_display_limits_remain_explicit():
    data = np.random.default_rng(33).normal(0, 1e-6, (1, 3000))
    for start in range(100, 2800, 100):
        data[0, start:start + 60] = 0
    report = _report(data, settings=qc.QCReviewDiagnosticSettings(max_events=3), evaluation_scope="all_analyzed_occurrences")
    assert len(report["localized_events"]) <= 3
    assert report["channel_summaries"][0]["localization_truncated"]
    pattern = report["channel_summaries"][0]["pattern_summaries"]["exact_flatline"]
    assert pattern["event_count_is_lower_bound"]
    assert pattern["observed_pattern_duration_s"] is None
    assert not report["shadow_evidence"]["channels"][0]["recording_scope_supported"]


def test_cancellation_is_checked_between_bounded_work_units():
    with pytest.raises(InterruptedError) as caught:
        _report(np.zeros((1, 200)), should_cancel=lambda: True)
    assert isinstance(caught.value, qc.QCReviewDiagnosticsCancelled)


def test_mne_scratch_ownership_never_unlinks_or_mutates_source_memmap(tmp_path):
    source_path = tmp_path / "owned-by-caller.dat"
    source = np.memmap(source_path, dtype="float64", mode="w+", shape=(1, 200))
    source[:] = 2e-6
    source.flush()
    before = source_path.read_bytes()
    report = _report(source)
    assert report["localized_events"][0]["kind"] == "exact_flatline"
    gc.collect()
    assert source_path.read_bytes() == before
    source._mmap.close()


def test_repair_topology_uses_named_positions_and_excludes_bad_donors():
    positions = {"A": (0.0, 0.0, 0.1), "B": (0.01, 0.0, 0.1),
                 "C": (0.03, 0.0, 0.1), "D": (0.2, 0.0, 0.1)}
    result = qc.review_repair_topology(list(positions), positions, repair_channels=["A", "B"],
                                      unusable_channels=["C"], settings=qc.QCReviewDiagnosticSettings(neighbor_count=1))
    assert result["components"] == [["A", "B"]]
    assert all(row["usable_donors"] == [{"channel": "D", "distance_m": pytest.approx(0.2 if row["channel"] == "A" else 0.19)}] for row in result["channels"])
    assert result["authority"] == "review_only"
    assert "risk" not in result
    assert qc.review_repair_topology(list(positions), positions, repair_channels=["Unknown"])["status"] == "unavailable"


def test_heldout_prediction_uses_mne_interpolation_and_preserves_original(monkeypatch):
    coordinates = canonical_biosemi64_head_coordinates()
    channels = list(coordinates)[:16]
    data = np.random.default_rng(44).normal(0, 5e-6, (len(channels), 600))
    original = data.tobytes()
    calls = []
    interpolate = mne.io.BaseRaw.interpolate_bads

    def spy(raw, *args, **kwargs):
        calls.append(tuple(raw.info["bads"]))
        return interpolate(raw, *args, **kwargs)

    monkeypatch.setattr(mne.io.BaseRaw, "interpolate_bads", spy)
    report = qc.build_qc_review_diagnostics(
        data, sfreq=100, channels=channels,
        occurrences=[{"start_sample": 0, "stop_sample": 600}], positions=coordinates,
        signal_stage="loaded_raw_before_reference", unusable_channels=[channels[-1]],
        settings=qc.QCReviewDiagnosticSettings(enable_spatial_holdout=True, max_holdout_channels=2),
    )
    assert len(calls) == 2
    assert all(channels[-1] in bads for bads in calls)
    assert data.tobytes() == original
    holdout = report["shadow_evidence"]["spatial_holdouts"][0]
    assert holdout["tested_channel_count"] == 2
    assert all(row["status"] == "available" for row in holdout["channels"])
    assert report["shadow_evidence"]["eligible_kurtosis_corroborator"] is False


def test_raw_adapter_uses_resident_per_channel_views_and_keeps_stim_out(monkeypatch):
    from tests.processing.test_preprocess_kurtosis_gate import _raw

    raw = _raw()
    raw.crop(tmin=1.0)
    before = raw._data.tobytes()
    monkeypatch.setattr(raw, "get_data", lambda **_kwargs: pytest.fail("full-array get_data copy"))
    report = qc.build_raw_qc_review_diagnostics(
        raw, occurrences=[{"start_sample": 0, "stop_sample": 500}], ref_channels=["EXG1", "EXG2"],
    )
    assert "Status" not in report["channels"]
    assert "EXG1" in report["channels"]
    assert report["evaluation_scope"] == "all_analyzed_occurrences"
    assert report["source_first_samp"] == 100
    assert report["localized_events"][0]["start_sample"] == 100
    assert report["localized_events"][0]["start_s"] == 0.0
    assert raw._data.tobytes() == before
    raw.close()


def test_on_demand_spatial_support_does_not_repeat_temporal_detection(monkeypatch):
    coordinates = canonical_biosemi64_head_coordinates()
    channels = list(coordinates)
    data = np.random.default_rng(5).normal(0, 4e-6, (len(channels), 100))
    before = data.tobytes()
    monkeypatch.setattr(qc, "_channel_patterns", lambda *_args: pytest.fail("temporal detector repeated"))
    result = qc.estimate_qc_spatial_support(
        data, channels=channels, positions=coordinates, unusable_channels=[channels[0]],
        settings={"max_holdout_channels": 1},
    )
    assert result["channels"][0]["channel"] == channels[1]
    assert result["channels"][0]["donor_count"] == 62
    assert result["eligible_kurtosis_corroborator"] is False
    assert "Supplied samples only" in result["summary"]
    assert data.tobytes() == before


@pytest.mark.parametrize("changes", [{"flatline_min_duration_s": 0}, {"chunk_samples": 1},
                                      {"summary_sample_limit": 100000}, {"enable_spatial_holdout": "yes"}])
def test_settings_reject_invalid_or_unbounded_values(changes):
    with pytest.raises(ValueError):
        replace(qc.QCReviewDiagnosticSettings(), **changes)
