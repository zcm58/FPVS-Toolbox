"""Authorize unchanged source derivatives across verified incremental cohort releases."""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Mapping

from Main_App.processing.expected_processing_ledger import ExpectedRecordingConditionPlanError, ExpectedRecordingPlan
from Main_App.processing.incremental_recording_plan import _original_exports, _verified_history
from Main_App.processing.processing_ledger import _resolve_source_derivative_path, load_ledger
from Main_App.processing.recording_condition_outcomes import RecordingConditionOutcomeError

STAMP = "retained_source_derivative"
_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class RetainedSourceRecording:
    plan_fingerprint: str
    parent_fingerprint: str
    processing_fingerprint: str
    processing_version: str
    recording: ExpectedRecordingPlan
    entry: Mapping
    exports: Mapping

    @property
    def original_exports_sha256(self):
        pins = {label: receipt["fingerprint"] for label, receipt in self.exports.items()}
        encoded = json.dumps(pins, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def verified_retained_sources(ledger, processing_fingerprint, *, published):
    """Bind native expected rows, per-condition original export receipts and actual outcomes."""
    expected = ledger.get("expected_recording_condition_plan")
    if not isinstance(expected, Mapping) or not expected.get("retained_export_fingerprints"):
        return {}
    try:
        history = _verified_history(ledger)
    except (ValueError, TypeError, KeyError, ExpectedRecordingConditionPlanError, RecordingConditionOutcomeError):
        return {}
    if history is None:
        return {}
    plan, _outcome_plan, completed, outcomes = history
    if completed != published or plan.processing_fingerprint != processing_fingerprint:
        return {}
    entries = ledger.get("entries", {})
    plan_fingerprint = plan.fingerprint
    verified = {}
    for recording in plan.recordings:
        key = recording.processing_id
        pins = plan.retained_export_fingerprints.get(key)
        entry = entries.get(key)
        if (
            not pins
            or not isinstance(entry, Mapping)
            or entry.get("status") != "completed"
            or entry.get("source_derivative_status") != "complete"
            or entry.get("processing_fingerprint_version") != plan.processing_fingerprint_version
            or any(entry.get(field) != value for field, value in recording.raw_file_identity.items())
            or _original_exports(recording, entry, outcomes) != pins
        ):
            continue
        origin = {row["condition_label"]: row for row in entry["export_receipts"] if row["condition_label"] in pins}
        verified[key] = RetainedSourceRecording(
            plan_fingerprint,
            plan.retained_from_plan,
            processing_fingerprint,
            plan.processing_fingerprint_version,
            recording,
            entry,
            origin,
        )
    return verified


def source_commit_stamp(project_root, binding):
    """Pin the pre-existing committed manifest before advancing this skipped ledger entry."""
    if binding is None:
        return None
    entry = binding.entry
    try:
        path = _resolve_source_derivative_path(project_root, entry["source_derivative_manifest"])
        if entry["source_derivative_manifest"] not in entry["source_derivative_outputs"]:
            return None
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        prior = entry.get(STAMP, {})
        if not all(
            row.get("processing_fingerprint") == entry.get("processing_fingerprint") for row in binding.exports.values()
        ):
            # A second incremental transition can only continue the already pinned origin.
            if (
                not isinstance(prior, Mapping)
                or prior.get("version") != 1
                or binding.parent_fingerprint
                not in {prior.get("plan_fingerprint"), prior.get("parent_plan_fingerprint")}
                or prior.get("original_exports_sha256") != binding.original_exports_sha256
                or prior.get("manifest_sha256") != digest
                or prior.get("recording_id") != binding.recording.processing_id
                or prior.get("processing_fingerprint") != entry.get("processing_fingerprint")
            ):
                return None
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return None
    return {
        "version": 1,
        "plan_fingerprint": binding.plan_fingerprint,
        "parent_plan_fingerprint": binding.parent_fingerprint,
        "original_exports_sha256": binding.original_exports_sha256,
        "recording_id": binding.recording.processing_id,
        "processing_fingerprint": binding.processing_fingerprint,
        "manifest_sha256": digest,
    }


class RetainedSourceReader:
    """Only resolve the release ledger if a signed derivative predates the requested cohort."""

    def __init__(self, project_root, processing_fingerprint):
        self.root = Path(project_root)
        self.fingerprint = processing_fingerprint

    @cached_property
    def bindings(self):
        return verified_retained_sources(load_ledger(self.root), self.fingerprint, published=True)

    def accepts(self, expected, manifest_path, manifest_sha256, sidecar, fingerprint, version):
        try:
            binding = self.bindings.get(expected.participant_id)
            if binding is None:
                return False
            recording, entry = binding.recording, binding.entry
            origin = binding.exports.get(expected.condition_label)
            stamp = entry.get(STAMP)
            if (
                not isinstance(stamp, Mapping)
                or stamp.get("version") != 1
                or not isinstance(origin, Mapping)
                or entry["processing_fingerprint"] != self.fingerprint
                or version != binding.processing_version
                or stamp.get("processing_fingerprint") != self.fingerprint
                or stamp.get("plan_fingerprint") != binding.plan_fingerprint
                or stamp.get("parent_plan_fingerprint") != binding.parent_fingerprint
                or stamp.get("original_exports_sha256") != binding.original_exports_sha256
                or stamp.get("recording_id") != recording.processing_id
                or stamp.get("manifest_sha256") != manifest_sha256
                or _resolve_source_derivative_path(self.root, entry["source_derivative_manifest"]) != manifest_path
                or recording.participant_id != expected.participant_id
                or recording.group_id != expected.group_id
                or not any(
                    c.condition_label == expected.condition_label
                    and expected.condition_id in {str(c.condition_code), c.canonical_condition_id}
                    for c in recording.cells
                )
                or origin.get("status") != "written"
                or origin.get("participant_id") != recording.participant_id
                or origin.get("recording_id") != recording.processing_id
                or not all(
                    isinstance(origin.get(key), str) and _DIGEST.fullmatch(origin[key])
                    for key in ("source_analysis_span_plan_fingerprint", "target_analysis_span_plan_fingerprint")
                )
                or origin["processing_fingerprint"] != fingerprint
                or origin["processing_fingerprint_version"] != version
                or sidecar["source_signature"] != recording.raw_file_identity
            ):
                return False
            provenance = sidecar["processing"]["provenance"]
            return (
                provenance["processing_fingerprint"] == fingerprint
                and provenance["processing_fingerprint_version"] == version
                and provenance["geometry"] == origin["geometry"]
                and sidecar["geometry"] == entry["geometry"]
                and provenance["source_analysis_span_plan"]["fingerprint"]
                == origin["source_analysis_span_plan_fingerprint"]
                and provenance["realized_analysis_span_plan"]["fingerprint"]
                == origin["target_analysis_span_plan_fingerprint"]
            )
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            return False
