"""Run the production downstream worker on an isolated benchmark clone, without Qt.

Only the worker's QObject base and signal transport are rebound. All production
method ASTs, constructor state, imports, guards, statistical methods, and native
review gates/skip logic remain unchanged. An explicit optional fixture policy
may apply matched Retain decisions through the native API. This is a manual benchmark adapter, not
a replacement runtime workflow. Python audit hooks constrain audited filesystem
writes; they are diagnostic instrumentation, not an operating-system sandbox.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
import copy
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import importlib
import json
import logging
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
from time import perf_counter
from types import ModuleType, SimpleNamespace
from typing import Any


LOG = logging.getLogger(__name__)
SCHEMA = "pipeline_downstream_probe_v1"
WORKER_MODULE = "Main_App.workers.post_processing_pipeline_worker"
WORKER_RELATIVE = Path("src/Main_App/workers/post_processing_pipeline_worker.py")
SOURCE_PACKAGES = ("Main_App", "Shared", "Tools", "config")
POLICY_SCHEMA = "pipeline_benchmark_qc_policy_v1"
FINDING_FIELDS = ("finding_type", "recording_id", "condition", "electrode", "severity")
BENCHMARK_FINDING_TYPES = frozenset({"absolute_electrode_summed_bca"})


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_value(value: Any) -> Any:
    """Snapshot signal payloads without silently stringifying unknown objects."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {"__nonfinite_float__": repr(value), "float64_hex": struct.pack(">d", value).hex()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Signal/report mappings must have string keys")
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return json_value(asdict(value))
    # NumPy payloads are tagged explicitly; no NumPy import is needed by this adapter.
    if type(value).__module__.startswith("numpy"):
        if hasattr(value, "shape") and hasattr(value, "dtype") and hasattr(value, "tobytes"):
            return {
                "__numpy_payload__": True,
                "dtype": str(value.dtype),
                "shape": list(value.shape),
                "c_order_bytes_hex": value.tobytes(order="C").hex(),
                "values": json_value(value.tolist()),
            }
    raise TypeError(f"Unsupported signal/report payload type: {type(value).__module__}.{type(value).__qualname__}")


class RecordedSignal:
    """Inert synchronous signal transport, with instance-local subscribers."""

    def __init__(self, *_types: type) -> None:
        self.name = ""

    def __set_name__(self, _owner: type, name: str) -> None:
        self.name = name

    def __get__(self, instance: object | None, _owner: type | None = None):
        if instance is None:
            return self
        key = f"_probe_signal_{self.name}"
        if key not in instance.__dict__:
            instance.__dict__[key] = BoundSignal()
        return instance.__dict__[key]


class BoundSignal:
    def __init__(self) -> None:
        self.callbacks: list = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in tuple(self.callbacks):
            callback(*args)


def identity_slot(*_types, **_options):
    def decorate(function):
        return function
    return decorate


def _method_digests(node: ast.ClassDef) -> dict[str, str]:
    return {
        method.name: sha256_bytes(ast.dump(method, include_attributes=False).encode("utf-8"))
        for method in node.body
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def selected_source(source_root: Path) -> Path:
    root = source_root.resolve(strict=True)
    worker_path = root / WORKER_RELATIVE
    if not worker_path.is_file():
        raise FileNotFoundError(worker_path)
    source_dir = root / "src"
    for name, module in tuple(sys.modules.items()):
        if name.split(".")[0] in SOURCE_PACKAGES and getattr(module, "__file__", None):
            imported_path = Path(module.__file__).resolve()
            if not imported_path.is_relative_to(source_dir):
                raise RuntimeError(f"A different source checkout is already imported: {name}: {imported_path}")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source_dir))
    importlib.invalidate_caches()
    return worker_path


def bind_worker(source_root: Path, *, expected_sha256: str | None = None):
    """Compile only the production class, changing its base/transport globals."""
    worker_path = selected_source(source_root)
    source_bytes = worker_path.read_bytes()
    source_sha = sha256_bytes(source_bytes)
    if expected_sha256 is not None and source_sha != expected_sha256:
        raise RuntimeError(f"Worker source SHA does not match expected value: {source_sha}")
    module = importlib.import_module(WORKER_MODULE)
    if Path(module.__file__).resolve() != worker_path.resolve():
        raise RuntimeError("Imported worker module did not come from --source-root")
    if worker_path.read_bytes() != source_bytes:
        raise RuntimeError("Worker source changed while binding")
    tree = ast.parse(source_bytes, filename=str(worker_path))
    matching = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PostProcessingPipelineWorker"]
    if len(matching) != 1:
        raise RuntimeError("Expected exactly one production PostProcessingPipelineWorker class")
    original = matching[0]
    if len(original.bases) != 1 or not isinstance(original.bases[0], ast.Name) or original.bases[0].id != "QObject":
        raise RuntimeError("Unexpected production worker base; adapter must be reviewed")
    rebound = copy.deepcopy(original)
    rebound.bases = [ast.copy_location(ast.Name(id="object", ctx=ast.Load()), rebound.bases[0])]
    original_methods = _method_digests(original)
    rebound_methods = _method_digests(rebound)
    if original_methods != rebound_methods:
        raise AssertionError("Binding modified production method ASTs")
    isolated = ast.Module(body=[rebound], type_ignores=[])
    ast.fix_missing_locations(isolated)
    globals_copy = dict(vars(module))
    globals_copy.update(Signal=RecordedSignal, Slot=identity_slot)
    # Match production future-annotations semantics while compiling only the class.
    import __future__
    exec(compile(isolated, str(worker_path), "exec", flags=__future__.annotations.compiler_flag), globals_copy)
    worker_class = globals_copy["PostProcessingPipelineWorker"]
    if worker_class.__bases__ != (object,):
        raise AssertionError("GUI-neutral binding retained a Qt base")
    receipt = {
        "worker_module": WORKER_MODULE,
        "worker_source_path": str(worker_path),
        "worker_source_sha256": source_sha,
        "production_class_ast_sha256": sha256_bytes(ast.dump(original, include_attributes=False).encode("utf-8")),
        "bound_class_ast_sha256": sha256_bytes(ast.dump(rebound, include_attributes=False).encode("utf-8")),
        "production_method_ast_sha256": original_methods,
        "bound_method_ast_sha256": rebound_methods,
        "all_production_method_asts_identical": True,
        "binding_changes": ["QObject base replaced by object", "Signal transport replaced by synchronous callback recorder", "Slot decorator replaced by identity"],
        "qobject_instances_created_by_adapter": 0,
        "qapplication_instances_created_by_adapter": 0,
    }
    return worker_class, module, receipt


class WriteGuard:
    """Reject audited writes outside named roots and writes to BDF source files."""

    def __init__(self, workspace_root: Path, scratch_root: Path) -> None:
        self.roots = (workspace_root.resolve(strict=True), scratch_root.resolve(strict=True))
        self.denied: list[dict] = []
        self.audited_mutations = 0

    def check(self, path, *, event: str, dir_fd=None) -> None:
        if isinstance(path, int):
            # Existing inherited descriptors (e.g. console/pipe) have no new path.
            return
        if dir_fd not in (None, -1):
            raise PermissionError("Directory-relative writes are not supported by the probe guard")
        resolved = Path(os.fsdecode(path)).expanduser().resolve(strict=False)
        allowed = any(resolved.is_relative_to(root) for root in self.roots)
        if not allowed or resolved.suffix.casefold() == ".bdf":
            denial = {"event": event, "path": str(resolved), "reason": "BDF sources are read-only" if resolved.suffix.casefold() == ".bdf" else "outside named write roots"}
            self.denied.append(denial)
            raise PermissionError(f"Probe write guard rejected {event}: {resolved}")
        self.audited_mutations += 1

    def __call__(self, event: str, args: tuple) -> None:
        if event == "open":
            path, mode, flags = args
            if (isinstance(mode, str) and any(char in mode for char in "wax+")) or (flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                self.check(path, event=event)
        elif event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime", "os.truncate"}:
            dir_fd = args[-1] if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.utime"} else None
            self.check(args[0], event=event, dir_fd=dir_fd)
        elif event == "os.rename":
            self.check(args[0], event=event, dir_fd=args[2])
            self.check(args[1], event=event, dir_fd=args[3])
        elif event in {"os.link", "os.symlink"}:
            raise PermissionError("Link creation is not permitted by the probe guard")
        elif event in {"shutil.copyfile", "shutil.copytree"}:
            self.check(args[1], event=event)
        elif event == "shutil.move":
            self.check(args[0], event=event)
            self.check(args[1], event=event)
        elif event == "os.chdir":
            # Stay in the explicit cloned workspace; source remains importable by absolute paths.
            destination = Path(os.fsdecode(args[0])).resolve(strict=True)
            if not destination.is_relative_to(self.roots[0]):
                raise PermissionError(f"Probe cannot change cwd outside workspace: {destination}")


def output_path(workspace_root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else workspace_root / candidate).resolve(strict=False)
    if resolved == workspace_root or not resolved.is_relative_to(workspace_root):
        raise ValueError("Diagnostic output must remain beneath --workspace-root")
    if resolved.exists():
        raise FileExistsError(resolved)
    return resolved


def source_inventory(source_root: Path) -> list[dict]:
    source_dir = source_root / "src"
    inventory = []
    for name, module in sorted(tuple(sys.modules.items())):
        path_value = getattr(module, "__file__", None)
        if name.split(".")[0] not in SOURCE_PACKAGES or path_value is None:
            continue
        path = Path(path_value).resolve(strict=True)
        if not path.is_relative_to(source_dir):
            raise RuntimeError(f"Production dependency imported from another checkout: {name}: {path}")
        inventory.append({"module": name, "relative_path": path.relative_to(source_root).as_posix(), "sha256": sha256_bytes(path.read_bytes())})
    return inventory


def write_json(target: Path, payload: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(json_value(payload), stream, indent=2, allow_nan=False)
        stream.write("\n")


def load_benchmark_policy(path: Path, workspace_root: Path) -> tuple[dict, str]:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(workspace_root) or not resolved.is_file():
        raise ValueError("Benchmark policy must be an existing JSON file inside --workspace-root")
    encoded = resolved.read_bytes()
    if len(encoded) > 128 * 1024:
        raise ValueError("Benchmark policy exceeds the bounded 128 KiB input limit")
    policy = json.loads(encoded)
    expected_keys = {"schema", "identity_scope", "decision", "purpose", "reason", "expected_findings"}
    if not isinstance(policy, dict) or set(policy) != expected_keys:
        raise ValueError("Benchmark policy must contain exactly schema, identity_scope, decision, purpose, reason, expected_findings")
    if policy["schema"] != POLICY_SCHEMA or policy["identity_scope"] != "recording" or policy["decision"] != "keep":
        raise ValueError("Only the explicit recording-scoped engineering Keep policy is supported")
    purpose = str(policy["purpose"]).casefold()
    reason = str(policy["reason"]).casefold()
    if not all(token in purpose for token in ("engineering", "fixture", "not a study qc approval")) or not all(token in reason for token in ("performance", "fixture", "identical inputs")):
        raise ValueError("Benchmark purpose/reason must explicitly limit Keep to identical-input engineering performance fixtures")
    findings = policy["expected_findings"]
    if not isinstance(findings, list) or not findings:
        raise ValueError("Benchmark policy requires an explicit nonempty finding list")
    expected = []
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != set(FINDING_FIELDS):
            raise ValueError("Every expected finding must specify the exact five identity/severity fields")
        if not all(isinstance(finding[key], str) and finding[key] for key in FINDING_FIELDS):
            raise ValueError("Expected finding identity/severity fields must be nonempty strings")
        if finding["finding_type"] not in BENCHMARK_FINDING_TYPES or finding["severity"] not in {"warning", "strong"}:
            raise ValueError("Unknown finding type or severity is outside the authorized benchmark policy")
        expected.append(tuple(finding[key] for key in FINDING_FIELDS))
    if len(set(expected)) != len(expected):
        raise ValueError("Benchmark policy contains duplicate findings")
    if resolved.read_bytes() != encoded:
        raise ValueError("Benchmark policy changed while reading")
    return policy, sha256_bytes(encoded)


def benchmark_decision_rows(report: dict, policy: dict) -> list[dict]:
    """Match all native findings before any automatic engineering-fixture action."""
    if report.get("identity_scope") != "recording" or not report.get("review_required"):
        raise ValueError("Engineering policy requires a current recording-scoped native review pause")
    if report.get("technical_integrity_failed") or report.get("technical_integrity_failures") or report.get("qc_complete") is not True:
        raise ValueError("Technical integrity/native incomplete findings cannot be accepted by a benchmark policy")
    for field in ("manual_participant_exclusions", "manual_recording_exclusions", "auto_participant_exclusions", "auto_recording_exclusions", "auto_participant_electrode_exclusions", "auto_recording_electrode_exclusions"):
        if report.get(field):
            raise ValueError(f"Keep-all engineering fixture cannot contain preexisting {field}")
    if any(row.get("decision") != "retain" for row in report.get("active_review_decisions", [])):
        raise ValueError("Keep-all engineering fixture cannot contain active exclusion/repair decisions")
    findings = report.get("review_findings", report.get("flags"))
    if not isinstance(findings, list):
        raise ValueError("Native review does not contain a finding list")
    actual = [tuple(finding.get(key) for key in FINDING_FIELDS) for finding in findings]
    expected = [tuple(finding[key] for key in FINDING_FIELDS) for finding in policy["expected_findings"]]
    if len(actual) != len(expected) or sorted(actual) != sorted(expected):
        raise ValueError("Native findings changed or contain unknown/missing identities, severities, or types; benchmark policy is blocked")
    fingerprints = [finding.get("finding_fingerprint") for finding in findings]
    if not all(isinstance(value, str) and len(value) == 64 for value in fingerprints) or len(set(fingerprints)) != len(fingerprints):
        raise ValueError("Native findings must retain unique evidence fingerprints")
    return [{"finding_fingerprint": fingerprint, "decision": "retain", "reason": policy["reason"]} for fingerprint in fingerprints]


def apply_benchmark_policy(project_root: Path, report: dict, policy: dict) -> dict:
    from Main_App.processing.frequency_domain_qc import (
        apply_frequency_domain_qc_decision,
        require_frequency_domain_qc_complete,
        validate_frequency_domain_qc_review_decisions,
    )
    rows = benchmark_decision_rows(report, policy)
    require_frequency_domain_qc_complete(report)
    normalized = validate_frequency_domain_qc_review_decisions(report, rows)
    state = apply_frequency_domain_qc_decision(project_root, report, review_decisions=normalized)
    if not state.get("review_complete") or any(row.get("decision") != "retain" for row in state.get("review_decisions", [])):
        raise ValueError("Native saved review did not preserve the engineering Keep policy")
    return {
        "schema": "pipeline_benchmark_qc_automation_receipt_v1",
        "reviewer_identity": "automated_benchmark_policy; no human QC review is claimed",
        "purpose": policy["purpose"], "reason": policy["reason"],
        "native_api_label_note": "The unchanged native Retain validator assigns reason='No reason provided' and source='explicit_gui_review'. Those fixed API fields are preserved verbatim; the benchmark automation provenance and engineering reason are recorded separately here.",
        "first_native_report": report, "submitted_decisions": rows,
        "native_validated_decisions": normalized, "native_saved_review_state": state,
    }


def run_probe(args) -> int:
    source_root = Path(args.source_root).resolve(strict=True)
    workspace_root = Path(args.workspace_root).resolve(strict=True)
    project_root = Path(args.project_root).resolve(strict=True)
    scratch_root = Path(args.scratch_root).resolve(strict=True)
    if project_root == workspace_root or not project_root.is_relative_to(workspace_root):
        raise ValueError("--project-root must be a clone beneath --workspace-root")
    if source_root.is_relative_to(workspace_root) or source_root.is_relative_to(scratch_root):
        raise ValueError("A named write root cannot contain the source checkout")
    if not (project_root / "project.json").is_file():
        raise FileNotFoundError("The clone must have an existing project.json")
    config_value = os.environ.get("FPVS_CONFIG_HOME", "").strip()
    if not config_value or not Path(config_value).is_absolute():
        raise ValueError("Set FPVS_CONFIG_HOME to an explicit frozen config clone inside --workspace-root")
    config_root = Path(config_value).resolve(strict=True)
    if not config_root.is_relative_to(workspace_root):
        raise ValueError("FPVS_CONFIG_HOME must remain inside --workspace-root")
    config_file = config_root / "settings" / "settings.ini"
    if not config_file.is_file():
        raise FileNotFoundError("FPVS_CONFIG_HOME must contain a frozen settings/settings.ini before source imports")
    target = output_path(workspace_root, args.output)
    events_target = output_path(workspace_root, args.events or target.with_suffix(".events.jsonl"))
    if events_target == target:
        raise ValueError("Receipt and events must use different output files")
    policy_path = getattr(args, "benchmark_review_policy", None)
    policy_path = policy_path.resolve(strict=True) if policy_path else None
    policy, policy_sha = load_benchmark_policy(policy_path, workspace_root) if policy_path else (None, None)
    automation_target = output_path(workspace_root, target.with_suffix(".benchmark_qc_policy_receipt.json")) if policy else None
    guard = WriteGuard(workspace_root, scratch_root)
    sys.dont_write_bytecode = True
    sys.addaudithook(guard)
    os.chdir(workspace_root)
    for key in ("TEMP", "TMP", "TMPDIR"):
        os.environ[key] = str(scratch_root)
    os.environ["MPLCONFIGDIR"] = str(scratch_root / "matplotlib")
    tempfile.tempdir = str(scratch_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    events_target.parent.mkdir(parents=True, exist_ok=True)
    start = perf_counter()
    starting_manifest_bytes = (project_root / "project.json").read_bytes()
    starting_manifest = json.loads(starting_manifest_bytes)
    capture_repair_manifest = bool(starting_manifest.get("tools", {}).get("condition_electrode_interpolation", {}).get("requests"))
    receipt = {
        "schema": SCHEMA,
        "started_at_utc": utc_now(),
        "source_root": str(source_root),
        "workspace_root": str(workspace_root),
        "project_root": str(project_root),
        "scratch_root": str(scratch_root),
        "config_home": str(config_root),
        "frozen_settings_before_sha256": sha256_bytes(config_file.read_bytes()),
        "events_path": str(events_target),
        "pid": os.getpid(),
        "interpreter": sys.executable,
        "python_version": sys.version,
        "scientific_methods": "Every production worker method body, constructor, and business guard is unchanged. An optional explicit benchmark policy may apply only matched engineering-fixture Retain decisions through the native API; no study/human QC decision is claimed.",
        "write_guard_scope": "Python audited filesystem operations only; not an OS sandbox. Outputs restricted to workspace and explicit scratch; BDF writes forbidden.",
        "project_manifest_before_sha256": sha256_bytes(starting_manifest_bytes),
    }
    finished_payloads = []
    native_finished_payloads = []
    phase_payloads = []
    attempts = []
    review_paths = []
    attempt_index = 0
    policy_action_elapsed = 0.0
    sequence = 0
    error = None
    worker_elapsed = None
    repair_manifest_preimages = []
    observer_capture_windows = []
    with events_target.open("x", encoding="utf-8", buffering=65536) as events:
        def capture(signal_name, *payload):
            nonlocal sequence
            snapshot = json_value(list(payload))
            item = {"sequence": sequence, "signal": signal_name, "elapsed_seconds": perf_counter() - start, "attempt_index": attempt_index, "payload": snapshot}
            sequence += 1
            events.write(json.dumps(item, allow_nan=False) + "\n")
            events.flush()
            if signal_name == "finished":
                finished_payloads.append(snapshot[0])
                native_finished_payloads.append(payload[0])
            elif signal_name == "phase_progress":
                phase_payloads.append(snapshot)
                if (capture_repair_manifest and snapshot[:2] == ["frequency_domain_qc", 0]
                        and not any(row["attempt_index"] == attempt_index for row in repair_manifest_preimages)):
                    capture_start = perf_counter()
                    current_bytes = (project_root / "project.json").read_bytes()
                    path = output_path(workspace_root, target.parent / f"project_after_condition_repairs.attempt{attempt_index}.bin")
                    with path.open("xb") as stream:
                        stream.write(current_bytes)
                    proof = {"path": str(path), "size_bytes": len(current_bytes), "sha256": sha256_bytes(current_bytes),
                             "attempt_index": attempt_index, "native_phase_transition": "frequency_domain_qc:0"}
                    capture_finish = perf_counter()
                    repair_manifest_preimages.append(proof)
                    observer_capture_windows.append({"attempt_index": attempt_index, "start_elapsed_seconds": capture_start - start,
                                                     "finish_elapsed_seconds": capture_finish - start})
        try:
            worker_class, _module, binding = bind_worker(source_root, expected_sha256=args.expected_worker_sha256)
            receipt["binding"] = binding
            from Main_App.projects import Project
            project = Project.load(project_root)
            receipt["setup_elapsed_seconds"] = perf_counter() - start
            for attempt_index in range(1, 3 if policy else 2):
                worker = worker_class(project)
                for name in ("progress", "phase_progress", "log_message", "finished"):
                    getattr(worker, name).connect(lambda *payload, signal_name=name: capture(signal_name, *payload))
                capture("worker_attempt_started", {"attempt_index": attempt_index})
                initial_finished_count = len(finished_payloads)
                worker_start = perf_counter()
                attempt = {"attempt_index": attempt_index, "start_elapsed_seconds": worker_start - start}
                attempts.append(attempt)
                try:
                    worker.run()
                finally:
                    worker_finish = perf_counter()
                    attempt["finish_elapsed_seconds"] = worker_finish - start
                    gross = worker_finish - worker_start
                    capture_seconds = sum(row["finish_elapsed_seconds"] - row["start_elapsed_seconds"] for row in observer_capture_windows
                                          if row["attempt_index"] == attempt_index)
                    attempt["worker_run_gross_elapsed_seconds"] = gross
                    attempt["observer_manifest_capture_elapsed_seconds_excluded_from_worker_time"] = capture_seconds
                    attempt["worker_run_elapsed_seconds"] = gross - capture_seconds
                    worker_elapsed = sum(item["worker_run_elapsed_seconds"] for item in attempts)
                    capture("worker_attempt_finished", attempt)
                if len(finished_payloads) != initial_finished_count + 1:
                    raise RuntimeError("Each native worker attempt must emit exactly one actual finished payload")
                final_native = native_finished_payloads[-1]
                if not final_native.get("requires_frequency_domain_qc_review"):
                    break
                review_target = output_path(workspace_root, target.with_suffix(".frequency_qc_review.json" if attempt_index == 1 else f".attempt{attempt_index}.frequency_qc_review.json"))
                write_json(review_target, final_native["frequency_domain_qc_report"])
                review_paths.append(str(review_target))
                if policy is None or attempt_index != 1:
                    break
                policy_started = perf_counter()
                if sha256_bytes(policy_path.read_bytes()) != policy_sha:
                    raise ValueError("Benchmark policy changed before application")
                automation = apply_benchmark_policy(project_root, final_native["frequency_domain_qc_report"], policy)
                if sha256_bytes(policy_path.resolve(strict=True).read_bytes()) != policy_sha:
                    raise ValueError("Benchmark policy changed before/during application")
                automation.update(policy_path=str(policy_path.resolve()), policy_sha256=policy_sha,
                                  project_root=str(project_root), applied_at_utc=utc_now())
                write_json(automation_target, automation)
                receipt["benchmark_qc_policy_automation_receipt"] = str(automation_target)
                receipt["benchmark_qc_policy_sha256"] = policy_sha
                # A fresh canonical Project observes the true saved native decision state.
                project = Project.load(project_root)
                policy_action_elapsed = perf_counter() - policy_started
            receipt["production_source_inventory"] = source_inventory(source_root)
            if sha256_bytes((source_root / WORKER_RELATIVE).read_bytes()) != binding["worker_source_sha256"]:
                raise RuntimeError("Worker source changed during execution")
        except Exception as exc:
            LOG.exception("downstream_probe_failed")
            error = {"type": type(exc).__name__, "message": str(exc)}
    receipt.update(
        finished_at_utc=utc_now(),
        total_elapsed_seconds=perf_counter() - start,
        worker_run_elapsed_seconds=worker_elapsed,
        worker_run_attempts=attempts,
        benchmark_policy_action_elapsed_seconds_excluded_from_worker_time=policy_action_elapsed,
        actual_review_report_paths=review_paths,
        signal_event_count=sequence,
        phase_progress_payloads=phase_payloads,
        condition_repair_manifest_preimages=repair_manifest_preimages,
        observer_manifest_capture_windows_excluded_from_worker_time=observer_capture_windows,
        finished_payloads=finished_payloads,
        error=error,
        audited_mutation_count=guard.audited_mutations,
        denied_writes=list(guard.denied),
        project_manifest_after_sha256=sha256_bytes((project_root / "project.json").read_bytes()),
    )
    final = finished_payloads[-1] if finished_payloads else {}
    if error is not None or guard.denied or len(finished_payloads) != len(attempts) or not finished_payloads:
        status, exit_code = "probe_failed", 1
    elif final.get("requires_frequency_domain_qc_review"):
        status, exit_code = "frequency_domain_qc_review_required", 3
        if review_paths:
            receipt["actual_review_report_path"] = review_paths[-1]
    elif final.get("failure_reason") or final.get("requires_processing") or not final.get("ok"):
        status, exit_code = "native_pipeline_incomplete", 4
    else:
        status, exit_code = "complete", 0
    receipt["status"] = status
    receipt["exit_code"] = exit_code
    write_json(target, receipt)
    LOG.info("downstream_probe_finished status=%s receipt=%s", status, target)
    return exit_code


@contextmanager
def synthetic_imports():
    """Use minimal computation stubs only for --self-test, restoring all imports."""
    replacements = {
        "Main_App.io": {"xlsx_read_cache_scope": nullcontext},
        "Main_App.processing.post_processing_context": {"post_processing_validation_scope": nullcontext},
        "Main_App.processing.condition_interpolation_executor": {"execute_pending_condition_interpolations": lambda *_a, **_k: False, "ConditionInterpolationProcessingRequired": type("ConditionInterpolationProcessingRequired", (RuntimeError,), {})},
        "Main_App.processing.condition_interpolation_state": {"require_no_pending_condition_interpolation": lambda *_a: None},
        "Main_App.projects": {"project_recording_context": lambda _project: SimpleNamespace(is_repeated_session=True)},
    }
    previous = {name: sys.modules.get(name) for name in replacements}
    try:
        for name, attrs in replacements.items():
            module = ModuleType(name)
            vars(module).update(attrs)
            sys.modules[name] = module
        yield
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def self_test(source_root: Path) -> dict:
    """Validate binding/constructor, native run order, repeated skips, and review."""
    worker_class, module, binding = bind_worker(source_root)
    project = SimpleNamespace(project_root=source_root / ".codex-tmp" / "probe-self-test-nonexistent")
    worker = worker_class(project)
    assert worker._project is project
    assert worker._provisional_cache is None and worker._dataset_index is None
    assert worker._harmonic_selection_metadata is None
    assert worker._artifact_targets == {} and worker._artifact_archives == {}
    assert worker._resume_from_selection is False
    copied_selection = {"key": "original"}
    second = worker_class(project, resume_from_selection=True, selection_metadata=copied_selection, previous_selection_fingerprint="prior", provisional_cache="cache")
    copied_selection["key"] = "changed"
    assert second._harmonic_selection_metadata == {"key": "original"}
    assert second._previous_selection_fingerprint == "prior" and second._provisional_cache == "cache"
    assert worker.finished is not second.finished
    calls = []
    results = []
    phases = []
    worker.finished.connect(results.append)
    worker.phase_progress.connect(lambda *args: phases.append(args))
    worker._capture_previous_selection_fingerprint = lambda _root: calls.append("capture")
    worker._run_frequency_domain_qc_review = lambda: (calls.append("qc") or {"review_required": False, "review_reused": False})
    worker._sync_frequency_domain_qc_automatic_state = lambda *_a: calls.append("sync")
    worker._finalize_frequency_qc_release = lambda _root: calls.append("release")
    def full_fft(_root, steps):
        assert steps[0].name == "frequency_domain_qc" and steps[0].ok
        calls.append("provenance")
        return module.PostProcessingStepResult("full_fft_provenance", True, "synthetic")
    worker._run_full_fft_provenance = full_fft
    worker._run_harmonic_selection = lambda: (calls.append("selection") or module.PostProcessingStepResult("harmonic_selection", True, "synthetic"))
    worker._activate_artifact_freshness = lambda *_a, **_k: calls.append("freshness")
    worker._run_analysis_ready_export = lambda _root: (calls.append("audit") or module.PostProcessingStepResult("analysis_ready_full_audit", True, "synthetic"))
    worker._record_failed_frequency_outputs = lambda *_a: calls.append("failures")
    with synthetic_imports():
        worker.run()
    assert calls == ["capture", "qc", "sync", "release", "provenance", "selection", "freshness", "audit", "failures"]
    assert len(results) == 1 and results[0]["ok"] and not results[0]["failure_reason"]
    native_skips = [row for row in results[0]["steps"] if row["name"] in ("stats_ready_summed_bca", *module.SOURCE_OUTPUT_MODES)]
    assert len(native_skips) == 3 and all(row["ok"] and "repeated-session" in row["message"] for row in native_skips)
    assert phases[-1][0] == "post_processing_complete"
    assert worker._dataset_index is None and worker._harmonic_selection_metadata is None
    worker._run_analysis_ready_export = lambda _root: module.PostProcessingStepResult("analysis_ready_full_audit", False, "synthetic required-export failure")
    with synthetic_imports():
        worker.run()
    assert len(results) == 2 and results[-1]["ok"] is False
    assert "synthetic required-export failure" in results[-1]["failure_reason"]
    assert phases[-1][0] == "post_processing_failed"
    review = worker_class(project)
    review_payloads = []
    actual_report = {"review_required": True, "review_reused": False, "findings": [{"id": "synthetic-finding"}]}
    review._capture_previous_selection_fingerprint = lambda _root: None
    review._run_frequency_domain_qc_review = lambda: actual_report
    review._run_harmonic_selection = lambda: (_ for _ in ()).throw(AssertionError("Review gate was bypassed"))
    review.finished.connect(review_payloads.append)
    with synthetic_imports():
        review.run()
    assert len(review_payloads) == 1 and review_payloads[0]["requires_frequency_domain_qc_review"]
    assert review_payloads[0]["frequency_domain_qc_report"] is actual_report
    synthetic_finding = {"finding_type": "absolute_electrode_summed_bca", "recording_id": "P01__VISIT1", "condition": "Faces", "electrode": "O1", "severity": "warning", "finding_fingerprint": "a" * 64}
    synthetic_policy = {"expected_findings": [{key: synthetic_finding[key] for key in FINDING_FIELDS}], "reason": "Performance fixture: retain identical inputs"}
    policy_report = {"identity_scope": "recording", "review_required": True, "qc_complete": True, "review_findings": [synthetic_finding]}
    rows = benchmark_decision_rows(policy_report, synthetic_policy)
    assert rows == [{"finding_fingerprint": "a" * 64, "decision": "retain", "reason": synthetic_policy["reason"]}]
    for changed in ({**policy_report, "technical_integrity_failed": True}, {**policy_report, "manual_recording_exclusions": [{"recording_id": "P01__VISIT1"}]}, {**policy_report, "review_findings": [{**synthetic_finding, "severity": "strong"}]}, {**policy_report, "review_findings": []}):
        try:
            benchmark_decision_rows(changed, synthetic_policy)
        except ValueError:
            pass
        else:
            raise AssertionError("Benchmark policy bypassed a finding/integrity guard")
    guard = WriteGuard(source_root, source_root)
    guard("open", (source_root / "synthetic-output.json", "w", os.O_WRONLY | os.O_CREAT))
    for rejected in (source_root / "synthetic-input.BDF", source_root.parent / "synthetic-output.json"):
        try:
            guard("open", (rejected, "w", os.O_WRONLY | os.O_CREAT))
        except PermissionError:
            pass
        else:
            raise AssertionError("Write guard accepted a forbidden path")
    assert len(guard.denied) == 2
    assert json_value(float("nan"))["float64_hex"] == struct.pack(">d", float("nan")).hex()
    try:
        json_value(object())
    except TypeError:
        pass
    else:
        raise AssertionError("Unknown report objects were silently serialized")
    return {"schema": SCHEMA, "self_test": "passed", "real_project_computation": False, "binding": binding, "mocked_phase_order": calls, "native_repeated_session_skip_count": len(native_skips), "review_gate_preserved": True, "required_export_failure_preserved": True, "write_guard_checked": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--scratch-root", type=Path)
    parser.add_argument("--output")
    parser.add_argument("--events")
    parser.add_argument("--expected-worker-sha256")
    parser.add_argument("--benchmark-review-policy", type=Path, help="Optional explicit workspace-local Keep policy for matched engineering-fixture findings; default is a native review pause")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.self_test:
        result = self_test(args.source_root.resolve(strict=True))
        LOG.info("downstream_probe_self_test status=%s method_count=%d worker_sha256=%s", result["self_test"], len(result["binding"]["production_method_ast_sha256"]), result["binding"]["worker_source_sha256"])
        return 0
    for name in ("workspace_root", "project_root", "scratch_root", "output"):
        if getattr(args, name) is None:
            parser.error(f"--{name.replace('_', '-')} is required unless --self-test is used")
    return run_probe(args)


if __name__ == "__main__":
    raise SystemExit(main())
