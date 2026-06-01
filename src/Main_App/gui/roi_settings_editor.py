from __future__ import annotations

from typing import cast

from PySide6.QtWidgets import (
    QWidget,
    QScrollArea,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
)

from Main_App.gui.components import make_remove_button


class ROISettingsEditor(QWidget):
    """Widget for editing Regions of Interest mappings."""

    def __init__(self, parent: QWidget | None = None, pairs: list[tuple[str, list[str]]] | None = None) -> None:
        super().__init__(parent)
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
        remove_btn = make_remove_button(
            parent=row,
            tooltip="Remove ROI",
            object_name="settings_rois_remove_roi",
        )
        remove_btn.clicked.connect(lambda _, r=row: self.remove_entry(r))

        row_layout.addWidget(name_edit)
        row_layout.addWidget(elec_edit)
        row_layout.addWidget(remove_btn)

        self.container_layout.addWidget(row)
        self.entries.append({"frame": row, "name": name_edit, "elec": elec_edit})

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
