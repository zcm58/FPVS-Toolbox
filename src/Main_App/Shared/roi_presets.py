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
        ROIPreset("Frontal Lobe", ("F3", "F4", "FZ")),
        ROIPreset("Central Lobe", ("C3", "C4", "CZ")),
        ROIPreset("Parietal Lobe", ("P3", "P4", "PZ")),
        ROIPreset("Occipital Lobe", ("O1", "O2", "OZ")),
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
