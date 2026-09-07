from __future__ import annotations

import pytest

from Main_App.Shared.roi_presets import (
    ROI_MONTAGE_BIOSEMI64,
    default_roi_presets,
    supported_roi_montages,
)
from Main_App.Shared.settings_manager import SettingsManager


def test_custom_roi_presets_roundtrip_excludes_default_names(tmp_path) -> None:
    manager = SettingsManager(str(tmp_path / "settings.ini"))
    manager.set_roi_montage(ROI_MONTAGE_BIOSEMI64)
    manager.set_custom_roi_presets(
        ROI_MONTAGE_BIOSEMI64,
        [
            ("Custom Occipito Temporal", ["po7", "po8"]),
            ("LOT", ["bad"]),
        ],
    )
    manager.save()

    restored = SettingsManager(str(tmp_path / "settings.ini"))

    assert restored.get_roi_montage() == ROI_MONTAGE_BIOSEMI64
    assert restored.get_custom_roi_presets(ROI_MONTAGE_BIOSEMI64) == [
        ("Custom Occipito Temporal", ["PO7", "PO8"]),
    ]


@pytest.mark.parametrize("montage", ["unsupported", "10-10", "standard_1020"])
def test_roi_preset_montage_validation_is_explicit(tmp_path, montage) -> None:
    manager = SettingsManager(str(tmp_path / "settings.ini"))

    with pytest.raises(ValueError, match="Unsupported ROI montage"):
        manager.set_roi_montage(montage)
    with pytest.raises(ValueError, match="Unsupported ROI montage"):
        manager.set_custom_roi_presets(montage, [("Custom", ["P7"])])


def test_biosemi64_default_roi_presets_preserve_electrodes() -> None:
    presets = default_roi_presets(ROI_MONTAGE_BIOSEMI64)

    assert [(preset.name, list(preset.electrodes)) for preset in presets] == [
        ("LOT", ["P7", "P9", "PO7", "PO3", "O1"]),
        ("ROT", ["P8", "P10", "PO8", "PO4", "O2"]),
        ("Central", ["FCZ", "CZ", "CPZ", "CP1", "C1", "FC1"]),
    ]


def test_biosemi64_is_the_only_supported_roi_montage() -> None:
    assert supported_roi_montages() == ((ROI_MONTAGE_BIOSEMI64, "BioSemi 64"),)


def test_fresh_settings_rois_match_the_canonical_default_catalog(tmp_path) -> None:
    manager = SettingsManager(str(tmp_path / "settings.ini"))

    assert manager.get_roi_pairs() == [
        (preset.name, list(preset.electrodes))
        for preset in default_roi_presets(ROI_MONTAGE_BIOSEMI64)
    ]


def test_roi_pair_schema_preserves_row_and_duplicate_electrode_order(tmp_path) -> None:
    path = tmp_path / "settings.ini"
    manager = SettingsManager(str(path))
    manager.set_roi_pairs(
        [
            ("First", ["o2", "O1", "o2", "CustomAux"]),
            ("First", ["cz"]),
        ]
    )
    manager.save()

    restored = SettingsManager(str(path))

    assert restored.get_roi_pairs() == [
        ("First", ["O2", "O1", "O2", "CUSTOMAUX"]),
        ("First", ["CZ"]),
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


def test_legacy_roi_montage_keeps_custom_presets_and_current_rois(tmp_path) -> None:
    path = tmp_path / "settings.ini"
    original = (
        "[rois]\n"
        "montage = 10-10\n"
        "names = My ROI\n"
        "electrodes = P7,PO7\n"
        "[roi_presets]\n"
        'custom_10_10 = [{"name": "My preset", "electrodes": ["PO7", "PO8"]}]\n'
    )
    path.write_text(original, encoding="utf-8")

    manager = SettingsManager(str(path))

    assert manager.get_roi_montage() == "biosemi64"
    assert manager.get_roi_pairs() == [("My ROI", ["P7", "PO7"])]
    assert manager.get_custom_roi_presets() == [("My preset", ["PO7", "PO8"])]
    assert path.read_text(encoding="utf-8") == original

    manager.set_roi_montage("biosemi64")
    manager.set_custom_roi_presets("biosemi64", manager.get_custom_roi_presets())
    manager.save()
    restored = SettingsManager(str(path))
    assert restored.get_custom_roi_presets() == [("My preset", ["PO7", "PO8"])]
    assert restored.get_roi_pairs() == [("My ROI", ["P7", "PO7"])]


@pytest.mark.parametrize("presets", [[], [("Replacement", ["C3", "C4"])]])
def test_canonical_custom_presets_take_precedence_over_legacy(tmp_path, presets) -> None:
    path = tmp_path / "settings.ini"
    manager = SettingsManager(str(path))
    manager.set(
        "roi_presets", "custom_10_10",
        '[{"name": "Old preset", "electrodes": ["PO7", "PO8"]}]',
    )
    manager.set_custom_roi_presets("biosemi64", presets)
    manager.save()

    assert SettingsManager(str(path)).get_custom_roi_presets() == presets
