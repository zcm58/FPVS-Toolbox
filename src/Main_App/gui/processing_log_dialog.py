"""On-demand log viewer for the Main App processing workflow."""

from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox, QTextEdit, QWidget

from Main_App.gui.components import AppDialog, SurfaceSize, fixed_width_font


class ProcessingLogDialog(AppDialog):
    """Keep processing diagnostics available without occupying page space."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Processing Log",
            parent,
            size=SurfaceSize(width=760, height=500, min_width=560, min_height=360),
        )
        self.setObjectName("processing_log_dialog")
        self.setModal(True)

        self.viewer = QTextEdit(self)
        self.viewer.setObjectName("log_surface")
        self.viewer.setProperty("logSurface", True)
        self.viewer.setAccessibleName("Processing log details")
        self.viewer.setReadOnly(True)
        self.viewer.setFont(fixed_width_font())
        self.viewer.setPlaceholderText("No processing details are available yet.")
        self.root_layout.addWidget(self.viewer, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.setObjectName("processing_log_buttons")
        clear_button = buttons.addButton(
            "Clear Log",
            QDialogButtonBox.ButtonRole.ResetRole,
        )
        clear_button.setObjectName("processing_log_clear")
        clear_button.setAccessibleName("Clear processing log")
        clear_button.clicked.connect(self.viewer.clear)
        buttons.rejected.connect(self.reject)
        self.root_layout.addWidget(buttons)


__all__ = ["ProcessingLogDialog"]
