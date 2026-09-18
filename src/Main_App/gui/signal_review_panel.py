"""Compact, recording-grouped presentation of QC signal-review evidence."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import replace
from html import escape

from PySide6.QtCore import Qt, Signal
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

from Main_App.gui.components import SubsectionHeaderLabel, font_for_role, make_action_button
from Main_App.gui.signal_review_model import SignalReviewItem
from Main_App.gui.style_tokens import SECTION_HEADER_CONTENT_GAP, TEXT_SECONDARY
from Main_App.processing.qc_review_episodes import QcReviewEpisode, group_review_episodes


class SignalReviewPanel(QWidget):
    """Let users scan short findings and inspect their complete original evidence."""

    inspect_requested = Signal(object)

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
        self._episodes = group_review_episodes(self._items)
        self._selected_episode: QcReviewEpisode | None = None
        self._recording_count = len({item.recording_key for item in self._items})
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SECTION_HEADER_CONTENT_GAP)

        self.count_label = SubsectionHeaderLabel("", self)
        layout.addWidget(self.count_label)
        review_note = QLabel(
            "Overlapping review windows are grouped for inspection. Linked findings "
            "are not independent confirmations and do not change data automatically.",
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
        self.tree.setAccessibleName("Review findings grouped by recording and episode")
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
        details_header = QHBoxLayout()
        details_header.addWidget(SubsectionHeaderLabel("Finding details", details_panel), 1)
        self.inspect_button = make_action_button(
            "Inspect signal", variant="secondary", parent=details_panel,
        )
        self.inspect_button.setObjectName("signal_review_inspect_signal")
        self.inspect_button.setEnabled(False)
        self.inspect_button.clicked.connect(self._request_inspection)
        details_header.addWidget(self.inspect_button)
        details_layout.addLayout(details_header)
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
        matching_indices = set()
        for index, item in enumerate(self._items):
            if kind and item.kind != kind:
                continue
            if not all(term in item.search_text for term in terms):
                continue
            matching_indices.add(index)
        grouped: OrderedDict[tuple[str, ...], list[tuple[int, QcReviewEpisode]]] = OrderedDict()
        for index, episode in enumerate(self._episodes):
            if matching_indices.intersection(episode.item_indices):
                grouped.setdefault(episode.recording_key, []).append((index, episode))

        visible_count = len(matching_indices)
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
        for recording_episodes in grouped.values():
            identity = self._items[recording_episodes[0][1].item_indices[0]].recording_label
            count = len({
                index for _, episode in recording_episodes
                for index in episode.item_indices if index in matching_indices
            })
            root = QTreeWidgetItem(self.tree, [f"{identity}  ·  {count} review item{'s' if count != 1 else ''}"])
            root.setFirstColumnSpanned(True)
            root.setToolTip(0, identity)
            root.setFont(0, font_for_role("subsection_header", self.tree.font()))
            root.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            for episode_index, episode in recording_episodes:
                episode_root = root
                # Unlocalized singleton findings retain their concise leaf rows.
                if episode.time_spans_s:
                    linked_count = len(episode.item_indices)
                    matching_count = len(matching_indices.intersection(episode.item_indices))
                    label = f"{episode.title} · {linked_count} linked finding{'s' if linked_count != 1 else ''}"
                    if matching_count < linked_count:
                        label += f" ({matching_count} matching)"
                    episode_root = QTreeWidgetItem(root, [label, episode.condition, episode.occurrence, ""])
                    episode_root.setData(0, Qt.ItemDataRole.UserRole, ("episode", episode_index))
                    episode_root.setToolTip(0, episode.timing_note)
                    if first_child is None:
                        first_child = episode_root
                        root.setExpanded(True)
                        episode_root.setExpanded(True)
                for index in episode.item_indices:
                    if index not in matching_indices:
                        continue
                    item = self._items[index]
                    child = QTreeWidgetItem(episode_root, [item.title, item.condition, item.occurrence, item.channels])
                    child.setData(0, Qt.ItemDataRole.UserRole, ("item", index, episode_index))
                    for column in range(4):
                        child.setToolTip(column, child.text(column))
                    if first_child is None:
                        first_child = child
                        root.setExpanded(True)

        if first_child is not None:
            self.tree.setCurrentItem(first_child)
            self.tree.scrollToItem(first_child)
        else:
            self._selected_episode = None
            self.inspect_button.setEnabled(False)
            self.amplitude_help_link.hide()
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
        self._selected_episode = None
        self.inspect_button.setEnabled(False)
        if current is None or current.parent() is None:
            self.details_context_label.setText("Select a finding to read its complete evidence.")
            return
        selection = current.data(0, Qt.ItemDataRole.UserRole)
        if not selection:
            return
        if selection[0] == "episode":
            episode = self._episodes[selection[1]]
            self._show_episode_details(episode)
            self._set_inspection(episode)
            return
        item = self._items[selection[1]]
        episode = self._episodes[selection[2]]
        self._set_inspection(replace(episode, item_indices=(selection[1],)))
        context = [item.recording_label, item.kind]
        if item.condition:
            context.append(f"Condition: {item.condition}")
        if item.occurrence:
            context.append(f"Occurrence: {item.occurrence}")
        if item.channels:
            context.append(f"Channel(s): {item.channels}")
        if episode.time_spans_s:
            context.append(episode.title)
        elif item.source_path:
            context.append("No localized interval")
        self.details_context_label.setText(" · ".join(context))
        self.details_view.setPlainText(item.evidence_text)
        self.amplitude_help_link.setVisible(
            item.kind == "Amplitude" and bool(self.amplitude_help_link.text())
        )

    def _show_episode_details(self, episode: QcReviewEpisode) -> None:
        linked = [self._items[index] for index in episode.item_indices]
        self.details_context_label.setText(
            " · ".join(filter(None, (
                linked[0].recording_label, episode.title,
                f"Condition: {episode.condition}" if episode.condition else "",
                f"Occurrence: {episode.occurrence}" if episode.occurrence else "",
            )))
        )
        self.details_view.setPlainText("\n\n".join((
            episode.timing_note,
            "All linked findings are shown below, including any hidden by the current filters.",
            *(
                f"Finding {index + 1} · {item.kind} · {item.title}"
                + (f" · {item.channels}" if item.channels else "")
                + "\n" + item.evidence_text
                for index, item in zip(episode.item_indices, linked)
            ),
        )))
        self.amplitude_help_link.setVisible(
            any(item.kind == "Amplitude" for item in linked)
            and bool(self.amplitude_help_link.text())
        )

    def _set_inspection(self, episode: QcReviewEpisode) -> None:
        self._selected_episode = episode
        self.inspect_button.setEnabled(bool(episode.source_path))
        self.inspect_button.setToolTip(
            "The source recording path is unavailable for this finding."
            if not episode.source_path else
            "Open the source signal for the selected review interval."
            if episode.time_spans_s else
            "No localized interval was supplied. Open the recording and choose an interval to inspect."
        )

    def _request_inspection(self) -> None:
        if self._selected_episode is not None and self._selected_episode.source_path:
            self.inspect_requested.emit(self._selected_episode)
