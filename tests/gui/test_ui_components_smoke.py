import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

import Main_App.gui.components as components
from Main_App.gui.components import (
    ActionRow,
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

EXPECTED_COMPONENT_EXPORTS = (
    "ActionRow",
    "AppDialog",
    "BrainPulseWidget",
    "BusySpinner",
    "CardHeader",
    "PathPickerRow",
    "SectionCard",
    "StatusBanner",
    "SurfaceSize",
    "confirm",
    "configure_window_surface",
    "make_action_button",
    "make_action_row",
    "make_form_layout",
    "show_error",
    "show_info",
    "show_warning",
)


def test_component_public_exports_are_explicit() -> None:
    assert components.__all__ == EXPECTED_COMPONENT_EXPORTS
    for name in EXPECTED_COMPONENT_EXPORTS:
        assert getattr(components, name) is not None


def test_component_consumer_import_style_remains_available() -> None:
    from Main_App.gui.components import ActionRow as ImportedActionRow
    from Main_App.gui.components import AppDialog as ImportedAppDialog
    from Main_App.gui.components import BrainPulseWidget as ImportedBrainPulseWidget
    from Main_App.gui.components import BusySpinner as ImportedBusySpinner
    from Main_App.gui.components import CardHeader as ImportedCardHeader
    from Main_App.gui.components import PathPickerRow as ImportedPathPickerRow
    from Main_App.gui.components import SectionCard as ImportedSectionCard
    from Main_App.gui.components import StatusBanner as ImportedStatusBanner
    from Main_App.gui.components import SurfaceSize as ImportedSurfaceSize
    from Main_App.gui.components import confirm as imported_confirm
    from Main_App.gui.components import configure_window_surface as imported_configure_window_surface
    from Main_App.gui.components import make_action_button as imported_make_action_button
    from Main_App.gui.components import make_action_row as imported_make_action_row
    from Main_App.gui.components import make_form_layout as imported_make_form_layout
    from Main_App.gui.components import show_error as imported_show_error
    from Main_App.gui.components import show_info as imported_show_info
    from Main_App.gui.components import show_warning as imported_show_warning

    imported = {
        "ActionRow": ImportedActionRow,
        "AppDialog": ImportedAppDialog,
        "BrainPulseWidget": ImportedBrainPulseWidget,
        "BusySpinner": ImportedBusySpinner,
        "CardHeader": ImportedCardHeader,
        "PathPickerRow": ImportedPathPickerRow,
        "SectionCard": ImportedSectionCard,
        "StatusBanner": ImportedStatusBanner,
        "SurfaceSize": ImportedSurfaceSize,
        "confirm": imported_confirm,
        "configure_window_surface": imported_configure_window_surface,
        "make_action_button": imported_make_action_button,
        "make_action_row": imported_make_action_row,
        "make_form_layout": imported_make_form_layout,
        "show_error": imported_show_error,
        "show_info": imported_show_info,
        "show_warning": imported_show_warning,
    }

    for name in EXPECTED_COMPONENT_EXPORTS:
        assert imported[name] is getattr(components, name)


def test_component_import_does_not_create_qapplication() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    existing_pythonpath = env.get("PYTHONPATH")
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = (
        src_path
        if not existing_pythonpath
        else src_path + os.pathsep + existing_pythonpath
    )
    code = (
        "from PySide6.QtWidgets import QApplication\n"
        "assert QApplication.instance() is None\n"
        "import Main_App.gui.components as components\n"
        "assert QApplication.instance() is None\n"
        "assert components.__all__[0] == 'ActionRow'\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_make_action_button_sets_properties(qtbot) -> None:
    button = make_action_button("Run", variant="primary", compact=True)
    qtbot.addWidget(button)

    assert button.text() == "Run"
    assert button.property("variant") == "primary"
    assert button.property("primary") is True
    assert button.property("compact") is True
    assert button.isEnabled()


def test_make_action_button_rejects_unknown_variant() -> None:
    with pytest.raises(ValueError, match="Unsupported action button variant"):
        make_action_button("Run", variant="ghost")


def test_action_button_preserves_contract_when_disabled(qtbot) -> None:
    button = make_action_button("Delete", variant="danger")
    qtbot.addWidget(button)

    button.setObjectName("delete_action")
    button.setEnabled(False)

    assert button.objectName() == "delete_action"
    assert not button.isEnabled()
    assert button.property("variant") == "danger"
    assert button.property("danger") is True


def test_section_card_exposes_header_and_content_layout(qtbot) -> None:
    card = SectionCard("Processing Options", object_name="processing_group")
    qtbot.addWidget(card)

    child = QLabel("Field", card)
    card.content_layout.addWidget(child)

    assert card.objectName() == "processing_group"
    assert card.header.title_label.text() == "Processing Options"
    assert card.header.title_label.font().bold()
    assert card.header.property("cardHeader") is True
    assert card.content_layout.indexOf(child) >= 0


def test_section_card_has_stable_layout_size_contract(qtbot) -> None:
    card = SectionCard("Output", object_name="output_group")
    qtbot.addWidget(card)

    card.content_layout.addWidget(QLabel("Folder", card))

    assert card.sizeHint().isValid()
    assert card.minimumSizeHint().isValid()
    assert card.layout().contentsMargins().left() == 15
    assert card.content_layout.contentsMargins().left() == 0


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


def test_path_picker_row_keeps_object_names_and_empty_selection_state(qtbot) -> None:
    row = PathPickerRow("Choose", placeholder="Select a folder")
    qtbot.addWidget(row)

    row.setObjectName("input_path_row")
    row.line_edit.setObjectName("input_path_field")
    row.button.setObjectName("input_path_button")

    with qtbot.waitSignal(row.button.clicked, timeout=1000):
        qtbot.mouseClick(row.button, Qt.LeftButton)

    assert row.objectName() == "input_path_row"
    assert row.line_edit.objectName() == "input_path_field"
    assert row.button.objectName() == "input_path_button"
    assert row.line_edit.text() == ""


def test_path_picker_row_preserves_missing_or_invalid_path_text(qtbot) -> None:
    row = PathPickerRow("Choose", placeholder="Select a folder")
    qtbot.addWidget(row)
    missing_path = r"C:\missing\not-a-project-folder"

    row.line_edit.setText(missing_path)

    with qtbot.waitSignal(row.button.clicked, timeout=1000):
        qtbot.mouseClick(row.button, Qt.LeftButton)

    assert row.line_edit.text() == missing_path


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


def test_status_banner_rejects_unknown_variant(qtbot) -> None:
    banner = StatusBanner("Ready", variant="info")
    qtbot.addWidget(banner)

    with pytest.raises(ValueError, match="Unsupported status banner variant"):
        banner.set_variant("muted")

    assert banner.property("statusVariant") == "info"


def test_status_banner_has_stable_layout_size_contract(qtbot) -> None:
    banner = StatusBanner("Ready", variant="warning")
    qtbot.addWidget(banner)

    banner.setObjectName("operation_status")

    assert banner.objectName() == "operation_status"
    assert banner.label.wordWrap()
    assert banner.banner_layout.contentsMargins().left() == 10
    assert banner.sizeHint().isValid()


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
        assert 'QWidget[statusVariant="info"]' in app.styleSheet()
        assert 'QWidget[statusVariant="warning"]' in app.styleSheet()
        assert 'QWidget[statusVariant="error"]' in app.styleSheet()
        assert 'QWidget[statusVariant="success"]' in app.styleSheet()
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


def test_component_action_row_emits_button_signals(qtbot) -> None:
    run_button = make_action_button("Run", variant="primary")
    row = ActionRow(alignment=Qt.AlignLeft, spacing=12)
    qtbot.addWidget(row)

    row.setObjectName("run_action_row")
    row.add_button(run_button)

    with qtbot.waitSignal(run_button.clicked, timeout=1000):
        qtbot.mouseClick(run_button, Qt.LeftButton)

    assert row.objectName() == "run_action_row"
    assert row.row_layout.spacing() == 12
    assert row.row_layout.indexOf(run_button) >= 0


def test_component_message_helpers_delegate_to_qmessagebox(monkeypatch) -> None:
    calls = []

    def fake_warning(parent, title, message):
        calls.append((parent, title, message))
        return 1

    monkeypatch.setattr("Main_App.gui.components.messages.QMessageBox.warning", fake_warning)

    assert show_warning(None, "Invalid", "Check the fields") == 1
    assert calls == [(None, "Invalid", "Check the fields")]
