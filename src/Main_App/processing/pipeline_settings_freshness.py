"""Processing-setting receipts that cannot be satisfied by post-processing alone.

The optional setup transaction enables this guard when numerical settings change.
Existing projects retain their historical processing fingerprint and reuse policy.
Receipts belong to each recording, so one new Single run cannot release the rest.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from Main_App.processing.pipeline_plan import fingerprint_settings
from Main_App.projects.experimental_qc_settings import normalize_experimental_qc_settings
from Main_App.projects.frequency_protocol import FrequencyProtocol, normalize_frequency_protocol
from Main_App.projects.hardware import brain_products_qc_defaults, hardware_supports_calibrated_qc, resolve_hardware
from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings

REQUIREMENT_KEY = "pipeline_setup_requirements"
RECEIPT_KEY = "pipeline_settings_identity"
REASON = "Processing pipeline settings changed. Run Processing before using existing results."

# Review decisions, per-recording exclusions and downstream harmonic settings have
# their own identity/release contracts. Preflight may add these during a run.
_NON_PIPELINE_KEYS = frozenset({
    "experimental_ram_preload", "max_parallel_workers_override",
    "hardware_confirmed", "hardware_selection_source",
    "removed_electrode_detection_choice_schema_version",
    "removed_electrode_detection_choice_status", "removed_electrode_detection_choice_source",
    "interpolation_burden_review_decisions", "kurtosis_review_decisions_by_recording",
    "manual_removed_electrodes", "manual_removed_electrodes_by_recording",
    "manual_excluded_participants", "manual_excluded_recordings",
    "manual_excluded_participant_conditions", "manual_excluded_recording_conditions",
})
_DOWNSTREAM_PREFIXES = ("harmonic_", "group_significant_", "fixed_harmonic_")
_QC_KEYS = (
    "raw_signal_screening_enabled", "kurtosis_screening_enabled",
    "raw_spectral_screening", "condition_specific_interpolation_enabled",
    "kurtosis_review_auto_interpolate_extreme",
)


class PipelineSettingsChangedError(ValueError):
    """A contributing recording predates the selected processing settings."""


def pipeline_settings_identity(manifest: Mapping) -> str:
    """Canonical identity of setup-owned scientific choices, not confirmation."""
    preprocessing = fingerprint_settings(normalize_preprocessing_settings(manifest.get("preprocessing")))
    preprocessing["hardware_platform"] = resolve_hardware(preprocessing).platform
    preprocessing = {
        key: value for key, value in preprocessing.items()
        if key not in _NON_PIPELINE_KEYS and not key.startswith(_DOWNSTREAM_PREFIXES)
    }
    raw_protocol = manifest.get("frequency_protocol")
    protocol = (FrequencyProtocol.confirmation_required() if raw_protocol is None
                else normalize_frequency_protocol(raw_protocol)).canonical_payload()
    for key in ("status", "oddball_input_mode", "expected_analyzed_oddball_cycles_source", "oddball_marker_code_source"):
        protocol.pop(key, None)
    qc_settings = normalize_experimental_qc_settings(manifest.get("experimental_qc"))
    if "experimental_qc" not in manifest and not hardware_supports_calibrated_qc(preprocessing):
        qc_settings = brain_products_qc_defaults(qc_settings)
    qc = qc_settings.to_manifest()
    payload = {
        "version": 1, "preprocessing": preprocessing, "frequency_protocol": protocol,
        "experimental_qc": {key: qc[key] for key in _QC_KEYS},
    }
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def project_pipeline_settings_identity(project) -> str:
    return pipeline_settings_identity({
        "preprocessing": getattr(project, "preprocessing", {}),
        "frequency_protocol": getattr(project, "frequency_protocol", None),
        "experimental_qc": getattr(project, "experimental_qc_settings", None),
    })


def apply_pipeline_setup_freshness(data: dict, previous_manifest: Mapping) -> bool:
    """Patch freshness inside the caller's single settings-save transaction."""
    identity = pipeline_settings_identity(data)
    if identity == pipeline_settings_identity(previous_manifest):
        return False
    now = datetime.now(UTC).isoformat()
    tools = deepcopy(dict(data.get("tools") or {}))
    processing = deepcopy(dict(tools.get("processing") or {}))
    processing[REQUIREMENT_KEY] = {"version": 1, "settings_identity": identity}
    provenance = processing.get("full_fft_provenance")
    if isinstance(provenance, Mapping):
        processing["full_fft_provenance"] = {
            **deepcopy(dict(provenance)), "status": "stale", "stale_reason": REASON, "stale_at": now,
        }
    qc = deepcopy(dict(tools.get("frequency_domain_qc") or {}))
    qc.update(downstream_outputs_stale=True, stale_reason=REASON, stale_at=now)
    tools.update(processing=processing, frequency_domain_qc=qc)
    data["tools"] = tools
    return True


def pipeline_settings_requirement_enabled(manifest: Mapping) -> bool:
    tools = manifest.get("tools") or {}
    processing = tools.get("processing") or {}
    marker = processing.get(REQUIREMENT_KEY)
    if marker is None:
        return False
    if (not isinstance(marker, Mapping) or type(marker.get("version")) is not int
            or marker.get("version") != 1 or not isinstance(marker.get("settings_identity"), str)
            or len(marker["settings_identity"]) != 64):
        raise PipelineSettingsChangedError("Processing setup freshness metadata is invalid. Run Processing again.")
    return True


def require_current_pipeline_settings(
    project_root: str | Path, *, ledger: Mapping | None = None,
    required_processing_ids=None, manifest: Mapping | None = None,
) -> None:
    """Require each active contribution's immutable processing-time receipt."""
    root = Path(project_root)
    required_processing_ids = tuple(required_processing_ids or ())
    if manifest is None:
        try:
            manifest = json.loads((root / "project.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
    if not isinstance(manifest, Mapping):
        raise PipelineSettingsChangedError("Project settings are invalid.")
    if not pipeline_settings_requirement_enabled(manifest):
        return
    from Main_App.processing.processing_ledger import _preprocessing_qc_required_entries, load_ledger

    state = load_ledger(root) if ledger is None else ledger
    entries = state.get("entries")
    if not isinstance(entries, Mapping) or not entries:
        raise PipelineSettingsChangedError(REASON)
    from Main_App.projects import project_recording_context_from_manifest

    context = project_recording_context_from_manifest(root, manifest)
    registered = (
        {row.recording_id: row.participant_id for row in context.recordings}
        if context.is_repeated_session else
        {row.participant_id: row.participant_id for row in context.participants}
    )
    required = set(registered) | set(required_processing_ids or ())
    # Missing and failed entries must not disappear from the contributor check.
    # The existing helper still applies current whole-owner/condition exclusions.
    checked_entries = {str(key): dict(value) for key, value in entries.items() if isinstance(value, Mapping)}
    folded = {key.casefold() for key in checked_entries}
    for identity in required:
        if str(identity).casefold() not in folded:
            checked_entries[str(identity)] = {
                "participant_id": registered.get(identity, identity), "status": "completed",
            }
    for value in checked_entries.values():
        if value.get("status") not in {"completed", "excluded"}:
            value["status"] = "completed"
            value.pop(RECEIPT_KEY, None)
    expected = pipeline_settings_identity(manifest)
    mismatches = [str(identity) for identity, entry in _preprocessing_qc_required_entries(
        root, manifest, checked_entries, required_processing_ids,
    ) if entry.get(RECEIPT_KEY) != expected]
    if mismatches:
        raise PipelineSettingsChangedError(
            "Processing pipeline settings changed for " + ", ".join(mismatches)
            + ". Run Processing again before continuing post-processing or analysis."
        )
