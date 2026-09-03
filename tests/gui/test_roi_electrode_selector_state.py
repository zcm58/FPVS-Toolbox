from __future__ import annotations

import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
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

    result, index, created = collection.add_or_update("shared", ("P7",))
    assert (result, index, created) == ("updated", 0, False)
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

    result, index, created = collection.add_or_update("Mapped", ("O1",))
    assert (result, index, created) == ("added", 0, False)
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


def test_editor_collection_reports_only_legacy_occurrences_a_preset_drops() -> None:
    collection = ROIEditorCollection(DEFAULT_ELECTRODE_NAMES_64)
    collection.reset(
        [("Custom", ("O1", "LegacyAux", "LegacyAux", "RetainedAux"))]
    )

    assert collection.dropped_unmapped_occurrences(
        0,
        ("O2", "legacyaux", "RetainedAux", "NewAux"),
    ) == ("LegacyAux",)
    assert collection.dropped_unmapped_occurrences(
        0,
        ("O2", "LegacyAux", "legacyaux", "retainedaux"),
    ) == ()


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
