"""Copy every manifest-declared BDF into a new isolated RAM benchmark fixture.

Inspect mode reads metadata only. Creation streams and verifies raw input bytes,
preserves the original study method/review settings, and inventories actual prior
human marker receipts. It never processes EEG or modifies the source project.
The coordinator must serialize this substantial copy/hash I/O with timing trials.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import shutil
import stat


LOG = logging.getLogger(__name__)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def destination(root: Path, value: Path) -> Path:
    resolved = value.resolve(strict=False)
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError(f"Fixture output escapes benchmark root: {resolved}")
    return resolved


def inventory(project_manifest: Path, root: Path) -> tuple[dict, list[dict]]:
    project = json.loads(project_manifest.read_text(encoding="utf-8"))
    rows = []
    seen = set()
    for recording_id, recording in project["recordings"].items():
        source = Path(recording["raw_file"])
        source = (source if source.is_absolute() else project_manifest.parent / source).resolve(strict=True)
        if source.suffix.lower() != ".bdf" or not source.is_file():
            raise ValueError(f"Manifest recording is not a regular BDF: {source}")
        source_id = recording["source_id"]
        group_id = project["recording_sources"][source_id]["group_id"]
        target = destination(root, root / "inputs" / group_id / recording["session_id"] / source.name)
        if target in seen:
            raise ValueError("Duplicate benchmark input destination")
        seen.add(target)
        metadata = source.stat()
        rows.append({"recording_id": recording_id, "original_path": str(source),
                     "benchmark_input_path": str(target), "size_bytes": metadata.st_size,
                     "source_mtime_ns": metadata.st_mtime_ns})
    if not rows:
        raise ValueError("Source project contains no declared recordings")
    return project, rows


def copy_verified(row: dict, root: Path) -> dict:
    source = Path(row["original_path"])
    target = destination(root, Path(row["benchmark_input_path"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)
    before = source.stat()
    if before.st_size != row["size_bytes"] or before.st_mtime_ns != row["source_mtime_ns"]:
        raise RuntimeError(f"Source metadata changed after fixture inventory: {source}")
    sha = hashlib.sha256()
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        while chunk := incoming.read(16 * 1024 * 1024):
            sha.update(chunk)
            outgoing.write(chunk)
    after = source.stat()
    def identity(value):
        return value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_ino, value.st_dev
    if identity(before) != identity(after) or target.stat().st_size != before.st_size:
        raise RuntimeError(f"Source changed during benchmark input copy: {source}")
    checksum = sha.hexdigest()
    if digest(target) != checksum:
        raise RuntimeError(f"Benchmark input copy checksum mismatch: {target}")
    shutil.copystat(source, target)
    target.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
    return {**row, "sha256": checksum, "copied_input_read_only": True}


def marker_inventory(paths: list[Path], project: dict, root: Path) -> dict:
    originals = []
    evidence = []
    seen = set()
    for path in paths:
        encoded = path.read_bytes()
        payload = json.loads(encoded)
        def canonical(value):
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        if hashlib.sha256(canonical(payload["key"])).hexdigest() != payload["fingerprint"]:
            raise ValueError("Original marker evidence cache key failed its fingerprint")
        if hashlib.sha256(canonical(payload["result"])).hexdigest() != payload["result_sha256"]:
            raise ValueError("Original marker evidence cache result failed its checksum")
        found = []
        for span in payload["key"]["event_plan"]["approved_occurrences"]:
            decision = span.get("decision_payload")
            if decision is not None:
                found.append(decision)
        if not found:
            raise ValueError(f"No actual marker review receipt in evidence: {path}")
        for decision in found:
            key = (decision["recording_id"], decision["occurrence_key"])
            if key in seen:
                raise ValueError("Duplicate original marker receipt")
            seen.add(key)
            raw = Path(project["recordings"][key[0]]["raw_file"]).resolve(strict=True)
            if Path(decision["source_file_path"]).resolve(strict=True) != raw:
                raise ValueError("Original marker receipt does not belong to the declared source")
            if decision["decision"] != "exclude_occurrence" or decision["reviewer_state"] != "explicit_gui_review":
                raise ValueError("Only existing explicit GUI occurrence exclusions are supported")
            originals.append(decision)
        target = destination(root, root / "evidence" / path.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(encoded)
        evidence.append({"original_evidence_path": str(path.resolve(strict=True)),
                         "frozen_evidence_path": str(target), "sha256": hashlib.sha256(encoded).hexdigest()})
    return {"schema": "pipeline_marker_review_replay_v1", "original_decisions": originals,
            "source_evidence": evidence,
            "policy": "Reuse actual prior human occurrence exclusions only after fresh native marker and occurrence fingerprints match; preserve original human review times and reasons."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--fixture-name", default="full58")
    parser.add_argument("--marker-evidence", type=Path, nargs="+", default=[])
    parser.add_argument("--create", action="store_true", help="Perform serialized full-data copy/hash work; inspect is the default")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    source_manifest = (args.source_project / "project.json").resolve(strict=True)
    original_encoded = source_manifest.read_bytes()
    source_sha = hashlib.sha256(original_encoded).hexdigest()
    benchmark_root = args.benchmark_root.resolve(strict=True)
    root = destination(benchmark_root, benchmark_root / args.fixture_name)
    if root.is_relative_to(source_manifest.parent) or source_manifest.parent.is_relative_to(root):
        parser.error("Fixture and original study must have distinct non-nested roots")
    project, rows = inventory(source_manifest, root)
    if digest(source_manifest) != source_sha:
        raise RuntimeError("Original project manifest changed while reading its inventory")
    total = sum(row["size_bytes"] for row in rows)
    LOG.info("full_dataset_fixture recordings=%d participants=%d raw_bytes=%d raw_gib=%.6f root=%s create=%s",
             len(rows), len(project["participants"]), total, total / 1024**3, root, args.create)
    if not args.create:
        return 0
    root.mkdir(exist_ok=False)
    frozen = deepcopy(project)
    frozen["name"] = "Full Dataset RAM Preload Benchmark"
    frozen["results_folder"] = "."
    for group_id, group in frozen["groups"].items():
        group["raw_input_folder"] = str(destination(root, root / "inputs" / group_id))
    for source in frozen["recording_sources"].values():
        source["raw_input_folder"] = str(destination(root, root / "inputs" / source["group_id"] / source["session_id"]))
    for key, value in frozen["subfolders"].items():
        if Path(value).is_absolute():
            frozen["subfolders"][key] = Path(value).name
    copied = []
    for index, row in enumerate(rows, 1):
        copied.append(copy_verified(row, root))
        frozen["recordings"][row["recording_id"]]["raw_file"] = row["benchmark_input_path"]
        LOG.info("full_dataset_input_verified completed=%d total=%d recording=%s bytes=%d", index, len(rows), row["recording_id"], row["size_bytes"])
    (root / "original_project.json").write_bytes(original_encoded)
    (root / "frozen_project.json").write_text(json.dumps(frozen, indent=2) + "\n", encoding="utf-8")
    replay = marker_inventory(args.marker_evidence, project, root)
    (root / "marker_review_replay.json").write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    receipt = {"schema": "pipeline_full_dataset_fixture_v1", "created_utc": datetime.now(timezone.utc).isoformat(),
               "original_project": str(source_manifest), "original_project_sha256": source_sha,
               "frozen_project_sha256": digest(root / "frozen_project.json"), "raw_input_bytes": total,
               "inputs": copied, "study_preprocessing_settings": project["preprocessing"],
               "study_experimental_qc_settings": project["experimental_qc"],
               "scope": "All original manifest-declared recordings, participants, groups and sessions. Original statistical methods and pending reviews preserved. Only copied input/output locations and benchmark display name differ.",
               "comparison_settings": "Each trial sets only experimental_ram_preload and the same explicit worker limit in a fresh project copy; immutable frozen settings remain unchanged."}
    (root / "input_manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if digest(source_manifest) != source_sha:
        raise RuntimeError("Original project manifest changed during fixture publication")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
