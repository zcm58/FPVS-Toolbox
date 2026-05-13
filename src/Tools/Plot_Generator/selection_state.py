"""Condition, ROI, and group-selection helpers for the Plot Generator GUI."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QListWidgetItem, QMessageBox

from Tools.Plot_Generator.manifest_utils import (
    extract_group_names,
    has_multi_groups,
    load_manifest_for_excel_root,
    normalize_participants_map,
)
from Tools.Stats.analysis.stats_analysis import ALL_ROIS_OPTION


ALL_CONDITIONS_OPTION = "All Conditions"


class PlotGeneratorSelectionMixin:
    """Selection and group-state helpers for PlotGeneratorWindow."""

    def _ensure_condition_a_valid_for_overlay(self) -> None:
        if (
            self.condition_combo.currentText() == ALL_CONDITIONS_OPTION
            and self.condition_combo.count() > 1
        ):
            self.condition_combo.setCurrentIndex(1)

    def _set_all_conditions_enabled(self, enabled: bool) -> None:
        model = self.condition_combo.model()
        if model and hasattr(model, "item") and model.rowCount() > 0:
            item = model.item(0)
            if item is not None:
                item.setEnabled(enabled)
        self._check_required()

    def _overlay_toggled(self, checked: bool) -> None:
        if checked:
            self._ensure_condition_a_valid_for_overlay()
            self._set_all_conditions_enabled(False)
            self._update_selector_columns(True)
            if self.group_box.isVisible():
                self.group_overlay_check.setChecked(False)
                self.group_overlay_check.setEnabled(False)
                self.group_list.setEnabled(False)
            self.title_edit.setEnabled(True)
            self.title_edit.clear()
            self.title_edit.setPlaceholderText(
                "Enter base chart name (e.g. Color Response vs Category Response)"
            )
        else:
            self._set_all_conditions_enabled(True)
            self._update_selector_columns(False)
            self._update_chart_title_state(self.condition_combo.currentText())
            self.scalp_title_b_edit.clear()
            if self.group_box.isVisible():
                self.group_overlay_check.setEnabled(True)
                self.group_list.setEnabled(self.group_overlay_check.isChecked())
        self._update_scalp_title_b_visibility()
        self._update_scalp_title_warnings()
        self._update_legend_group_visibility()

    def _on_group_overlay_toggled(self, checked: bool) -> None:
        self.group_list.setEnabled(checked)
        self._check_required()

    def _on_condition_a_changed(self, condition: str) -> None:
        self._update_chart_title_state(condition)
        if not (self._ui_initializing or self._populating_conditions):
            self.scalp_title_a_edit.clear()
        if hasattr(self, "legend_custom_check"):
            self._sync_legend_defaults_with_conditions()
        self._update_scalp_title_warnings()
        self._check_required()

    def _on_condition_b_changed(self, condition: str) -> None:
        _ = condition
        if not (self._ui_initializing or self._populating_conditions):
            self.scalp_title_b_edit.clear()
        if hasattr(self, "legend_custom_check"):
            self._sync_legend_defaults_with_conditions()
        self._update_scalp_title_warnings()
        self._check_required()

    def _update_chart_title_state(self, condition: str) -> None:
        """Enable/disable the title field based on the selected condition."""
        if self.overlay_check.isChecked():
            self.title_edit.setEnabled(True)
            self.title_edit.setPlaceholderText(
                "Enter base chart name (e.g. Color Response vs Category Response)"
            )
            return
        if condition == ALL_CONDITIONS_OPTION:
            self.title_edit.setEnabled(False)
            self.title_edit.setPlaceholderText("")
            self.title_edit.setText(
                "Chart Names Automatically Generated Based on Condition"
            )
        else:
            self.title_edit.setEnabled(True)
            self.title_edit.setPlaceholderText("e.g. Fruit vs Veg")
            if condition:
                self.title_edit.setText(condition)

    def _populate_conditions(self, folder: str) -> None:
        self._populating_conditions = True
        try:
            self._refresh_group_controls(folder)
            subfolders: list[str] = []
            try:
                subfolders = [
                    f.name
                    for f in Path(folder).iterdir()
                    if f.is_dir() and ".fif" not in f.name.lower()
                ]
            except OSError:
                subfolders = []

            with QSignalBlocker(self.condition_combo), QSignalBlocker(
                self.condition_b_combo
            ):
                self.condition_combo.clear()
                self.condition_b_combo.clear()
                if subfolders:
                    self.condition_combo.addItem(ALL_CONDITIONS_OPTION)
                    self.condition_combo.addItems(subfolders)
                    self.condition_b_combo.addItems(subfolders)
            if self.overlay_check.isChecked():
                self._ensure_condition_a_valid_for_overlay()
                self._set_all_conditions_enabled(False)
            else:
                self._set_all_conditions_enabled(True)
            self._update_chart_title_state(
                ALL_CONDITIONS_OPTION
                if subfolders
                else self.condition_combo.currentText()
            )
            self._update_scalp_title_warnings()
            self._check_required()
        finally:
            self._populating_conditions = False

    def _refresh_group_controls(self, folder: str) -> None:
        if not hasattr(self, "group_box"):
            return
        manifest = None
        if folder:
            try:
                manifest = load_manifest_for_excel_root(Path(folder))
            except Exception:  # pragma: no cover - log via UI only
                manifest = None
        self._subject_groups_map = normalize_participants_map(manifest)
        groups = extract_group_names(manifest)
        self._available_groups = groups
        self._has_multi_groups = has_multi_groups(manifest)
        self.group_box.setVisible(self._has_multi_groups)
        self.group_overlay_check.setChecked(False)
        self.group_overlay_check.setEnabled(
            self._has_multi_groups and not self.overlay_check.isChecked()
        )
        self.group_list.clear()
        if self._has_multi_groups:
            for name in groups:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.group_list.addItem(item)
            self.group_list.setEnabled(False)
        else:
            self.group_list.setEnabled(False)

    def _selected_groups(self) -> list[str]:
        selected: list[str] = []
        for idx in range(self.group_list.count()):
            item = self.group_list.item(idx)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected

    def _group_overlay_enabled(self) -> bool:
        return self.group_box.isVisible() and self.group_overlay_check.isChecked()

    def _group_worker_kwargs(
        self, overlay_enabled: bool, selected_groups: list[str]
    ) -> dict:
        if not overlay_enabled:
            return {
                "subject_groups": None,
                "selected_groups": None,
                "enable_group_overlay": False,
                "multi_group_mode": self._has_multi_groups,
            }
        return {
            "subject_groups": dict(self._subject_groups_map),
            "selected_groups": list(selected_groups),
            "enable_group_overlay": True,
            "multi_group_mode": self._has_multi_groups,
        }

    def _worker_roi_selection(self) -> tuple[dict[str, list[str]], str] | None:
        selected_roi = self.roi_combo.currentText().strip()
        if not selected_roi:
            QMessageBox.warning(
                self, "ROI", "Select a region of interest before plotting."
            )
            return None
        if selected_roi == ALL_ROIS_OPTION:
            return {k: list(v) for k, v in self.roi_map.items()}, selected_roi

        channels = self.roi_map.get(selected_roi)
        if not channels:
            QMessageBox.warning(
                self,
                "ROI",
                f"The selected ROI '{selected_roi}' has no electrode mapping.",
            )
            return None
        return {selected_roi: list(channels)}, selected_roi
