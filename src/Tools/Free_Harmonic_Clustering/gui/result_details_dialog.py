"""Read-only interpretation of one completed repeated-session comparison."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QPlainTextEdit

from Main_App.gui.components import (
    AppDialog,
    SubsectionHeaderLabel,
    SurfaceSize,
    make_action_button,
    make_action_row,
)

if TYPE_CHECKING:
    from ..reporting import RepeatedSessionReportRow


class ResultDetailsDialog(AppDialog):
    """Show immutable report text and optionally navigate to its existing maps."""

    maps_requested = Signal(int)

    def __init__(
        self,
        row: RepeatedSessionReportRow,
        parent=None,
        *,
        maps_available: bool = False,
    ) -> None:
        super().__init__(
            "Exploratory Finding Details" if row.is_exploratory else "Comparison Details",
            parent,
            size=SurfaceSize(1000, 650, min_width=720, min_height=420),
        )
        self.setObjectName("free_harmonic_result_details_dialog")
        self._run_index = row.run_index
        self.identity = SubsectionHeaderLabel(
            f"{row.condition} | {row.family_label}", self,
        )
        self.identity.setTextFormat(Qt.PlainText)
        self.identity.setWordWrap(True)
        self.root_layout.addWidget(self.identity)
        self.details = QPlainTextEdit(self)
        self.details.setObjectName("free_harmonic_result_details_text")
        self.details.setReadOnly(True)
        self.details.setPlainText(row.detail_text)
        self.root_layout.addWidget(self.details, 1)
        self.maps_button = make_action_button(
            "View cluster maps", variant="secondary", parent=self,
        )
        self.maps_button.setObjectName("free_harmonic_details_maps_button")
        self.maps_button.setEnabled(maps_available)
        self.maps_button.setToolTip(
            "Open this comparison's existing descriptive maps and within-run cluster members."
            if maps_available
            else "Maps are unavailable for this completed batch."
        )
        self.close_button = make_action_button("Close", variant="primary", parent=self)
        self.close_button.setObjectName("free_harmonic_details_close_button")
        self.root_layout.addWidget(
            make_action_row((self.maps_button, self.close_button), parent=self),
        )
        self.maps_button.clicked.connect(self._show_maps)
        self.close_button.clicked.connect(self.reject)

    @Slot()
    def _show_maps(self) -> None:
        self.accept()
        self.maps_requested.emit(self._run_index)


__all__ = ["ResultDetailsDialog"]
