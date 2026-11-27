"""Read a selected Net Station MFF v3 event track on its continuous EEG sample grid.

The source track is authoritative. MNE 1.9's dense trigger channels cannot
represent two occurrences of the same named event at the same sample.
Only block headers are read from the EEG stream. This event inspection never
registers EEG, constructs a processing Raw, or changes the recording.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import struct
from xml.etree import ElementTree as ET

from .recording_events import RecordingEventError


@dataclass(frozen=True)
class MffDinEvent:
    source_order: int
    source_code: str
    source_label: str | None
    begin_time: str
    onset_ns: int
    duration: int
    sample: int
    studio_code: int | None


@dataclass(frozen=True)
class MffDinInspection:
    track: str
    record_time: str
    amp_type: str | None
    acquisition_version: str | None
    sampling_rate_hz: int
    sample_count: int
    events: tuple[MffDinEvent, ...]


class _MffTreeBuilder(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise RecordingEventError("DTD declarations are unsupported in MFF metadata.")


def _member(root: Path, name: str) -> Path:
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise RecordingEventError(f"MFF member is outside the recording or is not a file: {name}")
    return path


def _xml(root: Path, name: str, tag: str) -> ET.Element:
    parser = ET.XMLParser(target=_MffTreeBuilder())
    element = ET.parse(_member(root, name), parser=parser).getroot()
    if element.tag.rsplit("}", 1)[-1] != tag:
        raise RecordingEventError(f"Expected {tag} in {name}.")
    return element


def _text(element: ET.Element, field: str) -> str:
    entries = element.findall("{*}" + field)
    value = entries[0].text if len(entries) == 1 else None
    if value is None or not value.strip():
        raise RecordingEventError(f"Expected one nonempty MFF {field}.")
    return value


_TIMESTAMP = re.compile(
    r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.(\d{6}|\d{9})(Z|[+-]\d\d:\d\d)"
)


def _timestamp_ns(value: str) -> tuple[int, int]:
    match = _TIMESTAMP.fullmatch(value)
    if not match:
        raise RecordingEventError(f"Unsupported MFF timestamp: {value!r}")
    seconds, fraction, offset = match.groups()
    base = datetime.fromisoformat(seconds + ("+00:00" if offset == "Z" else offset))
    delta = base - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta // timedelta(seconds=1)) * 10**9 + int(fraction.ljust(9, "0")), len(fraction)


def _eeg_grid(path: Path) -> tuple[int, int, int]:
    """Count complete blocks using MFF's little-endian float32 block headers."""
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        rate = block_bytes = block_samples = blocks = samples = 0
        while (start := stream.tell()) < size:
            flag, = struct.unpack("<I", stream.read(4))
            if flag == 1:
                header_bytes, block_bytes, channels = struct.unpack("<III", stream.read(12))
                if (
                    not channels or not block_bytes or block_bytes % (channels * 4)
                    or not 16 + channels * 8 <= header_bytes <= size - start - block_bytes
                ):
                    raise RecordingEventError("Invalid or truncated EEG block header.")
                block_samples = block_bytes // (channels * 4)
                # Each equal-rate channel owns a consecutive float32 sample array.
                # Read both header tables incrementally; their counts come from the file.
                for offset_bytes in range(0, block_bytes, block_samples * 4):
                    if struct.unpack("<I", stream.read(4))[0] != offset_bytes:
                        raise RecordingEventError("Unsupported EEG channel offsets for a uniform sample grid.")
                first_format, = struct.unpack("<I", stream.read(4))
                block_rate, depth = divmod(first_format, 256)
                if (
                    not block_rate or depth != 32 or (rate and rate != block_rate)
                    or any(struct.unpack("<I", stream.read(4))[0] != first_format for _ in range(1, channels))
                ):
                    raise RecordingEventError("Unsupported EEG sample rate or sample encoding.")
                rate = block_rate
                stream.seek(start + header_bytes)
            elif flag != 0 or blocks == 0:
                raise RecordingEventError("Unsupported EEG block type or missing first block header.")
            if stream.tell() + block_bytes > size:
                raise RecordingEventError("Truncated EEG signal block.")
            stream.seek(block_bytes, os.SEEK_CUR)
            blocks += 1
            samples += block_samples
    if not blocks:
        raise RecordingEventError("MFF EEG stream is empty.")
    return rate, samples, blocks


def read_mff_din_events(
    path: str | Path, *, track: str, code_map: Mapping[str, int]
) -> MffDinInspection:
    """Keep every event in XML order, including unmapped rows and sample ties.

    Sample is the zero-based interval containing the recorded onset. onset_ns
    retains the precise offset within the recording. duration is the original
    XML integer, without assumptions about pulse duration on the wire.
    """
    if not isinstance(track, str) or not re.fullmatch(r"Events_[^/\\:]+\.xml", track):
        raise RecordingEventError("Select an Events_*.xml filename within the MFF recording.")
    if not isinstance(code_map, Mapping) or any(
        not isinstance(key, str) or not key.strip() or type(value) is not int or not 1 <= value <= 255
        for key, value in code_map.items()
    ):
        raise RecordingEventError("Map exact MFF source codes to Studio integers in 1..255.")
    root = Path(path).resolve()
    if root.suffix.lower() != ".mff" or not root.is_dir():
        raise RecordingEventError("Select an unpacked .mff directory.")
    try:
        info = _xml(root, "info.xml", "fileInfo")
        if _text(info, "mffVersion") != "3":
            raise RecordingEventError("Only continuous MFF v3 recordings are supported.")
        record_time = _text(info, "recordTime")
        origin_ns, precision = _timestamp_ns(record_time)
        signal_info = _xml(root, "info1.xml", "dataInfo")
        if signal_info.find(".//{*}fileDataType/{*}EEG") is None:
            raise RecordingEventError("Expected the EEG stream in signal1.bin.")
        epochs = _xml(root, "epochs.xml", "epochs").findall("{*}epoch")
        if (
            len(epochs) != 1 or int(_text(epochs[0], "beginTime")) != 0
            or (root / "categories.xml").exists()
        ):
            raise RecordingEventError("Event inspection requires one continuous, unsegmented EEG epoch.")
        rate, samples, blocks = _eeg_grid(_member(root, "signal1.bin"))
        epoch = epochs[0]
        if (
            int(_text(epoch, "endTime")) * rate != samples * 10**precision
            or int(_text(epoch, "firstBlock")) != 1 or int(_text(epoch, "lastBlock")) != blocks
        ):
            raise RecordingEventError("Epoch timing or block range disagrees with the EEG sample grid.")
        events = []
        for order, event in enumerate(_xml(root, track, "eventTrack").findall("{*}event")):
            code = _text(event, "code")
            begin = _text(event, "beginTime")
            onset_ns = _timestamp_ns(begin)[0] - origin_ns
            sample = onset_ns * rate // 10**9
            duration = int(_text(event, "duration"))
            if not 0 <= sample < samples or duration < 0:
                raise RecordingEventError(f"Invalid onset or duration for event {order} ({code!r}).")
            events.append(MffDinEvent(
                order, code, event.findtext("{*}label"), begin, onset_ns, duration,
                sample, code_map.get(code),
            ))
    except RecordingEventError:
        raise
    except (ValueError, OSError, ET.ParseError, struct.error) as exc:
        raise RecordingEventError(f"Cannot inspect MFF event metadata: {exc}") from exc
    return MffDinInspection(
        track, record_time, info.findtext("{*}ampType"), info.findtext("{*}acquisitionVersion"),
        rate, samples, tuple(events),
    )
