"""Draft tracking and non-modal validation for the Settings editor."""

from __future__ import annotations

import copy

from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit

from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings

PREPROCESSING_FIELDS = (
    "low_pass", "high_pass", "downsample", "rejection_z", "ref_chan1",
    "ref_chan2", "max_chan_idx_keep", "max_bad_chans", "max_parallel_workers_override",
)
_MANUAL_DRAFTS = (
    "_manual_removed_electrodes_by_pid", "_manual_removed_electrodes_by_recording",
    "_manual_excluded_participants", "_manual_excluded_recordings",
    "_manual_excluded_participant_conditions", "_manual_excluded_recording_conditions",
)


def preprocessing_error_field(message: str) -> str | None:
    text = message.casefold()
    for alias, field in (("low-pass", "low_pass"), ("high-pass", "high_pass")):
        if alias in text:
            return field
    return next((field for field in PREPROCESSING_FIELDS if field in text), None)


def mark_invalid(field: QLineEdit, message: str) -> None:
    field.setProperty("invalid", bool(message))
    field.setAccessibleDescription(message)
    field.style().unpolish(field)
    field.style().polish(field)


def refresh_preprocessing_feedback(panel) -> None:
    """Show validation without stealing focus, navigating, or touching disk."""
    for edit, label in zip(panel.preproc_edits, panel.preproc_error_labels):
        mark_invalid(edit, "")
        label.hide()
    values = {
        key: edit.text() for key, edit in zip(PREPROCESSING_FIELDS, panel.preproc_edits)
    }
    try:
        normalize_preprocessing_settings(values)
    except ValueError as exc:
        key = preprocessing_error_field(str(exc))
        if key is not None:
            index = PREPROCESSING_FIELDS.index(key)
            mark_invalid(panel.preproc_edits[index], str(exc))
            panel.preproc_error_labels[index].setText(str(exc))
            panel.preproc_error_labels[index].show()


class SettingsDraftTracker:
    """Compare editable values, excluding selection-only controls in the ROI editor."""

    def __init__(self, panel) -> None:
        self.panel = panel
        self.controls = []
        for kind in (QLineEdit, QComboBox, QCheckBox):
            for control in panel.findChildren(kind):
                if panel.roi_editor.isAncestorOf(control):
                    continue
                if isinstance(control, QLineEdit) and control.isReadOnly():
                    continue
                self.controls.append(control)
        self.baseline = self.snapshot()
        for control in self.controls:
            signal = (
                control.textChanged if isinstance(control, QLineEdit)
                else control.currentIndexChanged if isinstance(control, QComboBox)
                else control.toggled
            )
            signal.connect(lambda *_args, field=control: self.changed(field))
        panel.roi_editor.draft_changed.connect(self.changed)

    def snapshot(self):
        values = []
        for control in self.controls:
            if isinstance(control, QLineEdit):
                values.append(control.text())
            elif isinstance(control, QComboBox):
                values.append((control.currentData(), control.currentText()))
            else:
                values.append(control.isChecked())
        # Include incomplete ROI drafts too; get_pairs deliberately omits them.
        rois = [
            (entry.name, entry.selection.selected_electrodes())
            for entry in self.panel.roi_editor.entries
        ]
        manual = [getattr(self.panel, name) for name in _MANUAL_DRAFTS]
        return copy.deepcopy((values, rois, manual))

    def is_dirty(self) -> bool:
        return self.snapshot() != self.baseline

    def mark_saved(self) -> None:
        self.baseline = self.snapshot()
        self.changed()

    def changed(self, field=None) -> None:
        if isinstance(field, QLineEdit) and field not in self.panel.preproc_edits:
            mark_invalid(field, "")
        self.panel.setWindowModified(self.is_dirty())
        banner = getattr(self.panel, "settings_validation_status", None)
        if banner is not None:
            banner.hide()
        refresh = getattr(self.panel.host, "_refresh_project_dirty_indicator", None)
        if callable(refresh):
            refresh()
