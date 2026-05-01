import importlib.util

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtWidgets import QApplication, QLabel

from Main_App.PySide6_App.utils.theme import apply_fpvs_theme
from Main_App.PySide6_App.widgets import (
    PathPickerRow,
    SectionCard,
    StatusBanner,
    make_action_button,
    make_form_layout,
)


def test_make_action_button_sets_properties(qtbot) -> None:
    button = make_action_button("Run", variant="primary", compact=True)
    qtbot.addWidget(button)

    assert button.text() == "Run"
    assert button.property("variant") == "primary"
    assert button.property("primary") is True
    assert button.property("compact") is True
    assert button.isEnabled()


def test_section_card_exposes_header_and_content_layout(qtbot) -> None:
    card = SectionCard("Processing Options", object_name="processing_group")
    qtbot.addWidget(card)

    child = QLabel("Field", card)
    card.content_layout.addWidget(child)

    assert card.objectName() == "processing_group"
    assert card.header.title_label.text() == "Processing Options"
    assert card.header.property("cardHeader") is True
    assert card.content_layout.indexOf(child) >= 0


def test_path_picker_row_exposes_field_and_button(qtbot) -> None:
    row = PathPickerRow(
        "Browse",
        placeholder="Select a file",
        read_only=True,
    )
    qtbot.addWidget(row)

    assert row.line_edit.isReadOnly()
    assert row.line_edit.placeholderText() == "Select a file"
    assert row.button.text() == "Browse"
    assert row.button.property("variant") == "secondary"
    assert row.button.property("secondary") is True
    assert row.line_edit.text() == ""


def test_status_banner_switches_text_and_variant(qtbot) -> None:
    banner = StatusBanner("Ready", variant="info")
    qtbot.addWidget(banner)

    assert banner.text() == "Ready"
    assert banner.property("statusVariant") == "info"

    banner.set_text("Finished")
    banner.set_variant("success")

    assert banner.text() == "Finished"
    assert banner.property("statusVariant") == "success"

    banner.setText("Running")
    banner.setWordWrap(False)
    assert banner.text() == "Running"


def test_make_form_layout_uses_expected_defaults() -> None:
    layout = make_form_layout()

    assert layout.horizontalSpacing() == 14
    assert layout.contentsMargins().left() == 0


def test_apply_fpvs_theme_sets_app_stylesheet_and_preserves_button_properties(qtbot) -> None:
    app = QApplication.instance()
    assert app is not None
    previous_stylesheet = app.styleSheet()

    try:
        apply_fpvs_theme(app)
        button = make_action_button("Apply", variant="danger", compact=True)
        qtbot.addWidget(button)

        assert app.styleSheet()
        assert 'QPushButton[primary="true"]' in app.styleSheet()
        assert 'QPushButton[secondary="true"]' in app.styleSheet()
        assert 'QPushButton[tertiary="true"]' in app.styleSheet()
        assert 'QPushButton[variant="danger"]' in app.styleSheet()
        assert button.property("variant") == "danger"
        assert button.property("danger") is True
        assert button.property("compact") is True
    finally:
        app.setStyleSheet(previous_stylesheet)
