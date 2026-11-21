"""Explicit Studio handoff and acquisition identity for analysis reporting."""

from __future__ import annotations

import math
import hashlib
import re
from uuid import UUID


def scoped_identity(dataset_id: str, kind: str, original: object) -> str:
    value = str(original or "").strip().casefold()
    if not value:
        return ""
    digest = hashlib.sha256(f"{dataset_id}\n{kind}\n{value}".encode("utf-8")).hexdigest()
    return f"{kind}_{digest[:24]}"


def recording_identity(dataset_id: str, participant: object, recording: object, session: object, visit: object) -> dict:
    subject = scoped_identity(dataset_id, "subject", participant)
    if not subject:
        raise ValueError("Canonical reporting rows are missing participant identity.")
    visit_text = ""
    if visit not in (None, ""):
        if isinstance(visit, bool):
            raise ValueError("Canonical visit indices must be positive integers.")
        number = float(visit)
        if not math.isfinite(number) or not number.is_integer() or not 1 <= number <= 999_999_999:
            raise ValueError("Canonical visit indices must be positive integers.")
        visit_text = str(int(number))
    return {
        "subject_id": subject,
        "recording_id": scoped_identity(dataset_id, "recording", recording or participant),
        "session_id": scoped_identity(dataset_id, "session", session),
        "visit_id": visit_text,
    }


def reporting_scope(project, study_id: str = "") -> dict[str, str]:
    cohort = project.manifest.get("tools", {}).get("studio_cohort", {})
    handoff = cohort.get("website_study")
    if not isinstance(handoff, dict):
        raise ValueError("Import a Studio cohort with a verified OpenFPVS study connection.")
    required = ("experiment_id", "experiment_version", "protocol_sha256")
    if not all(isinstance(handoff.get(key), str) and handoff[key] for key in required):
        raise ValueError("The imported website protocol is incomplete.")
    if not re.fullmatch(r"[a-f0-9]{64}", handoff["protocol_sha256"]):
        raise ValueError("The imported website protocol fingerprint is invalid.")
    study = str(UUID(handoff["project_id"]))
    if study_id and study != study_id:
        raise ValueError("The saved connection belongs to another OpenFPVS study.")
    return {"study_id": study, **{key: handoff[key] for key in required}}


def acquisition_provenance(preprocessing: dict, native: float, analysis: float) -> dict:
    from Main_App.io.acquisition_metadata import recorded_channel_policy
    from Main_App.io.acquisition_profiles import resolve_acquisition_contract
    from Main_App.io.recorded_eeg_geometry import RECORDED_GEOMETRY_VERSION
    from Main_App.projects.hardware import resolve_hardware, unicorn_acquisition_profile

    try:
        native, analysis = float(native), float(analysis)
    except (TypeError, ValueError):
        raise ValueError("Reporting requires the recorded native and analysis sampling rates.") from None
    if any(not math.isfinite(value) or value <= 0 for value in (native, analysis)):
        raise ValueError("Reporting acquisition sampling rates are invalid.")
    platform = resolve_hardware(preprocessing).platform
    if platform in {"brain_products", "biosemi_active_three"}:
        policy = recorded_channel_policy(preprocessing, platform)
        return {
            "profile_id": platform,
            "profile_version": policy["version"],
            "montage_id": policy["electrode_montage"],
            "montage_version": RECORDED_GEOMETRY_VERSION,
            "event_decoder_id": "brainvision_marker_impulses" if platform == "brain_products" else "biosemi_edge",
            "event_decoder_version": policy["version"],
            "reference_policy": policy["initial_reference"],
            "reference": policy["initial_reference_channels"],
            "final_reference": "average",
            "native_sampling_rate_hz": native,
            "analysis_sampling_rate_hz": analysis,
        }
    contract = resolve_acquisition_contract(
        {"acquisition_profile": unicorn_acquisition_profile(preprocessing)} if platform == "unicorn" else preprocessing
    )
    configured_native = contract.profile.capabilities.native_sfreq
    if configured_native is not None and native != configured_native:
        raise ValueError("Observed native sampling rate differs from the acquisition profile.")
    reference = []
    if contract.reference_policy == "biosemi_exg_pair_then_average":
        from Main_App.io.acquisition_metadata import resolve_recording_contract

        reference = list(resolve_recording_contract(preprocessing).review_reference_pair)
    return {
        "profile_id": contract.profile.id,
        "profile_version": contract.profile.version,
        "montage_id": contract.montage.id,
        "montage_version": contract.montage.version,
        "event_decoder_id": contract.event_decoder.id,
        "event_decoder_version": contract.event_decoder.version,
        "reference_policy": contract.reference_policy,
        "native_sampling_rate_hz": native,
        "analysis_sampling_rate_hz": analysis,
        "reference": reference,
        "final_reference": "average",
    }


def reviewed_coverage(cohort: dict, analyzed_executions: set[str], excluded_recordings: set[str]) -> dict:
    scope = cohort["study_id"]
    coverage = {
        "source_study_id": scope,
        "roster_revision": cohort["roster_revision"],
        "included": [],
        "excluded": [],
        "awaiting_eeg": [],
    }
    included = set()
    for visit_id, visit in cohort["visits"].items():
        if not visit["in_source_roster"]:
            continue
        if visit_id in analyzed_executions and visit["decision"] == "matched":
            key = "included"
            included.add(visit_id)
        elif visit["decision"] == "excluded" or visit.get("recording_id") in excluded_recordings:
            key = "excluded"
        elif visit["decision"] == "awaiting_eeg":
            key = "awaiting_eeg"
        else:
            raise ValueError(
                "A reviewed visit has no released result or explicit exclusion. Review the cohort before sharing."
            )
        coverage[key].append(hashlib.sha256(f"openfpvs-visit-v1\n{scope}\n{visit_id}".encode()).hexdigest())
    if not included or analyzed_executions != included:
        raise ValueError("The current exported recordings do not belong to the reviewed study roster.")
    for key in ("included", "excluded", "awaiting_eeg"):
        coverage[key].sort()
        recorded = {
            hashlib.sha256(f"openfpvs-visit-v1\n{scope}\n{visit_id}".encode()).hexdigest()
            for visit_id in cohort["current_result"][key]
            if cohort["visits"][visit_id]["in_source_roster"]
        }
        if sorted(recorded) != coverage[key]:
            raise ValueError("Visit coverage differs from the accepted full-audit release.")
    return coverage
