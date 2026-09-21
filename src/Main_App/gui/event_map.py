from __future__ import annotations

from typing import Callable, TypeVar

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QIntValidator, QValidator
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import make_remove_button
from Main_App.gui.condition_input_model import validate_condition_rows
from .style_tokens import EVENT_ID_COLUMN_WIDTH

EntryAdapterT = TypeVar("EntryAdapterT")


def live_event_map_rows(owner: object) -> list[QWidget]:
    layout = getattr(owner, "event_layout", None)
    if layout is None:
        return []
    rows: list[QWidget] = []
    for index in range(layout.count()):
        item = layout.itemAt(index)
        row = item.widget() if item is not None else None
        if isinstance(row, QWidget):
            rows.append(row)
    return rows


def event_row_edits(row: QWidget) -> tuple[QLineEdit | None, QLineEdit | None]:
    edits = [child for child in row.children() if isinstance(child, QLineEdit)]
    if len(edits) < 2:
        return None, None
    label_edit = next((edit for edit in edits if edit.property("event_map_role") == "label"), edits[0])
    id_edit = next((edit for edit in edits if edit.property("event_map_role") == "id"), edits[1])
    return label_edit, id_edit


def ensure_event_row_registered(owner: object, row: QWidget) -> None:
    event_rows = getattr(owner, "event_rows")
    if row not in event_rows:
        event_rows.append(row)


def bind_event_map_row_widgets(owner: object, row: QWidget) -> None:
    row.setAttribute(Qt.WA_StyledBackground, True)
    row.setProperty("event_map_row", True)
    label_edit, id_edit = event_row_edits(row)
    if label_edit is None or id_edit is None:
        return
    label_edit.setProperty("event_map_role", "label")
    id_edit.setProperty("event_map_role", "id")
    id_edit.setValidator(QIntValidator(1, 999999, id_edit))
    if not id_edit.property("event_map_enter_bound"):
        id_edit.installEventFilter(owner)
        id_edit.setProperty("event_map_enter_bound", True)
    for edit in (label_edit, id_edit):
        if not edit.property("event_map_start_readiness_bound"):
            edit.textChanged.connect(
                lambda _text, bound_owner=owner: _refresh_start_enabled(bound_owner)
            )
            edit.setProperty("event_map_start_readiness_bound", True)
    ensure_event_row_registered(owner, row)


def bind_existing_event_map_rows(owner: object) -> None:
    for row in live_event_map_rows(owner):
        bind_event_map_row_widgets(owner, row)


def event_row_label_edit(row: QWidget) -> QLineEdit | None:
    return event_row_edits(row)[0]


def event_row_id_edit(row: QWidget) -> QLineEdit | None:
    return event_row_edits(row)[1]


def resolve_event_map_row(owner: object, widget: QWidget) -> QWidget | None:
    live_rows = tuple(live_event_map_rows(owner))
    current: QWidget | None = widget
    while current is not None:
        if current in live_rows or current.property("event_map_row"):
            bind_event_map_row_widgets(owner, current)
            return current
        current = current.parentWidget()
    return None


def event_map_scroll_area(owner: object) -> QScrollArea | None:
    parent = (
        getattr(owner, "event_container").parentWidget()
        if hasattr(owner, "event_container")
        else None
    )
    while parent is not None:
        if isinstance(parent, QScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


def focus_event_row_label(owner: object, row: QWidget) -> None:
    label_edit = event_row_label_edit(row)
    if label_edit is None or not label_edit.isEnabled():
        return
    scroll_area = event_map_scroll_area(owner)
    if scroll_area is not None:
        scroll_area.ensureWidgetVisible(label_edit)
    label_edit.setFocus(Qt.FocusReason.OtherFocusReason)


def is_valid_event_map_id(id_edit: QLineEdit) -> bool:
    text = id_edit.text().strip()
    if not text:
        return False
    validator = id_edit.validator()
    if validator is None:
        return text.isdigit()
    state, _, _ = validator.validate(text, len(text))
    return state == QValidator.State.Acceptable


def has_complete_event_map_entry(owner: object) -> bool:
    """Return whether the complete draft is valid and contains a condition."""
    mapping, errors = validate_condition_rows(condition_row_values(owner))
    return bool(mapping) and not errors


def condition_row_values(owner: object) -> list[tuple[str, str]]:
    return [
        (label.text(), ident.text())
        for row in getattr(owner, "event_rows", [])
        for label, ident in [event_row_edits(row)]
        if label is not None and ident is not None
    ]


def validated_event_map(owner: object, *, focus_error: bool = False) -> dict[str, int] | None:
    """Present field errors and optionally focus the first invalid control."""
    mapping, errors = validate_condition_rows(condition_row_values(owner))
    rows = getattr(owner, "event_rows", [])
    for index, row in enumerate(rows):
        messages = [error.message for error in errors if error.row == index]
        message = row.findChild(QLabel, "condition_row_error")
        if message is not None:
            message.setText(" ".join(messages))
            message.setVisible(bool(messages))
        for field, edit in zip(("label", "id"), event_row_edits(row)):
            if edit is not None:
                field_message = " ".join(error.message for error in errors if error.row == index and error.field == field)
                edit.setAccessibleDescription(field_message)
                edit.setToolTip(field_message)
    if errors and focus_error:
        first = errors[0]
        edit = event_row_edits(rows[first.row])[0 if first.field == "label" else 1]
        if edit is not None:
            area = event_map_scroll_area(owner)
            if area is not None:
                area.ensureWidgetVisible(edit)
            edit.setFocus(Qt.OtherFocusReason)
            edit.selectAll()
    return None if errors else mapping


def _refresh_start_enabled(owner: object) -> None:
    refresh = getattr(owner, "_update_start_enabled", None)
    if callable(refresh):
        refresh()


def handle_event_map_id_enter(owner: object, id_edit: QLineEdit) -> bool:
    if getattr(owner, "_event_row_return_in_progress"):
        return True
    if resolve_event_map_row(owner, id_edit) is None:
        return False
    if not id_edit.isEnabled() or not is_valid_event_map_id(id_edit):
        return False

    btn_add_row = getattr(owner, "btn_add_row", None)
    if not isinstance(btn_add_row, QPushButton) or not btn_add_row.isEnabled():
        return False

    existing_rows = tuple(live_event_map_rows(owner))
    owner._event_row_return_in_progress = True
    btn_add_row.click()

    def _finish_focus() -> None:
        try:
            current_rows = tuple(live_event_map_rows(owner))
            new_row = next((row for row in current_rows if row not in existing_rows), None)
            if new_row is not None:
                bind_event_map_row_widgets(owner, new_row)
                focus_event_row_label(owner, new_row)
        finally:
            owner._event_row_return_in_progress = False

    QTimer.singleShot(0, _finish_focus)
    return True


def handle_event_filter(owner: object, watched: object, event: QEvent) -> bool | None:
    if (
        isinstance(watched, QLineEdit)
        and watched.property("event_map_role") == "id"
        and event.type() == QEvent.Type.KeyPress
    ):
        key_event = event
        if key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if key_event.isAutoRepeat():
                return True
            return handle_event_map_id_enter(owner, watched)
    return None


def add_event_row(owner: object, label: str = "", ident: str = "") -> None:
    row = QWidget(getattr(owner, "event_container"))
    row.setObjectName("event_map_row")
    row.setAttribute(Qt.WA_StyledBackground, True)
    row.setProperty("event_map_row", True)
    row_layout = QVBoxLayout(row)
    row_layout.setContentsMargins(0, 2, 0, 2)
    row_layout.setSpacing(2)
    hl = QHBoxLayout()
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(8)

    le_label = QLineEdit(label, row)
    le_label.setPlaceholderText("Condition")
    le_label.setProperty("event_map_role", "label")
    le_id = QLineEdit(ident, row)
    le_id.setPlaceholderText("ID")
    le_id.setProperty("event_map_role", "id")
    le_id.setFixedWidth(EVENT_ID_COLUMN_WIDTH)
    le_id.setAlignment(Qt.AlignCenter)

    btn_rm = make_remove_button(
        parent=row,
        tooltip="Remove condition",
        object_name="event_map_remove_button",
    )

    def _remove() -> None:
        getattr(owner, "event_layout").removeWidget(row)
        event_rows = getattr(owner, "event_rows")
        if row in event_rows:
            event_rows.remove(row)
        row.deleteLater()
        owner.log("Event map row removed.")
        _refresh_start_enabled(owner)

    btn_rm.clicked.connect(_remove)

    hl.addWidget(le_label, 1)
    hl.addWidget(le_id, 0)
    hl.addWidget(btn_rm, 0, Qt.AlignVCenter)
    row_layout.addLayout(hl)
    error_label = QLabel(row)
    error_label.setObjectName("condition_row_error")
    error_label.setWordWrap(True)
    error_label.hide()
    row_layout.addWidget(error_label)
    getattr(owner, "event_layout").addWidget(row)
    bind_event_map_row_widgets(owner, row)
    owner.log("Added event map row")
    _refresh_start_enabled(owner)


def event_map_entries(
    owner: object,
    entry_adapter: Callable[[QLineEdit], EntryAdapterT],
) -> list[dict[str, EntryAdapterT]]:
    entries: list[dict[str, EntryAdapterT]] = []
    for row in getattr(owner, "event_rows"):
        label_edit = event_row_label_edit(row)
        id_edit = event_row_id_edit(row)
        if label_edit is not None and id_edit is not None:
            entries.append({"label": entry_adapter(label_edit), "id": entry_adapter(id_edit)})
    return entries
