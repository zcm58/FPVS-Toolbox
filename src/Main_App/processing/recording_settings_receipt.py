"""Per-recording settings and review identities for incremental GUI processing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from Main_App.processing.processing_controller import RawFileInfo


_PARTICIPANT_SETTINGS = {
    "manual_removed_electrodes", "manual_excluded_participants",
    "manual_excluded_participant_conditions",
}
_RECORDING_SETTINGS = {
    "manual_removed_electrodes_by_recording", "manual_excluded_recordings",
    "manual_excluded_recording_conditions", "kurtosis_review_decisions_by_recording",
}
# These are supplied by preflight for the files actually reviewed on this run.
# Missing current evidence can reuse the original reviewed plan. Present evidence
# must agree with the corresponding original decision, even for just one file.
_REVIEW_OWNERS = {
    "_fpvs_preflight_event_plans_by_file": "path",
    "_fpvs_marker_review_decisions_by_file": "path",
    "_fpvs_preflight_recording_not_started_files": "path",
    "_fpvs_removed_electrode_review_by_pid": "participant",
    "_fpvs_removed_electrode_review_by_recording": "recording",
}

_AFTER_PLAN_FIELDS = {
    "_fpvs_expected_plan_fingerprint", "_fpvs_expected_plan_run_id", "_fpvs_grouped_project",
    "_fpvs_processing_fingerprint", "_fpvs_processing_fingerprint_version",
    "_fpvs_output_group_by_file", "_fpvs_participant_id_by_file", "_fpvs_recording_id_by_file",
    "_fpvs_session_id_by_file", "_fpvs_session_label_by_file", "_fpvs_visit_index_by_file",
    "_fpvs_days_from_baseline_by_file", "_fpvs_output_stem_by_file", "_fpvs_group_id_by_file",
}


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _select(value: Any, owners: set[str]) -> Any:
    if isinstance(value, Mapping):
        return {key: item for key, item in value.items() if str(key).casefold() in owners}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, str)):
        return [item for item in value if str(item).casefold() in owners]
    return value  # Preserve unexpected representations in the identity.


def recording_settings_receipts(payload: Mapping, files: Sequence[RawFileInfo]) -> dict[str, dict]:
    """Hash common numerical inputs once and bind owner-scoped settings separately."""
    common = dict(payload)
    scoped = {}
    review = {}
    for section in ("settings", "project_preprocessing"):
        local = dict(payload[section])
        scoped[section] = {
            key: local.pop(key) for key in sorted(_PARTICIPANT_SETTINGS | _RECORDING_SETTINGS)
            if key in local
        }
        if section == "settings":
            review = {key: local.pop(key) for key in _REVIEW_OWNERS if key in local}
        common[section] = local
    # A different acquisition design or condition schema is deliberately included
    # in the common identity until the per-record interpretation can be proven.
    shared_digest = _digest(common)
    receipts = {}
    for info in files:
        participant = {info.subject_id.casefold()}
        recording = {info.processing_id.casefold()}
        selections = {
            section: {key: _select(value, participant if key in _PARTICIPANT_SETTINGS else recording)
                      for key, value in fields.items()}
            for section, fields in scoped.items()
        }
        source_path = Path(info.path)
        path = {
            str(source_path.resolve()).casefold(), str(source_path).casefold(),
            source_path.name.casefold(), *recording,
        }
        owners = {"path": path, "participant": participant, "recording": recording}
        review_digests = {}
        for key, value in review.items():
            selected = _select(value, owners[_REVIEW_OWNERS[key]])
            if selected:
                review_digests[key] = _digest(selected)
        receipts[info.processing_id] = {
            "version": 1,
            "settings": _digest([shared_digest, selections, info.subject_id, info.processing_id, info.group]),
            "review": review_digests,
        }
    return receipts


def recording_settings_match(original: Any, requested: Mapping) -> bool:
    if not isinstance(original, Mapping) or original.get("version") != 1:
        return False
    previous_review = original.get("review")
    return (
        isinstance(previous_review, Mapping)
        and original.get("settings") == requested["settings"]
        and all(previous_review.get(key) == value for key, value in requested["review"].items())
    )


def recover_recording_settings(project: Any, ledger: Mapping, files: Sequence[RawFileInfo]) -> dict:
    """Recover historical settings only if their complete original run hash reproduces."""
    from Main_App.processing.condition_interpolation_executor import SNAPSHOT_VERSION
    from Main_App.processing.expected_processing_ledger import (
        EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY, ExpectedRecordingConditionPlan,
    )
    from Main_App.processing.processing_ledger import _processing_fingerprint_payload
    from Main_App.processing.recording_condition_outcomes import CELL_BLOCKED, load_recording_condition_outcomes

    root = Path(project.project_root)
    try:
        stored = json.loads((root / ".fpvs_processing" / "condition_interpolation_run.json").read_text(encoding="utf-8"))
        if stored["version"] != SNAPSHOT_VERSION or Path(stored["project_root"]) != root:
            return {}
        expected = ExpectedRecordingConditionPlan.from_payload(ledger[EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY])
        settings = {key: value for key, value in stored["settings"].items() if key not in _AFTER_PLAN_FIELDS}
        if (
            stored["processing_fingerprint"] != expected.processing_fingerprint
            or stored["settings"]["_fpvs_expected_plan_run_id"] != expected.run_id
        ):
            return {}
        historical = _processing_fingerprint_payload(project, settings, stored["event_map"])
        # Current project-wide inputs either reproduce the original hash, or only
        # per-owner settings have changed. The run snapshot carries their old values.
        if _digest(historical) != expected.processing_fingerprint:
            for key in _PARTICIPANT_SETTINGS | _RECORDING_SETTINGS:
                if key in settings and key in historical["project_preprocessing"]:
                    historical["project_preprocessing"][key] = settings[key]
            if _digest(historical) != expected.processing_fingerprint:
                return {}
        outcomes = load_recording_condition_outcomes(ledger)
        if not outcomes or outcomes.expected_plan_fingerprint != expected.fingerprint or outcomes.expected_plan_run_id != expected.run_id:
            return {}
        outcome_by_cell = {cell.cell_id: cell for cell in outcomes.cells}
        verified = {
            row.processing_id for row in expected.recordings
            if all(cell.cell_id in outcome_by_cell and outcome_by_cell[cell.cell_id].status != CELL_BLOCKED
                   and outcome_by_cell[cell.cell_id].expected_cell_fingerprint == cell.fingerprint for cell in row.cells)
            and ledger["entries"].get(row.processing_id, {}).get("processing_fingerprint") == expected.processing_fingerprint
        }
        return recording_settings_receipts(historical, [info for info in files if info.processing_id in verified])
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        # Optional historical evidence never upgrades an unverifiable recording.
        return {}


def restore_retained_reviews(settings: dict, previous_settings: Mapping, record: Mapping) -> list[str]:
    """Restore only original per-record inputs whose recorded digest still matches."""
    info = record["info"]
    raw = Path(info["path"])
    recording = str(record["processing_id"]).casefold()
    owners = {
        "participant": {str(info["subject_id"]).casefold()},
        "recording": {recording},
        "path": {str(raw.resolve()).casefold(), str(raw).casefold(), raw.name.casefold(), recording},
    }
    missing = []
    for key, digest in record["retained_review"].items():
        if key not in _REVIEW_OWNERS:
            missing.append(key)
            continue
        owner = owners[_REVIEW_OWNERS[key]]
        current = _select(settings.get(key), owner)
        if current:
            if _digest(current) != digest:
                missing.append(key)
            continue
        selected = _select(previous_settings.get(key), owner)
        if not selected or _digest(selected) != digest:
            missing.append(key)
            continue
        if isinstance(selected, dict):
            target = settings.setdefault(key, {})
            for identity, value in selected.items():
                target.setdefault(identity, value)
        elif isinstance(selected, list):
            target = settings.setdefault(key, [])
            target.extend(value for value in selected if value not in target)
        else:
            missing.append(key)
    return missing
