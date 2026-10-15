"""Describe actual native QC findings without creating or changing decisions."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import logging
import math
from pathlib import Path
import struct
import sys


LOG = logging.getLogger(__name__)
MAX_RECEIPT_BYTES = 1024 * 1024 * 1024


def read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ValueError("Native QC receipt exceeds the bounded local evidence limit")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Expected a native QC evidence object")
    return payload


def restore_float_bits(value):
    """Restore exact scalar floats from the observer representation, never arrays."""
    if isinstance(value, dict):
        if set(value) == {"float64_bits", "display"}:
            encoded = bytes.fromhex(value["float64_bits"])
            if len(encoded) != 8:
                raise ValueError("Malformed observer float bit proof")
            return struct.unpack(">d", encoded)[0]
        return {key: restore_float_bits(item) for key, item in value.items()}
    if isinstance(value, list):
        return [restore_float_bits(item) for item in value]
    return value


def describe_kurtosis(receipt: dict, project: dict) -> dict:
    from Main_App.processing.kurtosis_qc import (
        qualifies_for_experimental_kurtosis_auto,
        qualifies_for_experimental_kurtosis_auto_all,
        validate_kurtosis_review_decision_payload,
    )

    preprocessing = project["preprocessing"]
    auto_all = preprocessing.get("kurtosis_auto_interpolate_all") is True
    auto_extreme = project.get("experimental_qc", {}).get("kurtosis_review_auto_interpolate_extreme") is True
    saved = preprocessing.get("kurtosis_review_decisions_by_recording") or {}
    saved = {key.casefold(): value for key, value in saved.items()}
    rows, errors = [], []
    native = receipt.get("kurtosis_review")
    if native is None:
        raise ValueError("No completed native kurtosis preparation evidence is available")
    for result in native["results"]:
        if result.get("error"):
            errors.append({"recording_id": result["recording_id"], "error": result["error"]})
        for item in result["review_items"]:
            evidence_proof = item["evidence"]
            channel = next((row for row in evidence_proof["channels"] if row["channel"] == item["channel"]), None)
            if channel is None:
                raise ValueError("A native review item has no matching channel evidence")
            channel = restore_float_bits(channel)
            stored_channels = saved.get(item["recording_id"].casefold(), {})
            stored = next((value for key, value in stored_channels.items() if key.casefold() == item["channel"].casefold()), None)
            disposition = "manual_new"
            validation_error = None
            if stored is not None:
                evidence = restore_float_bits(evidence_proof)
                scope = {"source_file_path": str(Path(item["path"]).resolve()),
                         "participant_id": item["participant_id"], "recording_id": item["recording_id"],
                         "session_id": item["session_id"], "session_label": item["session_label"]}
                try:
                    validate_kurtosis_review_decision_payload(
                        stored, evidence=evidence, channel=item["channel"], review_scope=scope,
                        kurtosis_auto_interpolate_all=auto_all,
                    )
                except (TypeError, ValueError) as exc:
                    disposition, validation_error = "manual_stale", str(exc)
                else:
                    disposition = "existing_current"
            if disposition != "existing_current":
                if auto_all and qualifies_for_experimental_kurtosis_auto_all(channel):
                    disposition = "automatic_all"
                elif auto_extreme and qualifies_for_experimental_kurtosis_auto(channel):
                    disposition = "automatic_extreme"
            score = channel.get("signed_z")
            rows.append({"recording_id": item["recording_id"], "participant_id": item["participant_id"],
                         "session_id": item["session_id"], "channel": item["channel"], "disposition": disposition,
                         "signed_normalized_score": score if isinstance(score, (int, float)) and math.isfinite(score) else None,
                         "validity": channel.get("validity"), "evidence_fingerprint": evidence_proof.get("fingerprint"),
                         "existing_receipt_validation_error": validation_error})
    counts = Counter(row["disposition"] for row in rows)
    manual = [row for row in rows if row["disposition"] in {"manual_new", "manual_stale"}]
    return {"selected_recording_count": len(receipt["recordings"]), "native_result_count": len(native["results"]),
            "native_cancelled": native["cancelled"], "technical_errors": errors,
            "findings_count": len(rows), "recordings_with_findings": len({row["recording_id"] for row in rows}),
            "disposition_counts": dict(counts), "actual_manual_review_count": len(manual),
            "recordings_requiring_actual_manual_review": sorted({row["recording_id"] for row in manual}),
            "saved_auto_all_policy": auto_all, "saved_auto_extreme_policy": auto_extreme, "rows": rows,
            "interpretation": "Descriptions use production eligibility/receipt validators. No receipt, interpolation, exclusion, approval or timestamp is created."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--core-receipt", type=Path, required=True)
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.benchmark_root.resolve(strict=True)
    target = (args.output if args.output.is_absolute() else root / args.output).resolve(strict=False)
    project_root = args.project_root.resolve(strict=True)
    if not project_root.is_relative_to(root) or target == root or not target.is_relative_to(root):
        parser.error("Project/output paths must remain in the isolated benchmark root")
    if target.exists():
        raise FileExistsError(target)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.source_root.resolve(strict=True) / "src"))
    receipt = read_json(args.core_receipt)
    project = read_json(project_root / "project.json")
    description = describe_kurtosis(receipt, project)
    description.update(schema="pipeline_actual_review_summary_v1", core_status=receipt["status"],
                       core_receipt=str(args.core_receipt.resolve(strict=True)),
                       source_root=str(args.source_root.resolve(strict=True)),
                       interpolation_burden=receipt.get("interpolation_burden_review"),
                       interpolation_burden_note="Actual successful interpolation burden is unavailable before normal processing; no burden is inferred from preparation flags.")
    with args.core_receipt.open("rb") as stream:
        description["core_receipt_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(description, stream, indent=2, allow_nan=False)
        stream.write("\n")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    LOG.info("actual_qc_review_summary recordings=%d findings=%d manual=%d dispositions=%s path=%s",
             description["selected_recording_count"], description["findings_count"],
             description["actual_manual_review_count"], description["disposition_counts"], target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
