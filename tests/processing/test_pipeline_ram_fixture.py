"""Small byte-copy/provenance checks for full-dataset fixture isolation."""

import hashlib
import importlib.util
import json
from pathlib import Path
import stat

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts/manual_diagnostics/pipeline_ram_fixture.py"
SPEC = importlib.util.spec_from_file_location("pipeline_ram_fixture_test", SCRIPT)
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def test_fixture_preserves_all_declared_inputs_settings_and_original_bytes(tmp_path):
    source = tmp_path / "study"
    source.mkdir()
    bdf = source / "raw.bdf"
    bdf.write_bytes(b"immutable source byte fixture")
    original_stat = bdf.stat()
    project = {"recordings": {"P1__visit": {"raw_file": str(bdf), "source_id": "group_visit", "session_id": "visit"}},
               "recording_sources": {"group_visit": {"group_id": "group", "session_id": "visit", "raw_input_folder": str(source)}},
               "groups": {"group": {"raw_input_folder": str(source)}}, "participants": {"P1": {"group_id": "group"}},
               "preprocessing": {"experimental_ram_preload": False, "kurtosis_auto_interpolate_all": False},
               "experimental_qc": {"kurtosis_review_auto_interpolate_extreme": True},
               "subfolders": {"excel": "1 - Excel Data Files"}, "results_folder": "."}
    manifest = source / "project.json"
    manifest.write_text(json.dumps(project), encoding="utf-8")
    original_bytes = manifest.read_bytes()
    benchmark = tmp_path / "benchmark"
    benchmark.mkdir()
    command = ["--source-project", str(source), "--benchmark-root", str(benchmark)]
    assert fixture.main(command) == 0
    assert not (benchmark / "full58").exists()
    assert fixture.main([*command, "--create"]) == 0
    frozen = json.loads((benchmark / "full58" / "frozen_project.json").read_text())
    assert frozen["preprocessing"] == project["preprocessing"]
    assert frozen["experimental_qc"] == project["experimental_qc"]
    copied = Path(frozen["recordings"]["P1__visit"]["raw_file"])
    assert copied.read_bytes() == bdf.read_bytes()
    receipt = json.loads((benchmark / "full58" / "input_manifest.json").read_text())
    assert receipt["inputs"][0]["sha256"] == hashlib.sha256(bdf.read_bytes()).hexdigest()
    assert manifest.read_bytes() == original_bytes
    assert bdf.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert list(frozen["recordings"]) == list(project["recordings"])
    with pytest.raises(FileExistsError):
        fixture.main([*command, "--create"])
    copied.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_fixture_outputs_reject_parent_escape(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        fixture.destination(tmp_path, tmp_path / "../outside")


def test_marker_receipt_inventory_rejects_invalid_original_checksum(tmp_path):
    source = tmp_path / "raw.bdf"
    source.write_bytes(b"bytes")
    original = {"recording_id": "P1", "occurrence_key": "14:0", "source_file_path": str(source),
                "decision": "exclude_occurrence", "reviewer_state": "explicit_gui_review"}
    key = {"event_plan": {"approved_occurrences": [{"decision_payload": original}]}}
    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    payload = {"key": key, "fingerprint": hashlib.sha256(canonical(key)).hexdigest(),
               "result": {"scientific": "unchanged"}, "result_sha256": "0" * 64}
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(payload))
    root = tmp_path / "benchmark"
    root.mkdir()
    project = {"recordings": {"P1": {"raw_file": str(source)}}}
    with pytest.raises(ValueError, match="result failed"):
        fixture.marker_inventory([path], project, root)
