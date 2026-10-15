"""Sample a benchmark process tree without reading or modifying project data.

Outputs are streaming JSONL plus hardware/coverage JSON in an explicitly named
benchmark directory. Per-disk OS counters are system-wide and are not mapped to
a physical project device or interpreted as NVMe utilization.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import platform
import tempfile
import time
from uuid import uuid4

import psutil

LOG = logging.getLogger(__name__)
SCHEMA_VERSION = "pipeline_resource_samples_v1"
MAX_STOP_BYTES = 4096
MAX_PROCESSES = 1024
DISK_FIELDS = ("read_count", "write_count", "read_bytes", "write_bytes", "read_time", "write_time", "busy_time")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def output_path(root: Path, value: str | Path) -> Path:
    """Resolve an output beneath the explicit benchmark root, rejecting links."""
    root = root.resolve(strict=True)
    candidate = Path(value)
    target = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=False)
    if not target.is_relative_to(root) or target == root:
        raise ValueError(f"Output must remain beneath benchmark root: {target}")
    return target


def write_json_atomic(target: Path, value: dict) -> None:
    """Publish a new metadata/summary file; never overwrite an existing run."""
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            raise FileExistsError(target)
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def stop_snapshot(path: Path) -> tuple[tuple, dict] | None:
    """Read one bounded complete sentinel snapshot, accepting atomic publication."""
    try:
        before = path.stat()
        if before.st_size > MAX_STOP_BYTES:
            return None
        with path.open("rb") as stream:
            encoded = stream.read(MAX_STOP_BYTES + 1)
        after = path.stat()
        def stat_fields(stat):
            return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino
        if len(encoded) > MAX_STOP_BYTES or stat_fields(before) != stat_fields(after):
            return None
        decoded = json.loads(encoded)
        if not isinstance(decoded, dict):
            return None
        return (*stat_fields(after), hashlib.sha256(encoded).hexdigest()), decoded
    except (OSError, ValueError, UnicodeError):
        return None


class StopSentinel:
    def __init__(self, path: Path, token: str) -> None:
        self.path = path
        self.token = token
        self.initial = stop_snapshot(path)

    def requested(self) -> bool:
        current = stop_snapshot(self.path)
        return bool(current is not None and current != self.initial and current[1].get("stop_token") == self.token)


def nonnegative_delta(current: int | float | None, previous: int | float | None):
    if current is None or previous is None or current < previous:
        return None
    return current - previous


def process_deltas(current: dict, previous: dict | None, elapsed: float | None) -> dict:
    result = {"cpu_percent_one_core": None, "io_read_bytes_delta": None, "io_write_bytes_delta": None}
    if previous is None or current["process_key"] != previous["process_key"] or elapsed is None or elapsed <= 0:
        return result
    cpu = nonnegative_delta(current["cpu_seconds"], previous["cpu_seconds"])
    result["cpu_percent_one_core"] = None if cpu is None else 100.0 * cpu / elapsed
    for key in ("read", "write"):
        result[f"io_{key}_bytes_delta"] = nonnegative_delta(current.get(f"io_{key}_bytes"), previous.get(f"io_{key}_bytes"))
    return result


def command_summary(command: list[str]) -> dict:
    """Keep only executable/module/script identity, excluding paths and arguments."""
    if not command:
        return {}
    value = {"executable_name": Path(command[0]).name}
    if "-m" in command and command.index("-m") + 1 < len(command):
        value["python_module"] = command[command.index("-m") + 1]
    elif len(command) > 1 and not command[1].startswith("-"):
        value["script_name"] = Path(command[1]).name
    if any("multiprocessing.spawn" in part or "spawn_main" in part for part in command):
        value["worker_kind"] = "spawned_python_worker"
    elif any("multiprocessing.resource_tracker" in part for part in command):
        value["worker_kind"] = "resource_tracker"
    return value


def process_sample(process: psutil.Process, *, root_pid: int, include_identity: bool) -> dict:
    process = psutil.Process(process.pid)
    with process.oneshot():
        created = process.create_time()
        cpu = process.cpu_times()
        memory = process.memory_info()
        try:
            io = process.io_counters()
        except (psutil.Error, AttributeError):
            io = None
        sample = {
            "pid": process.pid, "parent_pid": process.ppid(), "creation_time_unix": created,
            "process_key": f"{process.pid}:{created:.9f}", "role": "root" if process.pid == root_pid else "child",
            "cpu_seconds": cpu.user + cpu.system, "rss_bytes": memory.rss,
            "vms_bytes": memory.vms, "thread_count": process.num_threads(),
            "io_read_bytes": None if io is None else io.read_bytes,
            "io_write_bytes": None if io is None else io.write_bytes,
            "private_bytes": getattr(memory, "private", None), "private_metric": "private_commit" if hasattr(memory, "private") else None,
        }
        if include_identity:
            sample["name"] = process.name()
            sample["command_identity"] = command_summary(process.cmdline())
    if sample["private_bytes"] is None:
        try:
            sample["private_bytes"] = process.memory_full_info().uss
            sample["private_metric"] = "unique_set_size"
        except (psutil.Error, AttributeError):
            pass
    if psutil.Process(process.pid).create_time() != created:
        raise psutil.NoSuchProcess(process.pid, msg="Process PID changed during sampling")
    sample["worker_id"] = sample["process_key"] if sample.get("command_identity", {}).get("worker_kind") == "spawned_python_worker" else None
    return sample


def disk_counters() -> dict:
    values = psutil.disk_io_counters(perdisk=True, nowrap=True) or {}
    return {name: {field: getattr(counter, field, None) for field in DISK_FIELDS} for name, counter in values.items()}


def disk_deltas(current: dict, previous: dict | None) -> dict:
    return {name: {field: nonnegative_delta(value, None if previous is None else previous.get(name, {}).get(field)) for field, value in counters.items()} for name, counters in current.items()}


def disk_space(root: Path) -> dict:
    try:
        usage = psutil.disk_usage(str(root))
        return {"root": str(root), "total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free, "percent_used": usage.percent}
    except (OSError, psutil.Error) as exc:
        return {"root": str(root), "error": str(exc)}


def hardware_metadata(roots: dict[str, Path]) -> dict:
    memory = psutil.virtual_memory()
    try:
        frequency = psutil.cpu_freq()
    except (OSError, psutil.Error, NotImplementedError):
        frequency = None
    return {
        "platform": platform.platform(), "python": platform.python_version(), "psutil": psutil.__version__,
        "cpu_logical_count": psutil.cpu_count(logical=True), "cpu_physical_count": psutil.cpu_count(logical=False),
        "cpu_frequency_mhz": None if frequency is None else frequency._asdict(), "ram_total_bytes": memory.total,
        "disk_counter_mapping": "unknown; OS per-disk labels are recorded without physical-device or project-device attribution",
        "disk_spaces": {name: disk_space(root) for name, root in roots.items()},
        "metric_notes": {
            "cpu": "100 percent is one logical core; process-tree sums can exceed 100 percent",
            "rss": "Process-tree RSS sum can double-count shared pages; system-used RAM is recorded separately",
            "private": "Windows private commit and POSIX unique set size are distinct metrics, labelled per sample",
            "disk": "System-wide per-disk counters include other applications; read/write/busy times are OS counters, not NVMe utilization",
            "process_io": "Process IO counters are OS-accounted process activity, not necessarily physical disk transfers",
            "sampling": "Sampled peaks and CPU-active child counts can miss short-lived processes; first per-process interval has no CPU delta",
        },
    }


def sample_tree(root_process: psutil.Process, expected_creation: float, previous: dict, previous_time: float | None, include_identity: bool) -> tuple[dict, dict]:
    started = time.monotonic()
    # psutil.Process caches create_time; use a fresh handle to detect PID reuse.
    if psutil.Process(root_process.pid).create_time() != expected_creation:
        raise RuntimeError("Root PID was reused by a different process.")
    children = root_process.children(recursive=True)
    processes = [root_process, *children[:MAX_PROCESSES - 1]]
    values, errors = [], []
    state = {}
    elapsed = None if previous_time is None else started - previous_time
    for process in processes:
        try:
            value = process_sample(process, root_pid=root_process.pid, include_identity=include_identity)
            if process.pid == root_process.pid and value["creation_time_unix"] != expected_creation:
                raise RuntimeError("Root PID changed while sampling.")
            value.update(process_deltas(value, previous.get(value["process_key"]), elapsed))
            values.append(value)
            state[value["process_key"]] = value
        except psutil.Error as exc:
            errors.append({"pid": process.pid, "error_type": type(exc).__name__})
    memory = psutil.virtual_memory()
    return {
        "utc": utc_now(), "monotonic_time": started, "sample_gap_seconds": elapsed,
        "processes": values, "process_errors": errors, "discovered_child_count": len(children),
        "process_limit_omissions": max(0, len(children) + 1 - MAX_PROCESSES),
        "tree_rss_bytes": sum(value["rss_bytes"] for value in values),
        "tree_private_bytes": sum(value["private_bytes"] or 0 for value in values),
        "tree_private_complete": all(value["private_bytes"] is not None for value in values),
        "tree_cpu_percent_one_core": sum(value["cpu_percent_one_core"] or 0 for value in values),
        "cpu_active_child_count": sum(value["role"] == "child" and (value["cpu_percent_one_core"] or 0) > 1.0 for value in values),
        "observed_worker_count": sum(value["worker_id"] is not None for value in values),
        "cpu_active_worker_count": sum(value["worker_id"] is not None and (value["cpu_percent_one_core"] or 0) > 1.0 for value in values),
        "system_ram_used_bytes": memory.used, "system_ram_available_bytes": memory.available,
        "sampling_duration_seconds": time.monotonic() - started,
    }, state


def monitor(args) -> Path:
    benchmark_root = args.benchmark_root.resolve(strict=True)
    if not args.benchmark_root.is_absolute() or not benchmark_root.is_dir():
        raise ValueError("--benchmark-root must be an explicit existing absolute directory.")
    roots = {"project": args.project_root.resolve(strict=True), "scratch": args.scratch_root.resolve(strict=True)}
    if any(not root.is_dir() for root in roots.values()):
        raise ValueError("Disk-space probe roots must be existing directories.")
    output = output_path(benchmark_root, args.output)
    metadata_path = output_path(benchmark_root, output.with_suffix(".metadata.json"))
    summary_path = output_path(benchmark_root, output.with_suffix(".summary.json"))
    stop_path = output_path(benchmark_root, args.stop_file)
    if any(path.exists() for path in (output, metadata_path, summary_path)):
        raise FileExistsError("Sampler output files already exist; select a fresh output path.")
    root_process = psutil.Process(args.pid)
    created = root_process.create_time()
    token = args.stop_token or uuid4().hex
    sentinel = StopSentinel(stop_path, token)
    started = time.monotonic()
    metadata = {"schema_version": SCHEMA_VERSION, "started_at_utc": utc_now(), "root_pid": args.pid,
                "root_creation_time_unix": created, "interval_seconds": args.interval,
                "stop_file": str(stop_path), "stop_token": token,
                "stop_protocol": "Atomically publish a new JSON object containing stop_token; a pre-existing unchanged sentinel is ignored",
                "hardware": hardware_metadata(roots)}
    write_json_atomic(metadata_path, metadata)
    output.parent.mkdir(parents=True, exist_ok=True)
    previous, previous_time, previous_disks = {}, None, None
    samples = errors = gaps = omissions = 0
    peaks = {"tree_rss_bytes": 0, "tree_private_bytes": 0, "tree_cpu_percent_one_core": 0.0,
             "cpu_active_child_count": 0, "discovered_child_count": 0, "system_ram_used_bytes": 0,
             "observed_worker_count": 0, "cpu_active_worker_count": 0,
             "sample_gap_seconds": 0.0, "sampling_duration_seconds": 0.0}
    totals = {"process_io_read_bytes": 0, "process_io_write_bytes": 0}
    reason = "root_exited"
    failure = None
    try:
        with output.open("x", encoding="utf-8", buffering=64 * 1024) as stream:
            while True:
                if sentinel.requested():
                    reason = "fresh_stop_sentinel"
                    break
                if args.max_seconds is not None and time.monotonic() - started >= args.max_seconds:
                    reason = "max_duration"
                    break
                try:
                    sample, previous = sample_tree(root_process, created, previous, previous_time, not args.no_process_identity)
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    break
                disks = disk_counters()
                sample["disk_counters"] = disks
                sample["disk_deltas"] = disk_deltas(disks, previous_disks)
                sample["disk_spaces"] = {name: disk_space(root) for name, root in roots.items()}
                sample["elapsed_seconds"] = sample["monotonic_time"] - started
                previous_time, previous_disks = sample["monotonic_time"], disks
                samples += 1
                errors += len(sample["process_errors"])
                omissions += sample["process_limit_omissions"]
                if (sample["sample_gap_seconds"] or 0) > args.interval * 1.5:
                    gaps += 1
                for key in peaks:
                    peaks[key] = max(peaks[key], sample[key] or 0)
                for value in sample["processes"]:
                    for key in ("read", "write"):
                        totals[f"process_io_{key}_bytes"] += value[f"io_{key}_bytes_delta"] or 0
                stream.write(json.dumps(sample, separators=(",", ":"), allow_nan=False) + "\n")
                stream.flush()
                remaining = args.interval - (time.monotonic() - sample["monotonic_time"])
                if remaining > 0:
                    time.sleep(remaining)
    except KeyboardInterrupt:
        reason = "interrupt"
    except (OSError, psutil.Error, RuntimeError) as exc:
        reason, failure = "sampling_error", str(exc)
        LOG.exception("Resource sampling failed")
    finally:
        summary = {"schema_version": SCHEMA_VERSION, "finished_at_utc": utc_now(), "elapsed_seconds": time.monotonic() - started,
                   "stop_reason": reason, "error": failure, "sample_count": samples,
                   "coverage": {"process_read_errors": errors, "sample_gaps_over_1_5_intervals": gaps,
                                "process_limit_omissions": omissions, "short_lived_processes_can_be_missed": True,
                                "first_process_intervals_excluded_from_cpu_and_io_deltas": True},
                   "sampled_peaks": peaks, "observed_process_io_deltas": totals,
                   "final_disk_spaces": {name: disk_space(root) for name, root in roots.items()}}
        write_json_atomic(summary_path, summary)
    if failure:
        raise RuntimeError(failure)
    LOG.info("Resource samples saved: %s (%d samples, %s)", output, samples, reason)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("resource_samples.jsonl"))
    parser.add_argument("--stop-file", type=Path, default=Path("stop_resource_sampler.json"))
    parser.add_argument("--stop-token", help="Optional caller-chosen fresh token; otherwise read it from metadata.")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--no-process-identity", action="store_true")
    args = parser.parse_args()
    if args.pid <= 0 or not .1 <= args.interval <= 60 or (args.max_seconds is not None and (not math.isfinite(args.max_seconds) or args.max_seconds <= 0)):
        parser.error("PID and duration must be positive; interval must be between 0.1 and 60 seconds.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    monitor(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
