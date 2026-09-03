"""Presentation-only controls for the embedded ROI settings editor."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QSignalBlocker, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import SubsectionHeaderLabel, make_action_button
from Main_App.gui.roi_visual_editor_state import (
    ROI_COLOR_PALETTE,
    roi_color_for_id,
)


ROIPreset = tuple[str, Sequence[str], bool]
ROIPresetProvider = Callable[[str], Sequence[ROIPreset]]

def roi_color_icon(color: str) -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def map_selection_summary(labels: Sequence[str]) -> str:
    """Return a bounded textual companion to the visual map selection."""

    if not labels:
        return "No mapped electrodes selected for this ROI."
    shown = ", ".join(labels[:12])
    remaining = len(labels) - 12
    suffix = f"; +{remaining} more" if remaining > 0 else ""
    return f"Selected map positions ({len(labels)}): {shown}{suffix}"


class ROIEditorToolbar(QWidget):
    """Compact montage and preset controls for the visual ROI surface."""

    def __init__(
        self,
        montage_options: Sequence[tuple[str, str]],
        current_montage: str,
        preset_provider: ROIPresetProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._preset_provider = preset_provider
        self.setObjectName("settings_rois_toolbar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        montage_label = QLabel("Montage:", self)
        self.montage_combo = QComboBox(self)
        self.montage_combo.setObjectName("settings_rois_montage_combo")
        self.montage_combo.setAccessibleName("ROI electrode montage")
        montage_label.setBuddy(self.montage_combo)
        for montage_key, display_label in montage_options:
            self.montage_combo.addItem(display_label, montage_key)
        montage_index = self.montage_combo.findData(current_montage)
        if montage_index >= 0:
            self.montage_combo.setCurrentIndex(montage_index)

        preset_label = QLabel("Preset:", self)
        self.preset_combo = QComboBox(self)
        self.preset_combo.setObjectName("settings_rois_preset_combo")
        self.preset_combo.setAccessibleName("ROI preset")
        self.preset_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        preset_label.setBuddy(self.preset_combo)
        self.add_preset_button = make_action_button(
            "Add / Reset Preset ROI",
            compact=True,
            parent=self,
        )
        self.add_preset_button.setObjectName("settings_rois_add_preset")
        self.add_preset_button.setAccessibleName(
            "Add a preset ROI or reset its first matching definition"
        )
        self.save_presets_button = make_action_button(
            "Save Custom Presets",
            variant="tertiary",
            compact=True,
            parent=self,
        )
        self.save_presets_button.setObjectName("settings_rois_save_custom_presets")

        layout.addWidget(montage_label)
        layout.addWidget(self.montage_combo)
        layout.addSpacing(8)
        layout.addWidget(preset_label)
        layout.addWidget(self.preset_combo, 1)
        layout.addWidget(self.add_preset_button)
        layout.addStretch(1)
        layout.addWidget(self.save_presets_button)

    def current_montage(self) -> str:
        data = self.montage_combo.currentData()
        return str(data) if data is not None else ""

    def selected_preset(self) -> tuple[str, list[str], bool] | None:
        preset = self.preset_combo.currentData()
        if not isinstance(preset, tuple) or len(preset) != 3:
            return None
        name, electrodes, is_default = preset
        if not isinstance(name, str) or not isinstance(is_default, bool):
            return None
        if not isinstance(electrodes, (list, tuple)):
            return None
        return name, [str(electrode) for electrode in electrodes], is_default

    def refresh_presets(self) -> None:
        selected = self.selected_preset()
        selected_key = selected[0].casefold() if selected else ""
        presets = tuple(self._preset_provider(self.current_montage()))
        with QSignalBlocker(self.preset_combo):
            self.preset_combo.clear()
            for name, electrodes, is_default in presets:
                source = "Default" if is_default else "Custom"
                self.preset_combo.addItem(
                    f"{name} ({source})",
                    (str(name), [str(item) for item in electrodes], bool(is_default)),
                )
            if selected_key:
                for index in range(self.preset_combo.count()):
                    data = self.preset_combo.itemData(index)
                    if isinstance(data, tuple) and str(data[0]).casefold() == selected_key:
                        self.preset_combo.setCurrentIndex(index)
                        break
        self.add_preset_button.setEnabled(self.selected_preset() is not None)


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
        self.remove_button = make_action_button(
            "Remove ROI",
            variant="tertiary",
            compact=True,
            parent=self,
        )
        self.remove_button.setObjectName("settings_rois_remove_roi")
        list_actions.addWidget(self.remove_button)
        list_actions.addStretch(1)
        layout.addLayout(list_actions)

        layout.addWidget(SubsectionHeaderLabel("Edit active ROI", self))
        name_label = QLabel("ROI name:", self)
        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("settings_rois_name")
        self.name_edit.setPlaceholderText("ROI name")
        name_label.setBuddy(self.name_edit)
        layout.addWidget(name_label)
        layout.addWidget(self.name_edit)
        self.electrode_count = QLabel(self)
        self.electrode_count.setObjectName("settings_rois_electrode_count")
        self.electrode_count.setTextFormat(Qt.TextFormat.PlainText)
        self.electrode_count.setWordWrap(True)
        layout.addWidget(self.electrode_count)

        self.clear_button = make_action_button(
            "Clear Active ROI",
            variant="tertiary",
            compact=True,
            parent=self,
        )
        self.clear_button.setObjectName("settings_rois_clear")
        layout.addWidget(self.clear_button, 0, Qt.AlignmentFlag.AlignLeft)

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
    toolbar: ROIEditorToolbar,
    side_panel: ROIEditorSidePanel,
    map_buttons: Sequence[QWidget],
) -> None:
    """Put ROI context controls before the map's 64-node keyboard sequence."""

    chain = (
        toolbar.montage_combo,
        toolbar.preset_combo,
        toolbar.add_preset_button,
        toolbar.save_presets_button,
        side_panel.roi_list,
        side_panel.add_button,
        side_panel.remove_button,
        side_panel.name_edit,
        side_panel.clear_button,
        side_panel.unmapped_list,
        side_panel.remove_unmapped_button,
        *map_buttons,
    )
    for current, following in zip(chain, chain[1:]):
        QWidget.setTabOrder(current, following)


__all__ = [
    "ROIEditorSidePanel",
    "ROIEditorToolbar",
    "ROI_COLOR_PALETTE",
    "ROIPresetProvider",
    "configure_roi_tab_order",
    "map_selection_summary",
    "roi_color_for_id",
    "roi_color_icon",
]
