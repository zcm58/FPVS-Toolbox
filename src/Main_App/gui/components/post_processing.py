"""Reusable modal for downstream tools that require refreshed post-processing."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QTextBrowser, QWidget

from Main_App.gui.widgets.buttons import make_action_button
from Main_App.gui.widgets.status import StatusBanner

from .actions import make_action_row
from .surfaces import AppDialog, SurfaceSize


class PostProcessingRequiredDialog(AppDialog):
    """Explain a stale downstream state and offer the shared rebuild action."""

    def __init__(
        self,
        *,
        tool_name: str,
        reason: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Post-processing Required",
            parent,
            size=SurfaceSize(width=590, height=390, min_width=500, min_height=330),
        )
        self.setObjectName("post_processing_required_dialog")

        banner = StatusBanner(
            f"{tool_name} needs a complete, current set of project analysis outputs.",
            self,
            variant="warning",
        )
        banner.setObjectName("post_processing_required_banner")
        self.root_layout.addWidget(banner)

        explanation = QLabel(
            "Review the reason below before retrying. Post-processing reuses "
            "existing processed EEG data. If a condition is missing, resolve its "
            "triggers or record an intentional condition exclusion and rerun "
            "processing first.",
            self,
        )
        explanation.setObjectName("post_processing_required_explanation")
        explanation.setWordWrap(True)
        self.root_layout.addWidget(explanation)

        details = QTextBrowser(self)
        details.setObjectName("post_processing_required_details")
        details.setPlainText(reason.strip() or "Project analysis outputs are incomplete or need refreshing.")
        details.setMaximumHeight(105)
        self.root_layout.addWidget(details)

        self.run_button = make_action_button(
            "Run Post-processing",
            variant="primary",
            parent=self,
        )
        self.run_button.setObjectName("post_processing_required_run")
        self.cancel_button = make_action_button("Not Now", parent=self)
        self.cancel_button.setObjectName("post_processing_required_cancel")
        self.run_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.run_button.setDefault(True)
        self.root_layout.addWidget(
            make_action_row([self.cancel_button, self.run_button], parent=self)
        )


def show_post_processing_required(
    parent: QWidget | None,
    *,
    tool_name: str,
    reason: str,
) -> bool:
    """Show the shared modal and return whether the rebuild was requested."""

    dialog = PostProcessingRequiredDialog(
        tool_name=tool_name,
        reason=reason,
        parent=parent,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


__all__ = ["PostProcessingRequiredDialog", "show_post_processing_required"]
