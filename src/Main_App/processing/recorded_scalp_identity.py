"""Immutable retained-channel coverage identity for recorded EEG montages."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from Main_App.processing.recorded_cohort_geometry import validate_recorded_spectral_geometry_identity


@dataclass(frozen=True, slots=True)
class RecordedScalpIdentity:
    """Freeze geometry as JSON so later callers cannot mutate its coordinates."""

    geometry_json: str

    @classmethod
    def from_geometry(cls, value: Mapping[str, Any]) -> "RecordedScalpIdentity":
        geometry = validate_recorded_spectral_geometry_identity(value)
        return cls(json.dumps(geometry, sort_keys=True, separators=(",", ":")))

    def __post_init__(self) -> None:
        validate_recorded_spectral_geometry_identity(json.loads(self.geometry_json))

    @property
    def geometry(self) -> dict[str, Any]:
        return json.loads(self.geometry_json)

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(self.geometry["retained_scalp_channels"])

    @property
    def montage_id(self) -> str:
        return self.geometry["montage_id"]

    @property
    def geometry_version(self) -> str:
        return self.geometry["geometry_version"]

    @property
    def coordinate_fingerprint(self) -> str:
        return self.geometry["coordinate_fingerprint"]

    @property
    def canonical_scalp_set_fingerprint(self) -> str:
        return self.geometry["canonical_scalp_set_fingerprint"]

    @property
    def retained_scalp_set_fingerprint(self) -> str:
        return self.geometry["retained_scalp_set_fingerprint"]

    def _identity_payload(self) -> dict[str, Any]:
        geometry = self.geometry
        return {
            key: geometry[key] for key in (
                "montage_id", "geometry_version", "coordinate_fingerprint",
                "canonical_scalp_set_fingerprint", "retained_scalp_channels",
                "retained_scalp_set_fingerprint",
            )
        } | {"recorded_geometry": geometry}

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self._identity_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_payload(self) -> dict[str, Any]:
        return self._identity_payload() | {"fingerprint": self.fingerprint}
