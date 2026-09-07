"""Shared column sort/filter popup for review tables."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .actions import make_action_row
from Main_App.gui.widgets.buttons import make_action_button


class ColumnFilterMenu(QMenu):
    """Stage value selections until Apply; sorting and clearing act immediately.

    Search only changes which checklist options are visible. Hidden options
    retain their check state, and an empty checked set is a valid filter.
    """

    sort_requested = Signal(object)
    filter_applied = Signal(object)

    def __init__(
        self,
        title: str,
        values: list[str],
        selected_values: set[str] | None = None,
        *,
        numeric: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        self.setObjectName("column_filter_menu")
        self.setFixedWidth(320)
        self.addSection(title)

        ascending = self.addAction("Sort smallest to largest" if numeric else "Sort A to Z")
        ascending.setObjectName("column_filter_sort_ascending")
        ascending.triggered.connect(
            lambda: self.sort_requested.emit(Qt.SortOrder.AscendingOrder)
        )
        descending = self.addAction("Sort largest to smallest" if numeric else "Sort Z to A")
        descending.setObjectName("column_filter_sort_descending")
        descending.triggered.connect(
            lambda: self.sort_requested.emit(Qt.SortOrder.DescendingOrder)
        )
        clear_filter = self.addAction("Clear filter")
        clear_filter.setObjectName("column_filter_clear")
        clear_filter.triggered.connect(self._clear_filter)
        self.addSeparator()

        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setSpacing(8)

        self.search_edit = QLineEdit(panel)
        self.search_edit.setObjectName("column_filter_search")
        self.search_edit.setPlaceholderText("Search values...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName(f"Search {title} filter values")
        layout.addWidget(self.search_edit)

        select_all = make_action_button("Select all", compact=True, parent=panel)
        select_all.setObjectName("column_filter_select_all")
        select_all.setToolTip("Check all values visible in this list.")
        select_all.clicked.connect(lambda: self._set_visible_checks(Qt.CheckState.Checked))
        clear_selection = make_action_button("Clear selection", compact=True, parent=panel)
        clear_selection.setObjectName("column_filter_clear_selection")
        clear_selection.setToolTip("Uncheck all values visible in this list.")
        clear_selection.clicked.connect(
            lambda: self._set_visible_checks(Qt.CheckState.Unchecked)
        )
        layout.addWidget(
            make_action_row([select_all, clear_selection], parent=panel, alignment=Qt.AlignLeft)
        )

        self.values_list = QListWidget(panel)
        self.values_list.setObjectName("column_filter_values")
        self.values_list.setAccessibleName(f"Included {title} values")
        self.values_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.values_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.values_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.values_list.setUniformItemSizes(True)
        self.values_list.setFixedHeight(220)
        for value in dict.fromkeys(values):
            item = QListWidgetItem(value or "(Blank)", self.values_list)
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setToolTip(value or "(Blank)")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = selected_values is None or value in selected_values
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        layout.addWidget(self.values_list)
        self.search_edit.textChanged.connect(self._filter_options)

        cancel_button = make_action_button("Cancel", compact=True, parent=panel)
        cancel_button.setObjectName("column_filter_cancel")
        cancel_button.clicked.connect(self.close)
        self.apply_button = make_action_button(
            "Apply", variant="primary", compact=True, parent=panel
        )
        self.apply_button.setObjectName("column_filter_apply")
        self.apply_button.clicked.connect(self._apply_selection)
        layout.addWidget(make_action_row([cancel_button, self.apply_button], parent=panel))

        widget_action = QWidgetAction(self)
        widget_action.setDefaultWidget(panel)
        self.addAction(widget_action)

    def _filter_options(self, text: str) -> None:
        query = text.strip().casefold()
        for index in range(self.values_list.count()):
            item = self.values_list.item(index)
            item.setHidden(query not in item.text().casefold())

    def _set_visible_checks(self, state: Qt.CheckState) -> None:
        for index in range(self.values_list.count()):
            item = self.values_list.item(index)
            if not item.isHidden():
                item.setCheckState(state)

    def _apply_selection(self) -> None:
        selected = {
            item.data(Qt.ItemDataRole.UserRole)
            for index in range(self.values_list.count())
            if (item := self.values_list.item(index)).checkState() == Qt.CheckState.Checked
        }
        self.filter_applied.emit(selected)
        self.close()

    def _clear_filter(self) -> None:
        self.filter_applied.emit(None)
        self.close()
