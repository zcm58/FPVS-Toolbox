"""Run the frozen powered-null calibration outside routine verification.

The official protocol is intentionally expensive (4,000 synthetic null
replicates x 10,000 permutation assignments).  Results are checkpointed in a
caller-selected directory and can be resumed with the same command.  This
script is never invoked by pytest, focused verification, or precommit.

Example
-------
python scripts/manual_diagnostics/run_free_harmonic_clustering_null_calibration.py \
    --output-dir .codex-tmp/fhc-null-calibration-v1 --workers 8
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import hashlib
import json
import logging
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Iterable
import uuid

# Each process parallelizes across replicates.  Prevent nested BLAS pools from
# multiplying the requested worker count before NumPy/SciPy are imported.
for _variable in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ.setdefault(_variable, "1")

_SCRIPT_PATH = Path(__file__).resolve()
_REPOSITORY_ROOT = _SCRIPT_PATH.parents[2]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

import numpy as np  # noqa: E402
import scipy  # noqa: E402

from Tools.Free_Harmonic_Clustering.null_calibration import (  # noqa: E402
    CALIBRATION_DETERMINISM_BATCH_SIZE,
    CALIBRATION_DETERMINISM_PERMUTATIONS,
    CALIBRATION_DETERMINISM_PROTOCOL_ID,
    DEFAULT_NULL_CALIBRATION_PROTOCOL,
    NullCalibrationProtocol,
    NullCalibrationReplicate,
    NullCalibrationTask,
    build_calibration_receipt,
    calibration_tasks,
    canonical_json_bytes,
    determinism_tasks,
    ordered_results_fingerprint,
    protocol_fingerprint,
    protocol_payload,
    replicate_from_payload,
    replicate_payload,
    run_null_calibration_replicate,
    validate_determinism_check,
    validate_replicate_for_task,
)


LOGGER = logging.getLogger("fpvs.fhc_null_calibration")
_PROTOCOL_FILENAME = "protocol.json"
_CHECKPOINT_FILENAME = "results.jsonl"
_RECEIPT_FILENAME = "receipt.json"


def _default_worker_count() -> int:
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Run or resume the frozen 4,000 x 10,000 Free Harmonic Clustering powered-null calibration.")
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Dedicated directory for protocol, checkpoint rows, and the final receipt.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=_default_worker_count(),
        help="Independent replicate worker processes (default: up to 8).",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=10,
        help="Atomically rewrite the ordered JSONL checkpoint after this many new rows.",
    )
    parser.add_argument(
        "--max-new-replicates",
        type=int,
        default=None,
        help="Optional resumable chunk limit; omit for all remaining replicates.",
    )
    return parser.parse_args(argv)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json(path: Path, payload: object) -> None:
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def _protocol_document() -> dict[str, object]:
    return {
        "protocol_fingerprint_sha256": protocol_fingerprint(),
        "protocol": protocol_payload(),
        "execution_identity": _execution_identity(),
    }


def _ensure_protocol(path: Path) -> None:
    expected = _protocol_document()
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Cannot read existing protocol document: {path}") from exc
        if existing != expected:
            raise RuntimeError(
                "The output directory belongs to a different calibration protocol. "
                "Choose a new directory; existing checkpoints were not modified."
            )
        return
    _write_json(path, expected)


def _load_checkpoint(path: Path) -> dict[str, NullCalibrationReplicate]:
    if not path.exists():
        return {}
    results: dict[str, NullCalibrationReplicate] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            result = replicate_from_payload(json.loads(line))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid checkpoint row {line_number} in {path}.") from exc
        if result.task_id in results:
            raise RuntimeError(f"Duplicate checkpoint task ID {result.task_id!r} in {path}.")
        results[result.task_id] = result
    return results


def _checkpoint_bytes(results: Iterable[NullCalibrationReplicate]) -> bytes:
    ordered = sorted(results, key=lambda value: value.task_id)
    return b"".join(canonical_json_bytes(replicate_payload(value)) + b"\n" for value in ordered)


def _write_checkpoint(path: Path, results: dict[str, NullCalibrationReplicate]) -> None:
    _atomic_write(path, _checkpoint_bytes(results.values()))


def _run_official_task(task: NullCalibrationTask) -> NullCalibrationReplicate:
    return run_null_calibration_replicate(task, DEFAULT_NULL_CALIBRATION_PROTOCOL)


def _run_determinism_task(
    job: tuple[NullCalibrationTask, NullCalibrationProtocol],
) -> NullCalibrationReplicate:
    task, protocol = job
    return run_null_calibration_replicate(task, protocol)


def _runtime_payload(*, workers: int, result_count: int) -> dict[str, object]:
    return {
        "toolbox_commit": _toolbox_commit(),
        **_execution_identity(),
        "workers": workers,
        "completed_checkpoint_rows": result_count,
    }


def _scientific_source_hashes() -> dict[str, str]:
    relative_paths = (
        Path("src/Tools/Free_Harmonic_Clustering/analysis.py"),
        Path("src/Tools/Free_Harmonic_Clustering/models.py"),
        Path("src/Tools/Free_Harmonic_Clustering/preparation.py"),
        Path("src/Tools/Free_Harmonic_Clustering/null_calibration.py"),
        Path("scripts/manual_diagnostics/run_free_harmonic_clustering_null_calibration.py"),
    )
    return {
        path.as_posix(): hashlib.sha256((_REPOSITORY_ROOT / path).read_bytes()).hexdigest() for path in relative_paths
    }


def _execution_identity() -> dict[str, object]:
    """Return the immutable code and runtime identity bound to a checkpoint."""

    return {
        "scientific_source_sha256": _scientific_source_hashes(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
    }


def _checkpoint_round_trip(
    results: Iterable[NullCalibrationReplicate],
) -> tuple[NullCalibrationReplicate, ...]:
    checkpoint = _checkpoint_bytes(results)
    return tuple(replicate_from_payload(json.loads(line)) for line in checkpoint.decode("utf-8").splitlines() if line)


def _run_determinism_check() -> dict[str, object]:
    """Compare non-official rows across serial, checkpoint, and process execution."""

    protocol = replace(
        DEFAULT_NULL_CALIBRATION_PROTOCOL,
        permutations_per_replicate=CALIBRATION_DETERMINISM_PERMUTATIONS,
        permutation_batch_size=CALIBRATION_DETERMINISM_BATCH_SIZE,
    )
    tasks = determinism_tasks(protocol)
    serial = tuple(run_null_calibration_replicate(task, protocol) for task in tasks)
    resumed = _checkpoint_round_trip(serial)
    jobs = tuple((task, protocol) for task in tasks)
    with ProcessPoolExecutor(max_workers=min(2, len(tasks))) as executor:
        parallel = tuple(executor.map(_run_determinism_task, jobs, chunksize=1))
    for result_set in (serial, resumed, parallel):
        for task, result in zip(tasks, result_set, strict=True):
            validate_replicate_for_task(result, task, protocol=protocol)
    serial_hash = ordered_results_fingerprint(serial)
    resumed_hash = ordered_results_fingerprint(resumed)
    parallel_hash = ordered_results_fingerprint(parallel)
    report = {
        "protocol_id": CALIBRATION_DETERMINISM_PROTOCOL_ID,
        "task_ids": [task.task_id for task in tasks],
        "permutations_per_replicate": CALIBRATION_DETERMINISM_PERMUTATIONS,
        "permutation_batch_size": CALIBRATION_DETERMINISM_BATCH_SIZE,
        "serial_results_sha256": serial_hash,
        "resumed_results_sha256": resumed_hash,
        "parallel_results_sha256": parallel_hash,
        "status": ("pass" if len({serial_hash, resumed_hash, parallel_hash}) == 1 else "fail"),
    }
    validate_determinism_check(report)
    return report


def _toolbox_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    commit = completed.stdout.strip()
    return commit if completed.returncode == 0 and commit else "unavailable"


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.workers < 1:
        raise ValueError("--workers must be positive.")
    if args.checkpoint_every < 1:
        raise ValueError("--checkpoint-every must be positive.")
    if args.max_new_replicates is not None and args.max_new_replicates < 1:
        raise ValueError("--max-new-replicates must be positive when supplied.")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    protocol_path = output_dir / _PROTOCOL_FILENAME
    checkpoint_path = output_dir / _CHECKPOINT_FILENAME
    receipt_path = output_dir / _RECEIPT_FILENAME
    if checkpoint_path.exists() and not protocol_path.exists():
        raise RuntimeError(
            "Checkpoint exists without its protocol document. Choose a new output "
            "directory or restore the matching protocol.json; no rows were modified."
        )
    _ensure_protocol(protocol_path)
    results = _load_checkpoint(checkpoint_path)

    all_tasks = calibration_tasks()
    task_by_id = {task.task_id: task for task in all_tasks}
    expected_ids = set(task_by_id)
    unexpected = sorted(set(results) - expected_ids)
    if unexpected:
        raise RuntimeError("Checkpoint contains task IDs outside the frozen protocol: " + ", ".join(unexpected[:5]))
    for task_id, result in results.items():
        try:
            validate_replicate_for_task(
                result,
                task_by_id[task_id],
                protocol=DEFAULT_NULL_CALIBRATION_PROTOCOL,
            )
        except ValueError as exc:
            raise RuntimeError(f"Checkpoint scientific row {task_id!r} is invalid; no rows were modified.") from exc
    determinism_check = _run_determinism_check()
    remaining = [task for task in all_tasks if task.task_id not in results]
    if args.max_new_replicates is not None:
        remaining = remaining[: args.max_new_replicates]

    LOGGER.info(
        "Calibration %s: %d/%d rows already complete; scheduling %d with %d workers.",
        DEFAULT_NULL_CALIBRATION_PROTOCOL.protocol_id,
        len(results),
        len(all_tasks),
        len(remaining),
        args.workers,
    )
    new_since_checkpoint = 0
    executor: ProcessPoolExecutor | None = None
    try:
        if remaining:
            executor = ProcessPoolExecutor(max_workers=args.workers)
            for result in executor.map(_run_official_task, remaining, chunksize=1):
                results[result.task_id] = result
                new_since_checkpoint += 1
                if result.status == "error":
                    LOGGER.error("%s failed: %s", result.task_id, result.error)
                elif len(results) % 25 == 0:
                    LOGGER.info("Completed %d/%d protocol rows.", len(results), len(all_tasks))
                if new_since_checkpoint >= args.checkpoint_every:
                    _write_checkpoint(checkpoint_path, results)
                    new_since_checkpoint = 0
            executor.shutdown(wait=True)
            executor = None
    except KeyboardInterrupt:
        LOGGER.warning("Interrupted; preserving completed rows for resume.")
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        _write_checkpoint(checkpoint_path, results)
        return 130
    except BaseException:
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        _write_checkpoint(checkpoint_path, results)
        raise
    finally:
        if new_since_checkpoint or not checkpoint_path.exists():
            _write_checkpoint(checkpoint_path, results)

    if len(results) != len(all_tasks):
        LOGGER.info(
            "Checkpoint contains %d/%d rows. Re-run the same command to continue.",
            len(results),
            len(all_tasks),
        )
        return 0

    receipt = build_calibration_receipt(
        (results[task.task_id] for task in all_tasks),
        determinism_check=determinism_check,
        runtime=_runtime_payload(workers=args.workers, result_count=len(results)),
    )
    _write_json(receipt_path, receipt)
    status = receipt["assessment"]["status"]
    LOGGER.info("Complete receipt written to %s with assessment %s.", receipt_path, status)
    return 0 if status == "pass" else 2


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(run())


if __name__ == "__main__":
    main()
