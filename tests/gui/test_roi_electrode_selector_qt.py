from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QPushButton, QScrollArea

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.Shared.roi_presets import ROI_MONTAGE_10_10, default_roi_presets
from Main_App.gui.roi_electrode_selector import ElectrodeMapWidget
from Main_App.gui.roi_settings_editor import ROISettingsEditor


def _preset_items(
    _montage: str,
    *,
    include_custom: bool = False,
) -> list[tuple[str, Sequence[str], bool]]:
    items: list[tuple[str, Sequence[str], bool]] = [
        (preset.name, preset.electrodes, True)
        for preset in default_roi_presets(ROI_MONTAGE_10_10)
    ]
    if include_custom:
        items.append(
            (
                "Custom with auxiliary",
                ("O2", "O2", "LegacyAux", "LegacyAux"),
                False,
            )
        )
    return items


def _build_editor(
    qtbot,
    *,
    pairs: list[tuple[str, list[str]]],
    include_custom: bool = False,
) -> ROISettingsEditor:
    editor = ROISettingsEditor(
        pairs=pairs,
        canonical_electrodes=DEFAULT_ELECTRODE_NAMES_64,
        montage_options=((ROI_MONTAGE_10_10, "10-10 International"),),
        current_montage=ROI_MONTAGE_10_10,
        preset_provider=lambda montage: _preset_items(
            montage,
            include_custom=include_custom,
        ),
    )
    qtbot.addWidget(editor)
    editor.resize(1000, 700)
    editor.show()
    qtbot.waitExposed(editor)
    return editor


def test_embedded_editor_is_default_accessible_two_pane_surface(qtbot):
    editor = _build_editor(
        qtbot,
        pairs=[("Central", ["Cz", "FCz"])],
    )

    assert editor.splitter.orientation() == Qt.Orientation.Horizontal
    assert editor.map_pane.geometry().right() < editor.roi_pane.geometry().left()
    assert editor.map_pane.isVisibleTo(editor)
    assert editor.roi_list.isVisibleTo(editor)
    assert editor.findChildren(QScrollArea) == []
    assert editor.findChildren(QLineEdit) == [editor.name_edit]
    assert editor.findChild(QLineEdit, "settings_rois_preset_electrodes") is None
    assert editor.findChildren(QPushButton, "settings_rois_select_electrodes") == []

    buttons = editor.map_widget.electrode_buttons
    assert len(buttons) == 64
    assert all(
        button.accessibleName() == f"Electrode {label}"
        for label, button in buttons.items()
    )
    assert all("Space" in button.accessibleDescription() for button in buttons.values())
    assert all(button.focusPolicy() == Qt.FocusPolicy.StrongFocus for button in buttons.values())
    assert buttons["Cz"].isChecked()
    assert buttons["Cz"].property("activeRoiMember") is True
    assert buttons["O1"].isChecked() is False
    assert buttons["O1"].property("activeRoiMember") is False
    assert buttons["Fp1"].y() < buttons["O1"].y()
    assert buttons["C3"].x() < buttons["Cz"].x() < buttons["C4"].x()
    assert editor.active_roi_index() == 0
    assert editor.roi_list.currentRow() == 0
    assert "Editing ROI 1: Central" in editor.active_summary.text()
    assert "2 electrode entries" in editor.roi_list.item(0).text()
    editor.save_presets_button.setFocus()
    QTest.keyClick(editor.save_presets_button, Qt.Key.Key_Tab)
    assert editor.roi_list.hasFocus()
    for button in buttons.values():
        assert QFontMetrics(button.font()).horizontalAdvance(button.text()) <= button.width() - 6


def test_electrode_hit_targets_are_contained_and_disjoint_at_minimum_size(qtbot):
    electrode_map = ElectrodeMapWidget(DEFAULT_ELECTRODE_NAMES_64)
    qtbot.addWidget(electrode_map)
    electrode_map.resize(electrode_map.minimumSize())
    electrode_map.show()
    qtbot.waitExposed(electrode_map)

    buttons = tuple(electrode_map.electrode_buttons.values())
    assert all(electrode_map.rect().contains(button.geometry()) for button in buttons)
    assert all(
        first.geometry().intersected(second.geometry()).isEmpty()
        for first, second in combinations(buttons, 2)
    )


def test_active_roi_switch_and_overlap_are_independent(qtbot):
    editor = _build_editor(
        qtbot,
        pairs=[
            ("Shared", ["O1", "Cz"]),
            ("Shared", ["O1", "O2"]),
        ],
    )
    buttons = editor.map_widget.electrode_buttons
    original_pairs = editor.get_pairs()
    first_id = editor.roi_id(0)
    second_id = editor.roi_id(1)
    first_color = editor.roi_color(0)
    second_color = editor.roi_color(1)

    assert first_id != second_id
    assert first_color != second_color
    assert editor.map_widget.roi_memberships("O1") == (
        "ROI 1: Shared",
        "ROI 2: Shared",
    )
    assert tuple(buttons["O1"].property("roiMemberships")) == (
        "ROI 1: Shared",
        "ROI 2: Shared",
    )
    assert tuple(buttons["O1"].property("roiMembershipColors")) == (
        first_color,
        second_color,
    )
    assert "In ROI 1: Shared, ROI 2: Shared." in buttons["O1"].accessibleDescription()

    editor.select_roi(1)

    assert editor.get_pairs() == original_pairs
    assert editor.active_roi_index() == 1
    assert buttons["O1"].isChecked()
    assert buttons["O2"].isChecked()
    assert buttons["Cz"].isChecked() is False

    qtbot.mouseClick(buttons["O1"], Qt.MouseButton.LeftButton)
    buttons["P10"].setFocus()
    QTest.keyClick(buttons["P10"], Qt.Key.Key_Space)

    assert editor.get_pairs() == [
        ("Shared", ["O1", "CZ"]),
        ("Shared", ["O2", "P10"]),
    ]
    assert editor.map_widget.roi_memberships("O1") == ("ROI 1: Shared",)
    assert editor.map_widget.roi_memberships("P10") == ("ROI 2: Shared",)
    assert editor.roi_id(0) == first_id
    assert editor.roi_id(1) == second_id
    assert editor.roi_color(0) == first_color
    assert editor.roi_color(1) == second_color

    editor.select_roi(0)

    assert buttons["O1"].isChecked()
    assert buttons["P10"].isChecked() is False
    assert buttons["O1"].property("activeRoiMember") is True
    assert buttons["P10"].property("activeRoiMember") is False


def test_add_rename_remove_and_legacy_occurrences_preserve_row_identity(qtbot):
    editor = _build_editor(
        qtbot,
        pairs=[
            ("Legacy", ["cz", "CZ", "LegacyAux", "LegacyAux"]),
            ("Other", ["O2"]),
        ],
    )
    buttons = editor.map_widget.electrode_buttons
    surviving_id = editor.roi_id(1)
    surviving_color = editor.roi_color(1)

    assert editor.unmapped_pane.isVisibleTo(editor)
    assert editor.unmapped_list.count() == 2
    assert [editor.unmapped_list.item(index).text() for index in range(2)] == [
        "LegacyAux",
        "LegacyAux",
    ]
    assert editor.get_pairs()[0] == (
        "Legacy",
        ["CZ", "CZ", "LEGACYAUX", "LEGACYAUX"],
    )

    editor.name_edit.setFocus()
    QTest.keyClick(
        editor.name_edit,
        Qt.Key.Key_A,
        Qt.KeyboardModifier.ControlModifier,
    )
    QTest.keyClicks(editor.name_edit, "Legacy Renamed")

    assert editor.get_pairs()[0][0] == "Legacy Renamed"
    assert editor.roi_id(0) != surviving_id
    assert editor.map_widget.roi_memberships("Cz") == ("ROI 1: Legacy Renamed",)
    assert "Editing ROI 1: Legacy Renamed" in editor.active_summary.text()
    editor.name_edit.setCursorPosition(len("Legacy"))
    QTest.keyClicks(editor.name_edit, "X")
    assert editor.name_edit.text() == "LegacyX Renamed"
    assert editor.name_edit.cursorPosition() == len("LegacyX")
    QTest.keyClick(editor.name_edit, Qt.Key.Key_Backspace)

    qtbot.mouseClick(buttons["O1"], Qt.MouseButton.LeftButton)
    editor.unmapped_list.setCurrentRow(0)
    qtbot.mouseClick(editor.remove_unmapped_button, Qt.MouseButton.LeftButton)

    assert editor.unmapped_list.count() == 1
    assert editor.unmapped_list.item(0).text() == "LegacyAux"
    assert editor.get_pairs()[0] == (
        "Legacy Renamed",
        ["CZ", "CZ", "LEGACYAUX", "O1"],
    )

    qtbot.mouseClick(editor.remove_button, Qt.MouseButton.LeftButton)

    assert len(editor.entries) == 1
    assert editor.active_roi_index() == 0
    assert editor.roi_id(0) == surviving_id
    assert editor.roi_color(0) == surviving_color
    assert editor.get_pairs() == [("Other", ["O2"])]

    qtbot.mouseClick(editor.add_button, Qt.MouseButton.LeftButton)
    assert editor.active_roi_index() == 1
    assert editor.roi_id(1) != surviving_id
    qtbot.mouseClick(buttons["O1"], Qt.MouseButton.LeftButton)
    assert editor.validate_draft() is False
    assert editor.status.property("statusVariant") == "warning"
    editor.name_edit.clear()
    QTest.keyClicks(editor.name_edit, "Added")
    assert editor.validate_draft() is True

    assert editor.get_pairs() == [
        ("Other", ["O2"]),
        ("Added", ["O1"]),
    ]
    assert all(len(pair) == 2 for pair in editor.get_pairs())

    qtbot.mouseClick(editor.clear_button, Qt.MouseButton.LeftButton)

    assert editor.clear_button.isEnabled() is False
    assert editor.get_pairs() == [("Other", ["O2"])]
    assert editor.validate_draft() is False
    editor.name_edit.clear()
    assert editor.validate_draft() is True


def test_embedded_presets_use_fpvs_membership_and_activate_the_target(qtbot):
    editor = _build_editor(
        qtbot,
        pairs=[("Existing", ["Cz"])],
        include_custom=True,
    )
    original_pairs = editor.get_pairs()

    assert editor.preset_combo.findText("LOT (Default)") >= 0
    assert editor.preset_combo.findText("ROT (Default)") >= 0
    assert editor.preset_combo.findText("Central (Default)") >= 0
    assert editor.preset_combo.findText("Custom with auxiliary (Custom)") >= 0
    assert editor.add_preset_button.text() == "Add / Reset Preset ROI"

    editor.preset_combo.setCurrentText("ROT (Default)")
    assert editor.get_pairs() == original_pairs
    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)

    expected_rot = list(default_roi_presets(ROI_MONTAGE_10_10)[1].electrodes)
    assert editor.get_pairs() == [
        ("Existing", ["CZ"]),
        ("ROT", expected_rot),
    ]
    assert editor.active_roi_index() == 1
    assert {
        label
        for label, button in editor.map_widget.electrode_buttons.items()
        if button.isChecked()
    } == set(expected_rot)
    row_count = len(editor.entries)

    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)

    assert len(editor.entries) == row_count
    assert editor.active_roi_index() == 1
    assert editor.status.property("statusVariant") == "success"

    editor.preset_combo.setCurrentText("Custom with auxiliary (Custom)")
    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)

    assert editor.active_roi_index() == 2
    assert editor.get_pairs()[-1] == (
        "Custom with auxiliary",
        ["O2", "O2", "LEGACYAUX", "LEGACYAUX"],
    )
    assert editor.unmapped_list.count() == 2
    assert editor.map_widget.roi_memberships("O2") == (
        "ROI 2: ROT",
        "ROI 3: Custom with auxiliary",
    )

    with qtbot.waitSignal(editor.save_custom_presets_requested):
        qtbot.mouseClick(editor.save_presets_button, Qt.MouseButton.LeftButton)

    editor.set_pairs([("ROT", ["O1", "LegacyAux"])])
    editor.preset_combo.setCurrentText("ROT (Default)")
    before_reset = editor.get_pairs()
    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)

    assert editor.get_pairs() == before_reset
    assert editor.status.property("statusVariant") == "warning"
    assert "again to confirm" in editor.status.text()

    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)

    assert editor.get_pairs() == [("ROT", expected_rot)]
    assert "removed its legacy / unmapped labels" in editor.status.text()


def test_clear_with_legacy_labels_requires_explicit_second_activation(qtbot):
    editor = _build_editor(
        qtbot,
        pairs=[("Legacy", ["O1", "LegacyAux", "LegacyAux"])],
    )
    before_clear = editor.get_pairs()

    qtbot.mouseClick(editor.clear_button, Qt.MouseButton.LeftButton)

    assert editor.get_pairs() == before_clear
    assert editor.status.property("statusVariant") == "warning"
    assert "again to confirm" in editor.status.text()

    qtbot.mouseClick(editor.clear_button, Qt.MouseButton.LeftButton)

    assert editor.get_pairs() == []
    assert editor.clear_button.isEnabled() is False
    assert editor.validate_draft() is False


def test_destructive_confirmations_expire_after_other_toolbar_actions(qtbot):
    editor = _build_editor(
        qtbot,
        pairs=[("ROT", ["O1", "LegacyAux"])],
    )
    editor.preset_combo.setCurrentText("ROT (Default)")
    before_action = editor.get_pairs()

    qtbot.mouseClick(editor.clear_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)
    assert editor.get_pairs() == before_action
    assert "Add / Reset Preset ROI again" in editor.status.text()

    qtbot.mouseClick(editor.clear_button, Qt.MouseButton.LeftButton)
    assert editor.get_pairs() == before_action
    assert "Clear Active ROI again" in editor.status.text()

    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)
    assert editor.get_pairs() == before_action
    with qtbot.waitSignal(editor.save_custom_presets_requested):
        qtbot.mouseClick(editor.save_presets_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)

    assert editor.get_pairs() == before_action
    assert "Add / Reset Preset ROI again" in editor.status.text()


def test_matching_custom_preset_warns_only_for_legacy_occurrences_it_drops(qtbot):
    editor = _build_editor(
        qtbot,
        pairs=[
            (
                "Custom with auxiliary",
                ["O1", "LegacyAux", "LegacyAux"],
            )
        ],
        include_custom=True,
    )
    editor.preset_combo.setCurrentText("Custom with auxiliary (Custom)")

    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)

    assert editor.get_pairs() == [
        (
            "Custom with auxiliary",
            ["O2", "O2", "LEGACYAUX", "LEGACYAUX"],
        )
    ]
    assert editor.status.property("statusVariant") == "success"
    assert "again to confirm" not in editor.status.text()

    editor.set_pairs(
        [
            (
                "Custom with auxiliary",
                ["O1", "LegacyAux", "LegacyAux", "DropAux"],
            )
        ]
    )
    before_reset = editor.get_pairs()
    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)

    assert editor.get_pairs() == before_reset
    assert "DropAux" in editor.status.text()
    assert "LegacyAux" not in editor.status.text()

    qtbot.mouseClick(editor.add_preset_button, Qt.MouseButton.LeftButton)

    assert editor.get_pairs() == [
        (
            "Custom with auxiliary",
            ["O2", "O2", "LEGACYAUX", "LEGACYAUX"],
        )
    ]
    assert "DropAux" in editor.status.text()
    assert "LegacyAux" not in editor.status.text()
