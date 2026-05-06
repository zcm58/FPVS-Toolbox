from __future__ import annotations

from typing import Callable, TypeVar

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QIntValidator, QValidator
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QToolButton,
    QWidget,
)

from .style_tokens import EVENT_ID_COLUMN_WIDTH, EVENT_REMOVE_BUTTON_SIZE

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
    hl = QHBoxLayout(row)
    hl.setContentsMargins(10, 6, 6, 6)
    hl.setSpacing(8)

    le_label = QLineEdit(label, row)
    le_label.setPlaceholderText("Condition")
    le_label.setProperty("event_map_role", "label")
    le_id = QLineEdit(ident, row)
    le_id.setPlaceholderText("ID")
    le_id.setProperty("event_map_role", "id")
    le_id.setFixedWidth(EVENT_ID_COLUMN_WIDTH)
    le_id.setAlignment(Qt.AlignCenter)

    btn_rm = QToolButton(row)
    btn_rm.setObjectName("event_map_remove_button")
    btn_rm.setText("x")
    btn_rm.setAutoRaise(True)
    btn_rm.setToolTip("Remove condition")
    btn_rm.setCursor(Qt.PointingHandCursor)
    btn_rm.setFixedSize(EVENT_REMOVE_BUTTON_SIZE, EVENT_REMOVE_BUTTON_SIZE)

    def _remove() -> None:
        getattr(owner, "event_layout").removeWidget(row)
        event_rows = getattr(owner, "event_rows")
        if row in event_rows:
            event_rows.remove(row)
        row.deleteLater()
        owner.log("Event map row removed.")

    btn_rm.clicked.connect(_remove)

    hl.addWidget(le_label, 1)
    hl.addWidget(le_id, 0)
    hl.addWidget(btn_rm, 0, Qt.AlignVCenter)
    getattr(owner, "event_layout").addWidget(row)
    bind_event_map_row_widgets(owner, row)
    owner.log("Added event map row")


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
