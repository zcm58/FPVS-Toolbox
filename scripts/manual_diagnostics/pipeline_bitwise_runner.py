"""Run canonical preprocessing backends on an explicitly isolated project clone.

The caller owns fixture creation and serialized baseline/candidate launches.
No Qt application, widget or QObject is instantiated. Source imports are chosen
before numerical libraries load. Manual marker/electrode/burden review is never
fabricated: unresolved choices produce a paused receipt and exit code 2.
Saved extreme-only and auto-all policies use the same public models as the
GUI. Optional profiling is diagnostic; never use it as a timing trial.
Downstream publication/FHC binding belongs to the coordinating harness.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import cProfile
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from fractions import Fraction
from functools import wraps
import hashlib
import importlib.util
import json
import logging
import multiprocessing
import os
from pathlib import Path
import re
import struct
import sys
import threading
from time import perf_counter
from time import sleep
from time import time_ns
import zipfile

LOGGER = logging.getLogger("pipeline_bitwise_runner")
PROFILE_DIRECTORY_ENV = "FPVS_PIPELINE_DIAGNOSTIC_PROFILE_DIRECTORY"
_CHILD_PROFILE = None
_NATIVE_NORMAL_INITIALIZER = None
_NATIVE_REVIEW_INITIALIZER = None
_PARENT_DIAGNOSTIC_PROFILE = None


def _write_profile(profiler, directory: Path, role: str, token: str, metadata: dict) -> None:
    """Keep diagnostic observer output separate from scientific artifacts."""
    profiler.disable()
    path = directory / f"{role}-pid{os.getpid()}-{token}.pstats"
    profiler.dump_stats(path)
    path.with_suffix(".json").write_text(json.dumps({
        "role": role, "pid": os.getpid(), "profile_path": str(path), **metadata,
    }, indent=2) + "\n", encoding="utf-8")


def _finish_child_profile(directory: Path, role: str, started: float, started_utc: str) -> None:
    if _CHILD_PROFILE is not None:
        _write_profile(_CHILD_PROFILE, directory, role, "worker", {
            "started_utc": started_utc, "elapsed_seconds": perf_counter() - started,
            "coverage": "Initializer through cooperative worker shutdown. Python3.13 cProfile callbacks can include auxiliary threads process-wide; overlapping cumulative times must not be summed as wall time.",
        })


def _start_child_profile(role: str) -> None:
    from multiprocessing.util import Finalize

    global _CHILD_PROFILE
    directory = Path(os.environ[PROFILE_DIRECTORY_ENV])
    started, started_utc = perf_counter(), datetime.now(timezone.utc).isoformat()
    _CHILD_PROFILE = cProfile.Profile()
    _CHILD_PROFILE.enable()
    # multiprocessing can exit without regular atexit callbacks. Its own finalizer
    # writes after native task/cache owners have had their shutdown opportunity.
    Finalize(None, _finish_child_profile, args=(directory, role, started, started_utc), exitpriority=-100)


def _profile_normal_worker_init() -> None:
    from Main_App.workers import process_runner

    _start_child_profile("normal_worker")
    initializer = _NATIVE_NORMAL_INITIALIZER or process_runner._worker_init
    initializer()


def _profile_review_worker_init(cancel_event, progress_queue) -> None:
    from Main_App.workers import kurtosis_review_process

    _start_child_profile("review_worker")
    initializer = _NATIVE_REVIEW_INITIALIZER or kurtosis_review_process._review_worker_init
    initializer(cancel_event, progress_queue)


@contextmanager
def diagnostic_profile_hooks(enabled: bool, directory: Path, parent_profiler=None):
    """Wrap public-owner scheduling seams only for explicitly profiled runs."""
    if not enabled:
        yield
        return
    from Main_App.processing import preflight_qc
    from Main_App.workers import kurtosis_review_process, process_runner

    global _NATIVE_NORMAL_INITIALIZER, _NATIVE_REVIEW_INITIALIZER, _PARENT_DIAGNOSTIC_PROFILE
    directory.mkdir(parents=True, exist_ok=True)
    original_preflight = preflight_qc._scan_one_preflight_file
    original_normal = process_runner._worker_init
    original_review = kurtosis_review_process._review_worker_init
    original_environment = os.environ.get(PROFILE_DIRECTORY_ENV)
    claim_lock = threading.Lock()
    claimed_preflight = False

    @wraps(original_preflight)
    def profile_preflight(*args, **kwargs):
        nonlocal claimed_preflight
        with claim_lock:
            capture = not claimed_preflight
            claimed_preflight = True
        if not capture:
            return original_preflight(*args, **kwargs)
        profiler = cProfile.Profile()
        started, started_utc = perf_counter(), datetime.now(timezone.utc).isoformat()
        token = f"thread{threading.get_ident()}-job{time_ns()}"
        profiler.enable()
        try:
            return original_preflight(*args, **kwargs)
        finally:
            _write_profile(profiler, directory, "preflight_thread", token, {
                "thread_id": threading.get_ident(), "thread_name": threading.current_thread().name,
                "started_utc": started_utc, "elapsed_seconds": perf_counter() - started,
                "recording_id": str(getattr(args[0], "processing_id", "")) if args else "",
                "coverage": "Process-wide cProfile window bounded by one first-claimed native preflight task, including semaphore waits. Python3.13 also captures concurrent task callbacks: this is not an isolated per-file timing, and overlapping cumulative times must not be summed as wall time. Remaining native tasks are unwrapped.",
            })

    _NATIVE_NORMAL_INITIALIZER = original_normal
    _NATIVE_REVIEW_INITIALIZER = original_review
    _PARENT_DIAGNOSTIC_PROFILE = parent_profiler
    preflight_qc._scan_one_preflight_file = profile_preflight
    process_runner._worker_init = _profile_normal_worker_init
    kurtosis_review_process._review_worker_init = _profile_review_worker_init
    os.environ[PROFILE_DIRECTORY_ENV] = str(directory)
    try:
        yield
    finally:
        preflight_qc._scan_one_preflight_file = original_preflight
        process_runner._worker_init = original_normal
        kurtosis_review_process._review_worker_init = original_review
        _NATIVE_NORMAL_INITIALIZER = _NATIVE_REVIEW_INITIALIZER = _PARENT_DIAGNOSTIC_PROFILE = None
        if original_environment is None:
            os.environ.pop(PROFILE_DIRECTORY_ENV, None)
        else:
            os.environ[PROFILE_DIRECTORY_ENV] = original_environment


@contextmanager
def pause_parent_for_preflight_profile():
    """Avoid concurrent cProfile monitoring-tool ownership in Python3.13."""
    profiler = _PARENT_DIAGNOSTIC_PROFILE
    if profiler is not None:
        profiler.disable()
    try:
        yield
    finally:
        if profiler is not None:
            profiler.enable()


def run_downstream(args, receipt: dict, events_path: Path) -> int:
    """Call the existing native-method probe in this same process tree."""
    original_manifest = (args.project_root / "project.json").read_bytes()
    preimage_path = args.output_dir / "project_before_downstream.json"
    with preimage_path.open("xb") as stream:
        stream.write(original_manifest)
    preimage_sha = hashlib.sha256(original_manifest).hexdigest()
    receipt["project_manifest_before_downstream_preimage"] = {
        "path": str(preimage_path), "sha256": preimage_sha, "size_bytes": len(original_manifest),
    }
    path = Path(__file__).with_name("pipeline_downstream_probe.py")
    name = "_pipeline_bitwise_downstream_probe"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load diagnostic downstream binding: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    target, native_events = args.output_dir / "downstream_receipt.json", args.output_dir / "downstream_events.jsonl"
    exit_code = module.run_probe(argparse.Namespace(
        source_root=args.source_root, workspace_root=args.workspace_root, project_root=args.project_root,
        scratch_root=args.scratch_root, output=target, events=native_events, expected_worker_sha256=None,
        benchmark_review_policy=args.benchmark_review_policy,
    ))
    downstream = json.loads(target.read_text(encoding="utf-8"))
    if downstream.get("project_manifest_before_sha256") != preimage_sha:
        raise ValueError("Native downstream starting manifest does not match its archived preimage")
    receipt["downstream"] = downstream
    start_time = datetime.fromisoformat(downstream["started_at_utc"]).timestamp()
    with events_path.open("a", encoding="utf-8") as stream:
        for line in native_events.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            utc = datetime.fromtimestamp(start_time + event["elapsed_seconds"], timezone.utc).isoformat()
            stream.write(json.dumps({"utc": utc, "phase": "downstream_native", "event": "signal",
                                     "source": "pipeline_downstream_probe", **event}) + "\n")
    return exit_code


class ReviewRequired(RuntimeError):
    """The actual workflow needs a decision the diagnostic cannot authorize."""


def checked(path: Path, root: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError(f"Expected a dedicated path beneath {root}: {resolved}")
    return resolved


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def storage_footprint(project_root: Path, evidence_root: Path) -> dict:
    """Post-run stat-only census of generated project files, excluding observers."""
    groups = {}
    errors = []
    for path in project_root.rglob("*"):
        if path.is_relative_to(evidence_root) or path.is_symlink():
            continue
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
            continue
        name = path.relative_to(project_root).parts[0]
        group = groups.setdefault(name, {"file_count": 0, "size_bytes": 0})
        group["file_count"] += 1
        group["size_bytes"] += size
    return {"file_count": sum(value["file_count"] for value in groups.values()),
            "size_bytes": sum(value["size_bytes"] for value in groups.values()),
            "by_project_top_level": groups, "stat_errors": errors,
            "scope": "Post-run file sizes beneath the isolated project root; benchmark observer evidence and symbolic links excluded. Raw input copies live outside this generated project root. This is final footprint, not peak allocated disk space."}


def serialize(value):
    """Retain float bits and array dtype/shape/bytes for independent comparison."""
    import numpy as np

    if is_dataclass(value):
        return {field.name: serialize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        return {"array_dtype": value.dtype.str, "array_shape": list(value.shape),
                "array_strides": list(value.strides),
                "array_c_contiguous": bool(value.flags.c_contiguous),
                "array_f_contiguous": bool(value.flags.f_contiguous),
                "array_sha256": hashlib.sha256(array.tobytes()).hexdigest()}
    if isinstance(value, np.generic):
        return serialize(value.item())
    if isinstance(value, float):
        return {"float64_bits": struct.pack(">d", value).hex(), "display": repr(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Fraction):
        return {"numerator": value.numerator, "denominator": value.denominator}
    if isinstance(value, dict):
        return {str(key): serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((serialize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Unsupported evidence value: {type(value).__name__}")


def defer_native_proof(receipt: dict, key: str, value) -> None:
    """Retain the native object without creating a duplicate JSON representation."""
    receipt.setdefault("_deferred_native_proofs", {})[key] = value


def json_proof_parts(value, *, native=False):
    """Yield the existing observer JSON structure without duplicating native trees."""
    import numpy as np

    if native and is_dataclass(value):
        yield "{"
        for index, field in enumerate(fields(value)):
            if index:
                yield ","
            yield json.dumps(field.name, ensure_ascii=False)
            yield ":"
            yield from json_proof_parts(getattr(value, field.name), native=True)
        yield "}"
    elif native and isinstance(value, np.ndarray):
        yield from json_proof_parts(serialize(value))
    elif native and isinstance(value, np.generic):
        yield from json_proof_parts(value.item(), native=True)
    elif native and isinstance(value, (float, Path, Fraction, set, frozenset)):
        yield from json_proof_parts(serialize(value))
    elif isinstance(value, dict):
        yield "{"
        for index, (key, item) in enumerate(value.items()):
            if index:
                yield ","
            yield json.dumps(str(key), ensure_ascii=False)
            yield ":"
            yield from json_proof_parts(item, native=native)
        yield "}"
    elif isinstance(value, (list, tuple)):
        yield "["
        for index, item in enumerate(value):
            if index:
                yield ","
            yield from json_proof_parts(item, native=native)
        yield "]"
    elif value is None or isinstance(value, (str, int, float, bool)):
        yield json.dumps(value, ensure_ascii=False, allow_nan=False)
    else:
        raise TypeError(f"Unsupported evidence value: {type(value).__name__}")


class JsonProofWriter:
    """Keep encoded output and hashing bounded independently of receipt size."""

    def __init__(self, stream, buffer_bytes=256 * 1024):
        self.stream, self.buffer_bytes = stream, buffer_bytes
        self.pending = bytearray()
        self.sha256, self.size_bytes = hashlib.sha256(), 0
        self.maximum_write_bytes = 0

    def append(self, part):
        encoded = part.encode("utf-8")
        for start in range(0, len(encoded), self.buffer_bytes):
            self.pending.extend(encoded[start:start + self.buffer_bytes])
            if len(self.pending) >= self.buffer_bytes:
                self.flush()

    def flush(self):
        if not self.pending:
            return
        self.stream.write(self.pending)
        self.sha256.update(self.pending)
        self.size_bytes += len(self.pending)
        self.maximum_write_bytes = max(self.maximum_write_bytes, len(self.pending))
        self.pending.clear()

    def value(self, value, *, native=False):
        for part in json_proof_parts(value, native=native):
            self.append(part)


def telemetry_receipt(receipt: dict, pending: dict, full_proof: dict) -> dict:
    """Retain the measured facts while the complete scientific proof stays separate."""
    names = {
        "version", "started_utc", "finished_utc", "native_runner_returned_utc", "source_root", "project_root",
        "recordings", "profiling_diagnostic", "functional_seed", "ambient_workload_note", "requested_worker_policy",
        "normal_pool_max_workers", "validated_params", "stage_seconds", "status", "error", "pause_reason",
        "generated_storage_footprint", "initial_project_sha256", "final_project_sha256",
    }
    result = {key: value for key, value in receipt.items() if key in names}
    result["version"] = "pipeline_bitwise_telemetry_receipt_v1"
    result["observer_complete_receipt_version"] = receipt.get("version")
    if "processing_result" in pending:
        result["processing_result"] = {"results": [
            {key: row[key] for key in ("file", "timings_ms", "export_timing_records") if key in row}
            for row in pending["processing_result"].get("results", [])
        ]}
    result["observer_full_receipt_proof"] = full_proof
    result["observer_receipt_scope"] = "Compact native timing/settings/status/worker facts; scientific values remain in the SHA/size-bound complete run receipt."
    return result


def write_native_receipt(receipt: dict, events_path: Path, target: Path, telemetry_target: Path) -> dict:
    """Stream all proof conversion after native work, with a small bound telemetry view."""
    pending = receipt.pop("_deferred_native_proofs", {})
    if target.exists() or telemetry_target.exists():
        raise FileExistsError("Observer receipts must be captured to fresh paths")
    name = "observer_proof_conversion_excluded_from_processing_time"
    started = perf_counter()
    with events_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "phase": name, "event": "start"}) + "\n")
    try:
        with target.open("xb") as stream:
            writer = JsonProofWriter(stream)
            writer.append("{")
            first = True
            for key, value in receipt.items():
                if key in {"stage_seconds", "finished_utc"}:
                    continue
                if not first:
                    writer.append(",")
                first = False
                writer.value(key)
                writer.append(":")
                writer.value(value)
            for key, value in pending.items():
                if not first:
                    writer.append(",")
                first = False
                writer.value(key)
                writer.append(":")
                writer.value(value, native=True)
            receipt.setdefault("stage_seconds", {})[name] = perf_counter() - started
            receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
            for key in ("stage_seconds", "finished_utc"):
                if not first:
                    writer.append(",")
                first = False
                writer.value(key)
                writer.append(":")
                writer.value(receipt[key])
            writer.append("}\n")
            writer.flush()
        proof = {"path": str(target.resolve()), "size_bytes": writer.size_bytes, "sha256": writer.sha256.hexdigest()}
        with telemetry_target.open("xb") as stream:
            compact_writer = JsonProofWriter(stream)
            compact_writer.value(telemetry_receipt(receipt, pending, proof))
            compact_writer.append("\n")
            compact_writer.flush()
        return proof
    finally:
        with events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "phase": name, "event": "finish"}) + "\n")


def validate_clone(manifest: dict, project_root: Path, workspace_root: Path) -> None:
    results = Path(manifest.get("results_folder", "."))
    results = (project_root / results).resolve() if not results.is_absolute() else results.resolve()
    if not results.is_relative_to(project_root):
        raise ValueError("Results must stay inside the isolated project clone")
    for value in (manifest.get("subfolders") or {}).values():
        target = Path(value)
        target = (results / target).resolve() if not target.is_absolute() else target.resolve()
        if target == project_root or not target.is_relative_to(project_root):
            raise ValueError(f"Output subfolder escapes the clone: {target}")
    inputs = [manifest.get("input_folder")]
    inputs.extend(value.get("raw_input_folder") for value in (manifest.get("groups") or {}).values())
    inputs.extend(value.get("raw_input_folder") for value in (manifest.get("recording_sources") or {}).values())
    inputs.extend(value.get("raw_file") for value in (manifest.get("recordings") or {}).values())
    for value in filter(None, inputs):
        target = Path(value)
        target = (project_root / target).resolve() if not target.is_absolute() else target.resolve()
        if not target.is_relative_to(workspace_root):
            raise ValueError(f"Raw input is outside the explicitly isolated workspace: {target}")


def replay_marker_review(scan, infos, params, project_root, event_map, workers, progress, replay_path, receipt):
    """Rebind actual prior human receipts after verifying unchanged marker evidence.

    The replay file inventories original receipts from an immutable study copy.
    Public production models bind each receipt to the copied input path. No new
    review decision, reason, reviewer identity or human review time is invented.
    """
    from Main_App.gui.marker_occurrence_review import (
        build_marker_review_decision, collect_marker_occurrence_reviews,
        merge_marker_review_decision, merge_rescanned_results,
    )
    from Main_App.processing.preflight_qc import scan_preprocessing_qc

    payload = json.loads(replay_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "pipeline_marker_review_replay_v1":
        raise ValueError("Unsupported marker-review replay inventory")
    inventoried = []
    for proof in payload["source_evidence"]:
        evidence_path = checked(Path(proof["frozen_evidence_path"]), replay_path.parent)
        if file_hash(evidence_path) != proof["sha256"]:
            raise ValueError("Frozen original marker evidence checksum changed")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        inventoried.extend(span["decision_payload"] for span in evidence["key"]["event_plan"]["approved_occurrences"]
                           if span.get("decision_payload") is not None)
    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if sorted(map(canonical, inventoried)) != sorted(map(canonical, payload["original_decisions"])):
        raise ValueError("Replay decisions do not exactly match frozen original evidence receipts")
    expected = {}
    for original in payload["original_decisions"]:
        key = (original["recording_id"], original["occurrence_key"])
        if key in expected:
            raise ValueError("Duplicate original marker-review receipt")
        if original.get("decision") != "exclude_occurrence" or original.get("reviewer_state") != "explicit_gui_review":
            raise ValueError("Marker replay only accepts existing explicit GUI occurrence exclusions")
        expected[key] = original
    items = collect_marker_occurrence_reviews(scan)
    if {(item.recording_id, item.occurrence_key) for item in items} != set(expected):
        raise ReviewRequired("Fresh unresolved marker findings do not exactly match the prior human receipts")
    decisions = {}
    affected = []
    proofs = []
    for item in items:
        original = expected[(item.recording_id, item.occurrence_key)]
        for name, actual in (
            ("reviewed_marker_plan_fingerprint", item.marker_plan_fingerprint),
            ("reviewed_occurrence_fingerprint", item.occurrence_fingerprint),
            ("participant_id", item.participant_id), ("session_id", item.session_id),
            ("condition_code", item.condition_code), ("repetition_index", item.repetition_index),
        ):
            if original.get(name) != actual:
                raise ReviewRequired(f"Original marker-review evidence changed for {item.recording_id}: {name}")
        rebound = build_marker_review_decision(
            item, original["decision"], reason=original["reason"],
            reviewed_at_utc=original["reviewed_at_utc"],
        )
        decisions = merge_marker_review_decision(
            decisions, file_path=item.path, occurrence_key=item.occurrence_key, decision=rebound,
        )
        if item.path not in affected:
            affected.append(item.path)
        proofs.append({"original_receipt": original, "copied_input_receipt": rebound})
    params["_fpvs_marker_review_decisions_by_file"] = decisions
    affected_keys = {str(path.resolve()).casefold() for path in affected}
    selected = [info for info in infos if str(info.path.resolve()).casefold() in affected_keys]
    rescanned = scan_preprocessing_qc(
        selected, params, project_root=project_root, event_map=event_map,
        max_workers=workers, progress=progress,
    )
    if rescanned.cancelled:
        raise ReviewRequired("Marker receipt replay rescan was cancelled")
    from dataclasses import replace
    result = replace(
        scan, results=merge_rescanned_results(scan.results, rescanned.results, affected_paths=affected),
        project_grid_observations=rescanned.project_grid_observations or scan.project_grid_observations,
    )
    receipt["marker_review_replay"] = {
        "inventory_path": str(replay_path), "inventory_sha256": file_hash(replay_path),
        "action": "Rebound existing human exclusions to byte-identical copied inputs after matching fresh scientific marker fingerprints",
        "new_human_review": False, "receipts": proofs,
    }
    return result


def validated_params(project) -> dict:
    """Mirror build_validated_params' GUI-to-backend key conversion."""
    from Main_App.projects import (
        normalize_preprocessing_settings,
        require_removed_electrode_detection_choice_ready,
        validate_protocol_condition_codes,
    )

    project.refresh_electrode_geometry_settings()
    normalized = normalize_preprocessing_settings(project.preprocessing)
    require_removed_electrode_detection_choice_ready(normalized)
    protocol = project.frequency_protocol
    if protocol is None or not protocol.is_ready:
        raise ReviewRequired("A confirmed project frequency protocol is required")
    validate_protocol_condition_codes(protocol, project.event_map.values())
    converted = {
        "electrode_montage": normalized["electrode_montage"],
        "electrode_mapping_profile": normalized["electrode_mapping_profile"],
        "low_pass": float(normalized["low_pass"]), "high_pass": float(normalized["high_pass"]),
        "downsample": int(normalized["downsample"]), "downsample_rate": int(normalized["downsample"]),
        "line_noise_filter_enabled": bool(normalized["line_noise_filter_enabled"]),
        "line_noise_frequency_hz": int(normalized["line_noise_frequency_hz"]),
        "reject_thresh": float(normalized["rejection_z"]),
        "ref_channel1": normalized.get("ref_chan1") or None,
        "ref_channel2": normalized.get("ref_chan2") or None,
        "max_idx_keep": int(normalized["max_chan_idx_keep"]),
        "max_bad_channels_alert_thresh": int(normalized["max_bad_chans"]),
        "stim_channel": normalized.get("stim_channel") or "Status",
        "save_preprocessed_fif": False,
        "frequency_protocol": protocol, "frequency_protocol_fingerprint": protocol.fingerprint,
        "base_freq": float(protocol.presentation_rate_hz), "oddball_freq": float(protocol.oddball_rate_hz),
        "analysis": {"base_freq": float(protocol.presentation_rate_hz),
                     "oddball_freq": float(protocol.oddball_rate_hz),
                     "frequency_protocol": protocol.to_manifest(),
                     "frequency_protocol_fingerprint": protocol.fingerprint},
        "raw_spectral_screening": project.experimental_qc_settings.raw_spectral_screening.to_manifest(),
        "event_id_map": dict(project.event_map),
    }
    for key in (
        "auto_detect_removed_electrodes", "removed_electrode_detection_mode",
        "manual_removed_electrodes_enabled", "removed_electrode_detection_choice_schema_version",
        "removed_electrode_detection_choice_status", "removed_electrode_detection_choice_source",
        "manual_removed_electrodes", "manual_removed_electrodes_by_recording",
        "manual_excluded_participants", "manual_excluded_recordings",
        "manual_excluded_participant_conditions", "manual_excluded_recording_conditions",
        "kurtosis_review_decisions_by_recording", "kurtosis_auto_interpolate_all",
        "experimental_ram_preload",
    ):
        converted[key] = normalized.get(key)
    for key in ("auto_detect_removed_electrodes", "manual_removed_electrodes_enabled",
                "kurtosis_auto_interpolate_all", "experimental_ram_preload"):
        converted[key] = bool(converted[key])
    for key in ("manual_removed_electrodes", "manual_removed_electrodes_by_recording",
                "manual_excluded_participant_conditions", "manual_excluded_recording_conditions",
                "kurtosis_review_decisions_by_recording"):
        converted[key] = dict(converted[key] or {})
    for key in ("manual_excluded_participants", "manual_excluded_recordings"):
        converted[key] = list(converted[key] or [])
    return converted


def automatic_receipts(project, scan, receipt_time: str | None) -> dict:
    from Main_App.processing.kurtosis_qc import (
        KURTOSIS_DECISION_APPROVE,
        KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD,
        build_kurtosis_review_decision,
        qualifies_for_experimental_kurtosis_auto,
    )
    from Main_App.processing.kurtosis_review_scan import reconcile_kurtosis_review_decisions

    if scan.cancelled or scan.errors:
        raise ReviewRequired("Kurtosis evidence is cancelled or incomplete")
    auto_all = bool(project.preprocessing.get("kurtosis_auto_interpolate_all", False))
    reconciliation = reconcile_kurtosis_review_decisions(
        scan, project.preprocessing.get("kurtosis_review_decisions_by_recording", {}),
        kurtosis_auto_interpolate_all=auto_all,
    )
    receipts = dict(reconciliation.current_receipts)
    for item in reconciliation.pending_items:
        # Native preparation omits valid auto-all flags from pending review and
        # creates its own decision plan without per-channel human receipts.
        # Anything still pending under that policy requires genuine review.
        if auto_all:
            raise ReviewRequired(f"Manual kurtosis review is required under auto-all: {item.recording_id} / {item.channel}")
        channel = next((row for row in item.evidence["channels"] if row["channel"] == item.channel), None)
        if (not project.experimental_qc_settings.kurtosis_review_auto_interpolate_extreme
                or channel is None or not qualifies_for_experimental_kurtosis_auto(channel)):
            raise ReviewRequired(f"Manual kurtosis review is required: {item.recording_id} / {item.channel}")
        receipt = build_kurtosis_review_decision(
            item.evidence, channel=item.channel, decision=KURTOSIS_DECISION_APPROVE,
            reason=f"Experimental automatic interpolation: |normalized score| > {KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD:.1f}.",
            review_scope=item.review_scope, experimental_auto=True,
            reviewed_at_utc=receipt_time,
        )
        receipts.setdefault(item.recording_id, {})[item.channel] = receipt.to_payload()
    validated = reconcile_kurtosis_review_decisions(scan, receipts, kurtosis_auto_interpolate_all=auto_all)
    if validated.pending_items:
        raise ReviewRequired("Automatic receipts did not resolve the existing QC model")
    return validated.current_receipts


def routing_settings(project, infos, params, plan) -> dict:
    from Main_App.processing.processing_ledger import PROCESSING_FINGERPRINT_VERSION, output_group_folder_by_file
    from Main_App.projects import project_group_context

    settings = dict(params)
    settings["_fpvs_grouped_project"] = project_group_context(project).has_group_metadata
    settings["_fpvs_processing_fingerprint"] = plan.fingerprint
    settings["_fpvs_processing_fingerprint_version"] = PROCESSING_FINGERPRINT_VERSION
    settings["_fpvs_output_group_by_file"] = output_group_folder_by_file(project, infos)
    for name, attribute in (
        ("participant_id", "subject_id"), ("recording_id", "recording_id"),
        ("session_id", "session_id"), ("session_label", "session_label"),
        ("visit_index", "visit_index"), ("days_from_baseline", "days_from_baseline"),
        ("output_stem", "output_stem"), ("group_id", "group"),
    ):
        settings[f"_fpvs_{name}_by_file"] = {
            str(info.path.resolve()): getattr(info, attribute)
            for info in infos if getattr(info, attribute) is not None
        }
    return settings


def artifact_inventory(project_root: Path) -> dict:
    """Audit generated numerical arrays and workbook ZIP payloads after timing."""
    import numpy as np

    result = {}
    for path in sorted(project_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".npz", ".npy", ".xlsx", ".fif"}:
            continue
        if "benchmark_evidence" in path.parts:
            continue
        key = path.relative_to(project_root).as_posix()
        if path.suffix.lower() == ".npz":
            with np.load(path, allow_pickle=False) as archive:
                result[key] = {name: serialize(archive[name]) for name in archive.files}
        elif path.suffix.lower() == ".npy":
            result[key] = serialize(np.load(path, allow_pickle=False, mmap_mode="r"))
        elif path.suffix.lower() == ".xlsx":
            with zipfile.ZipFile(path) as archive:
                members = {}
                for name in archive.namelist():
                    content = archive.read(name)
                    if name == "docProps/core.xml":
                        content = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)", rb"\1TIMESTAMP\2", content)
                    members[name] = hashlib.sha256(content).hexdigest()
                result[key] = {"normalized_zip_members": members}
        else:
            result[key] = {"container_sha256": file_hash(path)}
    return result


def run(args, receipt: dict, events_path: Path) -> None:
    from Main_App.gui.marker_occurrence_review import MarkerOccurrenceReviewError, canonical_event_plans_by_file
    from Main_App.processing.condition_interpolation_executor import build_condition_interpolation_run_snapshot
    from Main_App.processing.expected_processing_ledger import build_expected_recording_condition_plan, save_expected_recording_condition_plan
    from Main_App.processing.interpolation_burden_review import collect_interpolation_burden_review
    from Main_App.processing.kurtosis_review_scan import scan_kurtosis_review
    from Main_App.processing.preflight_qc import scan_preprocessing_qc
    from Main_App.processing.processing_controller import prepare_batch_file_infos, validate_repeated_recording_sources_for_processing
    from Main_App.processing.processing_ledger import (
        classify_processing_inputs, clean_downstream_outputs_for_reprocess_all,
        clean_managed_excel_root, record_processing_results, with_processing_choice,
    )
    from Main_App.processing.qc_summary_export import export_processing_qc_summary
    from Main_App.projects import Project
    from Main_App.workers import RunParams, run_project_parallel
    from Main_App.workers.mp_env import compute_effective_max_workers
    import psutil

    @contextmanager
    def phase(name):
        started = perf_counter()
        def event(kind):
            with events_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(), "phase": name, "event": kind}) + "\n")
        event("start")
        try:
            yield
        finally:
            receipt.setdefault("stage_seconds", {})[name] = perf_counter() - started
            event("finish")
            LOGGER.info("benchmark_stage_finished phase=%s elapsed_seconds=%.6f", name, receipt["stage_seconds"][name])

    def progress(message, completed, total):
        LOGGER.info("benchmark_progress completed=%s total=%s message=%s", completed, total, message)

    with phase("setup"):
        project = Project.load(args.project_root)
        params = validated_params(project)
        all_infos = prepare_batch_file_infos(project)
        available = {info.processing_id: info for info in all_infos}
        missing = set(args.recordings).difference(available)
        if missing:
            raise ValueError(f"Selected canonical recordings are missing: {sorted(missing)}")
        infos = [available[recording] for recording in args.recordings]
        for info in infos:
            checked(info.path, args.workspace_root)
        receipt["repeated_source_preflight"] = serialize(validate_repeated_recording_sources_for_processing(project, all_infos))
        project_override = int(project.preprocessing.get("max_parallel_workers_override") or 0)
        maximum = (project_override or project.options.get("max_workers") or None
                   if args.workers == "auto" else int(args.workers))
        bypass_ram_tier = args.workers != "auto" or project_override > 0
        workers = compute_effective_max_workers(
            psutil.virtual_memory().total, os.cpu_count() or 1, maximum,
            allow_ram_cap_bypass=bypass_ram_tier,
        )
        receipt["normal_pool_max_workers"] = workers
        receipt["selected_recordings"] = serialize(infos)
        receipt["validated_params"] = serialize(params)
    with phase("preflight"), pause_parent_for_preflight_profile():
        preflight = scan_preprocessing_qc(infos, params, project_root=args.project_root,
                                          event_map=project.event_map, max_workers=workers, progress=progress)
        defer_native_proof(receipt, "preflight", preflight)
        if args.marker_review_replay is not None:
            preflight = replay_marker_review(
                preflight, infos, params, args.project_root, project.event_map,
                workers, progress, args.marker_review_replay, receipt,
            )
        defer_native_proof(receipt, "preflight", preflight)
        blocked = [row for row in preflight.results if row.load_error or row.raw_qc_excluded or row.raw_qc_decision_review_required]
        if preflight.cancelled or blocked:
            raise ReviewRequired("Preflight requires recording/raw-QC review")
        try:
            plans = canonical_event_plans_by_file(preflight)
        except MarkerOccurrenceReviewError as exc:
            raise ReviewRequired(str(exc)) from exc
        raw_qc = {row.recording_id or row.participant_id: dict(row.raw_channel_qc)
                  for row in preflight.results if row.raw_channel_qc is not None}
        params["_fpvs_preflight_event_plans_by_file"] = plans
    if args.stop_after_preflight:
        receipt["status"] = "preflight_complete_diagnostic_only"
        receipt["approved_event_plans"] = serialize(plans)
        return
    with phase("kurtosis_preparation"):
        review = scan_kurtosis_review(
            infos, {**params, "project_root": str(args.project_root)}, event_map=project.event_map,
            reviewed_event_plans_by_file=plans, raw_channel_qc_by_recording=raw_qc,
            execution_backend="process", max_workers=maximum, progress=progress,
        )
    defer_native_proof(receipt, "kurtosis_review", review)
    if args.stop_after_preparation:
        if review.cancelled or len(review.results) != len(infos) or any(item.error for item in review.results):
            raise RuntimeError("Native preparation did not complete every selected recording successfully")
        receipt["status"] = "preparation_complete_diagnostic_only"
        receipt["approved_event_plans"] = serialize(plans)
        return
    with phase("automatic_receipt_validation"):
        receipts = automatic_receipts(project, review, args.receipt_time)
        saved = dict(project.preprocessing.get("kurtosis_review_decisions_by_recording") or {})
        selected = {info.processing_id.casefold() for info in infos}
        saved = {key: value for key, value in saved.items() if key.casefold() not in selected}
        saved.update(receipts)
        project.update_preprocessing({**project.preprocessing, "kurtosis_review_decisions_by_recording": saved})
        project.save()
        params["kurtosis_review_decisions_by_recording"] = saved
        receipt["applied_automatic_receipts"] = serialize(receipts)
    with phase("processing_plan"):
        plan = with_processing_choice(classify_processing_inputs(project, infos, params, project.event_map), "reprocess_all")
        expected = build_expected_recording_condition_plan(
            processing_plan=plan, event_map=project.event_map, frequency_protocol=project.frequency_protocol,
            approved_event_plans=plans, planning_settings=params,
            run_id="00000000000000000000000000000001", created_at=args.receipt_time,
        )
        save_expected_recording_condition_plan(args.project_root, expected)
        clean_managed_excel_root(project)
        clean_downstream_outputs_for_reprocess_all(project)
        params["_fpvs_expected_plan_run_id"] = expected.run_id
        params["_fpvs_expected_plan_fingerprint"] = expected.fingerprint
        settings = routing_settings(project, infos, params, plan)
        excel_root = checked(Path(project.subfolders["excel"]), args.project_root)
        settings["_fpvs_condition_interpolation_run_snapshot"] = build_condition_interpolation_run_snapshot(
            settings, project.event_map, plan, excel_root,
        )
        receipt["processing_plan"] = serialize(plan)
        receipt["expected_plan"] = serialize(expected)
    with phase("normal_processing"):
        result = run_project_parallel(RunParams(
            project_root=args.project_root, data_files=list(plan.run_files), settings=settings,
            event_map=dict(project.event_map), save_folder=excel_root, max_workers=workers,
        ))
    defer_native_proof(receipt, "processing_result", result)
    with phase("ledger_and_qc_export"):
        record_processing_results(project, plan, [*result.get("results", []), *result.get("errors", []), *result.get("excluded", [])],
                                  run_mode="Batch", user_choice="reprocess_all", cancelled=bool(result.get("cancelled")))
        export_processing_qc_summary(project, plan, [*result.get("results", []), *result.get("errors", []), *result.get("excluded", [])])
        if result.get("status") != "success":
            raise ReviewRequired("Normal processing is incomplete; downstream remains blocked")
        burden = collect_interpolation_burden_review(project)
        receipt["interpolation_burden_review"] = serialize(burden)
    downstream_code = None
    if args.downstream and not burden.requires_review:
        with phase("downstream"):
            downstream_code = run_downstream(args, receipt, events_path)
    with phase("artifact_audit_excluded_from_processing_time"):
        receipt["generated_artifact_proof"] = artifact_inventory(args.project_root)
    if burden.requires_review:
        raise ReviewRequired("Interpolation-burden review is required before downstream publication")
    if downstream_code == 1:
        raise RuntimeError("Native downstream diagnostic binding failed; inspect downstream receipt")
    if downstream_code in (3, 4):
        raise ReviewRequired(f"Native downstream returned {receipt['downstream']['status']}")
    receipt["status"] = "pipeline_complete" if downstream_code == 0 else "processing_complete_downstream_pending"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--recordings", "--selection", nargs="+", required=True)
    parser.add_argument("--workers", default="auto")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--receipt-time", default="2026-10-14T03:20:00Z", help="Common frozen automatic-policy UTC timestamp for paired fixtures")
    parser.add_argument("--start-gate", type=Path, help="Wait up to 60 seconds for this workspace file before source imports")
    parser.add_argument("--scratch-root", type=Path, help="Explicit dedicated runtime TEMP/TMP/TMPDIR directory")
    parser.add_argument("--profile", action="store_true", help="Diagnostic parent/preflight-thread/child-worker cProfile; not a timing trial")
    parser.add_argument("--functional-seed", action="store_true", help="Discovery/QC seed with ambient work; ineligible for comparative timing claims")
    parser.add_argument("--ambient-note", help="Recorded concurrent workload or other measurement limitations")
    parser.add_argument("--downstream", action="store_true", help="Continue native downstream methods in this process, preserving review gates")
    parser.add_argument("--benchmark-review-policy", type=Path, help="Explicit engineering-fixture downstream review policy inside the workspace")
    parser.add_argument("--stop-after-preflight", action="store_true", help="Diagnostic-only early return after native preflight and marker plans")
    parser.add_argument("--stop-after-preparation", action="store_true", help="Complete native preparation without authorizing pending kurtosis review or normal processing")
    parser.add_argument("--marker-review-replay", type=Path, help="Inventory of actual prior human occurrence exclusions; fresh scientific marker fingerprints must match")
    args = parser.parse_args()
    args.source_root = args.source_root.resolve()
    args.workspace_root = args.workspace_root.resolve()
    args.project_root = checked(args.project_root, args.workspace_root)
    args.output_dir = checked(args.output_dir or args.project_root / "benchmark_evidence", args.project_root)
    args.recordings = [value.strip() for entry in args.recordings for value in entry.split(",") if value.strip()]
    if not args.recordings or len(set(args.recordings)) != len(args.recordings):
        parser.error("Supply a nonempty unique canonical recording-ID list")
    if args.workers != "auto" and (not args.workers.isdigit() or int(args.workers) < 1):
        parser.error("--workers must be auto or a positive integer")
    if os.environ.get("PYTHONHASHSEED") != "0":
        parser.error("Launch this separate process with PYTHONHASHSEED=0")
    if not (args.source_root / "src" / "Main_App").is_dir():
        parser.error("--source-root must contain the selected repository's src/Main_App")
    manifest_path = args.project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_clone(manifest, args.project_root, args.workspace_root)
    if args.start_gate is not None:
        args.start_gate = checked(args.start_gate, args.workspace_root)
    if args.marker_review_replay is not None:
        args.marker_review_replay = checked(args.marker_review_replay, args.workspace_root)
        if not args.marker_review_replay.is_file():
            parser.error("--marker-review-replay requires an existing isolated inventory file")
    if args.stop_after_preparation and (args.stop_after_preflight or args.downstream):
        parser.error("--stop-after-preparation cannot be combined with --stop-after-preflight or --downstream")
    if args.benchmark_review_policy is not None:
        args.benchmark_review_policy = checked(args.benchmark_review_policy, args.workspace_root)
        if not args.downstream or not args.benchmark_review_policy.is_file():
            parser.error("--benchmark-review-policy requires --downstream and an existing workspace policy file")
    if args.scratch_root is not None:
        args.scratch_root = args.scratch_root.resolve()
        if args.scratch_root == Path(args.scratch_root.anchor) or args.scratch_root in (args.source_root, args.project_root, args.workspace_root):
            parser.error("--scratch-root must name a dedicated temporary directory")
        args.scratch_root.mkdir(parents=True, exist_ok=True)
        for name in ("TEMP", "TMP", "TMPDIR"):
            os.environ[name] = str(args.scratch_root)
    if args.downstream and args.scratch_root is None:
        parser.error("--downstream requires --scratch-root")
    if args.downstream:
        config_root = Path(os.environ.get("FPVS_CONFIG_HOME", "")).resolve()
        if not config_root.is_absolute() or not config_root.is_relative_to(args.workspace_root) or not (config_root / "settings" / "settings.ini").is_file():
            parser.error("--downstream requires FPVS_CONFIG_HOME inside --workspace-root with frozen settings/settings.ini")
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                        handlers=[logging.FileHandler(args.output_dir / "backend.log", encoding="utf-8"), logging.StreamHandler()])
    LOGGER.info("benchmark_ready pid=%s start_gate=%s", os.getpid(), args.start_gate)
    if args.start_gate is not None:
        deadline = perf_counter() + 60.0
        while not args.start_gate.is_file():
            if perf_counter() >= deadline:
                LOGGER.error("benchmark_start_gate_timeout path=%s", args.start_gate)
                return 1
            sleep(0.05)
    for name in ("MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"):
        os.environ[name] = str(os.cpu_count() or 1)
    os.environ["NUMEXPR_NUM_THREADS"] = str(max(1, (os.cpu_count() or 1) // 2))
    sys.path.insert(0, str(args.source_root / "src"))
    from Main_App.workers.mp_env import set_blas_threads_single_process

    set_blas_threads_single_process()
    logging.getLogger("Main_App.Performance.process_runner").setLevel(logging.DEBUG)
    initial_manifest_bytes = manifest_path.read_bytes()
    initial_preimage_path = args.output_dir / "project_before_runner.bin"
    with initial_preimage_path.open("xb") as stream:
        stream.write(initial_manifest_bytes)
    initial_manifest_sha256 = hashlib.sha256(initial_manifest_bytes).hexdigest()
    receipt = {"version": "pipeline_bitwise_backend_runner_v1", "started_utc": datetime.now(timezone.utc).isoformat(),
               "source_root": str(args.source_root), "project_root": str(args.project_root),
               "recordings": args.recordings, "profiling_diagnostic": args.profile,
               "functional_seed": args.functional_seed, "ambient_workload_note": args.ambient_note,
               "requested_worker_policy": args.workers,
               "scratch_root": str(args.scratch_root) if args.scratch_root else None,
               "receipt_time": args.receipt_time,
               "downstream_requested": args.downstream,
               "benchmark_review_policy": str(args.benchmark_review_policy) if args.benchmark_review_policy else None,
               "stop_after_preflight": args.stop_after_preflight,
               "stop_after_preparation": args.stop_after_preparation,
               "marker_review_replay_path": str(args.marker_review_replay) if args.marker_review_replay else None,
               "initial_project_sha256": initial_manifest_sha256,
               "initial_project_manifest_preimage": {"path": str(initial_preimage_path), "size_bytes": len(initial_manifest_bytes),
                                                     "sha256": initial_manifest_sha256},
               "hash_seed": "0", "status": "started"}
    profiler = cProfile.Profile() if args.profile else None
    try:
        if profiler is not None:
            profiler.enable()
        with diagnostic_profile_hooks(args.profile, args.output_dir / "profiles", profiler):
            run(args, receipt, args.output_dir / "events.jsonl")
        return_code = 0
    except ReviewRequired as exc:
        receipt.update(status="paused_for_review", pause_reason=str(exc))
        LOGGER.warning("benchmark_paused reason=%s", exc)
        return_code = 2
    except Exception as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        LOGGER.exception("benchmark_failed")
        return_code = 1
    finally:
        if profiler is not None:
            profiler.disable()
            profiler.dump_stats(args.output_dir / "parent_profile.pstats")
            _write_profile(profiler, args.output_dir / "profiles", "parent", "coordinator", {
                "coverage": "Coordinator including optional native downstream, paused throughout preflight. Python3.13 can capture concurrent auxiliary callbacks process-wide. A bounded preflight window and spawned workers have separate profiles; use unprofiled phase events for wall times.",
            })
            receipt["diagnostic_profiles"] = [str(path.relative_to(args.output_dir)) for path in sorted((args.output_dir / "profiles").glob("*.pstats"))]
        receipt["native_runner_returned_utc"] = datetime.now(timezone.utc).isoformat()
        receipt["generated_storage_footprint"] = storage_footprint(args.project_root, args.output_dir)
        receipt["final_project_sha256"] = file_hash(manifest_path)
        try:
            write_native_receipt(receipt, args.output_dir / "events.jsonl", args.output_dir / "run_receipt.json",
                                 args.output_dir / "telemetry_core_receipt.json")
        except Exception as exc:
            LOGGER.exception("benchmark_observer_proof_failed")
            receipt.update(status="observer_proof_failed", observer_error=f"{type(exc).__name__}: {exc}")
            return_code = 1
            receipt["finished_utc"] = datetime.now(timezone.utc).isoformat()
            with (args.output_dir / "observer_failure_receipt.json").open("x", encoding="utf-8") as stream:
                json.dump(receipt, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
    return return_code


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
