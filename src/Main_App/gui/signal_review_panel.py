"""Compact, recording-grouped presentation of QC signal-review evidence."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import SubsectionHeaderLabel, font_for_role
from Main_App.gui.signal_review_model import SignalReviewItem
from Main_App.gui.style_tokens import SECTION_HEADER_CONTENT_GAP, TEXT_SECONDARY


class SignalReviewPanel(QWidget):
    """Let users scan short findings and inspect their complete original evidence."""

    def __init__(
        self,
        items: Sequence[SignalReviewItem],
        parent: QWidget | None = None,
        *,
        amplitude_help_url: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("signal_review_panel")
        self._items = tuple(items)
        self._recording_count = len({item.recording_key for item in self._items})
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SECTION_HEADER_CONTENT_GAP)

        self.count_label = SubsectionHeaderLabel("", self)
        layout.addWidget(self.count_label)
        review_note = QLabel(
            "These review items do not change data automatically.",
            self,
        )
        review_note.setWordWrap(True)
        review_note.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(review_note)

        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(SECTION_HEADER_CONTENT_GAP)
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Search participant, recording, condition, channel, or evidence…")
        self.search_edit.setAccessibleName("Search review findings")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumHeight(32)
        filters.addWidget(self.search_edit, 1)
        self.kind_combo = QComboBox(self)
        self.kind_combo.setAccessibleName("Filter by finding type")
        self.kind_combo.setMinimumHeight(32)
        self.kind_combo.addItem("All finding types", "")
        for kind in sorted({item.kind for item in self._items}, key=str.casefold):
            self.kind_combo.addItem(kind, kind)
        filters.addWidget(self.kind_combo)
        layout.addLayout(filters)

        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.setChildrenCollapsible(False)
        self.tree = QTreeWidget(self.splitter)
        self.tree.setAccessibleName("Review findings grouped by recording")
        self.tree.setHeaderLabels(["Finding", "Condition", "Occurrence", "Channel(s)"])
        self.tree.setUniformRowHeights(True)
        self.tree.setWordWrap(False)
        self.tree.setStyleSheet("QTreeWidget::item { padding: 4px 0; }")
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setMinimumHeight(140)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 170), (2, 95), (3, 110)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.tree.setColumnWidth(column, width)

        details_panel = QWidget(self.splitter)
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(0, SECTION_HEADER_CONTENT_GAP, 0, 0)
        details_layout.setSpacing(SECTION_HEADER_CONTENT_GAP)
        details_layout.addWidget(SubsectionHeaderLabel("Finding details", details_panel))
        self.details_context_label = QLabel(details_panel)
        self.details_context_label.setTextFormat(Qt.TextFormat.PlainText)
        self.details_context_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details_context_label.setWordWrap(True)
        self.details_context_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        details_layout.addWidget(self.details_context_label)
        self.amplitude_help_link = QLabel(details_panel)
        self.amplitude_help_link.setText(
            f'<a href="{escape(amplitude_help_url, quote=True)}">'
            "BioSemi: referencing and shared noise</a>" if amplitude_help_url else ""
        )
        self.amplitude_help_link.setOpenExternalLinks(True)
        self.amplitude_help_link.hide()
        details_layout.addWidget(self.amplitude_help_link)
        self.details_view = QPlainTextEdit(details_panel)
        self.details_view.setAccessibleName("Complete finding evidence")
        self.details_view.setReadOnly(True)
        self.details_view.setMinimumHeight(80)
        details_layout.addWidget(self.details_view, 1)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([300, 180])
        layout.addWidget(self.splitter, 1)

        self.search_edit.textChanged.connect(self._rebuild_tree)
        self.kind_combo.currentIndexChanged.connect(self._rebuild_tree)
        self.tree.currentItemChanged.connect(self._show_details)
        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        terms = self.search_edit.text().casefold().split()
        kind = self.kind_combo.currentData()
        grouped: OrderedDict[tuple[str, ...], list[tuple[int, SignalReviewItem]]] = OrderedDict()
        for index, item in enumerate(self._items):
            if kind and item.kind != kind:
                continue
            if not all(term in item.search_text for term in terms):
                continue
            grouped.setdefault(item.recording_key, []).append((index, item))

        visible_count = sum(len(items) for items in grouped.values())
        if terms or kind:
            count_text = (
                f"{visible_count} of {len(self._items)} review items · "
                f"{len(grouped)} of {self._recording_count} recordings"
            )
        else:
            count_text = f"{visible_count} review items · {len(grouped)} recordings"
        self.count_label.setText(count_text)

        self.tree.clear()
        first_child: QTreeWidgetItem | None = None
        for recording_items in grouped.values():
            identity = recording_items[0][1].recording_label
            count = len(recording_items)
            root = QTreeWidgetItem(self.tree, [f"{identity}  ·  {count} review item{'s' if count != 1 else ''}"])
            root.setFirstColumnSpanned(True)
            root.setToolTip(0, identity)
            root.setFont(0, font_for_role("subsection_header", self.tree.font()))
            root.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            for index, item in recording_items:
                child = QTreeWidgetItem(root, [item.title, item.condition, item.occurrence, item.channels])
                child.setData(0, Qt.ItemDataRole.UserRole, index)
                for column in range(4):
                    child.setToolTip(column, child.text(column))
                if first_child is None:
                    first_child = child
                    root.setExpanded(True)

        if first_child is not None:
            self.tree.setCurrentItem(first_child)
            self.tree.scrollToItem(first_child)
        else:
            self.details_context_label.setText("No matching findings." if self._items else "No review findings.")
            self.details_view.clear()
            self.details_view.setPlaceholderText(
                "Try another search or choose All finding types." if self._items else "There are no findings to review."
            )

    def _show_details(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        self.details_view.clear()
        self.details_view.setPlaceholderText("")
        self.amplitude_help_link.hide()
        if current is None or current.parent() is None:
            self.details_context_label.setText("Select a finding to read its complete evidence.")
            return
        item = self._items[current.data(0, Qt.ItemDataRole.UserRole)]
        context = [item.recording_label, item.kind]
        if item.condition:
            context.append(f"Condition: {item.condition}")
        if item.occurrence:
            context.append(f"Occurrence: {item.occurrence}")
        if item.channels:
            context.append(f"Channel(s): {item.channels}")
        self.details_context_label.setText(" · ".join(context))
        self.details_view.setPlainText(item.details)
        self.amplitude_help_link.setVisible(
            item.kind == "Amplitude" and bool(self.amplitude_help_link.text())
        )
