from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QScrollArea,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
)


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
        remove_btn = QPushButton("\u2715")
        remove_btn.setFixedWidth(24)
        remove_btn.clicked.connect(lambda _, r=row: self.remove_entry(r))

        row_layout.addWidget(name_edit)
        row_layout.addWidget(elec_edit)
        row_layout.addWidget(remove_btn)

        self.container_layout.addWidget(row)
        self.entries.append({"frame": row, "name": name_edit, "elec": elec_edit})

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
