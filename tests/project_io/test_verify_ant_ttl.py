"""Compare native ANT records with a single Studio run through the source CLI."""

import csv
import json
from pathlib import Path
from shutil import copyfile

import pytest

from Main_App.io.verify_ant_ttl import main
from tests.fixtures.ant_cnt import write_ant_fixture


def test_native_cnt_from_studio_playback_matches_original_run(capsys):
    """A libeep writer captured the mock parallel edges from Studio's frame-flip test."""
    run = Path(__file__).resolve().parents[1] / "fixtures" / "ant_cnt" / "studio_playback"
    assert main([str(run / "studio-native.cnt"), "--studio-run", str(run)]) == 0
    comparison = json.loads(capsys.readouterr().out)["comparison"]
    assert comparison["status"] == "ordered_marker_match"
    assert comparison["condition_id"] == "faces" and comparison["studio_configured_rate_hz"] == 512
    assert [(row["frame_index"], row["studio_code"], row["cnt_sample"]) for row in comparison["aligned_markers"]] == [
        (0, 1, 9), (40, 55, 350), (90, 55, 777),
    ]


def test_second_condition_csv_from_studio_export_keeps_its_session_indices(tmp_path, capsys):
    """Studio's shared ANT logger and run writer exported the same schedule twice."""
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "ant_cnt"
    source = fixtures / "studio_playback"
    spec = json.loads((source / "runspec.json").read_text(encoding="utf-8"))
    spec["run_id"] = "second"
    (tmp_path / "runspec.json").write_text(json.dumps(spec), encoding="utf-8")
    copyfile(source / "runtime_metadata.json", tmp_path / "runtime_metadata.json")
    copyfile(fixtures / "second-run-trigger_log.csv", tmp_path / "trigger_log.csv")
    assert main([str(source / "studio-native.cnt"), "--studio-run", str(tmp_path)]) == 0
    comparison = json.loads(capsys.readouterr().out)["comparison"]
    assert [(row["studio_trigger_index"], row["studio_code"], row["cnt_sample"])
            for row in comparison["aligned_markers"]] == [(3, 1, 9), (4, 55, 350), (5, 55, 777)]


def _write_run(path, *, backend="ant_mylab_ttl", status="sent", times=(1.5, 1.7, 1.9), indices=(0, 1, 2)):
    plan = [
        {"code": 1, "label": "condition_start", "frame_index": 0},
        {"code": 55, "label": "oddball_onset", "frame_index": 12},
        {"code": 55, "label": "oddball_onset", "frame_index": 24},
    ]
    spec = {"run_id": "faces-1", "condition": {"condition_id": "faces", "name": "Faces"}, "trigger_events": plan}
    (path / "runspec.json").write_text(json.dumps(spec), encoding="utf-8")
    with (path / "trigger_log.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("trigger_index", "code", "label", "frame_index",
                                                    "time_s", "backend_name", "status"))
        writer.writeheader()
        for index, entry in enumerate(plan):
            writer.writerow(dict(entry, trigger_index=indices[index], backend_name=backend, status=status,
                                 time_s=times[index]))


@pytest.mark.parametrize(("indices", "expected"), [
    ((147, 148, 149), 0), ((147, 149, 150), 1), ((147, 147, 148), 1),
    ((-1, 0, 1), 1),
])
def test_later_condition_keeps_session_indices_and_detects_breaks(tmp_path, capsys, indices, expected):
    path = write_ant_fixture(tmp_path / "condition-two.cnt", [("1", 20), ("55", 220), ("55", 420)])
    _write_run(tmp_path, indices=indices)
    assert main([str(path), "--studio-run", str(tmp_path)]) == expected
    comparison = json.loads(capsys.readouterr().out)["comparison"]
    if expected == 0:
        assert [row["studio_trigger_index"] for row in comparison["aligned_markers"]] == list(indices)
    else:
        assert any("trigger_index" in msg for msg in comparison["differences"])


def test_session_wide_log_cannot_substitute_for_per_condition_csv(tmp_path):
    path = write_ant_fixture(tmp_path / "condition-two.cnt", [("1", 20), ("55", 220), ("55", 420)])
    _write_run(tmp_path, indices=(147, 148, 149))
    log = tmp_path / "trigger_log.csv"
    header, *rows = log.read_text().splitlines()
    log.write_text("\n".join(["run_id," + header, *("faces-1," + row for row in rows)]))
    assert main([str(path), "--studio-run", str(tmp_path)]) == 2


def test_per_run_verification_retains_recorder_events_and_ties(tmp_path, capsys):
    events = [("1", 100), ("55", 300), ("Rs", 300), ("55", 300), ("__", 309)]
    path = write_ant_fixture(tmp_path / "faces.cnt", events)
    before = path.read_bytes()
    _write_run(tmp_path)
    assert main([str(path), "--studio-run", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [(e["source_code"], e["sample"]) for e in report["events"]] == events
    assert report["comparison"]["roles_by_code"] == {"1": "condition_start", "55": "oddball_onset"}
    assert report["comparison"]["condition_id"] == "faces"
    aligned = report["comparison"]["aligned_markers"]
    assert [e["source_order"] for e in aligned] == [0, 1, 3]
    assert [e["cnt_sample"] for e in aligned] == [100, 300, 300]
    assert [e["cnt_minus_studio_elapsed_ms"] for e in aligned] == pytest.approx([0, 0, -200])
    assert path.read_bytes() == before


@pytest.mark.parametrize(("codes", "backend", "status"), [
    (["1", "55"], "ant_mylab_ttl", "sent"),
    (["1", "55", "55", "99"], "ant_mylab_ttl", "sent"),
    (["55", "1", "55"], "ant_mylab_ttl", "sent"),
    (["1", "256", "55"], "ant_mylab_ttl", "sent"),
    (["1", "ODDB", "55"], "ant_mylab_ttl", "sent"),
    (["1", "55", "55"], "egi_din", "sent"),
    (["1", "55", "55"], "ant_mylab_ttl", "error"),
])
def test_comparison_identifies_incomplete_or_unmatched_evidence(tmp_path, capsys, codes, backend, status):
    path = write_ant_fixture(tmp_path / "faces.cnt", [(code, index * 16) for index, code in enumerate(codes)])
    _write_run(tmp_path, backend=backend, status=status)
    assert main([str(path), "--studio-run", str(tmp_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert [event["source_code"] for event in report["events"]] == codes
    assert report["comparison"]["status"] == "mismatch" and report["comparison"]["differences"]
    assert "aligned_markers" not in report["comparison"]


def test_non_ant_file_is_an_input_error(tmp_path):
    path = tmp_path / "other.cnt"
    path.write_bytes(b"Version 3.0\0" + bytes(900))
    assert main([str(path)]) == 2


def test_matching_codes_with_wrong_recorder_sample_rate_are_flagged(tmp_path, capsys):
    path = write_ant_fixture(tmp_path / "faces.cnt", [("1", 20), ("55", 220), ("55", 420)])
    _write_run(tmp_path)
    (tmp_path / "runtime_metadata.json").write_text(json.dumps({
        "recording": {"effective_backend": "ant_mylab_ttl", "ant_sampling_rate_hz": 512},
    }), encoding="utf-8")
    assert main([str(path), "--studio-run", str(tmp_path)]) == 1
    comparison = json.loads(capsys.readouterr().out)["comparison"]
    assert comparison["status"] == "mismatch"
    assert comparison["differences"] == ["Studio configured 512 Hz, but the CNT records 1000 Hz."]


def test_snapshot_from_another_transport_reports_mismatch_without_ant_fields(tmp_path, capsys):
    path = write_ant_fixture(tmp_path / "faces.cnt", [("1", 20), ("55", 220), ("55", 420)])
    _write_run(tmp_path)
    (tmp_path / "runtime_metadata.json").write_text(json.dumps({
        "recording": {"effective_backend": "egi_din"},
    }), encoding="utf-8")
    assert main([str(path), "--studio-run", str(tmp_path)]) == 1
    comparison = json.loads(capsys.readouterr().out)["comparison"]
    assert comparison["differences"] == ["Studio runtime metadata identifies a different output."]


@pytest.mark.parametrize(("samples", "times", "problem"), [
    ((20, 420, 220), (1.5, 1.7, 1.9), "Recorded stimulus sample positions"),
    ((20, 220, 420), (1.5, 1.9, 1.7), "Studio trigger timestamps"),
])
def test_correct_words_with_reversed_time_cannot_match(tmp_path, capsys, samples, times, problem):
    path = write_ant_fixture(tmp_path / "faces.cnt", list(zip(("1", "55", "55"), samples, strict=True)))
    _write_run(tmp_path, times=times)
    assert main([str(path), "--studio-run", str(tmp_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert [event["sample"] for event in report["events"]] == list(samples)
    assert report["comparison"]["differences"][0].startswith(problem)
    assert "aligned_markers" not in report["comparison"]


@pytest.mark.parametrize("change", ["match", "visit", "log_clock", "short_log", "recording"])
def test_companion_summary_binds_log_and_plan_to_same_studio_run(tmp_path, capsys, change):
    path = write_ant_fixture(tmp_path / "faces.cnt", [("1", 20), ("55", 220), ("55", 420)])
    _write_run(tmp_path)
    with (tmp_path / "trigger_log.csv").open(encoding="utf-8", newline="") as stream:
        attempts = list(csv.DictReader(stream))
    for attempt in attempts:
        for field in ("trigger_index", "frame_index", "code"):
            attempt[field] = int(attempt[field])
        attempt["time_s"] = float(attempt["time_s"])
    metadata = {"recording": {"effective_backend": "ant_mylab_ttl", "ant_sampling_rate_hz": 1000}}
    if change == "log_clock":
        attempts[-1]["time_s"] += 0.01
    if change == "short_log":
        attempts.pop()
    if change == "recording":
        (tmp_path / "runtime_metadata.json").write_text(json.dumps({
            "recording": dict(metadata["recording"], parallel_port_address=0xDC00),
        }))
    (tmp_path / "run_summary.json").write_text(json.dumps({
        "run_id": "faces-2" if change == "visit" else "faces-1", "condition_id": "faces",
        "condition_name": "Faces", "trigger_log": attempts, "runtime_metadata": metadata,
    }), encoding="utf-8")
    assert main([str(path), "--studio-run", str(tmp_path)]) == int(change != "match")
    result = json.loads(capsys.readouterr().out)["comparison"]
    assert result["run_summary_checked"] is True
    assert result["studio_configured_rate_hz"] == 1000
    assert ("aligned_markers" in result) == (change == "match")
    if change != "match":
        assert any("run_summary.json" in problem for problem in result["differences"])


@pytest.mark.parametrize("change", [
    "missing_start", "extra_start", "reverse_frames", "shared_frame", "wrong_start_code",
    "blank_identity", "extra_csv_field", "missing_csv_field", "unrepresentable_elapsed_time",
])
def test_malformed_run_files_are_input_errors(tmp_path, capsys, change):
    path = write_ant_fixture(tmp_path / "faces.cnt", [("1", 20), ("55", 220), ("55", 420)])
    _write_run(tmp_path, times=(1.5, 1.7, 1e308) if change == "unrepresentable_elapsed_time" else (1.5, 1.7, 1.9))
    spec_path = tmp_path / "runspec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if change == "missing_start":
        spec["trigger_events"][0]["label"] = "oddball_onset"
    elif change == "extra_start":
        spec["trigger_events"][1]["label"] = "condition_start"
    elif change in ("reverse_frames", "shared_frame"):
        spec["trigger_events"][2]["frame_index"] = 6 if change == "reverse_frames" else 12
    elif change == "wrong_start_code":
        spec["condition"]["trigger_code"] = 2
    elif change == "blank_identity":
        spec["condition"]["condition_id"] = ""
    elif change in ("extra_csv_field", "missing_csv_field"):
        log = tmp_path / "trigger_log.csv"
        lines = log.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1] + ",stale-field" if change == "extra_csv_field" else lines[1].rsplit(",", 1)[0]
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    assert main([str(path), "--studio-run", str(tmp_path)]) == 2
    assert not capsys.readouterr().out
