"""Project identity and immutable, bounded snapshot outbox (no credentials)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from Main_App.projects.manifest_store import project_manifest_transaction
from Main_App.io.atomic_write import atomic_write
from Main_App.io.safe_file import regular_file_info

MAX_REQUEST_BYTES = 1_048_576
MAX_CSV_BYTES = 512 * 1024
MAX_MANIFEST_BYTES = 32 * 1024
MAX_MANIFEST_V11_BYTES = 256 * 1024
MAX_OUTBOX_BYTES = 16 * 1024 * 1024
MAX_PENDING = 32
MAX_ATTEMPTS = 5
STATE_NAME = ".openfpvs-reporting.json"
SNAPSHOT_DIRECTORY = ".openfpvs-reporting/snapshots"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def snapshot_sha256(manifest: dict[str, Any], results_csv: str) -> str:
    unsigned = {key: value for key, value in manifest.items() if key != "snapshot_sha256"}
    return hashlib.sha256((canonical_json(unsigned) + "\n" + results_csv).encode("utf-8")).hexdigest()


def state_path(project_root: Path) -> Path:
    return Path(project_root).resolve() / STATE_NAME


def read_state(project_root: Path) -> dict[str, Any]:
    path = state_path(project_root)
    regular_file_info(path)
    if not path.exists():
        return {"schema_version": "1.0", "dataset_id": str(uuid4()), "pending": [], "last_snapshot_id": None}
    if path.stat().st_size > 128 * 1024:
        raise ValueError("Reporting state exceeds its size limit.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "1.0"
        or not isinstance(value.get("pending"), list)
    ):
        raise ValueError("Reporting state is invalid.")
    UUID(value["dataset_id"])
    if len(value["pending"]) > MAX_PENDING:
        raise ValueError("Reporting outbox has too many pending snapshots.")
    for item in value["pending"]:
        if not isinstance(item, dict) or not isinstance(item.get("attempts"), int) or item["attempts"] < 0:
            raise ValueError("Reporting pending state is invalid.")
        UUID(item["snapshot_id"])
    return value


def dataset_identity(project_root: Path) -> str:
    """Create once; copying this sidecar preserves the scientific dataset identity."""
    with project_manifest_transaction(state_path(project_root)) as transaction:
        state = read_state(project_root)
        transaction.write(state)
        return state["dataset_id"]


def save_scope(project_root: Path, scope: dict[str, str], enrollment: dict | None = None) -> None:
    with project_manifest_transaction(state_path(project_root)) as transaction:
        state = read_state(project_root)
        if state.get("scope") and state["scope"] != scope:
            raise ValueError("This dataset already belongs to another OpenFPVS study. Review the linked project.")
        state["scope"] = dict(scope)
        if enrollment is not None:
            state["enrollment"] = {key: enrollment[key] for key in ("approval_status", "upload_enabled")}
        transaction.write(state)


def queue_snapshot(project_root: Path, manifest: dict[str, Any], results_csv: str) -> Path:
    """Freeze one successful processing revision; retries never rebuild its bytes."""
    if len(results_csv.encode("utf-8")) > MAX_CSV_BYTES:
        raise ValueError("CSV exceeds the OpenFPVS 512 KiB limit. Local analysis files are retained.")
    root = Path(project_root).resolve()
    with project_manifest_transaction(state_path(root)) as transaction:
        state = read_state(root)
        if state["pending"]:
            pending = state["pending"][-1]
            old = load_snapshot(root, pending["snapshot_id"])["manifest"]
            if (
                len(state["pending"]) == 1
                and pending["status"] == "roster_revision_conflict"
                and old.get("roster_coverage", {}).get("roster_revision")
                != manifest.get("roster_coverage", {}).get("roster_revision")
            ):
                # The service explicitly rejected this roster. Keep the old file
                # and publish the reviewed replacement against its accepted parent.
                state["last_snapshot_id"] = old["parent_snapshot_id"]
                state["pending"].clear()
            else:
                raise ValueError(
                    "A snapshot is already pending. Retry its original bytes before sharing another revision."
                )
        if state["dataset_id"] != manifest.get("dataset_id"):
            raise ValueError("The reporting dataset changed during export.")
        if state.get("scope") != {
            key: manifest[key] for key in ("study_id", "experiment_id", "experiment_version", "protocol_sha256")
        }:
            raise ValueError("The reporting destination changed during export.")
        if state["last_snapshot_id"]:
            last = load_snapshot(root, state["last_snapshot_id"])
            identity_fields = {"snapshot_id", "parent_snapshot_id", "snapshot_sha256"}
            previous = {key: value for key, value in last["manifest"].items() if key not in identity_fields}
            if previous == manifest and last["results_csv"] == results_csv:
                raise ValueError("OpenFPVS already accepted this exact result revision.")
        revision = dict(manifest)
        revision.update(
            snapshot_id=str(uuid4()), parent_snapshot_id=state["last_snapshot_id"]
        )
        revision["snapshot_sha256"] = snapshot_sha256(revision, results_csv)
        manifest_json = canonical_json({key: value for key, value in revision.items() if key != "snapshot_sha256"})
        manifest_limit = (
            MAX_MANIFEST_V11_BYTES if revision.get("schema_version") in {"1.1", "1.2"} else MAX_MANIFEST_BYTES
        )
        if len(manifest_json.encode("utf-8")) > manifest_limit:
            raise ValueError("Snapshot manifest exceeds its size limit.")
        envelope = {
            "schema_version": "1.0",
            "manifest": revision,
            "manifest_json": manifest_json,
            "results_csv": results_csv,
        }
        encoded = canonical_json(envelope).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("Snapshot exceeds the OpenFPVS request limit.")
        directory = root / SNAPSHOT_DIRECTORY
        if directory.resolve() != directory:
            raise ValueError("Reporting snapshot directory must not be a linked directory.")
        directory.mkdir(parents=True, exist_ok=True)
        size = sum(path.stat().st_size for path in directory.glob("*.json"))
        if size + len(encoded) > MAX_OUTBOX_BYTES:
            raise ValueError("Reporting snapshot storage is full. Local analysis files are retained.")
        path = directory / f"{revision['snapshot_id']}.json"
        regular_file_info(path)
        if path.exists():
            raise ValueError("A snapshot with this identity already exists.")
        with atomic_write(path, binary=True) as stream:
            stream.write(encoded)
        state["last_snapshot_id"] = revision["snapshot_id"]
        state["pending"].append({"snapshot_id": revision["snapshot_id"], "attempts": 0, "status": "pending"})
        transaction.write(state)
        return path


def load_snapshot(project_root: Path, snapshot_id: str) -> dict[str, Any]:
    identifier = str(UUID(snapshot_id))
    directory = Path(project_root).resolve() / SNAPSHOT_DIRECTORY
    if directory.resolve() != directory:
        raise ValueError("Reporting snapshot directory must not be a linked directory.")
    path = directory / f"{identifier}.json"
    regular_file_info(path)
    if path.stat().st_size > MAX_REQUEST_BYTES:
        raise ValueError("Stored snapshot exceeds its size limit.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    manifest = payload["manifest"]
    unsigned = {key: value for key, value in manifest.items() if key != "snapshot_sha256"}
    if (
        payload.get("manifest_json") != canonical_json(unsigned)
        or manifest["snapshot_id"] != identifier
        or manifest["snapshot_sha256"] != snapshot_sha256(manifest, payload["results_csv"])
    ):
        raise ValueError("Stored snapshot integrity check failed.")
    return payload


def record_delivery(project_root: Path, snapshot_id: str, *, accepted: bool, status: str) -> None:
    with project_manifest_transaction(state_path(project_root)) as transaction:
        state = read_state(project_root)
        for item in state["pending"]:
            if item["snapshot_id"] == snapshot_id:
                item["attempts"] += 1
                item["status"] = status
        if accepted:
            state["pending"] = [item for item in state["pending"] if item["snapshot_id"] != snapshot_id]
        transaction.write(state)
