"""A two-second continuous synthetic MFF with one float32 EEG signal and a DIN track."""
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
import struct
from xml.etree import ElementTree as ET


def write_mff_fixture(path: Path, events: Sequence[tuple[str, int]]) -> Path:
    """Create a 1000 Hz recording with (exact XML code, nanoseconds from start) rows."""
    path.mkdir()
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    members = {
        "info.xml": '<fileInfo xmlns="http://www.egi.com/info_mff"><mffVersion>3</mffVersion>'
                    '<recordTime>2020-01-01T00:00:00.000000+00:00</recordTime>'
                    '<ampType>NA400</ampType></fileInfo>',
        "epochs.xml": '<epochs xmlns="http://www.egi.com/epochs_mff"><epoch><beginTime>0</beginTime>'
                      '<endTime>2000000</endTime><firstBlock>1</firstBlock><lastBlock>2</lastBlock>'
                      '</epoch></epochs>',
        "info1.xml": '<dataInfo xmlns="http://www.egi.com/info_n_mff"><generalInformation>'
                     '<fileDataType><EEG><EEGFile/></EEG></fileDataType></generalInformation></dataInfo>',
        "sensorLayout.xml": '<sensorLayout xmlns="http://www.egi.com/sensorLayout_mff"><name>Synthetic</name>'
                            '<sensors><sensor><name>E1</name><number>1</number><type>0</type></sensor>'
                            '</sensors></sensorLayout>',
        "coordinates.xml": '<coordinates xmlns="http://www.egi.com/coordinates_mff"><sensorLayout>'
                           '<name>Synthetic</name><sensors><sensor><name>E1</name><number>1</number>'
                           '<x>0</x><y>0</y><z>8</z></sensor></sensors></sensorLayout></coordinates>',
    }
    for name, content in members.items():
        (path / name).write_text(content, encoding="utf-8")
    # One described block, followed by a second block that reuses the first header.
    header = struct.pack("<7I", 1, 28, 4000, 1, 0, 1000 << 8 | 32, 0)
    (path / "signal1.bin").write_bytes(header + bytes(4000) + struct.pack("<I", 0) + bytes(4000))
    root = ET.Element("eventTrack", xmlns="http://www.egi.com/event_mff")
    ET.SubElement(root, "name").text = "255 DINs"
    ET.SubElement(root, "trackType").text = "STIM"
    for code, onset_ns in events:
        whole, frac = divmod(onset_ns, 10**9)
        stamp = (start + timedelta(seconds=whole)).strftime("%Y-%m-%dT%H:%M:%S")
        row = ET.SubElement(root, "event")
        ET.SubElement(row, "beginTime").text = f"{stamp}.{frac:09d}+00:00"
        ET.SubElement(row, "duration").text = "0"
        ET.SubElement(row, "code").text = code
        ET.SubElement(row, "label").text = f"Recorded {code}"
    ET.ElementTree(root).write(path / "Events_255 DINs.xml", encoding="utf-8", xml_declaration=True)
    return path
