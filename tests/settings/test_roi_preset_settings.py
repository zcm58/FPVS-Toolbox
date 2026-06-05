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
            ("LOT", ["bad"]),
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
        ("LOT", ["P7", "P9", "PO7", "PO3", "O1"]),
        ("ROT", ["P8", "P10", "PO8", "PO4", "O2"]),
        ("Central", ["FCZ", "CZ", "CPZ", "CP1", "C1", "FC1"]),
    ]


def test_legacy_lobe_roi_defaults_migrate_to_semantic_defaults(tmp_path) -> None:
    path = tmp_path / "settings.ini"
    path.write_text(
        "\n".join(
            [
                "[rois]",
                "montage = 10-10",
                "names = Frontal Lobe;Central Lobe;Parietal Lobe;Occipital Lobe",
                "electrodes = F3,F4,Fz;C3,C4,Cz;P3,P4,Pz;O1,O2,Oz",
            ]
        ),
        encoding="utf-8",
    )

    manager = SettingsManager(str(path))

    assert manager.get_roi_pairs() == [
        ("LOT", ["P7", "P9", "PO7", "PO3", "O1"]),
        ("ROT", ["P8", "P10", "PO8", "PO4", "O2"]),
        ("Central", ["FCZ", "CZ", "CPZ", "CP1", "C1", "FC1"]),
    ]
