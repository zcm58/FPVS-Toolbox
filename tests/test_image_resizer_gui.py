import importlib.util

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

pytest.importorskip("PIL")

from Main_App.PySide6_App.widgets import PathPickerRow, SectionCard, StatusBanner
from Tools.Image_Resizer.pyside_resizer import FPVSImageResizerQt


@pytest.mark.qt
def test_image_resizer_uses_shared_component_layer(qtbot) -> None:
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
    assert isinstance(window.output_row, PathPickerRow)
    assert isinstance(window.status_banner, StatusBanner)
    assert window.start_btn.property("variant") == "primary"
    assert window.cancel_btn.property("variant") == "danger"
    assert window.log.property("logSurface") is True
    assert window.cancel_btn.isEnabled() is False
    assert window.open_btn.isEnabled() is False
