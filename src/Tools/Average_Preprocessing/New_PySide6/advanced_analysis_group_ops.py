"""Group management mixin for the PySide6 averaging window."""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QListWidget, QMessageBox
import logging

logger = logging.getLogger(__name__)


class AdvancedAnalysisGroupOpsMixin:
    """Create, delete and rename averaging groups."""

    groups_listbox: QListWidget
    defined_groups: list[dict]
    source_eeg_files: list[str]
    selected_group_index: int | None

    def create_new_group(self) -> None:
        """Prompt the user for a group name and event IDs."""

        name, ok = QInputDialog.getText(
            self, "New Averaging Group", "Enter a name for this averaging group:"
        )
        if not ok or not name.strip():
            self.log("Group creation cancelled.")
            return
        name = name.strip()
        if any(g["name"] == name for g in self.defined_groups):
            QMessageBox.warning(self, "Error", f"A group named '{name}' already exists.")
            return

        id_str, ok = QInputDialog.getText(
            self,
            "Event IDs to Average",
            "Enter the event IDs to average within each participant, separated by commas (e.g. 11,12):",
        )
        if not ok or not id_str.strip():
            self.log("Group creation cancelled (no IDs).")
            return
        try:
            ids_to_average = [int(x.strip()) for x in id_str.split(",") if x.strip()]
        except ValueError:
            QMessageBox.warning(self, "Error", "Enter only integers separated by commas.")
            return
        if not ids_to_average:
            QMessageBox.warning(self, "Error", "Enter at least one event ID.")
            return
        if not self.source_eeg_files:
            QMessageBox.warning(self, "Error", "No EEG files selected. Add files first.")
            return

        mapping_rule = {"output_label": name, "sources": []}
        for f_path in self.source_eeg_files:
            for event_id_val in ids_to_average:
                mapping_rule["sources"].append(
                    {
                        "file_path": f_path,
                        "original_label": str(event_id_val),
                        "original_id": event_id_val,
                    }
                )

        averaging_method = "Pool Trials" if self.radio_pool.isChecked() else "Average of Averages"
        new_grp_data = {
            "name": name,
            "file_paths": list(self.source_eeg_files),
            "condition_mappings": [mapping_rule],
            "averaging_method": averaging_method,
            "config_saved": True,
            "ui_mapping_rules": [],
        }
        self.defined_groups.append(new_grp_data)
        self._update_groups_listbox()
        self.log(
            f"Created group '{name}' averaging IDs {ids_to_average} in all {len(self.source_eeg_files)} files."
        )
        self.selected_group_index = len(self.defined_groups) - 1
        self.groups_listbox.setCurrentRow(self.selected_group_index)
        self._update_start_processing_button_state()

    def delete_selected_group(self) -> None:
        """Remove the currently selected averaging group."""

        if self.selected_group_index is None:
            self.log("No group selected to delete.")
            return
        group_name = self.defined_groups[self.selected_group_index]["name"]
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete group '{group_name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            del self.defined_groups[self.selected_group_index]
            self.selected_group_index = None
            self._update_groups_listbox()
            self._update_start_processing_button_state()
            self.log(f"Deleted group: {group_name}")

    def rename_selected_group(self) -> None:
        """Prompt the user to rename the currently selected group."""

        if self.selected_group_index is None:
            self.log("No group selected to rename.")
            return
        current_name = self.defined_groups[self.selected_group_index]["name"]
        new_name, ok = QInputDialog.getText(
            self, "Rename Averaging Group", f"Enter a new name for '{current_name}':"
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        for i, grp in enumerate(self.defined_groups):
            if i != self.selected_group_index and grp["name"] == new_name:
                QMessageBox.warning(
                    self, "Error", f"A group named '{new_name}' already exists."
                )
                return
        self.defined_groups[self.selected_group_index]["name"] = new_name
        self.defined_groups[self.selected_group_index]["config_saved"] = False
        self._update_groups_listbox()
        self.log(f"Renamed group to '{new_name}'.")

    def _update_groups_listbox(self) -> None:
        self.groups_listbox.clear()
        for g in self.defined_groups:
            status = "" if g.get("config_saved", False) else " (Unsaved)"
            self.groups_listbox.addItem(
                f"{g['name']} ({len(g['file_paths'])} files){status}"
            )
        if self.selected_group_index is not None and self.selected_group_index < len(
            self.defined_groups
        ):
            self.groups_listbox.setCurrentRow(self.selected_group_index)

    def on_group_select(self, row: int) -> None:
        """Handle list selection changes."""

        if row == -1:
            return
        self.selected_group_index = row
        self.log(f"Selected group: {self.defined_groups[row]['name']}")
        self._update_start_processing_button_state()

    def _clear_group_config_display(self) -> None:
        """Placeholder for config UI clearing in PySide6 version."""

        # The PySide6 GUI builds configuration widgets differently than the
        # legacy customtkinter version, so this function intentionally does
        # nothing here.
        return
