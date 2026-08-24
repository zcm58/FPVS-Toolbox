"""On-demand generation log for the Scalp Maps tool."""

from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox, QPlainTextEdit, QWidget

from Main_App.gui.components import AppDialog, SurfaceSize, fixed_width_font


class ScalpMapsGenerationLogDialog(AppDialog):
    """Keep the current Scalp Maps run history available outside the page layout."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            "Scalp Maps Generation Log",
            parent,
            size=SurfaceSize(width=760, height=500, min_width=560, min_height=360),
        )
        self.setObjectName("publication_maps_generation_log_dialog")
        self.setModal(True)

        self.viewer = QPlainTextEdit(self)
        self.viewer.setObjectName("publication_maps_generation_log_viewer")
        self.viewer.setProperty("logSurface", True)
        self.viewer.setAccessibleName("Scalp Maps generation log details")
        self.viewer.setReadOnly(True)
        self.viewer.setFont(fixed_width_font())
        self.viewer.setPlaceholderText("No generation details are available yet.")
        self.root_layout.addWidget(self.viewer, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.setObjectName("publication_maps_generation_log_buttons")
        buttons.rejected.connect(self.reject)
        self.root_layout.addWidget(buttons)


__all__ = ["ScalpMapsGenerationLogDialog"]
