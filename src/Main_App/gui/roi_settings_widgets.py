"""Presentation-only controls for the embedded ROI settings editor."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import SubsectionHeaderLabel, make_action_button
from Main_App.gui.roi_visual_editor_state import (
    ROI_COLOR_PALETTE,
    roi_color_for_id,
)


def roi_color_icon(color: str) -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class ROIEditorSidePanel(QWidget):
    """Flat right-hand ROI list and active-ROI controls."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settings_rois_list_pane")
        self.setMinimumWidth(300)
        self.setMaximumWidth(390)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(6)

        list_header = QWidget(self)
        list_header_layout = QHBoxLayout(list_header)
        list_header_layout.setContentsMargins(0, 0, 0, 0)
        list_header_layout.setSpacing(8)
        list_header_layout.addWidget(SubsectionHeaderLabel("Regions of interest", list_header))
        list_header_layout.addStretch(1)
        self.add_button = make_action_button("+ New ROI", compact=True, parent=list_header)
        self.add_button.setObjectName("settings_rois_add_roi")
        list_header_layout.addWidget(self.add_button)
        layout.addWidget(list_header)

        self.roi_list = QListWidget(self)
        self.roi_list.setObjectName("settings_rois_list")
        self.roi_list.setAccessibleName("Defined regions of interest")
        self.roi_list.setAccessibleDescription(
            "Select one ROI to edit its name and electrode membership on the scalp map."
        )
        self.roi_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.roi_list.setIconSize(QSize(14, 14))
        self.roi_list.setAlternatingRowColors(True)
        self.roi_list.setMinimumHeight(110)
        layout.addWidget(self.roi_list, 1)

        list_actions = QHBoxLayout()
        list_actions.setContentsMargins(0, 0, 0, 0)
        list_actions.setSpacing(8)
        list_actions.addStretch(1)
        self.clear_button = make_action_button(
            "Clear Active ROI",
            variant="secondary",
            compact=True,
            parent=self,
        )
        self.clear_button.setObjectName("settings_rois_clear")
        list_actions.addWidget(self.clear_button)
        self.remove_button = make_action_button(
            "Remove ROI",
            variant="danger",
            compact=True,
            parent=self,
        )
        self.remove_button.setObjectName("settings_rois_remove_roi")
        list_actions.addWidget(self.remove_button)
        layout.addLayout(list_actions)

        name_label = QLabel("ROI name:", self)
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("settings_rois_name")
        self.name_edit.setPlaceholderText("ROI name")
        name_label.setBuddy(self.name_edit)
        layout.addWidget(name_label)
        layout.addWidget(self.name_edit)
        self.unmapped_pane = QWidget(self)
        self.unmapped_pane.setObjectName("settings_rois_unmapped_pane")
        unmapped_layout = QVBoxLayout(self.unmapped_pane)
        unmapped_layout.setContentsMargins(0, 4, 0, 0)
        unmapped_layout.setSpacing(4)
        unmapped_layout.addWidget(
            SubsectionHeaderLabel("Legacy / unmapped labels", self.unmapped_pane)
        )
        unmapped_help = QLabel(
            "These existing labels are preserved even though they are not positions on this map.",
            self.unmapped_pane,
        )
        unmapped_help.setWordWrap(True)
        unmapped_layout.addWidget(unmapped_help)
        self.unmapped_list = QListWidget(self.unmapped_pane)
        self.unmapped_list.setObjectName("settings_rois_unmapped")
        self.unmapped_list.setAccessibleName("Legacy or unmapped electrode labels")
        self.unmapped_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.unmapped_list.setMinimumHeight(44)
        self.unmapped_list.setMaximumHeight(88)
        unmapped_layout.addWidget(self.unmapped_list)
        self.remove_unmapped_button = make_action_button(
            "Remove Selected Label",
            variant="tertiary",
            compact=True,
            parent=self.unmapped_pane,
        )
        self.remove_unmapped_button.setObjectName("settings_rois_remove_unmapped")
        unmapped_layout.addWidget(
            self.remove_unmapped_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        layout.addWidget(self.unmapped_pane)


def configure_roi_tab_order(
    side_panel: ROIEditorSidePanel,
    map_buttons: Sequence[QWidget],
) -> None:
    """Put ROI editing controls before the map's 64-node keyboard sequence."""

    chain = (
        side_panel.add_button,
        side_panel.roi_list,
        side_panel.clear_button,
        side_panel.remove_button,
        side_panel.name_edit,
        side_panel.unmapped_list,
        side_panel.remove_unmapped_button,
        *map_buttons,
    )
    for current, following in zip(chain, chain[1:]):
        QWidget.setTabOrder(current, following)


__all__ = [
    "ROIEditorSidePanel",
    "ROI_COLOR_PALETTE",
    "configure_roi_tab_order",
    "roi_color_for_id",
    "roi_color_icon",
]
