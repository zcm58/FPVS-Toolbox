"""Summarize isolated pipeline timing/resource evidence without Qt or project writes.

CLI inputs are native runner/probe receipts, phase events and one or more resource
JSONL files. CPU and I/O totals cover observed same-process intervals only. Phase
allocation prorates intervals that cross event boundaries; sampled memory and
worker peaks can miss brief events. OS disk counters are system-wide and their
physical-device mapping is unknown. This is descriptive evidence, not a test of
statistical significance or an artifact-parity oracle.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import datetime, timezone
import hashlib
import json
import math
import logging
from pathlib import Path
import re
import statistics


LOG = logging.getLogger(__name__)
SCHEMA = "pipeline_telemetry_summary_v1"
MAX_JSON_BYTES = 1024 * 1024 * 1024
MAX_LINE_BYTES = 2 * 1024 * 1024
EXPORT_TIMING = re.compile(rb"\[EXPORT TIMING\] file=(.*?) stage=(\w+) elapsed_ms=(\d+)")


def timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Evidence timestamps must include a UTC offset")
    return parsed.timestamp()


def read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"Evidence JSON exceeds {MAX_JSON_BYTES} bytes: {path}")
    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected evidence JSON object: {path}")
    return payload


def read_lines(path: Path) -> Iterable[dict]:
    with path.open("rb") as stream:
        number = 0
        while line := stream.readline(MAX_LINE_BYTES + 1):
            number += 1
            if len(line) > MAX_LINE_BYTES:
                raise ValueError(f"JSONL line exceeds limit: {path}:{number}")
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSONL object: {path}:{number}")
            yield payload


def file_identity(path: Path) -> dict:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.resolve()), "size_bytes": path.stat().st_size, "sha256": digest}


def native_stages(receipt: dict, events: Iterable[dict]) -> list[dict]:
    pending = {}
    result = []
    for item in events:
        if item.get("phase") == "downstream_native" and item.get("event") == "signal":
            # This is a copied native progress event, not a core phase timer.
            continue
        name = item["phase"]
        at = timestamp(item["utc"])
        if item["event"] == "start":
            if name in pending:
                raise ValueError(f"Duplicate unfinished core stage: {name}")
            pending[name] = at
        elif item["event"] == "finish":
            if name not in pending or at < pending[name]:
                raise ValueError(f"Unpaired/nonmonotone core finish: {name}")
            duration = receipt.get("stage_seconds", {}).get(name)
            if duration is None:
                raise ValueError(f"Finished stage has no native timing: {name}")
            result.append({"kind": "core_native_stage", "name": name, "start_unix": pending.pop(name), "finish_unix": at,
                           "native_elapsed_seconds": duration})
            result[-1]["event_window_seconds"] = at - result[-1]["start_unix"]
        else:
            raise ValueError(f"Unknown core stage event: {item['event']}")
    if pending:
        result.extend({"kind": "core_native_stage", "name": name, "start_unix": start, "finish_unix": None,
                       "native_elapsed_seconds": None, "incomplete_event_window": True} for name, start in pending.items())
    return result


def downstream_windows(receipt: dict, events: Iterable[dict]) -> list[dict]:
    started = timestamp(receipt["started_at_utc"])
    setup = receipt.get("setup_elapsed_seconds")
    worker_duration = receipt.get("worker_run_elapsed_seconds")
    windows = []
    attempts = receipt.get("worker_run_attempts", [])
    if attempts:
        attempt_ids = {attempt["attempt_index"] for attempt in attempts}
        if len(attempt_ids) != len(attempts) or any(row["attempt_index"] not in attempt_ids for row in
                                                   receipt.get("observer_manifest_capture_windows_excluded_from_worker_time", [])):
            raise ValueError("Observer capture gap refers to an unknown or ambiguous worker attempt")
        for attempt in attempts:
            exclusions = sorted((row for row in receipt.get("observer_manifest_capture_windows_excluded_from_worker_time", [])
                                 if row["attempt_index"] == attempt["attempt_index"]), key=lambda row: row["start_elapsed_seconds"])
            first, finish = attempt["start_elapsed_seconds"], attempt["finish_elapsed_seconds"]
            cursor, segments, excluded_seconds = first, [], 0.0
            for row in exclusions:
                begin, end = row["start_elapsed_seconds"], row["finish_elapsed_seconds"]
                if not first <= cursor <= begin < end <= finish:
                    raise ValueError("Observer manifest capture gap does not lie within its native worker attempt")
                segments.append((cursor, begin))
                excluded_seconds += end - begin
                cursor = end
            segments.append((cursor, finish))
            if (exclusions or "worker_run_gross_elapsed_seconds" in attempt) and (not math.isclose(attempt.get("worker_run_gross_elapsed_seconds", -1), finish - first, rel_tol=1e-10, abs_tol=1e-9)
                               or not math.isclose(attempt.get("observer_manifest_capture_elapsed_seconds_excluded_from_worker_time", -1), excluded_seconds, rel_tol=1e-10, abs_tol=1e-9)
                               or not math.isclose(attempt["worker_run_elapsed_seconds"], finish - first - excluded_seconds, rel_tol=1e-10, abs_tol=1e-9)):
                raise ValueError("Native worker timer does not exclude exactly its witnessed observer capture gaps")
            for index, (begin, end) in enumerate(segments, 1):
                if begin == end:
                    continue
                windows.append({"kind": "downstream_native_worker",
                                "name": f"downstream_worker_attempt{attempt['attempt_index']}" + (f"_segment{index}" if exclusions else ""),
                                "start_unix": started + begin, "finish_unix": started + end,
                                "native_elapsed_seconds": end - begin if exclusions else attempt["worker_run_elapsed_seconds"],
                                "boundary_note": "Actual native worker attempt timer; benchmark policy application, Project loading and exactly witnessed observer manifest-capture gaps excluded."})
    elif setup is not None and worker_duration is not None:
        windows.append({"kind": "downstream_native_worker", "name": "downstream_worker_run", "start_unix": started + setup,
                        "finish_unix": started + setup + worker_duration, "native_elapsed_seconds": worker_duration,
                        "boundary_note": "Worker start reconstructed from receipt setup duration; constructor/signal setup occurs immediately afterward."})
    phase_start = None
    phase_name = None
    for event in events:
        if event.get("signal") == "worker_attempt_finished":
            if phase_name is not None:
                at = started + event["elapsed_seconds"]
                windows.append({"kind": "downstream_progress_window", "name": phase_name, "start_unix": phase_start,
                                "finish_unix": at, "progress_interval_seconds": at - phase_start})
            phase_start = phase_name = None
            continue
        if event.get("signal") != "phase_progress":
            continue
        payload = event["payload"]
        name = payload[0]
        at = started + event["elapsed_seconds"]
        if name != phase_name:
            if phase_name is not None:
                windows.append({"kind": "downstream_progress_window", "name": phase_name, "start_unix": phase_start,
                                "finish_unix": at, "progress_interval_seconds": at - phase_start})
            phase_start, phase_name = at, name
    # Completion/failure progress is terminal, not a separate computation stage.
    return windows


class Resources:
    def __init__(self, logical_cores: int | None) -> None:
        self.logical_cores = logical_cores
        self.samples = 0
        self.interval_seconds = self.cpu_seconds = self.cpu_interval_seconds = 0.0
        self.weighted = {"tree_rss_bytes": 0.0, "tree_private_bytes": 0.0, "observed_worker_count": 0.0, "cpu_active_worker_count": 0.0, "discovered_child_count": 0.0}
        self.peaks = {name: 0 for name in (*self.weighted, "tree_cpu_percent_one_core", "cpu_active_child_count", "system_ram_used_bytes")}
        self.io = {"read_bytes": 0.0, "write_bytes": 0.0}
        self.disk = {}
        self.disk_spaces = {}
        self.worker_ids = set()
        self.process_keys = set()
        self.private_metrics = set()
        self.process_errors = self.process_omissions = self.gaps = 0
        self.first_unix = self.last_unix = None
        self.private_incomplete = 0

    def add(self, sample: dict, *, fraction=1.0, peak_eligible=True) -> None:
        if not 0 < fraction <= 1:
            return
        self.samples += int(peak_eligible)
        at = timestamp(sample["utc"])
        self.first_unix = at if self.first_unix is None else min(self.first_unix, at)
        self.last_unix = at if self.last_unix is None else max(self.last_unix, at)
        self.process_errors += len(sample.get("process_errors", []))
        self.process_omissions += sample.get("process_limit_omissions", 0)
        self.private_incomplete += int(not sample.get("tree_private_complete", False))
        gap = sample.get("sample_gap_seconds")
        duration = 0.0 if gap is None else gap * fraction
        self.interval_seconds += duration
        known_cpu = [item for item in sample["processes"] if item.get("cpu_percent_one_core") is not None]
        if known_cpu and duration:
            self.cpu_interval_seconds += duration
            self.cpu_seconds += sum(item["cpu_percent_one_core"] for item in known_cpu) * duration / 100
        for name in self.weighted:
            self.weighted[name] += sample.get(name, 0) * duration
        if peak_eligible:
            for name in self.peaks:
                self.peaks[name] = max(self.peaks[name], sample.get(name, 0) or 0)
            for name, space in sample.get("disk_spaces", {}).items():
                if "error" in space:
                    continue
                values = self.disk_spaces.setdefault(name, {
                    "root": space["root"], "total_bytes": space["total_bytes"],
                    "first_observed_free_bytes": space["free_bytes"],
                    "last_observed_free_bytes": space["free_bytes"],
                    "minimum_observed_free_bytes": space["free_bytes"],
                    "maximum_observed_used_bytes": space["used_bytes"], "sample_count_in_window": 0,
                })
                if values["root"] != space["root"] or values["total_bytes"] != space["total_bytes"]:
                    raise ValueError("Disk-space probe identity changed within one resource window")
                values["last_observed_free_bytes"] = space["free_bytes"]
                values["minimum_observed_free_bytes"] = min(values["minimum_observed_free_bytes"], space["free_bytes"])
                values["maximum_observed_used_bytes"] = max(values["maximum_observed_used_bytes"], space["used_bytes"])
                values["sample_count_in_window"] += 1
        for process in sample["processes"]:
            self.process_keys.add(process["process_key"])
            if process.get("worker_id") is not None:
                self.worker_ids.add(process["worker_id"])
            if process.get("private_metric") is not None:
                self.private_metrics.add(process["private_metric"])
            for kind in ("read", "write"):
                delta = process.get(f"io_{kind}_bytes_delta")
                self.io[f"{kind}_bytes"] += (delta or 0) * fraction
        for disk, deltas in sample.get("disk_deltas", {}).items():
            totals = self.disk.setdefault(disk, {})
            for name, delta in deltas.items():
                if delta is not None:
                    totals[name] = totals.get(name, 0.0) + delta * fraction

    def payload(self, *, configured_workers=None) -> dict:
        means = {key: None if not self.interval_seconds else value / self.interval_seconds for key, value in self.weighted.items()}
        average_cpu = None if not self.cpu_interval_seconds else 100 * self.cpu_seconds / self.cpu_interval_seconds
        return {
            "sample_count_in_window": self.samples,
            "first_sample_unix": self.first_unix, "last_sample_unix": self.last_unix,
            "observed_interval_seconds": self.interval_seconds, "observed_cpu_interval_seconds": self.cpu_interval_seconds,
            "observed_process_tree_cpu_seconds": self.cpu_seconds,
            "mean_cpu_percent_one_logical_core": average_cpu,
            "mean_equivalent_logical_cores": None if average_cpu is None else average_cpu / 100,
            "mean_cpu_percent_machine_logical_capacity": None if average_cpu is None or not self.logical_cores else average_cpu / self.logical_cores,
            "sampled_peaks": self.peaks if self.samples else {name: None for name in self.peaks}, "interval_weighted_endpoint_sample_means": means,
            "mean_active_worker_fraction_of_configured_pool": None if not configured_workers or means["cpu_active_worker_count"] is None else means["cpu_active_worker_count"] / configured_workers,
            "observed_worker_process_count_across_pools": len(self.worker_ids),
            "observed_process_count_across_lifetimes": len(self.process_keys),
            "private_memory_metrics": sorted(self.private_metrics),
            "observed_process_io_delta_bytes": self.io,
            "system_wide_per_disk_counter_deltas": self.disk,
            "sampled_disk_spaces_by_probe": self.disk_spaces,
            "coverage": {"process_read_errors": self.process_errors, "process_limit_omissions": self.process_omissions,
                         "private_memory_incomplete_samples": self.private_incomplete},
        }


def add_window(accumulator: Resources, sample: dict, window: dict) -> None:
    at = timestamp(sample["utc"])
    start, end = window["start_unix"], window["finish_unix"]
    if end is None:
        return
    peak_eligible = start <= at <= end
    gap = sample.get("sample_gap_seconds")
    if gap:
        overlap = max(0.0, min(at, end) - max(at - gap, start))
        if overlap:
            accumulator.add(sample, fraction=min(1.0, overlap / gap), peak_eligible=peak_eligible)
    elif peak_eligible:
        accumulator.add(sample)


def export_timings(path: Path) -> list[dict]:
    values = {}
    # Timing tokens are ASCII even when Windows console prose uses a local codepage.
    with path.open("rb") as stream:
        for line in stream:
            if match := EXPORT_TIMING.search(line):
                stage = match[2].decode("ascii")
                values.setdefault(stage, []).append(int(match[3]) / 1000)
    return [{"stage": name, "call_count": len(times), "sum_worker_elapsed_seconds": sum(times),
             "median_worker_call_seconds": statistics.median(times), "min_seconds": min(times), "max_seconds": max(times),
             "note": "Worker elapsed calls overlap in parallel; totals are not additive end-to-end time. Timing log values are rounded to milliseconds."}
            for name, times in sorted(values.items())]


def structured_worker_timings(core: dict) -> list[dict]:
    """Include producer records intentionally omitted from the parent text log."""
    values = {}
    results = core.get("processing_result", {}).get("results", [])
    for result in results:
        for item in result.get("export_timing_records", []):
            elapsed = item.get("elapsed_ms")
            if type(elapsed) not in (int, float) or elapsed < 0:
                raise ValueError("Invalid structured worker timing duration")
            values.setdefault((item["source"], item["stage"]), []).append(elapsed / 1000)
        for name, elapsed in result.get("timings_ms", {}).items():
            if type(elapsed) not in (int, float) or elapsed < 0:
                raise ValueError("Invalid worker route timing duration")
            values.setdefault(("processing_route", name), []).append(elapsed / 1000)
    return [{"source": source, "stage": name, "call_count": len(times), "sum_worker_elapsed_seconds": sum(times),
             "median_worker_call_seconds": statistics.median(times), "min_seconds": min(times), "max_seconds": max(times),
             "note": "Native structured worker elapsed calls overlap in parallel and nested stages overlap; totals are not additive end-to-end time. Values are rounded to milliseconds."}
            for (source, name), times in sorted(values.items())]


def ratio(current, baseline) -> dict:
    return {"baseline": baseline, "current": current, "difference": current - baseline,
            "current_divided_by_baseline": None if baseline == 0 else current / baseline,
            "percent_change": None if baseline == 0 else 100 * (current - baseline) / baseline}


def business_stage(stage: dict, has_downstream_receipt: bool) -> bool:
    """Count embedded downstream worker windows once, excluding their wrapper."""
    return (stage["kind"] in {"core_native_stage", "downstream_native_worker"}
            and "excluded_from_processing_time" not in stage["name"]
            and not (has_downstream_receipt and stage["kind"] == "core_native_stage" and stage["name"] == "downstream"))


def native_business_seconds(core: dict, downstream: dict) -> float:
    return sum(value for name, value in core.get("stage_seconds", {}).items()
               if "excluded_from_processing_time" not in name and not (downstream and name == "downstream"))


def preparation_workers(path: Path | None) -> int | None:
    if path is None:
        return None
    counts = set()
    with path.open("rb") as stream:
        for line in stream:
            if match := re.search(rb"kurtosis_review_process_(?:started|finished) files=\d+(?: completed=\d+)? max_workers=(\d+)", line):
                counts.add(int(match[1]))
    if len(counts) > 1:
        raise ValueError("One preparation phase has inconsistent logged worker limits")
    return next(iter(counts), None)


def compare_summary(current: dict, baseline: dict, *, purpose="source_optimization") -> dict:
    if current.get("selected_recordings") != baseline.get("selected_recordings"):
        raise ValueError("Comparison cases must use the same ordered selected recordings")
    for report in (current, baseline):
        if report.get("profiling_diagnostic"):
            raise ValueError("Profiled diagnostics cannot be used as timing-comparison trials")
        if report.get("functional_seed"):
            raise ValueError("Functional/QC seed runs cannot be used as timing-comparison trials")
        if report.get("core_status") not in {None, "complete", "pipeline_complete", "processing_complete_downstream_pending", "preparation_complete_diagnostic_only", "preflight_complete_diagnostic_only"} or report.get("downstream_status") not in {None, "complete"}:
            raise ValueError("Failed/incomplete cases cannot be used as timing-comparison trials")
    if current.get("core_status") != baseline.get("core_status"):
        raise ValueError("Timing comparison must include the same completed core scope")
    if current.get("configured_normal_pool_workers") != baseline.get("configured_normal_pool_workers"):
        raise ValueError("Timing comparison must use the same configured normal worker limit")
    if purpose == "ram_preload" and current.get("configured_preparation_pool_workers") != baseline.get("configured_preparation_pool_workers"):
        raise ValueError("Timing comparison must use the same actual preparation worker limit")
    if current.get("requested_worker_policy") != baseline.get("requested_worker_policy"):
        raise ValueError("Timing comparison must use the same requested worker policy")
    if purpose == "ram_preload" and (not current.get("source_root") or current.get("source_root") != baseline.get("source_root")):
        raise ValueError("RAM preload comparison must use the same frozen implementation source")
    if purpose == "ram_preload":
        flags = (current.get("experimental_ram_preload"), baseline.get("experimental_ram_preload"))
        if any(type(flag) is not bool for flag in flags) or flags[0] == flags[1]:
            raise ValueError("RAM preload comparison requires one explicit ON and one explicit OFF case")
        if any(report.get("configured_preparation_pool_workers") is None
               or report.get("configured_normal_pool_workers") is None
               or report.get("requested_worker_policy") is None for report in (current, baseline)):
            raise ValueError("RAM preload comparison requires actual native pool and requested worker evidence")
    if purpose == "source_optimization" and current.get("experimental_ram_preload") != baseline.get("experimental_ram_preload"):
        raise ValueError("Source optimization comparison must use the same RAM preload setting")
    for report in (current, baseline):
        if "validated_params" not in report:
            raise ValueError("Timing comparison requires the complete validated parameter evidence")
    current_params = {key: value for key, value in current["validated_params"].items() if key != "experimental_ram_preload"}
    baseline_params = {key: value for key, value in baseline["validated_params"].items() if key != "experimental_ram_preload"}
    if current_params != baseline_params:
        raise ValueError("Timing comparison must preserve all validated settings apart from the labelled RAM preload option")
    if bool(current.get("downstream_status")) != bool(baseline.get("downstream_status")):
        raise ValueError("Timing comparison must include the same downstream scope")
    current_resources, baseline_resources = current["business_window_resources"], baseline["business_window_resources"]
    metrics = {"pipeline_business_elapsed_seconds": ratio(current["pipeline_business_elapsed_seconds"], baseline["pipeline_business_elapsed_seconds"])}
    for name in ("tree_rss_bytes", "tree_private_bytes", "observed_worker_count", "cpu_active_worker_count"):
        metrics[f"sampled_peak_{name}"] = ratio(current_resources["sampled_peaks"][name], baseline_resources["sampled_peaks"][name])
    for name in ("observed_process_tree_cpu_seconds", "mean_equivalent_logical_cores"):
        if current_resources[name] is not None and baseline_resources[name] is not None:
            metrics[name] = ratio(current_resources[name], baseline_resources[name])
    for kind in ("read_bytes", "write_bytes"):
        current_io = current_resources.get("observed_process_io_delta_bytes", {}).get(kind)
        baseline_io = baseline_resources.get("observed_process_io_delta_bytes", {}).get(kind)
        if current_io is not None and baseline_io is not None:
            metrics[f"observed_native_process_io_{kind}"] = ratio(current_io, baseline_io)
    current_storage, baseline_storage = current.get("generated_storage_footprint"), baseline.get("generated_storage_footprint")
    if current_storage is not None and baseline_storage is not None:
        if current_storage.get("stat_errors") or baseline_storage.get("stat_errors"):
            raise ValueError("Generated project storage comparison requires a complete file census")
        for name in ("size_bytes", "file_count"):
            metrics[f"final_generated_project_{name}"] = ratio(current_storage[name], baseline_storage[name])
    stages = {row["name"]: row["native_elapsed_seconds"] for row in baseline["stages"] if row.get("native_elapsed_seconds") is not None}
    return {"baseline_case": baseline["case_name"], "comparison_purpose": purpose, "metrics": metrics,
            "resource_comparison_scope": "Native business-window CPU/RAM/worker/IO resources; imports, start gates, artifact auditing and observer proof conversion are excluded. Storage size/count is the separate final generated-project census excluding observer evidence.",
            "actual_preparation_pool_workers": {"baseline": baseline.get("configured_preparation_pool_workers"), "current": current.get("configured_preparation_pool_workers")},
            "stage_comparisons": {row["name"]: ratio(row["native_elapsed_seconds"], stages[row["name"]]) for row in current["stages"] if row.get("native_elapsed_seconds") is not None and row["name"] in stages},
            "interpretation": "Descriptive case comparison only. Sampling, profiling, OS cache state, hardware/load and replicated trials determine practical confidence; no statistical significance is inferred."}


def summarize(args) -> dict:
    root = args.benchmark_root.resolve(strict=True)
    core = read_json(args.core_receipt) if args.core_receipt else {}
    full_core_proof_path = None
    if "observer_full_receipt_proof" in core:
        proof = core["observer_full_receipt_proof"]
        full_core_proof_path = args.core_receipt.with_name("run_receipt.json").resolve(strict=True)
        if (not isinstance(proof, dict) or set(proof) != {"path", "size_bytes", "sha256"}
                or not isinstance(proof["path"], str) or Path(proof["path"]).name != "run_receipt.json"
                or type(proof["size_bytes"]) is not int or proof["size_bytes"] < 0
                or not isinstance(proof["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", proof["sha256"])):
            raise ValueError("Malformed complete native proof binding in compact telemetry receipt")
        actual = file_identity(full_core_proof_path)
        if actual["size_bytes"] != proof["size_bytes"] or actual["sha256"] != proof["sha256"]:
            raise ValueError("Compact telemetry receipt does not bind its complete native proof")
    downstream = read_json(args.downstream_receipt) if args.downstream_receipt else {}
    stages = native_stages(core, read_lines(args.core_events)) if args.core_events else []
    if args.downstream_events:
        stages.extend(downstream_windows(downstream, read_lines(args.downstream_events)))
    resources = None
    business_resources = None
    stage_resources = None
    streams = []
    proofs = []
    logical = None
    launch_policies = set()
    for path in args.samples:
        path = path.resolve(strict=True)
        metadata = read_json(path.with_suffix(".metadata.json"))
        launch_path = path.parent / "launch.json"
        if launch_path.is_file():
            launch = read_json(launch_path)
            command = launch.get("command", [])
            if "--workers" in command:
                launch_policies.add(command[command.index("--workers") + 1])
            proofs.append(file_identity(launch_path))
        summary_path = path.with_suffix(".summary.json")
        summary = read_json(summary_path) if summary_path.is_file() else None
        count = metadata["hardware"]["cpu_logical_count"]
        if logical is not None and count != logical:
            raise ValueError("Resource streams have different logical CPU counts")
        logical = count
        if resources is None:
            resources = Resources(logical)
            business_resources = Resources(logical)
            stage_resources = [Resources(logical) for _stage in stages]
        previous_monotonic = previous_utc = None
        for sample in read_lines(path):
            now = sample["monotonic_time"]
            utc = timestamp(sample["utc"])
            if previous_monotonic is not None and (now < previous_monotonic or utc < previous_utc):
                raise ValueError(f"Resource timestamps moved backward: {path}")
            previous_monotonic, previous_utc = now, utc
            resources.add(sample)
            for stage, accumulator in zip(stages, stage_resources):
                add_window(accumulator, sample, stage)
                if business_stage(stage, bool(downstream)):
                    add_window(business_resources, sample, stage)
        streams.append({"samples": str(path), "sampler_metadata": metadata, "sampler_summary": summary})
        proofs.extend(file_identity(p) for p in (path, path.with_suffix(".metadata.json"), summary_path) if p.is_file())
    if resources is None:
        raise ValueError("At least one resource stream is required")
    if stages and not any(accumulator.interval_seconds or accumulator.samples for accumulator in stage_resources):
        raise ValueError("Native stage events do not overlap any resource samples; evidence files belong to different runs")
    configured = core.get("normal_pool_max_workers")
    requested_policy = core.get("requested_worker_policy")
    if len(launch_policies) > 1 or (requested_policy is not None and launch_policies and requested_policy not in launch_policies):
        raise ValueError("Native receipt and launch evidence disagree on requested worker policy")
    if requested_policy is None:
        requested_policy = next(iter(launch_policies), None)
    configured_preparation = preparation_workers(args.backend_log)
    for stage, accumulator in zip(stages, stage_resources):
        # Startup, thread preflight, and downstream are not the normal process pool.
        stage_workers = configured_preparation if stage["name"] == "kurtosis_preparation" else (configured if stage["name"] == "normal_processing" else None)
        stage["configured_process_pool_workers"] = stage_workers
        stage["included_in_business_time"] = business_stage(stage, bool(downstream))
        stage["sampled_resources"] = accumulator.payload(configured_workers=stage_workers)
    native_business = native_business_seconds(core, downstream)
    downstream_elapsed = downstream.get("worker_run_elapsed_seconds") or 0
    for path in (args.core_receipt, args.core_events, args.downstream_receipt, args.downstream_events, args.backend_log):
        if path:
            proofs.append(file_identity(path))
    if full_core_proof_path is not None:
        proofs.append(actual)
    report = {
        "schema": SCHEMA, "case_name": args.case_name, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark_root": str(root), "selected_recordings": core.get("recordings"),
        "source_root": core.get("source_root"), "requested_worker_policy": requested_policy,
        "selected_recording_job_count": len(core.get("recordings", [])),
        "experimental_ram_preload": core.get("validated_params", {}).get("experimental_ram_preload"),
        "validated_params": core.get("validated_params", {}),
        "profiling_diagnostic": core.get("profiling_diagnostic"), "configured_normal_pool_workers": configured,
        "functional_seed": core.get("functional_seed", False), "ambient_workload_note": core.get("ambient_workload_note"),
        "configured_preparation_pool_workers": configured_preparation,
        "core_status": core.get("status"), "downstream_status": downstream.get("status"),
        "benchmark_policy_action_elapsed_seconds_excluded": downstream.get("benchmark_policy_action_elapsed_seconds_excluded_from_worker_time", 0),
        "core_business_elapsed_seconds": native_business, "downstream_worker_elapsed_seconds": downstream_elapsed,
        "pipeline_business_elapsed_seconds": native_business + downstream_elapsed,
        "elapsed_time_scope": "Sum of native core stages excluding the explicitly labelled artifact audit and the embedded downstream wrapper when its native worker receipt is available, plus actual downstream worker.run duration counted once. Setup/imports outside native stages and review waiting are excluded.",
        "stages": stages, "resources": resources.payload(),
        "business_window_resources": business_resources.payload(),
        "generated_storage_footprint": core.get("generated_storage_footprint"),
        "resource_time_scope": "resources covers every sampler interval, including start gates/imports/artifact auditing. business_window_resources allocates only completed native core business stages and actual downstream worker intervals.",
        "resource_streams": streams, "evidence_files": proofs,
        "export_worker_timing_calls": export_timings(args.backend_log) if args.backend_log else [],
        "structured_worker_timing_calls": structured_worker_timings(core),
        "limitations": ["Process-tree RSS can count shared pages repeatedly; system-used RAM includes other applications.",
                        "Private commit on Windows and USS on POSIX are distinct metrics; labels are retained.",
                        "CPU/IO totals omit first observed process intervals and unobserved short-lived processes.",
                        "Phase resource deltas crossing boundaries are prorated assuming uniform activity within the observed interval.",
                        "Memory/worker means use endpoint samples weighted by interval duration; peaks are sampled, not guaranteed absolute maxima.",
                        "Progress windows measure event transitions and can include intervening provenance/guard work; they are not standalone business-method timings.",
                        "Disk counters are system-wide with unknown physical mapping; no NVMe or project-device utilization is claimed.",
                        "Disk-space probes report sampled volume occupancy, including other applications and cached files; they are not per-project peak allocations.",
                        "Multiple streams must describe distinct serialized process trees; overlapping streams are not deduplicated.",
                        "Descriptive measurements do not establish statistical significance."],
    }
    if args.baseline_summary:
        report["comparison"] = compare_summary(report, read_json(args.baseline_summary), purpose=getattr(args, "comparison_purpose", "source_optimization"))
    return report


def self_test() -> None:
    sample = {"utc": "2026-01-01T00:00:02+00:00", "sample_gap_seconds": 2.0, "tree_private_complete": True,
              "tree_rss_bytes": 100, "tree_private_bytes": 80, "observed_worker_count": 2, "cpu_active_worker_count": 1,
              "discovered_child_count": 2, "tree_cpu_percent_one_core": 150, "system_ram_used_bytes": 1000,
              "processes": [{"process_key": "1:1", "worker_id": "1:1", "cpu_percent_one_core": 150,
                             "private_metric": "private_commit", "io_read_bytes_delta": 20, "io_write_bytes_delta": 10}],
              "disk_deltas": {"disk0": {"read_bytes": 50, "write_bytes": 30}}}
    value = Resources(8)
    value.add(sample)
    output = value.payload(configured_workers=4)
    assert output["observed_process_tree_cpu_seconds"] == 3
    assert output["mean_cpu_percent_machine_logical_capacity"] == 18.75
    assert output["mean_active_worker_fraction_of_configured_pool"] == .25
    window = {"start_unix": timestamp("2026-01-01T00:00:01+00:00"), "finish_unix": timestamp("2026-01-01T00:00:02+00:00")}
    partial = Resources(8)
    add_window(partial, sample, window)
    assert partial.payload()["observed_process_tree_cpu_seconds"] == 1.5
    assert partial.payload()["observed_process_io_delta_bytes"]["read_bytes"] == 10
    assert ratio(2, 4)["percent_change"] == -50
    receipt = {"stage_seconds": {"setup": 1.0}}
    stages = native_stages(receipt, [{"utc": "2026-01-01T00:00:00Z", "phase": "setup", "event": "start"},
                                    {"utc": "2026-01-01T00:00:01Z", "phase": "setup", "event": "finish"}])
    assert stages[0]["event_window_seconds"] == stages[0]["native_elapsed_seconds"] == 1
    assert native_business_seconds({"stage_seconds": {"setup": 2, "downstream": 10, "artifact_audit_excluded_from_processing_time": 9}}, {"worker_run_elapsed_seconds": 7}) == 2
    assert not business_stage({"kind": "core_native_stage", "name": "downstream"}, True)
    assert business_stage({"kind": "downstream_native_worker", "name": "downstream_worker_attempt1"}, True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path)
    parser.add_argument("--case-name")
    parser.add_argument("--samples", type=Path, nargs="+")
    parser.add_argument("--core-receipt", type=Path)
    parser.add_argument("--core-events", type=Path)
    parser.add_argument("--downstream-receipt", type=Path)
    parser.add_argument("--downstream-events", type=Path)
    parser.add_argument("--backend-log", type=Path)
    parser.add_argument("--baseline-summary", type=Path)
    parser.add_argument("--comparison-purpose", choices=("source_optimization", "ram_preload"), default="source_optimization")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.self_test:
        self_test()
        LOG.info("pipeline_telemetry_self_test passed")
        return 0
    for name in ("benchmark_root", "case_name", "samples", "output"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required")
    if bool(args.core_events) != bool(args.core_receipt) or bool(args.downstream_events) != bool(args.downstream_receipt):
        parser.error("Each receipt must be paired with its events file")
    root = args.benchmark_root.resolve(strict=True)
    target = (args.output if args.output.is_absolute() else root / args.output).resolve(strict=False)
    if target == root or not target.is_relative_to(root):
        parser.error("--output must resolve beneath --benchmark-root")
    if target.exists():
        raise FileExistsError(target)
    report = summarize(args)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    LOG.info("pipeline_telemetry_summary_saved case=%s native_business_seconds=%.6f path=%s", args.case_name, report["pipeline_business_elapsed_seconds"], target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
