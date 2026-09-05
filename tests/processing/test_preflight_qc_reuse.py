"""Exact evidence reuse without carrying forward review authority."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import struct

import numpy as np
import pytest

import Main_App.processing.preflight_qc as qc
from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
from Main_App.processing.preflight_qc_cache import preflight_qc_cache_directory
from Main_App.processing.preflight_qc_reuse import decode_evidence, encode_evidence
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol, RawSpectralScreeningSettings


def _settings():
    return {
        "stim_channel": "Status", "ref_channel1": "EXG1", "ref_channel2": "EXG2",
        "high_pass": 0.1, "low_pass": 50.0, "downsample": 256,
        "manual_removed_electrodes_enabled": True,
        "frequency_protocol": FrequencyProtocol.from_recurrence(
            6, 5, expected_analyzed_oddball_cycles=3,
            expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
        ),
    }


@pytest.fixture
def scan_fixture(monkeypatch, tmp_path):
    names = list(BIOSEMI64_CHANNELS) + ["Status"]
    data = np.random.default_rng(88).normal(0, 90e-6, (len(names), 5000))
    data[0, 301:330] = 0.0
    data[2, 2210:2225] = 8e-3
    events = np.array([
        [100, 0, 1], [300, 0, 55], [513, 0, 55], [727, 0, 55], [940, 0, 55],
        [2000, 0, 2], [2200, 0, 55], [2413, 0, 55], [2627, 0, 55], [2840, 0, 55],
    ], dtype=np.int64)
    reads = []
    event_reads = []

    class Raw:
        info = {"sfreq": 256.0}
        ch_names = names
        n_times = data.shape[1]
        first_samp = 0

        def get_data(self, *, picks, start, stop, **_kwargs):
            reads.append((self.path.name, start, stop))
            return data[np.asarray(picks), start:stop]

    @contextmanager
    def open_raw(_log, path, **_kwargs):
        raw = Raw()
        raw.path = Path(path)
        yield raw

    def find_events(raw, **_kwargs):
        event_reads.append(raw.path.name)
        return events.copy()

    monkeypatch.setattr(qc.load_utils, "inspect_bdf_header", lambda _path: None)
    monkeypatch.setattr(qc.load_utils, "open_preflight_eeg_file", open_raw)
    monkeypatch.setattr(qc.mne, "find_events", find_events)
    paths = [tmp_path / "P1.bdf", tmp_path / "P9.bdf"]
    for path in paths:
        path.write_bytes(b"source recording identity")

    def scan(settings=None, *, participants=("P1",), root=None):
        result = qc.scan_preprocessing_qc(
            [RawFileInfo(tmp_path / f"{pid}.bdf", pid, "control", recording_id=f"{pid}-r1") for pid in participants],
            settings or _settings(), project_root=root or tmp_path,
            event_map={"Faces": 1, "Objects": 2},
        )
        assert not result.cancelled
        assert all(item.load_error is None for item in result.results)
        return result

    return scan, reads, event_reads, paths, events


def _without_runtime(value):
    if isinstance(value, dict):
        ignored = {
            "cache_status", "event_cache_status", "occurrence_cache_hits", "timings_ms",
            "samples_read_per_channel", "disk_buffered_condition_count",
        }
        return {key: _without_runtime(item) for key, item in value.items() if key not in ignored}
    if isinstance(value, (tuple, list)):
        return [_without_runtime(item) for item in value]
    return value


def _assert_same_evidence(left, right):
    # The encoder compares the IEEE bits of each float, not an allclose tolerance.
    assert encode_evidence(left.raw_channel_qc) == encode_evidence(right.raw_channel_qc)
    assert encode_evidence(left.raw_spectral_qc) == encode_evidence(right.raw_spectral_qc)
    assert _without_runtime(left.condition_qc) == _without_runtime(right.condition_qc)


def test_other_participant_choices_keep_p1_full_cache_and_source_events(scan_fixture):
    scan, reads, event_reads, _paths, _events = scan_fixture
    first = scan().results[0]
    settings = _settings()
    settings.update(
        manual_excluded_participant_conditions={"P9": ["Objects"]},
        manual_excluded_recording_conditions={"P9-r1": ["Faces"]},
        manual_removed_electrodes={"P9": ["P9"]},
        manual_removed_electrodes_by_recording={"P9-r1": ["P10"]},
    )
    second = scan(settings).results[0]
    assert len(reads) == 2
    assert event_reads == ["P1.bdf"]
    assert second.condition_qc["cache_status"] == "hit"
    _assert_same_evidence(first, second)


def test_excluding_one_condition_reuses_other_occurrence_and_matches_cold(scan_fixture, tmp_path):
    scan, reads, event_reads, _paths, _events = scan_fixture
    scan()
    settings = _settings()
    settings["manual_excluded_recording_conditions"] = {"P1-r1": ["Faces"]}
    second = scan(settings).results[0]
    assert len(reads) == 2
    assert event_reads == ["P1.bdf"]
    assert second.condition_qc["occurrence_cache_hits"] == 1
    assert second.condition_qc["samples_read_per_channel"] == 0
    assert [item["condition_id"] for item in second.raw_channel_qc["conditions"]] == ["Objects"]
    cold = scan(settings, root=tmp_path / "cold-project").results[0]
    _assert_same_evidence(second, cold)


def test_reaggregation_all_cached_occurrences_is_bitwise_equal(scan_fixture, tmp_path):
    scan, reads, event_reads, _paths, _events = scan_fixture
    first = scan().results[0]
    for path in preflight_qc_cache_directory(tmp_path).glob("*.json"):
        path.unlink()
    second = scan().results[0]
    assert len(reads) == 2
    assert event_reads == ["P1.bdf"]
    assert second.condition_qc["occurrence_cache_hits"] == 2
    _assert_same_evidence(first, second)


def test_one_changed_exact_span_reuses_the_other(scan_fixture, tmp_path):
    scan, reads, _event_reads, _paths, events = scan_fixture
    scan()
    # Inject a fresh event-reader result to exercise current-plan reaggregation;
    # real source modifications are separately tested to invalidate every entry.
    events[:5, 0] += 1
    for path in preflight_qc_cache_directory(tmp_path, namespace="events").glob("*.json"):
        path.unlink()
    second = scan().results[0]
    assert reads[-1] == ("P1.bdf", 301, 941)
    assert len(reads) == 3
    assert second.condition_qc["occurrence_cache_hits"] == 1


def test_current_marker_provenance_wraps_reused_numerical_evidence(scan_fixture, monkeypatch):
    scan, reads, _event_reads, _paths, _events = scan_fixture
    first = scan().results[0]
    original = qc.plan_preflight_qc_events

    def reviewed_plan(**kwargs):
        plan = original(**kwargs)
        return replace(plan, spans=tuple(replace(span, approved_span_fingerprint="current-review") for span in plan.spans))

    monkeypatch.setattr(qc, "plan_preflight_qc_events", reviewed_plan)
    second = scan().results[0]
    assert len(reads) == 2
    assert second.condition_qc["occurrence_cache_hits"] == 2
    assert all(item["approved_span_fingerprint"] == "current-review" for item in second.raw_spectral_qc["condition_results"])
    assert second.raw_spectral_qc != first.raw_spectral_qc


def test_changed_source_reloads_exact_mne_events(scan_fixture):
    scan, reads, event_reads, paths, events = scan_fixture
    first = scan().results[0]
    paths[0].write_bytes(b"changed source recording identity")
    second = scan().results[0]
    assert len(reads) == 4
    assert event_reads == ["P1.bdf", "P1.bdf"]
    assert second.condition_qc["event_plan"]["event_digest"] == first.condition_qc["event_plan"]["event_digest"]
    assert events[:, 0].tolist() == [100, 300, 513, 727, 940, 2000, 2200, 2413, 2627, 2840]


@pytest.mark.parametrize("change", ["threshold", "spectral_policy", "method", "protocol", "geometry", "manual"])
def test_numerical_settings_changes_recompute_occurrences(scan_fixture, monkeypatch, change):
    scan, reads, _event_reads, _paths, _events = scan_fixture
    scan()
    settings = _settings()
    if change == "threshold":
        settings["max_bad_chans"] = 2
    elif change == "spectral_policy":
        settings["raw_spectral_screening"] = RawSpectralScreeningSettings(enabled=False).to_manifest()
    elif change == "method":
        monkeypatch.setattr(qc, "CONDITION_RAW_CHANNEL_QC_METHOD_VERSION", "new-method")
    elif change == "protocol":
        settings["frequency_protocol"] = FrequencyProtocol.from_recurrence(
            12, 10, expected_analyzed_oddball_cycles=3,
            expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
        )
    elif change == "geometry":
        settings["max_idx_keep"] = 63
    else:
        settings["manual_removed_electrodes_by_recording"] = {"P1-r1": ["P9"]}
    second = scan(settings).results[0]
    assert len(reads) == 4
    assert second.condition_qc["occurrence_cache_hits"] == 0


@pytest.mark.parametrize("namespace", ["events", "occurrences", ""])
def test_corrupt_cache_payload_recomputes_safely(scan_fixture, tmp_path, namespace):
    scan, reads, event_reads, _paths, _events = scan_fixture
    first = scan().results[0]
    for path in preflight_qc_cache_directory(tmp_path).glob("*.json"):
        if namespace:
            path.unlink()  # Force lower-stage lookup.
    directory = preflight_qc_cache_directory(tmp_path, namespace=namespace)
    for path in directory.glob("*.json"):
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["result"] = {"invalid": "checksum no longer matches"}
        path.write_text(json.dumps(envelope), encoding="utf-8")
    second = scan().results[0]
    _assert_same_evidence(first, second)
    if namespace == "events":
        assert len(event_reads) == 2
    elif namespace == "occurrences":
        assert len(reads) == 4


def test_float_evidence_codec_preserves_nan_payload_signed_zero_and_infinities():
    patterns = ["8000000000000000", "0000000000000000", "7ff8000000000123", "7ff0000000000000", "fff0000000000000"]
    source = tuple(struct.unpack(">d", bytes.fromhex(pattern))[0] for pattern in patterns)
    restored = decode_evidence(json.loads(json.dumps(encode_evidence(source))))
    assert [struct.pack(">d", value).hex() for value in restored] == patterns


def test_unknown_evidence_dataclass_is_rejected():
    with pytest.raises(KeyError):
        decode_evidence({"dataclass": "UnapprovedObject", "fields": {}})


def test_disabled_spectral_policy_reuses_the_recorded_disabled_result(scan_fixture):
    scan, reads, _event_reads, _paths, _events = scan_fixture
    settings = _settings()
    settings["raw_spectral_screening"] = RawSpectralScreeningSettings(enabled=False).to_manifest()
    scan(settings)
    settings["manual_excluded_recording_conditions"] = {"P1-r1": ["Objects"]}
    result = scan(settings).results[0]
    assert len(reads) == 2
    assert result.condition_qc["occurrence_cache_hits"] == 1
    assert result.raw_spectral_qc["evaluation_status"] == "not_performed_disabled"


def test_cancellation_never_publishes_partial_occurrence_evidence(scan_fixture, tmp_path):
    scan, _reads, event_reads, paths, _events = scan_fixture
    cancelled = False

    def progress(message, _done, _total):
        nonlocal cancelled
        if "checking exact on-bin spectrum" in message:
            cancelled = True

    result = qc.scan_preprocessing_qc(
        [RawFileInfo(paths[0], "P1", "control", recording_id="P1-r1")],
        _settings(), project_root=tmp_path, event_map={"Faces": 1, "Objects": 2},
        progress=progress, should_cancel=lambda: cancelled,
    )
    assert result.cancelled
    assert not list(preflight_qc_cache_directory(tmp_path, namespace="occurrences").glob("*.json"))
    assert not list(preflight_qc_cache_directory(tmp_path).glob("*.json"))
    # The completed source-event entry is safe; resuming still computes evidence.
    resumed = scan().results[0]
    assert event_reads == ["P1.bdf"]
    assert resumed.condition_qc["occurrence_cache_hits"] == 0


def test_source_change_during_read_cannot_publish_event_or_qc_cache(scan_fixture, monkeypatch, tmp_path):
    _scan, _reads, _event_reads, paths, _events = scan_fixture
    original = qc._find_preflight_events

    def changed_source(*args, **kwargs):
        result = original(*args, **kwargs)
        paths[0].write_bytes(b"changed while event reader was running")
        return result

    monkeypatch.setattr(qc, "_find_preflight_events", changed_source)
    result = qc.scan_preprocessing_qc(
        [RawFileInfo(paths[0], "P1", "control", recording_id="P1-r1")],
        _settings(), project_root=tmp_path, event_map={"Faces": 1, "Objects": 2},
    )
    assert "source recording changed" in result.results[0].load_error
    assert not list(preflight_qc_cache_directory(tmp_path).rglob("*.json"))
