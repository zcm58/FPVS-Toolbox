"""Native per-sample markers retain identity through generic event consumers."""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import mne
import numpy as np
import pytest

from Main_App.io.pipeline_events import (
    canonical_recording_events,
    restore_canonical_event_metadata,
    snapshot_canonical_event_metadata,
)
from Main_App.io.recording_contract import RecordingContract
from Main_App.io.recording_events import RecordingEventError


def _recording(values=None, *, first_samp=71):
    values = [3, 3, 0, 55, 55, 0, 2] if values is None else values
    raw = mne.io.RawArray(
        np.asarray([np.zeros(len(values)), values], dtype=float),
        mne.create_info(["E1", "Trigger"], 250, ["eeg", "stim"]),
        first_samp=first_samp, verbose=False,
    )
    raw._fpvs_recording_contract = RecordingContract(
        initial_reference_mode="average_scalp", initial_reference_channels=(),
        drop_reference_channels=False, max_idx_keep=None,
        canonical_scalp_order=None, recorded_channel_geometry=True,
        kurtosis_screening_supported=False, strict_processing_errors=True,
        geometry_fingerprint="test", stim_channel="Trigger", event_encoding="sample",
        required_sfreq=250.0, resampling_allowed=False, interpolation_allowed=False,
    )
    return raw


def test_sample_markers_preserve_first_sample_and_adjacent_equal_codes():
    raw = _recording()
    expected = np.array([[71, 0, 3], [72, 0, 3], [74, 0, 55], [75, 0, 55], [77, 0, 2]])
    np.testing.assert_array_equal(canonical_recording_events(raw), expected)
    np.testing.assert_array_equal(canonical_recording_events(raw.copy()), expected)


@pytest.mark.parametrize("bad_value", [0.5, np.nan, np.inf, -1, 256])
def test_invalid_sample_values_never_use_edge_detection(bad_value, monkeypatch):
    raw = _recording([0, bad_value, 0])
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: pytest.fail("edge fallback"))
    with pytest.raises(RecordingEventError):
        canonical_recording_events(raw)


def test_explicit_annotation_authority_and_empty_authority_do_not_read_status():
    raw = _recording()
    raw._fpvs_canonical_events = np.array([[73, 0, 9], [74, 0, 9]], dtype=np.int64)
    raw._fpvs_canonical_events_sfreq = 250.0
    np.testing.assert_array_equal(canonical_recording_events(raw), raw._fpvs_canonical_events)
    returned = canonical_recording_events(raw)
    returned[0, 2] = 5
    assert raw._fpvs_canonical_events[0, 2] == 9
    raw._fpvs_canonical_events = np.empty((0, 3), dtype=np.int64)
    assert canonical_recording_events(raw).shape == (0, 3)


@pytest.mark.parametrize("events", [
    [[71.0, 0, 1]], [[70, 0, 1]], [[78, 0, 1]], [[71, 0, 1], [71, 0, 1]],
    [[72, 0, 1], [71, 0, 2]], [[71, 1, 2]], [[71, 0, 0]], [71, 0, 1],
])
def test_malformed_admitted_markers_fail_closed(events):
    raw = _recording()
    raw._fpvs_canonical_events = np.asarray(events)
    raw._fpvs_canonical_events_sfreq = 250.0
    with pytest.raises(RecordingEventError):
        canonical_recording_events(raw)


def test_canonical_markers_reject_changed_native_grid():
    raw = _recording()
    raw._fpvs_canonical_events = canonical_recording_events(raw)
    raw._fpvs_canonical_events_sfreq = 250.0
    with pytest.warns(RuntimeWarning, match="event information"):
        raw.resample(125, verbose=False)
    with pytest.raises(RecordingEventError, match="native sampling grid"):
        canonical_recording_events(raw)


def test_historical_edge_route_remains_delegated():
    raw = _recording()
    raw._fpvs_recording_contract = replace(raw._fpvs_recording_contract, event_encoding="edge")
    assert canonical_recording_events(raw) is None
    assert snapshot_canonical_event_metadata(raw, cache_key="unchanged") is None
    del raw._fpvs_recording_contract
    assert canonical_recording_events(raw) is None


@pytest.mark.parametrize("consumer", ["preflight", "review", "runner", "export"])
def test_production_event_consumers_preserve_same_native_sequence(consumer, monkeypatch):
    from Main_App.exports import post_process
    from Main_App.io import load_utils
    from Main_App.processing import kurtosis_review_scan, preflight_qc
    from Main_App.workers import process_runner

    raw = _recording()
    expected = canonical_recording_events(raw)
    monkeypatch.setattr(mne, "find_events", lambda *_args, **_kwargs: pytest.fail("edge fallback"))
    monkeypatch.setattr(mne, "events_from_annotations", lambda *_args, **_kwargs: pytest.fail("annotation fallback"))
    if consumer == "preflight":
        actual, source = preflight_qc._find_preflight_events(raw, stim_channel="Trigger")
    elif consumer == "review":
        actual, source = kurtosis_review_scan._find_raw_events(raw, stim_channel="Trigger")
    elif consumer == "runner":
        actual, source = process_runner._find_raw_events(raw, mne_module=mne, stim_channel="Trigger")
    else:
        @contextmanager
        def opened(*_args, **_kwargs):
            yield raw
        monkeypatch.setattr(load_utils, "open_preflight_eeg_file", opened)
        actual, count = post_process._load_events_for_file(
            "recording", {"Condition": 3}, "Trigger", app=SimpleNamespace(settings={}),
        )
        assert count == raw.n_times
        source = "canonical"
    assert source == "canonical"
    np.testing.assert_array_equal(actual, expected)


def test_canonical_cache_metadata_roundtrip_and_corruption_rejection():
    raw = _recording()
    expected = canonical_recording_events(raw)
    metadata = snapshot_canonical_event_metadata(raw, cache_key="file-and-settings")
    restored = _recording([0] * raw.n_times)
    restore_canonical_event_metadata(restored, metadata, cache_key="file-and-settings")
    np.testing.assert_array_equal(canonical_recording_events(restored), expected)
    metadata["events"][1][2] = 99
    with pytest.raises(RecordingEventError, match="does not match"):
        restore_canonical_event_metadata(restored, metadata, cache_key="file-and-settings")


@pytest.mark.parametrize("changed", ["cache_key", "rate", "count", "missing"])
def test_canonical_cache_metadata_must_match_recording(changed):
    raw = _recording()
    metadata = snapshot_canonical_event_metadata(raw, cache_key="original")
    key = "original"
    if changed == "cache_key":
        key = "other"
    elif changed == "rate":
        metadata["sfreq"] = 125.0
    elif changed == "count":
        metadata["n_times"] += 1
    else:
        metadata = None
    with pytest.raises(RecordingEventError):
        restore_canonical_event_metadata(raw, metadata, cache_key=key)


def test_preflight_source_cache_preserves_canonical_origin_and_adjacent_markers(monkeypatch, tmp_path):
    from Main_App.processing import preflight_qc_reuse

    expected = canonical_recording_events(_recording())
    monkeypatch.setattr(
        preflight_qc_reuse, "load_preflight_qc_cache",
        lambda *_args, **_kwargs: {"events": expected.tolist(), "source": "canonical"},
    )
    actual, source = preflight_qc_reuse.load_source_events(
        tmp_path, event_plan={"first_samp": 71, "n_times": 7},
    )
    assert source == "canonical"
    np.testing.assert_array_equal(actual, expected)
