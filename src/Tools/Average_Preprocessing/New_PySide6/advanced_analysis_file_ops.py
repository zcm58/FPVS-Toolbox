"""File operations mixin for the PySide6 averaging window."""

from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtWidgets import QFileDialog, QListWidget
import logging

logger = logging.getLogger(__name__)


class AdvancedAnalysisFileOpsMixin:
    """Handle adding and removing source EEG files."""

    source_files_listbox: QListWidget
    source_eeg_files: list[str]
    defined_groups: list[dict]
    selected_group_index: int | None

    def add_source_files(self) -> None:
        """Prompt the user for EEG files and add them to the list."""

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select EEG Files",
            "",
            "BDF Files (*.bdf);;All Files (*)",
        )
        if not files:
            return

        added = 0
        for path in files:
            if path not in self.source_eeg_files:
                self.source_eeg_files.append(path)
                added += 1
        if added:
            self.source_eeg_files.sort()
            self._update_source_files_listbox()
            self.log(
                f"Added {added} source file(s). Total: {len(self.source_eeg_files)}."
            )

    def remove_source_files(self) -> None:
        """Remove the currently selected source files."""

        selected_rows = [i.row() for i in self.source_files_listbox.selectedIndexes()]
        if not selected_rows:
            self.log("No source files selected to remove.")
            return

        removed = [self.source_eeg_files[i] for i in selected_rows]
        self.source_eeg_files = [
            f for i, f in enumerate(self.source_eeg_files) if i not in selected_rows
        ]
        if removed:
            self._update_source_files_listbox()
            self.log(f"Removed {len(removed)} file(s) from source list.")
            self._check_groups_for_removed_files(removed)

    def _update_source_files_listbox(self) -> None:
        """Refresh the list widget to match ``self.source_eeg_files``."""

        self.source_files_listbox.clear()
        for f_path in self.source_eeg_files:
            self.source_files_listbox.addItem(Path(f_path).name)

    def _check_groups_for_removed_files(self, removed_paths: List[str]) -> None:
        """Remove deleted files from each group's file list."""

        updated_any = False
        affected = []
        for idx, group in enumerate(self.defined_groups):
            original = len(group.get("file_paths", []))
            group["file_paths"] = [
                fp for fp in group.get("file_paths", []) if fp not in removed_paths
            ]
            if len(group["file_paths"]) != original:
                group["config_saved"] = False
                updated_any = True
                affected.append(idx)

        if updated_any:
            self._update_groups_listbox()
            if self.selected_group_index in affected:
                self.selected_group_index = None
            self._update_start_processing_button_state()
