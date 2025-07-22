from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QHBoxLayout,
)


class SettingsPanel(QWidget):
    """Simple settings editor using PySide6 widgets."""

    settings_saved = Signal()
    settings_canceled = Signal()

    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.out_edit = QLineEdit()
        self.thr_edit = QLineEdit()
        form.addRow(QLabel("Output Folder"), self.out_edit)
        form.addRow(QLabel("Threshold"), self.thr_edit)

        btn_row = QHBoxLayout()
        self.ok_btn = QPushButton("OK")
        self.cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(self.ok_btn)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

        self.ok_btn.clicked.connect(self._on_ok)
        self.cancel_btn.clicked.connect(self._on_cancel)

    def _on_ok(self) -> None:
        values = {
            "output_folder": self.out_edit.text(),
            "threshold": self.thr_edit.text(),
        }
        if hasattr(self.controller, "save_settings"):
            self.controller.save_settings(values)
        self.settings_saved.emit()

    def _on_cancel(self) -> None:
        self.settings_canceled.emit()
