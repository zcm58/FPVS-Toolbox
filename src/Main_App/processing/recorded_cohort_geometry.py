"""Spectral cohort identity without substituting one subject's digitization.

Scalp spectra require compatible channel identities and processing policies.
They do not require identical measured electrode coordinates across subjects.
Coordinates remain validated, fingerprinted, and owned by each source here;
this aggregate must never be used as a montage for a spatial calculation.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any

from Main_App.io.recorded_eeg_geometry import validate_recorded_geometry_identity

RECORDED_COHORT_GEOMETRY_VERSION = "recorded_eeg_spectral_cohort_v1"

_SHARED_FIELDS = (
    "hardware_platform", "montage_id", "electrode_mapping_profile",
    "canonical_scalp_channels", "canonical_scalp_channel_count",
    "canonical_scalp_set_fingerprint", "retained_scalp_channels",
    "retained_scalp_channel_count", "retained_scalp_set_fingerprint",
)


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def recorded_cohort_geometry_identity(
    source_geometries: Mapping[str, Mapping[str, Any]],
    *,
    source_identity_kind: str,
    processing_identity: Mapping[str, str],
) -> dict[str, Any]:
    """Freeze matching ordered scalp identities and each source's coordinates."""
    if source_identity_kind not in {"participant_id", "recording_id"}:
        raise ValueError("Unknown recorded-cohort source identity kind.")
    if not isinstance(source_geometries, Mapping) or not source_geometries:
        raise ValueError("A recorded spectral cohort requires source geometries.")
    if any(not isinstance(key, str) or not key or key != key.strip() for key in source_geometries):
        raise ValueError("Recorded-cohort source IDs must be nonempty strings.")
    if len({key.casefold() for key in source_geometries}) != len(source_geometries):
        raise ValueError("Recorded-cohort source IDs must be unique.")
    if any(not isinstance(geometry, Mapping) for geometry in source_geometries.values()):
        raise ValueError("Every recorded source requires its own geometry identity.")
    if (
        not isinstance(processing_identity, Mapping)
        or set(processing_identity) != {"processing_fingerprint_version", "processing_fingerprint"}
        or any(not isinstance(value, str) or not value.strip() for value in processing_identity.values())
    ):
        raise ValueError("Recorded spectral cohorts require a complete processing policy identity.")
    geometries = {
        key: validate_recorded_geometry_identity(source_geometries[key])
        for key in sorted(source_geometries)
    }
    first = next(iter(geometries.values()))
    common = {key: first[key] for key in _SHARED_FIELDS}
    for source_id, geometry in geometries.items():
        if any(geometry[key] != value for key, value in common.items()):
            raise ValueError(
                f"Recorded source {source_id!r} has incompatible montage, mapping, "
                "or ordered scalp channels. Process a cohort with matching channel identities."
            )
        if geometry["coordinate_source"] != first["coordinate_source"]:
            raise ValueError("Recorded sources mix measured and template coordinate policies.")
    payload = {
        **common,
        "geometry_version": RECORDED_COHORT_GEOMETRY_VERSION,
        "coordinate_source": "per_recording",
        "coordinate_frame": "per_recording",
        "geometry_status": "per_recording",
        "coordinate_fingerprint": _fingerprint({
            key: geometry["coordinate_fingerprint"] for key, geometry in geometries.items()
        }),
        "interpolation_supported": False,
        "source_identity_kind": source_identity_kind,
        "source_geometries": geometries,
        "processing_identity": dict(processing_identity),
    }
    payload["geometry_identity_fingerprint"] = _fingerprint(payload)
    return payload


def validate_recorded_cohort_geometry_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild every nested identity; no source coordinates may be omitted."""
    if value.get("geometry_version") != RECORDED_COHORT_GEOMETRY_VERSION:
        raise ValueError("Unsupported recorded spectral cohort geometry version.")
    expected = recorded_cohort_geometry_identity(
        value.get("source_geometries"),
        source_identity_kind=value.get("source_identity_kind"),
        processing_identity=value.get("processing_identity"),
    )
    if dict(value) != expected:
        raise ValueError("Recorded spectral cohort geometry identity or fingerprint is inconsistent.")
    return expected


def validate_recorded_spectral_geometry_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    """Accept source or cohort identities only at nonspatial spectral boundaries."""
    if value.get("geometry_version") == RECORDED_COHORT_GEOMETRY_VERSION:
        return validate_recorded_cohort_geometry_identity(value)
    return validate_recorded_geometry_identity(value)
