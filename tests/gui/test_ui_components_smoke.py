import importlib.util

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtWidgets import QApplication, QLabel

from Main_App.gui.components import (
    AppDialog,
    PathPickerRow,
    SectionCard,
    StatusBanner,
    SurfaceSize,
    configure_window_surface,
    make_action_row,
    make_action_button,
    make_form_layout,
    show_warning,
)
from Main_App.gui.theme import apply_fpvs_theme


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


def test_component_surface_helpers_configure_top_level_widgets(qtbot) -> None:
    dialog = AppDialog(
        "Settings",
        size=SurfaceSize(width=480, height=320, min_width=400),
    )
    qtbot.addWidget(dialog)

    assert dialog.windowTitle() == "Settings"
    assert dialog.property("fpvsSurface") is True
    assert dialog.minimumWidth() == 400
    assert dialog.root_layout.contentsMargins().left() == 16

    configure_window_surface(
        dialog,
        title="Updated",
        size=SurfaceSize(width=500, height=340, min_height=300),
    )

    assert dialog.windowTitle() == "Updated"
    assert dialog.minimumHeight() == 300


def test_component_action_row_adds_buttons(qtbot) -> None:
    run_button = make_action_button("Run", variant="primary")
    cancel_button = make_action_button("Cancel")
    row = make_action_row([run_button, cancel_button])
    qtbot.addWidget(row)

    assert row.row_layout.indexOf(run_button) >= 0
    assert row.row_layout.indexOf(cancel_button) >= 0


def test_component_message_helpers_delegate_to_qmessagebox(monkeypatch) -> None:
    calls = []

    def fake_warning(parent, title, message):
        calls.append((parent, title, message))
        return 1

    monkeypatch.setattr("Main_App.gui.components.messages.QMessageBox.warning", fake_warning)

    assert show_warning(None, "Invalid", "Check the fields") == 1
    assert calls == [(None, "Invalid", "Check the fields")]
