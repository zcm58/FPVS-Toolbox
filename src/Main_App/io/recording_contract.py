"""Immutable recording facts and method choices consumed by processing.

This contract deliberately contains no manufacturer, native-format reader, or
montage-template selection logic. The acquisition boundary resolves those
details before attaching a contract to an MNE recording.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import mne


@dataclass(frozen=True)
class RecordingContract:
    """Resolved channel roles, methods, geometry, and qualified capabilities."""

    initial_reference_mode: str
    initial_reference_channels: tuple[str, ...]
    drop_reference_channels: bool
    max_idx_keep: int | None
    canonical_scalp_order: tuple[str, ...] | None
    recorded_channel_geometry: bool
    kurtosis_screening_supported: bool
    strict_processing_errors: bool
    geometry_fingerprint: str
    acquisition_label: str = "EEG"
    marker_impulses: bool = False
    acquisition_fingerprint: str = ""
    provenance_json: str = ""
    montage_id: str = ""
    mapping_profile: str = ""
    fingerprint_montage: Any = ""
    fingerprint_mapping: Any = ""
    stim_channel: str = ""
    load_reference_channels: tuple[str, ...] = ()
    review_reference_pair: tuple[str, str] = ("", "")
    channel_limit: int | None = None
    geometry_json: str = ""
    raw_screening_supported: bool = False
    removed_electrode_screening_supported: bool = False
    condition_repair_supported: bool = False
    supports_template_spatial_tools: bool = False
    qualified_spatial_model_label: str = ""

    @property
    def event_kwargs(self) -> dict[str, bool]:
        return {"initial_event": True, "consecutive": True} if self.marker_impulses else {}

    @property
    def provenance(self) -> dict[str, Any]:
        """Detached historical provenance; its labels are opaque to processing."""
        return json.loads(self.provenance_json) if self.provenance_json else {}

    @property
    def geometry(self) -> dict[str, Any]:
        return json.loads(self.geometry_json) if self.geometry_json else {}

    @property
    def spatial_qc_supported(self) -> bool:
        return self.supports_template_spatial_tools

    def scalp_channels(self, raw: Any) -> list[str]:
        if self.canonical_scalp_order is None:
            return [raw.ch_names[int(pick)] for pick in mne.pick_types(raw.info, eeg=True, exclude=[])]
        canonical = set(self.canonical_scalp_order)
        return [name for name in raw.ch_names if name in canonical]

    def ordered_scalp_channels(self, raw: Any) -> list[str]:
        channels = self.scalp_channels(raw)
        if self.canonical_scalp_order is None:
            return channels
        present = set(channels)
        return [name for name in self.canonical_scalp_order if name in present]

    def validate(self, raw: Any, params: Mapping[str, Any]) -> None:
        from Main_App.io.acquisition_metadata import validate_processing_geometry

        validate_processing_geometry(raw, self)
        self.validate_qc(params)

    def validate_qc(self, params: Mapping[str, Any]) -> None:
        if not self.kurtosis_screening_supported and params.get("kurtosis_screening_enabled", False):
            raise ValueError(f"Normalized kurtosis screening is not qualified for {self.acquisition_label} montages; disable it in project settings.")
