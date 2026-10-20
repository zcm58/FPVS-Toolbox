"""Stable project acquisition policy identity without opening signal files."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json


def brain_products_settings_identity(settings: Mapping) -> dict[str, object]:
    """Bind configuration to caches; observed geometry remains a separate fact."""
    payload = {
        "hardware_platform": "brain_products",
        "policy_version": "brain_products_recorded_v1",
        "montage_id": settings.get("electrode_montage") or "recorded",
        "initial_reference": settings.get("initial_reference") or "recorded",
        "initial_reference_channels": list(settings.get("initial_reference_channels") or []),
        "drop_reference_channels": bool(settings.get("drop_reference_channels", False)),
        "channel_types": dict(settings.get("channel_types") or {}),
        "max_idx_keep": settings.get("max_idx_keep", settings.get("max_chan_idx_keep")),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**payload, "hardware_policy_fingerprint": "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()}


def recorded_settings_identity(settings: Mapping) -> dict[str, object]:
    """Resolve configuration identities without altering existing platform bytes."""
    from Main_App.projects.hardware import resolve_hardware, unicorn_acquisition_profile

    platform = resolve_hardware(settings).platform
    if platform == "brain_products":
        return brain_products_settings_identity(settings)
    if platform == "biosemi_active_three":
        payload = brain_products_settings_identity(settings)
        payload.pop("hardware_policy_fingerprint")
        payload.update(hardware_platform=platform, policy_version="biosemi_active_three_recorded_v1")
    elif platform == "unicorn":
        from Main_App.io.acquisition_profiles import resolve_acquisition_contract

        contract = resolve_acquisition_contract({"acquisition_profile": unicorn_acquisition_profile(settings)})
        payload = {
            "hardware_platform": platform, "policy_version": "unicorn_native_eeg_v1",
            "montage_id": contract.montage.id, "reference_policy": contract.reference_policy,
            "acquisition_contract": json.loads(json.dumps(contract.identity)),
            "acquisition_contract_fingerprint": contract.fingerprint,
            "recording_event_policy": json.loads(json.dumps(settings.get("recording_event_policy") or {})),
        }
    else:
        raise ValueError(f"No recorded-channel configuration identity for {platform!r}.")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**payload, "hardware_policy_fingerprint": "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()}


def geometry_matches_configuration(candidate: object, expected: Mapping) -> bool:
    """Check observed geometry against a plan whose source channels are not read yet.

    Processing fingerprints bind the complete reference/montage policy and
    source identities bind all companions. Recorded channel geometry must also
    validate itself and agree with the explicitly configured montage.
    """
    if not isinstance(candidate, Mapping):
        return False
    if expected.get("hardware_platform") not in {"brain_products", "biosemi_active_three", "unicorn"}:
        return dict(candidate) == dict(expected)
    from Main_App.io.recorded_eeg_geometry import validate_recorded_geometry_identity

    try:
        valid = validate_recorded_geometry_identity(candidate)
    except (ValueError, TypeError):
        return False
    return (
        valid["montage_id"] == expected.get("montage_id")
        and valid["hardware_platform"] == expected.get("hardware_platform")
    )
