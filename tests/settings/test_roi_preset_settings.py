from __future__ import annotations

import pytest

from Main_App.Shared.roi_presets import ROI_MONTAGE_10_10, default_roi_presets
from Main_App.Shared.settings_manager import SettingsManager


def test_custom_roi_presets_roundtrip_excludes_default_names(tmp_path) -> None:
    manager = SettingsManager(str(tmp_path / "settings.ini"))
    manager.set_roi_montage(ROI_MONTAGE_10_10)
    manager.set_custom_roi_presets(
        ROI_MONTAGE_10_10,
        [
            ("Custom Occipito Temporal", ["po7", "po8"]),
            ("Frontal Lobe", ["bad"]),
        ],
    )
    manager.save()

    restored = SettingsManager(str(tmp_path / "settings.ini"))

    assert restored.get_roi_montage() == ROI_MONTAGE_10_10
    assert restored.get_custom_roi_presets(ROI_MONTAGE_10_10) == [
        ("Custom Occipito Temporal", ["PO7", "PO8"]),
    ]


def test_roi_preset_montage_validation_is_explicit(tmp_path) -> None:
    manager = SettingsManager(str(tmp_path / "settings.ini"))

    with pytest.raises(ValueError, match="Unsupported ROI montage"):
        manager.set_roi_montage("unsupported")


def test_10_10_default_roi_presets_are_available() -> None:
    presets = default_roi_presets(ROI_MONTAGE_10_10)

    assert [(preset.name, list(preset.electrodes)) for preset in presets] == [
        ("Frontal Lobe", ["F3", "F4", "FZ"]),
        ("Central Lobe", ["C3", "C4", "CZ"]),
        ("Parietal Lobe", ["P3", "P4", "PZ"]),
        ("Occipital Lobe", ["O1", "O2", "OZ"]),
    ]
