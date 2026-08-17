"""On-demand generation-log dialog for SNR Plots."""

from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox, QTextEdit, QWidget

from Main_App.gui.components import AppDialog, SurfaceSize, fixed_width_font


class SNRGenerationLogDialog(AppDialog):
    """Show the complete SNR generation log without occupying page space."""

    def __init__(
        self,
        log_text: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "SNR Generation Log",
            parent,
            size=SurfaceSize(width=720, height=480, min_width=520, min_height=340),
        )
        self.setObjectName("snr_generation_log_dialog")
        self.setModal(True)

        self.viewer = QTextEdit(self)
        self.viewer.setObjectName("snr_generation_log_viewer")
        self.viewer.setAccessibleName("SNR plot generation log details")
        self.viewer.setReadOnly(True)
        self.viewer.setFont(fixed_width_font())
        self.viewer.setPlaceholderText("No generation details are available yet.")
        self.viewer.setPlainText(log_text)
        self.root_layout.addWidget(self.viewer, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.setObjectName("snr_generation_log_buttons")
        clear_button = buttons.addButton(
            "Clear Log",
            QDialogButtonBox.ButtonRole.ResetRole,
        )
        clear_button.setObjectName("snr_generation_log_clear")
        clear_button.setAccessibleName("Clear SNR plot generation log")
        clear_button.clicked.connect(self.viewer.clear)
        buttons.rejected.connect(self.reject)
        self.root_layout.addWidget(buttons)


__all__ = ["SNRGenerationLogDialog"]
