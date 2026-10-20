"""Interpret acquisition metadata before the shared numerical pipeline.

Manufacturer defaults, native recording semantics, qualification gates, and
historical provenance encodings are owned by this upstream boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

from Main_App.io.recording_contract import RecordingContract
from Main_App.processing.reference import apply_recorded_reference as apply_recorded_reference
from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    BIOSEMI64_COORDINATE_FINGERPRINT,
    BIOSEMI64_GEOMETRY_VERSION,
    BioSemi64GeometryError,
    attach_raw_biosemi64_geometry,
    biosemi64_geometry_identity,
    canonical_biosemi64_head_coordinates,
    read_raw_biosemi64_geometry,
)
from Main_App.io.recorded_eeg_geometry import (
    RECORDED_GEOMETRY_VERSION,
    attach_raw_recorded_geometry,
    read_raw_eeg_geometry,
    validate_raw_recorded_geometry,
)

BRAIN_PRODUCTS_PIPELINE_VERSION = "brain_products_recorded_eeg_v1"
ACTIVE_THREE_PIPELINE_VERSION = "biosemi_active_three_recorded_eeg_v1"
UNICORN_PIPELINE_VERSION = "unicorn_native_eeg_v1"
ACQUISITION_POLICY_ATTRIBUTE = "_fpvs_resolved_acquisition_policy"


ResolvedAcquisitionPolicy = RecordingContract
RECORDING_CONTRACT_ATTRIBUTE = "_fpvs_recording_contract"


def _resolve_policy(settings: Mapping[str, Any]) -> RecordingContract:
    """Resolve project acquisition facts once, before numerical processing.

    The source filename and native signal format have no authority here. The
    existing policies retain their historical numerical behavior
    and fingerprints, including the legacy EXG-pair fallback.
    """
    from Main_App.projects.hardware import HARDWARE_LABELS, resolve_hardware

    hardware = resolve_hardware(settings)
    if hardware.platform in {"brain_products", "biosemi_active_three"}:
        policy = recorded_channel_policy(settings, hardware.platform)
        encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"))
        return ResolvedAcquisitionPolicy(
            initial_reference_mode=policy["initial_reference"],
            initial_reference_channels=tuple(policy["initial_reference_channels"]),
            drop_reference_channels=policy["drop_reference_channels"],
            max_idx_keep=policy["max_idx_keep"], canonical_scalp_order=None,
            recorded_channel_geometry=True, kurtosis_screening_supported=False,
            strict_processing_errors=True, geometry_fingerprint=RECORDED_GEOMETRY_VERSION,
            acquisition_label=HARDWARE_LABELS[hardware.platform],
            marker_impulses=hardware.platform == "brain_products",
            acquisition_fingerprint=hashlib.sha256(encoded.encode()).hexdigest(),
            provenance_json=encoded,
        )
    if hardware.platform == "unicorn":
        from Main_App.io.acquisition_profiles import resolve_acquisition_contract
        from Main_App.projects.hardware import unicorn_acquisition_profile

        if not hardware.confirmed:
            raise ValueError("Confirm Unicorn hardware in this project's settings before processing.")
        if (settings.get("initial_reference", "recorded") not in {"recorded", "average_scalp"}
                or settings.get("initial_reference_channels") or settings.get("drop_reference_channels", False)):
            raise ValueError("Unicorn uses the eight-scalp average reference; recorded reference channel overrides are unavailable.")
        selected = resolve_acquisition_contract({"acquisition_profile": unicorn_acquisition_profile(settings)})
        policy = {
            "version": UNICORN_PIPELINE_VERSION, "hardware_platform": hardware.platform,
            "acquisition_contract": selected.identity, "acquisition_contract_fingerprint": selected.fingerprint,
            "reference_policy": "average_scalp",
            "recording_event_policy": deepcopy(settings.get("recording_event_policy") or {}),
        }
        encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"))
        return ResolvedAcquisitionPolicy(
            initial_reference_mode="recorded", initial_reference_channels=(),
            drop_reference_channels=False, max_idx_keep=None,
            canonical_scalp_order=selected.montage.channel_names, recorded_channel_geometry=True,
            kurtosis_screening_supported=False, strict_processing_errors=True,
            geometry_fingerprint=RECORDED_GEOMETRY_VERSION, acquisition_label=HARDWARE_LABELS[hardware.platform],
            acquisition_fingerprint=hashlib.sha256(encoded.encode()).hexdigest(), provenance_json=encoded,
            event_encoding="sample", required_sfreq=selected.profile.capabilities.native_sfreq,
            resampling_allowed=False, interpolation_allowed=False,
            montage_id=selected.montage.id,
        )
    return ResolvedAcquisitionPolicy(
        initial_reference_mode="legacy_pair",
        initial_reference_channels=(settings.get("ref_channel1") or "EXG1", settings.get("ref_channel2") or "EXG2"),
        drop_reference_channels=True, max_idx_keep=settings.get("max_idx_keep"),
        canonical_scalp_order=tuple(BIOSEMI64_CHANNELS), recorded_channel_geometry=False,
        kurtosis_screening_supported=True, strict_processing_errors=False,
        geometry_fingerprint=f"{BIOSEMI64_GEOMETRY_VERSION},{BIOSEMI64_COORDINATE_FINGERPRINT}",
        acquisition_label="BioSemi",
    )


def attach_recording_contract(
    raw: Any, settings: Mapping[str, Any] | None = None,
    *, recording_contract: RecordingContract | None = None,
) -> RecordingContract:
    """Attach immutable metadata after admission has established recording facts."""
    policy = recording_contract or resolve_recording_contract(settings or {}, raw=raw)
    setattr(raw, RECORDING_CONTRACT_ATTRIBUTE, policy)
    setattr(raw, ACQUISITION_POLICY_ATTRIBUTE, policy)
    return policy


attach_acquisition_policy = attach_recording_contract


def event_detection_kwargs(
    settings: Mapping[str, Any] | None = None, *, raw: Any = None,
    recording_contract: RecordingContract | None = None,
) -> dict[str, bool]:
    """Resolve event semantics without leaking source-format tests downstream."""
    if recording_contract is not None:
        return recording_contract.event_kwargs
    if settings is not None:
        return resolve_acquisition_policy(settings).event_kwargs
    attached = getattr(raw, RECORDING_CONTRACT_ATTRIBUTE, None) or getattr(raw, ACQUISITION_POLICY_ATTRIBUTE, None)
    if isinstance(attached, ResolvedAcquisitionPolicy):
        return attached.event_kwargs
    # Compatibility for existing callers that receive geometry-validated Raw
    # objects before the normalized import layer has attached the policy.
    geometry = read_raw_eeg_geometry(raw) if raw is not None else None
    return {"initial_event": True, "consecutive": True} if (
        (geometry and geometry.get("geometry_version") == RECORDED_GEOMETRY_VERSION)
        or hasattr(raw, "_fpvs_brain_products_events")
    ) else {}


def freeze_retained_geometry(
    raw: Any, params: dict[str, Any], *, stim_channel: str,
    recording_contract: RecordingContract | None = None,
) -> dict[str, Any]:
    """Freeze montage identity after the shared reference/channel-selection steps."""
    policy = recording_contract or resolve_recording_contract(params, raw=raw)
    if policy.recorded_channel_geometry:
        loaded_identity = read_raw_eeg_geometry(raw)
        if not loaded_identity or loaded_identity.get("geometry_version") != RECORDED_GEOMETRY_VERSION:
            raise RuntimeError("Processing requires validated recorded EEG geometry.")
        identity = attach_raw_recorded_geometry(
            raw, montage_id=loaded_identity["montage_id"],
            mapping_profile=loaded_identity["electrode_mapping_profile"],
        )
    else:
        loaded_identity = read_raw_biosemi64_geometry(raw)
        if loaded_identity is None:
            raise RuntimeError("Preprocessing requires a Raw loaded through the validated BioSemi64 geometry boundary.")
        retained = tuple(policy.ordered_scalp_channels(raw))
        if not retained:
            raise RuntimeError("No canonical BioSemi64 scalp channels remain for preprocessing.")
        identity = attach_raw_biosemi64_geometry(
            raw, electrode_mapping_profile=loaded_identity.get("electrode_mapping_profile"),
            retained_channels=retained,
            stim_channel=stim_channel if stim_channel in raw.ch_names else None,
        )
    params["_fpvs_geometry"] = dict(identity)
    params["_fpvs_retained_scalp_channels"] = list(identity["retained_scalp_channels"])
    params["_fpvs_retained_scalp_set_fingerprint"] = identity["retained_scalp_set_fingerprint"]
    return identity



def is_brain_products(settings: Mapping[str, Any]) -> bool:
    return settings.get("hardware_platform") == "brain_products"


def brain_products_policy(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve explicit reference policy without BioSemi reference fallbacks."""
    return recorded_channel_policy(settings, "brain_products")


def recorded_channel_policy(settings: Mapping[str, Any], platform: str) -> dict[str, Any]:
    """Resolve configured recorded-channel policy without inventing reference electrodes."""
    from Main_App.projects.hardware import HARDWARE_LABELS

    versions = {"brain_products": BRAIN_PRODUCTS_PIPELINE_VERSION, "biosemi_active_three": ACTIVE_THREE_PIPELINE_VERSION}
    if platform not in versions:
        raise ValueError(f"Unsupported recorded-channel acquisition platform: {platform!r}.")
    label = HARDWARE_LABELS[platform]
    if settings.get("hardware_confirmed") is not True:
        raise ValueError(f"Confirm {label} hardware in this project's settings before processing.")
    mode = settings.get("initial_reference", "recorded")
    if mode not in {"recorded", "channels"}:
        raise ValueError(f"{label} initial reference must be recorded or channels.")
    channels = settings.get("initial_reference_channels", [])
    if not isinstance(channels, (list, tuple)) or any(
        not isinstance(channel, str) or not channel.strip() for channel in channels
    ) or len(set(channels)) != len(channels):
        raise ValueError("Initial reference channels must be unique recorded channel names.")
    if mode == "channels" and not channels:
        raise ValueError("Select at least one recorded channel for the initial reference.")
    drop = settings.get("drop_reference_channels", False)
    if type(drop) is not bool:
        raise ValueError("Drop reference channels must be a boolean.")
    if mode == "recorded" and (channels or drop):
        raise ValueError("Recorded-reference mode cannot specify or drop reference channels.")
    limit = settings.get("max_idx_keep", settings.get("max_chan_idx_keep"))
    if limit is not None and (type(limit) is not int or limit < 2):
        raise ValueError("Average-reference EEG channel limit must be at least two or unset.")
    return {
        "version": versions[platform],
        "hardware_platform": platform, "initial_reference": mode,
        "initial_reference_channels": list(channels), "drop_reference_channels": drop,
        "max_idx_keep": limit, "electrode_montage": settings.get("electrode_montage", "recorded"),
        "channel_types": dict(settings.get("channel_types") or {}),
        "kurtosis_screening_supported": False,
    }


def policy_fingerprint(settings: Mapping[str, Any]) -> str:
    policy = brain_products_policy(settings)
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_brain_products_qc(settings: Mapping[str, Any]) -> None:
    """Do not apply BioSemi-calibrated adaptive screens to arbitrary electrode sets."""
    if settings.get("kurtosis_screening_enabled", False):
        raise ValueError("Normalized kurtosis screening is not qualified for Brain Products montages; disable it in project settings.")


def apply_brain_products_reference(raw: Any, params: dict[str, Any]) -> None:
    """Compatibility entry point for the shared recorded-reference operation."""
    policy = resolve_acquisition_policy({**params, "hardware_platform": "brain_products"})
    apply_recorded_reference(raw, params, policy)


def configured_channel_limit(settings: Mapping[str, Any]) -> int | None:
    """Resolve the admitted sensor limit, including historical project aliases."""
    from Main_App.projects.hardware import resolve_hardware

    platform = resolve_hardware(settings).platform
    if platform in {"brain_products", "biosemi_active_three"}:
        return recorded_channel_policy(settings, platform)["max_idx_keep"]
    if platform == "unicorn":
        limit = settings.get("max_idx_keep", settings.get("max_chan_idx_keep"))
        if limit is not None and (type(limit) is not int or limit != 8):
            raise ValueError("Unicorn processing requires all eight scalp channels; channel limits are unavailable.")
        return None
    raw_limit = settings.get("max_idx_keep")
    if raw_limit is None:
        raw_limit = settings.get("max_chan_idx_keep")
    if raw_limit is None:
        return len(BIOSEMI64_CHANNELS)
    message = "BioSemi64 channel limit must be an integer from 1 through 64."
    if isinstance(raw_limit, bool):
        raise ValueError(message)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError(message) from exc
    if isinstance(raw_limit, float) and not raw_limit.is_integer():
        raise ValueError(message)
    if not 1 <= limit <= len(BIOSEMI64_CHANNELS):
        raise ValueError(message)
    return limit


def resolve_recording_contract(
    settings: Mapping[str, Any], raw: Any = None,
) -> RecordingContract:
    """Resolve all acquisition choices into generic immutable processing inputs."""
    policy = _resolve_policy(settings)
    recorded = policy.recorded_channel_geometry
    refs = tuple(policy.initial_reference_channels) if recorded else (
        str(settings.get("ref_channel1") or settings.get("ref_chan1") or settings.get("ref_ch1") or "EXG1"),
        str(settings.get("ref_channel2") or settings.get("ref_chan2") or settings.get("ref_ch2") or "EXG2"),
    )
    identity = read_raw_eeg_geometry(raw) if raw is not None else None
    return replace(
        policy,
        montage_id=str(settings.get("electrode_montage") or policy.montage_id or ("recorded" if recorded else "biosemi64")),
        mapping_profile=str(settings.get("electrode_mapping_profile") or ("recorded_labels" if recorded else "anatomical_labels")),
        # Historical scientific fingerprints used these defaults for every
        # platform. Keep them opaque and distinct from the effective geometry.
        fingerprint_montage=settings.get("electrode_montage", "biosemi64"),
        fingerprint_mapping=settings.get("electrode_mapping_profile", "anatomical_labels"),
        stim_channel=str(settings.get("stim_channel") or settings.get("stim") or "Status"),
        load_reference_channels=refs,
        review_reference_pair=("", "") if recorded else refs,
        channel_limit=configured_channel_limit(settings),
        geometry_json=json.dumps(identity, sort_keys=True) if identity else "",
        raw_screening_supported=not recorded,
        removed_electrode_screening_supported=not recorded,
        condition_repair_supported=not recorded,
        supports_template_spatial_tools=not recorded,
        qualified_spatial_model_label="BioSemi64",
    )


resolve_acquisition_policy = resolve_recording_contract


def validate_processing_geometry(raw: Any, contract: RecordingContract) -> None:
    """Enforce the previously qualified loaded-geometry admission behavior."""
    if contract.recorded_channel_geometry:
        identity = validate_raw_recorded_geometry(raw)
        if contract.canonical_scalp_order is not None and (
            tuple(identity["retained_scalp_channels"]) != contract.canonical_scalp_order
        ):
            raise ValueError("Processing requires the complete configured scalp-channel order.")
        if not contract.interpolation_allowed and identity.get("interpolation_supported"):
            raise ValueError("Recorded geometry conflicts with the configured interpolation capability.")


def validate_loaded_geometry(
    raw: Any, contract: RecordingContract, **kwargs: Any,
) -> dict[str, Any]:
    """Validate source geometry using resolved channel roles and coordinates."""
    from Main_App.io.recorded_eeg_geometry import validate_raw_eeg_geometry

    if contract.canonical_scalp_order is not None:
        kwargs.setdefault("expected_retained_channels", contract.canonical_scalp_order[:contract.channel_limit])
        kwargs.setdefault("reference_channels", contract.load_reference_channels)
        kwargs.setdefault("require_runtime_identity", True)
    kwargs.setdefault("stim_channel", contract.stim_channel)
    return validate_raw_eeg_geometry(raw, **kwargs)


def cache_acquisition_identity(settings: Mapping[str, Any]) -> dict[str, Any] | None:
    """Preserve the historical cache extension only where it was already used."""
    from Main_App.io.hardware_identity import recorded_settings_identity
    from Main_App.projects.hardware import resolve_hardware

    return recorded_settings_identity(settings) if resolve_hardware(settings).platform != "biosemi" else None


def geometry_identity_for_channels(
    settings: Mapping[str, Any], channel_names: list[str] | None = None,
) -> dict[str, Any]:
    """Preserve the worker's pre-read geometry/configuration cache identity."""
    recorded_identity = cache_acquisition_identity(settings)
    if recorded_identity is not None:
        return recorded_identity
    from Main_App.projects.preprocessing_settings import normalize_electrode_montage

    montage = normalize_electrode_montage(settings.get("electrode_montage"))
    if montage != "biosemi64":
        raise ValueError(f"Unsupported electrode montage {montage!r}; only 'biosemi64' is supported.")
    retained = (
        list(BIOSEMI64_CHANNELS[:configured_channel_limit(settings)])
        if channel_names is None else [name for name in BIOSEMI64_CHANNELS if name in set(channel_names)]
    )
    return biosemi64_geometry_identity(
        electrode_mapping_profile=settings.get("electrode_mapping_profile"), retained_channels=retained,
    )


def attach_processed_geometry(raw: Any, settings: Mapping[str, Any]) -> dict[str, Any]:
    """Restore/validate geometry for an admitted numerical result or checkpoint."""
    contract = resolve_recording_contract(settings)
    if contract.recorded_channel_geometry:
        if read_raw_eeg_geometry(raw) is not None:
            identity = validate_raw_recorded_geometry(raw)
        else:
            identity = attach_raw_recorded_geometry(
                raw, montage_id=contract.montage_id, mapping_profile=contract.mapping_profile,
                hardware_platform=contract.provenance["hardware_platform"],
                interpolation_allowed=contract.interpolation_allowed,
            )
        attach_recording_contract(raw, settings)
        return identity
    geometry_identity_for_channels(settings, list(raw.ch_names))
    present = set(raw.ch_names)
    return attach_raw_biosemi64_geometry(
        raw, electrode_mapping_profile=settings.get("electrode_mapping_profile"),
        retained_channels=[name for name in BIOSEMI64_CHANNELS if name in present],
        stim_channel=contract.stim_channel if contract.stim_channel in present else None,
    )


def restore_processed_geometry(
    raw: Any, settings: Mapping[str, Any], cached_geometry: Any,
) -> dict[str, Any]:
    """Restore exact recorded coordinates after a cache representation roundtrip."""
    contract = resolve_recording_contract(settings)
    if contract.recorded_channel_geometry and isinstance(cached_geometry, Mapping):
        from Main_App.io.hardware_loader import restore_cached_recorded_geometry

        identity = restore_cached_recorded_geometry(raw, cached_geometry)
        attach_recording_contract(raw, settings)
        return identity
    return attach_processed_geometry(raw, settings)


def review_geometry_identity(
    settings: Mapping[str, Any], raw: Any = None,
    *, retained_channels: Any = None,
) -> dict[str, Any]:
    """Preserve the QC method/result geometry provenance representation."""
    contract = resolve_recording_contract(settings)
    if contract.recorded_channel_geometry:
        return validate_raw_recorded_geometry(raw) if raw is not None else contract.provenance
    retained = retained_channels if retained_channels is not None else BIOSEMI64_CHANNELS[:contract.channel_limit]
    return biosemi64_geometry_identity(
        electrode_mapping_profile=settings.get("electrode_mapping_profile"), retained_channels=retained,
    )


def source_load_kwargs(
    settings: Mapping[str, Any], *, prefer_first_n: bool = False,
) -> dict[str, Any]:
    """Return the existing normalized source-load argument policy."""
    contract = resolve_recording_contract(settings)
    limit = settings.get("first_n_channels", contract.channel_limit) if prefer_first_n else contract.channel_limit
    if contract.recorded_channel_geometry:
        return {
            "first_n_channels": limit,
            "stim_channel": str(settings.get("stim_channel") or "Status"),
            "electrode_montage": contract.montage_id if contract.required_sfreq is not None else settings.get("electrode_montage", "recorded"),
        }
    return {
        "ref_pair": contract.load_reference_channels,
        "first_n_channels": limit,
        "stim_channel": contract.stim_channel,
        "electrode_mapping_profile": settings.get("electrode_mapping_profile"),
        "electrode_montage": "biosemi64",
    }


def source_identity(settings: Mapping[str, Any]) -> dict[str, Any]:
    """Detach only project metadata that can change admitted source samples."""
    from Main_App.projects.hardware import HARDWARE_SETTINGS_KEYS

    keys = (*HARDWARE_SETTINGS_KEYS, "electrode_montage", "electrode_mapping_profile", "acquisition_profile")
    return deepcopy({key: settings[key] for key in keys if key in settings})


def resolve_spatial_tool_capability(settings: Mapping[str, Any] | None) -> tuple[bool, str, str]:
    """Describe qualified add-on availability before processing is configured.

    This read-only explanation does not authorize a recording load or validate
    reference choices; those remain mandatory at recording admission.
    """
    from Main_App.projects.hardware import HARDWARE_LABELS, resolve_hardware

    hardware = resolve_hardware(settings)
    return hardware.platform == "biosemi", "BioSemi64", HARDWARE_LABELS[hardware.platform]


@dataclass(frozen=True)
class QualifiedSpatialProfile:
    """Opaque metadata for the existing scientifically qualified spatial model."""

    channels: tuple[str, ...]
    channel_set: frozenset[str]
    coordinates: Any
    validation_error: type[ValueError]
    shared_noise_help_url: str
    montage_id: str
    geometry_version: str
    coordinate_fingerprint: str
    geometry_identity: Any

    @property
    def channel_order(self) -> tuple[str, ...]:
        return self.channels


CALIBRATED_SPATIAL_PROFILE = QualifiedSpatialProfile(
    channels=tuple(BIOSEMI64_CHANNELS), channel_set=frozenset(BIOSEMI64_CHANNELS),
    coordinates=canonical_biosemi64_head_coordinates, validation_error=BioSemi64GeometryError,
    shared_noise_help_url="https://www.biosemi.com/faq/cms%26drl.htm",
    montage_id="biosemi64", geometry_version=BIOSEMI64_GEOMETRY_VERSION,
    coordinate_fingerprint=BIOSEMI64_COORDINATE_FINGERPRINT,
    geometry_identity=biosemi64_geometry_identity,
)
