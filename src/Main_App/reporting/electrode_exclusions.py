"""Freeze deidentified per-recording entered and effective electrode evidence."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import re
from Main_App.projects.studio_recording_identity import require_studio_source_hashes
from Main_App.reporting.provenance import recording_identity
from Main_App.processing.preprocessing_outcome import normalize_preprocessing_outcome


MAX_RECORDINGS = 4096


def electrode_labels(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) > 256:
        raise ValueError("Invalid electrode list.")
    labels = [str(label).upper() for label in value]
    if len(set(labels)) != len(labels) or any(
        not re.fullmatch(r"[A-Z0-9][A-Z0-9_.+-]{0,79}", label) for label in labels
    ):
        raise ValueError("Invalid or repeated electrode label.")
    return labels


def _current_entry(recording, plan, entries: Mapping) -> Mapping | None:
    matching = [entry for key, entry in entries.items() if str(key).casefold() == recording.processing_id.casefold()]
    if len(matching) > 1:
        raise ValueError("Processing electrode evidence repeats a recording identity.")
    entry = matching[0] if matching else None
    if not isinstance(entry, Mapping):
        return None
    if (
        entry.get("processing_fingerprint") != plan.processing_fingerprint
        or entry.get("processing_fingerprint_version") != plan.processing_fingerprint_version
        or entry.get("participant_id") != recording.participant_id
        or entry.get("recording_id") != recording.recording_id
        or entry.get("session_id") != recording.session_id
        or entry.get("visit_index") != recording.visit_index
        or any(entry.get(key) != value for key, value in recording.raw_file_identity.items())
    ):
        return None
    return entry


def _toolbox_evidence(entry: Mapping | None) -> dict:
    unknown = {
        "toolbox_manual_removed_electrodes": None,
        "toolbox_interpolation_requested": None,
        "toolbox_interpolated_electrodes": None,
        "toolbox_interpolation_status": "legacy_unknown",
    }
    if entry is None:
        return unknown
    outcome = normalize_preprocessing_outcome(entry)
    if not outcome.is_current or outcome.interpolation_status == "legacy_unknown":
        return unknown
    raw_outcome = entry.get("preprocessing_outcome", {})
    if any(
        raw_outcome.get(key) is None
        for key in ("interpolation_requested_channels", "interpolation_successful_channels")
    ):
        return unknown
    requested = electrode_labels(raw_outcome["interpolation_requested_channels"])
    successful = electrode_labels(raw_outcome["interpolation_successful_channels"])
    if outcome.interpolation_status != "succeeded" and successful:
        raise ValueError("Unsuccessful interpolation cannot claim repaired electrodes.")
    return {
        "toolbox_manual_removed_electrodes": electrode_labels(entry.get("raw_qc_manual_removed_channels")),
        "toolbox_interpolation_requested": requested,
        "toolbox_interpolated_electrodes": successful,
        "toolbox_interpolation_status": outcome.interpolation_status,
    }


def build_electrode_exclusions(project, plan, entries: Mapping, dataset_id: str, analyzed: set[str]) -> dict:
    """Include every current planned recording, including excluded/no-output cells."""
    recordings = plan.recordings
    if not recordings or len(recordings) > MAX_RECORDINGS:
        raise ValueError("Electrode evidence requires 1–4096 planned recordings.")
    cohort = project.manifest["tools"]["studio_cohort"]
    matched = {
        visit["recording_id"]: (key, visit)
        for key, visit in cohort["visits"].items()
        if visit["decision"] == "matched" and visit.get("in_source_roster")
    }
    output = []
    seen = set()
    for recording in recordings:
        identity = recording_identity(
            dataset_id, recording.participant_id, recording.recording_id, recording.session_id, recording.visit_index
        )
        if identity["recording_id"] in seen:
            raise ValueError("Electrode evidence repeats a recording identity.")
        seen.add(identity["recording_id"])
        entry = _current_entry(recording, plan, entries)
        if entry is None and identity["recording_id"] in analyzed:
            raise ValueError("A released recording is missing its matching processing ledger evidence.")
        match = matched.get(recording.recording_id)
        raw_path = Path(recording.raw_file_identity["raw_file"]) if match else None
        brain_products = raw_path is not None and raw_path.suffix.lower() in {".vhdr", ".bvrh"}
        if (match and brain_products and identity["recording_id"] not in analyzed and entry
                and entry.get("status") == "excluded" and not entry.get("source_sha256_by_file")
                and not match[1].get("source_sha256_by_file")):
            # A historical exclusion can predate any read of the signal.
            # Keep its roster coverage without attributing electrode evidence.
            match = entry = None
        source, execution, studio_channels = "unknown", None, None
        if match:
            key, visit = match
            sources = recording.raw_file_identity.get("recording_sources")
            if brain_products:
                approved = require_studio_source_hashes(visit.get("source_sha256_by_file"))
                if (not isinstance(sources, list) or len(sources) != len(approved)
                        or {row["path"] for row in sources if isinstance(row, Mapping)
                            and isinstance(row.get("path"), str)} != approved.keys()):
                    raise ValueError("The component files differ from the reviewed Studio recording.")
                if entry is None or entry.get("source_sha256_by_file") != approved:
                    if identity["recording_id"] in analyzed:
                        raise ValueError("Reprocess the recording to bind the results to the reviewed Studio visit.")
                    entry = None
            if (
                key != visit["execution_id"]
                or not re.fullmatch(r"[0-9a-f]{32}", key)
                or recording.participant_id != visit["participant_number"]
                or raw_path.resolve() != (Path(cohort["raw_folder"]) / visit["raw_file"]).resolve()
                or [recording.raw_file_identity["raw_size"], recording.raw_file_identity["raw_mtime_ns"]]
                != visit["file_identity"]
                or sources != visit.get("recording_sources")
            ):
                raise ValueError("A recording differs from the reviewed Studio visit. Review the cohort again.")
            source, execution = "completed_session", key
            studio_channels = electrode_labels(visit.get("manual_removed_electrodes"))
        output.append(
            {
                **identity,
                "studio_execution_id": execution,
                "studio_evidence_source": source,
                "studio_removed_electrodes": studio_channels,
                **_toolbox_evidence(entry),
            }
        )
    return {"schema_version": "1.0", "recordings": output}
