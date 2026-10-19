"""Resolve acquisition geometry into metadata for processing consumers.

Manufacturer interpretation and historical geometry encodings belong at this
boundary. Numerical/cohort consumers use the resolved geometry mode, ordered
channels, and validated identities without choosing an acquisition platform.
Existing serialized identities are intentionally unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    BIOSEMI64_MONTAGE_ID,
    biosemi64_geometry_identity,
)
from Main_App.io.hardware_identity import brain_products_settings_identity
from Main_App.io.recorded_eeg_geometry import (
    RECORDED_GEOMETRY_VERSION,
    validate_recorded_geometry_identity,
)
from Main_App.projects.hardware import resolve_hardware


@dataclass(frozen=True)
class ProjectGeometryMetadata:
    """Project geometry expectations independent of a recording's sample data."""

    per_recording: bool
    montage_id: str
    source_platform: str
    fixed_geometry: Mapping[str, object] | None = None

    def matches_source(self, geometry: Mapping[str, object]) -> bool:
        if self.per_recording:
            return (
                is_recorded_source_geometry(geometry)
                and geometry.get("hardware_platform") == self.source_platform
                and geometry.get("montage_id") == self.montage_id
            )
        return dict(geometry) == dict(self.fixed_geometry or {})


def is_recorded_source_geometry(value: Mapping[str, object]) -> bool:
    """Identify the recorded-coordinate schema, never infer from channel names."""
    return value.get("geometry_version") == RECORDED_GEOMETRY_VERSION


def source_geometry_definition(value: Mapping[str, Any]) -> dict[str, object]:
    """Rebuild a source definition, preserving its existing identity format."""
    if is_recorded_source_geometry(value):
        return validate_recorded_geometry_identity(value)
    retained = value.get("retained_scalp_channels")
    if not isinstance(retained, Sequence) or isinstance(retained, (str, bytes)):
        raise ValueError("Source geometry has no ordered retained scalp channels.")
    return biosemi64_geometry_identity(
        electrode_mapping_profile=value.get("electrode_mapping_profile"),
        retained_channels=[str(channel) for channel in retained],
    )


def validate_source_geometry_identity(value: Mapping[str, Any]) -> dict[str, object]:
    """Reject stale coordinates, channel identities, and unknown source schemas."""
    expected = source_geometry_definition(value)
    if dict(value) != expected:
        raise ValueError(
            "Source geometry uses an unknown or legacy electrode geometry, "
            "or its identity does not match the validated definition."
        )
    return expected


def configured_geometry_identity(settings: Mapping[str, Any]) -> dict[str, object]:
    """Resolve the exact historical ledger identity without reading samples."""
    hardware = resolve_hardware(settings)
    if hardware.platform == "brain_products":
        return brain_products_settings_identity(settings)
    raw_limit = settings.get("max_idx_keep")
    if raw_limit is None:
        raw_limit = settings.get("max_chan_idx_keep")
    if raw_limit is None:
        channel_limit = len(BIOSEMI64_CHANNELS)
    elif isinstance(raw_limit, bool):
        raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.")
    else:
        try:
            channel_limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.") from exc
        if isinstance(raw_limit, float) and not raw_limit.is_integer():
            raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.")
    if not 1 <= channel_limit <= len(BIOSEMI64_CHANNELS):
        raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.")
    return biosemi64_geometry_identity(
        electrode_mapping_profile=settings.get("electrode_mapping_profile"),
        retained_channels=BIOSEMI64_CHANNELS[:channel_limit],
    )


def project_spectral_geometry(settings: Mapping[str, Any]) -> ProjectGeometryMetadata:
    """Resolve normalized project expectations for nonspatial cohort matching."""
    hardware = resolve_hardware(settings)
    montage_id = str(settings.get("electrode_montage") or "")
    if hardware.platform == "brain_products":
        return ProjectGeometryMetadata(True, montage_id, hardware.platform)
    if montage_id != BIOSEMI64_MONTAGE_ID:
        raise ValueError(
            f"Unsupported project electrode montage {montage_id!r}; only "
            f"{BIOSEMI64_MONTAGE_ID!r} is valid for current processing."
        )
    expected_limit = int(settings.get("max_chan_idx_keep") or len(BIOSEMI64_CHANNELS))
    count = expected_limit if 0 < expected_limit < len(BIOSEMI64_CHANNELS) else len(BIOSEMI64_CHANNELS)
    geometry = biosemi64_geometry_identity(
        electrode_mapping_profile=settings.get("electrode_mapping_profile"),
        retained_channels=BIOSEMI64_CHANNELS[:count],
    )
    return ProjectGeometryMetadata(False, montage_id, hardware.platform, geometry)


def condition_repair_channel_order(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the channel domain qualified for condition-specific repairs."""
    hardware = resolve_hardware(settings)
    if hardware.platform == "brain_products":
        raise ValueError("Condition-specific interpolation is not qualified for this project's montage.")
    return BIOSEMI64_CHANNELS
