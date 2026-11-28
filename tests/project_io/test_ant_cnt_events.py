"""Exercise the native ANT reader through its marker-only inspection boundary."""
from hashlib import sha256
import subprocess

import pytest

from Main_App.io.ant_cnt_events import _event, read_ant_cnt_events
from Main_App.io.recording_events import RecordingEventError
from tests.fixtures.ant_cnt import write_ant_fixture


@pytest.mark.parametrize("rf64", [True, False])
def test_native_cnt_keeps_source_order_duplicates_codes_and_grid(tmp_path, rf64):
    rows = [("1", 40), ("55", 101), ("55", 101), ("128", 101), ("255", 110), ("55", 405),
            ("Rs", 310), ("__", 310), ("256", 500), ("0", 510), ("opaque", 600)]
    path = write_ant_fixture(tmp_path / "run.cnt", rows, rf64=rf64)
    before = sha256(path.read_bytes()).digest()
    result = read_ant_cnt_events(path)
    assert result.container == ("RF64" if rf64 else "RIFF")
    assert (result.sample_count, result.sampling_rate_hz, result.companion_files) == (2000, 1000, ())
    assert [(e.source_code, e.sample) for e in result.events] == rows
    assert [e.source_order for e in result.events] == list(range(len(rows)))
    assert [e.studio_code for e in result.events] == [1, 55, 55, 128, 255, 55, None, None, None, None, None]
    assert [e.kind for e in result.events] == ["stimulus"] * 6 + ["recorder"] * 2 + ["unclassified"] * 3
    assert [e.onset_ns for e in result.events] == [sample * 1_000_000 for _code, sample in rows]
    assert sha256(path.read_bytes()).digest() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("rf64", [True, False])
def test_mne_ant_reader_agrees_on_native_stimulus_codes_and_samples(tmp_path, rf64):
    from mne.io import read_raw_ant

    rows = [("1", 8), ("55", 120), ("55", 120), ("128", 120), ("255", 245)]
    path = write_ant_fixture(tmp_path / "markers.cnt", rows, rf64=rf64)
    with read_raw_ant(path, preload=False, verbose="ERROR") as raw:
        samples = raw.time_as_index(raw.annotations.onset, use_rounding=True)
        assert list(zip(raw.annotations.description, samples, strict=True)) == rows


@pytest.mark.parametrize("code,condition,description,impedances,kind", [
    ("0", None, "Impedance", "3 4", "recorder"),
    ("9001", "Amplifier disconnected", None, None, "recorder"),
    ("9002", "Amplifier reconnected", None, None, "recorder"),
    ("1000", "user-annot", None, None, "recorder"),
    ("55", "unknown condition", None, None, "unclassified"),
    ("55", None, "unknown label", None, "unclassified"),
])
def test_extended_cnt_rows_preserve_recorder_metadata(code, condition, description, impedances, kind):
    row = _event(0, [code, 8, 12, condition, description, impedances], 500, 1024)
    assert row.studio_code is None and row.kind == kind
    assert (row.condition, row.description, row.impedance) == (condition, description, impedances)
    assert (row.sample, row.duration_samples, row.onset_ns) == (8, 12, 16_000_000)


def test_unrelated_cnt_and_truncated_recording_rejected_before_native_read(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Cannot route an incompatible file into libeep.")

    monkeypatch.setattr(subprocess, "run", unexpected)
    path = tmp_path / "neuroscan.cnt"
    path.write_bytes(b"Version 3.0" + bytes(100))
    with pytest.raises(RecordingEventError, match="Neuroscan"):
        read_ant_cnt_events(path)
    path = write_ant_fixture(tmp_path / "truncated.cnt", [("55", 100)])
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(RecordingEventError, match="Incomplete"):
        read_ant_cnt_events(path)


def test_failed_native_reader_does_not_return_a_partial_match(tmp_path, monkeypatch):
    path = write_ant_fixture(tmp_path / "rejected.cnt", [])
    failure = subprocess.CompletedProcess([], 1, b"", b"cannot open recording")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: failure)
    with pytest.raises(RecordingEventError, match="cannot open recording"):
        read_ant_cnt_events(path)


def test_out_of_grid_event_is_rejected(tmp_path):
    path = write_ant_fixture(tmp_path / "bad-event.cnt", [("1", 2000)])
    with pytest.raises(RecordingEventError, match="invalid sample"):
        read_ant_cnt_events(path)


def test_cnt_reader_uses_original_companion_with_native_precedence(tmp_path):
    path = write_ant_fixture(tmp_path / "with-companion.cnt", [("9", 700)])
    companion = path.with_suffix(".trg")
    companion.write_text("0.001 6\n0.010 1\n0.020 55\n0.020 55\n", encoding="ascii")
    before = {source: sha256(source.read_bytes()).digest() for source in (path, companion)}
    result = read_ant_cnt_events(path)
    assert result.companion_files == (companion.name,)
    assert [(e.studio_code, e.sample) for e in result.events] == [(1, 10), (55, 20), (55, 20)]
    assert {source: sha256(source.read_bytes()).digest() for source in (path, companion)} == before


def test_case_sensitive_native_extension_handling(tmp_path):
    path = write_ant_fixture(tmp_path / "upper.CNT", [("1", 40)])
    if path.with_suffix(".cnt").exists():
        assert read_ant_cnt_events(path).events[0].studio_code == 1
    else:
        with pytest.raises(RecordingEventError, match="lowercase"):
            read_ant_cnt_events(path)


def test_case_sensitive_companion_is_not_silently_ignored(tmp_path):
    path = write_ant_fixture(tmp_path / "upper.cnt", [("9", 700)])
    companion = path.with_suffix(".TRG")
    companion.write_text("0.001 6\n0.010 1\n", encoding="ascii")
    if path.with_suffix(".trg").exists():
        result = read_ant_cnt_events(path)
        assert result.companion_files == (companion.name,)
        assert [(e.studio_code, e.sample) for e in result.events] == [(1, 10)]
    else:
        with pytest.raises(RecordingEventError, match="lowercase"):
            read_ant_cnt_events(path)


@pytest.mark.parametrize("suffix,payload", [
    (".evt", b""), (".evt", b"not an event library"), (".seg", b""), (".trg", b"bogus"),
    (".seg", b"NumberSegments=3\n43831 0.0 450\n"), (".seg", b"NumberSegments=2\n43831 nan 450\n"),
    (".trg", b"0.001 6\ngarbage\n"), (".trg", b"0.002 6\n0.1 55\n"),
    (".trg", b"0.001 6\n0.2 55\n0.1 1\n"),
])
def test_invalid_companion_cannot_pass_through_matching_embedded_marker(tmp_path, suffix, payload):
    path = write_ant_fixture(tmp_path / "recorded.cnt", [("55", 100)])
    path.with_suffix(suffix).write_bytes(payload)
    with pytest.raises(RecordingEventError):
        read_ant_cnt_events(path)
