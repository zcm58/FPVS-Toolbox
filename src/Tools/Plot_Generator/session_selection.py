"""Repeated-session selection helpers for the Plot Generator GUI."""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker

from Main_App.projects import DatasetIndexError, load_project_dataset_index
from Tools.Plot_Generator.session_controls import (
    RepeatedSessionControlError,
    RepeatedSessionControlState,
    SESSION_MODE_COMPARISON,
    SESSION_MODE_CONDITION,
    repeated_session_control_state,
)


class PlotGeneratorSessionSelectionMixin:
    """Populate and validate canonical recording-session controls."""

    def _refresh_session_controls(self, folder: str) -> None:
        """Populate canonical session selectors without path/name inference."""

        self._selection_dataset_index = None
        state = RepeatedSessionControlState(repeated=False)
        error = ""
        if folder:
            try:
                index = load_project_dataset_index(folder)
                self._selection_dataset_index = index
                state = repeated_session_control_state(index)
            except (DatasetIndexError, RepeatedSessionControlError) as exc:
                canonical_root = (
                    getattr(self, "_project_root", None) is not None
                    and self._folder_is_canonical_project_excel_root(folder)
                )
                if canonical_root:
                    error = str(exc)
        self._repeated_session_state = state
        self._session_control_error = error
        widget = getattr(self, "session_controls_widget", None)
        if widget is None:
            return
        prior_mode = self.session_dimension_combo.currentData()
        prior_single = self.single_session_combo.currentData()
        prior_reference = self.reference_session_combo.currentData()
        prior_comparison = self.comparison_session_combo.currentData()
        with QSignalBlocker(self.session_dimension_combo), QSignalBlocker(
            self.single_session_combo
        ), QSignalBlocker(self.reference_session_combo), QSignalBlocker(
            self.comparison_session_combo
        ):
            for combo in (
                self.single_session_combo,
                self.reference_session_combo,
                self.comparison_session_combo,
            ):
                combo.clear()
                for choice in state.sessions:
                    combo.addItem(choice.display_label, choice.session_id)
            mode = (
                str(prior_mode)
                if prior_mode in {SESSION_MODE_CONDITION, SESSION_MODE_COMPARISON}
                else state.default_mode
            )
            if state.repeated and not self._session_controls_initialized:
                mode = state.default_mode
            mode_index = self.session_dimension_combo.findData(mode)
            self.session_dimension_combo.setCurrentIndex(max(0, mode_index))
            for combo, prior, fallback in (
                (self.single_session_combo, prior_single, 0),
                (self.reference_session_combo, prior_reference, 0),
                (self.comparison_session_combo, prior_comparison, 1),
            ):
                index = combo.findData(prior)
                selected_index = (
                    index if index >= 0 else min(fallback, combo.count() - 1)
                )
                combo.setCurrentIndex(selected_index)
        widget.setVisible(state.repeated or bool(error))
        self._session_controls_initialized = (
            self._session_controls_initialized or state.repeated
        )
        self.session_caveat_label.setText(error or state.caveat)
        self._on_session_mode_changed()

    def _session_mode(self) -> str:
        value = self.session_dimension_combo.currentData()
        return str(value or SESSION_MODE_CONDITION)

    def _session_comparison_active(self) -> bool:
        return bool(
            self._repeated_session_state.repeated
            and self._session_mode() == SESSION_MODE_COMPARISON
        )

    def _on_session_mode_changed(self, _index: int | None = None) -> None:
        comparison = self._session_comparison_active()
        repeated = self._repeated_session_state.repeated
        self.single_session_label.setVisible(repeated and not comparison)
        self.single_session_combo.setVisible(repeated and not comparison)
        for widget in (
            self.reference_session_label,
            self.reference_session_combo,
            self.comparison_session_label,
            self.comparison_session_combo,
        ):
            widget.setVisible(repeated and comparison)
        if comparison:
            if self.overlay_check.isChecked():
                with QSignalBlocker(self.overlay_check):
                    self.overlay_check.setChecked(False)
            self._ensure_condition_a_valid_for_overlay()
            self._set_all_conditions_enabled(False)
            self._update_selector_columns(False)
        elif self._has_multi_groups or self.overlay_check.isChecked():
            self._set_all_conditions_enabled(False)
        else:
            self._set_all_conditions_enabled(True)
        self._update_multigroup_mode_controls()
        self._update_legend_group_visibility()
        self._check_required()

    def _session_worker_kwargs(self) -> dict[str, object]:
        state = self._repeated_session_state
        if not state.repeated:
            return {}
        mode = self._session_mode()
        session_ids = state.validate_selection(
            mode=mode,
            single_session_id=str(self.single_session_combo.currentData() or ""),
            reference_session_id=str(
                self.reference_session_combo.currentData() or ""
            ),
            comparison_session_id=str(
                self.comparison_session_combo.currentData() or ""
            ),
        )
        if mode == SESSION_MODE_CONDITION:
            return {"workbook_session_ids": session_ids}
        selected_labels = self._selected_groups()
        if selected_labels:
            group_ids = tuple(
                self._group_ids_by_label[label]
                for label in selected_labels
                if label in self._group_ids_by_label
            )
        else:
            indexed = getattr(self, "_selection_dataset_index", None)
            group_ids = (
                tuple(group.group_id for group in indexed.ordered_groups)
                if indexed is not None
                else ()
            )
        if not group_ids:
            raise RepeatedSessionControlError(
                "Select at least one canonical stable group for the session comparison."
            )
        return {
            "session_comparison_ids": session_ids,
            "session_group_ids": group_ids,
        }
