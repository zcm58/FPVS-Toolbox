"""Neutral ROI settings and immutable analysis snapshots.

The application-level ROI editor remains the source of definitions in v3.
This module gives processing callers a strict, frozen representation so a
later edit cannot silently change the identity of an existing analysis.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from Main_App.io import (
    BIOSEMI64_CHANNELS,
    BIOSEMI64_COORDINATE_FINGERPRINT,
    BIOSEMI64_GEOMETRY_VERSION,
    BIOSEMI64_SCALP_SET_FINGERPRINT,
)

ALL_ROIS_OPTION = "(All ROIs)"
ROI_DEFINITION_SNAPSHOT_VERSION = "roi_definition_snapshot_v1"
ROI_DEFINITION_SOURCE_APPLICATION_GLOBAL_SETTINGS = "application_global_settings"

_CANONICAL_CHANNEL_BY_CASEFOLD = {
    channel.casefold(): channel for channel in BIOSEMI64_CHANNELS
}


class RoiDefinitionError(ValueError):
    """An ROI definition cannot be represented without ambiguity or loss."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _normalize_roi_name(value: object) -> str:
    if not isinstance(value, str):
        raise RoiDefinitionError("ROI names must be text.")
    name = value.strip()
    if not name:
        raise RoiDefinitionError("ROI names cannot be blank.")
    return name


def _normalize_roi_members(value: object, *, roi_name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RoiDefinitionError(
            f"ROI {roi_name!r} electrodes must be an ordered list or tuple."
        )
    if not value:
        raise RoiDefinitionError(f"ROI {roi_name!r} must contain at least one electrode.")

    members: list[str] = []
    seen: set[str] = set()
    for index, raw_member in enumerate(value, start=1):
        if not isinstance(raw_member, str):
            raise RoiDefinitionError(
                f"ROI {roi_name!r} electrode {index} must be text."
            )
        submitted = raw_member.strip()
        if not submitted:
            raise RoiDefinitionError(
                f"ROI {roi_name!r} contains a blank electrode at position {index}."
            )
        canonical = _CANONICAL_CHANNEL_BY_CASEFOLD.get(submitted.casefold())
        if canonical is None:
            raise RoiDefinitionError(
                f"ROI {roi_name!r} contains unknown BioSemi64 electrode {submitted!r}."
            )
        if canonical in seen:
            raise RoiDefinitionError(
                f"ROI {roi_name!r} repeats electrode {canonical!r}."
            )
        seen.add(canonical)
        members.append(canonical)
    return tuple(members)


@dataclass(frozen=True, slots=True)
class RoiDefinition:
    """One named, ordered, unique BioSemi64 electrode set."""

    name: str
    electrodes: tuple[str, ...]

    def __post_init__(self) -> None:
        name = _normalize_roi_name(self.name)
        electrodes = _normalize_roi_members(self.electrodes, roi_name=name)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "electrodes", electrodes)

    def to_payload(self) -> dict[str, object]:
        return {"name": self.name, "electrodes": list(self.electrodes)}


@dataclass(frozen=True, slots=True)
class RoiDefinitionSnapshot:
    """Versioned ROI definitions frozen for one analysis identity."""

    rois: tuple[RoiDefinition, ...]
    snapshot_version: str = field(
        default=ROI_DEFINITION_SNAPSHOT_VERSION,
        init=False,
    )
    source: str = field(
        default=ROI_DEFINITION_SOURCE_APPLICATION_GLOBAL_SETTINGS,
        init=False,
    )
    geometry_version: str = field(
        default=BIOSEMI64_GEOMETRY_VERSION,
        init=False,
    )
    geometry_fingerprint: str = field(
        default=BIOSEMI64_COORDINATE_FINGERPRINT,
        init=False,
    )
    canonical_scalp_set_fingerprint: str = field(
        default=BIOSEMI64_SCALP_SET_FINGERPRINT,
        init=False,
    )
    fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        rois = tuple(self.rois)
        if any(not isinstance(roi, RoiDefinition) for roi in rois):
            raise RoiDefinitionError(
                "ROI snapshots must contain validated RoiDefinition values."
            )
        seen_names: dict[str, str] = {}
        for roi in rois:
            folded = roi.name.casefold()
            previous = seen_names.get(folded)
            if previous is not None:
                raise RoiDefinitionError(
                    f"ROI names must be unique ignoring case: {previous!r} and {roi.name!r}."
                )
            seen_names[folded] = roi.name
        object.__setattr__(self, "rois", rois)
        object.__setattr__(self, "fingerprint", _fingerprint(self._identity_payload()))

    def _identity_payload(self) -> dict[str, object]:
        return {
            "snapshot_version": self.snapshot_version,
            "source": self.source,
            "geometry_version": self.geometry_version,
            "geometry_fingerprint": self.geometry_fingerprint,
            "canonical_scalp_set_fingerprint": self.canonical_scalp_set_fingerprint,
            "rois": [roi.to_payload() for roi in self.rois],
        }

    def to_payload(self) -> dict[str, object]:
        payload = self._identity_payload()
        payload["fingerprint"] = self.fingerprint
        return payload

    def as_mapping(self) -> dict[str, list[str]]:
        """Return a detached compatibility mapping for existing consumers."""

        return {roi.name: list(roi.electrodes) for roi in self.rois}


def _iter_strict_roi_pairs(raw_pairs: object) -> tuple[tuple[object, object], ...]:
    if raw_pairs is None:
        return ()
    if isinstance(raw_pairs, Mapping):
        return tuple(raw_pairs.items())
    if not isinstance(raw_pairs, Sequence) or isinstance(
        raw_pairs,
        (str, bytes, bytearray),
    ):
        raise RoiDefinitionError(
            "ROI settings must be an ordered sequence of name/electrode pairs or a mapping."
        )

    pairs: list[tuple[object, object]] = []
    for index, raw_pair in enumerate(raw_pairs, start=1):
        if not isinstance(raw_pair, Sequence) or isinstance(
            raw_pair,
            (str, bytes, bytearray),
        ):
            raise RoiDefinitionError(f"ROI entry {index} is not a name/electrode pair.")
        if len(raw_pair) != 2:
            raise RoiDefinitionError(
                f"ROI entry {index} must contain exactly a name and an electrode list."
            )
        pairs.append((raw_pair[0], raw_pair[1]))
    return tuple(pairs)


def build_roi_definition_snapshot(raw_pairs: object) -> RoiDefinitionSnapshot:
    """Validate and freeze ordered application-level ROI settings."""

    definitions = tuple(
        RoiDefinition(name=raw_name, electrodes=raw_electrodes)
        for raw_name, raw_electrodes in _iter_strict_roi_pairs(raw_pairs)
    )
    return RoiDefinitionSnapshot(rois=definitions)


def _settings_manager(manager: Any = None) -> Any:
    if manager is not None:
        return manager
    from Main_App.Shared.settings_manager import SettingsManager

    return SettingsManager()


def snapshot_rois_from_settings(manager: Any = None) -> RoiDefinitionSnapshot:
    """Read, strictly validate, and freeze the current global ROI definitions."""

    mgr = _settings_manager(manager)
    get_roi_pairs = getattr(mgr, "get_roi_pairs", None)
    if not callable(get_roi_pairs):
        raise RoiDefinitionError("The settings provider does not expose ROI pairs.")
    try:
        raw_pairs = get_roi_pairs()
    except Exception as error:  # noqa: BLE001 - settings-provider boundary
        raise RoiDefinitionError("The application ROI settings could not be read.") from error
    return build_roi_definition_snapshot(raw_pairs)


def load_rois_from_settings(manager: Any = None) -> dict[str, list[str]]:
    """Return current ROI definitions, cleaned for compatibility callers.

    This tolerant adapter preserves the existing user workflow. New analysis
    code should call :func:`snapshot_rois_from_settings` so malformed settings
    fail explicitly instead of being silently shortened.
    """

    mgr = _settings_manager(manager)
    rois_from_settings = None

    try:
        get_roi_pairs = getattr(mgr, "get_roi_pairs", None)
        if callable(get_roi_pairs):
            pairs = get_roi_pairs() or []
            if isinstance(pairs, Mapping):
                rois_from_settings = dict(pairs)
            else:
                rois_from_settings = {
                    name: electrodes for name, electrodes in pairs
                }
    except Exception:  # noqa: BLE001 - settings-provider compatibility boundary
        rois_from_settings = None

    if rois_from_settings is None:
        return {}

    cleaned: dict[str, list[str]] = {}
    for raw_name, raw_values in rois_from_settings.items():
        name = str(raw_name).strip()
        if not name or not isinstance(raw_values, (list, tuple)):
            continue
        cleaned[name] = [
            str(electrode).strip()
            for electrode in raw_values
            if str(electrode).strip()
        ]
    return cleaned


__all__ = [
    "ALL_ROIS_OPTION",
    "ROI_DEFINITION_SNAPSHOT_VERSION",
    "ROI_DEFINITION_SOURCE_APPLICATION_GLOBAL_SETTINGS",
    "RoiDefinition",
    "RoiDefinitionError",
    "RoiDefinitionSnapshot",
    "build_roi_definition_snapshot",
    "load_rois_from_settings",
    "snapshot_rois_from_settings",
]
