"""Validate timing scopes with tiny synthetic telemetry, without EEG or Qt."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts/manual_diagnostics/pipeline_telemetry_summary.py"
SPEC = importlib.util.spec_from_file_location("pipeline_telemetry_summary_test", SCRIPT)
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


def test_embedded_downstream_wrapper_is_not_counted_twice(tmp_path, monkeypatch):
    core = {"stage_seconds": {"setup": 2, "downstream": 10}, "recordings": ["P1"],
            "status": "pipeline_complete", "normal_pool_max_workers": 2}
    downstream = {"started_at_utc": "2026-01-01T00:00:02Z", "setup_elapsed_seconds": 2,
                  "worker_run_elapsed_seconds": 7, "status": "complete"}
    events = [{"utc": f"2026-01-01T00:00:{second:02d}Z", "phase": phase, "event": event}
              for second, phase, event in ((0, "setup", "start"), (2, "setup", "finish"),
                                            (2, "downstream", "start"), (12, "downstream", "finish"))]
    events.append({"utc": "2026-01-01T00:00:05Z", "phase": "downstream_native", "event": "signal"})
    streams = []
    for second in range(1, 13):
        streams.append({"utc": f"2026-01-01T00:00:{second:02d}Z", "monotonic_time": second,
                        "sample_gap_seconds": 1, "tree_private_complete": True,
                        "tree_cpu_percent_one_core": 100, "processes": [
                            {"process_key": "1:1", "cpu_percent_one_core": 100}],
                        "disk_spaces": {"scratch": {"root": "scratch", "total_bytes": 1000,
                            "free_bytes": 1000 - second, "used_bytes": second}}})
    def save(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path
    samples = tmp_path / "resources.jsonl"
    samples.write_text("".join(json.dumps(value) + "\n" for value in streams), encoding="utf-8")
    save("resources.metadata.json", {"hardware": {"cpu_logical_count": 4}})
    save("launch.json", {"command": ["runner.py", "--workers", "2"]})
    core_events = tmp_path / "core.jsonl"
    core_events.write_text("".join(json.dumps(value) + "\n" for value in events), encoding="utf-8")
    downstream_events = tmp_path / "downstream.jsonl"
    downstream_events.write_text("", encoding="utf-8")
    arguments = SimpleNamespace(
        benchmark_root=tmp_path, case_name="complete", samples=[samples],
        core_receipt=save("core.json", core), core_events=core_events,
        downstream_receipt=save("downstream.json", downstream), downstream_events=downstream_events,
        backend_log=None, baseline_summary=None,
    )
    result = summary.summarize(arguments)
    assert result["core_business_elapsed_seconds"] == 2
    assert result["pipeline_business_elapsed_seconds"] == 9
    assert result["business_window_resources"]["observed_interval_seconds"] == 9
    assert result["business_window_resources"]["observed_process_tree_cpu_seconds"] == 9
    assert result["resources"]["observed_interval_seconds"] == 12
    assert result["resources"]["sampled_disk_spaces_by_probe"]["scratch"]["minimum_observed_free_bytes"] == 988
    assert result["business_window_resources"]["sampled_disk_spaces_by_probe"]["scratch"]["minimum_observed_free_bytes"] == 989
    assert result["requested_worker_policy"] == "2"
    assert not next(row for row in result["stages"] if row["name"] == "downstream")["included_in_business_time"]
    assert summary.compare_summary(result, result)["metrics"]["pipeline_business_elapsed_seconds"]["difference"] == 0
    with pytest.raises(ValueError, match="preserve all validated settings"):
        summary.compare_summary({**result, "validated_params": {"high_pass": 1.0}}, result)
    off = {**result, "source_root": "one frozen implementation", "configured_preparation_pool_workers": 2,
           "experimental_ram_preload": False,
           "validated_params": {"experimental_ram_preload": False}}
    on = {**off, "experimental_ram_preload": True, "validated_params": {"experimental_ram_preload": True}}
    assert summary.compare_summary(on, off, purpose="ram_preload")["comparison_purpose"] == "ram_preload"
    with pytest.raises(ValueError, match="same RAM preload setting"):
        summary.compare_summary(on, off, purpose="source_optimization")
    with pytest.raises(ValueError, match="seed runs cannot"):
        summary.compare_summary({**off, "functional_seed": True}, off)
    with pytest.raises(ValueError, match="one explicit ON"):
        summary.compare_summary(off, off, purpose="ram_preload")
    with pytest.raises(ValueError, match="actual native pool"):
        summary.compare_summary({**on, "configured_preparation_pool_workers": None},
                                {**off, "configured_preparation_pool_workers": None}, purpose="ram_preload")
    overhead_only = {**off, "resources": {**off["resources"],
                       "sampled_peaks": {**off["resources"]["sampled_peaks"], "tree_rss_bytes": 9999},
                       "observed_process_tree_cpu_seconds": 9999, "mean_equivalent_logical_cores": 9999}}
    comparison = summary.compare_summary(overhead_only, off)
    assert comparison["metrics"]["sampled_peak_tree_rss_bytes"]["difference"] == 0
    assert comparison["metrics"]["observed_process_tree_cpu_seconds"]["difference"] == 0
    assert "Native business-window" in comparison["resource_comparison_scope"]
    storage_off = {**off, "generated_storage_footprint": {"size_bytes": 100, "file_count": 2, "stat_errors": []}}
    storage_on = {**on, "generated_storage_footprint": {"size_bytes": 80, "file_count": 2, "stat_errors": []}}
    assert summary.compare_summary(storage_on, storage_off, purpose="ram_preload")["metrics"]["final_generated_project_size_bytes"]["difference"] == -20
    with pytest.raises(ValueError, match="complete file census"):
        summary.compare_summary({**storage_on, "generated_storage_footprint": {"stat_errors": ["unreadable"]}},
                                storage_off, purpose="ram_preload")
    full_proof = save("run_receipt.json", {"large_native_evidence": "x" * 10000})
    identity = summary.file_identity(full_proof)
    compact = save("telemetry_core_receipt.json", {**core, "observer_full_receipt_proof": identity})
    monkeypatch.setattr(summary, "MAX_JSON_BYTES", 4096)
    arguments.core_receipt = compact
    compact_result = summary.summarize(arguments)
    assert compact_result["pipeline_business_elapsed_seconds"] == 9
    assert identity in compact_result["evidence_files"]
    full_proof.write_text(full_proof.read_text() + " ")
    with pytest.raises(ValueError, match="does not bind"):
        summary.summarize(arguments)


def test_comparison_rejects_worker_and_completion_scope_mismatches():
    baseline = {"selected_recordings": ["P1"], "core_status": "preparation_complete_diagnostic_only",
                "configured_normal_pool_workers": 2, "configured_preparation_pool_workers": 2}
    with pytest.raises(ValueError, match="preparation worker"):
        summary.compare_summary({**baseline, "configured_preparation_pool_workers": 3}, baseline, purpose="ram_preload")
    with pytest.raises(ValueError, match="normal worker"):
        summary.compare_summary({**baseline, "configured_normal_pool_workers": 3}, baseline)
    with pytest.raises(ValueError, match="same completed core scope"):
        summary.compare_summary({**baseline, "core_status": "pipeline_complete"}, baseline)


def test_preparation_worker_limit_comes_from_native_pool_log(tmp_path):
    path = tmp_path / "backend.log"
    path.write_text("kurtosis_review_process_started files=58 max_workers=2 memory_budget_bytes=10\n"
                    "kurtosis_review_process_finished files=58 completed=58 max_workers=2 elapsed_seconds=3\n")
    assert summary.preparation_workers(path) == 2
    path.write_text(path.read_text() + "kurtosis_review_process_started files=58 max_workers=3\n")
    with pytest.raises(ValueError, match="inconsistent"):
        summary.preparation_workers(path)


def test_native_worker_windows_exclude_only_exact_witnessed_capture_gaps():
    receipt = {"started_at_utc": "2026-01-01T00:00:00Z", "worker_run_attempts": [{"attempt_index": 1,
                "start_elapsed_seconds": 2.0, "finish_elapsed_seconds": 12.0, "worker_run_gross_elapsed_seconds": 10.0,
                "worker_run_elapsed_seconds": 9.75, "observer_manifest_capture_elapsed_seconds_excluded_from_worker_time": .25}],
               "observer_manifest_capture_windows_excluded_from_worker_time": [{"attempt_index": 1,
                 "start_elapsed_seconds": 4.0, "finish_elapsed_seconds": 4.25}]}
    windows = summary.downstream_windows(receipt, [])
    assert len(windows) == 2
    assert sum(row["native_elapsed_seconds"] for row in windows) == 9.75
    assert windows[0]["finish_unix"] == summary.timestamp("2026-01-01T00:00:04Z")
    assert windows[1]["start_unix"] == summary.timestamp("2026-01-01T00:00:04.250000Z")
    receipt["worker_run_attempts"][0]["worker_run_elapsed_seconds"] = 9.5
    with pytest.raises(ValueError, match="exactly its witnessed"):
        summary.downstream_windows(receipt, [])
    receipt["worker_run_attempts"][0]["worker_run_elapsed_seconds"] = 9.75
    receipt["observer_manifest_capture_windows_excluded_from_worker_time"][0]["finish_elapsed_seconds"] = 13.0
    with pytest.raises(ValueError, match="within its native worker"):
        summary.downstream_windows(receipt, [])


def test_disk_space_probe_identity_cannot_change_during_one_window():
    resources = summary.Resources(4)
    sample = {"utc": "2026-01-01T00:00:01Z", "processes": [],
              "disk_spaces": {"scratch": {"root": "one-volume", "total_bytes": 1000,
                                         "free_bytes": 900, "used_bytes": 100}}}
    resources.add(sample)
    with pytest.raises(ValueError, match="probe identity"):
        resources.add({**sample, "disk_spaces": {"scratch": {**sample["disk_spaces"]["scratch"],
                                                             "root": "different-volume"}}})
