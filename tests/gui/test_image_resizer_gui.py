import importlib.util
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

pytest.importorskip("PIL")

from Main_App.gui.components import ActionRow, PathPickerRow, SectionCard, StatusBanner
from Tools.Image_Resizer.pyside_resizer import FPVSImageResizerQt


@pytest.mark.qt
def test_image_resizer_uses_shared_component_layer(qtbot, monkeypatch, tmp_path: Path) -> None:
    window = FPVSImageResizerQt()
    qtbot.addWidget(window)

    cards = {card.objectName(): card for card in window.findChildren(SectionCard)}

    expected_cards = {
        "image_resizer_folders",
        "image_resizer_options",
        "image_resizer_actions",
        "image_resizer_progress",
    }
    assert expected_cards <= set(cards)
    assert isinstance(window.input_row, PathPickerRow)
    assert window.input_row.objectName() == "image_resizer_input_row"
    assert isinstance(window.output_row, PathPickerRow)
    assert window.output_row.objectName() == "image_resizer_output_row"
    assert isinstance(window.action_row, ActionRow)
    assert window.action_row.row_layout.indexOf(window.start_btn) >= 0
    assert window.action_row.row_layout.indexOf(window.cancel_btn) >= 0
    assert window.action_row.row_layout.indexOf(window.open_btn) >= 0
    assert isinstance(window.status_banner, StatusBanner)
    assert window.status_banner.objectName() == "image_resizer_status"
    assert window.status_banner.text() == "Ready."
    assert window.status_banner.property("statusVariant") == "info"
    assert window.start_btn.text() == "Process"
    assert window.cancel_btn.text() == "Cancel"
    assert window.open_btn.text() == "Open Folder"
    assert window.start_btn.property("variant") == "primary"
    assert window.cancel_btn.property("variant") == "danger"
    assert window.log.property("logSurface") is True
    assert window.cancel_btn.isEnabled() is False
    assert window.open_btn.isEnabled() is False

    monkeypatch.setattr(
        "Tools.Image_Resizer.pyside_resizer.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: "",
    )
    window._select_input()
    assert window.input_folder == ""
    assert window.in_edit.text() == ""

    input_dir = str(tmp_path / "input")
    window.input_folder = input_dir
    window.in_edit.setText(input_dir)
    window._select_output()
    assert window.output_folder == ""
    assert window.out_edit.text() == ""
