"""Fail-closed, read-only comparison of isolated pipeline artifacts.

Examples::

    python scripts/manual_diagnostics/pipeline_bitwise_compare.py before after --report .codex-tmp/parity.json
    python scripts/manual_diagnostics/pipeline_bitwise_compare.py --self-test

All files are included unless the supplied policy explicitly excludes them.
JSON rules address one file pattern and one JSON-pointer pattern; they never
drop fingerprint/hash keys. Native declarations and physical artifact bindings
are validated before any runtime-field normalization. A common original project
root should be used for baseline/candidate archives whenever possible.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile
from typing import Any
from types import SimpleNamespace
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
CHUNK_BYTES = 1024 * 1024
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_CORE_TIME = re.compile(rb"(<dcterms:(created|modified)\b[^>]*>)([^<]*)(</dcterms:\2>)")
_ELAPSED = {"elapsed", "elapsed_ms", "elapsed_s", "elapsed_seconds", "wall_time_seconds"}
_GENERATED = {"generated_at_utc", "created_at_utc", "written_at_utc", "saved_at_utc", "exported_at_utc",
              "started_utc", "finished_utc"}
_PATHS = {"path", "project_root", "output_root", "save_folder", "fif_path", "sidecar_path", "cache_folder"}


class ParityError(ValueError):
    """An artifact is invalid or differs outside the approved runtime policy."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ParityError(message)


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json_load(path: Path, content: str | None = None) -> Any:
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, f"Duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8") if content is None else content, object_pairs_hook=object_pairs)


def _stable_document(path: Path) -> Any:
    if path.suffix.lower() != ".jsonl":
        return _json_load(path)
    _require(path.name == "processing_runs.jsonl" and path.parent.name == ".fpvs_processing",
             "Uncharacterized stable JSON-lines artifact")
    content = path.read_text(encoding="utf-8")
    _require(content.endswith("\n") and all(line for line in content.splitlines()),
             "Malformed native processing-run journal framing")
    values = [_json_load(path, line) for line in content.splitlines()]
    _require(all(isinstance(value, dict) and isinstance(value.get("timestamp"), str)
                 and value.get("processing_fingerprint_version") == "processing_fingerprint_v13_v3_trigger_alignment"
                 for value in values), "Uncharacterized processing-run journal schema")
    return values


def _exact(value: Any) -> Any:
    """Preserve scalar float bits, numeric types and dictionary/list order."""
    if isinstance(value, dict):
        return ["dict", [[_exact(key), _exact(item)] for key, item in value.items()]]
    if isinstance(value, (tuple, list)):
        return [type(value).__name__, [_exact(item) for item in value]]
    if type(value) is float:
        return ["float64", struct.pack("!d", value).hex()]
    if value is None or type(value) in (int, str, bool):
        return [type(value).__name__, value]
    raise ParityError(f"Unsupported JSON value type: {type(value).__name__}")


def _canonical_mapping_order(value: Any) -> Any:
    """Canonical native identity schemas sort mapping keys, never list values."""
    if isinstance(value, dict):
        return {key: _canonical_mapping_order(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_mapping_order(item) for item in value]
    return value


def _pointer(parts: tuple[str, ...]) -> str:
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def _pointer_matches(pattern: str, parts: tuple[str, ...]) -> bool:
    tokens = pattern.removeprefix("/").split("/")
    wanted = [token.replace("~1", "/").replace("~0", "~") for token in tokens]
    return len(wanted) == len(parts) and all(a == "*" or a == b for a, b in zip(wanted, parts))


@dataclass
class Archive:
    root: Path
    origin_root: Path | None = None
    proofs: list[dict] = field(default_factory=list)
    normalizations: list[dict] = field(default_factory=list)
    hashes: dict[Path, str] = field(default_factory=dict)
    grids: dict[tuple[str, float], dict] = field(default_factory=dict)
    runner_artifacts: dict[str, Any] = field(default_factory=dict)
    verified_runner_artifacts: set[str] = field(default_factory=set)
    execution_source_root: Path | None = None
    fingerprint_payloads: dict[str, list[dict]] = field(default_factory=dict)
    span_plan_references: list[tuple[str, str, dict]] = field(default_factory=list)
    condition_repair_references: list[tuple[str, str, str, str, dict]] = field(default_factory=list)
    condition_repair_full_provenances: list[tuple[str, str, str, dict]] = field(default_factory=list)
    condition_repair_persisted_provenances: list[tuple[str, str, str, dict, dict]] = field(default_factory=list)
    condition_recording_global_bads: dict[str, list[str]] = field(default_factory=dict)
    condition_project_manifest: dict | None = None
    condition_artifact_recordings: dict[Path, str] | None = None
    identity_recipes: dict[str, list[dict]] = field(default_factory=dict)
    unverified_runtime_bindings: list[dict] = field(default_factory=list)

    def sha(self, path: Path) -> str:
        path = path.resolve()
        if path not in self.hashes:
            self.hashes[path] = _sha(path)
        return self.hashes[path]

    def resolve_binding(self, name: str, owner: Path, *, project_relative=False) -> Path:
        path = Path(name)
        if path.is_absolute():
            if self.origin_root is not None and path.is_relative_to(self.origin_root):
                return self.root / path.relative_to(self.origin_root)
            return path
        return (self.root if project_relative else owner.parent) / path


def _decode_audit_scalars(value: Any) -> Any:
    """Restore the runner's lossless float representation for recipe checks."""
    if isinstance(value, dict):
        if set(value) == {"float64_bits", "display"}:
            bits = value["float64_bits"]
            _require(isinstance(bits, str) and re.fullmatch(r"[0-9a-f]{16}", bits) is not None,
                     "Malformed runner float64 bits")
            decoded = struct.unpack("!d", bytes.fromhex(bits))[0]
            _require(value["display"] == repr(decoded), "Runner float display does not match its bits")
            return decoded
        return {key: _decode_audit_scalars(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode_audit_scalars(item) for item in value]
    return value


def _verify_compact_observer_receipt(value: dict, owner: Path, archive: Archive) -> dict:
    """Validate every compact fact against its complete, retained native proof."""
    value = _decode_audit_scalars(value)
    expected_owner = archive.root / "benchmark_evidence" / "telemetry_core_receipt.json"
    _require(owner.resolve() == expected_owner.resolve(), "Compact telemetry appears outside its characterized observer path")
    proof = value.get("observer_full_receipt_proof")
    _require(isinstance(proof, dict) and set(proof) == {"path", "size_bytes", "sha256"}
             and isinstance(proof["path"], str) and type(proof["size_bytes"]) is int and proof["size_bytes"] >= 0
             and isinstance(proof["sha256"], str) and HEX64.fullmatch(proof["sha256"]) is not None,
             "Malformed compact full-receipt proof binding")
    full_path = archive.root / "benchmark_evidence" / "run_receipt.json"
    bound = archive.resolve_binding(proof["path"], owner).resolve()
    _require(full_path.is_file() and not full_path.is_symlink() and full_path.resolve().is_relative_to(archive.root)
             and bound == full_path.resolve(), "Compact receipt must bind its sibling complete native proof")
    _require(full_path.stat().st_size == proof["size_bytes"] and archive.sha(full_path) == proof["sha256"],
             "Compact full-receipt checksum/size mismatch")
    full = _decode_audit_scalars(_json_load(full_path))
    _require(isinstance(full, dict) and full.get("version") == "pipeline_bitwise_backend_runner_v1",
             "Compact telemetry does not bind the characterized complete runner schema")
    fact_names = {"version", "started_utc", "finished_utc", "native_runner_returned_utc", "source_root", "project_root",
                  "recordings", "profiling_diagnostic", "functional_seed", "ambient_workload_note", "requested_worker_policy",
                  "normal_pool_max_workers", "validated_params", "stage_seconds", "status", "error", "pause_reason",
                  "generated_storage_footprint", "initial_project_sha256", "final_project_sha256"}
    expected = {key: item for key, item in full.items() if key in fact_names}
    expected["version"] = "pipeline_bitwise_telemetry_receipt_v1"
    expected["observer_complete_receipt_version"] = full["version"]
    if "processing_result" in full:
        _require(isinstance(full["processing_result"], dict)
                 and isinstance(full["processing_result"].get("results"), list), "Malformed complete processing timing source")
        expected["processing_result"] = {"results": [
            {key: row[key] for key in ("file", "timings_ms", "export_timing_records") if key in row}
            for row in full["processing_result"]["results"]
        ]}
    expected["observer_full_receipt_proof"] = proof
    expected["observer_receipt_scope"] = "Compact native timing/settings/status/worker facts; scientific values remain in the SHA/size-bound complete run receipt."
    _require(set(value) == set(expected), "Compact telemetry facts are missing or contain uncharacterized fields")
    for key in expected:
        _require(_exact(value[key]) == _exact(expected[key]), f"Compact telemetry copied fact differs from full proof: {key}")
    archive.proofs.append({"kind": "complete_native_receipt_and_exact_compact_facts", "file": str(owner),
                           "artifact": str(full_path), "sha256": proof["sha256"], "size_bytes": proof["size_bytes"],
                           "copied_fact_names": sorted(set(expected) - {"observer_full_receipt_proof", "observer_receipt_scope"})})
    return full


def _verify_generated_storage_census(value: dict, archive: Archive) -> None:
    """Check observer occupancy claims against every retained generated file."""
    _require(isinstance(value, dict) and set(value) == {"file_count", "size_bytes", "by_project_top_level", "stat_errors", "scope"}
             and value["stat_errors"] == [] and type(value["file_count"]) is int and type(value["size_bytes"]) is int
             and isinstance(value["by_project_top_level"], dict)
             and all(isinstance(key, str) and isinstance(row, dict) and set(row) == {"file_count", "size_bytes"}
                     and type(row["file_count"]) is int and type(row["size_bytes"]) is int
                     for key, row in value["by_project_top_level"].items()), "Malformed/incomplete generated-storage observer census")
    groups = {}
    evidence = (archive.root / "benchmark_evidence").resolve()
    for path in sorted(archive.root.rglob("*")):
        if not path.is_file() or path.is_relative_to(evidence):
            continue
        _require(not path.is_symlink(), "Generated-storage census cannot contain symbolic links")
        bucket = groups.setdefault(path.relative_to(archive.root).parts[0], {"file_count": 0, "size_bytes": 0})
        bucket["file_count"] += 1
        bucket["size_bytes"] += path.stat().st_size
    expected = {"file_count": sum(row["file_count"] for row in groups.values()),
                "size_bytes": sum(row["size_bytes"] for row in groups.values()),
                "by_project_top_level": groups, "stat_errors": [],
                "scope": "Post-run file sizes beneath the isolated project root; benchmark observer evidence and symbolic links excluded. Raw input copies live outside this generated project root. This is final footprint, not peak allocated disk space."}
    _require(value == expected, "Generated-storage observer census differs from its actual files")


def _verify_raw_diagnostics_namespace(receipt: dict, archive: Archive) -> list[Path]:
    """Prove every optional display cache against complete native diagnostic data."""
    from Main_App.processing.preflight_qc_cache import PREFLIGHT_QC_CACHE_METHOD_DIRECTORY

    folder = archive.root / ".fpvs_processing" / "preflight_qc" / PREFLIGHT_QC_CACHE_METHOD_DIRECTORY / "raw_diagnostics"
    if not folder.exists():
        return []
    from Main_App.processing.preflight_qc_reuse import decode_evidence
    from Main_App.processing.qc_review_diagnostics_cache import _restore_mapping_order, _valid_report
    from Main_App.processing.preflight_qc_pruning import _slot, _digest, _stat_identity

    def canonical_key(value):
        # Native cache-key JSON sorts dictionaries; ordered occurrence lists and
        # every scalar type/float bit remain exact. Report order is not changed.
        if isinstance(value, dict):
            return {key: canonical_key(value[key]) for key in sorted(value)}
        if isinstance(value, list):
            return [canonical_key(item) for item in value]
        return value

    results, preflights = {}, {}
    for row in receipt.get("kurtosis_review", {}).get("results", []):
        identity = (row.get("recording_id"), str(Path(row["path"]).resolve()))
        _require(identity not in results, "Ambiguous native diagnostic recording identity")
        results[identity] = row
    for row in receipt.get("preflight", {}).get("results", []):
        identity = (row.get("recording_id"), str(Path(row["path"]).resolve()))
        _require(identity not in preflights, "Ambiguous native preflight recording identity")
        preflights[identity] = row
    verified, slot_entries = [], {}
    for path in sorted(folder.glob("*.json")):
        _require(HEX64.fullmatch(path.stem) is not None and not path.is_symlink(), "Uncharacterized raw diagnostic namespace file")
        envelope = _decode_audit_scalars(_json_load(path))
        _require(isinstance(envelope, dict) and set(envelope) == {"schema_version", "fingerprint", "key", "result", "result_sha256"}
                 and envelope["fingerprint"] == path.stem, "Malformed raw diagnostic cache declaration")
        _verify_bindings(envelope, path, archive)
        key = envelope["key"]
        file = key["file_identity"]
        identity = (file.get("recording_id"), str(Path(file["resolved_path"]).resolve()))
        _require(identity in results and identity in preflights, "Raw diagnostic cache lacks its native recording result")
        native = results[identity]
        source = native.get("source_identity")
        report = native.get("review_diagnostics")
        expected_source = {"path": file["resolved_path"], "size_bytes": file["size"], "sha256": file["content_sha256"]}
        _require(isinstance(report, dict) and _exact(source) == _exact(expected_source)
                 and _exact(report.get("source_identity")) == _exact(source),
                 "Raw diagnostic cache source identity differs from its native result")
        scope = key["settings"]["recording_scope"]
        _require(_exact(canonical_key(scope)) == _exact(canonical_key({"participant_id": native["participant_id"], "recording_id": native["recording_id"]})),
                 "Raw diagnostic cache recording scope differs from its native result")
        cache_result = envelope["result"]
        _require(isinstance(cache_result, dict) and set(cache_result) == {"report", "mapping_order"},
                 "Uncharacterized raw diagnostic result schema")
        cached = _restore_mapping_order(decode_evidence(cache_result["report"]), cache_result["mapping_order"])
        _require(_valid_report(cached), "Raw diagnostic cache report failed its native schema/fingerprint validation")
        core = {name: item for name, item in report.items() if name != "source_identity"}
        _require(_exact(cached) == _exact(core), "Raw diagnostic cache typed payload differs from native diagnostic evidence")
        plan = key["event_plan"]
        _require(_exact(canonical_key(key["settings"]["diagnostics"])) == _exact(canonical_key(report["settings"]))
                 and plan["diagnostic_channels"] == report["channels"]
                 and _exact(plan["sfreq"]) == _exact(report["sfreq"])
                 and plan["first_samp"] == report["source_first_samp"], "Raw diagnostic key differs from its native signal context")
        source_plan = preflights[identity]["condition_qc"]["scored_source_analysis_span_plan"]
        occurrences = [{"start_sample": span["source_coordinates"]["start_relative_sample"],
                        "stop_sample": span["source_coordinates"]["stop_relative_sample"],
                        "condition_label": span["condition_label"], "occurrence": span["repetition_index"],
                        "occurrence_key": span["occurrence_key"]} for span in source_plan["spans"]]
        _require(_exact(canonical_key(plan["occurrences"])) == _exact(canonical_key(occurrences))
                 and type(report["occurrence_count"]) is int and report["occurrence_count"] == len(occurrences),
                 "Raw diagnostic key occurrences differ from native analyzed spans")
        slot = _slot(key, "raw_diagnostics", PREFLIGHT_QC_CACHE_METHOD_DIRECTORY)
        _require(slot is not None, "Invalid native raw diagnostic cache coordination scope")
        slot_entries.setdefault(_digest(slot), {"schema_version": 1, "slot": slot, "entries": []})["entries"].append(
            {"name": path.name, "stat": _stat_identity(path)})
        verified.append(path)
        archive.proofs.append({"kind": "raw_diagnostic_cache_exact_native_payload", "file": str(path),
                               "recording_id": native["recording_id"], "native_receipt_pointer":
                               f"/kurtosis_review/results/{list(results).index(identity)}/review_diagnostics",
                               "source_identity": source, "typed_diagnostic_payload_sha256": hashlib.sha256(
                                   json.dumps(_exact(core), separators=(",", ":")).encode()).hexdigest(),
                               "attached_source_identity_removed_only_after_exact_binding": True})
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path in verified:
            continue
        _require(not path.is_symlink(), "Symbolic link in raw diagnostic cache coordination")
        relative = path.relative_to(folder).as_posix()
        if relative == ".publication.lock":
            _require(path.read_bytes() == b"0", "Uncharacterized raw diagnostic publication lock bytes")
        elif relative == ".slots/index-state.json":
            _require(_exact(canonical_key(_json_load(path))) == _exact(canonical_key({"schema_version": 1, "state": "complete"})), "Incomplete raw diagnostic cache index")
        elif path.parent == folder / ".slots" and path.suffix == ".json" and path.stem in slot_entries:
            declared = _json_load(path)
            expected = slot_entries[path.stem]
            _require(set(declared) == set(expected)
                     and _exact(canonical_key({**declared, "entries": sorted(declared["entries"], key=lambda row: row["name"])})) ==
                         _exact(canonical_key({**expected, "entries": sorted(expected["entries"], key=lambda row: row["name"])})),
                     "Raw diagnostic slot does not bind its exact retained cache generations")
        else:
            _require(False, f"Unexplained raw diagnostic namespace artifact: {relative}")
        verified.append(path)
        archive.proofs.append({"kind": "validated_raw_diagnostic_cache_coordination", "file": str(path), "sha256": archive.sha(path)})
    return verified


def _record_identity_recipe(archive: Archive, digest: str, payload: Any, recipe: str,
                            owner: Path, parts) -> None:
    """Retain a verified canonical preimage; never substitute an opaque hash."""
    candidates = [hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=ascii_mode,
                                           allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()
                  for ascii_mode in (False, True)]
    _require(digest in candidates, f"Stale {recipe}: {owner}:{_pointer(parts)}")
    record = {"recipe": recipe, "file": str(owner), "pointer": _pointer(parts),
              "canonical_payload": payload}
    records = archive.identity_recipes.setdefault(digest, [])
    if not any(item["recipe"] == recipe for item in records):
        records.append(record)
    archive.proofs.append({"kind": recipe, "file": str(owner), "pointer": _pointer(parts), "sha256": digest})


def _repair_recording_context(archive: Archive, owner: Path, ancestors, parts=()) -> tuple[str, dict]:
    """Resolve a native record or companion through the declared project ledger."""
    if archive.condition_project_manifest is None:
        archive.condition_project_manifest = _json_load(archive.root / "project.json")
    manifest = archive.condition_project_manifest
    recordings = manifest.get("recordings", {})
    sources = {str(Path(row["raw_file"]).resolve()): identity for identity, row in recordings.items()}
    _require(len(sources) == len(recordings), "Ambiguous declared condition-repair source mapping")
    audit_alias = None
    # Production finalize_preproc_audit receives file_path.name, whereas its
    # enclosing process result retains str(file_path). Bind only that exact
    # full-run audit branch; a basename is never an independent source alias.
    if (len(parts) == 5 and parts[:2] == ("processing_result", "results")
            and parts[3:] == ("audit", "condition_electrode_interpolation")
            and owner.resolve() == (archive.root / "benchmark_evidence" / "run_receipt.json").resolve()
            and parts[2].isdigit() and str(int(parts[2])) == parts[2]
            and ancestors):
        root = ancestors[0]
        processing = root.get("processing_result")
        rows = processing.get("results") if isinstance(processing, dict) else None
        index = int(parts[2])
        if isinstance(rows, list) and index < len(rows):
            parent = rows[index]
            audit = parent.get("audit") if isinstance(parent, dict) else None
            if isinstance(audit, dict) and any(row is audit for row in ancestors):
                _require(root.get("version") == "pipeline_bitwise_backend_runner_v1"
                         and any(row is parent for row in ancestors),
                         "Native audit basename lacks its exact enclosing result context")
                parent_file = parent.get("file")
                _require(isinstance(parent_file, str) and Path(parent_file).is_absolute()
                         and str(Path(parent_file).resolve()) in sources,
                         "Native audit basename parent source is not declared absolute")
                basename = audit.get("file")
                _require(isinstance(basename, str) and Path(basename).parts == (basename,)
                         and basename == Path(parent_file).name,
                         "Native audit basename differs from its same-parent source")
                audit_alias = (audit, basename, sources[str(Path(parent_file).resolve())])
                archive.proofs.append({"kind": "native_preproc_audit_basename_context", "file": str(owner),
                                       "pointer": _pointer(parts[:4]), "audit_basename": basename,
                                       "parent_source": parent_file, "recording_id": audit_alias[2]})
    identities = set()
    for row in reversed(ancestors):
        for name in ("recording_id", "processing_id"):
            identity = row.get(name)
            if isinstance(identity, str) and identity:
                _require(identity in recordings, "Condition-repair recording identity is not declared")
                identities.add(identity)
        signature, payload = row.get("source_signature"), row.get("payload")
        paths = [("file", row.get("file")), ("source_path", row.get("source_path")), ("raw_file", row.get("raw_file")),
                 ("source_signature.raw_file", signature.get("raw_file") if isinstance(signature, dict) else None),
                 ("payload.source_path", payload.get("source_path") if isinstance(payload, dict) else None)]
        for name, path in paths:
            if isinstance(path, str) and path:
                if audit_alias is not None and row is audit_alias[0] and name == "file" and path == audit_alias[1]:
                    identities.add(audit_alias[2])
                    continue
                resolved = str(Path(path).resolve())
                if resolved in sources:
                    identities.add(sources[resolved])
                elif Path(path).suffix.lower() == ".bdf":
                    _require(False, "Condition-repair source path is not declared")
    _require(len(identities) <= 1, "Condition-repair enclosing recording/source identities disagree")
    if identities:
        return next(iter(identities)), manifest
    if archive.condition_artifact_recordings is None:
        archive.condition_artifact_recordings = {}
        ledger = _json_load(archive.root / ".fpvs_processing" / "processing_ledger.json")
        for cell in ledger.get("recording_condition_outcomes", {}).get("cells", []):
            receipt = cell.get("export_receipt") or {}
            if not receipt or cell.get("processing_id") not in recordings:
                continue
            anchor = archive.resolve_binding(receipt["path"], archive.root / "project.json", project_relative=True).resolve()
            _require(anchor.is_file() and anchor.is_relative_to(archive.root), "Condition-repair artifact ledger path is invalid")
            declaration = _json_load(anchor)
            for path in [anchor, *(anchor.parent / declaration[name]["path"] for name in ("condition_companion", "spectral_companion")
                                   if declaration.get(name))]:
                path = path.resolve()
                previous = archive.condition_artifact_recordings.setdefault(path, cell["processing_id"])
                _require(previous == cell["processing_id"], "Ambiguous condition-repair companion recording")
    _require(owner.resolve() in archive.condition_artifact_recordings, f"Condition-repair proof lacks a native recording context: {owner}")
    return archive.condition_artifact_recordings[owner.resolve()], manifest


def _capture_production_hashes(module, function, **kwargs):
    """Observe a pure recipe's SHA preimage within this diagnostic process."""
    original = module.hashlib
    captured = []

    def sha256(payload=b""):
        result = original.sha256(payload)
        if payload:
            captured.append((result.hexdigest(), json.loads(payload.decode("utf-8"))))
        return result

    module.hashlib = SimpleNamespace(sha256=sha256)
    try:
        result = function(**kwargs)
    finally:
        module.hashlib = original
    return result, captured


def _verify_compact_frequency_qc_identities(project, owner: Path, archive: Archive, parts=()) -> None:
    """Recover the native empty-findings compact review's source/analysis hashes.

    A completed native review need not persist its full transient report. Its
    compact evidence retains the exact recipe arguments except ordered cohort
    scope, which must be independently bound to the same project's current
    registry, active selection and complete ordered source-workbook grid.
    This adds canonical preimages; it does not normalize or drop any hash.
    """
    from Main_App.io.result_manifest import read_result_manifest
    from Main_App.processing import frequency_domain_qc as qc
    from Main_App.projects.experimental_qc_settings import SummedBcaScreeningSettings

    _require(parts == () and owner.resolve() == (archive.root / "project.json").resolve(),
             "Compact frequency QC requires its exact native project owner")
    try:
        state = project["tools"]["frequency_domain_qc"]
        evidence = state["review_evidence"]
        _require(type(state.get("schema_version")) is int and state["schema_version"] == 4
                 and state.get("review_complete") is True and state.get("identity_scope") == "recording"
                 and state.get("method_version") == qc.REPEATED_FREQUENCY_DOMAIN_QC_METHOD_VERSION,
                 "Unsupported compact frequency QC state")
        _require(evidence.get("version") == qc.FREQUENCY_DOMAIN_QC_REVIEW_EVIDENCE_VERSION
                 and evidence.get("identity_scope") == "recording"
                 and evidence.get("screening_enabled") is True
                 and evidence.get("screening_status") == "performed"
                 and type(evidence.get("condition_specific_interpolation_enabled")) is bool,
                 "Unsupported compact frequency QC evidence")
        for name in ("ordinary_findings", "cohort_findings", "cohort_rows", "reconfirmation_findings",
                     "technical_integrity_failures", "unavailable_by_method", "technical_statuses"):
            _require(type(evidence.get(name)) is list and evidence[name] == [],
                     "Compact frequency QC recipe supports only native empty findings/statuses")
        for name in ("review_decisions", "manual_participant_exclusions", "manual_recording_exclusions"):
            _require(type(state.get(name)) is list and state[name] == [],
                     "Compact frequency QC recipe does not infer reviewed or excluded cohort scope")
        _require(all(isinstance(evidence.get(name), dict) for name in
                     ("finite_input_status", "frequency_protocol", "independent_qc_source", "provisional_harmonic_metadata",
                      "thresholds", "screening_settings")), "Compact frequency QC requires native mapping arguments")
        finite = evidence["finite_input_status"]
        _require(finite.get("method_version") == qc.FREQUENCY_DOMAIN_QC_INTEGRITY_METHOD_VERSION
                 and finite.get("status") == "complete"
                 and all(type(finite.get(name)) is int and finite[name] == 0 for name in
                         ("technical_integrity_failure_count", "unavailable_by_method_count")),
                 "Compact frequency QC integrity state is not the characterized complete native state")
        fingerprints = (evidence.get("source_fingerprint"), evidence.get("analysis_fingerprint"), finite.get("fingerprint"),
                        evidence.get("harmonic_selection_fingerprint"), evidence.get("frequency_protocol_fingerprint"),
                        evidence["frequency_protocol"].get("frequency_protocol_fingerprint"),
                        evidence["independent_qc_source"].get("fingerprint"))
        _require(all(type(item) is str and HEX64.fullmatch(item) for item in fingerprints)
                 and evidence["frequency_protocol_fingerprint"] == evidence["frequency_protocol"]["frequency_protocol_fingerprint"],
                 "Compact frequency QC identity arguments must be exact native SHA-256 declarations")
        metadata = project["tools"]["processing"]["harmonic_selection"]["active"]["selection_metadata"]
        subjects, conditions, assignments = (metadata[name] for name in
                                             ("selection_recordings", "selection_conditions", "recording_assignments"))
        recordings, participants, event_map = (project[name] for name in ("recordings", "participants", "event_map"))
        _require(isinstance(recordings, dict) and recordings and isinstance(participants, dict)
                 and isinstance(event_map, dict) and event_map,
                 "Compact frequency QC requires the actual native recording/condition registry")
        for rows in (subjects, conditions):
            _require(type(rows) is list and rows and all(type(item) is str and item for item in rows)
                     and len(set(item.casefold() for item in rows)) == len(rows),
                     "Compact frequency QC scope must contain unique ordered literal strings")
        _require(subjects == sorted(recordings, key=str.casefold) and conditions == list(event_map),
                 "Compact frequency QC scope differs from the current full registry/order")
        fields = ("participant_id", "group_id", "session_id", "source_id", "visit_index", "days_from_baseline")
        _require(type(assignments) is list and len(assignments) == len(subjects),
                 "Compact frequency QC assignment cohort is incomplete")
        assignment_map = {}
        for identity, row in zip(subjects, assignments):
            _require(isinstance(row, dict) and set(row) == {"recording_id", *fields},
                     "Uncharacterized compact frequency QC assignment schema")
            recording = recordings[identity]
            participant = participants[recording["participant_id"]]
            expected = {"recording_id": identity, "participant_id": recording["participant_id"],
                        "group_id": participant["group_id"],
                        **{name: recording.get(name) for name in fields if name not in {"participant_id", "group_id"}}}
            _require(_exact(_canonical_mapping_order(row)) == _exact(_canonical_mapping_order(expected))
                     and all(type(row[name]) is str and row[name] for name in
                             ("recording_id", "participant_id", "group_id", "session_id", "source_id"))
                     and (row["visit_index"] is None or type(row["visit_index"]) is int)
                     and (row["days_from_baseline"] is None or
                          (type(row["days_from_baseline"]) in (int, float) and math.isfinite(row["days_from_baseline"]))),
                     "Compact frequency QC assignment differs from its typed stable project identity")
            assignment_map[identity] = row
        workbooks = evidence["source_workbooks"]
        _require(type(workbooks) is list and len(workbooks) == len(subjects) * len(conditions),
                 "Compact frequency QC source grid is incomplete")
        workbook_fields = {"subject", "condition", "path", "size_bytes", "mtime_ns", "recording_id", *fields}
        canonical_sources = metadata["source_workbook_fingerprints"]
        _require(type(canonical_sources) is list and len(canonical_sources) == len(workbooks),
                 "Compact frequency QC lacks its full current canonical source grid")
        source_index = {}
        for source in canonical_sources:
            _require(isinstance(source, dict) and set(source) == workbook_fields | {"condition_companion", "spectral_companion"}
                     and type(source["subject"]) is str and type(source["condition"]) is str,
                     "Uncharacterized current canonical source-workbook schema")
            key = (source["subject"], source["condition"])
            _require(key not in source_index, "Duplicate current canonical source-workbook cell")
            source_index[key] = source
        _require(set(source_index) == {(identity, condition) for identity in subjects for condition in conditions},
                 "Current canonical source-workbook cells differ from compact QC scope")
        paths = set()
        for row, (identity, condition) in zip(workbooks, ((identity, condition) for identity in subjects for condition in conditions)):
            _require(isinstance(row, dict) and set(row) == workbook_fields
                     and row["subject"] == row["recording_id"] == identity and row["condition"] == condition
                     and _exact(_canonical_mapping_order({name: row[name] for name in fields}))
                         == _exact(_canonical_mapping_order({name: assignment_map[identity][name] for name in fields})),
                     "Compact frequency QC source grid/order/identity is not native")
            canonical = source_index[(identity, condition)]
            compared_fields = workbook_fields - {"path"}
            _require(_exact(_canonical_mapping_order({name: row[name] for name in compared_fields}))
                         == _exact(_canonical_mapping_order({name: canonical[name] for name in compared_fields})),
                     "Compact frequency QC source differs from the same current canonical recording/condition cell")
            name = row["path"]
            _require(type(name) is str and name and not Path(name).anchor and ".." not in Path(name).parts,
                     "Compact frequency QC source must be project relative")
            declared = archive.resolve_binding(name, owner, project_relative=True)
            _require(all(not path.is_symlink() for path in (declared, *declared.parents) if path.is_relative_to(archive.root)),
                     "Compact frequency QC source contains a symbolic-link alias")
            bound = declared.resolve()
            canonical_name = canonical["path"]
            _require(type(canonical_name) is str and canonical_name and not Path(canonical_name).anchor
                     and ".." not in Path(canonical_name).parts,
                     "Current canonical source must be project relative")
            canonical_declared = archive.resolve_binding(canonical_name, owner, project_relative=True)
            _require(all(not path.is_symlink() for path in (canonical_declared, *canonical_declared.parents)
                         if path.is_relative_to(archive.root)) and canonical_declared.resolve() == bound,
                     "Compact frequency QC source is cross-wired from its own canonical recording/condition cell")
            _require(bound.is_relative_to(archive.root) and bound.suffix.lower() == ".fpvs"
                     and bound.is_file() and not bound.is_symlink() and bound not in paths
                     and type(row["size_bytes"]) is int and row["size_bytes"] == bound.stat().st_size
                     and type(row["mtime_ns"]) is int and row["mtime_ns"] == bound.stat().st_mtime_ns,
                     "Compact frequency QC source does not bind its own native physical artifact")
            read_result_manifest(bound)
            paths.add(bound)
        thresholds = qc.FrequencyDomainQcThresholds(**evidence["thresholds"])
        settings = SummedBcaScreeningSettings.from_manifest(evidence["screening_settings"])
        _require(_exact(_canonical_mapping_order(thresholds.to_manifest()))
                     == _exact(_canonical_mapping_order(evidence["thresholds"]))
                 and _exact(_canonical_mapping_order(settings.to_manifest()))
                     == _exact(_canonical_mapping_order(evidence["screening_settings"]))
                 and _exact(_canonical_mapping_order(qc.FrequencyDomainQcThresholds.from_settings(settings).to_manifest()))
                     == _exact(_canonical_mapping_order(thresholds.to_manifest()))
                 and evidence["screening_policy_version"] == settings.policy_version
                 and settings.enabled is True,
                 "Compact frequency QC thresholds/settings are not native typed manifests")
        selected = evidence["selected_harmonics_hz"]
        _require(type(selected) is list and selected and all(type(item) is float and math.isfinite(item) and item > 0 for item in selected),
                 "Compact frequency QC harmonic inputs must retain their native floating values")
        source_payload = {"source_workbooks": workbooks,
                          "finite_input_fingerprint": evidence["finite_input_status"]["fingerprint"],
                          "harmonic_selection_fingerprint": evidence["harmonic_selection_fingerprint"],
                          "frequency_protocol_fingerprint": evidence["frequency_protocol"]["frequency_protocol_fingerprint"],
                          "independent_qc_source_fingerprint": evidence["independent_qc_source"]["fingerprint"]}
        source_digest, source_captured = _capture_production_hashes(qc, qc._hash_payload, payload=source_payload)
        _require(source_digest == evidence["source_fingerprint"] and len(source_captured) == 1
                 and source_captured[0][0] == source_digest,
                 "Compact frequency QC native source preimage checksum mismatch")
        analysis_digest, analysis_captured = _capture_production_hashes(
            qc, qc._analysis_fingerprint, project_root=archive.root, subjects=subjects, conditions=conditions,
            subject_data={}, selected_harmonics=selected, thresholds=thresholds, flags=evidence["ordinary_findings"],
            finite_input_fingerprint=evidence["finite_input_status"]["fingerprint"], recording_assignments=assignment_map,
            screening_settings=settings, provisional_metadata=evidence["provisional_harmonic_metadata"],
            source_workbooks=workbooks, source_fingerprint=source_digest, previous_review_evidence=None)
        _require(analysis_digest == evidence["analysis_fingerprint"] and len(analysis_captured) == 1
                 and analysis_captured[0][0] == analysis_digest,
                 "Compact frequency QC native analysis preimage checksum mismatch")
        pointer = ("tools", "frequency_domain_qc", "review_evidence")
        for digest, payload in source_captured:
            _record_identity_recipe(archive, digest, payload, "frequency_qc_source_recipe", owner, pointer)
        for digest, payload in analysis_captured:
            _record_identity_recipe(archive, digest, payload, "frequency_qc_analysis_recipe", owner, pointer)
        archive.proofs.append({"kind": "native_compact_frequency_qc_scope", "file": str(owner), "pointer": _pointer(pointer),
                               "recordings": len(subjects), "conditions": len(conditions), "native_sources": len(paths),
                               "ordered_registry_and_cartesian_scope_exact": True})
    except ParityError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ParityError(f"Malformed or unsupported compact frequency QC native context: {owner}") from exc


def _verify_additional_identities(value, owner, archive, parts, ancestors=()):
    """Validate persisted scientific identities with their production recipes."""
    if (parts == () and owner.name == "project.json"
            and isinstance(value.get("tools", {}).get("frequency_domain_qc"), dict)
            and value["tools"]["frequency_domain_qc"].get("review_complete") is True):
        state = value["tools"]["frequency_domain_qc"]
        evidence = state.get("review_evidence")
        # Preserve the pre-existing full-report route for participant reviews
        # and other review modes. This adapter only claims the characterized
        # compact repeated-recording domain; its direct checks remain strict.
        finite = evidence.get("finite_input_status") if isinstance(evidence, dict) else None
        sources = evidence.get("source_workbooks") if isinstance(evidence, dict) else None
        if (type(state.get("schema_version")) is int and state["schema_version"] == 4
                and state.get("identity_scope") == "recording"
                and state.get("method_version") == "experimental_summed_bca_recording_electrode_review_v5"
                and isinstance(evidence, dict) and evidence.get("version") == "frequency_qc_review_evidence_v1"
                and evidence.get("identity_scope") == "recording" and evidence.get("screening_enabled") is True
                and evidence.get("screening_status") == "performed"
                and all(type(state.get(name)) is list and state[name] == [] for name in
                        ("review_decisions", "manual_participant_exclusions", "manual_recording_exclusions"))
                and all(type(evidence.get(name)) is list and evidence[name] == [] for name in
                        ("ordinary_findings", "cohort_findings", "cohort_rows", "reconfirmation_findings",
                         "technical_integrity_failures", "unavailable_by_method", "technical_statuses"))
                and isinstance(finite, dict) and finite.get("method_version") == "selected_bca_finite_v1"
                and finite.get("status") == "complete"
                and all(type(finite.get(name)) is int and finite[name] == 0 for name in
                        ("technical_integrity_failure_count", "unavailable_by_method_count"))
                and type(sources) is list and sources
                and all(isinstance(row, dict) and type(row.get("path")) is str
                        and Path(row["path"]).suffix.lower() == ".fpvs" for row in sources)):
            _verify_compact_frequency_qc_identities(value, owner, archive, parts)
    if {"selection_fingerprint", "included_harmonics_hz", "harmonic_policy", "final_release_receipt_fingerprint"} <= value.keys():
        from Main_App.processing import canonical_harmonics

        digest, captured = _capture_production_hashes(
            canonical_harmonics, canonical_harmonics.compute_selection_fingerprint, metadata=value)
        _require(digest == value["selection_fingerprint"], f"Canonical harmonic selection fingerprint mismatch: {owner}")
        for actual, payload in captured:
            _record_identity_recipe(archive, actual, payload, "canonical_harmonic_selection_recipe", owner, parts)
    if {"source_workbooks", "cohort_state", "frequency_qc_state", "processing_export_state", "fingerprints"} <= value.keys():
        names = {"sources": "source_workbooks", "cohort": "cohort_state", "frequency_qc": "frequency_qc_state",
                 "processing_export": "processing_export_state"}
        for name, payload_name in names.items():
            _record_identity_recipe(archive, value["fingerprints"][name], value[payload_name],
                                    "fullfft_" + name + "_recipe", owner, (*parts, "fingerprints", name))
    version = value.get("version")
    if (isinstance(value.get("file"), str) and isinstance(value.get("audit"), dict)
            and isinstance(value.get("interpolated_channels"), list)
            and (value.get("condition_electrode_interpolation") or value["audit"].get("condition_electrode_interpolation"))):
        identity, _manifest = _repair_recording_context(archive, owner, (*ancestors, value), parts)
        _require(_exact(_canonical_mapping_order(value.get("geometry"))) == _exact(_canonical_mapping_order(value["audit"].get("geometry"))),
                 "Condition-repair result geometry differs from the same recording's native audit")
        previous = archive.condition_recording_global_bads.setdefault(identity, value["interpolated_channels"])
        _require(_exact(previous) == _exact(value["interpolated_channels"]), "Conflicting native recording-wide interpolated channels")
    if version == "condition_electrode_interpolation_v1" and "fingerprint" in value:
        from Main_App.processing.condition_electrode_interpolation import _fingerprint, validate_condition_interpolation_provenance

        identity, manifest = _repair_recording_context(archive, owner, ancestors, parts)

        if "requests" in value:
            _require(set(value) == {"version", "status", "fingerprint", "requests", "recording_wide_interpolated_channels",
                                    "analysis_span_fingerprint", "geometry_fingerprint", "retained_scalp_set_fingerprint", "spans"}
                     and value.get("status") == "completed", "Uncharacterized full condition-repair provenance schema")
            core = {name: item for name, item in value.items() if name != "fingerprint"}
            _require(_fingerprint(core) == value.get("fingerprint"), "Condition-repair full provenance fingerprint mismatch")
            contexts = [candidate for row in reversed(ancestors) for candidate in (row, row.get("audit")) if isinstance(candidate, dict)]
            context = next((row for row in contexts if isinstance(row.get("geometry"), dict)
                            and isinstance(row.get("realized_analysis_span_plan"), dict)), None)
            if context is None:
                _require(owner.resolve() == (archive.root / ".fpvs_processing" / "processing_ledger.json").resolve()
                         and parts == ("entries", identity, "condition_electrode_interpolation"),
                         "Full condition-repair provenance lacks its same-recording geometry/span context")
                parent = next((row for row in contexts if isinstance(row.get("geometry"), dict)
                               and isinstance(row.get("interpolated_channels"), list)), None)
                _require(parent is not None and _exact(parent["interpolated_channels"]) == _exact(value["recording_wide_interpolated_channels"]),
                         "Persisted condition-repair ledger global bads are not bound")
                previous = archive.condition_recording_global_bads.setdefault(identity, parent["interpolated_channels"])
                _require(_exact(previous) == _exact(parent["interpolated_channels"]), "Conflicting persisted recording-wide interpolation evidence")
                archive.condition_repair_persisted_provenances.append((str(owner), _pointer(parts), identity, value, parent["geometry"]))
                _record_identity_recipe(archive, value["fingerprint"], core, "condition_repair_full_provenance_recipe", owner, parts)
                return
            from Main_App.processing.condition_interpolation_state import active_condition_requests, STATE_KEY
            from Main_App.processing.expected_processing_ledger import load_expected_recording_condition_plan

            requests = active_condition_requests(load_expected_recording_condition_plan(archive.root), identity,
                                                manifest.get("tools", {}).get(STATE_KEY, {}).get("requests", {}).get(identity, {}))
            try:
                from Main_App.io.eeg_geometry import biosemi64_geometry_identity
                from Main_App.processing.analysis_spans import validate_realized_target_analysis_span_plan

                geometry = context["geometry"]
                canonical_geometry = biosemi64_geometry_identity(electrode_mapping_profile=geometry["electrode_mapping_profile"],
                                                                 retained_channels=geometry["retained_scalp_channels"])
                _require(_exact(_canonical_mapping_order(geometry)) == _exact(_canonical_mapping_order(canonical_geometry)), "Condition-repair geometry is not canonical")
                target = context["realized_analysis_span_plan"]
                grid = target["target_grid"]
                validate_realized_target_analysis_span_plan(target, source_plan=context["source_analysis_span_plan"],
                                                           target_sfreq_hz=grid["sfreq_hz"], target_n_times=grid["n_times"],
                                                           target_first_samp=grid["first_samp"])
                validate_condition_interpolation_provenance(value, requests=requests,
                                                           analysis_span_plan=context["realized_analysis_span_plan"], geometry=context["geometry"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ParityError(f"Full condition-repair native context validation failed: {owner}:{_pointer(parts)}") from exc
            if isinstance(context.get("interpolated_channels"), list):
                _require(_exact(value["recording_wide_interpolated_channels"]) == _exact(context["interpolated_channels"]),
                         "Condition-repair global bads differ from the same recording's native audit")
                archive.condition_recording_global_bads.setdefault(identity, context["interpolated_channels"])
            archive.condition_repair_full_provenances.append((str(owner), _pointer(parts), identity, value))
            _record_identity_recipe(archive, value["fingerprint"], core, "condition_repair_full_provenance_recipe", owner, parts)
        else:
            _require(set(value) == {"version", "status", "fingerprint", "requested_channels", "recording_wide_interpolated_channels",
                                    "interpolated_channels", "analysis_span_fingerprint", "spans"},
                     "Uncharacterized compact condition-repair provenance schema")
            condition = next((row["condition_label"] for row in reversed(ancestors) if isinstance(row.get("condition_label"), str)), None)
            _require(condition is not None, "Compact condition repair lacks its enclosing native condition label")
            archive.condition_repair_references.append((str(owner), _pointer(parts), identity, condition, value))
    if parts == () and owner.name == "project.json":
        from Main_App.processing import condition_interpolation_state as repairs

        repair_state = value.get("tools", {}).get(repairs.STATE_KEY)
        if repair_state is not None:
            _require(repair_state.get("version") == repairs.STATE_VERSION and not repair_state.get("pending"),
                     "Completed archive contains invalid or pending condition-repair state")
            current_identity, captured = _capture_production_hashes(repairs, repairs.project_processing_identity, project_root=archive.root)
            for actual, payload in captured:
                _record_identity_recipe(archive, actual, payload, "condition_repair_project_processing_recipe", owner, parts)
            for identity, requests in repair_state.get("requests", {}).items():
                completion = repair_state.get("completed", {}).get(identity)
                _require(isinstance(completion, dict) and repairs.completion_is_current(archive.root, identity, repair_state),
                         f"Condition-repair completion does not bind its actual current outputs: {identity}")
                _require(completion["project_processing_identity"] == current_identity, "Condition-repair project-processing identity mismatch")
                from Main_App.io.condition_data import condition_companion_identity
                from Main_App.io.spectral_data import spectral_companion_identity
                from Main_App.processing.expected_processing_ledger import load_expected_recording_condition_plan

                expected = load_expected_recording_condition_plan(archive.root)
                active = repairs.active_condition_requests(expected, identity, requests)
                ledger = _json_load(archive.root / ".fpvs_processing" / "processing_ledger.json")
                receipts = [cell["export_receipt"] for cell in ledger.get("recording_condition_outcomes", {}).get("cells", [])
                            if cell.get("processing_id") == identity and cell.get("condition_label") in active and cell.get("export_receipt")]
                _require(len(receipts) == len(active) and {row["condition_label"] for row in receipts} == set(active)
                         and all(row.get("status") == "written" for row in receipts),
                         "Condition-repair completion does not cover exactly its active native requested cells")
                output_identities = []
                for row in receipts:
                    path = archive.resolve_binding(row["path"], owner, project_relative=True).resolve()
                    _require(path.is_file() and path.is_relative_to(archive.root), "Condition-repair completion output escapes its archive")
                    output_identities.append({"artifact": repairs.artifact_identity(path, project_root=archive.root),
                                              "condition_companion": condition_companion_identity(path),
                                              "spectral_companion": spectral_companion_identity(path)})
                _require(isinstance(completion.get("outputs"), list)
                         and _exact(_canonical_mapping_order(sorted(completion["outputs"], key=lambda row: row["artifact"]["path"]))) ==
                             _exact(_canonical_mapping_order(sorted(output_identities, key=lambda row: row["artifact"]["path"]))),
                         "Condition-repair completion outputs differ from their same-recording reconciled receipts")
                _record_identity_recipe(archive, completion["request_fingerprint"], requests, "condition_repair_request_recipe", owner,
                                        (*parts, "tools", repairs.STATE_KEY, "completed", identity, "request_fingerprint"))
    if version == "frequency_qc_review_decision_v2":
        payload = {key: item for key, item in value.items() if key not in {"decision_fingerprint", "reviewed_at"}}
        _record_identity_recipe(archive, value["decision_fingerprint"], payload,
                                "frequency_qc_review_decision_recipe", owner, parts)
    if version == "frequency_qc_review_evidence_v1":
        payload = {key: item for key, item in value.items() if key != "evidence_fingerprint"}
        _record_identity_recipe(archive, value["evidence_fingerprint"], payload,
                                "frequency_qc_review_evidence_recipe", owner, parts)
    if "finding_fingerprint" in value and "finding_type" in value:
        from Main_App.processing import frequency_domain_qc as qc

        digest, captured = _capture_production_hashes(qc, qc._frequency_qc_finding_fingerprint, finding=value)
        _require(digest == value["finding_fingerprint"], f"Frequency QC finding fingerprint mismatch: {owner}")
        for actual, payload in captured:
            _record_identity_recipe(archive, actual, payload, "frequency_qc_finding_recipe", owner, parts)
    if {"independent_qc", "independent_qc_status", "independent_qc_fingerprint"} <= value.keys():
        payload = {"status": value["independent_qc_status"], "evidence": value["independent_qc"]}
        if value["independent_qc_status"] != "available":
            payload["source_status"] = value["independent_qc_source_status"]
        _record_identity_recipe(archive, value["independent_qc_fingerprint"], payload,
                                "frequency_qc_independent_finding_recipe", owner, parts)
    if value.get("method_version") in {
            "experimental_summed_bca_electrode_review_v5", "experimental_summed_bca_recording_electrode_review_v5"} and "subjects" in value:
        from Main_App.processing import frequency_domain_qc as qc
        from Main_App.projects.experimental_qc_settings import SummedBcaScreeningSettings

        assignments = ({row["recording_id"]: row for row in value["recording_assignments"]}
                       if value.get("identity_scope") == "recording" else None)
        source_payload = {
            "source_workbooks": value["source_workbooks"],
            "finite_input_fingerprint": value["finite_input_status"]["fingerprint"],
            "harmonic_selection_fingerprint": value["harmonic_selection_fingerprint"],
            "frequency_protocol_fingerprint": value["frequency_protocol"]["frequency_protocol_fingerprint"],
            "independent_qc_source_fingerprint": value["independent_qc_source"]["fingerprint"],
        }
        _record_identity_recipe(archive, value["source_fingerprint"], source_payload,
                                "frequency_qc_source_recipe", owner, parts)
        digest, captured = _capture_production_hashes(
            qc, qc._analysis_fingerprint, project_root=archive.root,
            subjects=(value["recordings"] if assignments is not None else value["subjects"]),
            conditions=value["conditions"], subject_data={}, selected_harmonics=value["selected_harmonics_hz"],
            thresholds=qc.FrequencyDomainQcThresholds(**value["thresholds"]), flags=value["flags"],
            finite_input_fingerprint=value["finite_input_status"]["fingerprint"], recording_assignments=assignments,
            screening_settings=SummedBcaScreeningSettings.from_manifest(value["screening_settings"]),
            provisional_metadata=value["provisional_harmonic_metadata"], source_workbooks=value["source_workbooks"],
            source_fingerprint=value["source_fingerprint"])
        _require(digest == value["analysis_fingerprint"], f"Frequency QC analysis fingerprint mismatch: {owner}:{_pointer(parts)}")
        for actual, payload in captured:
            _record_identity_recipe(archive, actual, payload, "frequency_qc_analysis_recipe", owner, parts)
        digest, captured = _capture_production_hashes(
            qc, qc._decision_fingerprint, analysis_fingerprint=value["analysis_fingerprint"],
            auto_electrodes=(), auto_participants=(), manual_participants=value["manual_participant_exclusions"],
            auto_recording_electrodes=(() if assignments is not None else None),
            auto_recordings=(() if assignments is not None else None),
            manual_recordings=(value["manual_recording_exclusions"] if assignments is not None else None),
            review_decisions=value["active_review_decisions"], identity_scope=value["identity_scope"])
        _require(digest == value["current_decision_fingerprint"], f"Frequency QC current decision fingerprint mismatch: {owner}")
        for actual, payload in captured:
            _record_identity_recipe(archive, actual, payload, "frequency_qc_current_decision_recipe", owner, parts)
    if (value.get("schema_version") == 4 and "review_complete" in value and "review_evidence" in value
            and value.get("review_complete") is True):
        from Main_App.processing import frequency_domain_qc as qc

        evidence = value["review_evidence"]
        repeated = value.get("identity_scope") == "recording"
        digest, captured = _capture_production_hashes(
            qc, qc._decision_fingerprint, analysis_fingerprint=evidence["analysis_fingerprint"],
            auto_electrodes=(), auto_participants=(), manual_participants=value["manual_participant_exclusions"],
            auto_recording_electrodes=(() if repeated else None), auto_recordings=(() if repeated else None),
            manual_recordings=(value["manual_recording_exclusions"] if repeated else None),
            review_decisions=value["review_decisions"], identity_scope=value["identity_scope"])
        _require(digest == value["last_review"]["decision_fingerprint"], f"Frequency QC decision aggregate mismatch: {owner}")
        for actual, payload in captured:
            _record_identity_recipe(archive, actual, payload, "frequency_qc_decision_aggregate_recipe", owner, parts)
    if parts == () and owner.name == "project.json" and "harmonic_selection" in value.get("tools", {}).get("processing", {}):
        from Main_App.processing import canonical_harmonics, harmonic_selection_qc as selection
        from Main_App.processing.recording_condition_outcomes import RecordingConditionOutcomeLedger
        from Main_App.processing.roi_coverage import RoiCoverageLedger, FinalReleaseReceipt

        active = value["tools"]["processing"]["harmonic_selection"]["active"]
        metadata = active["selection_metadata"]
        sources = metadata["source_workbook_fingerprints"]
        subject_data = {}
        for row in sources:
            subject_data.setdefault(row["subject"], {})[row["condition"]] = str(archive.root / row["path"])
        assignments = {row["recording_id"]: row for row in metadata.get("recording_assignments", [])}
        settings = selection._harmonic_selection_settings(SimpleNamespace(project_root=archive.root))
        inputs = SimpleNamespace(
            project_root=archive.root, subjects=tuple(metadata.get("selection_recordings", metadata["selection_subjects"])),
            conditions=tuple(metadata["selection_conditions"]), subject_data=subject_data, rois={}, settings=settings,
            base_frequency_hz=metadata["base_frequency_hz"], oddball_frequency_hz=metadata["oddball_frequency_hz"],
            max_frequency_hz=None, recording_assignments=assignments,
            declared_session_ids=tuple(metadata.get("declared_session_ids", ())),
            frequency_protocol_fingerprint=metadata["frequency_protocol_fingerprint"],
            spectral_eligibility_fingerprint=metadata["spectral_eligibility_fingerprint"],
            eligible_harmonic_orders=tuple(metadata["eligible_harmonic_orders"]))
        request = selection._processing_cache_request(inputs)
        ledger = _json_load(archive.root / ".fpvs_processing" / "processing_ledger.json")
        outcomes = RecordingConditionOutcomeLedger.from_payload(ledger["recording_condition_outcomes"])
        coverage = RoiCoverageLedger.from_payload(ledger["roi_coverage"]["final"])
        receipt = FinalReleaseReceipt.from_payload(ledger["final_release_readiness"])
        release = selection._final_release_metadata(outcomes, coverage, receipt)
        _require(all(metadata.get(name) == item for name, item in release.items()), "Saved selection release binding mismatch")
        original = selection._current_final_release_metadata
        selection._current_final_release_metadata = lambda _root: release
        try:
            digest, captured = _capture_production_hashes(
                canonical_harmonics, selection._processing_selection_input_fingerprint,
                inputs=inputs, cache_request=request)
        finally:
            selection._current_final_release_metadata = original
        _require(digest == active["input_fingerprint"], f"Processing selection input fingerprint mismatch: {owner}")
        for actual, payload in captured:
            _record_identity_recipe(archive, actual, payload, "processing_selection_input_recipe", owner, parts)
            upstream = payload["upstream_input_identity"]
            _record_identity_recipe(archive, upstream["project_processing_signature_hash"],
                                    upstream["project_processing_signature"],
                                    "project_processing_signature_recipe", owner, parts)


def _verify_grid(value: dict, owner: Path, archive: Archive, parts, ancestors) -> None:
    """Validate a grid summary against the production ordered-header recipe."""
    from Main_App.io import read_xlsx_sheet_header
    from Main_App.processing.full_fft_provenance import FULL_FFT_SHEET_NAME, _grid_identity

    frequency = next((item.get("oddball_frequency_hz") for item in reversed(ancestors)
                      if isinstance(item.get("oddball_frequency_hz"), (float, int))), None)
    if frequency is None:
        project = _json_load(archive.root / "project.json")
        frequency = project.get("analysis", {}).get("oddball_freq")
    _require(type(frequency) in (int, float) and math.isfinite(frequency) and frequency > 0,
             f"No declared oddball frequency for FullFFT grid: {owner}:{_pointer(parts)}")
    key = (value["fingerprint"], float(frequency))
    if key not in archive.grids:
        found = []
        for anchor in sorted(archive.root.rglob("*.fpvs")):
            declaration = _json_load(anchor)
            if FULL_FFT_SHEET_NAME not in declaration.get("sheet_names", []):
                continue
            grid = _grid_identity(read_xlsx_sheet_header(anchor, sheet_name=FULL_FFT_SHEET_NAME),
                                  oddball_frequency_hz=float(frequency))
            identity = {"fingerprint": grid.fingerprint,
                        "frequency_resolution_hz": grid.frequency_resolution_hz,
                        "upper_frequency_hz": grid.upper_frequency_hz,
                        "frequency_column_count": grid.frequency_column_count}
            if identity["fingerprint"] == value["fingerprint"]:
                found.append((anchor, identity))
        _require(bool(found), f"FullFFT grid fingerprint has no matching native header: {owner}:{_pointer(parts)}")
        _require(all(_exact({name: identity[name] for name in value}) == _exact(value) for _, identity in found),
                 f"FullFFT grid summary differs from its native header: {owner}:{_pointer(parts)}")
        archive.grids[key] = {"kind": "fullfft_ordered_header_fingerprint", "file": str(owner),
                              "pointer": _pointer(parts), "sha256": value["fingerprint"],
                              "native_headers": [str(anchor) for anchor, _ in found]}
    archive.proofs.append(archive.grids[key])


def _fingerprint_core(value: dict, ancestors) -> tuple[dict | None, str]:
    """Choose a documented recipe; summaries/references are not re-hashed."""
    core = {key: item for key, item in value.items() if key != "fingerprint"}
    if set(core) == {"fingerprint_version"} or set(value) == {
            "states", "fingerprint", "condition_labels", "choice", "geometry_identity"}:
        return None, "preserved_external_fingerprint"
    if value.get("version") == "analysis_span_plan_v2_v3_stim_alignment" and "spans" not in value:
        return None, "preserved_external_fingerprint"
    if set(value) == {"canonical_payload", "fingerprint"}:
        _require(isinstance(value["canonical_payload"], dict), "Malformed canonical protocol payload reference")
        return value["canonical_payload"], "canonical_protocol_fingerprint"
    validator = None
    if {"protocol_payload", "recordings", "event_map", "processing_fingerprint_version"} <= value.keys():
        from Main_App.processing.expected_processing_ledger import ExpectedRecordingConditionPlan

        validator = ExpectedRecordingConditionPlan.from_payload
    elif {"raw_file_identity", "marker_plan_identity", "cells", "raw_file_fingerprint"} <= value.keys():
        from Main_App.processing.expected_processing_ledger import ExpectedRecordingPlan

        validator = ExpectedRecordingPlan.from_payload
    elif {"cell_id", "planned_workbook_requirement", "occurrences"} <= value.keys():
        from Main_App.processing.expected_processing_ledger import ExpectedRecordingConditionCell

        validator = ExpectedRecordingConditionCell.from_payload
    elif {"source_sampling_rate_hz", "planned_disposition", "decision_payload"} <= value.keys():
        from Main_App.processing.expected_processing_ledger import ExpectedOccurrencePlan

        validator = ExpectedOccurrencePlan.from_payload
    elif {"expected_plan_run_id", "status_counts", "cells"} <= value.keys():
        from Main_App.processing.recording_condition_outcomes import RecordingConditionOutcomeLedger

        validator = RecordingConditionOutcomeLedger.from_payload
    elif {"cell_id", "expected_cell_fingerprint", "contributor_count", "reason_codes"} <= value.keys():
        from Main_App.processing.recording_condition_outcomes import RecordingConditionCellOutcome

        validator = RecordingConditionCellOutcome.from_payload
    elif {"roi_snapshot", "outcome_ledger_fingerprint", "review_complete", "cells"} <= value.keys():
        from Main_App.processing.roi_coverage import RoiCoverageLedger

        validator = RoiCoverageLedger.from_payload
    elif {"review_threshold_percent", "eligible_scalp_channels", "numerator", "denominator"} <= value.keys():
        from Main_App.processing.interpolation_burden import normalize_interpolation_burden

        validator = normalize_interpolation_burden
    if validator is not None:
        parsed = validator(value)
        _require(parsed.fingerprint == value["fingerprint"], "Production schema fingerprint mismatch")
        if callable(getattr(parsed, "canonical_payload", None)):
            return parsed.canonical_payload(), "production_schema_fingerprint"
        return None, "production_schema_fingerprint"
    if "raw_marker_samples" in value and "expected_interval_samples" in value:
        parent = next((item for item in reversed(ancestors) if "protocol_fingerprint" in item
                       and "method_version" in item and "occurrences" in item), None)
        _require(parent is not None, "Marker occurrence fingerprint needs its marker-plan context")
        names = ("condition_code", "repetition_index", "onset_sample", "block_stop_sample",
                 "raw_marker_samples", "retained_marker_samples", "duplicate_groups", "intervals",
                 "expected_analyzed_samples", "proposed_start_sample", "proposed_stop_sample",
                 "contiguous_candidate_spans", "review_reasons")
        return {"method_version": parent["method_version"], "protocol_fingerprint": parent["protocol_fingerprint"],
                "marker_code": value["oddball_marker_code"], **{name: value[name] for name in names}}, "marker_occurrence_fingerprint"
    if value.get("version") == "mne_amplitude_review_shadow_v1":
        # Scanner attaches the source identity after diagnostic generation.
        core.pop("source_identity", None)
        return core, "review_diagnostics_fingerprint"
    if value.get("version") == "condition_electrode_interpolation_v1" and "requests" in value:
        return core, "condition_repair_full_provenance_fingerprint"
    # These canonical-payload schemas are directly represented in the exports.
    known = (value.get("version") in {"analysis_span_plan_v2_v3_stim_alignment",
                                      "recording_condition_export_receipt_v1",
                                      "recording_condition_outcome_ledger_v1",
                                      "frequency_qc_independent_evidence_v1",
                                      "qc20_final_release_v1",
                                      "parity_selftest_canonical_v1"}
             or value.get("method_version") in {"marker_integrity_v3_review_receipt",
                                                 "eeglab_inspired_trimmed_kurtosis_v1",
                                                 "spectral_output_integrity_v1"}
             or {"finite_channel_count", "trim_count_per_tail", "included_raw_kurtosis"} <= value.keys()
             or {"channel", "raw_kurtosis", "signed_z", "evidence_context_fingerprint"} <= value.keys()
             or {"condition_code", "repetition_index", "disposition", "decision_payload"} <= value.keys()
             or {"source_coordinates", "occurrence_key", "approved_span_fingerprint"} <= value.keys()
             or {"snapshot_version", "rois", "canonical_scalp_set_fingerprint"} <= value.keys()
             or {"source_evidence", "roi_memberships", "whole_scalp_normalization"} <= value.keys()
             or {"retained_scalp_identity", "required_columns", "validation_stage"} <= value.keys()
             or {"retained_scalp_channels", "retained_scalp_set_fingerprint", "coordinate_fingerprint"} <= value.keys()
             or {"roi_name", "used_channels", "configured_count", "reason_codes"} <= value.keys()
             or {"used_channels", "expected_count", "interpolated_count", "reason_codes"} <= value.keys())
    return (core, "canonical_json_fingerprint") if known else (None, "preserved_external_fingerprint")


def _verify_native_harmonic_input_history(value, owner: Path, archive: Archive, parts, *, record=True) -> bool:
    """Preserve a whole actual-input snapshot; it claims no current outputs."""
    if not (len(parts) == 5 and parts[:4] == ("tools", "processing", "harmonic_selection", "history")):
        return False
    if owner.resolve() != (archive.root / "project.json").resolve():
        return False
    _require(isinstance(parts[4], str) and parts[4].isdigit() and str(int(parts[4])) == parts[4],
             "Noncanonical native harmonic history index")
    receipt_path = archive.root / "benchmark_evidence" / "run_receipt.json"
    _require(receipt_path.is_file(), "Native harmonic history lacks its full native receipt")
    receipt = _json_load(receipt_path)
    _require(receipt.get("version") == "pipeline_bitwise_backend_runner_v1"
             and receipt.get("status") == "pipeline_complete", "Unsupported native harmonic history receipt")
    preimage = receipt.get("initial_project_manifest_preimage")
    _require(isinstance(preimage, dict) and set(preimage) == {"path", "size_bytes", "sha256"}
             and isinstance(preimage["path"], str) and Path(preimage["path"]).is_absolute()
             and type(preimage["size_bytes"]) is int and preimage["size_bytes"] > 0
             and isinstance(preimage["sha256"], str) and HEX64.fullmatch(preimage["sha256"]) is not None,
             "Malformed native harmonic history initial preimage")
    initial_path = archive.resolve_binding(preimage["path"], receipt_path).resolve()
    _require(initial_path == (archive.root / "benchmark_evidence" / "project_before_runner.bin").resolve()
             and initial_path.is_file(), "Native harmonic history initial owner differs")
    content = initial_path.read_bytes()
    _require(len(content) == preimage["size_bytes"]
             and hashlib.sha256(content).hexdigest() == preimage["sha256"] == receipt.get("initial_project_sha256"),
             "Native harmonic history initial byte/hash binding differs")
    initial = _decode_audit_scalars(_json_load(initial_path, content.decode("utf-8")))
    final = _decode_audit_scalars(_json_load(owner))
    def section(document):
        result = document.get("tools", {}).get("processing", {}).get("harmonic_selection")
        _require(isinstance(result, dict) and set(result) == {"active", "history", "schema_version"}
                 and type(result["schema_version"]) is int and result["schema_version"] == 2
                 and isinstance(result["history"], list), "Unsupported native harmonic history section")
        return result
    before, after = section(initial), section(final)
    index = int(parts[4])
    _require(index < len(after["history"]), "Native harmonic history index is absent")
    if index < len(before["history"]):
        expected = before["history"][index]
        original_pointer = (*parts[:4], str(index))
    elif index == len(before["history"]) and isinstance(before["active"], dict):
        expected = before["active"]
        original_pointer = (*parts[:3], "active")
    else:
        return False  # Newly generated history retains strict output ownership.
    _require(isinstance(expected, dict)
             and set(expected) == {"harmonic_selection_profile", "harmonic_selection_profile_version", "input_fingerprint",
                                   "saved_at", "schema_version", "selection_fingerprint", "selection_metadata"}
             and isinstance(expected["harmonic_selection_profile"], str) and expected["harmonic_selection_profile"]
             and type(expected["harmonic_selection_profile_version"]) is str and expected["harmonic_selection_profile_version"] == "1.0"
             and all(isinstance(expected[key], str) and HEX64.fullmatch(expected[key]) is not None
                     for key in ("input_fingerprint", "selection_fingerprint"))
             and isinstance(expected["saved_at"], str) and isinstance(expected["selection_metadata"], dict)
             and type(expected.get("schema_version")) is int
             and expected["schema_version"] == 2 and isinstance(value, dict)
             and _exact(value) == _exact(after["history"][index]) == _exact(expected),
             "Native harmonic history differs from its entire actual input snapshot")
    if record:
        archive.proofs.append({"kind": "literal_native_harmonic_input_history", "file": str(owner),
                               "pointer": _pointer(parts), "initial_preimage_sha256": preimage["sha256"],
                               "initial_pointer": _pointer(original_pointer), "current_output_authority": False,
                               "all_input_fields_compared_literally": True})
    return True


def _verify_bindings(value: Any, owner: Path, archive: Archive, parts=(), ancestors=(), binding_owner=None) -> None:
    """Validate self-contained hashes; preserve opaque external references."""
    if isinstance(value, dict):
        if _verify_native_harmonic_input_history(value, owner, archive, parts):
            return
        if (parts == () and owner.resolve() == (archive.root / "benchmark_evidence" / "project_before_downstream.json").resolve()
                and (archive.root / "benchmark_evidence" / "downstream_receipt.json").is_file()):
            # These bytes are the actual input history before native repair
            # adoption, not a declaration that prior GUI outputs remain current.
            downstream = _json_load(archive.root / "benchmark_evidence" / "downstream_receipt.json")
            _require(downstream.get("project_manifest_before_sha256") == archive.sha(owner),
                     "Historical pre-downstream input manifest is not bound to its native receipt")
            archive.proofs.append({"kind": "native_historical_input_manifest_preimage", "file": str(owner), "sha256": archive.sha(owner),
                                   "current_output_authority": False, "all_input_fields_compared_in_typed_metadata_proof": True})
            return
        if parts == () and owner.resolve() == (archive.root / "benchmark_evidence" / "telemetry_core_receipt.json").resolve():
            _verify_compact_observer_receipt(value, owner, archive)
        elif value.get("version") == "pipeline_bitwise_telemetry_receipt_v1":
            _require(False, "Compact telemetry receipt must be its own characterized observer document")
        if set(value) == {"mapping"} and isinstance(value["mapping"], dict):
            from Main_App.processing.preflight_qc_reuse import decode_evidence

            decoded = decode_evidence(value)
            _verify_bindings(decoded, owner, archive, (*parts, "decoded"), ancestors, binding_owner)
            return
        _verify_additional_identities(value, owner, archive, parts, ancestors)
        if set(value) == {"schema_version", "fingerprint", "key", "result", "result_sha256"}:
            from Main_App.processing.preflight_qc_cache import (
                PREFLIGHT_QC_CACHE_SCHEMA_VERSION, _canonical_json,
                build_preflight_qc_cache_fingerprint,
            )

            _require(value["schema_version"] == PREFLIGHT_QC_CACHE_SCHEMA_VERSION,
                     f"Unknown preflight cache envelope version: {owner}")
            _require(value["fingerprint"] == build_preflight_qc_cache_fingerprint(**value["key"]),
                     f"Preflight cache key checksum mismatch: {owner}")
            _require(value["result_sha256"] == hashlib.sha256(
                _canonical_json(value["result"]).encode("utf-8")).hexdigest(),
                f"Preflight cache result checksum mismatch: {owner}")
            _record_identity_recipe(archive, value["fingerprint"], value["key"],
                                    "preflight_cache_key_recipe", owner, (*parts, "fingerprint"))
            _record_identity_recipe(archive, value["result_sha256"], value["result"],
                                    "preflight_cache_result_recipe", owner, (*parts, "result_sha256"))
            archive.proofs.append({"kind": "preflight_key_and_result_checksum", "file": str(owner),
                                   "pointer": _pointer(parts), "sha256": value["fingerprint"],
                                   "result_sha256": value["result_sha256"]})
        if value.get("version") == "pipeline_bitwise_backend_runner_v1":
            if "final_project_sha256" in value:
                _require(value["final_project_sha256"] == archive.sha(archive.root / "project.json"),
                         "Runner final project-manifest binding mismatch")
            if "project_manifest_before_downstream_preimage" in value:
                preimage = value["project_manifest_before_downstream_preimage"]
                _require(preimage.get("sha256") == value.get("downstream", {}).get("project_manifest_before_sha256"),
                         "Runner pre-downstream project-manifest preimage binding mismatch")
            if "initial_project_manifest_preimage" in value:
                preimage = value["initial_project_manifest_preimage"]
                expected_path = archive.root / "benchmark_evidence" / "project_before_runner.bin"
                _require(preimage.get("sha256") == value.get("initial_project_sha256")
                         and archive.resolve_binding(preimage["path"], owner).resolve() == expected_path.resolve(),
                         "Runner initial project-manifest preimage binding mismatch")
            expected = value.get("expected_plan", {}).get("processing_fingerprint")
            actual = value.get("processing_plan", {}).get("fingerprint")
            _require(expected == actual and isinstance(actual, str), "Runner processing-plan identity binding mismatch")
            declared = value.get("generated_artifact_proof", {})
            _require(isinstance(declared, dict), "Malformed runner artifact inventory")
            for name, proof in declared.items():
                relative = Path(name)
                _require(not relative.is_absolute() and ".." not in relative.parts, "Runner artifact escapes its project")
                _require((archive.root / relative).is_file(), f"Runner-declared artifact missing: {name}")
                _require(name not in archive.runner_artifacts or archive.runner_artifacts[name] == proof,
                         f"Conflicting runner artifact declarations: {name}")
                archive.runner_artifacts[name] = proof
        if "project_manifest_after_sha256" in value:
            _require(value["project_manifest_after_sha256"] == archive.sha(archive.root / "project.json"),
                     "Downstream final project-manifest binding mismatch")
        if "project_manifest_before_sha256" in value:
            preimage = archive.root / "benchmark_evidence" / "project_before_downstream.json"
            if preimage.is_file():
                _require(value["project_manifest_before_sha256"] == archive.sha(preimage),
                         "Downstream pre-project-manifest preimage binding mismatch")
                archive.proofs.append({"kind": "downstream_before_project_preimage_binding", "file": str(owner),
                                       "pointer": _pointer(parts), "sha256": value["project_manifest_before_sha256"]})
            else:
                archive.unverified_runtime_bindings.append({"file": str(owner), "pointer": _pointer((*parts, "project_manifest_before_sha256")),
                                                           "sha256": value["project_manifest_before_sha256"],
                                                           "reason": "Original intermediate project-manifest bytes were not archived"})
        if "fingerprint" in value:
            digest = value["fingerprint"]
            _require(isinstance(digest, str) and HEX64.fullmatch(digest) is not None,
                     f"Malformed fingerprint: {owner}:{_pointer(parts)}")
            if set(value) == {"fingerprint", "frequency_resolution_hz", "upper_frequency_hz", "frequency_column_count"}:
                _verify_grid(value, owner, archive, parts, ancestors)
                archive.fingerprint_payloads.setdefault(digest, []).append(value)
            else:
                core, recipe = _fingerprint_core(value, ancestors)
                if core is not None:
                    possible = []
                    for ascii_mode in (False, True):
                        encoded = json.dumps(core, sort_keys=True, ensure_ascii=ascii_mode,
                                             allow_nan=False, separators=(",", ":")).encode("utf-8")
                        possible.append(hashlib.sha256(encoded).hexdigest())
                    _require(digest in possible, f"Stale {recipe}: {owner}:{_pointer(parts)}")
                archive.proofs.append({"kind": recipe, "file": str(owner),
                                       "pointer": _pointer(parts), "sha256": digest})
                if core is not None or recipe == "production_schema_fingerprint":
                    archive.fingerprint_payloads.setdefault(digest, []).append(value)
                    if core is not None:
                        _record_identity_recipe(archive, digest, core, recipe + "_preimage", owner, parts)
                elif value.get("version") == "analysis_span_plan_v2_v3_stim_alignment":
                    archive.span_plan_references.append((str(owner), _pointer(parts), value))
        if value.get("version") == "workbook_write_receipt_v1" and isinstance(value.get("path"), str):
            binding_owner = archive.resolve_binding(value["path"], owner)
        elif (isinstance(value.get("path"), str)
              and Path(value["path"]).suffix.lower() in {".fpvs", ".xlsx"}
              and ("condition_companion" in value or "spectral_companion" in value)):
            # FullFFT/selection source-workbook records carry project-relative
            # anchors. Their companion paths are relative to that anchor,
            # exactly as in native manifests and workbook-write receipts.
            binding_owner = archive.resolve_binding(value["path"], owner, project_relative=True)
        bindings = []
        if isinstance(value.get("path"), str) and "sha256" in value:
            bindings.append(("path", "sha256", False))
        for prefix in ("fif", "sidecar"):
            if f"{prefix}_path" in value and f"{prefix}_sha256" in value:
                bindings.append((f"{prefix}_path", f"{prefix}_sha256", True))
        for path_key, hash_key, project_relative in bindings:
            bound = archive.resolve_binding(value[path_key], binding_owner or owner,
                                            project_relative=project_relative).resolve()
            _require(bound.is_file(), f"Missing hash-bound artifact: {bound}")
            digest = value[hash_key]
            _require(isinstance(digest, str) and HEX64.fullmatch(digest) is not None,
                     f"Malformed bound SHA-256: {owner}:{_pointer(parts)}")
            _require(archive.sha(bound) == digest, f"Bound artifact checksum mismatch: {bound}")
            if path_key == "path":
                for size_key in ("size", "size_bytes"):
                    if size_key in value:
                        _require(type(value[size_key]) is int and value[size_key] == bound.stat().st_size,
                                 f"Bound artifact size mismatch: {bound}")
                if "mtime_ns" in value:
                    _require(value["mtime_ns"] == bound.stat().st_mtime_ns,
                             f"Bound artifact modification time mismatch: {bound}")
            archive.proofs.append({"kind": "artifact_binding", "file": str(owner), "pointer": _pointer(parts),
                                   "artifact": str(bound), "sha256": digest})
        completion_anchor = None
        if (len(parts) == 6
                and parts[:3] == ("tools", "condition_electrode_interpolation", "completed")
                and parts[4] == "outputs"
                and owner.resolve() == (archive.root / "project.json").resolve() and parts[5].isdigit()):
            from Main_App.io.condition_data import condition_companion_identity
            from Main_App.io.spectral_data import spectral_companion_identity
            from Main_App.processing.condition_interpolation_state import artifact_identity

            _require(set(value) == {"artifact", "condition_companion", "spectral_companion"}
                     and isinstance(value["artifact"], dict)
                     and set(value["artifact"]) == {"path", "size", "mtime_ns", "sha256"},
                     "Uncharacterized condition-repair completion output schema")
            completion_anchor = archive.resolve_binding(value["artifact"]["path"], owner, project_relative=True).resolve()
            _require(completion_anchor.is_file() and completion_anchor.is_relative_to(archive.root)
                     and completion_anchor.suffix.lower() in {".fpvs", ".xlsx"},
                     "Condition-repair completion artifact anchor is invalid")
            identities = {"artifact": artifact_identity(completion_anchor, project_root=archive.root),
                          "condition_companion": condition_companion_identity(completion_anchor),
                          "spectral_companion": spectral_companion_identity(completion_anchor)}
            _require(_exact(_canonical_mapping_order(value)) == _exact(_canonical_mapping_order(identities)),
                     "Condition-repair completion output differs from its native artifact/companion identities")
            archive.proofs.append({"kind": "native_condition_repair_completion_output_anchor", "file": str(owner),
                                   "pointer": _pointer(parts), "artifact": str(completion_anchor)})
        for key, item in value.items():
            child_owner = completion_anchor if completion_anchor is not None and key in {"condition_companion", "spectral_companion"} else binding_owner
            _verify_bindings(item, owner, archive, (*parts, key), (*ancestors, value), child_owner)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _verify_bindings(item, owner, archive, (*parts, str(index)), ancestors, binding_owner)


def _verify_native(path: Path, archive: Archive) -> None:
    from Main_App.io.condition_data import validate_condition_companion
    from Main_App.io.result_manifest import read_result_manifest
    from Main_App.io.spectral_data import validate_spectral_companion

    declaration = read_result_manifest(path)
    for key, validator in (("spectral_companion", validate_spectral_companion),
                           ("condition_companion", validate_condition_companion)):
        descriptor = declaration[key]
        if descriptor is None:
            continue
        validator(path, descriptor)
        companion = path.parent / descriptor["path"]
        _require(archive.sha(companion) == descriptor["sha256"], f"Native companion checksum mismatch: {companion}")
        archive.proofs.append({"kind": "native_schema_and_companion", "file": str(path), "companion": str(companion),
                               "sha256": descriptor["sha256"], "sheets": descriptor["sheets"]})


def _normalize_json(value, relative, archive, rules, parts=()):
    matching = [rule for rule in rules if fnmatch.fnmatchcase(relative, rule["file"])
                and _pointer_matches(rule["pointer"], parts)]
    _require(len(matching) < 2, f"Overlapping normalization rules: {relative}:{_pointer(parts)}")
    if matching:
        rule = matching[0]
        name = parts[-1] if parts else ""
        _require(not any(word in name.casefold() for word in ("fingerprint", "sha256", "hash")),
                 f"Fingerprint/hash normalization is prohibited: {relative}:{_pointer(parts)}")
        kind = rule["kind"]
        if kind == "elapsed":
            _require(name in _ELAPSED or "timings_ms" in parts[:-1] or "stage_seconds" in parts[:-1],
                     "Elapsed rule must name an explicit runtime timing field")
            numeric = _decode_audit_scalars(value)
            _require(type(numeric) in (float, int) and math.isfinite(numeric) and numeric >= 0, "Invalid elapsed field")
        elif kind == "generated_timestamp":
            _require(name in _GENERATED and isinstance(value, str), "Unrecognized generated timestamp field")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif kind == "output_path":
            _require(name in _PATHS and isinstance(value, str) and archive.origin_root is not None,
                     "Output path normalization requires an explicit original project root")
            path = Path(value)
            _require(path.is_absolute() and path.is_relative_to(archive.origin_root), "Output path is outside its declared root")
            normalized = "<PROJECT_ROOT>/" + path.relative_to(archive.origin_root).as_posix()
            archive.normalizations.append({"file": relative, "pointer": _pointer(parts), "kind": kind, "original": value})
            return normalized
        elif kind == "execution_source_root":
            _require(parts == ("source_root",) and isinstance(value, str) and archive.execution_source_root is not None,
                     "Execution source normalization requires a declared source root and its exact top-level field")
            _require(Path(value).is_absolute() and Path(value).resolve() == archive.execution_source_root,
                     "Execution source path differs from the declared snapshot")
        else:
            raise ParityError(f"Unknown normalization kind: {kind}")
        archive.normalizations.append({"file": relative, "pointer": _pointer(parts), "kind": kind, "original": value})
        return f"<RUNTIME:{kind}>"
    if isinstance(value, dict):
        return {key: _normalize_json(item, relative, archive, rules, (*parts, key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json(item, relative, archive, rules, (*parts, str(index))) for index, item in enumerate(value)]
    return value


def _zip_members(left: Path, right: Path, *, xlsx=False) -> list[dict]:
    proofs = []
    with zipfile.ZipFile(left) as first, zipfile.ZipFile(right) as second:
        _require(first.namelist() == second.namelist(), f"ZIP member names/order differ: {left.name}")
        _require(len(set(first.namelist())) == len(first.namelist()), f"Duplicate ZIP member: {left}")
        for name in first.namelist():
            a, b = first.getinfo(name), second.getinfo(name)
            for field_name in ("compress_type", "flag_bits", "external_attr", "internal_attr",
                               "create_system", "create_version", "extract_version", "comment", "extra"):
                _require(getattr(a, field_name) == getattr(b, field_name), f"ZIP metadata differs: {name}/{field_name}")
            normalized = False
            if xlsx and name == "docProps/core.xml":
                raw_a, raw_b = first.read(name), second.read(name)
                def core_time(match):
                    datetime.fromisoformat(match[3].decode("ascii").replace("Z", "+00:00"))
                    return match[1] + b"<GENERATED_TIMESTAMP>" + match[4]

                normalized = raw_a != raw_b
                raw_a, raw_b = _CORE_TIME.sub(core_time, raw_a), _CORE_TIME.sub(core_time, raw_b)
                _require(raw_a == raw_b, f"ZIP member content differs: {left.name}:{name}")
                digest = hashlib.sha256(raw_a).hexdigest()
            else:
                checksum = hashlib.sha256()
                with first.open(name) as aa, second.open(name) as bb:
                    while True:
                        chunk_a, chunk_b = aa.read(CHUNK_BYTES), bb.read(CHUNK_BYTES)
                        _require(chunk_a == chunk_b, f"ZIP member content differs: {left.name}:{name}")
                        if not chunk_a:
                            break
                        checksum.update(chunk_a)
                digest = checksum.hexdigest()
            proofs.append({"member": name, "exact_uncompressed_sha256": digest,
                           "normalized_core_timestamps": normalized})
    return proofs


def _verified_workbook_source_text(original_sources: str, metadata: dict, owner: Path, archive: Archive,
                                   *, sheet_name: str, application_xml: bytes, cell="B19") -> tuple[str, dict]:
    """Bind a native source-summary cell to its complete ordered preimage.

    Openpyxl clips string cells to 32,767 Python characters before XML escaping.
    A clipped terminal timestamp is display text, never an artifact identity.
    Validate the exact native serialization and every source, including rows
    beyond the displayed prefix, before normalizing only generated mtimes in
    the complete comparison preimage. No source row is discarded.
    """
    import openpyxl
    from openpyxl.cell import cell as cell_module
    from Main_App.io.result_manifest import read_result_manifest

    approved = {"3 - Statistical Analysis Results/Analysis_Ready_Summed_BCA_Full_Audit.xlsx": "Selection Summary",
                "Quality Check/Harmonic_Selection_Summary.xlsx": "Selection_Summary"}
    relative = owner.relative_to(archive.root).as_posix()
    _require(relative in approved and sheet_name == approved[relative] and cell == "B19"
             and owner.resolve() == (archive.root / relative).resolve(),
             "Workbook source text is outside its exact native owner/sheet/field")
    actual_metadata = _json_load(archive.root / "project.json")["tools"]["processing"]["harmonic_selection"]["active"]["selection_metadata"]
    _require(_exact(_canonical_mapping_order(metadata)) == _exact(_canonical_mapping_order(actual_metadata)),
             "Workbook source preimage is not the current authoritative selection metadata")
    engine_file = Path(cell_module.__file__).resolve()
    _require(openpyxl.__version__ == "3.1.5"
             and _sha(engine_file) == "85526c302f64240c716ff0aca49941af00eddaacdf71c3ba6037cf1cadc10424"
             and cell_module.Cell.check_string.__module__ == cell_module.__name__
             and Path(cell_module.Cell.check_string.__code__.co_filename).resolve() == engine_file,
             "Unknown native workbook string engine/version/implementation")
    engine_ast = ast.parse(engine_file.read_text(encoding="utf-8"))
    native_classes = [node for node in engine_ast.body if isinstance(node, ast.ClassDef) and node.name == "Cell"]
    _require(len(native_classes) == 1, "Missing characterized native string-engine class")
    native_checks = [node for node in native_classes[0].body if isinstance(node, ast.FunctionDef) and node.name == "check_string"]
    _require(len(native_checks) == 1, "Missing characterized native string-engine function")
    engine_namespace = {}
    exec(compile(ast.Module(body=native_checks, type_ignores=[]), str(engine_file), "exec", dont_inherit=True), engine_namespace)
    expected_code = engine_namespace["check_string"].__code__
    actual_code = cell_module.Cell.check_string.__code__
    code_fields = ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals", "co_stacksize", "co_flags",
                   "co_code", "co_names", "co_varnames", "co_freevars", "co_cellvars")
    _require(all(getattr(actual_code, field) == getattr(expected_code, field) for field in code_fields)
             and _exact(actual_code.co_consts) == _exact(expected_code.co_consts),
             "Live native workbook string function differs from its characterized source code")
    properties = ET.fromstring(application_xml)
    ns = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
    applications = properties.findall("{" + ns + "}Application")
    versions = properties.findall("{" + ns + "}AppVersion")
    _require(len(applications) == len(versions) == 1
             and applications[0].text == "Microsoft Excel Compatible / Openpyxl 3.1.5" and versions[0].text == "3.1",
             "Physical workbook does not declare the characterized native string engine")
    _require(archive.execution_source_root is not None, "Workbook source text needs its verified frozen execution source")
    native_relative = Path("src/Tools/Stats/io/stats_ready_export.py")
    native_path = (archive.execution_source_root / native_relative).resolve()
    current_path = ROOT / native_relative
    _require(native_path.is_relative_to(archive.execution_source_root) and native_path.is_file()
             and _sha(native_path) == _sha(current_path), "Workbook native source formatter differs from its frozen execution source")
    module = ast.parse(native_path.read_text(encoding="utf-8"))
    functions = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_source_workbook_identities"]
    _require(len(functions) == 1, "Missing native workbook source formatter")
    namespace = {"Mapping": Mapping}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(native_path), "exec"), namespace)
    formatter = namespace["_source_workbook_identities"]
    sources = metadata["source_workbook_fingerprints"]
    _require(type(original_sources) is str and type(sources) is list and sources,
             "Workbook source text lacks its full native ordered source-list preimage")
    normalized, seen_paths, seen_cells = [], set(), set()
    for row in sources:
        _require(isinstance(row, dict) and all(type(row.get(name)) is str and row[name] for name in
                                             ("subject", "condition", "path"))
                 and type(row.get("size_bytes")) is int and type(row.get("mtime_ns")) is int,
                 "Workbook source preimage has non-native typed source fields")
        name = row["path"]
        _require(not Path(name).anchor and ".." not in Path(name).parts,
                 "Workbook source preimage must be project relative")
        declared = archive.resolve_binding(name, archive.root / "project.json", project_relative=True)
        _require(all(not path.is_symlink() for path in (declared, *declared.parents) if path.is_relative_to(archive.root)),
                 "Workbook source preimage contains a symbolic-link alias")
        bound = declared.resolve()
        identity = (row["subject"], row["condition"])
        _require(bound.is_relative_to(archive.root) and bound.is_file() and bound.suffix.lower() == ".fpvs"
                 and bound not in seen_paths and identity not in seen_cells
                 and row["size_bytes"] == bound.stat().st_size and row["mtime_ns"] == bound.stat().st_mtime_ns,
                 f"Workbook complete source preimage is not bound to its artifact: {bound}")
        read_result_manifest(bound)
        seen_paths.add(bound)
        seen_cells.add(identity)
        normalized.append({**row, "mtime_ns": "<VERIFIED_GENERATED_MTIME>"})
    full_text = formatter(sources)
    try:
        serialized_text = cell_module.Cell.check_string(None, full_text)
    except Exception as exc:
        raise ParityError("Native workbook string serialization rejected its source preimage") from exc
    _require(original_sources == serialized_text,
             "Workbook source cell differs from its exact native serialized full preimage")
    normalized_full_text = formatter(normalized)
    return normalized_full_text, {"native_source_formatter_sha256": _sha(native_path),
                                  "native_string_engine": "openpyxl 3.1.5", "native_cell_implementation_sha256": _sha(engine_file),
                                  "full_source_count": len(sources), "full_native_characters": len(full_text),
                                  "serialized_characters": len(serialized_text), "native_string_limit_characters": 32767,
                                  "native_full_preimage_sha256": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
                                  "serialized_cell_sha256": hashlib.sha256(original_sources.encode("utf-8")).hexdigest(),
                                  "complete_comparison_preimage_sha256": hashlib.sha256(normalized_full_text.encode("utf-8")).hexdigest(),
                                  "all_sources_including_undisplayed_tail_physically_bound": True}


def compare_workbook_provenance(left: Path, right: Path, a: Archive, b: Archive,
                                baseline_map: dict, candidate_map: dict) -> dict:
    """Compare every XML byte after two strictly bound provenance-cell edits."""
    approved = {"3 - Statistical Analysis Results/Analysis_Ready_Summed_BCA_Full_Audit.xlsx",
                "Quality Check/Harmonic_Selection_Summary.xlsx"}
    relative = left.relative_to(a.root).as_posix()
    _require(relative == right.relative_to(b.root).as_posix(), "Workbook relative identities differ")
    records = []

    def transform(container, archive, correspondence):
        sheet_member = None
        sheet_name = None
        if relative in approved:
            workbook = ET.fromstring(container.read("xl/workbook.xml"))
            relation = ET.fromstring(container.read("xl/_rels/workbook.xml.rels"))
            targets = {item.attrib["Id"]: item.attrib["Target"] for item in relation}
            for item in workbook.iter():
                if item.tag.rsplit("}", 1)[-1] == "sheet" and item.attrib.get("name") in {"Selection Summary", "Selection_Summary"}:
                    _require(sheet_member is None, "Ambiguous native selection-summary sheet")
                    sheet_name = item.attrib["name"]
                    identity = item.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
                    target = targets[identity]
                    sheet_member = target.lstrip("/") if target.startswith("/") else "xl/" + target
            _require(sheet_member in container.namelist(), "Selection-summary XML relationship is missing")
        outputs = {}
        for member in container.namelist():
            content = container.read(member)
            if member == "docProps/core.xml":
                def timestamp(match):
                    datetime.fromisoformat(match[3].decode("ascii").replace("Z", "+00:00"))
                    return match[1] + b"<GENERATED_TIMESTAMP>" + match[4]
                content = _CORE_TIME.sub(timestamp, content)
            if member == sheet_member:
                tree = ET.fromstring(content)
                native_cells = [item for item in tree.iter() if item.tag.rsplit("}", 1)[-1] == "c"]
                _require(all(sum(item.attrib.get("r") == name for item in native_cells) == 1
                             for name in ("A12", "B12", "A19", "B19")),
                         "Native selection-summary target cell is missing or duplicated")
                cells = {item.attrib["r"]: "".join(node.text or "" for node in item.iter()
                                                   if node.tag.rsplit("}", 1)[-1] == "t")
                         for item in native_cells}
                _require(cells.get("A12") == "Selection fingerprint"
                         and cells.get("A19") == "Selection source workbook identities",
                         "Selection-summary provenance cells have changed schema")
                manifest = _json_load(archive.root / "project.json")
                metadata = manifest["tools"]["processing"]["harmonic_selection"]["active"]["selection_metadata"]
                original_digest = cells["B12"]
                _require(original_digest == metadata["selection_fingerprint"] and original_digest in correspondence,
                         "Workbook selection fingerprint lacks a validated canonical correspondence")
                encoded = escape(original_digest).encode("utf-8")
                _require(content.count(encoded) == 1, "Ambiguous workbook selection fingerprint cell")
                content = content.replace(encoded, escape(correspondence[original_digest]).encode("utf-8"))
                original_sources = cells["B19"]
                normalized_sources, source_proof = _verified_workbook_source_text(
                    original_sources, metadata, archive.root / relative, archive,
                    sheet_name=sheet_name, application_xml=container.read("docProps/app.xml"))
                encoded = escape(original_sources).encode("utf-8")
                _require(content.count(encoded) == 1, "Ambiguous workbook source-identity cell")
                content = content.replace(encoded, escape(normalized_sources).encode("utf-8"))
                records.append({"archive": str(archive.root), "file": relative, "member": member,
                                "cells": ["B12", "B19"], "selection_fingerprint": original_digest,
                                "source_workbook_count": source_proof["full_source_count"],
                                "source_mtimes_validated_against_actual_artifacts": True, "source_text_proof": source_proof})
            outputs[member] = content
        return outputs

    with zipfile.ZipFile(left) as first, zipfile.ZipFile(right) as second:
        _require(first.namelist() == second.namelist() and len(set(first.namelist())) == len(first.namelist()),
                 "Workbook member inventory/order differs")
        aa, bb = transform(first, a, baseline_map), transform(second, b, candidate_map)
        proofs = []
        for member in first.namelist():
            for name in ("compress_type", "flag_bits", "external_attr", "internal_attr", "create_system",
                         "create_version", "extract_version", "comment", "extra"):
                _require(getattr(first.getinfo(member), name) == getattr(second.getinfo(member), name),
                         f"Workbook ZIP metadata differs: {member}:{name}")
            _require(aa[member] == bb[member], f"Workbook XML differs outside validated provenance: {relative}:{member}")
            proofs.append({"member": member, "normalized_uncompressed_sha256": hashlib.sha256(aa[member]).hexdigest()})
    return {"kind": "xlsx_bound_provenance", "file": relative, "members": proofs, "provenance_edits": records,
            "scientific_xml_and_all_other_content_exact": True, "fingerprint_fields_dropped": []}


def compare_frequency_review_text(a: Archive, b: Archive, baseline_map: dict, candidate_map: dict) -> dict:
    """Bind every displayed decision before normalizing its hash-derived order."""
    relative = "Quality Check/Frequency_Domain_QC_Review.txt"
    original_orders = []
    def normalize(archive, correspondence):
        content = (archive.root / relative).read_bytes()
        newline = "\r\n" if b"\r\n" in content else "\n"
        _require(b"\r" not in content.replace(b"\r\n", b"") and content.endswith(newline.encode()),
                 "Unexpected frequency-review newline encoding")
        lines = content.decode("utf-8").splitlines()
        for index, line in enumerate(lines):
            if line.startswith("Reviewed at: "):
                datetime.fromisoformat(line.removeprefix("Reviewed at: ").replace("Z", "+00:00"))
                lines[index] = "Reviewed at: <GENERATED_REVIEW_TIMESTAMP>"
            for prefix in ("Decision fingerprint: ", "- Analysis fingerprint: "):
                if line.startswith(prefix):
                    digest = line.removeprefix(prefix)
                    _require(HEX64.fullmatch(digest) is not None and digest in correspondence,
                             "Displayed review fingerprint lacks an exact canonical correspondence")
                    lines[index] = prefix + correspondence[digest]
        start = lines.index("Reviewed findings and decisions") + 1
        stop = next(index for index in range(start, len(lines)) if not lines[index])
        state = _json_load(archive.root / "project.json")["tools"]["frequency_domain_qc"]
        expected = {}
        for entry in state["review_decisions"]:
            evidence = entry["evidence"]
            identity = str(entry.get("recording_id") or entry.get("participant_id") or "")
            absolute = evidence.get("abs_summed_bca_uv")
            if absolute is None:
                absolute = evidence.get("value_uv")
            text = (f"- {identity} / {entry.get('condition') or ''} / {entry.get('electrode') or ''}: "
                    f"decision={entry.get('decision') or ''}; signed={evidence.get('summed_bca_uv')}; absolute={absolute}; "
                    f"band={evidence.get('band_crossed') or evidence.get('severity') or ''}; "
                    f"harmonics={evidence.get('selected_harmonics_hz') or []}; reason={entry.get('reason') or '(retain)'}")
            digest = entry["decision_fingerprint"]
            _require(digest in correspondence and text not in expected,
                     "Displayed decision is ambiguous or lacks a canonical correspondence")
            expected[text] = correspondence[digest]
        _require(len(lines[start:stop]) == len(expected) and set(lines[start:stop]) == expected.keys(),
                 "Frequency-review text is not bound exactly to all saved native decisions")
        original_orders.append({"archive": str(archive.root), "decision_lines": lines[start:stop]})
        lines[start:stop] = sorted(lines[start:stop], key=lambda text: expected[text])
        return (newline.join(lines) + newline).encode("utf-8")
    aa, bb = normalize(a, baseline_map), normalize(b, candidate_map)
    _require(aa == bb, "Frequency-review text differs outside its bound runtime provenance")
    return {"file": relative, "normalized_utf8_sha256": hashlib.sha256(aa).hexdigest(),
            "all_displayed_decision_values_exact": True, "original_hash_derived_display_orders": original_orders,
            "fingerprint_fields_dropped": []}


def _array_proof(array: np.ndarray) -> dict:
    _require(not array.dtype.hasobject, "Object arrays are prohibited")
    flattened = array.ravel(order="K")
    view = memoryview(flattened).cast("B")
    digest = hashlib.sha256()
    for offset in range(0, len(view), CHUNK_BYTES):
        digest.update(view[offset:offset + CHUNK_BYTES])
    return {"dtype": array.dtype.str, "dtype_descriptor": repr(array.dtype.descr), "shape": list(array.shape),
            "strides": list(array.strides), "c_contiguous": bool(array.flags.c_contiguous),
            "f_contiguous": bool(array.flags.f_contiguous), "sample_bytes_sha256": digest.hexdigest()}


def _verify_runner_array_claims(path: Path, archive: Archive, arrays) -> None:
    relative = path.relative_to(archive.root).as_posix()
    expected = archive.runner_artifacts.get(relative)
    if expected is None:
        return
    names = arrays.files if hasattr(arrays, "files") else list(arrays)
    _require(isinstance(expected, dict) and list(expected) == names,
             f"Runner array inventory/order mismatch: {path}")
    for name in names:
        array = arrays[name]
        claim = _runner_array_claim(array, expected[name])
        _require(expected[name] == claim, f"Runner array dtype/shape/checksum binding mismatch: {path}:{name}")
        if array.ndim == 0 and expected[name]["array_shape"] == [1]:
            archive.proofs.append({"kind": "legacy_runner_contiguous_scalar_shape", "file": relative,
                                   "array": name, "declared_inventory_shape": [1], "actual_npy_shape": [],
                                   "actual_shape_compared_independently": True})
    archive.verified_runner_artifacts.add(relative)
    archive.proofs.append({"kind": "runner_array_bindings", "file": relative, "array_count": len(names)})


def _runner_array_claim(array, expected):
    """Verify the runner's declared contiguous-byte/original-layout recipe."""
    base = {"array_dtype", "array_shape", "array_sha256"}
    layout = {"array_strides", "array_c_contiguous", "array_f_contiguous"}
    _require(isinstance(expected, dict) and set(expected) in (base, base | layout), "Unknown runner array claim schema")
    contiguous = np.ascontiguousarray(array)
    actual_shape = list(array.shape)
    # The original runner inventoried its contiguous view, which turns a scalar
    # into shape [1]. Retain that explicitly disclosed historical claim recipe;
    # cross-archive shape/layout always comes from the actual NPY header.
    claimed_shape = list(contiguous.shape) if array.ndim == 0 and expected["array_shape"] == [1] else actual_shape
    claim = {"array_dtype": array.dtype.str, "array_shape": claimed_shape,
             "array_sha256": _array_proof(contiguous)["sample_bytes_sha256"]}
    if set(expected) == base | layout:
        claim.update(array_strides=list(array.strides), array_c_contiguous=bool(array.flags.c_contiguous),
                     array_f_contiguous=bool(array.flags.f_contiguous))
    return claim


def _verify_npz_metadata(metadata: dict, container, owner: Path, archive: Archive) -> None:
    _verify_bindings(_decode_audit_scalars(metadata), owner, archive)
    state = metadata.get("state") if isinstance(metadata, dict) else None
    if isinstance(metadata, dict) and isinstance(metadata.get("version"), str) and metadata["version"].startswith("prepared_kurtosis_"):
        from Main_App.processing.prepared_kurtosis_cache import CHECKPOINT_VERSION

        _require(metadata["version"] == CHECKPOINT_VERSION
                 and set(metadata) == {"version", "key", "evidence_fingerprint", "state"}
                 and isinstance(state, list) and state and state[0] == "dict",
                 f"Malformed native prepared-checkpoint metadata: {owner}")
    if not (isinstance(state, list) and state and state[0] == "dict"):
        return
    from Main_App.processing.prepared_raw_codec import decode_state

    decoded = decode_state(state, container)
    _verify_bindings(decoded.get("params", {}), owner, archive, ("state", "params"))
    if "evidence_fingerprint" in metadata:
        evidence = decoded.get("evidence")
        _require(evidence is not None and getattr(evidence, "fingerprint", None) == metadata["evidence_fingerprint"],
                 f"Encoded checkpoint evidence fingerprint mismatch: {owner}")
        _verify_bindings(evidence.to_payload(), owner, archive, ("state", "evidence"))
        archive.proofs.append({"kind": "encoded_checkpoint_evidence", "file": str(owner),
                               "sha256": metadata["evidence_fingerprint"]})


def _compare_npz(left: Path, right: Path, a: Archive, b: Archive) -> dict:
    members = _zip_members(left, right)
    arrays = []
    with np.load(left, allow_pickle=False) as first, np.load(right, allow_pickle=False) as second:
        _require(first.files == second.files, f"NPZ member order differs: {left}")
        _verify_runner_array_claims(left, a, first)
        _verify_runner_array_claims(right, b, second)
        for name in first.files:
            aa, bb = first[name], second[name]
            signature = _array_proof(aa)
            _require(signature == _array_proof(bb), f"NPZ array bytes/layout differ: {left}:{name}")
            arrays.append({"name": name, **signature})
            if name == "metadata_json" and aa.size == 1 and aa.dtype.kind in "SU":
                for own, path, metadata, container in ((a, left, aa, first), (b, right, bb, second)):
                    text = metadata.reshape(-1)[0].item()
                    if isinstance(text, bytes):
                        text = text.decode("utf-8")
                    _verify_npz_metadata(json.loads(text), container, path, own)
    return {"kind": "npz", "members": members, "arrays": arrays}


def _compare_fif(left: Path, right: Path, a: Archive, b: Archive) -> dict:
    import mne
    from Main_App.processing.prepared_raw_codec import encode_state

    first = mne.io.read_raw_fif(left, preload=False, verbose=False)
    second = mne.io.read_raw_fif(right, preload=False, verbose=False)
    try:
        def metadata(raw):
            buffers = {}
            encoded = encode_state({"info": raw.info, "annotations": raw.annotations,
                                    "first_samp": int(raw.first_samp), "n_times": int(raw.n_times),
                                    "orig_format": raw.orig_format}, buffers)
            return encoded, {name: _array_proof(value) for name, value in buffers.items()}

        _require(metadata(first) == metadata(second), f"FIF Info/annotations/grid differs: {left}")
        digest = hashlib.sha256()
        channels = len(first.ch_names)
        span = max(1, CHUNK_BYTES // max(8, channels * 8))
        for start in range(0, first.n_times, span):
            stop = min(first.n_times, start + span)
            aa, bb = first.get_data(start=start, stop=stop), second.get_data(start=start, stop=stop)
            _require(_array_proof(aa) == _array_proof(bb), f"FIF sample bytes differ: {left}:{start}:{stop}")
            digest.update(memoryview(aa).cast("B"))
        _require(a.sha(left) == b.sha(right), f"FIF container bytes differ: {left}; no volatile-ID whitelist is approved")
        for path, archive in ((left, a), (right, b)):
            relative = path.relative_to(archive.root).as_posix()
            if relative in archive.runner_artifacts:
                _require(archive.runner_artifacts[relative] == {"container_sha256": archive.sha(path)},
                         f"Runner FIF container binding mismatch: {path}")
                archive.verified_runner_artifacts.add(relative)
        return {"kind": "fif", "container_exact": True, "metadata_exact": True,
                "sample_chunks_sha256": digest.hexdigest(), "channels": first.ch_names,
                "n_times": int(first.n_times), "sample_dtype": "<f8"}
    finally:
        first.close()
        second.close()


def _verify_remaining_runner_claims(archive: Archive) -> None:
    """Verify each audit inventory claim even when a cache is excluded."""
    for relative, expected in archive.runner_artifacts.items():
        if relative in archive.verified_runner_artifacts:
            continue
        path = archive.root / relative
        suffix = path.suffix.lower()
        if suffix == ".npz":
            with np.load(path, allow_pickle=False) as arrays:
                _verify_runner_array_claims(path, archive, arrays)
        elif suffix == ".npy":
            array = np.load(path, allow_pickle=False, mmap_mode="r")
            _require(expected == _runner_array_claim(array, expected),
                     f"Runner NPY array binding mismatch: {path}")
        elif suffix == ".fif":
            _require(expected == {"container_sha256": archive.sha(path)}, f"Runner FIF container binding mismatch: {path}")
        elif suffix == ".xlsx":
            with zipfile.ZipFile(path) as container:
                actual = {}
                for name in container.namelist():
                    content = container.read(name)
                    if name == "docProps/core.xml":
                        content = _CORE_TIME.sub(lambda match: match[1] + b"TIMESTAMP" + match[4], content)
                    actual[name] = hashlib.sha256(content).hexdigest()
            _require(_exact(expected) == _exact({"normalized_zip_members": actual}),
                     f"Runner worksheet/member binding mismatch: {path}")
        else:
            raise ParityError(f"Unsupported runner artifact claim: {path}")
        archive.verified_runner_artifacts.add(relative)
        archive.proofs.append({"kind": "runner_artifact_binding", "file": relative})


def _verify_span_plan_references(archive: Archive) -> None:
    for owner, pointer, reference in archive.span_plan_references:
        fields = {name: item for name, item in reference.items() if name != "fingerprint"}
        payloads = archive.fingerprint_payloads.get(reference["fingerprint"], [])
        _require(any("spans" in payload and all(name in payload and _exact(payload[name]) == _exact(item)
                                                for name, item in fields.items()) for payload in payloads),
                 f"Analysis-span reference has no validated full plan: {owner}:{pointer}")
        archive.proofs.append({"kind": "analysis_span_plan_reference_binding", "file": owner,
                               "pointer": pointer, "sha256": reference["fingerprint"]})
    from Main_App.processing.condition_electrode_interpolation import condition_interpolation_export_provenance

    for owner, pointer, identity, reference, geometry in archive.condition_repair_persisted_provenances:
        matches = [full for _file, _pointer_value, full_identity, full in archive.condition_repair_full_provenances
                   if full_identity == identity and _exact(_canonical_mapping_order(full)) == _exact(_canonical_mapping_order(reference))]
        _require(matches and all(full["geometry_fingerprint"] == geometry.get("coordinate_fingerprint")
                                and full["retained_scalp_set_fingerprint"] == geometry.get("retained_scalp_set_fingerprint") for full in matches),
                 f"Persisted condition-repair ledger lacks its exact same-recording native full context: {owner}:{pointer}")
        from Main_App.io.eeg_geometry import biosemi64_geometry_identity

        canonical = biosemi64_geometry_identity(electrode_mapping_profile=geometry["electrode_mapping_profile"],
                                               retained_channels=geometry["retained_scalp_channels"])
        _require(_exact(_canonical_mapping_order(geometry)) == _exact(_canonical_mapping_order(canonical)), "Persisted condition-repair ledger geometry is not canonical")
        archive.proofs.append({"kind": "persisted_condition_repair_native_full_context_binding", "file": owner,
                               "pointer": pointer, "recording_id": identity, "sha256": reference["fingerprint"]})
    for owner, pointer, identity, full in archive.condition_repair_full_provenances:
        _require(identity in archive.condition_recording_global_bads
                 and _exact(full["recording_wide_interpolated_channels"]) == _exact(archive.condition_recording_global_bads[identity]),
                 f"Full condition repair lacks exact same-recording global bads: {owner}:{pointer}")
    for owner, pointer, identity, condition, reference in archive.condition_repair_references:
        matches = []
        for _full_owner, _full_pointer, full_identity, full in archive.condition_repair_full_provenances:
            if full_identity != identity or full.get("fingerprint") != reference["fingerprint"]:
                continue
            subset = condition_interpolation_export_provenance({"_fpvs_condition_interpolation_provenance": full}, condition)
            if _exact(_canonical_mapping_order(subset)) == _exact(_canonical_mapping_order(reference)):
                matches.append(condition)
        _require(matches, f"Compact condition repair lacks its exact validated full native provenance: {owner}:{pointer}")
        archive.proofs.append({"kind": "condition_repair_compact_full_preimage_binding", "file": owner,
                               "pointer": pointer, "sha256": reference["fingerprint"], "matched_conditions": sorted(set(matches))})


def _normalize_identity_runtime(value, archive: Archive, correspondence: dict, parts=()):
    """Normalize only verified generated-anchor mtimes and review runtime data.

    This helper acts on already-validated canonical SHA preimages. It does not
    turn unknown fingerprint strings into placeholders: only a correspondence
    established from two matching preimages may replace a dependent reference.
    """
    if isinstance(value, dict):
        result = {}
        for name, item in sorted(value.items()):
            pointer = (*parts, name)
            if name == "mtime_ns" and isinstance(value.get("path"), str):
                bound = archive.resolve_binding(value["path"], archive.root / "project.json",
                                                project_relative=True).resolve()
                if bound.is_relative_to(archive.root) and bound.suffix.lower() == ".fpvs":
                    _require(bound.is_file() and type(item) is int and item == bound.stat().st_mtime_ns,
                             f"Generated-anchor mtime is not bound to its own artifact: {bound}")
                    result[name] = "<GENERATED_MTIME>/" + bound.relative_to(archive.root).as_posix()
                    continue
            if name == "timings_ms":
                _require(isinstance(item, dict) and all(type(number) in (int, float)
                         and math.isfinite(number) and number >= 0 for number in item.values()),
                         "Canonical timing payload contains a non-runtime value")
                result[name] = {stage: "<ELAPSED>" for stage in sorted(item)}
                continue
            if name == "reviewed_at" or (name == "synced_at" and "last_review" in parts):
                _require(isinstance(item, str), "Malformed reviewed runtime timestamp")
                datetime.fromisoformat(item.replace("Z", "+00:00"))
                result[name] = "<REVIEWED_TIMESTAMP>"
                continue
            result[name] = _normalize_identity_runtime(item, archive, correspondence, pointer)
        return result
    if isinstance(value, (list, tuple)):
        result = [_normalize_identity_runtime(item, archive, correspondence, (*parts, str(index)))
                  for index, item in enumerate(value)]
        # The production decision recipes sort these collections by the hashes
        # of their rows. A runtime-derived hash therefore changes their display
        # order; reapply precisely that recipe after the verified substitution.
        if parts and parts[-1] in {"review_decisions", "reviewed_decisions"}:
            _require(all(isinstance(item, dict) and isinstance(item.get("decision_fingerprint"), str)
                         for item in result), "Malformed canonical review-decision collection")
            result.sort(key=lambda item: item["decision_fingerprint"])
        return tuple(result) if isinstance(value, tuple) else result
    if isinstance(value, str) and value in correspondence:
        return correspondence[value]
    return value


def _normalize_ram_identity_preimage(record: dict, archive: Archive, flag: bool):
    """Substitute only admitted native project-owned storage leaves on a copy."""
    routes = {
        "project_processing_signature_recipe": ("preprocessing", "experimental_ram_preload"),
        "processing_selection_input_recipe": ("upstream_input_identity", "project_processing_signature",
                                              "preprocessing", "experimental_ram_preload"),
    }
    route = routes.get(record["recipe"])
    payload = record["canonical_payload"]
    if route is None:
        return payload
    _require(Path(record["file"]).resolve() == (archive.root / "project.json").resolve()
             and record["pointer"] == "/" and isinstance(payload, dict),
             "RAM identity substitution requires its exact native project-root recipe")
    result = payload.copy()
    source, target = payload, result
    for name in route[:-1]:
        _require(isinstance(source.get(name), dict), "RAM native identity preimage path differs")
        source = source[name]
        target[name] = source.copy()
        target = target[name]
    _require(type(source.get(route[-1])) is bool and source[route[-1]] is flag,
             "RAM native identity preimage contradicts its admitted storage boolean")
    target[route[-1]] = "<MATCHED_NATIVE_RAM_STORAGE_BOOLEAN>"
    proof = {"kind": "matched_native_ram_storage_identity_leaf", "file": record["file"],
             "pointer": record["pointer"], "recipe": record["recipe"],
             "canonical_preimage_pointer": _pointer(route), "original": flag}
    if proof not in archive.proofs:
        archive.proofs.append(proof)
    return result


def build_identity_correspondence(a: Archive, b: Archive, policy: dict | None = None) -> dict:
    """Prove the full generated-mtime/timing cascade without dropping hashes."""
    contexts = (a, b)
    ram_flags = None
    if policy is not None and policy.get("comparison_purpose") == "ram_preload":
        sources = tuple(Path(policy[prefix + "_source_root"]).resolve() for prefix in ("baseline", "candidate"))
        ram_flags = _verify_ram_config_scope(tuple(archive.root for archive in contexts), sources)
        for archive, flag in zip(contexts, ram_flags):
            manifest = _json_load(archive.root / "project.json")
            raw = manifest.get("preprocessing", {}).get("experimental_ram_preload")
            _require(type(raw) is bool and raw is flag,
                     "RAM native project contradicts its admitted storage boolean")
        for archive, flag in zip(contexts, ram_flags):
            for recipes in archive.identity_recipes.values():
                for record in recipes:
                    _normalize_ram_identity_preimage(record, archive, flag)
    common_actual_identities = a.identity_recipes.keys() & b.identity_recipes.keys()
    maps = ({}, {})
    proofs = []
    seen = set()
    rounds = 0
    while True:
        indexes = []
        for side, (archive, remap) in enumerate(zip(contexts, maps)):
            signatures = {}
            for actual, recipes in archive.identity_recipes.items():
                if actual in common_actual_identities:
                    continue
                for record in recipes:
                    if "raw_diagnostics" in Path(record["file"]).parts:
                        # Added display-cache implementation identities have
                        # no baseline counterpart. Their own key/result/report
                        # bindings are verified separately, never normalized.
                        continue
                    payload = record["canonical_payload"]
                    if ram_flags is not None:
                        payload = _normalize_ram_identity_preimage(record, archive, ram_flags[side])
                    normalized = _normalize_identity_runtime(payload, archive, remap)
                    typed = _exact(normalized)
                    digest = hashlib.sha256(json.dumps(typed, separators=(",", ":"),
                                                      ensure_ascii=False, allow_nan=False).encode()).hexdigest()
                    signature = (record["recipe"], digest)
                    signatures.setdefault(signature, []).append((actual, record, normalized))
            indexes.append(signatures)
        additions = 0
        for signature in sorted(indexes[0].keys() & indexes[1].keys()):
            left, right = indexes[0][signature], indexes[1][signature]
            left_ids, right_ids = {row[0] for row in left}, {row[0] for row in right}
            if left_ids == right_ids:
                continue
            normalized_identity = "<VERIFIED_IDENTITY>/" + signature[1]
            for side, rows in enumerate((left, right)):
                for actual, _, _ in rows:
                    if actual not in maps[side]:
                        maps[side][actual] = normalized_identity
                        additions += 1
            if signature not in seen:
                seen.add(signature)
                proofs.append({"recipe": signature[0], "normalized_typed_payload_sha256": signature[1],
                               "baseline_sha256": sorted(left_ids), "candidate_sha256": sorted(right_ids),
                               "baseline_preimage_location": {key: left[0][1][key] for key in ("file", "pointer")},
                               "candidate_preimage_location": {key: right[0][1][key] for key in ("file", "pointer")},
                               "normalized_canonical_payload": left[0][2], "dependency_round": rounds})
        rounds += 1
        if additions == 0:
            break
        _require(rounds <= len(a.identity_recipes) + len(b.identity_recipes) + 1,
                 "Identity correspondence failed to converge")
    unmatched = []
    for side, archive in enumerate(contexts):
        for actual, recipes in archive.identity_recipes.items():
            if actual in common_actual_identities or actual in maps[side]:
                continue
            for record in recipes:
                if "raw_diagnostics" in Path(record["file"]).parts:
                    continue
                unmatched.append({"side": "baseline" if side == 0 else "candidate", "sha256": actual,
                                  "recipe": record["recipe"], "file": record["file"], "pointer": record["pointer"]})
    return {"baseline_map": maps[0], "candidate_map": maps[1], "proofs": proofs, "rounds": rounds,
            "unmatched_canonical_identities": unmatched,
            "fingerprint_fields_dropped": [], "numerical_tolerance": None}


def compare_identity_archives(baseline: Path, candidate: Path, policy: dict | None = None) -> dict:
    """Audit canonical identity preimages separately from strict artifact bytes."""
    policy = policy or {}
    hashes = {}
    contexts = []
    for prefix, root in (("baseline", baseline), ("candidate", candidate)):
        origin = policy.get(prefix + "_origin_root")
        archive = Archive(Path(root).resolve(), Path(origin).resolve() if origin else None, hashes=hashes)
        _require(archive.root.is_dir(), f"Missing identity archive: {archive.root}")
        for path in sorted(archive.root.rglob("*")):
            _require(not path.is_symlink(), f"Symbolic link in identity archive: {path}")
            if not path.is_file() or (path.suffix.lower() not in {".json", ".fpvs"}
                                      and path.name != "processing_runs.jsonl"):
                continue
            if path.suffix.lower() == ".fpvs":
                _verify_native(path, archive)
            _verify_bindings(_decode_audit_scalars(_stable_document(path)), path, archive)
        _verify_span_plan_references(archive)
        contexts.append(archive)
    correspondence = build_identity_correspondence(*contexts, policy=policy)
    return {"status": "failed" if correspondence["unmatched_canonical_identities"] else "passed",
            "scope": "canonical scientific identity preimages; payload bytes require strict artifact comparison",
            "baseline": str(contexts[0].root), "candidate": str(contexts[1].root),
            "baseline_binding_proofs": contexts[0].proofs, "candidate_binding_proofs": contexts[1].proofs,
            "baseline_unverified_runtime_bindings": contexts[0].unverified_runtime_bindings,
            "candidate_unverified_runtime_bindings": contexts[1].unverified_runtime_bindings,
            "identity_correspondence": correspondence, "numerical_tolerance": None,
            "fingerprint_hash_fields_dropped": []}


def compare_prepared_checkpoints(baseline: Path, candidate: Path) -> dict:
    """Strictly compare the native checkpoint capture from RAM preparation runs.

    Namespace keys bind the original source paths. Matching by that namespace
    permits an explicit report when checkpoint filenames differ, while every
    actual array/member, encoded state, evidence and checkpoint key stays exact.
    A key difference requires its original canonical preimage; it is never
    silently normalized as a loader setting.
    """
    contexts = (Archive(Path(baseline).resolve()), Archive(Path(candidate).resolve()))
    indexes = []
    for archive in contexts:
        folder = archive.root / ".fpvs_cache" / "prepared_kurtosis"
        _require(folder.is_dir(), f"Missing prepared-checkpoint capture: {folder}")
        entries = {}
        for manifest in sorted(folder.rglob("latest.json")):
            namespace = manifest.parent.relative_to(folder).as_posix()
            _require(re.fullmatch(r"[0-9a-f]{24}", namespace) is not None,
                     f"Unexpected source checkpoint namespace: {namespace}")
            declaration = _json_load(manifest)
            _require(set(declaration) == {"version", "key", "path", "sha256", "size_bytes"},
                     f"Unknown prepared-checkpoint declaration schema: {manifest}")
            from Main_App.processing.prepared_kurtosis_cache import CHECKPOINT_VERSION

            _require(declaration["version"] == CHECKPOINT_VERSION
                     and isinstance(declaration["key"], str) and isinstance(declaration["sha256"], str)
                     and HEX64.fullmatch(declaration["key"]) is not None
                     and HEX64.fullmatch(declaration["sha256"]) is not None,
                     f"Malformed prepared-checkpoint identity: {manifest}")
            _require(declaration["path"] == f'{declaration["key"]}.{declaration["sha256"][:20]}.npz',
                     f"Prepared-checkpoint filename does not bind its key and hash: {manifest}")
            _verify_bindings(declaration, manifest, archive)
            selected = manifest.parent / declaration["path"]
            _require(set(manifest.parent.iterdir()) == {manifest, selected},
                     f"Prepared capture contains an unselected or stale namespace artifact: {manifest.parent}")
            with np.load(selected, allow_pickle=False) as arrays:
                metadata = json.loads(str(arrays["metadata_json"].item()))
                _require(metadata.get("version") == declaration["version"]
                         and metadata.get("key") == declaration["key"],
                         f"Prepared checkpoint metadata is not bound to its native declaration: {selected}")
                _verify_npz_metadata(metadata, arrays, selected, archive)
            _require(namespace not in entries, "Duplicate prepared source namespace")
            entries[namespace] = (selected, declaration)
        _require(bool(entries), "No prepared checkpoints captured")
        indexes.append(entries)
    _require(indexes[0].keys() == indexes[1].keys(), "Prepared source namespaces/count differ")
    proofs, failures = [], []
    for namespace in sorted(indexes[0]):
        (left, aa), (right, bb) = indexes[0][namespace], indexes[1][namespace]
        try:
            proof = _compare_npz(left, right, *contexts)
            _require(aa["key"] == bb["key"], "Checkpoint key differs; exact original key-preimage proof is required")
            proofs.append({"source_namespace": namespace, "baseline_file": str(left), "candidate_file": str(right),
                           "checkpoint_key": aa["key"], **proof})
        except (ParityError, OSError, ValueError) as exc:
            failures.append({"source_namespace": namespace, "baseline_file": str(left), "candidate_file": str(right),
                             "baseline_key": aa["key"], "candidate_key": bb["key"], "error": str(exc)})
    return {"status": "failed" if failures else "passed", "scope": "all native prepared arrays, raw NPY members, encoded MNE state and kurtosis evidence",
            "baseline": str(contexts[0].root), "candidate": str(contexts[1].root), "checkpoint_count": len(indexes[0]),
            "artifacts": proofs, "failures": failures, "baseline_binding_proofs": contexts[0].proofs,
            "candidate_binding_proofs": contexts[1].proofs, "numerical_tolerance": None,
            "fingerprint_hash_fields_dropped": []}


def _verify_ram12_review_trace(path: Path) -> dict:
    """Bind recorded populations; this is not a per-allocation event proof."""
    starts, finishes, pools, grants = [], [], [], []
    with path.open("rb") as stream:
        for line in stream:
            if b"kurtosis_review_process_started " in line:
                match = re.search(rb"kurtosis_review_process_started files=(\d+) max_workers=(\d+) memory_budget_bytes=(\d+) dynamic_memory=(True|False) emergency_reserve_bytes=(\d+)[ \t]*(?:\r?\n)?\Z", line)
                _require(match is not None, "Malformed RAM12 dynamic preparation start")
                starts.append(match.groups())
            elif b"kurtosis_review_process_finished " in line:
                match = re.search(rb"kurtosis_review_process_finished files=(\d+) completed=(\d+) max_workers=(\d+) elapsed_seconds=([0-9.]+) cancelled=(True|False) memory_budget_bytes=(\d+) peak_reserved_bytes=(\d+) peak_in_flight=(\d+) oversize_fallbacks=(\d+) peak_pool_workers=(\d+) pool_starts=(\d+)[ \t]*(?:\r?\n)?\Z", line)
                _require(match is not None, "Malformed RAM12 dynamic preparation finish")
                finishes.append(match.groups())
            elif b"kurtosis_review_pool_started " in line:
                match = re.search(rb"kurtosis_review_pool_started max_workers=(\d+) worker_ceiling=(\d+)[ \t]*(?:\r?\n)?\Z", line)
                _require(match is not None, "Malformed RAM12 preparation pool")
                pools.append(tuple(map(int, match.groups())))
            elif b"review_scoring_emergency_granted " in line:
                match = re.search(rb"review_scoring_emergency_granted index=(\d+) credit_bytes=(\d+)[ \t]*(?:\r?\n)?\Z", line)
                _require(match is not None, "Malformed RAM12 scoring grant")
                grants.append(tuple(map(int, match.groups())))
    _require(len(starts) == len(finishes) == 1 and bool(pools), "RAM12 preparation requires one start/finish and its actual pools")
    files, ceiling, budget, dynamic, emergency = starts[0]
    finished_files, completed, finished_ceiling, elapsed, cancelled, finished_budget, peak, in_flight, oversized, peak_pool, pool_starts = finishes[0]
    _require((int(files), int(ceiling), dynamic) == (58, 12, b"True")
             and (int(finished_files), int(completed), int(finished_ceiling), cancelled) == (58, 58, 12, b"False")
             and int(budget) > 0 and int(finished_budget) == int(budget)
             and math.isfinite(float(elapsed)) and float(elapsed) >= 0,
             "RAM12 preparation scope/status/budget differs")
    _require(all(1 <= population <= 12 and cap == 12 for population, cap in pools)
             and int(pool_starts) == len(pools) and int(peak_pool) == max(population for population, _ in pools)
             and 1 <= int(in_flight) <= int(peak_pool) and int(peak) > 0 and 0 <= int(oversized) <= 58
             and all(0 <= index < 58 and credit > 0 for index, credit in grants),
             "RAM12 preparation population/credit summary differs")
    return {"pool_populations": [population for population, _ in pools], "worker_ceiling": 12,
            "initial_budget_bytes": int(budget), "initial_emergency_bytes": int(emergency),
            "peak_reserved_bytes": int(peak), "peak_in_flight": int(in_flight), "scoring_grants": grants,
            "every_admission_snapshot_recorded": False}


def _verify_ram12_review_geometry(root: Path, source: Path, receipt: dict) -> list[dict]:
    from Main_App.workers import review_resource_budget as budget

    relative = "src/Main_App/workers/review_resource_budget.py"
    frozen = (source / relative).resolve()
    downstream = _json_load(root / "benchmark_evidence" / "downstream_receipt.json")
    _require(downstream.get("status") == "complete" and Path(downstream.get("source_root", "")).resolve() == source,
             "RAM12 geometry lacks its native downstream source witness")
    entries = [row for row in downstream.get("production_source_inventory", [])
               if row.get("module") == "Main_App.workers.review_resource_budget"]
    _require(len(entries) == 1 and entries[0].get("relative_path") == relative
             and frozen.is_file() and _sha(frozen) == entries[0].get("sha256")
             and _sha(Path(budget.__file__).resolve()) == entries[0]["sha256"],
             "RAM12 geometry implementation differs from its frozen execution inventory")
    manifest = _json_load(root / "project.json")
    geometries = []
    for identity in receipt["recordings"]:
        geometry = budget.read_review_geometry(Path(manifest["recordings"][identity]["raw_file"]), receipt["validated_params"])
        _require(geometry is not None, f"RAM12 source geometry is unsupported: {identity}")
        geometries.append({"recording_id": identity, "loaded_channels": geometry.loaded_channels,
                           "retained_channels": geometry.retained_channels, "scored_channels": geometry.scored_channels,
                           "source_n_times": geometry.source_n_times, "source_rate_hz": geometry.source_rate_hz,
                           "target_rate_hz": geometry.target_rate_hz, "packed_record_bytes": geometry.packed_record_bytes,
                           "source_record_samples": geometry.source_record_samples})
    return geometries


def _verify_ram_config_scope(roots: tuple[Path, Path], sources: tuple[Path, Path]) -> tuple[bool, bool]:
    """Admit the sole labelled native storage flag after matched full-run checks."""
    _require(sources[0] == sources[1], "RAM proof requires the same frozen execution source")
    receipts = [_decode_audit_scalars(_json_load(root / "benchmark_evidence" / "run_receipt.json")) for root in roots]
    _require(all(type(receipt.get("requested_worker_policy")) is str for receipt in receipts),
             "RAM proof worker policy must be an explicit string")
    requested = {receipt["requested_worker_policy"] for receipt in receipts}
    _require(len(requested) == 1 and requested <= {"2", "12"}, "RAM proof requires one explicit matched worker policy")
    requested_policy = next(iter(requested))
    normal_workers = int(requested_policy)
    for flag, root, receipt in zip((False, True), roots, receipts):
        _require(receipt.get("version") == "pipeline_bitwise_backend_runner_v1" and receipt.get("status") == "pipeline_complete"
                 and not receipt.get("profiling_diagnostic") and not receipt.get("functional_seed")
                 and type(receipt.get("normal_pool_max_workers")) is int
                 and receipt["normal_pool_max_workers"] == normal_workers, "RAM proof requires unprofiled complete matched-worker cases")
        _require(type(receipt.get("validated_params", {}).get("experimental_ram_preload")) is bool
                 and receipt["validated_params"]["experimental_ram_preload"] is flag,
                 "RAM proof direction must be OFF baseline followed by ON candidate")
        manifest = _json_load(root / "project.json")
        _require(set(receipt.get("recordings", [])) == set(manifest.get("recordings", {}))
                 and len(receipt.get("recordings", [])) == len(manifest.get("recordings", {}))
                 and (requested_policy != "12" or len(receipt["recordings"]) == 58)
                 and (root / "benchmark_evidence" / "project_before_runner.bin").is_file()
                 and "initial_project_manifest_preimage" in receipt,
                 "RAM proof requires all declared recordings and actual initial input bytes")
        if requested_policy == "12":
            _verify_ram12_review_trace(root / "benchmark_evidence" / "backend.log")
            _verify_ram12_review_geometry(root, sources[0], receipt)
        else:  # Preserve the separately labelled, historical two-worker scope.
            counts = set()
            with (root / "benchmark_evidence" / "backend.log").open("rb") as stream:
                for line in stream:
                    match = re.search(rb"kurtosis_review_process_(?:started|finished) files=\d+(?: completed=\d+)? max_workers=(\d+)", line)
                    if match:
                        counts.add(int(match[1]))
            _require(counts == {2}, "RAM proof lacks its actual fixed-two-worker preparation log")
    _require(receipts[0].get("recordings") == receipts[1].get("recordings") and receipts[0].get("recordings"),
             "RAM proof requires the same complete ordered recording scope")
    params = [{key: value for key, value in receipt["validated_params"].items() if key != "experimental_ram_preload"} for receipt in receipts]
    _require(_exact(params[0]) == _exact(params[1]), "RAM proof changed a validated scientific setting")
    return False, True


def _verify_preprocessed_ram_audit(value: dict, owner: Path, archive: Archive,
                                   project: dict, expected_flag: bool) -> dict:
    """Bind the native Raw-cache audit's sole storage annotation before admitting it."""
    from Main_App.projects import normalize_frequency_protocol
    from Main_App.workers import process_runner as runner

    relative_source = "src/Main_App/Performance/process_runner.py"
    frozen = archive.execution_source_root / relative_source if archive.execution_source_root is not None else None
    _require(frozen is not None and frozen.is_file()
             and _sha(Path(runner.__file__).resolve()) == _sha(frozen),
             "Preprocessed audit native implementation differs from its frozen execution source")
    _require(isinstance(value, dict) and isinstance(value.get("payload"), dict)
             and isinstance(value.get("audit_before"), dict)
             and type(value.get("cache_key")) is str and HEX64.fullmatch(value["cache_key"]) is not None,
             "Malformed native preprocessed cache sidecar")
    payload, audit, cache_key = value["payload"], value["audit_before"], value["cache_key"]
    _require(set(audit) == {"sfreq", "lowpass", "highpass", "n_channels", "ch_names", "ref_applied",
                            "ref_chans", "reference_requested", "params_snapshot", "file"}
             and isinstance(audit["params_snapshot"], dict)
             and payload.get("version") == runner.PREPROC_CACHE_VERSION
             and type(payload.get("mne_version")) is str and bool(payload["mne_version"])
             and type(payload.get("source_path")) is str,
             "Unsupported native preprocessed cache/audit schema")
    params = audit["params_snapshot"]
    recording_id = params.get("_fpvs_recording_id")
    recordings = project.get("recordings")
    _require(type(recording_id) is str and bool(recording_id) and isinstance(recordings, dict),
             "Preprocessed audit lacks its declared recording/source identity")
    declared = recordings.get(recording_id)
    _require(isinstance(declared, dict)
             and type(declared.get("raw_file")) is str,
             "Preprocessed audit lacks its declared recording/source identity")
    source = Path(payload["source_path"])
    _require(source.is_absolute() and source.suffix.lower() == ".bdf" and source.is_file()
             and str(source.resolve()) == payload["source_path"]
             and source.resolve() == Path(declared["raw_file"]).resolve()
             and params.get("_fpvs_source_file_path") == str(source.resolve())
             and params.get("_fpvs_participant_id") == declared.get("participant_id")
             and params.get("_fpvs_session_id") == declared.get("session_id")
             and type(audit.get("file")) is str and audit["file"] == source.name
             and archive.origin_root is not None and type(params.get("project_root")) is str
             and Path(params["project_root"]).resolve() == archive.origin_root.resolve(),
             "Preprocessed audit source/recording/project ownership differs")
    _require(type(expected_flag) is bool and type(params.get("experimental_ram_preload")) is bool
             and params["experimental_ram_preload"] is expected_flag,
             "Preprocessed audit storage boolean contradicts its matched native run")
    protocol = normalize_frequency_protocol(project["frequency_protocol"])
    reproduced = runner._preproc_cache_payload(source, params, mne_version=payload["mne_version"],
                                               frequency_protocol=protocol, event_map=project["event_map"])
    _require(_exact(_canonical_mapping_order(payload)) == _exact(_canonical_mapping_order(reproduced))
             and runner._preproc_cache_key(payload) == cache_key,
             "Preprocessed cache native source/settings payload or key differs")
    raw_path, meta_path = runner._preproc_cache_paths(archive.root, source, cache_key)
    _require(owner == meta_path and owner.is_file() and not owner.is_symlink()
             and not meta_path.parent.is_symlink() and not meta_path.parent.parent.is_symlink()
             and raw_path.is_file() and not raw_path.is_symlink(),
             "Preprocessed cache audit owner/name or paired FIF differs")
    return {"kind": "native_preprocessed_cache_audit_storage_flag", "file": owner.relative_to(archive.root).as_posix(),
            "pointer": "/audit_before/params_snapshot/experimental_ram_preload", "cache_key": cache_key,
            "recording_id": recording_id, "source_path": str(source), "paired_fif": raw_path.relative_to(archive.root).as_posix(),
            "native_payload_reproduced": True, "original_storage_boolean": expected_flag,
            "remaining_audit_and_sidecar_fields_compared_exactly": True}


def _verify_native_runtime_field(value, owner: Path, archive: Archive, parts: tuple, parent: dict):
    """Bind only native CLI notes and the observed physical interpreter alias."""
    owner = owner.resolve()
    evidence = archive.root / "benchmark_evidence"
    full = evidence / "run_receipt.json"
    compact = evidence / "telemetry_core_receipt.json"
    downstream = evidence / "downstream_receipt.json"
    note = owner in {full, compact} and parts == ("ambient_workload_note",)
    interpreter = ((owner == full and parts == ("downstream", "interpreter"))
                   or (owner == downstream and parts == ("interpreter",)))
    if not note and not interpreter:
        return None
    _require(type(value) is str and value and isinstance(parent, dict), "Malformed native runtime annotation")
    expected_schema = ("pipeline_bitwise_backend_runner_v1" if owner == full else "pipeline_bitwise_telemetry_receipt_v1")
    _require((parent.get("version") == expected_schema if note else parent.get("schema") == "pipeline_downstream_probe_v1"),
             "Native runtime annotation has the wrong owner schema")
    _require(archive.root.name == "artifacts" and archive.root.parent.parent.name == "runs"
             and archive.origin_root is not None and archive.execution_source_root is not None,
             "Native runtime annotation lacks its archived execution context")
    launch_path = archive.root.parent / "launch.json"
    _require(launch_path.is_file() and not launch_path.is_symlink(), "Native runtime annotation lacks its own launch")
    launch = _json_load(launch_path)
    command = launch.get("command")
    _require(type(command) is list and len(command) >= 4 and all(type(item) is str for item in command)
             and launch.get("fixture") == "full58" and launch.get("profiling") is False
             and type(launch.get("pid")) is int and launch["pid"] > 0,
             "Uncharacterized native launch context")
    harness_path = ROOT / ".codex-tmp/pipeline-bitwise/final-native-harness-v3-manifest.json"
    harness_sha = "abdd93c0448fbe76e2310fc10e38eb7ac41f8bb3e0818dc37ba839d3644d5e1f"
    _require(_sha(harness_path) == harness_sha and launch.get("harness_identity") == {
        "manifest_path": str(harness_path), "manifest_sha256": harness_sha, "verified_harness_file_count": 7},
        "Native annotation launch does not bind the unchanged observer harness")
    harness = _json_load(harness_path)
    _require(harness.get("file_count") == len(harness.get("files", [])) == 7, "Native annotation harness count differs")
    for row in harness["files"]:
        relative = Path(row["path"])
        _require(not relative.is_absolute() and ".." not in relative.parts and "Standalone_Scripts" not in relative.parts,
                 "Invalid native annotation harness member")
        actual = (ROOT / relative).resolve()
        _require(actual.is_relative_to(ROOT) and actual.stat().st_size == row["size"] and _sha(actual) == row["sha256"],
                 "Native annotation observer source changed")
    _require(Path(command[1]).is_absolute() and Path(command[1]).resolve() == (ROOT / "scripts/manual_diagnostics/pipeline_bitwise_runner.py").resolve(),
             "Native annotation launch uses a different runner")

    def option(name):
        _require(command.count(name) == 1, "Native annotation launch option is missing or duplicated: " + name)
        index = command.index(name) + 1
        _require(index < len(command), "Native annotation launch option lacks its literal value")
        return command[index]

    def absolute_option(name):
        path = Path(option(name))
        _require(path.is_absolute(), "Native annotation launch path is not absolute")
        return path.resolve()

    _require(absolute_option("--source-root") == archive.execution_source_root
             and absolute_option("--project-root") == archive.origin_root
             and absolute_option("--output-dir") == archive.origin_root / "benchmark_evidence"
             and absolute_option("--workspace-root") == archive.root.parents[2],
             "Native annotation launch belongs to different source/project roots")
    _require(type(parent.get("source_root")) is str and type(parent.get("project_root")) is str
             and Path(parent["source_root"]).is_absolute() and Path(parent["project_root"]).is_absolute()
             and Path(parent["source_root"]).resolve() == archive.execution_source_root
             and Path(parent["project_root"]).resolve() == archive.origin_root,
             "Native annotation owner belongs to different source/project roots")
    if note:
        _require(value == option("--ambient-note") and type(parent.get("initial_project_sha256")) is str
                 and HEX64.fullmatch(parent["initial_project_sha256"]) is not None
                 and launch.get("initial_active_project_sha256") == parent["initial_project_sha256"],
                 "Native ambient note differs from its own literal invocation or input manifest")
        return "<VERIFIED_NATIVE_CLI_AMBIENT_ANNOTATION>", {
            "kind": "native_cli_ambient_annotation", "literal": value, "launch_path": str(launch_path),
            "launch_sha256": archive.sha(launch_path), "native_harness_sha256": harness_sha,
            "scope": "CLI-backed benchmark annotation retained verbatim; no ambient-workload equivalence is asserted."}
    _require(value == command[0] and parent.get("python_version") == sys.version,
             "Native interpreter differs from its own invocation or captured Python version")
    executable = Path(value)
    active = Path(sys.executable)
    environment = executable.parent.parent
    current_environment = Path(sys.prefix)
    import sysconfig

    _require(executable.is_absolute() and executable.is_file() and executable.samefile(active)
             and executable.resolve() == active.resolve()
             and environment.is_dir() and environment.samefile(current_environment)
             and environment.resolve() == current_environment.resolve(),
             "Native interpreter is not the same physical executable and environment")
    config, current_config = environment / "pyvenv.cfg", current_environment / "pyvenv.cfg"
    _require(config.is_file() and current_config.is_file() and config.samefile(current_config),
             "Native interpreter environment configuration differs")
    packages = environment / ("Lib/site-packages" if os.name == "nt" else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
    current_packages = Path(sysconfig.get_path("purelib"))
    _require(packages.is_dir() and packages.samefile(current_packages) and packages.resolve() == current_packages.resolve(),
             "Native interpreter package directory is not the same physical environment")
    return "<VERIFIED_NATIVE_INTERPRETER_PHYSICAL_ALIAS>", {
        "kind": "native_interpreter_physical_alias", "literal": value, "resolved_executable": str(executable.resolve()),
        "executable_sha256": _sha(executable), "environment": str(environment.resolve()),
        "pyvenv_config_sha256": _sha(config), "package_directory": str(packages.resolve()),
        "captured_python_version": parent["python_version"], "launch_sha256": archive.sha(launch_path),
        "historical_package_inventory_asserted": False,
        "scope": "Only the requested interpreter alias is unified. Other runtime fields, including _base_executable, remain literal."}


def _typed_metadata_differences(left, right, parts=()):
    """Retain exact scalar types/bits and every concrete differing location."""
    if type(left) is not type(right):
        yield {"pointer": _pointer(parts), "kind": "type", "baseline": _exact(left), "candidate": _exact(right)}
    elif isinstance(left, dict):
        if list(left) != list(right):
            yield {"pointer": _pointer(parts), "kind": "ordered_keys", "baseline": list(left), "candidate": list(right)}
        for key in left:
            if key not in right:
                yield {"pointer": _pointer((*parts, key)), "kind": "candidate_missing", "baseline": _exact(left[key])}
            else:
                yield from _typed_metadata_differences(left[key], right[key], (*parts, key))
        for key in right:
            if key not in left:
                yield {"pointer": _pointer((*parts, key)), "kind": "baseline_missing", "candidate": _exact(right[key])}
    elif isinstance(left, list):
        if len(left) != len(right):
            yield {"pointer": _pointer(parts), "kind": "list_length", "baseline": len(left), "candidate": len(right)}
        for index in range(max(len(left), len(right))):
            if index >= len(left):
                yield {"pointer": _pointer((*parts, str(index))), "kind": "baseline_missing", "candidate": _exact(right[index])}
            elif index >= len(right):
                yield {"pointer": _pointer((*parts, str(index))), "kind": "candidate_missing", "baseline": _exact(left[index])}
            else:
                yield from _typed_metadata_differences(left[index], right[index], (*parts, str(index)))
    elif _exact(left) != _exact(right):
        yield {"pointer": _pointer(parts), "kind": "scalar_bits_or_value", "baseline": _exact(left), "candidate": _exact(right)}


def compare_runtime_metadata(baseline: Path, candidate: Path, policy: dict, identity_report: dict) -> dict:
    """Compare all stable JSON fields using an already validated identity proof.

    Execution-source digests are independently checked against the explicitly
    frozen source roots and inventoried separately. They are expected to change
    in a performance comparison; scientific fingerprint fields are substituted
    only through their validated canonical preimage correspondence.
    """
    graph = identity_report["identity_correspondence"]
    _require(identity_report["status"] == "passed" and not graph["unmatched_canonical_identities"],
             "Runtime metadata requires a complete canonical scientific identity proof")
    roots = (Path(baseline).resolve(), Path(candidate).resolve())
    _require(str(roots[0]) == identity_report["baseline"] and str(roots[1]) == identity_report["candidate"],
             "Identity proof belongs to different archived inputs")
    contexts = tuple(Archive(root, Path(policy[prefix + "_origin_root"]).resolve())
                     for prefix, root in zip(("baseline", "candidate"), roots))
    sources = tuple(Path(policy[prefix + "_source_root"]).resolve() for prefix in ("baseline", "candidate"))
    for archive, source in zip(contexts, sources):
        archive.execution_source_root = source
    ram_flags = _verify_ram_config_scope(roots, sources) if policy.get("comparison_purpose") == "ram_preload" else None
    maps = (dict(graph["baseline_map"]), dict(graph["candidate_map"]))
    runtime, execution, proofs, differences = [], [], [], []
    timestamps = {"generated_at", "groups_locked_at", "completed_at", "reviewed_at", "saved_at", "updated_at",
                  "synced_at", "last_outputs_refreshed_at", "started_utc", "finished_utc", "started_at_utc",
                  "finished_at_utc", "applied_at_utc", "native_runner_returned_utc"}
    elapsed = {"setup_elapsed_seconds", "worker_run_elapsed_seconds", "total_elapsed_seconds", "start_elapsed_seconds",
               "finish_elapsed_seconds", "worker_run_gross_elapsed_seconds", "observer_manifest_capture_elapsed_seconds_excluded_from_worker_time",
               "benchmark_policy_action_elapsed_seconds_excluded_from_worker_time"}
    verified_complete_receipts = {}
    verified_storage_censuses = {}
    verified_raw_diagnostic_files = {}
    ram_project_documents = {}
    verified_preprocessed_ram_audits = set()

    def record(side, file, parts, kind, original):
        runtime.append({"side": "baseline" if side == 0 else "candidate", "file": file,
                        "pointer": _pointer(parts), "kind": kind, "original": _exact(original)})

    def normalize(value, side, file, parts=(), parent=None):
        name = parts[-1] if parts else ""
        benchmark = file.startswith("benchmark_evidence/")
        historical_input = file in {"benchmark_evidence/project_before_downstream.json", "benchmark_evidence/project_before_runner.bin"}
        repair_transition_input = file.startswith("benchmark_evidence/project_after_condition_repairs.attempt") and file.endswith(".bin")
        if ram_flags is not None and parts == ():
            if file == "project.json":
                ram_project_documents[side] = value
            elif len(Path(file).parts) == 3 and Path(file).parts[:2] == (".fpvs_cache", "preprocessed") and Path(file).suffix == ".json":
                binding = _verify_preprocessed_ram_audit(value, roots[side] / file, contexts[side],
                                                        ram_project_documents[side], ram_flags[side])
                proofs.append(binding)
                verified_preprocessed_ram_audits.add((side, file))
        if (file == "project.json" and isinstance(value, dict)
                and _verify_native_harmonic_input_history(value, roots[side] / file, contexts[side], parts, record=False)):
            return value  # Every old type/bit/key/path/hash remains literal input history.
        if ram_flags is not None and name == "experimental_ram_preload":
            project_leaf = parts == ("preprocessing", name) and (file == "project.json" or historical_input or repair_transition_input)
            receipt_leaf = parts == ("validated_params", name) and file in {"benchmark_evidence/run_receipt.json", "benchmark_evidence/telemetry_core_receipt.json"}
            snapshot_leaf = parts == ("settings", name) and file == ".fpvs_processing/condition_interpolation_run.json"
            cache_audit_leaf = parts == ("audit_before", "params_snapshot", name) and (side, file) in verified_preprocessed_ram_audits
            _require((project_leaf or receipt_leaf or snapshot_leaf or cache_audit_leaf) and type(value) is bool and value is ram_flags[side],
                     f"Uncharacterized or contradictory persisted RAM preload flag: side={'baseline' if side == 0 else 'candidate'} "
                     f"file={file} pointer={_pointer(parts)} type={type(value).__name__} value={_exact(value)!r}")
            record(side, file, parts, "matched_native_ram_storage_boolean", value)
            return "<MATCHED_NATIVE_RAM_STORAGE_BOOLEAN>"
        if file == "benchmark_evidence/run_receipt.json" and parts == ():
            verified_raw_diagnostic_files[side] = _verify_raw_diagnostics_namespace(value, contexts[side])
            proofs.extend(contexts[side].proofs)
        if file == "benchmark_evidence/telemetry_core_receipt.json" and parts == ():
            _verify_compact_observer_receipt(value, roots[side] / file, contexts[side])
        native_note = (file in {"benchmark_evidence/run_receipt.json", "benchmark_evidence/telemetry_core_receipt.json"}
                       and parts == ("ambient_workload_note",) and value not in (None, ""))
        native_interpreter = ((file == "benchmark_evidence/run_receipt.json" and parts == ("downstream", "interpreter"))
                              or (file == "benchmark_evidence/downstream_receipt.json" and parts == ("interpreter",)))
        if native_note or native_interpreter:
            token, binding = _verify_native_runtime_field(value, roots[side] / file, contexts[side], parts, parent)
            record(side, file, parts, binding["kind"], binding)
            return token
        if file == "benchmark_evidence/telemetry_core_receipt.json" and parts == ("observer_full_receipt_proof",):
            _require(side in verified_complete_receipts, "Compact reference requires prior complete native proof equivalence")
            record(side, file, parts, "verified_complete_native_receipt_reference", value)
            return {"path": "<VERIFIED_COMPLETE_NATIVE_RECEIPT>/benchmark_evidence/run_receipt.json",
                    "size_bytes": "<INDEPENDENTLY_VERIFIED_PHYSICAL_SIZE>",
                    "sha256": "<VERIFIED_COMPLETE_NATIVE_RECEIPT>/" + verified_complete_receipts[side]}
        if benchmark and name == "size_bytes" and isinstance(parent, dict) and isinstance(parent.get("sha256"), str):
            typed_preimage = maps[side].get(parent["sha256"], "")
            if typed_preimage.startswith(("<VERIFIED_NATIVE_MANIFEST_PREIMAGE>/", "<VERIFIED_INTERMEDIATE_PROJECT_CONTENT>/")):
                bound = contexts[side].resolve_binding(parent["path"], roots[side] / file).resolve()
                _require(type(value) is int and bound.is_file() and bound.stat().st_size == value
                         and contexts[side].sha(bound) == parent["sha256"], "Native manifest preimage physical size/hash differs from its declaration")
                record(side, file, parts, "physical_size_of_verified_typed_native_manifest_preimage", value)
                return "<INDEPENDENTLY_VERIFIED_NATIVE_MANIFEST_PREIMAGE_SIZE>"
        if file in {"benchmark_evidence/run_receipt.json", "benchmark_evidence/telemetry_core_receipt.json"} and parts == ("generated_storage_footprint",):
            if side not in verified_storage_censuses:
                _verify_generated_storage_census(value, contexts[side])
                verified_storage_censuses[side] = value
            _require(_exact(value) == _exact(verified_storage_censuses[side]), "Conflicting copied generated-storage census")
            record(side, file, parts, "independently_verified_generated_file_size_observations", value)
            cache_files = verified_raw_diagnostic_files.get(side, [])
            record(side, file, parts, "exact_native_payload_bound_optional_cache_file_count", {
                "file_count": len(cache_files), "files": [path.relative_to(roots[side]).as_posix() for path in cache_files]})
            return {"file_count": value["file_count"] - len(cache_files), "size_bytes": "<VERIFIED_GENERATED_FILE_BYTES>",
                    "by_project_top_level": {key: {"file_count": value["by_project_top_level"][key]["file_count"] -
                                                    sum(path.relative_to(roots[side]).parts[0] == key for path in cache_files),
                                                    "size_bytes": "<VERIFIED_GENERATED_FILE_BYTES>"}
                                             for key in sorted(value["by_project_top_level"])},
                    "stat_errors": [], "scope": value["scope"]}
        if name == "timestamp" and file == ".fpvs_processing/processing_runs.jsonl":
            _require(isinstance(value, str), "Malformed native processing-run journal timestamp")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            record(side, file, parts, "processing_run_journal_timestamp", value)
            return "<PROCESSING_RUN_TIMESTAMP>"
        if name in timestamps:
            _require(name != "native_runner_returned_utc" or benchmark, "Native runner timestamp appears outside observer receipts")
            _require(isinstance(value, str), "Malformed inventoried generated timestamp")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            record(side, file, parts, "generated_timestamp", value)
            return "<GENERATED_TIMESTAMP>"
        if name == "mtime_ns" and isinstance(parent, dict) and "path" in parent:
            if historical_input or (repair_transition_input and parts[:3] != ("tools", "condition_electrode_interpolation", "completed")):
                # Prior GUI cache/output references remain fully present as
                # identical input history; they are not rebound to new outputs.
                return value
            bound = contexts[side].resolve_binding(parent["path"], roots[side] / "project.json", project_relative=True)
            if bound.is_relative_to(roots[side]) and bound.suffix.lower() == ".fpvs":
                _require(bound.is_file() and type(value) is int and bound.stat().st_mtime_ns == value,
                         f"Metadata mtime differs from its own generated anchor: {bound}")
                record(side, file, parts, "bound_generated_anchor_mtime", value)
                return "<GENERATED_MTIME>/" + bound.relative_to(roots[side]).as_posix()
        if name in {"timings_ms", "stage_seconds"}:
            _require(isinstance(value, dict) and all(type(item) in (int, float) and math.isfinite(item) and item >= 0
                     for item in value.values()), "Malformed inventoried runtime timing dictionary")
            record(side, file, parts, "runtime_timings", value)
            return {stage: "<ELAPSED>" for stage in value}
        if name == "elapsed_ms" or (benchmark and name in elapsed):
            _require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "Malformed runtime elapsed value")
            record(side, file, parts, "elapsed", value)
            return "<ELAPSED>"
        if name == "pid" and benchmark and type(value) is int:
            _require(value > 0, "Malformed worker process identifier")
            record(side, file, parts, "worker_process_id", value)
            return "<WORKER_PROCESS_ID>"
        if name == "source_root" and benchmark:
            _require(Path(value).resolve() == sources[side], "Receipt source root differs from its frozen snapshot")
            record(side, file, parts, "execution_source_root", value)
            return "<EXECUTION_SOURCE>"
        if name == "worker_source_path" and "binding" in parts:
            path = Path(value)
            _require(path.is_relative_to(sources[side]), "Worker source path escapes its frozen execution source")
            record(side, file, parts, "execution_source_path", value)
            return "<EXECUTION_SOURCE>/" + path.relative_to(sources[side]).as_posix()
        if name == "production_source_inventory":
            _require(benchmark and isinstance(value, list), "Execution inventory appears outside diagnostic receipts")
            seen = set()
            for row in value:
                _require(isinstance(row, dict) and set(row) == {"module", "relative_path", "sha256"}
                         and isinstance(row["module"], str) and row["module"].split(".")[0] in {"Main_App", "Shared", "Tools", "config"}
                         and row["module"] not in seen and isinstance(row["sha256"], str) and HEX64.fullmatch(row["sha256"]) is not None,
                         "Malformed or duplicated execution-source inventory entry")
                seen.add(row["module"])
                path = (sources[side] / row["relative_path"]).resolve()
                module_path = "src/" + row["module"].replace(".", "/")
                permitted_paths = {module_path + ".py", module_path + "/__init__.py"}
                aliases = {"Main_App.workers.mp_env": "src/Main_App/Performance/mp_env.py",
                           "Main_App.workers.process_runner": "src/Main_App/Performance/process_runner.py"}
                if row["module"] in aliases:
                    permitted_paths.add(aliases[row["module"]])
                _require(row["relative_path"] in permitted_paths,
                         "Execution-source module/path binding mismatch")
                _require(path.is_relative_to(sources[side]) and "Standalone_Scripts" not in path.parts
                         and path.is_file() and _sha(path) == row["sha256"], "Frozen execution-source inventory checksum mismatch")
                execution.append({"side": side, "file": file, "pointer": _pointer(parts),
                                  "module": row["module"], "path": str(path), "sha256": row["sha256"]})
            # Performance implementations can add an imported helper module.
            # Preserve every real module/path/hash above as execution evidence;
            # compare scientific results and their identities independently.
            return "<INDEPENDENTLY_VERIFIED_EXECUTION_SOURCE_INVENTORY>"
        if isinstance(value, dict):
            order = sorted(value) if name == "entries" and file == ".fpvs_processing/processing_ledger.json" else value
            if order is not value:
                record(side, file, parts, "worker_completion_mapping_order", list(value))
            return {key: normalize(value[key], side, file, (*parts, key), value) for key in order}
        if isinstance(value, list):
            result = [normalize(item, side, file, (*parts, str(index)), value) for index, item in enumerate(value)]
            if parts[-2:] == ("processing_result", "results"):
                _require(len({item["file"] for item in result}) == len(result), "Ambiguous recording completion results")
                record(side, file, parts, "worker_completion_list_order", [item["file"] for item in result])
                result.sort(key=lambda item: item["file"])
            if name in {"review_decisions", "reviewed_decisions", "native_validated_decisions"}:
                record(side, file, parts, "hash_derived_review_order", [item["decision_fingerprint"] for item in result])
                result.sort(key=lambda item: item["decision_fingerprint"])
            return result
        return maps[side].get(value, value) if isinstance(value, str) else value

    # Workbook XML correspondence also validates the raw member-hash claims in
    # runner receipts; actual scientific cells remain exact in that proof.
    for left in sorted(roots[0].rglob("*.xlsx")):
        right = roots[1] / left.relative_to(roots[0])
        workbook = compare_workbook_provenance(left, right, *contexts, *maps)
        for side, path in enumerate((left, right)):
            with zipfile.ZipFile(path) as container:
                for member in workbook["members"]:
                    raw = hashlib.sha256(container.read(member["member"])).hexdigest()
                    maps[side][raw] = "<VERIFIED_WORKBOOK_MEMBER>/" + member["normalized_uncompressed_sha256"]
    projects = [normalize(_decode_audit_scalars(_json_load(root / "project.json")), side, "project.json")
                for side, root in enumerate(roots)]
    _require(_exact(projects[0]) == _exact(projects[1]), "Stable project-manifest content differs")
    project_identity = hashlib.sha256(json.dumps(_exact(projects[0]), separators=(",", ":")).encode()).hexdigest()
    for side, root in enumerate(roots):
        maps[side][_sha(root / "project.json")] = "<VERIFIED_PROJECT_CONTENT>/" + project_identity
    intermediate = [root / "benchmark_evidence" / "project_before_downstream.json" for root in roots]
    _require(intermediate[0].is_file() == intermediate[1].is_file(),
             "Only one run archived its intermediate project-manifest preimage")
    if intermediate[0].is_file():
        relative = "benchmark_evidence/project_before_downstream.json"
        values = [normalize(_decode_audit_scalars(_json_load(path)), side, relative)
                  for side, path in enumerate(intermediate)]
        _require(_exact(values[0]) == _exact(values[1]), "Stable intermediate project-manifest content differs")
        identity = hashlib.sha256(json.dumps(_exact(values[0]), separators=(",", ":")).encode()).hexdigest()
        for side, path in enumerate(intermediate):
            maps[side][_sha(path)] = "<VERIFIED_INTERMEDIATE_PROJECT_CONTENT>/" + identity
    binary_preimages = [{path.relative_to(root).as_posix(): path for path in (root / "benchmark_evidence").glob("project_*.bin")} for root in roots]
    _require(binary_preimages[0].keys() == binary_preimages[1].keys(), "Native manifest preimage inventories differ")
    for relative in sorted(binary_preimages[0]):
        _require(relative == "benchmark_evidence/project_before_runner.bin" or re.fullmatch(
            r"benchmark_evidence/project_after_condition_repairs\.attempt[1-9][0-9]*\.bin", relative) is not None,
            "Uncharacterized native manifest preimage")
        for side in (0, 1):
            path = binary_preimages[side][relative]
            if relative.endswith("project_before_runner.bin"):
                declaration = _json_load(roots[side] / "benchmark_evidence" / "telemetry_core_receipt.json")
                _verify_compact_observer_receipt(declaration, roots[side] / "benchmark_evidence" / "telemetry_core_receipt.json", contexts[side])
                _require(declaration.get("initial_project_sha256") == contexts[side].sha(path), "Initial input manifest bytes differ from native launch SHA")
            else:
                downstream = _json_load(roots[side] / "benchmark_evidence" / "downstream_receipt.json")
                bound = [row for row in downstream.get("condition_repair_manifest_preimages", [])
                         if contexts[side].resolve_binding(row["path"], roots[side] / "benchmark_evidence" / "downstream_receipt.json").resolve() == path.resolve()]
                _require(len(bound) == 1 and bound[0].get("sha256") == contexts[side].sha(path)
                         and type(bound[0].get("size_bytes")) is int and bound[0]["size_bytes"] == path.stat().st_size
                         and bound[0].get("native_phase_transition") == "frequency_domain_qc:0"
                         and relative == f"benchmark_evidence/project_after_condition_repairs.attempt{bound[0]['attempt_index']}.bin",
                         "Repair transition manifest bytes lack their exact native observer declaration")
        values = [normalize(_decode_audit_scalars(_json_load(binary_preimages[side][relative])), side, relative) for side in (0, 1)]
        _require(_exact(values[0]) == _exact(values[1]), "Typed native project-input or repair-transition preimages differ")
        identity = hashlib.sha256(json.dumps(_exact(values[0]), separators=(",", ":")).encode()).hexdigest()
        proofs.append({"file": relative, "normalized_typed_payload_sha256": identity,
                       "role": "historical_native_input" if relative.endswith("project_before_runner.bin") else "native_after_repair_before_frequency_qc"})
        for side in (0, 1):
            path = binary_preimages[side][relative]
            maps[side][_sha(path)] = "<VERIFIED_NATIVE_MANIFEST_PREIMAGE>/" + identity
    inventory = [{path.relative_to(root).as_posix(): path for path in root.rglob("*")
                  if path.is_file() and (path.suffix.lower() in {".json", ".fpvs"}
                                        or path.name == "processing_runs.jsonl")
                  and "/.slots/" not in path.relative_to(root).as_posix() and "raw_diagnostics" not in path.parts}
                 for root in roots]
    _require(inventory[0].keys() == inventory[1].keys(), "Stable JSON artifact inventories differ")
    complete = "benchmark_evidence/run_receipt.json"
    _require(complete in inventory[0], "Stable native metadata requires its complete run receipt")
    ordered = [complete, *(relative for relative in sorted(inventory[0]) if relative != complete)]
    stopped_at_full = False
    visited = []
    for relative in ordered:
        values = [normalize(_decode_audit_scalars(_stable_document(inventory[side][relative])), side, relative)
                  for side in (0, 1)]
        visited.append(relative)
        if _exact(values[0]) != _exact(values[1]):
            difference = {"file": relative, "reason": "Stable metadata differs or has an unverified runtime binding"}
            if relative == complete:
                difference["typed_differences"] = list(_typed_metadata_differences(*values))
            differences.append(difference)
            if relative == complete:
                stopped_at_full = True
                break
        else:
            typed_identity = hashlib.sha256(json.dumps(_exact(values[0]), separators=(",", ":")).encode()).hexdigest()
            proofs.append({"file": relative, "normalized_typed_payload_sha256": typed_identity})
            if relative == "benchmark_evidence/run_receipt.json":
                verified_complete_receipts.update({0: typed_identity, 1: typed_identity})
    return {"status": "failed" if differences else "passed",
            "scope": ("partial failed metadata: complete native receipt differs; compact and remaining stable metadata were not visited"
                      if stopped_at_full else "all stable JSON and native result metadata, full native receipts"),
            "proofs": proofs, "differences": differences, "runtime_field_inventory": runtime,
            "stopped_at_full_native_receipt": stopped_at_full, "visited_stable_metadata_files": visited,
            "unvisited_stable_metadata_files": [relative for relative in ordered if relative not in visited],
            "independently_verified_execution_provenance": execution,
            "unverified_intermediate_manifest_preimages": {
                "baseline": identity_report.get("baseline_unverified_runtime_bindings", []),
                "candidate": identity_report.get("candidate_unverified_runtime_bindings", [])},
            "numerical_tolerance": None, "scientific_fingerprint_fields_dropped": []}


def _verify_absent_frequency_review_text(archive: Archive) -> dict:
    """Prove automatic completion without a newly materialized human report.

    The native benchmark starts from the frozen manifest alone. Automatic sync
    preserves historical report/review fields while writing no human report;
    those historical fields remain literal in the complete metadata proof.
    """
    relative = "Quality Check/Frequency_Domain_QC_Review.txt"
    target = archive.root / relative
    _require(not target.exists() and not target.is_symlink(), "Absent review text is present or aliased")
    project_path = archive.root / "project.json"
    compact_path = archive.root / "benchmark_evidence/telemetry_core_receipt.json"
    initial_path = archive.root / "benchmark_evidence/project_before_runner.bin"
    project, compact = _json_load(project_path), _json_load(compact_path)
    _require(compact.get("version") == "pipeline_bitwise_telemetry_receipt_v1"
             and compact.get("status") == "pipeline_complete"
             and isinstance(compact.get("initial_project_sha256"), str)
             and HEX64.fullmatch(compact["initial_project_sha256"]) is not None
             and not initial_path.is_symlink() and archive.sha(initial_path) == compact["initial_project_sha256"],
             "Absent review text lacks its native initial-manifest binding")
    _require(archive.execution_source_root is not None and archive.origin_root is not None
             and Path(compact["source_root"]).resolve() == archive.execution_source_root.resolve()
             and Path(compact["project_root"]).resolve() == archive.origin_root.resolve(),
             "Absent review text belongs to different native source/project roots")
    initial = _json_load(initial_path)
    try:
        state = project["tools"]["frequency_domain_qc"]
        evidence, last, automatic = (state[name] for name in ("review_evidence", "last_review", "last_automatic_qc"))
        historical = initial["tools"]["frequency_domain_qc"]["last_review"]
        _require(type(state.get("schema_version")) is int and state["schema_version"] == 4
                 and state.get("method_version") == "experimental_summed_bca_recording_electrode_review_v5"
                 and state.get("identity_scope") == "recording" and state.get("review_complete") is True
                 and automatic.get("authority") == "review_only" and automatic.get("review_required") is False
                 and automatic.get("review_reused") is False and automatic.get("screening_status") == "performed"
                 and last.get("screening_status") == "performed"
                 and last.get("identity_scope") == evidence.get("identity_scope") == "recording"
                 and all(type(last.get(name)) is int and last[name] == 0 for name in
                         ("review_subject_count", "review_recording_count"))
                 and evidence.get("version") == "frequency_qc_review_evidence_v1"
                 and evidence.get("screening_enabled") is True and evidence.get("screening_status") == "performed",
                 "Absent review text is outside characterized automatic empty-findings completion")
        for name in ("review_decisions", "manual_participant_exclusions", "manual_recording_exclusions",
                     "auto_participant_electrode_exclusions", "auto_participant_exclusions",
                     "auto_recording_electrode_exclusions", "auto_recording_exclusions", "legacy_machine_suggestions"):
            _require(type(state.get(name)) is list and state[name] == [], "Absent review text has saved decisions or exclusions")
        for name in ("ordinary_findings", "cohort_findings", "cohort_rows", "reconfirmation_findings",
                     "technical_integrity_failures", "unavailable_by_method", "technical_statuses"):
            _require(type(evidence.get(name)) is list and evidence[name] == [], "Absent review text has current findings/statuses")
        _require(type(last.get("report_path")) is str and last["report_path"] == historical["report_path"]
                 and last["report_path"].replace("\\", "/") in {"", relative}
                 and type(last.get("reviewed_at")) is str and last["reviewed_at"]
                 and last["reviewed_at"] == historical["reviewed_at"]
                 and automatic.get("reviewed_at") == last.get("synced_at")
                 and automatic.get("analysis_fingerprint") == last.get("analysis_fingerprint") == evidence.get("analysis_fingerprint")
                 and isinstance(evidence.get("analysis_fingerprint"), str)
                 and HEX64.fullmatch(evidence["analysis_fingerprint"]) is not None,
                 "Absent review text has changed historical fields or unbound automatic review authority")
        datetime.fromisoformat(last["reviewed_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, AttributeError) as exc:
        raise ParityError("Malformed native automatic review-text absence context") from exc
    _verify_generated_storage_census(compact["generated_storage_footprint"], archive)
    return {"archive": str(archive.root), "project_sha256": archive.sha(project_path),
            "native_compact_sha256": archive.sha(compact_path), "initial_manifest_sha256": archive.sha(initial_path),
            "historical_report_path": last["report_path"], "historical_reviewed_at": last["reviewed_at"],
            "current_automatic_authority": "review_only", "native_generated_storage_census_verified": True,
            "scope": "Only native automatic empty-findings report absence; complete native metadata is checked separately."}



def _native_manifest_metadata_files(metadata: dict) -> set[str]:
    """Return only canonical native manifest paths with an existing typed proof."""
    result = set()
    for entry in metadata["proofs"]:
        role = entry.get("role")
        if role not in {"historical_native_input", "native_after_repair_before_frequency_qc"}:
            continue
        name = entry.get("file")
        _require(set(entry) == {"file", "normalized_typed_payload_sha256", "role"}
                 and type(name) is str and name not in result
                 and ((role == "historical_native_input" and name == "benchmark_evidence/project_before_runner.bin")
                      or (role == "native_after_repair_before_frequency_qc" and re.fullmatch(
                          r"benchmark_evidence/project_after_condition_repairs\.attempt[1-9][0-9]*\.bin", name) is not None))
                 and type(entry.get("normalized_typed_payload_sha256")) is str
                 and HEX64.fullmatch(entry["normalized_typed_payload_sha256"]) is not None,
                 "Native manifest metadata proof dispatch ownership is malformed or duplicated")
        result.add(name)
    return result


def compare_full_archives(baseline: Path, candidate: Path, policy: dict) -> dict:
    """Combine own provenance, actual payloads and narrow stable-artifact proof.

    Every selected file is dispatched exactly once. Explicitly excluded caches
    still undergo their own binding/schema audit in the identity proof. Missing
    historical preimages keep the complete proof failed even if other payloads
    are identical; a scientific fingerprint is never erased to force a pass.
    """
    _require(set(policy) <= {"rules", "exclude_files", "baseline_origin_root", "candidate_origin_root",
                             "baseline_source_root", "candidate_source_root", "comparison_purpose"}, "Unknown policy fields")
    _require(policy.get("comparison_purpose", "source_optimization") in {"source_optimization", "ram_preload"}, "Unknown full-proof comparison purpose")
    identity = compare_identity_archives(baseline, candidate, policy)
    _require(identity["status"] == "passed", "Canonical scientific identity correspondence failed")
    roots = (Path(baseline).resolve(), Path(candidate).resolve())
    contexts = tuple(Archive(root, Path(policy[prefix + "_origin_root"]).resolve())
                     for prefix, root in zip(("baseline", "candidate"), roots))
    graph = identity["identity_correspondence"]
    maps = (graph["baseline_map"], graph["candidate_map"])
    for archive, prefix in zip(contexts, ("baseline", "candidate")):
        archive.execution_source_root = Path(policy[prefix + "_source_root"]).resolve()
        receipt = archive.root / "benchmark_evidence" / "run_receipt.json"
        _require(receipt.is_file(), "Complete pipeline proof requires its native run receipt")
        _verify_bindings(_decode_audit_scalars(_json_load(receipt)), receipt, archive)
    inventories, excluded = [], []
    for archive in contexts:
        files = {}
        for path in sorted(archive.root.rglob("*")):
            _require(not path.is_symlink(), f"Symbolic links are not accepted: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(archive.root).as_posix()
            if any(fnmatch.fnmatchcase(relative, pattern) for pattern in policy.get("exclude_files", [])):
                excluded.append({"root": str(archive.root), "file": relative})
            else:
                files[relative] = path
        inventories.append(files)
    _require(inventories[0].keys() == inventories[1].keys(),
             f"Artifact inventories differ; baseline-only={sorted(inventories[0].keys() - inventories[1].keys())}, "
             f"candidate-only={sorted(inventories[1].keys() - inventories[0].keys())}")
    try:
        metadata = compare_runtime_metadata(baseline, candidate, policy, identity)
    except ValueError as exc:
        if policy.get("comparison_purpose") != "ram_preload":
            raise
        return {"status": "failed", "scope": "partial failed proof: stable metadata validation raised before remaining artifact comparisons",
                "error": str(exc), "baseline": str(roots[0]), "candidate": str(roots[1]), "policy": policy,
                "file_count": len(inventories[0]), "artifacts": [],
                "failures": [{"stage": "stable_metadata", "error": str(exc), "exception_type": type(exc).__name__}],
                "unvisited_artifact_files": sorted(inventories[0]), "excluded_files": excluded,
                "identity_proof": identity, "numerical_tolerance": None, "scientific_fingerprint_fields_dropped": []}
    if metadata.get("stopped_at_full_native_receipt"):
        return {"status": "failed", "scope": "partial failed proof: complete native receipt metadata differs before remaining artifact comparisons",
                "baseline": str(roots[0]), "candidate": str(roots[1]), "policy": policy,
                "file_count": len(inventories[0]), "artifacts": [], "failures": metadata["differences"],
                "unvisited_artifact_files": sorted(inventories[0]), "excluded_files": excluded,
                "identity_proof": identity, "stable_metadata": metadata,
                "numerical_tolerance": None, "scientific_fingerprint_fields_dropped": []}
    metadata_files = {entry["file"] for entry in metadata["proofs"]} | {entry["file"] for entry in metadata["differences"]}
    native_manifest_files = _native_manifest_metadata_files(metadata)
    review_text = "Quality Check/Frequency_Domain_QC_Review.txt"
    if review_text in inventories[0]:
        text = compare_frequency_review_text(*contexts, *maps)
        text_files = {review_text}
    else:
        text = {"file": review_text, "status": "not_applicable_native_automatic_completion",
                "present_in_both_selected_inventories": False,
                "native_absence_proofs": [_verify_absent_frequency_review_text(archive) for archive in contexts],
                "fingerprint_fields_dropped": []}
        text_files = set()
    artifacts, failures = [], list(metadata["differences"])
    for relative in sorted(inventories[0]):
        left, right = (inventory[relative] for inventory in inventories)
        try:
            suffix = left.suffix.lower()
            if suffix == ".npz":
                proof = _compare_npz(left, right, *contexts)
            elif suffix == ".fif" or left.name.endswith(".fif.gz"):
                proof = _compare_fif(left, right, *contexts)
            elif suffix == ".xlsx":
                proof = compare_workbook_provenance(left, right, *contexts, *maps)
            elif (suffix in {".json", ".fpvs"} or relative == ".fpvs_processing/processing_runs.jsonl"
                  or relative in native_manifest_files):
                _require(relative in metadata_files, f"Selected stable metadata was not compared: {relative}")
                proof = {"kind": "stable_typed_metadata", "proof_in": "stable_metadata"}
            elif relative in text_files:
                proof = {"kind": "bound_frequency_review_text", "proof_in": "frequency_review_text"}
            else:
                _require(contexts[0].sha(left) == contexts[1].sha(right), f"File bytes differ: {relative}")
                proof = {"kind": "opaque_exact_bytes"}
            artifacts.append({"file": relative, "baseline_sha256": contexts[0].sha(left),
                              "candidate_sha256": contexts[1].sha(right), **proof})
        except (ParityError, OSError, ValueError) as exc:
            failures.append({"file": relative, "error": str(exc)})
    for archive in contexts:
        _verify_remaining_runner_claims(archive)
    for side in ("baseline", "candidate"):
        for unresolved in identity[side + "_unverified_runtime_bindings"]:
            failures.append({"side": side, **unresolved, "error": "Exact runtime-binding preimage was not archived"})
    return {"status": "failed" if failures else "passed", "scope": "all selected actual scientific payloads and stable artifacts",
            "baseline": str(roots[0]), "candidate": str(roots[1]), "policy": policy,
            "file_count": len(inventories[0]), "artifacts": artifacts, "failures": failures,
            "excluded_files": excluded, "identity_proof": identity, "stable_metadata": metadata,
            "frequency_review_text": text, "numerical_tolerance": None,
            "scientific_fingerprint_fields_dropped": []}


def compare_archives(baseline: Path, candidate: Path, policy: dict | None = None) -> dict:
    """Return a serializable proof receipt; any unknown difference raises."""
    policy = policy or {}
    _require(set(policy) <= {"rules", "exclude_files", "baseline_origin_root", "candidate_origin_root",
                             "baseline_source_root", "candidate_source_root"}, "Unknown policy fields")
    rules = policy.get("rules", [])
    for rule in rules:
        _require(set(rule) == {"file", "pointer", "kind"}, "Normalization rule must contain file/pointer/kind")
    contexts = [Archive(Path(root).resolve(), Path(origin).resolve() if origin else None)
                for root, origin in ((baseline, policy.get("baseline_origin_root")),
                                     (candidate, policy.get("candidate_origin_root")))]
    a, b = contexts
    for archive, prefix in ((a, "baseline"), (b, "candidate")):
        source = policy.get(f"{prefix}_source_root")
        if source is not None:
            _require(Path(source).is_absolute(), "Execution source root must be absolute")
            archive.execution_source_root = Path(source).resolve()
    excluded = []

    def inventory(archive):
        _require(archive.root.is_dir(), f"Missing archive directory: {archive.root}")
        result = {}
        for path in sorted(archive.root.rglob("*")):
            _require(not path.is_symlink(), f"Symbolic links are not accepted: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(archive.root).as_posix()
            if any(fnmatch.fnmatchcase(relative, pattern) for pattern in policy.get("exclude_files", [])):
                excluded.append({"root": str(archive.root), "file": relative})
            else:
                result[relative] = path
        return result

    first, second = inventory(a), inventory(b)
    _require(first.keys() == second.keys(), f"Artifact inventories differ; baseline-only={sorted(first.keys() - second.keys())}, candidate-only={sorted(second.keys() - first.keys())}")
    _require(bool(first), "No artifacts selected")
    # Validate each side's binding before looking at cross-archive equivalence.
    for archive, files in ((a, first), (b, second)):
        for relative, path in files.items():
            if path.suffix.lower() == ".fpvs":
                _verify_native(path, archive)
            if path.suffix.lower() in {".json", ".fpvs"}:
                _verify_bindings(_decode_audit_scalars(_json_load(path)), path, archive)
    proofs = []
    for relative, left in first.items():
        right = second[relative]
        suffix = left.suffix.lower()
        entry = {"file": relative, "baseline_sha256": a.sha(left), "candidate_sha256": b.sha(right)}
        if suffix == ".npz":
            entry.update(_compare_npz(left, right, a, b))
        elif suffix in {".fif", ".gz"} and (suffix == ".fif" or left.name.endswith(".fif.gz")):
            entry.update(_compare_fif(left, right, a, b))
        elif suffix == ".xlsx":
            entry.update(kind="xlsx", members=_zip_members(left, right, xlsx=True))
        elif suffix in {".json", ".fpvs"}:
            aa = _normalize_json(_json_load(left), relative, a, rules)
            bb = _normalize_json(_json_load(right), relative, b, rules)
            _require(_exact(aa) == _exact(bb), f"JSON content/order/float bits differ: {relative}")
            entry.update(kind="json", exact_order_and_float_bits=True)
        else:
            _require(a.sha(left) == b.sha(right), f"File bytes differ: {relative}")
            entry.update(kind="opaque_exact_bytes")
        proofs.append(entry)
    for archive in contexts:
        _verify_remaining_runner_claims(archive)
        _verify_span_plan_references(archive)
    return {"status": "passed", "baseline": str(a.root), "candidate": str(b.root),
            "policy": policy, "file_count": len(proofs), "artifacts": proofs, "excluded_files": excluded,
            "baseline_binding_proofs": a.proofs, "candidate_binding_proofs": b.proofs,
            "baseline_normalizations": a.normalizations, "candidate_normalizations": b.normalizations,
            "numerical_tolerance": None, "fingerprint_hash_fields_dropped": []}


def self_test() -> dict:
    """Small negative controls exercise numerical and metadata failure modes."""
    parent = (ROOT / "test_tmp").resolve()
    _require(parent.is_relative_to(ROOT), "Self-test scratch root escapes workspace")
    parent.mkdir(parents=True, exist_ok=True)
    checked = []
    with tempfile.TemporaryDirectory(prefix="pipeline-parity-", dir=parent) as temporary:
        root = Path(temporary).resolve()
        _require(root.is_relative_to(parent), "Self-test scratch directory escapes workspace")
        a, b = root / "a", root / "b"
        a.mkdir()
        b.mkdir()

        def identical(values):
            np.savez(a / "signal.npz", samples=values, metadata_json=np.asarray('{"method":"frozen"}'))
            shutil.copyfile(a / "signal.npz", b / "signal.npz")

        def rejects(name):
            try:
                compare_archives(a, b)
            except (ParityError, ValueError, OSError):
                checked.append(name)
            else:
                raise AssertionError(f"Comparator failed to reject {name}")

        values = np.array([[0.0, -0.0], [1.0, np.nan]], dtype=np.float64)
        identical(values)
        compare_archives(a, b)
        checked.append("identical_nan_and_signed_zero_pass")
        for name, changed in (
            ("last_bit", np.array([[0.0, -0.0], [np.nextafter(1.0, 2.0), np.nan]])),
            ("signed_zero", np.array([[-0.0, -0.0], [1.0, np.nan]])),
            ("dtype", values.astype(np.float32)),
            ("fortran_order", np.asfortranarray(values)),
        ):
            identical(values)
            np.savez(b / "signal.npz", samples=changed, metadata_json=np.asarray('{"method":"frozen"}'))
            rejects(name)
        identical(np.asarray(1.0))
        np.savez(b / "signal.npz", samples=np.asarray([1.0]), metadata_json=np.asarray('{"method":"frozen"}'))
        rejects("scalar_vs_single_element_vector")
        changed = values.view(np.uint64).copy()
        changed[1, 1] ^= np.uint64(1)
        identical(values)
        np.savez(b / "signal.npz", samples=changed.view(np.float64), metadata_json=np.asarray('{"method":"frozen"}'))
        rejects("nan_payload")
        identical(values)
        np.savez(b / "signal.npz", samples=values, metadata_json=np.asarray('{"method":"changed"}'))
        rejects("scientific_metadata")
        identical(values)
        np.savez(b / "signal.npz", metadata_json=np.asarray('{"method":"frozen"}'), samples=values)
        rejects("npz_member_order")
        identical(values)
        (a / "packet.json").write_text('{"elapsed_ms":1,"value":-0.0}', encoding="utf-8")
        (b / "packet.json").write_text('{"elapsed_ms":2,"value":-0.0}', encoding="utf-8")
        rejects("unlisted_runtime_field")
        policy = {"rules": [{"file": "packet.json", "pointer": "/elapsed_ms", "kind": "elapsed"}]}
        compare_archives(a, b, policy)
        checked.append("explicit_runtime_pointer_pass")
        (b / "extra.txt").write_text("extra", encoding="utf-8")
        rejects("extra_artifact")
        (b / "extra.txt").unlink()
        (b / "packet.json").write_text('{"elapsed_ms":1,"value":-0.0}', encoding="utf-8")
        (a / "bad.json").write_text('{"version":"parity_selftest_canonical_v1","value":1,"fingerprint":"' + "0" * 64 + '"}', encoding="utf-8")
        shutil.copyfile(a / "bad.json", b / "bad.json")
        rejects("identically_stale_fingerprint")
        (a / "bad.json").unlink()
        (b / "bad.json").unlink()
        from openpyxl import Workbook

        workbook = Workbook()
        workbook.active.append(["Condition", 1.25])
        workbook.properties.created = datetime(2026, 1, 1, tzinfo=timezone.utc)
        workbook.save(a / "table.xlsx")
        shutil.copyfile(a / "table.xlsx", b / "table.xlsx")
        compare_archives(a, b)
        workbook.active["B1"] = np.nextafter(1.25, 2.0)
        # Excel serializes too few digits to preserve this particular one-bit
        # change; a clearly different cell is the ZIP worksheet negative control.
        workbook.active["B1"] = 1.250001
        workbook.save(b / "table.xlsx")
        rejects("worksheet_numeric_cell")
        shutil.copyfile(a / "table.xlsx", b / "table.xlsx")
        with zipfile.ZipFile(a / "table.xlsx") as source, zipfile.ZipFile(b / "table.xlsx", "w") as target:
            for info in source.infolist():
                content = source.read(info.filename)
                if info.filename == "docProps/core.xml":
                    changed_core = content.replace(b"2026-01-01T00:00:00Z", b"2026-02-03T01:02:03Z")
                    _require(changed_core != content, "Self-test must change a real core timestamp")
                    content = changed_core
                target.writestr(info, content)
        _require(_sha(a / "table.xlsx") != _sha(b / "table.xlsx"), "Self-test timestamp control must change container bytes")
        compare_archives(a, b)
        checked.append("xlsx_only_core_timestamps_pass")
        shutil.copyfile(a / "table.xlsx", b / "table.xlsx")
        import pandas as pd
        from Main_App.io.result_manifest import write_result_manifest
        from Main_App.io.spectral_data import SPECTRAL_SHEET_NAMES, write_spectral_companion

        anchor = a / "recording_Condition_Results.fpvs"
        descriptor = write_spectral_companion(anchor, {
            SPECTRAL_SHEET_NAMES[0]: pd.DataFrame({"Electrode": ["Fp1", "Fp2"], "0.0_Hz": [1.0, 2.0],
                                                "1.0_Hz": [3.0, 4.0], "2.0_Hz": [5.0, 6.0]}),
        })
        write_result_manifest(anchor, sheet_names=descriptor["sheets"], spectral_companion=descriptor, condition_companion=None)
        shutil.copyfile(anchor, b / anchor.name)
        shutil.copyfile(a / descriptor["path"], b / descriptor["path"])
        compare_archives(a, b)
        checked.append("native_schema_and_hash_bindings_pass")
        from Main_App.processing.full_fft_provenance import _grid_identity

        grid = _grid_identity(["Electrode", "0.0_Hz", "1.0_Hz", "2.0_Hz"], oddball_frequency_hz=1.0)
        grid_payload = {"fingerprint": grid.fingerprint, "frequency_resolution_hz": grid.frequency_resolution_hz,
                        "upper_frequency_hz": grid.upper_frequency_hz, "frequency_column_count": grid.frequency_column_count}
        provenance = {"oddball_frequency_hz": 1.0, "grid": grid_payload}
        (a / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        shutil.copyfile(a / "provenance.json", b / "provenance.json")
        compare_archives(a, b)
        checked.append("fullfft_ordered_header_recipe_pass")
        provenance["grid"]["upper_frequency_hz"] = 3.0
        (b / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        rejects("fullfft_grid_stale_summary")
        shutil.copyfile(a / "provenance.json", b / "provenance.json")
        (a / "references.json").write_text(json.dumps({"fingerprint": "1" * 64, "domain_summary": "reference"}), encoding="utf-8")
        shutil.copyfile(a / "references.json", b / "references.json")
        compare_archives(a, b)
        checked.append("opaque_fingerprint_preserved_exact_pass")
        (b / "references.json").write_text(json.dumps({"fingerprint": "2" * 64, "domain_summary": "reference"}), encoding="utf-8")
        rejects("opaque_fingerprint_difference")
        shutil.copyfile(a / "references.json", b / "references.json")
        core = {"version": "parity_selftest_canonical_v1", "value": -0.0}
        core["fingerprint"] = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        core["value"] = {"float64_bits": "8000000000000000", "display": "-0.0"}
        (a / "runner.json").write_text(json.dumps(core), encoding="utf-8")
        shutil.copyfile(a / "runner.json", b / "runner.json")
        compare_archives(a, b)
        checked.append("runner_float_bits_recipe_pass")
        core["value"]["display"] = "0.0"
        (b / "runner.json").write_text(json.dumps(core), encoding="utf-8")
        rejects("runner_float_bits_display_mismatch")
        shutil.copyfile(a / "runner.json", b / "runner.json")
        with (b / descriptor["path"]).open("ab") as stream:
            stream.write(b"tampered container")
        rejects("native_companion_binding_corruption")
        shutil.copyfile(a / descriptor["path"], b / descriptor["path"])
        import mne

        raw = mne.io.RawArray(np.arange(32, dtype=np.float64)[None, :] * 1e-6,
                              mne.create_info(["Fp1"], 128.0, "eeg"), verbose=False)
        raw.save(a / "signal_raw.fif", fmt="double", overwrite=True, verbose=False)
        raw.close()
        shutil.copyfile(a / "signal_raw.fif", b / "signal_raw.fif")
        compare_archives(a, b)
        checked.append("fif_container_samples_and_info_pass")
        changed_raw = mne.io.read_raw_fif(a / "signal_raw.fif", preload=True, verbose=False)
        changed_raw.info["bads"] = ["Fp1"]
        changed_raw.save(b / "signal_raw.fif", fmt="double", overwrite=True, verbose=False)
        changed_raw.close()
        rejects("fif_scientific_info")
        # Canonical identities may differ because their own generated anchor
        # mtimes differ. Prove the dependency cascade, while numerical changes
        # and opaque reference changes must remain unmapped.
        stamp = anchor.stat().st_mtime_ns
        os.utime(b / anchor.name, ns=(stamp + 10_000_000, stamp + 10_000_000))

        def identity_context(directory, number=1.0, unknown="same"):
            archive = Archive(directory)
            own_anchor = directory / anchor.name
            core = {"version": "parity_selftest_canonical_v1", "value": number,
                    "artifact": {"path": str(own_anchor), "size": own_anchor.stat().st_size,
                                 "mtime_ns": own_anchor.stat().st_mtime_ns, "sha256": _sha(own_anchor)}}
            # Use one original root so only generated mtimes differ; the physical
            # archived locations are resolved by the comparator's binding seam.
            core["artifact"]["path"] = str(a / anchor.name)
            archive.origin_root = a
            core["fingerprint"] = hashlib.sha256(json.dumps(
                core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            parent_core = {"version": "parity_selftest_canonical_v1", "child_fingerprint": core["fingerprint"],
                           "external_fingerprint": unknown}
            parent_core["fingerprint"] = hashlib.sha256(json.dumps(
                parent_core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            _verify_bindings({"child": core, "parent": parent_core}, directory / "identity.json", archive)
            return archive, core["fingerprint"], parent_core["fingerprint"]

        aa, child_a, parent_a = identity_context(a)
        bb, child_b, parent_b = identity_context(b)
        mapping = build_identity_correspondence(aa, bb)
        _require(mapping["baseline_map"][child_a] == mapping["candidate_map"][child_b]
                 and mapping["baseline_map"][parent_a] == mapping["candidate_map"][parent_b]
                 and not mapping["unmatched_canonical_identities"], "Generated-mtime cascade self-test failed")
        checked.append("verified_generated_mtime_fingerprint_cascade_pass")
        for label, number, opaque in (("identity_last_bit", np.nextafter(1.0, 2.0).item(), "same"),
                                      ("identity_opaque_reference", 1.0, "different")):
            bb, child_b, parent_b = identity_context(b, number, opaque)
            mapping = build_identity_correspondence(aa, bb)
            _require(parent_a not in mapping["baseline_map"] and parent_b not in mapping["candidate_map"],
                     f"Identity graph concealed {label}")
            checked.append(label)
        aa, _, parent_a = identity_context(a, -0.0)
        bb, _, parent_b = identity_context(b, 0.0)
        mapping = build_identity_correspondence(aa, bb)
        _require(parent_a not in mapping["baseline_map"] and parent_b not in mapping["candidate_map"],
                 "Identity graph concealed signed zero")
        checked.append("identity_signed_zero")
        stages = (root / "stage_a", root / "stage_b")
        stage_policy = {}
        for side, folder in zip(("baseline", "candidate"), stages):
            (folder / "benchmark_evidence").mkdir(parents=True)
            (folder / ".fpvs_processing").mkdir()
            stage_policy[side + "_origin_root"] = str(folder)
            source = folder / "frozen_source"
            (source / "src" / "Main_App").mkdir(parents=True)
            stage_policy[side + "_source_root"] = str(source)
            module = source / "src" / "Main_App" / "characterized.py"
            module.write_text("VALUE = 1\n" if side == "baseline" else "VALUE = 2\n", encoding="utf-8")
            source_inventory = [{"module": "Main_App.characterized", "relative_path": "src/Main_App/characterized.py", "sha256": _sha(module)}]
            if side == "candidate":
                extra = source / "src" / "Main_App" / "performance_helper.py"
                extra.write_text("HELPER = True\n", encoding="utf-8")
                source_inventory.append({"module": "Main_App.performance_helper", "relative_path": "src/Main_App/performance_helper.py", "sha256": _sha(extra)})
            moment = "2026-01-01T00:00:00Z" if side == "baseline" else "2026-02-01T00:00:00Z"
            (folder / "project.json").write_text(json.dumps({"generated_at": moment, "value": -0.0}), encoding="utf-8")
            before = folder / "benchmark_evidence" / "project_before_downstream.json"
            before.write_text(json.dumps({"generated_at": moment, "value": 1.0}), encoding="utf-8")
            (folder / "benchmark_evidence" / "receipt.json").write_text(json.dumps({
                "project_manifest_before_sha256": _sha(before),
                "project_manifest_after_sha256": _sha(folder / "project.json"),
                "production_source_inventory": source_inventory,
            }), encoding="utf-8")
            (folder / ".fpvs_processing" / "processing_runs.jsonl").write_text(json.dumps({
                "timestamp": moment, "processing_fingerprint_version": "processing_fingerprint_v13_v3_trigger_alignment",
                "value": 1.0,
            }) + "\n", encoding="utf-8")
        stage_identity = compare_identity_archives(*stages, stage_policy)
        stage_metadata = compare_runtime_metadata(*stages, stage_policy, stage_identity)
        _require(stage_metadata["status"] == "passed", "Bound intermediate-manifest substitution failed")
        checked.append("archived_intermediate_manifest_binding_and_runtime_content_pass")
        _require(len(stage_metadata["independently_verified_execution_provenance"]) == 3,
                 "Execution-source additions/digests were not independently inventoried")
        checked.append("changed_execution_source_and_added_helper_inventory_pass")
        checked.append("native_run_journal_scoped_timestamp_pass")
        receipt = stages[1] / "benchmark_evidence" / "receipt.json"
        original_receipt = receipt.read_text(encoding="utf-8")
        for control in ("execution_source_stale_sha", "execution_source_module_path", "execution_source_duplicate_module"):
            content = _json_load(receipt)
            rows = content["production_source_inventory"]
            if control == "execution_source_stale_sha":
                rows[0]["sha256"] = "0" * 64
            elif control == "execution_source_module_path":
                rows[0]["relative_path"] = rows[1]["relative_path"]
                rows[0]["sha256"] = rows[1]["sha256"]
            else:
                rows.append(dict(rows[0]))
            receipt.write_text(json.dumps(content), encoding="utf-8")
            try:
                compare_runtime_metadata(*stages, stage_policy, stage_identity)
            except ParityError:
                checked.append(control)
            else:
                raise AssertionError(f"Comparator concealed {control}")
            receipt.write_text(original_receipt, encoding="utf-8")
        journal = stages[1] / ".fpvs_processing" / "processing_runs.jsonl"
        original_journal = journal.read_text(encoding="utf-8")
        content = _stable_document(journal)[0]
        content["value"] = np.nextafter(1.0, 2.0).item()
        journal.write_text(json.dumps(content) + "\n", encoding="utf-8")
        stage_identity = compare_identity_archives(*stages, stage_policy)
        changed = compare_runtime_metadata(*stages, stage_policy, stage_identity)
        _require(changed["status"] == "failed"
                 and {entry["file"] for entry in changed["differences"]} == {".fpvs_processing/processing_runs.jsonl"},
                 "Comparator concealed a processing-run journal last-bit difference")
        checked.append("native_run_journal_last_bit")
        journal.write_text(original_journal, encoding="utf-8")
        before = stages[1] / "benchmark_evidence" / "project_before_downstream.json"
        before.write_text(json.dumps({"generated_at": "2026-02-01T00:00:00Z", "value": np.nextafter(1.0, 2.0).item()}), encoding="utf-8")
        try:
            compare_identity_archives(*stages, stage_policy)
        except ParityError:
            checked.append("intermediate_manifest_stale_sha")
        else:
            raise AssertionError("Comparator concealed a stale intermediate-manifest SHA")
        receipt = stages[1] / "benchmark_evidence" / "receipt.json"
        content = _json_load(receipt)
        content["project_manifest_before_sha256"] = _sha(before)
        receipt.write_text(json.dumps(content), encoding="utf-8")
        stage_identity = compare_identity_archives(*stages, stage_policy)
        try:
            compare_runtime_metadata(*stages, stage_policy, stage_identity)
        except ParityError:
            checked.append("intermediate_manifest_last_bit")
        else:
            raise AssertionError("Comparator concealed an intermediate-manifest last-bit difference")
    return {"status": "passed", "negative_and_positive_controls": checked}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, nargs="?")
    parser.add_argument("candidate", type=Path, nargs="?")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--identity-proof", action="store_true",
                        help="Verify canonical fingerprint preimages and the narrow runtime identity cascade")
    parser.add_argument("--full-proof", action="store_true",
                        help="Combine actual scientific bytes, bound provenance and every stable artifact")
    parser.add_argument("--prepared-checkpoints", action="store_true",
                        help="Compare every native prepared checkpoint by its original source namespace")
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            report = self_test()
        else:
            if args.baseline is None or args.candidate is None:
                parser.error("baseline and candidate directories are required")
            if args.prepared_checkpoints:
                _require(not args.identity_proof and not args.full_proof and args.policy is None,
                         "Prepared proof has no implicit normalization policy")
                report = compare_prepared_checkpoints(args.baseline, args.candidate)
            else:
                _require(not (args.identity_proof and args.full_proof), "Choose one comparison scope")
                _require(not args.full_proof or args.policy is not None, "Full proof requires an explicit runtime/source policy")
                comparator = compare_full_archives if args.full_proof else compare_identity_archives if args.identity_proof else compare_archives
                report = comparator(args.baseline, args.candidate, _json_load(args.policy) if args.policy else None)
    except (ParityError, OSError, ValueError) as exc:
        report = {"status": "failed", "error": str(exc), "numerical_tolerance": None}
    if args.report:
        target = args.report.resolve()
        for protected in (args.baseline, args.candidate):
            if protected is not None:
                _require(not target.is_relative_to(protected.resolve()), "Report must not modify an input archive")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "file_count": report.get("file_count"), "error": report.get("error"),
                      "self_test_controls": report.get("negative_and_positive_controls")}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
