"""Recording-owned sensor identity for non-BioSemi acquisition systems.

Channel labels do not establish cap geometry. An explicit template selection or
complete, finite recorded head coordinates are required for interpolation.
Spectral processing can retain EEG without coordinates and reports that state.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import mne
import numpy as np
from mne._fiff.constants import FIFF

from Main_App.io.eeg_geometry import (
    BIOSEMI64_RUNTIME_ATTRIBUTE,
    read_raw_biosemi64_geometry,
    validate_raw_biosemi64_geometry,
)

RECORDED_GEOMETRY_VERSION = "recorded_eeg_geometry_v1"


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _names(values: Sequence[str], *, label: str) -> list[str]:
    names = list(values)
    if not names or any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError(f"{label} must contain nonempty channel names.")
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError(f"{label} contains duplicate channel names.")
    return names


def _coordinates(raw: Any, names: Sequence[str]) -> dict[str, list[float] | None]:
    result: dict[str, list[float] | None] = {}
    for name in names:
        channel = raw.info["chs"][raw.ch_names.index(name)]
        coordinate = np.asarray(channel["loc"][:3], dtype=float)
        usable = (
            coordinate.shape == (3,)
            and np.isfinite(coordinate).all()
            and np.linalg.norm(coordinate) > 0
            and channel["coord_frame"] == FIFF.FIFFV_COORD_HEAD
        )
        result[name] = coordinate.tolist() if usable else None
    return result


def _identity(
    *, montage_id: str, mapping_profile: str, canonical: list[str],
    retained: list[str], coordinates: Mapping[str, Any], coordinate_source: str,
    hardware_platform: str = "brain_products", interpolation_allowed: bool = True,
) -> dict[str, Any]:
    if not isinstance(hardware_platform, str) or not hardware_platform or hardware_platform != hardware_platform.strip():
        raise ValueError("Recorded EEG geometry requires an explicit acquisition platform.")
    if type(interpolation_allowed) is not bool:
        raise ValueError("Interpolation capability must be a boolean.")
    retained_coordinates = {name: coordinates[name] for name in retained}
    complete = all(value is not None for value in retained_coordinates.values())
    identity = {
        "hardware_platform": hardware_platform,
        "montage_id": montage_id,
        "geometry_version": RECORDED_GEOMETRY_VERSION,
        "coordinate_source": coordinate_source,
        "coordinate_frame": "head" if complete else "unavailable",
        "geometry_status": "available" if complete else "unavailable",
        "coordinate_fingerprint": _fingerprint(retained_coordinates),
        "channel_coordinates_m": retained_coordinates,
        "canonical_scalp_channels": canonical,
        "canonical_scalp_channel_count": len(canonical),
        "canonical_scalp_set_fingerprint": _fingerprint(sorted(canonical)),
        "electrode_mapping_profile": mapping_profile,
        "retained_scalp_channels": retained,
        "retained_scalp_channel_count": len(retained),
        "retained_scalp_set_fingerprint": _fingerprint(sorted(retained)),
        "interpolation_supported": interpolation_allowed and complete and len(retained) >= 4,
    }
    # Existing Brain Products geometry is a frozen scientific identity.
    if hardware_platform != "brain_products" or not interpolation_allowed:
        identity["interpolation_allowed"] = interpolation_allowed
    identity["geometry_identity_fingerprint"] = _fingerprint(identity)
    return identity


def attach_raw_recorded_geometry(
    raw: Any, *, montage_id: str = "recorded", template_montage: str | None = None,
    scalp_channels: Sequence[str] | None = None, mapping_profile: str = "recorded_labels",
    hardware_platform: str | None = None, interpolation_allowed: bool | None = None,
) -> dict[str, Any]:
    """Attach identity after type/position resolution; never infer a cap by count.

    ``template_montage`` is an explicit project choice, not file-type inference.
    Missing template electrodes are fatal rather than silently given no position.
    """
    _names(raw.ch_names, label="Recording")
    eeg = [name for name, kind in zip(raw.ch_names, raw.get_channel_types(), strict=True) if kind == "eeg"]
    retained = _names(list(scalp_channels) if scalp_channels is not None else eeg, label="EEG channels")
    if set(retained) != set(eeg):
        raise ValueError("Recorded scalp identity must include every EEG channel and no auxiliary channels.")
    prior = read_raw_eeg_geometry(raw)
    prior_recorded = prior if prior and prior.get("geometry_version") == RECORDED_GEOMETRY_VERSION else {}
    platform = hardware_platform if hardware_platform is not None else prior_recorded.get("hardware_platform", "brain_products")
    allow_interpolation = (
        interpolation_allowed if interpolation_allowed is not None
        else prior_recorded.get("interpolation_allowed", True)
    )
    if template_montage is not None:
        if template_montage not in mne.channels.get_builtin_montages():
            raise ValueError(f"Unknown EEG montage template {template_montage!r}.")
        raw.set_montage(template_montage, match_case=True, on_missing="raise", verbose=False)
        if montage_id == "recorded":
            montage_id = template_montage
        source = "explicit_project_template"
    else:
        source = (
            str(prior["coordinate_source"])
            if prior and prior.get("geometry_version") == RECORDED_GEOMETRY_VERSION
            else "recording"
        )
    canonical = (
        list(prior["canonical_scalp_channels"])
        if prior and prior.get("geometry_version") == RECORDED_GEOMETRY_VERSION
        else list(retained)
    )
    if not set(retained).issubset(canonical):
        raise ValueError("Retained EEG channels do not belong to the recording identity.")
    identity = _identity(
        montage_id=montage_id, mapping_profile=mapping_profile, canonical=canonical,
        retained=retained, coordinates=_coordinates(raw, retained), coordinate_source=source,
        hardware_platform=platform, interpolation_allowed=allow_interpolation,
    )
    setattr(raw, BIOSEMI64_RUNTIME_ATTRIBUTE, identity)
    return copy.deepcopy(identity)


def read_raw_eeg_geometry(raw: Any) -> dict[str, Any] | None:
    """Read the shared runtime attribute without changing its scientific owner."""
    return read_raw_biosemi64_geometry(raw)


def validate_raw_recorded_geometry(raw: Any, *, require_coordinates: bool = False) -> dict[str, Any]:
    stored = read_raw_eeg_geometry(raw)
    if not stored or stored.get("geometry_version") != RECORDED_GEOMETRY_VERSION:
        raise ValueError("Recording has no validated recorded-channel geometry identity.")
    validate_recorded_geometry_identity(stored)
    names = _names(raw.ch_names, label="Recording")
    eeg = [name for name, kind in zip(names, raw.get_channel_types(), strict=True) if kind == "eeg"]
    retained = _names(stored.get("retained_scalp_channels", []), label="Retained EEG channels")
    if eeg != retained:
        raise ValueError("EEG channel names, roles or order changed after geometry validation.")
    expected = _identity(
        montage_id=stored["montage_id"], mapping_profile=stored["electrode_mapping_profile"],
        canonical=_names(stored["canonical_scalp_channels"], label="Original EEG channels"),
        retained=retained, coordinates=_coordinates(raw, retained),
        coordinate_source=stored["coordinate_source"],
        hardware_platform=stored["hardware_platform"],
        interpolation_allowed=stored.get("interpolation_allowed", True),
    )
    if stored != expected:
        raise ValueError("Recorded EEG geometry changed after validation.")
    if require_coordinates and not stored["interpolation_supported"]:
        raise ValueError(
            "Interpolation requires complete head coordinates for at least four EEG electrodes; "
            "supply recorded digitization or select the correct montage template."
        )
    return stored


def validate_recorded_geometry_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate portable provenance without inventing geometry from channel count."""
    if value.get("geometry_version") != RECORDED_GEOMETRY_VERSION:
        raise ValueError("Unsupported recorded EEG geometry version.")
    canonical = _names(value.get("canonical_scalp_channels", []), label="Original EEG channels")
    retained = _names(value.get("retained_scalp_channels", []), label="Retained EEG channels")
    if not set(retained).issubset(canonical):
        raise ValueError("Retained EEG channels are outside the original recording identity.")
    coordinates = value.get("channel_coordinates_m")
    if not isinstance(coordinates, Mapping) or set(coordinates) != set(retained):
        raise ValueError("Recorded EEG geometry is missing coordinate identities.")
    for coordinate in coordinates.values():
        if coordinate is not None:
            array = np.asarray(coordinate, dtype=float)
            if array.shape != (3,) or not np.isfinite(array).all() or not np.linalg.norm(array) > 0:
                raise ValueError("Recorded EEG coordinates must be finite head positions or unavailable.")
    expected = _identity(
        montage_id=str(value.get("montage_id")), mapping_profile=str(value.get("electrode_mapping_profile")),
        canonical=canonical, retained=retained, coordinates=coordinates,
        coordinate_source=str(value.get("coordinate_source")),
        hardware_platform=value.get("hardware_platform"),
        interpolation_allowed=value.get("interpolation_allowed", True),
    )
    if dict(value) != expected:
        raise ValueError("Recorded EEG geometry identity or fingerprint is inconsistent.")
    return copy.deepcopy(expected)


def validate_raw_eeg_geometry(raw: Any, **kwargs: Any) -> dict[str, Any]:
    """Dispatch validated geometry without weakening the BioSemi64 boundary."""
    stored = read_raw_eeg_geometry(raw)
    if stored and stored.get("geometry_version") == RECORDED_GEOMETRY_VERSION:
        identity = validate_raw_recorded_geometry(
            raw, require_coordinates=bool(kwargs.pop("require_coordinates", False)),
        )
        expected = kwargs.get("expected_retained_channels")
        if expected is not None and list(expected) != identity["retained_scalp_channels"]:
            raise ValueError("Retained EEG channels differ from the expected recording identity.")
        stim = kwargs.get("stim_channel")
        if stim is not None:
            kinds = dict(zip(raw.ch_names, raw.get_channel_types(), strict=True))
            if kinds.get(stim) != "stim":
                raise ValueError(f"Stimulation channel {stim!r} is not typed as stim.")
        return identity
    kwargs.pop("require_coordinates", None)
    return validate_raw_biosemi64_geometry(raw, **kwargs)
