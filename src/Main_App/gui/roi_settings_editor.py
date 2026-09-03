from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import make_action_button, make_remove_button
from Main_App.gui.roi_electrode_selector import ROIElectrodeSelectorDialog
from Main_App.gui.roi_electrode_selector_state import split_electrode_text


ROIPresetProvider = Callable[[], Sequence[tuple[str, Sequence[str], bool]]]


class ROISettingsEditor(QWidget):
    """Widget for editing Regions of Interest mappings."""

    def __init__(
        self,
        parent: QWidget | None = None,
        pairs: list[tuple[str, list[str]]] | None = None,
        *,
        canonical_electrodes: Sequence[str] = (),
        preset_provider: ROIPresetProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self._canonical_electrodes = tuple(canonical_electrodes)
        self._preset_provider = preset_provider or (lambda: ())
        self.entries: list[dict[str, object]] = []
        layout = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll)

        self.container = QWidget()
        self.scroll.setWidget(self.container)
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(2)

        if pairs:
            for name, electrodes in pairs:
                self.add_entry(name, ",".join(electrodes))
        if not pairs:
            self.add_entry()

    def add_entry(self, name: str = "", electrodes: str = "") -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("ROI Name")
        name_edit.setText(name)
        elec_edit = QLineEdit()
        elec_edit.setPlaceholderText("Electrodes comma sep")
        elec_edit.setText(electrodes)
        select_btn = make_action_button("Select...", compact=True, parent=row)
        select_btn.setObjectName("settings_rois_select_electrodes")
        select_btn.setToolTip("Select electrodes on the visual BioSemi64 map")
        select_btn.setEnabled(bool(self._canonical_electrodes))
        select_btn.clicked.connect(
            lambda _checked=False, name=name_edit, electrode=elec_edit: self._open_selector(
                name,
                electrode,
            )
        )
        remove_btn = make_remove_button(
            parent=row,
            tooltip="Remove ROI",
            object_name="settings_rois_remove_roi",
        )
        remove_btn.clicked.connect(lambda _, r=row: self.remove_entry(r))

        row_layout.addWidget(name_edit)
        row_layout.addWidget(elec_edit)
        row_layout.addWidget(select_btn)
        row_layout.addWidget(remove_btn)

        self.container_layout.addWidget(row)
        self.entries.append(
            {
                "frame": row,
                "name": name_edit,
                "elec": elec_edit,
                "select": select_btn,
            }
        )
        name_edit.textChanged.connect(lambda _text: self._refresh_row_accessibility())
        self._refresh_row_accessibility()

    def _refresh_row_accessibility(self) -> None:
        for row_number, entry in enumerate(self.entries, start=1):
            name_edit = cast(QLineEdit, entry["name"])
            select_button = cast(QWidget, entry["select"])
            roi_name = name_edit.text().strip() or "unnamed ROI"
            select_button.setAccessibleName(
                f"Select electrodes visually for ROI row {row_number}: {roi_name}"
            )
            select_button.setAccessibleDescription(
                f"Open the nose-up BioSemi64 map for ROI row {row_number}, {roi_name}."
            )

    def _open_selector(self, name_edit: QLineEdit, electrode_edit: QLineEdit) -> None:
        dialog = ROIElectrodeSelectorDialog(
            canonical_electrodes=self._canonical_electrodes,
            current_name=name_edit.text(),
            current_electrodes=split_electrode_text(electrode_edit.text()),
            presets=self._preset_provider(),
            parent=self,
        )
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            if dialog.name_changed():
                name_edit.setText(dialog.selection_name())
            if dialog.electrodes_changed():
                electrode_edit.setText(",".join(dialog.selected_electrodes()))
        finally:
            dialog.deleteLater()

    def add_or_update_entry(self, name: str, electrodes: list[str]) -> str:
        clean_name = name.strip()
        electrode_text = ",".join(electrodes)
        for ent in self.entries:
            name_edit = cast(QLineEdit, ent["name"])
            elec_edit = cast(QLineEdit, ent["elec"])
            if name_edit.text().strip().casefold() == clean_name.casefold():
                elec_edit.setText(electrode_text)
                return "updated"

        for ent in self.entries:
            name_edit = cast(QLineEdit, ent["name"])
            elec_edit = cast(QLineEdit, ent["elec"])
            if not name_edit.text().strip() and not elec_edit.text().strip():
                name_edit.setText(clean_name)
                elec_edit.setText(electrode_text)
                return "added"

        self.add_entry(clean_name, electrode_text)
        return "added"

    def remove_entry(self, frame: QWidget) -> None:
        for i, ent in enumerate(self.entries):
            if ent["frame"] is frame:
                frame.deleteLater()
                self.entries.pop(i)
                self._refresh_row_accessibility()
                break
        if not self.entries:
            self.add_entry()

    def get_pairs(self) -> list[tuple[str, list[str]]]:
        pairs: list[tuple[str, list[str]]] = []
        for ent in self.entries:
            name = ent["name"].text().strip()
            electrodes = [e.strip().upper() for e in ent["elec"].text().split(",") if e.strip()]
            if name and electrodes:
                pairs.append((name, electrodes))
        return pairs

    def set_pairs(self, pairs: list[tuple[str, list[str]]]) -> None:
        for ent in list(self.entries):
            frame = ent["frame"]
            frame.deleteLater()
        self.entries.clear()
        for name, electrodes in pairs:
            self.add_entry(name, ",".join(electrodes))
        if not pairs:
            self.add_entry()
