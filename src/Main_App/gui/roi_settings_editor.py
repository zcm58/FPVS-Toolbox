"""Embedded visual editor for ordered FPVS regions of interest."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QListWidgetItem,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import StatusBanner, SubsectionHeaderLabel
from Main_App.gui.roi_electrode_selector import ElectrodeMapWidget, ROIMembership
from Main_App.gui.roi_electrode_selector_state import BIOSEMI64_LABELS
from Main_App.gui.roi_settings_widgets import (
    ROI_COLOR_PALETTE,
    ROIEditorSidePanel,
    ROIEditorToolbar,
    ROIPresetProvider,
    configure_roi_tab_order,
    map_selection_summary,
    roi_color_for_id,
    roi_color_icon,
)
from Main_App.gui.roi_visual_editor_state import ROIEditorCollection, ROIEditorEntry


class ROISettingsEditor(QWidget):
    """Visual-first ROI editor that preserves the existing settings pair API."""

    save_custom_presets_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        pairs: list[tuple[str, list[str]]] | None = None,
        *,
        canonical_electrodes: Sequence[str] = (),
        montage_options: Sequence[tuple[str, str]] = (),
        current_montage: str = "",
        preset_provider: ROIPresetProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self._canonical_electrodes = tuple(canonical_electrodes) or BIOSEMI64_LABELS
        self._preset_provider = preset_provider or (lambda _montage: ())
        self._collection = ROIEditorCollection(self._canonical_electrodes)
        self._rebuilding = False
        self._pending_preset_reset: tuple[int, str, tuple[str, ...]] | None = None
        self._pending_clear_entry_id: int | None = None
        self.entries = self._collection.entries

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(10)

        self.toolbar = ROIEditorToolbar(
            montage_options,
            current_montage,
            self._preset_provider,
            self,
        )
        self.montage_combo = self.toolbar.montage_combo
        self.preset_combo = self.toolbar.preset_combo
        self.add_preset_button = self.toolbar.add_preset_button
        self.save_presets_button = self.toolbar.save_presets_button
        root_layout.addWidget(self.toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("settings_rois_splitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.map_pane = QWidget(self.splitter)
        self.map_pane.setObjectName("settings_rois_map_pane")
        map_layout = QVBoxLayout(self.map_pane)
        map_layout.setContentsMargins(0, 0, 4, 0)
        map_layout.setSpacing(6)
        map_layout.addWidget(SubsectionHeaderLabel("Interactive scalp map", self.map_pane))
        self.active_summary = QLabel(self.map_pane)
        self.active_summary.setObjectName("settings_rois_active_summary")
        self.active_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.active_summary.setWordWrap(True)
        map_layout.addWidget(self.active_summary)
        self.map_widget = ElectrodeMapWidget(self._canonical_electrodes, self.map_pane)
        map_layout.addWidget(self.map_widget, 1)
        self.selection_summary = QLabel(self.map_pane)
        self.selection_summary.setObjectName("settings_rois_selection_summary")
        self.selection_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.selection_summary.setWordWrap(True)
        map_layout.addWidget(self.selection_summary)

        self.roi_pane = ROIEditorSidePanel(self.splitter)
        self.roi_list = self.roi_pane.roi_list
        self.add_button = self.roi_pane.add_button
        self.remove_button = self.roi_pane.remove_button
        self.name_edit = self.roi_pane.name_edit
        self.electrode_count = self.roi_pane.electrode_count
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
        self.status.setObjectName("settings_rois_preset_status")
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
        self.montage_combo.currentIndexChanged.connect(self._on_montage_changed)
        self.add_preset_button.clicked.connect(
            lambda _checked=False: self.add_selected_preset()
        )
        self.preset_combo.currentIndexChanged.connect(
            lambda _index: self._clear_pending_confirmations()
        )
        self.save_presets_button.clicked.connect(self._request_save_custom_presets)
        configure_roi_tab_order(
            self.toolbar,
            self.roi_pane,
            tuple(self.map_widget.electrode_buttons.values()),
        )

        self.set_pairs(pairs or [])
        self.refresh_presets()

    def current_montage(self) -> str:
        return self.toolbar.current_montage()

    def selected_preset(self) -> tuple[str, list[str], bool] | None:
        return self.toolbar.selected_preset()

    def refresh_presets(self) -> None:
        self._clear_pending_confirmations()
        self.toolbar.refresh_presets()

    def add_selected_preset(self) -> str | None:
        self._pending_clear_entry_id = None
        preset = self.selected_preset()
        if preset is None:
            self.show_status("No ROI preset is selected.", "warning")
            return None
        name, electrodes, _is_default = preset
        dropped_unmapped: tuple[str, ...] = ()
        matching_index = self._collection.first_name_match(name)
        if matching_index is not None:
            self.roi_list.setCurrentRow(matching_index)
            dropped_unmapped = self._collection.dropped_unmapped_occurrences(
                matching_index,
                electrodes,
            )
            confirmation = (
                self.entries[matching_index].entry_id,
                name.casefold(),
                tuple(electrodes),
            )
            if dropped_unmapped and self._pending_preset_reset != confirmation:
                self._pending_preset_reset = confirmation
                self.show_status(
                    f"Resetting {name} will remove its legacy / unmapped labels: "
                    + ", ".join(dropped_unmapped)
                    + ". Click Add / Reset Preset ROI again to confirm.",
                    "warning",
                )
                return "confirmation_required"
        self._clear_pending_confirmations()
        result = self.add_or_update_entry(name, electrodes)
        action = "Updated" if result == "updated" else "Added"
        if dropped_unmapped:
            self.show_status(
                f"{action} {name} from the preset and removed its legacy / unmapped labels: "
                + ", ".join(dropped_unmapped)
                + ".",
                "warning",
            )
        else:
            self.show_status(f"{action} {name} from the selected preset.", "success")
        return result

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

    def add_or_update_entry(self, name: str, electrodes: list[str]) -> str:
        self._clear_pending_confirmations()
        result, row, created = self._collection.add_or_update(name, electrodes)
        if created:
            self._append_list_item(row)
        else:
            self._update_list_item(row)
        self.roi_list.setCurrentRow(row)
        self._sync_active_roi()
        return result

    def remove_active_entry(self) -> None:
        self._clear_pending_confirmations()
        row = self.roi_list.currentRow()
        if not 0 <= row < len(self.entries):
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
        self._pending_preset_reset = None
        entry = self._active_entry()
        if entry is None:
            return None
        unmapped = entry.selection.unmapped_electrodes()
        if unmapped and self._pending_clear_entry_id != entry.entry_id:
            self._pending_clear_entry_id = entry.entry_id
            self.show_status(
                f"Clearing {entry.display_name} will remove its legacy / unmapped labels: "
                + ", ".join(unmapped)
                + ". Click Clear Active ROI again to confirm.",
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
            guidance = "Choose at least one electrode on the scalp map or remove the ROI."
        else:
            self.name_edit.setFocus()
            guidance = "Enter an ROI name or clear its electrode selection."
        self.show_status(f"ROI {index + 1} is incomplete. {guidance}", "warning")
        return False

    def set_pairs(self, pairs: list[tuple[str, list[str]]]) -> None:
        self._clear_pending_confirmations()
        self._rebuilding = True
        try:
            self._collection.reset(pairs)
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
        item.setText(f"{entry.display_name}  ·  {count_text}")
        accessible = f"{self._entry_label(index)}. {count_text}. Select to edit."
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
        self.entries[row].name = text
        self._update_list_item(row)
        self._refresh_active_heading()
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

    def _on_montage_changed(self, _index: int) -> None:
        self.refresh_presets()
        self.show_status("")

    def _request_save_custom_presets(self, _checked: bool = False) -> None:
        self._clear_pending_confirmations()
        self.save_custom_presets_requested.emit()

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
        self._sync_map_context()

        electrodes = entry.selection.selected_electrodes()
        map_count = len(entry.selection.selected_map_labels())
        unmapped = entry.selection.unmapped_electrodes()
        self._refresh_active_heading()
        mapped_labels = entry.selection.selected_map_labels()
        self.selection_summary.setText(map_selection_summary(mapped_labels))
        full_map_summary = (
            "All selected map positions: " + ", ".join(mapped_labels)
            if mapped_labels
            else "No mapped electrodes selected for this ROI."
        )
        self.selection_summary.setToolTip(full_map_summary)
        self.selection_summary.setAccessibleDescription(full_map_summary)
        self.electrode_count.setText(
            f"{len(electrodes)} electrode entr{'y' if len(electrodes) == 1 else 'ies'}; "
            f"{map_count} visible map position{'s' if map_count != 1 else ''}."
        )
        self.clear_button.setEnabled(bool(electrodes))

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

    def _refresh_active_heading(self) -> None:
        entry = self._active_entry()
        if entry is None:
            return
        row = self.roi_list.currentRow()
        electrodes = entry.selection.selected_electrodes()
        map_count = len(entry.selection.selected_map_labels())
        self.active_summary.setText(
            f"Editing {self._entry_label(row)} — {len(electrodes)} electrode "
            f"entr{'y' if len(electrodes) == 1 else 'ies'} ({map_count} map "
            f"position{'s' if map_count != 1 else ''})."
        )

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
            "Edit the active ROI name. Electrode membership is edited on the scalp map."
        )
        self.remove_button.setAccessibleName(f"Remove {label}")
        self.clear_button.setAccessibleName(f"Clear every electrode from {label}")
        self.remove_unmapped_button.setAccessibleName(
            f"Remove the selected legacy or unmapped label from {label}"
        )

    def _clear_pending_confirmations(self) -> None:
        self._pending_preset_reset = None
        self._pending_clear_entry_id = None


__all__ = ["ROISettingsEditor", "ROI_COLOR_PALETTE", "ROIPresetProvider"]
