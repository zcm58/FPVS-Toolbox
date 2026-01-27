"""Manual outlier exclusion dialog for the Stats tool."""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)


class ManualOutlierExclusionDialog(QDialog):
    manualExclusionsApplied = Signal(set)

    def __init__(
        self,
        *,
        candidates: Iterable[str],
        flagged_map: dict[str, list[str]] | None = None,
        preselected: Iterable[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manual Outlier Exclusion")
        self.setModal(True)

        self.selected_pids: set[str] = set(preselected or [])
        self._flagged_map = flagged_map or {}

        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_label = QLabel("Search:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter participants…")
        search_row.addWidget(search_label)
        search_row.addWidget(self.search_input, 1)
        layout.addLayout(search_row)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.list_widget)

        for pid in candidates:
            flags = self._flagged_map.get(pid, [])
            suffix = f" (FLAGGED: {', '.join(flags)})" if flags else ""
            item = QListWidgetItem(f"{pid}{suffix}")
            item.setData(Qt.UserRole, pid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if pid in self.selected_pids else Qt.Unchecked)
            self.list_widget.addItem(item)

        controls_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select all")
        self.select_none_btn = QPushButton("Select none")
        controls_row.addWidget(self.select_all_btn)
        controls_row.addWidget(self.select_none_btn)
        controls_row.addStretch(1)
        layout.addLayout(controls_row)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        layout.addWidget(self.button_box)
        self.apply_button = self.button_box.button(QDialogButtonBox.Apply)
        if self.apply_button is not None:
            self.apply_button.setEnabled(self.list_widget.count() > 0)

        self.search_input.textChanged.connect(self._apply_filter)
        self.select_all_btn.clicked.connect(self._select_all)
        self.select_none_btn.clicked.connect(self._select_none)
        if self.apply_button is not None:
            self.apply_button.clicked.connect(self._apply_changes)
        self.button_box.rejected.connect(self.reject)

    def _apply_filter(self, text: str) -> None:
        filter_text = text.strip().lower()
        for idx in range(self.list_widget.count()):
            item = self.list_widget.item(idx)
            pid = str(item.data(Qt.UserRole)).lower()
            item.setHidden(bool(filter_text) and filter_text not in pid)

    def _select_all(self) -> None:
        for idx in range(self.list_widget.count()):
            item = self.list_widget.item(idx)
            item.setCheckState(Qt.Checked)

    def _select_none(self) -> None:
        for idx in range(self.list_widget.count()):
            item = self.list_widget.item(idx)
            item.setCheckState(Qt.Unchecked)

    def _apply_changes(self) -> None:
        selections = set()
        for idx in range(self.list_widget.count()):
            item = self.list_widget.item(idx)
            if item.checkState() == Qt.Checked:
                selections.add(str(item.data(Qt.UserRole)))
        self.selected_pids = selections
        self.manualExclusionsApplied.emit(set(selections))
        self.accept()
