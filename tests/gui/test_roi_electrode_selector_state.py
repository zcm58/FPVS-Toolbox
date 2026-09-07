from __future__ import annotations

import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.Shared.roi_presets import ROI_MONTAGE_BIOSEMI64, default_roi_presets
from Main_App.gui.roi_electrode_selector_state import (
    BIOSEMI64_LABELS,
    BIOSEMI64_POLAR_COORDINATES,
    ROIElectrodeSelectionState,
    electrode_logical_position,
    split_electrode_text,
)
from Main_App.gui.roi_visual_editor_state import (
    ROI_COLOR_PALETTE,
    ROIEditorCollection,
    roi_color_for_id,
)


DEFAULT_ROIS = tuple(
    (preset.name, preset.electrodes)
    for preset in default_roi_presets(ROI_MONTAGE_BIOSEMI64)
)


def test_biosemi64_catalog_matches_fpvs_canonical_channels_case_insensitively() -> None:
    assert len(BIOSEMI64_POLAR_COORDINATES) == 64
    assert len({label.casefold() for label in BIOSEMI64_LABELS}) == 64
    assert {label.casefold() for label in BIOSEMI64_LABELS} == {
        label.casefold() for label in DEFAULT_ELECTRODE_NAMES_64
    }

    positions = {
        label: electrode_logical_position(theta, phi)
        for label, theta, phi in BIOSEMI64_POLAR_COORDINATES
    }
    assert positions["Fp1"][1] < positions["O1"][1]
    assert positions["C3"][0] < positions["Cz"][0] < positions["C4"][0]


def test_noop_selection_preserves_order_case_duplicates_and_unmapped_labels() -> None:
    original = ("custom-a", "cz", "CZ", "X1", "X1", "O2")
    state = ROIElectrodeSelectionState(DEFAULT_ELECTRODE_NAMES_64, original)

    assert state.is_selected("cZ")
    assert state.unmapped_electrodes() == ("custom-a", "X1", "X1")
    assert state.selected_electrodes() == original
    assert state.is_changed() is False

    state.set_checked("CZ", False)
    state.set_checked("cz", True)
    assert state.selected_electrodes() == original
    assert state.is_changed() is False


def test_changed_selection_keeps_survivors_and_appends_new_nodes_in_catalog_order() -> None:
    state = ROIElectrodeSelectionState(
        DEFAULT_ELECTRODE_NAMES_64,
        ("X1", "O2", "cz", "CZ"),
    )

    state.set_checked("O2", False)
    state.set_checked("P10", True)
    state.set_checked("Fp1", True)

    assert state.selected_electrodes() == ("X1", "cz", "CZ", "Fp1", "P10")
    assert state.is_changed() is True


def test_unmapped_labels_are_preserved_until_explicitly_removed() -> None:
    state = ROIElectrodeSelectionState(DEFAULT_ELECTRODE_NAMES_64, ("O1", "Aux1", "Aux1"))

    state.set_checked("O2", True)
    assert state.selected_electrodes() == ("O1", "Aux1", "Aux1", "O2")

    promoted = state.set_unmapped(("Aux1", "cz", "NewAux"))
    assert promoted == ("Cz",)
    assert state.unmapped_electrodes() == ("Aux1", "NewAux")
    assert state.selected_electrodes() == ("O1", "Aux1", "Cz", "O2", "NewAux")


def test_preset_replaces_draft_without_importing_preset_order_or_dropping_unknowns() -> None:
    state = ROIElectrodeSelectionState(DEFAULT_ELECTRODE_NAMES_64, ("Cz", "LegacyAux"))

    unmapped = state.replace_with(("P10", "fp1", "CustomAux"))

    assert unmapped == ("CustomAux",)
    assert state.selected_map_labels() == ("Fp1", "P10")
    assert state.selected_electrodes() == ("Fp1", "P10", "CustomAux")


def test_preset_and_text_promotion_preserve_duplicate_canonical_entries() -> None:
    state = ROIElectrodeSelectionState(DEFAULT_ELECTRODE_NAMES_64, ())

    state.replace_with(("O1", "o1", "LegacyAux", "LegacyAux"))
    assert state.selected_electrodes() == ("O1", "O1", "LegacyAux", "LegacyAux")

    state = ROIElectrodeSelectionState(DEFAULT_ELECTRODE_NAMES_64, ())
    promoted = state.set_unmapped(("o1", "O1", "LegacyAux"))
    assert promoted == ("O1", "O1")
    assert state.selected_electrodes() == ("O1", "O1", "LegacyAux")


def test_unmapped_preview_preserves_canonical_multiplicity_and_order() -> None:
    state = ROIElectrodeSelectionState(
        DEFAULT_ELECTRODE_NAMES_64,
        ("cz", "CZ", "LegacyAux"),
    )

    assert state.preview_electrodes(("Other",)) == ("cz", "CZ", "Other")
    assert state.preview_electrodes(("Cz", "Other")) == (
        "cz",
        "CZ",
        "Cz",
        "Other",
    )
    assert state.selected_electrodes() == ("cz", "CZ", "LegacyAux")


def test_text_parser_and_canonical_identity_do_not_silently_deduplicate() -> None:
    assert split_electrode_text(" O1, o1, X1, ,X1 ") == ("O1", "o1", "X1", "X1")

    with pytest.raises(ValueError, match="unique case-insensitively"):
        ROIElectrodeSelectionState(("Cz", "cz"), ())


def test_editor_collection_preserves_duplicate_rows_identity_and_isolation() -> None:
    collection = ROIEditorCollection(DEFAULT_ELECTRODE_NAMES_64)
    collection.reset(
        [
            ("Shared", ("cz", "CZ", "LegacyAux")),
            ("Shared", ("Cz", "O2")),
        ]
    )
    first_id, second_id = (entry.entry_id for entry in collection.entries)

    assert first_id != second_id
    assert collection.get_pairs() == [
        ("Shared", ["CZ", "CZ", "LEGACYAUX"]),
        ("Shared", ["CZ", "O2"]),
    ]

    collection.entries[1].selection.set_checked("Cz", False)
    assert collection.entries[0].selection.selected_electrodes() == (
        "cz",
        "CZ",
        "LegacyAux",
    )

    assert collection.entries[0].entry_id == first_id
    assert collection.entries[1].entry_id == second_id
    assert collection.entries[1].selection.selected_electrodes() == ("O2",)

    removed, new_index, appended_blank = collection.remove(0)
    assert removed.entry_id == first_id
    assert collection.entries[0].entry_id == second_id
    assert (new_index, appended_blank) == (0, False)


def test_editor_collection_reuses_blank_placeholder_and_restores_one_when_empty() -> None:
    collection = ROIEditorCollection(DEFAULT_ELECTRODE_NAMES_64)
    collection.reset([])
    placeholder_id = collection.entries[0].entry_id

    collection.entries[0].name = "Mapped"
    collection.entries[0].selection.set_checked("O1", True)
    assert collection.entries[0].entry_id == placeholder_id

    removed, new_index, appended_blank = collection.remove(0)
    assert removed.entry_id == placeholder_id
    assert (new_index, appended_blank) == (0, True)
    assert len(collection.entries) == 1
    assert collection.entries[0].entry_id != placeholder_id
    assert collection.entries[0].display_name == "Untitled ROI"


def test_editor_collection_partial_validation_allows_only_wholly_blank_placeholder() -> None:
    collection = ROIEditorCollection(DEFAULT_ELECTRODE_NAMES_64)
    collection.reset([])
    assert collection.first_partial_index() is None

    collection.entries[0].selection.set_checked("O1", True)
    assert collection.first_partial_index() == 0

    collection.reset([("Named", ())])
    assert collection.first_partial_index() == 0

    collection.reset([("", ("O1",))])
    assert collection.first_partial_index() == 0

    collection.reset([("Mapped", ("O1",))])
    assert collection.first_partial_index() is None


def test_editor_collection_appends_only_missing_defaults_without_reordering_saved_rows() -> None:
    collection = ROIEditorCollection(DEFAULT_ELECTRODE_NAMES_64)
    collection.reset(
        [
            ("Custom first", ("O1",)),
            ("ROT", ("O2", "LegacyAux")),
            ("Custom last", ("Cz",)),
        ],
        default_pairs=DEFAULT_ROIS,
    )

    assert [entry.name for entry in collection.entries] == [
        "Custom first",
        "ROT",
        "Custom last",
        "LOT",
        "Central",
    ]
    assert [entry.is_default for entry in collection.entries] == [
        False,
        True,
        False,
        True,
        True,
    ]
    assert collection.get_pairs() == [
        ("Custom first", ["O1"]),
        ("ROT", ["O2", "LEGACYAUX"]),
        ("Custom last", ["CZ"]),
        ("LOT", ["P7", "P9", "PO7", "PO3", "O1"]),
        ("Central", ["FCZ", "CZ", "CPZ", "CP1", "C1", "FC1"]),
    ]


def test_editor_collection_appends_all_defaults_to_an_empty_draft_in_catalog_order() -> None:
    collection = ROIEditorCollection(DEFAULT_ELECTRODE_NAMES_64)

    collection.reset([], default_pairs=DEFAULT_ROIS)

    assert [entry.name for entry in collection.entries] == ["LOT", "ROT", "Central"]
    assert all(entry.is_default for entry in collection.entries)
    assert collection.get_pairs() == [
        (name, [electrode.upper() for electrode in electrodes])
        for name, electrodes in DEFAULT_ROIS
    ]


def test_editor_collection_protects_last_canonical_duplicate_and_not_long_name_aliases() -> None:
    collection = ROIEditorCollection(DEFAULT_ELECTRODE_NAMES_64)
    collection.reset(
        [
            ("LOT", ("O1",)),
            ("Left Occipito-Temporal", ("PO7",)),
            ("lot", ("O2", "O2")),
            ("Right Occipito-Temporal", ("PO8",)),
        ],
        default_pairs=DEFAULT_ROIS,
    )

    assert [entry.name for entry in collection.entries] == [
        "LOT",
        "Left Occipito-Temporal",
        "lot",
        "Right Occipito-Temporal",
        "ROT",
        "Central",
    ]
    assert [entry.is_default for entry in collection.entries] == [
        False,
        False,
        True,
        False,
        True,
        True,
    ]
    assert collection.entries[2].selection.selected_electrodes() == ("O2", "O2")

    removed, new_index, appended_blank = collection.remove(0)
    assert removed.name == "LOT"
    assert (new_index, appended_blank) == (0, False)
    with pytest.raises(ValueError, match="Default ROIs cannot be removed"):
        collection.remove(1)


def test_empty_protected_default_is_partial_and_identity_is_not_persisted() -> None:
    collection = ROIEditorCollection(DEFAULT_ELECTRODE_NAMES_64)
    collection.reset([], default_pairs=DEFAULT_ROIS)

    collection.entries[0].selection.clear()

    assert collection.entries[0].is_default is True
    assert collection.first_partial_index() == 0
    assert collection.get_pairs() == [
        ("ROT", ["P8", "P10", "PO8", "PO4", "O2"]),
        ("Central", ["FCZ", "CZ", "CPZ", "CP1", "C1", "FC1"]),
    ]


def test_roi_colors_are_unique_and_keep_caption_contrast_with_white() -> None:
    colors = [roi_color_for_id(entry_id) for entry_id in range(1, 65)]

    assert tuple(colors[: len(ROI_COLOR_PALETTE)]) == ROI_COLOR_PALETTE
    assert len(set(colors)) == len(colors)
    for color in colors:
        components = [int(color[offset : offset + 2], 16) / 255 for offset in (1, 3, 5)]
        linear = [
            component / 12.92
            if component <= 0.04045
            else ((component + 0.055) / 1.055) ** 2.4
            for component in components
        ]
        luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
        assert 1.05 / (luminance + 0.05) >= 4.5

    with pytest.raises(ValueError, match="positive"):
        roi_color_for_id(0)
