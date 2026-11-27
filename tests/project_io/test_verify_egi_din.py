"""Exercise the operator-facing MFF diagnostic against Studio's run-file contract."""
import csv
import json

import pytest

from Main_App.io.verify_egi_din import main
from tests.fixtures.egi_mff import write_mff_fixture


@pytest.mark.parametrize("change", [
    "match", "missing", "extra", "unmapped", "order", "send_error", "disabled", "bad_timestamp",
])
def test_compare_studio_run_with_mff(tmp_path, capsys, change):
    mff = tmp_path / "sample.mff"
    events = [("STRT", 0), ("ODDB", 25_000_000), ("ODDB", 25_000_000)]
    if change == "missing":
        events.pop()
    if change == "extra":
        events.append(("STRT", 100_000_000))
    if change == "order":
        events[0], events[1] = ("ODDB", 0), ("STRT", 25_000_000)
    write_mff_fixture(mff, events)
    track, = mff.glob("Events_*.xml")
    plan = [
        {"code": 7, "frame_index": 0, "label": "condition_start"},
        {"code": 55, "frame_index": 12, "label": "oddball_onset"},
        {"code": 55, "frame_index": 24, "label": "oddball_onset"},
    ]
    spec = {"run_id": "run-1", "condition": {"condition_id": "c-1", "name": "Faces"}, "trigger_events": plan}
    (tmp_path / "runspec.json").write_text(json.dumps(spec), encoding="utf-8")
    with (tmp_path / "trigger_log.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            "trigger_index", "code", "frame_index", "time_s", "label", "status", "backend_name",
        ))
        writer.writeheader()
        for i, entry in enumerate(plan):
            writer.writerow(dict(entry, trigger_index=i, time_s="nan" if change == "bad_timestamp" else 1.5 + i * 0.2,
                                 status="error" if change == "send_error" else "sent",
                                 backend_name="null" if change == "disabled" else "egi_din"))
    args = [str(mff), "--track", track.name, "--studio-run", str(tmp_path), "--map", "STRT=7"]
    if change != "unmapped":
        args.extend(["--map", "ODDB=55"])
    if change == "bad_timestamp":
        assert main(args) == 2
        return
    assert main(args) == int(change != "match")
    report = json.loads(capsys.readouterr().out)
    assert report["comparison"]["condition_name"] == "Faces"
    assert report["comparison"]["roles_by_code"] == {"7": "condition_start", "55": "oddball_onset"}
    assert [event["source_code"] for event in report["events"]] == [code for code, _ in events]
    if change == "match":
        assert report["comparison"]["status"] == "ordered_marker_match"
        assert [event["sample"] for event in report["events"]] == [0, 25, 25]
        aligned = report["comparison"]["aligned_markers"]
        assert [row["frame_index"] for row in aligned] == [0, 12, 24]
        assert [row["mff_minus_studio_elapsed_ms"] for row in aligned] == pytest.approx([0, -175, -375])
    else:
        assert report["comparison"]["differences"]
        assert "aligned_markers" not in report["comparison"]
