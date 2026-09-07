"""Embedded visual editor for ordered FPVS regions of interest."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QLabel,
    QListWidgetItem,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import StatusBanner
from Main_App.gui.roi_electrode_selector import ElectrodeMapWidget, ROIMembership
from Main_App.gui.roi_electrode_selector_state import BIOSEMI64_LABELS
from Main_App.gui.roi_settings_widgets import (
    ROI_COLOR_PALETTE,
    ROIEditorSidePanel,
    configure_roi_tab_order,
    roi_color_for_id,
    roi_color_icon,
)
from Main_App.gui.roi_visual_editor_state import ROIEditorCollection, ROIEditorEntry


class ROISettingsEditor(QWidget):
    """Visual-first ROI editor that preserves the existing settings pair API."""

    def __init__(
        self,
        parent: QWidget | None = None,
        pairs: list[tuple[str, list[str]]] | None = None,
        *,
        canonical_electrodes: Sequence[str] = (),
        default_rois: Sequence[tuple[str, Sequence[str]]],
        current_montage: str,
        montage_label: str = "BioSemi 64",
    ) -> None:
        super().__init__(parent)
        self._canonical_electrodes = tuple(canonical_electrodes) or BIOSEMI64_LABELS
        self._default_rois = tuple(
            (str(name), tuple(str(electrode) for electrode in electrodes))
            for name, electrodes in default_rois
        )
        self._current_montage = str(current_montage)
        self._collection = ROIEditorCollection(self._canonical_electrodes)
        self._rebuilding = False
        self._pending_clear_entry_id: int | None = None
        self.entries = self._collection.entries

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(6)

        self.montage_label = QLabel(f"Montage: {montage_label}", self)
        self.montage_label.setObjectName("settings_rois_montage_label")
        self.montage_label.setAccessibleName(f"ROI montage: {montage_label}")
        root_layout.addWidget(self.montage_label)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("settings_rois_splitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.map_pane = QWidget(self.splitter)
        self.map_pane.setObjectName("settings_rois_map_pane")
        map_layout = QVBoxLayout(self.map_pane)
        map_layout.setContentsMargins(0, 0, 4, 0)
        map_layout.setSpacing(0)
        self.map_widget = ElectrodeMapWidget(self._canonical_electrodes, self.map_pane)
        map_layout.addWidget(self.map_widget, 1)

        self.roi_pane = ROIEditorSidePanel(self.splitter)
        self.roi_list = self.roi_pane.roi_list
        self.add_button = self.roi_pane.add_button
        self.remove_button = self.roi_pane.remove_button
        self.name_edit = self.roi_pane.name_edit
        self.clear_button = self.roi_pane.clear_button
        self.unmapped_pane = self.roi_pane.unmapped_pane
        self.unmapped_list = self.roi_pane.unmapped_list
        self.remove_unmapped_button = self.roi_pane.remove_unmapped_button

        self.splitter.addWidget(self.map_pane)
        self.splitter.addWidget(self.roi_pane)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([620, 330])
        root_layout.addWidget(self.splitter, 1)

        self.status = StatusBanner("", self, variant="info")
        self.status.setObjectName("settings_rois_status")
        self.status.label.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setVisible(False)
        root_layout.addWidget(self.status)

        self.map_widget.selection_changed.connect(self._on_map_selection_changed)
        self.roi_list.currentRowChanged.connect(self._on_active_row_changed)
        self.name_edit.textChanged.connect(self._on_name_changed)
        self.add_button.clicked.connect(lambda _checked=False: self.add_entry())
        self.remove_button.clicked.connect(lambda _checked=False: self.remove_active_entry())
        self.clear_button.clicked.connect(lambda _checked=False: self.clear_active_roi())
        self.remove_unmapped_button.clicked.connect(
            lambda _checked=False: self.remove_selected_unmapped_label()
        )
        self.unmapped_list.currentRowChanged.connect(
            lambda row: self.remove_unmapped_button.setEnabled(row >= 0)
        )
        configure_roi_tab_order(
            self.roi_pane,
            tuple(self.map_widget.electrode_buttons.values()),
        )

        self.set_pairs(pairs or [])

    def current_montage(self) -> str:
        return self._current_montage

    def show_status(self, text: str, variant: str = "info") -> None:
        self.status.set_variant(variant)
        self.status.set_text(text)
        self.status.setVisible(bool(text))

    def add_entry(
        self,
        name: str = "",
        electrodes: str | Sequence[str] = "",
    ) -> None:
        self._clear_pending_confirmations()
        row = self._collection.append(name, electrodes)
        self._append_list_item(row)
        self.roi_list.setCurrentRow(row)
        self.name_edit.setFocus()
        self.name_edit.selectAll()
        self.show_status(
            "New ROI draft added. Name it and choose at least one electrode on the map.",
            "info",
        )

    def remove_active_entry(self) -> None:
        self._clear_pending_confirmations()
        row = self.roi_list.currentRow()
        if not 0 <= row < len(self.entries):
            return
        if self.entries[row].is_default:
            self.show_status(
                f"{self.entries[row].display_name} is a built-in ROI and cannot be removed.",
                "info",
            )
            return
        removed, new_row, appended_blank = self._collection.remove(row)
        self.roi_list.takeItem(row)
        if appended_blank:
            self._append_list_item(0)
        self.roi_list.setCurrentRow(new_row)
        self._refresh_all_list_items()
        self._sync_active_roi()
        self.show_status(
            f"Removed {removed.display_name} from this Settings draft.", "info"
        )

    def clear_active_roi(self) -> str | None:
        entry = self._active_entry()
        if entry is None:
            return None
        unmapped = entry.selection.unmapped_electrodes()
        if unmapped and self._pending_clear_entry_id != entry.entry_id:
            self._pending_clear_entry_id = entry.entry_id
            self.show_status(
                f"Clearing {entry.display_name} will remove its legacy / unmapped labels: "
                + ", ".join(unmapped)
                + ". Activate Clear Active ROI again to confirm.",
                "warning",
            )
            return "confirmation_required"
        self._clear_pending_confirmations()
        entry.selection.clear()
        self._refresh_active_entry()
        self.show_status(
            f"Cleared every electrode from {entry.display_name} in this Settings draft.",
            "info",
        )
        return "cleared"

    def remove_selected_unmapped_label(self) -> None:
        self._clear_pending_confirmations()
        entry = self._active_entry()
        row = self.unmapped_list.currentRow()
        if entry is None or row < 0:
            return
        labels = list(entry.selection.unmapped_electrodes())
        if row >= len(labels):
            return
        removed = labels.pop(row)
        entry.selection.set_unmapped(labels)
        self._refresh_active_entry()
        self.show_status(
            f"Removed one {removed} legacy / unmapped label from this Settings draft.",
            "info",
        )

    def get_pairs(self) -> list[tuple[str, list[str]]]:
        return self._collection.get_pairs()

    def validate_draft(self) -> bool:
        """Reject only partially defined rows; a wholly blank placeholder is valid."""

        self._clear_pending_confirmations()
        index = self._collection.first_partial_index()
        if index is None:
            return True
        entry = self.entries[index]
        self.select_roi(index)
        if entry.name.strip():
            self.map_widget.electrode_buttons["Cz"].setFocus()
            guidance = (
                "Choose at least one electrode on the scalp map."
                if entry.is_default
                else "Choose at least one electrode on the scalp map or remove the ROI."
            )
        else:
            self.name_edit.setFocus()
            guidance = "Enter an ROI name or clear its electrode selection."
        self.show_status(f"ROI {index + 1} is incomplete. {guidance}", "warning")
        return False

    def set_pairs(self, pairs: list[tuple[str, list[str]]]) -> None:
        self._clear_pending_confirmations()
        self._rebuilding = True
        try:
            self._collection.reset(pairs, default_pairs=self._default_rois)
            self.roi_list.clear()
            for index in range(len(self.entries)):
                self._append_list_item(index)
            self.roi_list.setCurrentRow(0)
        finally:
            self._rebuilding = False
        self._sync_active_roi()

    def active_roi_index(self) -> int:
        return self.roi_list.currentRow()

    def select_roi(self, index: int) -> None:
        if not 0 <= index < len(self.entries):
            raise IndexError(index)
        self.roi_list.setCurrentRow(index)

    def roi_id(self, index: int) -> int:
        return self.entries[index].entry_id

    def roi_color(self, index: int) -> str:
        return self._color_for_entry(self.entries[index])

    def is_default_roi(self, index: int) -> bool:
        return self.entries[index].is_default

    @staticmethod
    def _color_for_entry(entry: ROIEditorEntry) -> str:
        return roi_color_for_id(entry.entry_id)

    def _append_list_item(self, index: int) -> None:
        entry = self.entries[index]
        color = self._color_for_entry(entry)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, entry.entry_id)
        item.setData(int(Qt.ItemDataRole.UserRole) + 1, color)
        item.setIcon(roi_color_icon(color))
        self.roi_list.addItem(item)
        self._update_list_item(index)

    def _entry_label(self, index: int) -> str:
        return f"ROI {index + 1}: {self.entries[index].display_name}"

    def _update_list_item(self, index: int) -> None:
        if not 0 <= index < len(self.entries):
            return
        entry = self.entries[index]
        item = self.roi_list.item(index)
        if item is None:
            return
        entry_count, map_count = entry.counts()
        unmapped_count = len(entry.selection.unmapped_electrodes())
        count_text = f"{entry_count} electrode entr{'y' if entry_count == 1 else 'ies'}"
        if map_count != entry_count:
            count_text += f" / {map_count} map position{'s' if map_count != 1 else ''}"
        if unmapped_count:
            count_text += f" / {unmapped_count} legacy"
        item.setText(
            f"{entry.display_name}  ·  Built-in"
            if entry.is_default
            else entry.display_name
        )
        protection = (
            " Built-in ROI; its name and row are protected."
            if entry.is_default
            else ""
        )
        accessible = (
            f"{self._entry_label(index)}. {count_text}.{protection} Select to edit."
        )
        item.setToolTip(accessible)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, accessible)
        item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, accessible)

    def _refresh_all_list_items(self) -> None:
        for index in range(len(self.entries)):
            self._update_list_item(index)

    def _active_entry(self) -> ROIEditorEntry | None:
        row = self.roi_list.currentRow()
        if 0 <= row < len(self.entries):
            return self.entries[row]
        return None

    def _on_active_row_changed(self, _row: int) -> None:
        self._clear_pending_confirmations()
        if not self._rebuilding:
            self._sync_active_roi()

    def _on_name_changed(self, text: str) -> None:
        if self._rebuilding:
            return
        self._clear_pending_confirmations()
        row = self.roi_list.currentRow()
        if not 0 <= row < len(self.entries):
            return
        if self.entries[row].is_default:
            with QSignalBlocker(self.name_edit):
                self.name_edit.setText(self.entries[row].name)
            return
        self.entries[row].name = text
        self._update_list_item(row)
        self._sync_map_context()
        self._refresh_accessibility()

    def _on_map_selection_changed(self, label: str, checked: bool) -> None:
        self._clear_pending_confirmations()
        entry = self._active_entry()
        if entry is None:
            return
        entry.selection.set_checked(label, checked)
        self._refresh_active_entry()
        action = "Added" if checked else "Removed"
        relation = "to" if checked else "from"
        self.show_status(
            f"{action} {label} {relation} {entry.display_name}.",
            "info",
        )

    def _refresh_active_entry(self) -> None:
        row = self.roi_list.currentRow()
        self._update_list_item(row)
        self._sync_active_roi()

    def _sync_active_roi(self) -> None:
        entry = self._active_entry()
        if entry is None:
            return
        with QSignalBlocker(self.name_edit):
            self.name_edit.setText(entry.name)
        self.name_edit.setReadOnly(entry.is_default)
        self.name_edit.setToolTip(
            "Built-in ROI names cannot be changed; edit membership on the scalp map."
            if entry.is_default
            else "Edit the active ROI name."
        )
        self._sync_map_context()

        electrodes = entry.selection.selected_electrodes()
        unmapped = entry.selection.unmapped_electrodes()
        self.clear_button.setEnabled(bool(electrodes))
        self.remove_button.setEnabled(not entry.is_default)
        if entry.is_default:
            self.remove_button.setToolTip(
                f"{entry.display_name} is a built-in ROI and cannot be removed."
            )
        else:
            self.remove_button.setToolTip(f"Remove {entry.display_name}.")

        with QSignalBlocker(self.unmapped_list):
            self.unmapped_list.clear()
            for occurrence, label in enumerate(unmapped, start=1):
                item = QListWidgetItem(label)
                item.setToolTip(
                    f"Occurrence {occurrence}: {label}. This value is preserved until explicitly removed."
                )
                self.unmapped_list.addItem(item)
        self.unmapped_pane.setVisible(bool(unmapped))
        self.remove_unmapped_button.setEnabled(False)
        self._refresh_accessibility()

    def _sync_map_context(self) -> None:
        entry = self._active_entry()
        if entry is None:
            return
        memberships: dict[str, list[ROIMembership]] = defaultdict(list)
        for index, candidate in enumerate(self.entries):
            member_label = self._entry_label(index)
            for electrode in candidate.selection.selected_map_labels():
                memberships[electrode].append(
                    (member_label, self._color_for_entry(candidate))
                )
        row = self.roi_list.currentRow()
        self.map_widget.set_roi_context(
            entry.selection.selected_map_labels(),
            memberships_by_label=memberships,
            active_color=self._color_for_entry(entry),
            active_roi_label=self._entry_label(row),
        )

    def _refresh_accessibility(self) -> None:
        entry = self._active_entry()
        if entry is None:
            return
        row = self.roi_list.currentRow()
        label = self._entry_label(row)
        self.name_edit.setAccessibleName(f"Name for {label}")
        self.name_edit.setAccessibleDescription(
            "This built-in ROI name is fixed. Electrode membership is edited on the scalp map."
            if entry.is_default
            else "Edit the active ROI name. Electrode membership is edited on the scalp map."
        )
        self.remove_button.setAccessibleName(
            f"{label} is built in and cannot be removed"
            if entry.is_default
            else f"Remove {label}"
        )
        self.clear_button.setAccessibleName(f"Clear every electrode from {label}")
        self.remove_unmapped_button.setAccessibleName(
            f"Remove the selected legacy or unmapped label from {label}"
        )

    def _clear_pending_confirmations(self) -> None:
        self._pending_clear_entry_id = None


__all__ = ["ROISettingsEditor", "ROI_COLOR_PALETTE"]
