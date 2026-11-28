"""Strict, read-only BDF inspection before a sample reader can flatten time gaps.

This is format evidence, not device qualification. TAL onsets are relative to
the header clock; the first record's fractional onset is preserved separately.
See the BDF+ specification and EDF+ sections 2.2.2-2.2.4.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import os
from pathlib import Path
import re
from typing import BinaryIO, Callable


class BdfFormatError(ValueError):
    """The source cannot be interpreted without losing format evidence."""


@dataclass(frozen=True)
class BdfSignal:
    label: str
    physical_dimension: str
    physical_minimum: Decimal
    physical_maximum: Decimal
    digital_minimum: int
    digital_maximum: int
    samples_per_record: int

    @property
    def is_annotation(self) -> bool:
        return self.label == "BDF Annotations"

    @property
    def identity_scaling(self) -> bool:
        return (self.physical_minimum == self.digital_minimum
                and self.physical_maximum == self.digital_maximum)


@dataclass(frozen=True)
class BdfHeader:
    variant: str
    header_bytes: int
    data_records: int
    record_duration: Decimal
    signals: tuple[BdfSignal, ...]
    start_date: str
    start_time: str

    @property
    def record_bytes(self) -> int:
        return 3 * sum(signal.samples_per_record for signal in self.signals)


@dataclass(frozen=True)
class BdfAnnotation:
    source_id: str
    source_order: int
    record_index: int
    channel_index: int
    onset_seconds: Decimal
    duration_seconds: Decimal | None
    text: str
    is_timekeeping: bool = False


@dataclass(frozen=True)
class BdfInspection:
    header: BdfHeader
    file_sha256: str
    record_onsets: tuple[Decimal, ...]
    annotations: tuple[BdfAnnotation, ...]
    digital_signals: tuple[tuple[str, tuple[int, ...]], ...]
    processing_blockers: tuple[str, ...]

    @property
    def first_sample_onset(self) -> Decimal:
        return self.record_onsets[0] if self.record_onsets else Decimal(0)


def _ascii(value: bytes, field: str) -> str:
    if any(byte < 32 or byte > 126 for byte in value):
        raise BdfFormatError(f"Non-ASCII BDF header field: {field}.")
    return value.decode("ascii").strip()


def _integer(value: bytes, field: str) -> int:
    text = _ascii(value, field)
    if not re.fullmatch(r"-?\d+", text):
        raise BdfFormatError(f"Invalid integer BDF field: {field}.")
    return int(text)


def _decimal(value: bytes, field: str) -> Decimal:
    text = _ascii(value, field)
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        raise BdfFormatError(f"Invalid numeric BDF field: {field}.")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise BdfFormatError(f"Invalid numeric BDF field: {field}.") from exc
    if not number.is_finite():
        raise BdfFormatError(f"Nonfinite BDF field: {field}.")
    return number


def _header(fixed: bytes, signals_bytes: bytes) -> BdfHeader:
    if len(fixed) != 256 or fixed[:8] != b"\xffBIOSEMI":
        raise BdfFormatError("Missing BDF 24-bit signature.")
    count = _integer(fixed[252:256], "signal count")
    size = _integer(fixed[184:192], "header length")
    if count <= 0 or size != (count + 1) * 256 or len(signals_bytes) != count * 256:
        raise BdfFormatError("Invalid or truncated BDF signal header.")
    reserved = _ascii(fixed[192:236], "reserved")
    if reserved not in {"24BIT", "BDF+C", "BDF+D"}:
        raise BdfFormatError(f"Unrecognized BDF format marker {reserved!r}.")
    records = _integer(fixed[236:244], "record count")
    duration = _decimal(fixed[244:252], "record duration")
    if records < 0 or duration <= 0:
        raise BdfFormatError("A closed BDF needs a known record count and positive duration.")
    fields: list[list[bytes]] = []
    offset = 0
    for width in (16, 80, 8, 8, 8, 8, 8, 80, 8, 32):
        fields.append([signals_bytes[offset + i * width:offset + (i + 1) * width]
                       for i in range(count)])
        offset += width * count
    signals = []
    ordinary_names = set()
    for i in range(count):
        signal = BdfSignal(
            _ascii(fields[0][i], "label"), _ascii(fields[2][i], "dimension"),
            _decimal(fields[3][i], "physical minimum"),
            _decimal(fields[4][i], "physical maximum"),
            _integer(fields[5][i], "digital minimum"),
            _integer(fields[6][i], "digital maximum"),
            _integer(fields[8][i], "samples per record"),
        )
        if (not signal.label or signal.samples_per_record <= 0
                or signal.physical_minimum == signal.physical_maximum
                or not -8388608 <= signal.digital_minimum < signal.digital_maximum <= 8388607):
            raise BdfFormatError(f"Invalid range or label for BDF signal {i}.")
        if signal.is_annotation:
            if (signal.digital_minimum, signal.digital_maximum) != (-8388608, 8388607):
                raise BdfFormatError("BDF Annotations needs the full signed 24-bit range.")
        elif signal.label.casefold() in ordinary_names:
            raise BdfFormatError("Duplicate BDF signal label.")
        else:
            ordinary_names.add(signal.label.casefold())
        signals.append(signal)
    has_annotations = any(signal.is_annotation for signal in signals)
    if has_annotations != (reserved != "24BIT"):
        raise BdfFormatError("BDF format marker and annotation channels disagree.")
    result = BdfHeader(
        "BDF" if reserved == "24BIT" else reserved, size, records, duration,
        tuple(signals), _ascii(fixed[168:176], "start date"),
        _ascii(fixed[176:184], "start time"),
    )
    if result.record_bytes > 15 * 1024 * 1024:
        raise BdfFormatError("BDF record exceeds the 15 MiB format limit.")
    return result


def _read_header(stream: BinaryIO) -> tuple[BdfHeader, bytes]:
    fixed = stream.read(256)
    if len(fixed) != 256:
        raise BdfFormatError("Truncated BDF header.")
    count = _integer(fixed[252:256], "signal count")
    if not 1 <= count <= 9999:
        raise BdfFormatError("Invalid BDF signal count.")
    signal_bytes = stream.read(count * 256)
    return _header(fixed, signal_bytes), fixed + signal_bytes


def validate_bdf_record_extent(path: Path, file_size: int) -> None:
    """Verify complete 24-bit records without imposing a montage or unit policy."""
    with path.open("rb") as stream:
        fixed = stream.read(256)
        if len(fixed) != 256 or fixed[:8] != b"\xffBIOSEMI":
            raise BdfFormatError("Missing or incomplete BDF header.")
        channels = _integer(fixed[252:256], "signal count")
        offset = _integer(fixed[184:192], "header length")
        declared_records = _integer(fixed[236:244], "record count")
        if not 1 <= channels <= 9999 or offset != 256 * (channels + 1) or file_size < offset:
            raise BdfFormatError("Incomplete BDF signal header.")
        # Packed samples-per-record fields follow 216 header bytes per signal.
        stream.seek(256 + channels * 216)
        sample_counts = stream.read(channels * 8)
    samples = [_integer(sample_counts[i:i + 8], "samples per record") for i in range(0, len(sample_counts), 8)]
    if len(samples) != channels or min(samples) <= 0:
        raise BdfFormatError("Invalid BDF samples per record.")
    records, remainder = divmod(file_size - offset, 3 * sum(samples))
    if remainder or not records or declared_records not in (-1, records):
        raise BdfFormatError("BDF record count/file size mismatch or truncated samples.")


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    # Windows path stat and descriptor fstat expose different ctime semantics.
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def count_bdf_status_transitions(
    path: Path, *, stim_channel: str, expected_samples: int,
    expected_record_samples: int, expected_record_bytes: int,
    should_cancel: Callable[[], bool] | None = None,
) -> int | None:
    """Count adjacent packed Status-word changes for bounded resource planning.

    Read only the fixed header and one Status slice per record. A pointwise
    calibration or mask can merge transitions, so this count plus one (a
    possible initial marker) bounds native event rows. Event detection stays
    with the admitted reader. Return None for unsupported geometry or cancellation.
    """
    if path.suffix.casefold() != ".bdf" or (should_cancel and should_cancel()):
        return None

    before = path.stat()
    identity = _file_identity(before)
    with path.open("rb", buffering=0) as stream:
        opened = os.fstat(stream.fileno())
        if _file_identity(opened) != identity:
            raise BdfFormatError("BDF source was replaced before reading Status.")
        header, _ = _read_header(stream)
        record_bytes = header.record_bytes
        if before.st_size != header.header_bytes + header.data_records * record_bytes:
            raise BdfFormatError("BDF record count/file size mismatch or truncated samples.")
        if (header.variant != "BDF" or not header.data_records
                or record_bytes != expected_record_bytes
                or header.data_records * expected_record_samples != expected_samples
                or any(signal.samples_per_record != expected_record_samples
                       or signal.label.casefold() in {"bdf annotations", "edf annotations"}
                       for signal in header.signals)):
            return None
        status_index = next((index for index, signal in enumerate(header.signals)
                             if signal.label == stim_channel), None)
        if status_index is None:
            return None

        import numpy as np

        status_bytes = expected_record_samples * 3
        status_offset = header.header_bytes + status_index * status_bytes
        previous = None
        transitions = 0
        for record in range(header.data_records):
            if should_cancel and should_cancel():
                return None
            stream.seek(status_offset + record * record_bytes)
            payload = stream.read(status_bytes)
            if len(payload) != status_bytes:
                raise BdfFormatError("BDF source changed or ended while reading Status.")
            if previous is not None and previous != payload[:3]:
                transitions += 1
            # Opaque three-byte values compare every bit of each packed sample.
            words = np.frombuffer(payload, dtype="V3")
            transitions += int(np.count_nonzero(words[1:] != words[:-1]))
            previous = payload[-3:]
        finished = os.fstat(stream.fileno())
        if _file_identity(finished) != identity or finished.st_ctime_ns != opened.st_ctime_ns:
            raise BdfFormatError("BDF source changed while reading Status.")

    after = path.stat()
    if _file_identity(after) != identity or after.st_ctime_ns != before.st_ctime_ns:
        raise BdfFormatError("BDF source changed while reading Status.")
    if should_cancel and should_cancel():
        return None
    return transitions


def _tal_annotations(payload: bytes, record: int, channel: int) -> list[BdfAnnotation]:
    result = []
    chunks = payload.split(b"\x00")
    if chunks[-1]:
        raise BdfFormatError("Unterminated BDF+ annotation list.")
    padding = False
    for tal_index, tal in enumerate(chunks[:-1]):
        if not tal:
            padding = True
            continue
        if padding or not tal.endswith(b"\x14"):
            raise BdfFormatError("Malformed BDF+ annotation padding or terminator.")
        parts = tal.split(b"\x14")
        timestamp = parts[0].split(b"\x15")
        if len(timestamp) > 2 or not re.fullmatch(rb"[+-]\d+(?:\.\d+)?", timestamp[0]):
            raise BdfFormatError("Malformed BDF+ onset.")
        onset = Decimal(timestamp[0].decode("ascii"))
        duration = None
        if len(timestamp) == 2:
            if not re.fullmatch(rb"\d+(?:\.\d+)?", timestamp[1]):
                raise BdfFormatError("Malformed BDF+ annotation duration.")
            duration = Decimal(timestamp[1].decode("ascii"))
        for text_index, text_bytes in enumerate(parts[1:-1]):
            try:
                description = text_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise BdfFormatError("BDF+ annotation is not UTF-8.") from exc
            if any(ord(char) < 32 and char not in "\t\n\r" for char in description):
                raise BdfFormatError("Forbidden control character in BDF+ annotation.")
            result.append(BdfAnnotation(
                f"record:{record}/channel:{channel}/tal:{tal_index}/text:{text_index}",
                len(result), record, channel, onset, duration, description,
                tal_index == 0 and text_index == 0 and not description,
            ))
    return result


def _signed_24(payload: bytes) -> list[int]:
    values = []
    for i in range(0, len(payload), 3):
        value = int.from_bytes(payload[i:i + 3], "little", signed=False)
        values.append(value - 16777216 if value & 8388608 else value)
    return values


def inspect_bdf_format(
    path: str | Path, *, digital_channels: tuple[str, ...] = (),
    optional_digital_channels: tuple[str, ...] = (),
) -> BdfInspection:
    """Inspect actual bytes without MNE, clock regularization or unit guesses.

    Only requested ordinary channels are materialized, in source order. Digital
    values are deliberately not converted to physical quantities. Unknown units
    and telemetry semantics belong to the acquisition qualification gate.
    """
    path = Path(path)
    if path.suffix.casefold() != ".bdf":
        raise BdfFormatError("BDF inspection requires a .bdf source.")
    before = path.stat()
    digest = hashlib.sha256()
    annotations = []
    record_onsets = []
    blockers = []
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if _file_identity(opened) != _file_identity(before):
            raise BdfFormatError("BDF source was replaced before inspection.")
        header, header_bytes = _read_header(stream)
        if before.st_size != header.header_bytes + header.data_records * header.record_bytes:
            raise BdfFormatError("BDF record count/file size mismatch or truncated samples.")
        digest.update(header_bytes)
        selected = {name: [] for name in digital_channels}
        available = {signal.label for signal in header.signals if not signal.is_annotation}
        if len(selected) != len(digital_channels) or not set(selected) <= available:
            raise BdfFormatError("Requested digital channels are missing or duplicated.")
        optional = {name.casefold() for name in optional_digital_channels}
        if len(optional) != len(optional_digital_channels):
            raise BdfFormatError("Optional digital channels are duplicated.")
        selected.update((name, []) for name in available if name.casefold() in optional)
        first_annotation = next((i for i, s in enumerate(header.signals) if s.is_annotation), None)
        for record_index in range(header.data_records):
            row = stream.read(header.record_bytes)
            if len(row) != header.record_bytes:
                raise BdfFormatError("BDF source changed or ended while inspecting records.")
            digest.update(row)
            offset = 0
            record_onset = Decimal(record_index) * header.record_duration
            for channel_index, signal in enumerate(header.signals):
                size = signal.samples_per_record * 3
                payload = row[offset:offset + size]
                offset += size
                if signal.is_annotation:
                    entries = _tal_annotations(payload, record_index, channel_index)
                    if channel_index == first_annotation:
                        if not entries or not entries[0].is_timekeeping or entries[0].duration_seconds is not None:
                            raise BdfFormatError("Missing BDF+ record timekeeping annotation.")
                        record_onset = entries[0].onset_seconds
                    for entry in entries:
                        annotations.append(BdfAnnotation(
                            entry.source_id, len(annotations), entry.record_index,
                            entry.channel_index, entry.onset_seconds, entry.duration_seconds,
                            entry.text, entry.is_timekeeping and channel_index == first_annotation,
                        ))
                elif signal.label in selected:
                    selected[signal.label].extend(_signed_24(payload))
            if record_index == 0 and not Decimal(0) <= record_onset < Decimal(1):
                raise BdfFormatError("First BDF+ record onset must be a fractional second.")
            if record_onsets:
                expected = Fraction(record_onsets[-1]) + Fraction(header.record_duration)
                if Fraction(record_onset) < expected:
                    raise BdfFormatError("Overlapping or reversed BDF+ record timestamps.")
                if Fraction(record_onset) != expected and header.variant == "BDF+C":
                    blockers.append("BDF+C record timestamps are not contiguous.")
            record_onsets.append(record_onset)
        if stream.read(1):
            raise BdfFormatError("BDF source grew during inspection.")
    after = path.stat()
    if _file_identity(after) != _file_identity(before) or after.st_ctime_ns != before.st_ctime_ns:
        raise BdfFormatError("BDF source changed during inspection.")
    if not header.data_records:
        blockers.append("No recorded samples.")
    if header.variant == "BDF+D":
        blockers.append("BDF+D discontinuous input is inspection-only; no time-grid flattening is permitted.")
    return BdfInspection(
        header, digest.hexdigest(), tuple(record_onsets), tuple(annotations),
        tuple((signal.label, tuple(selected[signal.label]))
              for signal in header.signals if signal.label in selected),
        tuple(dict.fromkeys(blockers)),
    )
