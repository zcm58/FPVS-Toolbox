from __future__ import annotations

from dataclasses import dataclass

ROI_MONTAGE_10_10 = "10-10"
DEFAULT_ROI_MONTAGE = ROI_MONTAGE_10_10

SUPPORTED_ROI_MONTAGES: tuple[tuple[str, str], ...] = (
    (ROI_MONTAGE_10_10, "10-10 International"),
)


@dataclass(frozen=True)
class ROIPreset:
    name: str
    electrodes: tuple[str, ...]


DEFAULT_ROI_PRESETS_BY_MONTAGE: dict[str, tuple[ROIPreset, ...]] = {
    ROI_MONTAGE_10_10: (
        ROIPreset("LOT", ("P7", "P9", "PO7", "PO3", "O1")),
        ROIPreset("ROT", ("P8", "P10", "PO8", "PO4", "O2")),
        ROIPreset("Central", ("FCZ", "CZ", "CPZ", "CP1", "C1", "FC1")),
    ),
}


def supported_roi_montages() -> tuple[tuple[str, str], ...]:
    return SUPPORTED_ROI_MONTAGES


def validate_roi_montage(montage: str) -> str:
    montage_key = str(montage).strip()
    supported = {key for key, _label in SUPPORTED_ROI_MONTAGES}
    if montage_key not in supported:
        raise ValueError(f"Unsupported ROI montage: {montage!r}")
    return montage_key


def default_roi_presets(montage: str) -> tuple[ROIPreset, ...]:
    montage_key = validate_roi_montage(montage)
    return DEFAULT_ROI_PRESETS_BY_MONTAGE[montage_key]


def default_roi_name_keys(montage: str) -> set[str]:
    return {preset.name.casefold() for preset in default_roi_presets(montage)}
