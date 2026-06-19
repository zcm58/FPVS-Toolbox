"""Condition, ROI, and group-selection helpers for the Plot Generator GUI."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QWidget,
)

from Tools.Plot_Generator.manifest_utils import (
    extract_group_names,
    has_multi_groups,
    load_manifest_for_excel_root,
    normalize_participants_map,
)
from Tools.Stats.analysis.stats_analysis import ALL_ROIS_OPTION


ALL_CONDITIONS_OPTION = "All Conditions"
_UNSELECTED_GROUP_COLOR = "#d9dee8"
_AUTO_GROUP_COLOR = "#9aa4b2"


def _group_color_assignment(
    group_name: str,
    selected_groups: list[str],
    color_a: str,
    color_b: str,
) -> tuple[str, bool, str]:
    """Return ``(color, editable, role)`` for a group row color swatch."""

    if group_name not in selected_groups:
        return _UNSELECTED_GROUP_COLOR, False, "Not selected"
    position = selected_groups.index(group_name)
    if position == 0:
        return color_a, True, "First selected group"
    if position == 1:
        return color_b, True, "Second selected group"
    return _AUTO_GROUP_COLOR, False, "Automatic palette"


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
            if self.group_box.isVisible():
                self.group_overlay_check.setEnabled(True)
                self.group_list.setEnabled(self.group_overlay_check.isChecked())
        self._update_legend_group_visibility()

    def _on_group_overlay_toggled(self, checked: bool) -> None:
        self.group_list.setEnabled(checked)
        self._update_group_color_widgets()
        if checked:
            self._force_legend_defaults()
        else:
            self._sync_legend_defaults_with_conditions()
        self._update_legend_group_visibility()
        self._check_required()

    def _on_group_selection_changed(self, _item: QListWidgetItem) -> None:
        if self._group_overlay_enabled():
            self._update_group_color_widgets()
            self._force_legend_defaults()
            self._update_legend_group_visibility()
        self._check_required()

    def _on_group_check_toggled(self) -> None:
        if self._group_overlay_enabled():
            self._update_group_color_widgets()
            self._force_legend_defaults()
            self._update_legend_group_visibility()
        self._check_required()

    def _choose_group_color(self, group_name: str) -> None:
        selected_groups = self._selected_groups()
        if group_name not in selected_groups:
            return
        position = selected_groups.index(group_name)
        if position == 0:
            self._choose_color("a")
        elif position == 1:
            self._choose_color("b")

    def _on_condition_a_changed(self, condition: str) -> None:
        self._update_chart_title_state(condition)
        if hasattr(self, "legend_custom_check"):
            self._sync_legend_defaults_with_conditions()
        self._check_required()

    def _on_condition_b_changed(self, condition: str) -> None:
        _ = condition
        if hasattr(self, "legend_custom_check"):
            self._sync_legend_defaults_with_conditions()
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
        self._has_multi_groups = has_multi_groups(
            manifest
        ) and self._folder_is_canonical_project_excel_root(folder)
        self.group_box.setVisible(self._has_multi_groups)
        self._update_multigroup_mode_controls()
        self.group_overlay_check.setChecked(False)
        self.group_overlay_check.setEnabled(
            self._has_multi_groups and not self.overlay_check.isChecked()
        )
        self.group_list.clear()
        self._group_checkboxes = {}
        self._group_color_buttons = {}
        if self._has_multi_groups:
            for name in groups:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                item.setCheckState(Qt.Checked)
                self.group_list.addItem(item)
                row = self._make_group_row_widget(name)
                item.setSizeHint(row.sizeHint())
                self.group_list.setItemWidget(item, row)
            self.group_list.setEnabled(False)
            self._update_group_color_widgets()
        else:
            self.group_list.setEnabled(False)

    def _make_group_row_widget(self, group_name: str):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        checkbox = QCheckBox(group_name)
        checkbox.setChecked(True)
        checkbox.toggled.connect(self._on_group_check_toggled)
        color_btn = QPushButton()
        color_btn.setFixedSize(20, 20)
        color_btn.clicked.connect(lambda: self._choose_group_color(group_name))
        layout.addWidget(checkbox, 1)
        layout.addWidget(color_btn)
        self._group_checkboxes[group_name] = checkbox
        self._group_color_buttons[group_name] = color_btn
        return row

    def _update_group_color_widgets(self) -> None:
        buttons = getattr(self, "_group_color_buttons", {})
        if not buttons:
            return
        selected_groups = self._selected_groups()
        overlay_enabled = self._group_overlay_enabled()
        for group_name, button in buttons.items():
            color, editable, role = _group_color_assignment(
                group_name,
                selected_groups,
                self.stem_color,
                self.stem_color_b,
            )
            button.setStyleSheet(f"background-color: {color};")
            button.setEnabled(overlay_enabled and editable)
            button.setToolTip(f"{role}: {group_name}")

    def _update_multigroup_mode_controls(self) -> None:
        multi_group = bool(self._has_multi_groups)
        if hasattr(self, "overlay_row"):
            self.overlay_row.setVisible(not multi_group)
        if multi_group:
            if self.overlay_check.isChecked():
                self.overlay_check.setChecked(False)
            self._update_selector_columns(False)

    def _folder_is_canonical_project_excel_root(self, folder: str) -> bool:
        canonical = getattr(self, "_canonical_project_excel_root", None)
        if canonical is None:
            return True
        try:
            return Path(folder).resolve() == Path(canonical).resolve()
        except (OSError, RuntimeError, ValueError):
            return False

    def _selected_groups(self) -> list[str]:
        checkboxes = getattr(self, "_group_checkboxes", None)
        if isinstance(checkboxes, dict) and checkboxes:
            return [
                group_name
                for idx, group_name in enumerate(self._available_groups)
                if group_name in checkboxes
                and checkboxes[group_name].isChecked()
                and self.group_list.item(idx).checkState() != Qt.Unchecked
            ]
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
                "subject_groups": dict(self._subject_groups_map)
                if self._has_multi_groups
                else None,
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
