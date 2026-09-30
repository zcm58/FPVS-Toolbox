"""Small independently encoded BDF/BDF+ fixtures, not vendor qualification."""
from __future__ import annotations

from pathlib import Path


def write_bdf(
    path: Path, *, variant="BDF+C", record_onsets=("0", "1"),
    annotations=(), status=True, eeg_names=("Fz",), unit="uV",
    samples_per_record=250, record_duration="1", signal_values=None,
    signal_units=None, physical_ranges=None, digital_ranges=None,
) -> Path:
    def field(value, width):
        encoded = str(value).encode("ascii")
        assert len(encoded) <= width
        return encoded.ljust(width, b" ")

    labels = list(eeg_names) + (["Status"] if status else [])
    if variant != "BDF":
        labels.append("BDF Annotations")
    default_samples = [[0] * samples_per_record] * len(record_onsets)
    channel_samples = {name: (signal_values or {}).get(name, default_samples) for name in labels}
    rows = []
    for index, onset in enumerate(record_onsets):
        row = bytearray()
        for name in labels:
            if name == "BDF Annotations":
                data = f"+{onset}\x14\x14\x00".encode("ascii")
                data += b"".join(annotations[index]) if index < len(annotations) else b""
                assert len(data) <= 768
                row.extend(data.ljust(768, b"\x00"))
            else:
                samples = channel_samples[name][index]
                assert len(samples) == samples_per_record
                for sample in samples:
                    row.extend((int(sample) & 0xFFFFFF).to_bytes(3, "little"))
        rows.append(bytes(row))
    fixed = b"\xffBIOSEMI" + field("X X X X", 80) + field("Startdate 01-JAN-2026 X X X", 80)
    fixed += b"01.01.2600.00.00" + field((len(labels) + 1) * 256, 8)
    fixed += field("24BIT" if variant == "BDF" else variant, 44)
    fixed += field(len(rows), 8) + field(record_duration, 8) + field(len(labels), 4)
    columns = [
        [field(name, 16) for name in labels],
        [field("", 80) for _ in labels],
        [field((signal_units or {}).get(name, unit if name in eeg_names else ""), 8) for name in labels],
        [field((physical_ranges or {}).get(name, (-8388608, 8388607))[0], 8) for name in labels],
        [field((physical_ranges or {}).get(name, (-8388608, 8388607))[1], 8) for name in labels],
        [field((digital_ranges or {}).get(name, (-8388608, 8388607))[0], 8) for name in labels],
        [field((digital_ranges or {}).get(name, (-8388608, 8388607))[1], 8) for name in labels],
        [field("", 80) for _ in labels],
        [field(256 if name == "BDF Annotations" else samples_per_record, 8) for name in labels],
        [field("", 32) for _ in labels],
    ]
    path.write_bytes(fixed + b"".join(value for column in columns for value in column) + b"".join(rows))
    return path
