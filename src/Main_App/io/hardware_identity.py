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


def geometry_matches_configuration(candidate: object, expected: Mapping) -> bool:
    """Check observed geometry against a plan whose source channels are not read yet.

    Processing fingerprints bind the complete reference/montage policy and
    source identities bind all companions. Recorded channel geometry must also
    validate itself and agree with the explicitly configured montage.
    """
    if not isinstance(candidate, Mapping):
        return False
    if expected.get("hardware_platform") != "brain_products":
        return dict(candidate) == dict(expected)
    from Main_App.io.recorded_eeg_geometry import validate_recorded_geometry_identity

    try:
        valid = validate_recorded_geometry_identity(candidate)
    except (ValueError, TypeError):
        return False
    return valid["montage_id"] == expected.get("montage_id")
