"""Canonical BioSemi ActiveTwo 64 sensor identity and runtime geometry.

The loader uses this module before any optional channel subset is opened.  It
validates channel identities by name, applies the one supported sensor
geometry, and records a JSON-safe identity on the in-memory MNE ``Raw``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Mapping, Optional, Sequence

import mne
import numpy as np

BIOSEMI64_MONTAGE_ID = "biosemi64"
BIOSEMI64_GEOMETRY_VERSION = "1.0"
BIOSEMI64_RUNTIME_ATTRIBUTE = "_fpvs_eeg_geometry"

# MNE's ``biosemi64`` template order is the documented BioSemi 64-channel
# 10-20 wiring order.  Keep this tuple literal so channel validation does not
# silently change when an installed MNE version changes.
BIOSEMI64_CHANNELS: tuple[str, ...] = (
    "Fp1",
    "AF7",
    "AF3",
    "F1",
    "F3",
    "F5",
    "F7",
    "FT7",
    "FC5",
    "FC3",
    "FC1",
    "C1",
    "C3",
    "C5",
    "T7",
    "TP7",
    "CP5",
    "CP3",
    "CP1",
    "P1",
    "P3",
    "P5",
    "P7",
    "P9",
    "PO7",
    "PO3",
    "O1",
    "Iz",
    "Oz",
    "POz",
    "Pz",
    "CPz",
    "Fpz",
    "Fp2",
    "AF8",
    "AF4",
    "AFz",
    "Fz",
    "F2",
    "F4",
    "F6",
    "F8",
    "FT8",
    "FC6",
    "FC4",
    "FC2",
    "FCz",
    "Cz",
    "C2",
    "C4",
    "C6",
    "T8",
    "TP8",
    "CP6",
    "CP4",
    "CP2",
    "P2",
    "P4",
    "P6",
    "P8",
    "P10",
    "PO8",
    "PO4",
    "O2",
)
BIOSEMI64_CHANNEL_SET = frozenset(BIOSEMI64_CHANNELS)

# This mapping is deliberately explicit.  A label such as ``A12`` has no
# anatomical meaning without the named, tested BioSemi 64 10-20 wiring
# profile; in particular, this must not be used for BioSemi's ABC/equiradial
# cap layouts.
BIOSEMI64_1020_AB_CHANNEL_MAP: Mapping[str, str] = {
    "A1": "Fp1",
    "A2": "AF7",
    "A3": "AF3",
    "A4": "F1",
    "A5": "F3",
    "A6": "F5",
    "A7": "F7",
    "A8": "FT7",
    "A9": "FC5",
    "A10": "FC3",
    "A11": "FC1",
    "A12": "C1",
    "A13": "C3",
    "A14": "C5",
    "A15": "T7",
    "A16": "TP7",
    "A17": "CP5",
    "A18": "CP3",
    "A19": "CP1",
    "A20": "P1",
    "A21": "P3",
    "A22": "P5",
    "A23": "P7",
    "A24": "P9",
    "A25": "PO7",
    "A26": "PO3",
    "A27": "O1",
    "A28": "Iz",
    "A29": "Oz",
    "A30": "POz",
    "A31": "Pz",
    "A32": "CPz",
    "B1": "Fpz",
    "B2": "Fp2",
    "B3": "AF8",
    "B4": "AF4",
    "B5": "AFz",
    "B6": "Fz",
    "B7": "F2",
    "B8": "F4",
    "B9": "F6",
    "B10": "F8",
    "B11": "FT8",
    "B12": "FC6",
    "B13": "FC4",
    "B14": "FC2",
    "B15": "FCz",
    "B16": "Cz",
    "B17": "C2",
    "B18": "C4",
    "B19": "C6",
    "B20": "T8",
    "B21": "TP8",
    "B22": "CP6",
    "B23": "CP4",
    "B24": "CP2",
    "B25": "P2",
    "B26": "P4",
    "B27": "P6",
    "B28": "P8",
    "B29": "P10",
    "B30": "PO8",
    "B31": "PO4",
    "B32": "O2",
}

_BIOSEMI64_CANONICAL_BY_CASEFOLD = {name.casefold(): name for name in BIOSEMI64_CHANNELS}
_BIOSEMI64_AB_BY_CASEFOLD = {name.casefold(): canonical for name, canonical in BIOSEMI64_1020_AB_CHANNEL_MAP.items()}
_BIOSEMI_AUXILIARY_LABELS = frozenset(f"EXG{index}" for index in range(1, 9))
_BIOSEMI_NON_DATA_ELECTRODES = frozenset({"CMS", "DRL"})


class BioSemi64GeometryError(ValueError):
    """The recording cannot be assigned the supported BioSemi64 geometry."""


def _mapping_profile_contract() -> tuple[str, str]:
    """Load project-owned identifiers lazily to keep processing imports acyclic."""

    from Main_App.projects.preprocessing_settings import (
        ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
        ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1,
    )

    return (
        ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
        ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1,
    )


def _normalize_mapping_profile(value: Any) -> str:
    from Main_App.projects.preprocessing_settings import (
        normalize_electrode_mapping_profile,
    )

    return normalize_electrode_mapping_profile(value)


@dataclass(frozen=True)
class BioSemi64AcquisitionGeometry:
    """Validated acquisition-header identity before an optional channel limit."""

    source_channel_names: tuple[str, ...]
    scalp_source_names: tuple[str, ...]
    scalp_canonical_names: tuple[str, ...]
    source_to_canonical_items: tuple[tuple[str, str], ...]
    reference_source_names: tuple[str, str]
    stim_source_name: str
    electrode_mapping_profile: str

    @property
    def source_to_canonical(self) -> dict[str, str]:
        return dict(self.source_to_canonical_items)

    def retained_scalp_names(self, first_n_channels: Optional[int]) -> tuple[str, ...]:
        """Return the predictable first-N canonical anatomical identities."""

        if first_n_channels is None:
            return self.scalp_canonical_names
        if isinstance(first_n_channels, bool) or not isinstance(first_n_channels, int):
            raise BioSemi64GeometryError("BioSemi64 channel limit must be an integer from 1 through 64.")
        if not 1 <= first_n_channels <= len(BIOSEMI64_CHANNELS):
            raise BioSemi64GeometryError("BioSemi64 channel limit must be an integer from 1 through 64.")
        return BIOSEMI64_CHANNELS[:first_n_channels]

    def included_source_names(self, first_n_channels: Optional[int]) -> Optional[list[str]]:
        """Return a source-order include list after full-header validation."""

        if first_n_channels is None:
            return None
        retained_canonical = set(self.retained_scalp_names(first_n_channels))
        source_to_canonical = self.source_to_canonical
        retained = {source for source in self.scalp_source_names if source_to_canonical[source] in retained_canonical}
        retained.update(self.reference_source_names)
        retained.add(self.stim_source_name)
        return [name for name in self.source_channel_names if name in retained]


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


@lru_cache(maxsize=1)
def cached_biosemi64_montage() -> mne.channels.DigMontage:
    """Return the validated canonical MNE BioSemi64 montage."""

    montage = mne.channels.make_standard_montage(BIOSEMI64_MONTAGE_ID)
    if tuple(montage.ch_names) != BIOSEMI64_CHANNELS:
        raise BioSemi64GeometryError(
            "Installed MNE BioSemi64 channel identities do not match the FPVS Toolbox geometry contract."
        )
    positions = montage.get_positions().get("ch_pos", {})
    if set(positions) != BIOSEMI64_CHANNEL_SET:
        raise BioSemi64GeometryError("Installed MNE BioSemi64 montage does not contain exactly 64 sensor positions.")
    for channel in BIOSEMI64_CHANNELS:
        coordinate = np.asarray(positions[channel], dtype=float)
        if coordinate.shape != (3,) or not np.isfinite(coordinate).all():
            raise BioSemi64GeometryError(f"Installed MNE BioSemi64 coordinate is invalid for {channel}.")
    return montage


@lru_cache(maxsize=1)
def _canonical_head_coordinate_items() -> tuple[tuple[str, tuple[float, float, float]], ...]:
    """Return coordinates exactly as MNE writes them into Raw.info in head space."""

    info = mne.create_info(list(BIOSEMI64_CHANNELS), sfreq=1.0, ch_types="eeg")
    info.set_montage(
        cached_biosemi64_montage(),
        on_missing="raise",
        match_case=True,
        verbose=False,
    )
    return tuple(
        (
            channel,
            tuple(float(value) for value in info["chs"][index]["loc"][:3]),
        )
        for index, channel in enumerate(BIOSEMI64_CHANNELS)
    )


def canonical_biosemi64_head_coordinates() -> dict[str, tuple[float, float, float]]:
    """Return a fresh name-to-coordinate mapping in MNE's Raw head frame."""

    return dict(_canonical_head_coordinate_items())


def _coordinate_fingerprint() -> str:
    positions = canonical_biosemi64_head_coordinates()
    payload = [[channel, *(float(value).hex() for value in positions[channel])] for channel in BIOSEMI64_CHANNELS]
    return _sha256_json(payload)


BIOSEMI64_COORDINATE_FINGERPRINT = _coordinate_fingerprint()
BIOSEMI64_SCALP_SET_FINGERPRINT = _sha256_json(sorted(BIOSEMI64_CHANNELS))


def _canonical_retained_channels(channels: Optional[Iterable[str]]) -> tuple[str, ...]:
    if channels is None:
        return BIOSEMI64_CHANNELS
    requested = tuple(channels)
    if not requested:
        raise BioSemi64GeometryError("Retained BioSemi64 scalp channel set is empty.")
    if len(requested) != len(set(requested)):
        raise BioSemi64GeometryError("Retained BioSemi64 scalp channel set has duplicates.")
    unknown = sorted(set(requested).difference(BIOSEMI64_CHANNEL_SET))
    if unknown:
        raise BioSemi64GeometryError("Retained scalp channel(s) are not in BioSemi64: " + ", ".join(unknown))
    requested_set = set(requested)
    return tuple(name for name in BIOSEMI64_CHANNELS if name in requested_set)


def biosemi64_geometry_identity(
    *,
    electrode_mapping_profile: Any = None,
    retained_channels: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Return a fresh JSON-safe identity for canonical or reduced geometry."""

    profile = _normalize_mapping_profile(electrode_mapping_profile)
    retained = _canonical_retained_channels(retained_channels)
    identity: dict[str, Any] = {
        "montage_id": BIOSEMI64_MONTAGE_ID,
        "geometry_version": BIOSEMI64_GEOMETRY_VERSION,
        "coordinate_fingerprint": BIOSEMI64_COORDINATE_FINGERPRINT,
        "canonical_scalp_channels": list(BIOSEMI64_CHANNELS),
        "canonical_scalp_channel_count": len(BIOSEMI64_CHANNELS),
        "canonical_scalp_set_fingerprint": BIOSEMI64_SCALP_SET_FINGERPRINT,
        "electrode_mapping_profile": profile,
        "retained_scalp_channels": list(retained),
        "retained_scalp_channel_count": len(retained),
        "retained_scalp_set_fingerprint": _sha256_json(sorted(retained)),
    }
    identity["geometry_identity_fingerprint"] = _sha256_json(identity)
    return identity


def _unique_name_lookup(channel_names: Sequence[str]) -> dict[str, str]:
    names = tuple(str(name) for name in channel_names)
    if any(not name for name in names):
        raise BioSemi64GeometryError("Recording header contains a blank channel name.")
    lookup: dict[str, str] = {}
    duplicates: list[str] = []
    for name in names:
        folded = name.casefold()
        if folded in lookup:
            duplicates.extend((lookup[folded], name))
        else:
            lookup[folded] = name
    if duplicates:
        raise BioSemi64GeometryError(
            "Recording header contains duplicate channel identities: " + ", ".join(dict.fromkeys(duplicates))
        )
    return lookup


def validate_biosemi64_acquisition_channels(
    channel_names: Sequence[str],
    *,
    ref_pair: Sequence[str],
    stim_name: str,
    electrode_mapping_profile: Any = None,
) -> BioSemi64AcquisitionGeometry:
    """Validate the full acquisition header and resolve names explicitly."""

    names = tuple(str(name) for name in channel_names)
    lookup = _unique_name_lookup(names)
    profile = _normalize_mapping_profile(electrode_mapping_profile)
    anatomical_profile, ab_1020_profile = _mapping_profile_contract()

    non_data_present = [name for name in names if name.upper() in _BIOSEMI_NON_DATA_ELECTRODES]
    if non_data_present:
        raise BioSemi64GeometryError(
            "CMS/DRL are BioSemi mode-sense electrodes, not recorded data channels; "
            "remove these channel identities from the BDF configuration: " + ", ".join(non_data_present)
        )

    if len(ref_pair) != 2 or any(not str(name) for name in ref_pair):
        raise BioSemi64GeometryError("Exactly two BioSemi EXG reference channels are required.")
    if str(ref_pair[0]).casefold() == str(ref_pair[1]).casefold():
        raise BioSemi64GeometryError("BioSemi reference channels must be distinct.")
    if any(str(name).upper() not in _BIOSEMI_AUXILIARY_LABELS for name in ref_pair):
        raise BioSemi64GeometryError("BioSemi64 reference channels must use recorded EXG1 through EXG8 signals.")
    reference_names: list[str] = []
    for requested in ref_pair:
        actual = lookup.get(str(requested).casefold())
        if actual is None:
            raise BioSemi64GeometryError(f"Required BioSemi reference channel {requested!r} is missing.")
        reference_names.append(actual)

    stim_source_name = lookup.get(str(stim_name).casefold())
    if stim_source_name is None:
        raise BioSemi64GeometryError(f"Required stimulation channel {stim_name!r} is missing.")

    direct_sources = {
        actual: _BIOSEMI64_CANONICAL_BY_CASEFOLD[folded]
        for folded, actual in lookup.items()
        if folded in _BIOSEMI64_CANONICAL_BY_CASEFOLD
    }
    ab_sources = {
        actual: _BIOSEMI64_AB_BY_CASEFOLD[folded]
        for folded, actual in lookup.items()
        if folded in _BIOSEMI64_AB_BY_CASEFOLD
    }
    full_direct = set(direct_sources.values()) == BIOSEMI64_CHANNEL_SET
    full_ab = set(ab_sources.values()) == BIOSEMI64_CHANNEL_SET

    if direct_sources and ab_sources:
        raise BioSemi64GeometryError("Recording mixes anatomical and A/B scalp labels; the cap wiring is ambiguous.")
    if profile == anatomical_profile:
        if full_ab:
            raise BioSemi64GeometryError(
                "Recording uses A1-A32/B1-B32 labels. Select the tested "
                f"{ab_1020_profile!r} electrode "
                "mapping profile only for the BioSemi 64 10-20 standard wiring."
            )
        source_to_canonical = direct_sources
    elif profile == ab_1020_profile:
        if full_direct:
            raise BioSemi64GeometryError(
                "Recording already uses anatomical labels but the project requests the A1-A32/B1-B32 mapping profile."
            )
        source_to_canonical = ab_sources
    else:  # The project normalizer is authoritative, but keep this boundary explicit.
        raise BioSemi64GeometryError(f"Unsupported electrode mapping profile {profile!r}.")

    resolved_values = set(source_to_canonical.values())
    if resolved_values != BIOSEMI64_CHANNEL_SET or len(source_to_canonical) != 64:
        missing = [name for name in BIOSEMI64_CHANNELS if name not in resolved_values]
        detail = ", ".join(missing[:8])
        if len(missing) > 8:
            detail += ", ..."
        raise BioSemi64GeometryError(
            "Recording does not contain the exact 64-channel BioSemi 10-20 scalp set"
            + (f"; missing: {detail}" if detail else "")
            + "."
        )

    allowed_auxiliary = {
        *(name.casefold() for name in _BIOSEMI_AUXILIARY_LABELS),
        str(stim_source_name).casefold(),
    }
    scalp_source_set = set(source_to_canonical)
    unknown = [name for name in names if name not in scalp_source_set and name.casefold() not in allowed_auxiliary]
    if unknown:
        raise BioSemi64GeometryError(
            "Recording contains unsupported or custom channel identities: " + ", ".join(unknown)
        )

    scalp_source_names = tuple(name for name in names if name in scalp_source_set)
    scalp_canonical_names = tuple(source_to_canonical[name] for name in scalp_source_names)
    return BioSemi64AcquisitionGeometry(
        source_channel_names=names,
        scalp_source_names=scalp_source_names,
        scalp_canonical_names=scalp_canonical_names,
        source_to_canonical_items=tuple(source_to_canonical.items()),
        reference_source_names=(reference_names[0], reference_names[1]),
        stim_source_name=stim_source_name,
        electrode_mapping_profile=profile,
    )


def read_raw_biosemi64_geometry(raw: Any) -> Optional[dict[str, Any]]:
    """Return a detached runtime geometry identity, if the loader attached one."""

    value = getattr(raw, BIOSEMI64_RUNTIME_ATTRIBUTE, None)
    if not isinstance(value, Mapping):
        return None
    return json.loads(json.dumps(dict(value)))


def _raw_channel_coordinate(raw: Any, channel: str) -> np.ndarray:
    try:
        index = list(raw.ch_names).index(channel)
        return np.asarray(raw.info["chs"][index]["loc"][:3], dtype=float)
    except (AttributeError, KeyError, TypeError, ValueError, IndexError) as error:
        raise BioSemi64GeometryError(f"Could not read the sensor coordinate for {channel}.") from error


def validate_raw_biosemi64_geometry(
    raw: Any,
    *,
    expected_retained_channels: Optional[Iterable[str]] = None,
    require_full: bool = False,
    reference_channels: Sequence[str] = (),
    stim_channel: Optional[str] = None,
    require_runtime_identity: bool = True,
) -> dict[str, Any]:
    """Validate canonical names, finite coordinates, channel roles, and identity."""

    raw_names = tuple(str(name) for name in raw.ch_names)
    _unique_name_lookup(raw_names)
    actual_scalp = tuple(name for name in raw_names if name in BIOSEMI64_CHANNEL_SET)
    if expected_retained_channels is None:
        expected = BIOSEMI64_CHANNELS if require_full else _canonical_retained_channels(actual_scalp)
    else:
        expected = _canonical_retained_channels(expected_retained_channels)
    if require_full and expected != BIOSEMI64_CHANNELS:
        raise BioSemi64GeometryError("A complete BioSemi64 recording must retain all 64 scalp channels.")
    if set(actual_scalp) != set(expected) or len(actual_scalp) != len(expected):
        raise BioSemi64GeometryError("Loaded Raw scalp channels do not match the validated retained BioSemi64 set.")
    canonical_coordinates = canonical_biosemi64_head_coordinates()
    for channel in actual_scalp:
        coordinate = _raw_channel_coordinate(raw, channel)
        if coordinate.shape != (3,) or not np.isfinite(coordinate).all():
            raise BioSemi64GeometryError(f"Loaded Raw has no finite BioSemi64 coordinate for {channel}.")
        expected_coordinate = np.asarray(canonical_coordinates[channel], dtype=float)
        if not np.allclose(coordinate, expected_coordinate, rtol=1e-7, atol=1e-9):
            raise BioSemi64GeometryError(f"Loaded Raw coordinate for {channel} does not match canonical BioSemi64.")

    try:
        channel_types = dict(zip(raw_names, raw.get_channel_types()))
    except (AttributeError, TypeError, ValueError) as error:
        raise BioSemi64GeometryError("Could not validate loaded Raw channel types.") from error
    forbidden_non_data = [name for name in raw_names if name.upper() in _BIOSEMI_NON_DATA_ELECTRODES]
    if forbidden_non_data:
        raise BioSemi64GeometryError(
            "CMS/DRL must remain outside recorded Raw data channels: " + ", ".join(forbidden_non_data)
        )
    allowed_non_scalp_eeg = set(reference_channels)
    unsupported_eeg = [
        name
        for name, channel_type in channel_types.items()
        if channel_type == "eeg" and name not in BIOSEMI64_CHANNEL_SET and name not in allowed_non_scalp_eeg
    ]
    if unsupported_eeg:
        raise BioSemi64GeometryError(
            "Loaded Raw contains unsupported non-BioSemi64 EEG channel(s): " + ", ".join(unsupported_eeg)
        )
    wrong_scalp_types = [name for name in actual_scalp if channel_types.get(name) != "eeg"]
    if wrong_scalp_types:
        raise BioSemi64GeometryError("BioSemi64 scalp channel(s) are not typed as EEG: " + ", ".join(wrong_scalp_types))
    for reference in reference_channels:
        if reference not in channel_types:
            raise BioSemi64GeometryError(f"Loaded Raw is missing reference channel {reference!r}.")
        if channel_types[reference] != "eeg":
            raise BioSemi64GeometryError(f"Reference channel {reference!r} is not typed as EEG.")
        if np.isfinite(_raw_channel_coordinate(raw, reference)).any():
            raise BioSemi64GeometryError(f"Reference channel {reference!r} must remain coordinate-free.")
    if stim_channel is not None and channel_types.get(stim_channel) != "stim":
        raise BioSemi64GeometryError(f"Stimulation channel {stim_channel!r} is not typed as stim.")

    stored = read_raw_biosemi64_geometry(raw)
    expected_identity = biosemi64_geometry_identity(
        electrode_mapping_profile=(stored.get("electrode_mapping_profile") if stored else None),
        retained_channels=expected,
    )
    if require_runtime_identity:
        if stored is None:
            raise BioSemi64GeometryError("Loaded Raw has no FPVS geometry identity.")
        comparison_keys = (
            "montage_id",
            "geometry_version",
            "coordinate_fingerprint",
            "canonical_scalp_set_fingerprint",
            "electrode_mapping_profile",
            "retained_scalp_channels",
            "retained_scalp_set_fingerprint",
            "geometry_identity_fingerprint",
        )
        if any(stored.get(key) != expected_identity.get(key) for key in comparison_keys):
            raise BioSemi64GeometryError("Loaded Raw geometry identity does not match its BioSemi64 channels.")
    return stored or expected_identity


def attach_raw_biosemi64_geometry(
    raw: Any,
    *,
    electrode_mapping_profile: Any,
    retained_channels: Iterable[str],
    reference_channels: Sequence[str] = (),
    stim_channel: Optional[str] = None,
) -> dict[str, Any]:
    """Validate and attach the canonical runtime identity to an MNE Raw."""

    retained = _canonical_retained_channels(retained_channels)
    validate_raw_biosemi64_geometry(
        raw,
        expected_retained_channels=retained,
        reference_channels=reference_channels,
        stim_channel=stim_channel,
        require_runtime_identity=False,
    )
    identity = biosemi64_geometry_identity(
        electrode_mapping_profile=electrode_mapping_profile,
        retained_channels=retained,
    )
    setattr(raw, BIOSEMI64_RUNTIME_ATTRIBUTE, identity)
    return read_raw_biosemi64_geometry(raw) or identity


__all__ = [
    "BIOSEMI64_1020_AB_CHANNEL_MAP",
    "BIOSEMI64_CHANNELS",
    "BIOSEMI64_CHANNEL_SET",
    "BIOSEMI64_COORDINATE_FINGERPRINT",
    "BIOSEMI64_GEOMETRY_VERSION",
    "BIOSEMI64_MONTAGE_ID",
    "BIOSEMI64_RUNTIME_ATTRIBUTE",
    "BIOSEMI64_SCALP_SET_FINGERPRINT",
    "BioSemi64AcquisitionGeometry",
    "BioSemi64GeometryError",
    "attach_raw_biosemi64_geometry",
    "biosemi64_geometry_identity",
    "canonical_biosemi64_head_coordinates",
    "cached_biosemi64_montage",
    "read_raw_biosemi64_geometry",
    "validate_biosemi64_acquisition_channels",
    "validate_raw_biosemi64_geometry",
]
