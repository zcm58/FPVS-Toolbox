"""Inspect native ANT RIFF/RF64 CNT markers on their original sample grid."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Literal

from .recording_events import RecordingEventError

_CONNECTION_CHANGES = {"amplifier disconnected", "amplifier reconnected"}


@dataclass(frozen=True)
class AntCntEvent:
    source_order: int
    source_code: str
    sample: int
    onset_ns: int
    duration_samples: int
    condition: str | None
    description: str | None
    impedance: str | None
    kind: Literal["stimulus", "recorder", "unclassified"]
    studio_code: int | None


@dataclass(frozen=True)
class AntCntInspection:
    container: str
    reader_version: str
    amp_make: str
    amp_model: str
    sampling_rate_hz: int
    sample_count: int
    companion_files: tuple[str, ...]
    events: tuple[AntCntEvent, ...]
    timing_break_samples: tuple[int, ...] = ()


def _container(path: Path) -> str:
    # libeep can also open legacy Neuroscan files. Require the ANT form signature
    # before opening the native reader. Its RF64 uses an eight-byte root size.
    if path.suffix.lower() != ".cnt" or not path.is_file():
        raise RecordingEventError("Select a native ANT eego .cnt file.")
    with path.open("rb") as stream:
        header = stream.read(16)
        size = stream.seek(0, 2)
    tag = header[:4]
    width = 4 if tag == b"RIFF" else 8
    offset = 4 + width
    if tag not in (b"RIFF", b"RF64") or header[offset:offset + 4] != b"CNT ":
        raise RecordingEventError("Expected an ANT RIFF/RF64 CNT recording. Neuroscan CNT is unsupported.")
    if int.from_bytes(header[4:offset], "little") != size - offset:
        raise RecordingEventError("Incomplete ANT CNT container or inconsistent recording size.")
    return tag.decode("ascii")


def _event(order: int, row: list, rate: int, count: int) -> AntCntEvent:
    code, sample, duration, condition, description, impedance = row
    if not 0 <= sample < count or duration < 0:
        raise RecordingEventError(f"ANT event {order} has an invalid sample position or duration.")
    # eego Recorder uses code 1000 and a condition label for user annotations.
    # Embedded libeep codes '__' and 'Rs' mark a discontinuity and DC reset.
    kind: Literal["stimulus", "recorder", "unclassified"] = "unclassified"
    studio_code = None
    word = code.strip()
    state_change = (condition or "").casefold() in _CONNECTION_CHANGES
    if (impedance is not None or (description or "").casefold() == "impedance" or state_change
            or word in ("__", "Rs") or (word == "1000" and condition)):
        kind = "recorder"
    elif not condition and not description and word.isascii() and word.isdecimal() and 1 <= int(word) <= 255:
        kind, studio_code = "stimulus", int(word)
    return AntCntEvent(order, code, sample, (sample * 10**9 + rate // 2) // rate, duration,
                       condition, description, impedance, kind, studio_code)


def _later_segment_lengths(path: Path) -> list[int]:
    """The SEG table describes every recorded segment after the first."""
    try:
        with path.open("rb") as stream:
            key, count = stream.readline(1024).split(b"=", 1)
            segments = int(count)
            if key != b"NumberSegments" or segments < 1:
                raise ValueError
            lengths = []
            for row in stream:
                if row.strip():
                    date, fraction, n_samples = row.split()
                    length = int(n_samples)
                    if not all(math.isfinite(float(n)) for n in (date, fraction)) or length <= 0:
                        raise ValueError
                    lengths.append(length)
            if len(lengths) != segments - 1:
                raise ValueError
            return lengths
    except ValueError as exc:
        raise RecordingEventError(f"Incomplete or unrecognized ANT companion: {path.name}") from exc


def _check_companion(path: Path) -> tuple[float, int] | None:
    """Catch unreadable and incomplete companions before libeep silently falls back."""
    suffix = path.suffix.lower()
    with path.open("rb") as stream:
        if suffix == ".evt":
            # libeep expects a 24-byte header followed by the event library class.
            header = stream.read(64)
            if b"class dcEventsLibrary_c" not in header[28:]:
                raise RecordingEventError(f"Incomplete or unrecognized ANT event library: {path.name}")
            return None
        header = stream.readline(1024)
        try:
            period_field, block_size, *_ = header.split()
            period = float(period_field)
            if not math.isfinite(period) or period <= 0 or int(block_size) <= 0:
                raise ValueError
        except ValueError as exc:
            raise RecordingEventError(f"Incomplete or unrecognized ANT companion: {path.name}") from exc
        previous = -1.0
        row_count = 0
        for row in stream:
            fields = row.split()
            if not fields:
                continue
            try:
                onset = float(fields[0])
                if len(fields) < 2 or not math.isfinite(onset) or onset < 0:
                    raise ValueError
            except ValueError as exc:
                raise RecordingEventError(f"Invalid ANT .trg event time or label: {path.name}") from exc
            if onset < previous:
                raise RecordingEventError("The ANT reader would reorder this unsorted .trg companion.")
            previous = onset
            row_count += 1
        return period, row_count


def read_ant_cnt_events(path: str | Path) -> AntCntInspection:
    """Read the ANT reader's event table, including recorder annotations and ties.

    libeep searches for sibling .evt/.seg/.trg files using the original basename.
    Its event time is a sample index. onset_ns rounds that exact index/rate to
    nanoseconds and does not describe independent sub-sample observations.
    """
    path = Path(path).absolute()
    container = _container(path)
    if path.suffix != ".cnt":
        lowercase = path.with_suffix(".cnt")
        if not lowercase.exists() or not path.samefile(lowercase):
            raise RecordingEventError("antio requires a lowercase .cnt extension on case-sensitive filesystems.")
        path = lowercase
    expected = [path.with_suffix(ext) for ext in (".evt", ".seg", ".trg")]
    expected_names = {entry.name.casefold(): entry for entry in expected}
    companions = []
    trg_grid = None
    later_segments: list[int] = []
    for sibling in path.parent.iterdir():
        candidate = expected_names.get(sibling.name.casefold())
        if candidate is None:
            continue
        if not candidate.is_file() or not candidate.samefile(sibling):
            raise RecordingEventError(f"ANT companion must match the recording basename and lowercase extension: {sibling.name}")
        if candidate.suffix == ".seg":
            later_segments = _later_segment_lengths(sibling)
        else:
            grid = _check_companion(sibling)
            if grid is not None:
                trg_grid = grid
        companions.append(sibling.name)
    # libeep is native code. Keep parser failures outside the caller's process.
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).with_name("_ant_cnt_native.py")), str(path)],
            capture_output=True, timeout=120, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RecordingEventError("ANT marker inspection timed out while reading the recording.") from exc
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RecordingEventError(f"ANT reader failed (exit {result.returncode}). {detail}".rstrip())
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise RecordingEventError("The ANT reader did not return a valid event table.") from exc
    rate, count = data["sampling_rate_hz"], data["sample_count"]
    if rate <= 0 or count <= 0:
        raise RecordingEventError("The ANT recording has an empty or invalid sample grid.")
    if trg_grid is not None and not path.with_suffix(".evt").exists():
        period, row_count = trg_grid
        if not math.isclose(period * rate, 1, rel_tol=1e-5) or row_count != len(data["events"]):
            raise RecordingEventError("The ANT .trg companion disagrees with the native sample grid or event count.")
    events = tuple(_event(order, row, rate, count) for order, row in enumerate(data["events"]))
    breaks = {e.sample for e in events if e.source_code.strip() == "__"
              or (e.condition or "").casefold() in _CONNECTION_CHANGES}
    # libeep counts backwards from the CNT sample count to locate SEG boundaries.
    start = count
    for length in reversed(later_segments):
        start -= length
        if start <= 0:
            raise RecordingEventError("ANT segment sample counts leave no samples in the first recording segment.")
        breaks.add(start)
    return AntCntInspection(
        container, data["reader_version"], data["amp_make"], data["amp_model"], rate, count, tuple(sorted(companions)),
        events, tuple(sorted(breaks)),
    )
