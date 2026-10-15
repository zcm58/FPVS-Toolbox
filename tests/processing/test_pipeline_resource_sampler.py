from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "manual_diagnostics" / "pipeline_resource_sampler.py"
_SPEC = importlib.util.spec_from_file_location("pipeline_resource_sampler_test", _SCRIPT)
sampler = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(sampler)


def test_outputs_reject_escape_and_preserve_existing_files(tmp_path):
    with pytest.raises(ValueError, match="beneath"):
        sampler.output_path(tmp_path, "../escaped.jsonl")
    target = sampler.output_path(tmp_path, "nested/metadata.json")
    sampler.write_json_atomic(target, {"first": True})
    original = target.read_bytes()
    with pytest.raises(FileExistsError):
        sampler.write_json_atomic(target, {"second": True})
    assert target.read_bytes() == original
    assert not list(target.parent.glob("*.tmp"))


def test_stop_requires_fresh_complete_matching_token(tmp_path):
    path = tmp_path / "stop.json"
    path.write_text('{"stop_token":"token","reason":"old"}', encoding="utf-8")
    stop = sampler.StopSentinel(path, "token")
    assert not stop.requested()
    path.write_text('{"stop_token":', encoding="utf-8")
    assert not stop.requested()
    path.write_text('{"stop_token":"other"}', encoding="utf-8")
    assert not stop.requested()
    replacement = tmp_path / "stop.tmp"
    replacement.write_text('{"stop_token":"token","reason":"new"}', encoding="utf-8")
    os.replace(replacement, path)
    assert stop.requested()
    path.write_bytes(b"x" * (sampler.MAX_STOP_BYTES + 1))
    assert not stop.requested()


def test_process_deltas_keep_read_write_separate_and_reject_pid_reuse():
    previous = {"process_key": "1:old", "cpu_seconds": 2., "io_read_bytes": 100, "io_write_bytes": 10}
    current = {"process_key": "1:old", "cpu_seconds": 3., "io_read_bytes": 140, "io_write_bytes": 13}
    assert sampler.process_deltas(current, previous, .5) == {"cpu_percent_one_core": 200., "io_read_bytes_delta": 40, "io_write_bytes_delta": 3}
    current["process_key"] = "1:new"
    assert all(value is None for value in sampler.process_deltas(current, previous, .5).values())
    assert sampler.nonnegative_delta(9, 10) is None


def test_root_pid_guard_uses_fresh_process_identity(monkeypatch):
    stale = SimpleNamespace(pid=7, create_time=lambda: 1.)
    monkeypatch.setattr(sampler.psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 2.))
    with pytest.raises(RuntimeError, match="reused"):
        sampler.sample_tree(stale, 1., {}, None, False)


def test_command_identity_omits_arguments_and_paths():
    value = sampler.command_summary(["/private/bin/python", "/private/runner.py", "--secret", "private-value"])
    assert value == {"executable_name": "python", "script_name": "runner.py"}
    worker = sampler.command_summary(["python", "-c", "from multiprocessing.spawn import spawn_main; spawn_main()", "--private-value"])
    assert worker["worker_kind"] == "spawned_python_worker"
    assert "private" not in json.dumps(worker)


def test_monitor_streams_bounded_small_run_and_records_coverage(tmp_path):
    args = SimpleNamespace(benchmark_root=tmp_path, project_root=tmp_path, scratch_root=tmp_path,
                           output=Path("samples.jsonl"), stop_file=Path("stop.json"), stop_token="fresh",
                           pid=os.getpid(), interval=.1, max_seconds=.21, no_process_identity=True)
    target = sampler.monitor(args)
    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    metadata = json.loads(target.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    summary = json.loads(target.with_suffix(".summary.json").read_text(encoding="utf-8"))
    assert rows and summary["sample_count"] == len(rows)
    assert summary["stop_reason"] == "max_duration"
    assert summary["coverage"]["first_process_intervals_excluded_from_cpu_and_io_deltas"]
    assert metadata["hardware"]["disk_counter_mapping"].startswith("unknown")
    assert rows[0]["processes"][0]["cpu_percent_one_core"] is None
    assert all({"rss_bytes", "private_bytes", "thread_count", "io_read_bytes", "io_write_bytes", "process_key"}.issubset(row["processes"][0]) for row in rows)
    assert {"project", "scratch"} == set(rows[0]["disk_spaces"])
