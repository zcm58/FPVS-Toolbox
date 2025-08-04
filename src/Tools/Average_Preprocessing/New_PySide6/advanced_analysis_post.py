"""Post-processing utilities for the PySide6 averaging window."""

from __future__ import annotations

from pathlib import Path
import json
import re
import traceback
from typing import Any, Dict

from PySide6.QtWidgets import QFileDialog, QMessageBox
import logging

logger = logging.getLogger(__name__)


class AdvancedAnalysisPostMixin:
    """Support saving/loading group definitions and PID extraction."""

    defined_groups: list[dict]
    source_eeg_files: list[str]

    def _extract_pid_for_group(self, group_data: Dict[str, Any]) -> str:
        """Return a participant identifier extracted from a group's first file."""

        file_paths = group_data.get("file_paths", [])
        if not file_paths:
            return "UnknownPID"
        base_name = Path(file_paths[0]).stem
        pid_regex_primary = r"\b(P\d+|S\d+|Sub\d+)\b"
        match = re.search(pid_regex_primary, base_name, re.IGNORECASE)
        if match:
            return match.group(1).upper()
        if "_" in base_name:
            for part in base_name.split("_"):
                if re.fullmatch(r"(P\d+|S\d+|Sub\d+)", part, re.IGNORECASE):
                    return part.upper()
        cleaned = re.sub(
            r"(_unamb|_ambig|_mid|_run\d*|_sess\d*|_task\w*|_eeg|_raw|_preproc|_ica).*",
            "",
            base_name,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"[^A-Za-z0-9]", "", cleaned)
        return cleaned or base_name

    def save_groups_to_file(self) -> None:
        """Save ``self.defined_groups`` to a JSON file chosen by the user."""

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Group Configuration", "", "JSON Files (*.json)"
        )
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.defined_groups, f, indent=2)
            self.log(f"Saved group configuration to {file_path}.")
        except Exception as e:  # pragma: no cover - show dialog to user
            QMessageBox.critical(
                self, "Error", f"Failed to save configuration:\n{e}"
            )
            logger.error("Failed to save config: %s", traceback.format_exc())

    def load_groups_from_file(self) -> None:
        """Load groups from a JSON file and refresh the UI."""

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Group Configuration", "", "JSON Files (*.json)"
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list) or not all(isinstance(g, dict) for g in data):
                raise ValueError("Invalid configuration structure")
            required = {
                "name",
                "file_paths",
                "condition_mappings",
                "averaging_method",
                "config_saved",
            }
            for group in data:
                if not required.issubset(group.keys()):
                    raise ValueError("Configuration missing required keys")
            self.defined_groups = data
            all_paths = {fp for g in self.defined_groups for fp in g.get("file_paths", [])}
            self.source_eeg_files = sorted(all_paths)
            self.selected_group_index = None
            self._update_source_files_listbox()
            self._update_groups_listbox()
            self._clear_group_config_display()
            self._update_start_processing_button_state()
            self.log(f"Loaded {len(self.defined_groups)} group(s) from {file_path}.")
        except Exception as e:  # pragma: no cover - show dialog to user
            QMessageBox.critical(
                self, "Error", f"Failed to load configuration:\n{e}"
            )
            logger.error("Failed to load config: %s", traceback.format_exc())
