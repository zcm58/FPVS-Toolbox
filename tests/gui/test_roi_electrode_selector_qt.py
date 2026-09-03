from __future__ import annotations

from types import SimpleNamespace

import pytest

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QBoxLayout, QDialog, QLineEdit, QPushButton

import Main_App.gui.roi_settings_editor as editor_module
from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.Shared.roi_presets import ROI_MONTAGE_10_10, default_roi_presets
from Main_App.gui.roi_electrode_selector import ROIElectrodeSelectorDialog
from Main_App.gui.roi_settings_editor import ROISettingsEditor


def _preset_items(*, include_custom: bool = False):
    items = [
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


def test_selector_map_is_accessible_keyboard_operable_and_cancel_is_transactional(qtbot):
    original = ("cz", "CZ", "LegacyAux")
    dialog = ROIElectrodeSelectorDialog(
        canonical_electrodes=DEFAULT_ELECTRODE_NAMES_64,
        current_name="Original ROI",
        current_electrodes=original,
        presets=_preset_items(),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    buttons = dialog.map_widget.electrode_buttons
    assert len(buttons) == 64
    assert all(button.accessibleName() == f"Electrode {name}" for name, button in buttons.items())
    assert all("Space" in button.toolTip() for button in buttons.values())
    assert buttons["Cz"].isChecked()
    assert buttons["Cz"].text() == "Cz"
    assert "border: 3px double" in buttons["Cz"].styleSheet()
    assert "double" not in buttons["O1"].styleSheet()
    assert buttons["Cz"].focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert buttons["Fp1"].y() < buttons["O1"].y()
    assert buttons["C3"].x() < buttons["Cz"].x() < buttons["C4"].x()
    dialog.unmapped_edit.setText("Other")
    assert dialog.selection_label.text() == "Selected electrode entries (3): cz, CZ, Other"
    dialog.unmapped_edit.setText("LegacyAux")

    qtbot.mouseClick(buttons["O1"], Qt.LeftButton)
    buttons["Cz"].setFocus()
    qtbot.wait(1)
    assert buttons["Cz"].hasFocus()
    QTest.keyClick(buttons["Cz"], Qt.Key_Space)
    assert buttons["O1"].isChecked()
    assert buttons["Cz"].isChecked() is False
    assert dialog.selection_name() == "Original ROI"
    assert dialog.selected_electrodes() == original

    dialog.resize(800, 600)
    qtbot.wait(1)
    assert dialog._content_layout.direction() == QBoxLayout.Direction.TopToBottom
    for button in buttons.values():
        assert QFontMetrics(button.font()).horizontalAdvance(button.text()) <= button.width() - 6
    assert dialog.findChild(QLineEdit, "roi_selector_unmapped").text() == "LegacyAux"

    dialog.cancel_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.selection_name() == "Original ROI"
    assert dialog.selected_electrodes() == original


@pytest.mark.parametrize("dismissal", ["escape", "window-close"])
def test_selector_escape_and_window_close_leave_public_result_unchanged(qtbot, dismissal):
    original = ("Cz", "LegacyAux")
    dialog = ROIElectrodeSelectorDialog(
        canonical_electrodes=DEFAULT_ELECTRODE_NAMES_64,
        current_name="Original ROI",
        current_electrodes=original,
        presets=_preset_items(),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    qtbot.mouseClick(dialog.map_widget.electrode_buttons["O1"], Qt.MouseButton.LeftButton)

    if dismissal == "escape":
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    else:
        dialog.close()

    assert dialog.isVisible() is False
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.selection_name() == "Original ROI"
    assert dialog.selected_electrodes() == original


def test_unmapped_editor_preserves_incremental_plain_text(qtbot):
    dialog = ROIElectrodeSelectorDialog(
        canonical_electrodes=DEFAULT_ELECTRODE_NAMES_64,
        current_name="Legacy ROI",
        current_electrodes=("CzAux", "<b>Aux</b>"),
        presets=_preset_items(),
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.selection_label.textFormat() == Qt.TextFormat.PlainText
    assert dialog.status.label.textFormat() == Qt.TextFormat.PlainText
    dialog.unmapped_edit.setFocus()
    QTest.keyClick(dialog.unmapped_edit, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClicks(dialog.unmapped_edit, "Cz")

    assert dialog.unmapped_edit.text() == "Cz"
    assert dialog.map_widget.electrode_buttons["Cz"].isChecked() is False

    QTest.keyClicks(dialog.unmapped_edit, "Aux")
    dialog.unmapped_edit.editingFinished.emit()

    assert dialog.unmapped_edit.text() == "CzAux"
    assert dialog.map_widget.electrode_buttons["Cz"].isChecked() is False
    assert dialog.selected_electrodes() == ("CzAux", "<b>Aux</b>")


def test_selector_noop_preserves_duplicates_and_fpvs_presets_replace_only_the_draft(qtbot):
    original = ("cz", "CZ", "LegacyAux")
    no_op = ROIElectrodeSelectorDialog(
        canonical_electrodes=DEFAULT_ELECTRODE_NAMES_64,
        current_name="Original ROI",
        current_electrodes=original,
        presets=_preset_items(),
    )
    qtbot.addWidget(no_op)
    no_op.use_button.click()

    assert no_op.result() == QDialog.DialogCode.Accepted
    assert no_op.name_changed() is False
    assert no_op.electrodes_changed() is False
    assert no_op.selected_electrodes() == original

    dialog = ROIElectrodeSelectorDialog(
        canonical_electrodes=DEFAULT_ELECTRODE_NAMES_64,
        current_name="Original ROI",
        current_electrodes=("Cz", "LegacyAux"),
        presets=_preset_items(include_custom=True),
    )
    qtbot.addWidget(dialog)
    dialog.preset_combo.setCurrentText("LOT (Default)")
    dialog.apply_preset_button.click()
    lot_members = set(default_roi_presets(ROI_MONTAGE_10_10)[0].electrodes)
    assert {
        name for name, button in dialog.map_widget.electrode_buttons.items() if button.isChecked()
    } == lot_members
    assert dialog.name_edit.text() == "LOT"
    assert dialog.selection_name() == "Original ROI"

    dialog.clear_button.click()
    assert dialog.use_button.isEnabled() is False
    dialog.preset_combo.setCurrentText("Custom with auxiliary (Custom)")
    dialog.apply_preset_button.click()
    assert dialog.unmapped_edit.text() == "LegacyAux,LegacyAux"
    assert dialog.status.property("statusVariant") == "warning"
    dialog.name_edit.clear()
    assert dialog.use_button.isEnabled() is False
    dialog.name_edit.setText("Custom result")
    dialog.use_button.click()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.selection_name() == "Custom result"
    assert dialog.selected_electrodes() == (
        "LegacyAux",
        "O2",
        "O2",
        "LegacyAux",
    )


def test_roi_editor_selector_updates_only_target_row_and_leaves_noop_text_untouched(
    qtbot,
    monkeypatch,
):
    responses = iter(
        (
            SimpleNamespace(
                result=QDialog.DialogCode.Accepted,
                name="  First  ",
                electrodes=("o1", "O1", "LegacyAux"),
                name_changed=False,
                electrodes_changed=False,
            ),
            SimpleNamespace(
                result=QDialog.DialogCode.Accepted,
                name="Second edited",
                electrodes=("Cz", "O2"),
                name_changed=True,
                electrodes_changed=True,
            ),
            SimpleNamespace(
                result=QDialog.DialogCode.Rejected,
                name="Should not apply",
                electrodes=("Fp1",),
                name_changed=True,
                electrodes_changed=True,
            ),
        )
    )

    class FakeSelector:
        def __init__(self, **kwargs):
            self.response = next(responses)
            self.kwargs = kwargs

        def exec(self):
            return self.response.result

        def selection_name(self):
            return self.response.name

        def selected_electrodes(self):
            return self.response.electrodes

        def name_changed(self):
            return self.response.name_changed

        def electrodes_changed(self):
            return self.response.electrodes_changed

        def deleteLater(self):
            pass

    monkeypatch.setattr(editor_module, "ROIElectrodeSelectorDialog", FakeSelector)
    editor = ROISettingsEditor(
        pairs=[("First", ["O1"]), ("Second", ["Cz"])],
        canonical_electrodes=DEFAULT_ELECTRODE_NAMES_64,
        preset_provider=_preset_items,
    )
    qtbot.addWidget(editor)
    first = editor.entries[0]
    second = editor.entries[1]
    first_name = first["name"]
    first_electrodes = first["elec"]
    assert isinstance(first_name, QLineEdit)
    assert isinstance(first_electrodes, QLineEdit)
    first_name.setText("  First  ")
    first_electrodes.setText(" o1, O1, LegacyAux ")

    first_button = first["frame"].findChild(QPushButton, "settings_rois_select_electrodes")
    second_button = second["frame"].findChild(QPushButton, "settings_rois_select_electrodes")
    assert "row 1: First" in first_button.accessibleName()
    assert "row 2: Second" in second_button.accessibleName()
    first_name.setText("First renamed")
    assert "row 1: First renamed" in first_button.accessibleName()
    first_name.setText("  First  ")
    first_button.click()
    assert first_name.text() == "  First  "
    assert first_electrodes.text() == " o1, O1, LegacyAux "

    second_button.click()
    assert second["name"].text() == "Second edited"
    assert second["elec"].text() == "Cz,O2"
    assert first_electrodes.text() == " o1, O1, LegacyAux "

    first_button.click()
    assert first_name.text() == "  First  "
    assert first_electrodes.text() == " o1, O1, LegacyAux "
