"""Condition and path-selection helpers for the Ratio Calculator GUI."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QFileDialog, QComboBox, QLineEdit

from Main_App.Shared.file_filters import is_excel_workbook_file

CUSTOM_CONDITION_OPTION = "Custom path"


class RatioConditionSelectionMixin:
    """GUI-only condition and folder selection behavior."""

    def _resolve_project_root(self, provided_root: str | None) -> Optional[Path]:
        if provided_root:
            root = Path(provided_root)
            if root.exists():
                return root
        env_root = os.environ.get("FPVS_PROJECT_ROOT")
        if env_root:
            root = Path(env_root)
            if root.exists():
                return root
        proj = getattr(self.parent(), "currentProject", None)
        if proj and hasattr(proj, "project_root"):
            root = Path(proj.project_root)
            if root.exists():
                return root
        return None

    def _excel_root(self) -> Optional[Path]:
        if not self._project_root:
            return None
        return self._project_root / "1 - Excel Data Files"

    def _set_default_output(self) -> None:
        if self.output_edit.text().strip():
            return
        if self._project_root:
            default_out = self._project_root / "5 - Ratio Summaries"
            self._set_path_lineedit(self.output_edit, str(default_out))

    @staticmethod
    def _set_path_lineedit(edit: QLineEdit, path: str) -> None:
        edit.setText(path)
        edit.setCursorPosition(0)
        edit.deselect()
        edit.setToolTip(path)

    def _scan_condition_folders(self, excel_root: Path) -> list[Path]:
        if not excel_root.exists():
            return []
        folders: list[Path] = []
        for child in sorted(excel_root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            if any(
                is_excel_workbook_file(fp)
                for fp in child.glob("*.xlsx")
            ):
                folders.append(child)
        return folders

    def _refresh_conditions(self) -> None:
        excel_root = self._excel_root()
        condition_paths: dict[str, Path] = {}
        if excel_root:
            for folder in self._scan_condition_folders(excel_root):
                condition_paths[folder.name] = folder
        self._condition_paths = condition_paths

        self._populate_condition_combo(self.condition_a_combo, self.input_a_edit)
        self._populate_condition_combo(self.condition_b_combo, self.input_b_edit)
        if (
            len(self._condition_paths) > 1
            and self.condition_a_combo.currentText() == self.condition_b_combo.currentText()
        ):
            second = list(self._condition_paths.keys())[1]
            with QSignalBlocker(self.condition_b_combo):
                self.condition_b_combo.setCurrentText(second)
            self._apply_condition_selection(second, is_a=False)
        self._maybe_autoload_participants(force=True)
        self._refresh_rois()
        self._update_run_state()

    def _populate_condition_combo(self, combo: QComboBox, edit: QLineEdit) -> None:
        current_path = edit.text().strip()
        current_match = None
        if current_path:
            for name, folder in self._condition_paths.items():
                if folder.resolve() == Path(current_path).resolve():
                    current_match = name
                    break

        with QSignalBlocker(combo):
            combo.clear()
            combo.addItems(self._condition_paths.keys())
            combo.addItem(CUSTOM_CONDITION_OPTION)
            if current_match:
                combo.setCurrentText(current_match)
            elif self._condition_paths:
                combo.setCurrentText(next(iter(self._condition_paths.keys())))
            else:
                combo.setCurrentText(CUSTOM_CONDITION_OPTION)

        selected = combo.currentText()
        if selected in self._condition_paths:
            self._set_path_lineedit(edit, str(self._condition_paths[selected]))
            self._set_condition_labels_from_folder(selected, combo is self.condition_a_combo)

    def _set_condition_labels_from_folder(self, folder_name: str, is_a: bool) -> None:
        if is_a:
            if not self._label_a_dirty:
                with QSignalBlocker(self.label_a_edit):
                    self.label_a_edit.setText(folder_name)
        else:
            if not self._label_b_dirty:
                with QSignalBlocker(self.label_b_edit):
                    self.label_b_edit.setText(folder_name)
        self._update_run_label_default()

    def _on_condition_a_selected(self, condition: str) -> None:
        self._apply_condition_selection(condition, is_a=True)

    def _on_condition_b_selected(self, condition: str) -> None:
        self._apply_condition_selection(condition, is_a=False)

    def _apply_condition_selection(self, condition: str, is_a: bool) -> None:
        if condition == CUSTOM_CONDITION_OPTION:
            self._maybe_autoload_participants(force=True)
            self._update_run_state()
            return

        target_edit = self.input_a_edit if is_a else self.input_b_edit
        selected_path = self._condition_paths.get(condition)
        if selected_path:
            self._set_path_lineedit(target_edit, str(selected_path))
            self._set_condition_labels_from_folder(condition, is_a)
            self._last_dir = selected_path
        self._maybe_autoload_participants(force=True)
        self._update_run_state()

    def _swap_conditions(self) -> None:
        a_path = self.input_a_edit.text()
        b_path = self.input_b_edit.text()
        a_label = self.label_a_edit.text()
        b_label = self.label_b_edit.text()
        a_combo = self.condition_a_combo.currentText()
        b_combo = self.condition_b_combo.currentText()
        a_dirty = self._label_a_dirty
        b_dirty = self._label_b_dirty

        with QSignalBlocker(self.condition_a_combo), QSignalBlocker(self.condition_b_combo):
            self.condition_a_combo.setCurrentText(b_combo)
            self.condition_b_combo.setCurrentText(a_combo)

        self._set_path_lineedit(self.input_a_edit, b_path)
        self._set_path_lineedit(self.input_b_edit, a_path)
        with QSignalBlocker(self.label_a_edit), QSignalBlocker(self.label_b_edit):
            self.label_a_edit.setText(b_label)
            self.label_b_edit.setText(a_label)

        self._label_a_dirty = b_dirty
        self._label_b_dirty = a_dirty
        self._update_run_label_default()
        self._maybe_autoload_participants(force=True)
        self._update_run_state()

    def _browse_folder(self, target_edit: QLineEdit, is_output: bool, condition_key: str | None = None) -> None:
        start_dir = self._initial_dialog_dir(is_output)
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", str(start_dir))
        if folder:
            self._set_path_lineedit(target_edit, folder)
            self._last_dir = Path(folder)
            if condition_key:
                combo = self.condition_a_combo if condition_key == "a" else self.condition_b_combo
                if combo.findText(CUSTOM_CONDITION_OPTION) == -1:
                    combo.addItem(CUSTOM_CONDITION_OPTION)
                with QSignalBlocker(combo):
                    combo.setCurrentText(CUSTOM_CONDITION_OPTION)
                self._set_condition_labels_from_folder(Path(folder).name, condition_key == "a")
            self._maybe_autoload_participants(force=True)
            self._update_run_state()

    def _initial_dialog_dir(self, is_output: bool) -> Path:
        if self._project_root:
            if is_output:
                preferred = self._project_root / "5 - Ratio Summaries"
            else:
                preferred = self._project_root / "1 - Excel Data Files"
            if preferred.exists():
                return preferred
            return self._project_root
        if self._last_dir:
            return self._last_dir
        return Path.cwd()
