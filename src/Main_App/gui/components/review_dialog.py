"""Shared discard protection for explicit, unsaved QC review choices."""

from __future__ import annotations

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from Main_App.gui.components.surfaces import AppDialog


class ReviewDialog(AppDialog):
    """Keep a review open unless the user explicitly discards changed choices."""

    def _review_state(self) -> tuple:
        raise NotImplementedError

    def _remember_initial_review_state(self) -> None:
        self._initial_review_state = self._review_state()

    def _confirm_discard(self) -> bool:
        if self._review_state() == self._initial_review_state:
            return True
        message = QMessageBox(self)
        message.setWindowTitle("Discard review choices?")
        message.setIcon(QMessageBox.Icon.Question)
        message.setText("Your changes to this review have not been applied.")
        message.setInformativeText("Keep reviewing to preserve these choices, or discard them and close the review.")
        keep = message.addButton("Keep reviewing", QMessageBox.ButtonRole.RejectRole)
        discard = message.addButton("Discard choices", QMessageBox.ButtonRole.DestructiveRole)
        message.setDefaultButton(keep)
        message.setEscapeButton(keep)
        message.exec()
        return message.clickedButton() is discard

    def reject(self) -> None:
        if self._confirm_discard():
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._confirm_discard():
            # Calling QDialog.closeEvent would invoke reject and prompt twice.
            super().reject()
            event.accept()
        else:
            event.ignore()
