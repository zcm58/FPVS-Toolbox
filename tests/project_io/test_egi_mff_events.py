"""Read-only event inspection, independent of processing and montage admission."""
import hashlib
from pathlib import Path
import struct

import pytest

from Main_App.io.egi_mff_events import read_mff_din_events
from Main_App.io.recording_events import RecordingEventError
from tests.fixtures.egi_mff import write_mff_fixture

TRACK = "Events_255 DINs.xml"
MAPPING = {"DIN1": 23, "DI55": 55}


def _inspect(path):
    return read_mff_din_events(path, track=TRACK, code_map=MAPPING)


def _snapshot(path):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir()}


def test_mff_inspection_preserves_source_ties_and_raw_names(tmp_path):
    recording = write_mff_fixture(tmp_path / "case.mff", [
        ("DI55", 0), ("DIN1", 1_234_567), ("DI55", 1_234_567),
        ("DI55", 1_234_567), ("DI55", 2_000_000), ("unmapped", 1_999_999_999),
    ])
    before = _snapshot(recording)
    result = _inspect(recording)
    assert result.sampling_rate_hz == 1000 and result.sample_count == 2000
    assert result.record_time == "2020-01-01T00:00:00.000000+00:00"
    assert [row.studio_code for row in result.events] == [55, 23, 55, 55, 55, None]
    assert [row.source_code for row in result.events] == ["DI55", "DIN1", "DI55", "DI55", "DI55", "unmapped"]
    assert [row.sample for row in result.events] == [0, 1, 1, 1, 2, 1999]
    assert [row.source_order for row in result.events] == list(range(6))
    assert result.events[1].source_label == "Recorded DIN1"
    assert result.events[1].onset_ns == 1_234_567
    assert result.events[1].begin_time.endswith("00.001234567+00:00")
    assert result.events[1].duration == 0
    assert _snapshot(recording) == before


@pytest.mark.parametrize("onset_ns", [-1, 2_000_000_000])
def test_out_of_bounds_event_is_reported(tmp_path, onset_ns):
    recording = write_mff_fixture(tmp_path / "case.mff", [("DIN1", onset_ns)])
    with pytest.raises(RecordingEventError, match="onset"):
        _inspect(recording)


def test_handles_timezone_change_and_preserves_source_order(tmp_path):
    recording = write_mff_fixture(tmp_path / "case.mff", [("DIN1", 5_000_000), ("DI55", 4_000_000)])
    events = recording / TRACK
    events.write_text(events.read_text().replace("T00:00:", "T01:00:").replace("+00:00", "+01:00"))
    assert [(row.studio_code, row.sample) for row in _inspect(recording).events] == [(23, 5), (55, 4)]


def test_nanosecond_epoch_and_timestamp_preserve_duration(tmp_path):
    recording = write_mff_fixture(tmp_path / "case.mff", [("DIN1", 4_000_001)])
    info = recording / "info.xml"
    info.write_text(info.read_text().replace(".000000+00:00", ".000000001Z"))
    epochs = recording / "epochs.xml"
    epochs.write_text(epochs.read_text().replace(">2000000<", ">2000000000<"))
    events = recording / TRACK
    events.write_text(events.read_text().replace("<duration>0<", "<duration>1000<"))
    event, = _inspect(recording).events
    assert (event.onset_ns, event.sample, event.duration) == (4_000_000, 4, 1000)


@pytest.mark.parametrize(("block_samples", "blocks", "end_us", "valid"), [
    (519, 2, 2_027_342, True),   # Native writer truncates each block to microseconds.
    (519, 2, 2_027_343, True),   # Writer truncates the complete epoch once.
    (519, 2, 2_027_341, False),  # Neither representation matches the source grid.
    (7, 3000, 13_671 * 3000, False),  # Accumulated truncation exceeds a whole sample.
])
def test_fractional_sample_period_keeps_exact_grid_and_last_sample(tmp_path, block_samples, blocks, end_us, valid):
    rate = 512
    last_ns = (blocks * block_samples * 10**9 - 1) // rate
    recording = write_mff_fixture(tmp_path / "clock.mff", [("DIN1", last_ns)])
    size = block_samples * 4
    first_header = struct.pack("<7I", 1, 28, size, 1, 0, rate << 8 | 32, 0)
    (recording / "signal1.bin").write_bytes(first_header + bytes(size) + (bytes(4 + size) * (blocks - 1)))
    epochs = recording / "epochs.xml"
    epochs.write_text(epochs.read_text().replace("2000000<", f"{end_us}<")
                      .replace("<lastBlock>2<", f"<lastBlock>{blocks}<"))
    if valid:
        result = _inspect(recording)
        assert result.sample_count == block_samples * blocks
        assert (result.events[0].sample, result.events[0].onset_ns) == (result.sample_count - 1, last_ns)
    else:
        with pytest.raises(RecordingEventError, match="Epoch timing"):
            _inspect(recording)


@pytest.mark.parametrize(("filename", "old", "new", "message"), [
    ("epochs.xml", "<endTime>2000000", "<endTime>1000000", "disagrees"),
    ("epochs.xml", "<beginTime>0", "<beginTime>10", "continuous"),
    ("epochs.xml", "</epochs>", "<epoch/></epochs>", "continuous"),
    (TRACK, "<duration>0", "<duration>-5", "duration"),
    (TRACK, "<code>DIN1</code>", "", "code"),
    ("info.xml", "<fileInfo", "<!DOCTYPE fileInfo><fileInfo", "DTD"),
])
def test_invalid_mff_metadata_reports_discrepancy(tmp_path, filename, old, new, message):
    recording = write_mff_fixture(tmp_path / "case.mff", [("DIN1", 0)])
    file = recording / filename
    file.write_text(file.read_text().replace(old, new))
    with pytest.raises(RecordingEventError, match=message):
        _inspect(recording)


def test_incomplete_signal_and_external_track_are_rejected(tmp_path):
    recording = write_mff_fixture(tmp_path / "case.mff", [])
    file = recording / "signal1.bin"
    file.write_bytes(file.read_bytes()[:-4])
    with pytest.raises(RecordingEventError, match="Truncated"):
        _inspect(recording)
    with pytest.raises(RecordingEventError, match="filename"):
        read_mff_din_events(recording, track="../Events_Other.xml", code_map={})


@pytest.mark.parametrize(("byte_offset", "value", "message"), [
    (0, 0, "first block"),
    (16, 4, "offsets"),
    (20, 1000 * 256 + 16, "encoding"),
])
def test_invalid_eeg_grid_is_rejected(tmp_path, byte_offset, value, message):
    recording = write_mff_fixture(tmp_path / "case.mff", [("DIN1", 0)])
    with (recording / "signal1.bin").open("r+b") as stream:
        stream.seek(byte_offset)
        stream.write(struct.pack("<I", value))
    with pytest.raises(RecordingEventError, match=message):
        _inspect(recording)


@pytest.mark.parametrize("bad_map", [{"DIN1": 0}, {"DIN1": True}, {"": 2}, {"DIN1": 256}])
def test_rejects_ambiguous_config_before_read(tmp_path: Path, bad_map):
    with pytest.raises(RecordingEventError, match="1..255"):
        read_mff_din_events(tmp_path, track=TRACK, code_map=bad_map)
