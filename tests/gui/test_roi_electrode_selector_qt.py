from __future__ import annotations

from itertools import combinations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QWidget,
)

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.Shared.roi_presets import ROI_MONTAGE_BIOSEMI64, default_roi_presets
from Main_App.gui.roi_electrode_selector import ElectrodeMapWidget
from Main_App.gui.roi_settings_editor import ROISettingsEditor


DEFAULT_ROIS = tuple(
    (preset.name, preset.electrodes)
    for preset in default_roi_presets(ROI_MONTAGE_BIOSEMI64)
)


def _build_editor(
    qtbot,
    *,
    pairs: list[tuple[str, list[str]]],
) -> ROISettingsEditor:
    editor = ROISettingsEditor(
        pairs=pairs,
        canonical_electrodes=DEFAULT_ELECTRODE_NAMES_64,
        default_rois=DEFAULT_ROIS,
        current_montage=ROI_MONTAGE_BIOSEMI64,
        montage_label="BioSemi 64",
    )
    qtbot.addWidget(editor)
    editor.resize(1100, 750)
    editor.show()
    qtbot.waitExposed(editor)
    return editor


def _default_pairs() -> list[tuple[str, list[str]]]:
    return [(name, list(electrodes)) for name, electrodes in DEFAULT_ROIS]


def _row_named(editor: ROISettingsEditor, name: str, *, occurrence: int = 1) -> int:
    matches = [
        index
        for index, entry in enumerate(editor.entries)
        if entry.name.casefold() == name.casefold()
    ]
    return matches[occurrence - 1]


def test_embedded_editor_is_flat_accessible_visual_first_surface(qtbot):
    editor = _build_editor(qtbot, pairs=_default_pairs())

    assert editor.splitter.orientation() == Qt.Orientation.Horizontal
    assert editor.map_pane.geometry().right() < editor.roi_pane.geometry().left()
    assert editor.map_pane.isVisibleTo(editor)
    assert editor.roi_list.isVisibleTo(editor)
    assert editor.findChildren(QScrollArea) == []
    assert editor.findChildren(QComboBox) == []
    assert editor.findChildren(QLineEdit) == [editor.name_edit]
    assert editor.montage_label.text() == "Montage: BioSemi 64"
    assert [entry.name for entry in editor.entries] == ["LOT", "ROT", "Central"]
    assert all(entry.is_default for entry in editor.entries)
    assert [editor.roi_list.item(index).text() for index in range(3)] == [
        "LOT  ·  Built-in",
        "ROT  ·  Built-in",
        "Central  ·  Built-in",
    ]

    visible_label_text = {
        label.text()
        for label in editor.findChildren(QLabel)
        if label.text()
    }
    assert "Regions of interest" in visible_label_text
    assert "Interactive scalp map" not in visible_label_text
    assert "Edit active ROI" not in visible_label_text
    assert not any(text.startswith("Editing ROI") for text in visible_label_text)
    assert not any("visible map position" in text for text in visible_label_text)
    assert not any("Selected map positions" in text for text in visible_label_text)
    assert editor.findChild(QLabel, "settings_rois_active_summary") is None
    assert editor.findChild(QLabel, "settings_rois_electrode_count") is None
    assert editor.findChild(QLabel, "settings_rois_selection_summary") is None
    assert editor.findChild(QWidget, "settings_rois_toolbar") is None
    assert editor.findChild(QPushButton, "settings_rois_add_preset") is None
    assert editor.findChild(QPushButton, "settings_rois_save_custom_presets") is None

    actions = editor.roi_pane.layout().itemAt(2).layout()
    assert actions is not None
    assert actions.indexOf(editor.clear_button) < actions.indexOf(editor.remove_button)
    assert editor.clear_button.property("variant") == "secondary"
    assert editor.remove_button.property("variant") == "danger"
    assert editor.add_button.property("variant") == "secondary"

    buttons = editor.map_widget.electrode_buttons
    assert len(buttons) == 64
    assert all(
        button.accessibleName() == f"Electrode {label}"
        for label, button in buttons.items()
    )
    assert all("Space" in button.accessibleDescription() for button in buttons.values())
    assert all(button.focusPolicy() == Qt.FocusPolicy.StrongFocus for button in buttons.values())
    assert buttons["P7"].isChecked()
    assert buttons["O2"].isChecked() is False
    assert buttons["Fp1"].y() < buttons["O1"].y()
    assert buttons["C3"].x() < buttons["Cz"].x() < buttons["C4"].x()

    editor.add_button.setFocus()
    QTest.keyClick(editor.add_button, Qt.Key.Key_Tab)
    assert editor.roi_list.hasFocus()
    QTest.keyClick(editor.roi_list, Qt.Key.Key_Tab)
    assert editor.clear_button.hasFocus()
    QTest.keyClick(editor.clear_button, Qt.Key.Key_Tab)
    assert editor.name_edit.hasFocus()
    QTest.keyClick(editor.name_edit, Qt.Key.Key_Tab)
    assert buttons["Fp1"].hasFocus()


def test_custom_roi_tab_order_includes_removal_and_legacy_controls(qtbot):
    editor = _build_editor(
        qtbot,
        pairs=[*_default_pairs(), ("Legacy", ["O1", "LegacyAux"])],
    )
    editor.select_roi(_row_named(editor, "Legacy"))
    editor.unmapped_list.setCurrentRow(0)

    editor.add_button.setFocus()
    expected_chain = (
        editor.roi_list,
        editor.clear_button,
        editor.remove_button,
        editor.name_edit,
        editor.unmapped_list,
        editor.remove_unmapped_button,
        editor.map_widget.electrode_buttons["Fp1"],
    )
    current = editor.add_button
    for expected in expected_chain:
        QTest.keyClick(current, Qt.Key.Key_Tab)
        assert expected.hasFocus()
        current = expected


def test_electrode_hit_targets_are_contained_disjoint_and_text_fits(qtbot):
    electrode_map = ElectrodeMapWidget(DEFAULT_ELECTRODE_NAMES_64)
    qtbot.addWidget(electrode_map)
    electrode_map.show()
    qtbot.waitExposed(electrode_map)

    assert electrode_map.minimumSize().width() >= 600
    assert electrode_map.minimumSize().height() >= 550
    for size in (QSize(600, 550), QSize(620, 580), QSize(650, 600), QSize(720, 620)):
        electrode_map.resize(size)
        qtbot.wait(1)
        buttons = tuple(electrode_map.electrode_buttons.values())
        assert all(electrode_map.rect().contains(button.geometry()) for button in buttons)
        assert all(button.width() >= 36 and button.height() >= 36 for button in buttons)
        assert all(
            first.geometry().intersected(second.geometry()).isEmpty()
            for first, second in combinations(buttons, 2)
        )
        assert all(
            QFontMetrics(button.font()).horizontalAdvance(button.text())
            <= button.width() - 8
            for button in buttons
        )
        for label in ("Fpz", "P9", "P10", "T7", "T8", "Iz"):
            assert electrode_map.rect().contains(
                electrode_map.electrode_buttons[label].geometry()
            )


def test_default_roi_name_and_removal_are_protected_but_membership_is_editable(qtbot):
    editor = _build_editor(qtbot, pairs=_default_pairs())
    lot_row = _row_named(editor, "LOT")
    editor.select_roi(lot_row)
    before_count = len(editor.entries)

    assert editor.is_default_roi(lot_row) is True
    assert editor.name_edit.isReadOnly()
    assert editor.remove_button.isEnabled() is False
    editor.name_edit.setText("Renamed")
    assert editor.entries[lot_row].name == "LOT"
    assert editor.name_edit.text() == "LOT"

    editor.remove_active_entry()
    assert len(editor.entries) == before_count
    assert editor.entries[lot_row].name == "LOT"
    assert "cannot be removed" in editor.status.text()

    qtbot.mouseClick(
        editor.map_widget.electrode_buttons["P7"],
        Qt.MouseButton.LeftButton,
    )
    assert "P7" not in editor.get_pairs()[lot_row][1]

    qtbot.mouseClick(editor.clear_button, Qt.MouseButton.LeftButton)
    assert editor.validate_draft() is False
    assert "Choose at least one electrode" in editor.status.text()
    qtbot.mouseClick(
        editor.map_widget.electrode_buttons["P7"],
        Qt.MouseButton.LeftButton,
    )
    assert editor.validate_draft() is True


def test_active_roi_switch_and_overlap_are_independent(qtbot):
    pairs = [
        *_default_pairs(),
        ("Shared", ["Oz", "Iz"]),
        ("Shared", ["Oz", "Pz"]),
    ]
    editor = _build_editor(qtbot, pairs=pairs)
    first_row = _row_named(editor, "Shared", occurrence=1)
    second_row = _row_named(editor, "Shared", occurrence=2)
    first_id = editor.roi_id(first_row)
    second_id = editor.roi_id(second_row)
    first_color = editor.roi_color(first_row)
    second_color = editor.roi_color(second_row)
    first_label = f"ROI {first_row + 1}: Shared"
    second_label = f"ROI {second_row + 1}: Shared"

    editor.select_roi(first_row)
    assert editor.map_widget.roi_memberships("Oz") == (first_label, second_label)
    assert tuple(
        editor.map_widget.electrode_buttons["Oz"].property("roiMemberships")
    ) == (first_label, second_label)
    assert tuple(
        editor.map_widget.electrode_buttons["Oz"].property("roiMembershipColors")
    ) == (first_color, second_color)
    assert editor.map_widget.electrode_buttons["Oz"].property("activeRoiMember") is True
    assert first_label in editor.map_widget.electrode_buttons["Oz"].accessibleDescription()
    assert second_label in editor.map_widget.electrode_buttons["Oz"].accessibleDescription()

    editor.select_roi(second_row)
    qtbot.mouseClick(
        editor.map_widget.electrode_buttons["Oz"],
        Qt.MouseButton.LeftButton,
    )
    editor.map_widget.electrode_buttons["Fp1"].setFocus()
    QTest.keyClick(editor.map_widget.electrode_buttons["Fp1"], Qt.Key.Key_Space)

    assert editor.map_widget.roi_memberships("Oz") == (first_label,)
    assert editor.map_widget.roi_memberships("Fp1") == (second_label,)
    oz_button = editor.map_widget.electrode_buttons["Oz"]
    fp1_button = editor.map_widget.electrode_buttons["Fp1"]
    assert tuple(oz_button.property("roiMemberships")) == (first_label,)
    assert tuple(fp1_button.property("roiMemberships")) == (second_label,)
    assert oz_button.property("activeRoiMember") is False
    assert fp1_button.property("activeRoiMember") is True
    assert first_label in oz_button.accessibleDescription()
    assert f"Editing {second_label}" in oz_button.accessibleDescription()
    assert f"add it to {second_label}" in oz_button.accessibleDescription()
    assert second_label in fp1_button.accessibleDescription()
    assert f"remove it from {second_label}" in fp1_button.accessibleDescription()
    assert editor.roi_id(first_row) == first_id
    assert editor.roi_id(second_row) == second_id
    assert editor.roi_color(first_row) == first_color
    assert editor.roi_color(second_row) == second_color


def test_custom_roi_add_rename_remove_and_legacy_occurrences_preserve_identity(qtbot):
    editor = _build_editor(
        qtbot,
        pairs=[
            *_default_pairs(),
            ("Legacy", ["cz", "CZ", "LegacyAux", "LegacyAux"]),
            ("Other", ["O2"]),
        ],
    )
    legacy_row = _row_named(editor, "Legacy")
    other_row = _row_named(editor, "Other")
    surviving_id = editor.roi_id(other_row)
    surviving_color = editor.roi_color(other_row)
    editor.select_roi(legacy_row)

    assert editor.name_edit.isReadOnly() is False
    assert editor.remove_button.isEnabled()
    assert editor.unmapped_pane.isVisibleTo(editor)
    assert [editor.unmapped_list.item(index).text() for index in range(2)] == [
        "LegacyAux",
        "LegacyAux",
    ]

    editor.name_edit.setFocus()
    QTest.keyClick(
        editor.name_edit,
        Qt.Key.Key_A,
        Qt.KeyboardModifier.ControlModifier,
    )
    QTest.keyClicks(editor.name_edit, "Legacy Renamed")
    assert editor.get_pairs()[legacy_row][0] == "Legacy Renamed"
    assert editor.roi_list.item(legacy_row).text() == "Legacy Renamed"
    assert "Legacy Renamed" in str(
        editor.roi_list.item(legacy_row).data(Qt.ItemDataRole.AccessibleTextRole)
    )
    editor.unmapped_list.setCurrentRow(0)
    qtbot.mouseClick(editor.remove_unmapped_button, Qt.MouseButton.LeftButton)
    assert editor.unmapped_list.count() == 1

    qtbot.mouseClick(editor.remove_button, Qt.MouseButton.LeftButton)
    assert all(entry.name != "Legacy Renamed" for entry in editor.entries)
    surviving_row = _row_named(editor, "Other")
    assert editor.roi_id(surviving_row) == surviving_id
    assert editor.roi_color(surviving_row) == surviving_color

    qtbot.mouseClick(editor.add_button, Qt.MouseButton.LeftButton)
    added_row = editor.active_roi_index()
    assert editor.is_default_roi(added_row) is False
    qtbot.mouseClick(
        editor.map_widget.electrode_buttons["O1"],
        Qt.MouseButton.LeftButton,
    )
    assert editor.validate_draft() is False
    editor.name_edit.setText("Added")
    assert editor.validate_draft() is True
    assert editor.get_pairs()[-1] == ("Added", ["O1"])


def test_clear_with_legacy_labels_requires_explicit_second_activation(qtbot):
    editor = _build_editor(
        qtbot,
        pairs=[
            *_default_pairs(),
            ("Legacy", ["O1", "LegacyAux", "LegacyAux"]),
        ],
    )
    editor.select_roi(_row_named(editor, "Legacy"))
    before_clear = editor.get_pairs()

    qtbot.mouseClick(editor.clear_button, Qt.MouseButton.LeftButton)
    assert editor.get_pairs() == before_clear
    assert editor.status.property("statusVariant") == "warning"
    assert "again to confirm" in editor.status.text()

    qtbot.mouseClick(editor.clear_button, Qt.MouseButton.LeftButton)
    assert editor.get_pairs() == _default_pairs()
    assert editor.clear_button.isEnabled() is False
    assert editor.validate_draft() is False
