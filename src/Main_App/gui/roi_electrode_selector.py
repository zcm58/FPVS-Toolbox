"""Accessible BioSemi64 electrode-map dialog for editing an ROI draft."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    ActionRow,
    AppDialog,
    StatusBanner,
    SubsectionHeaderLabel,
    SurfaceSize,
    font_for_role,
    make_action_button,
)
from Main_App.gui.roi_electrode_selector_state import (
    BIOSEMI64_LABELS,
    BIOSEMI64_POLAR_COORDINATES,
    ROIElectrodeSelectionState,
    electrode_logical_position,
    split_electrode_text,
)
from Main_App.gui.style_tokens import (
    ACCENT_COLOR,
    ACCENT_SOFT_BG,
    BORDER_COLOR,
    HEADER_BG,
    SURFACE_ALT_BG,
    SURFACE_BG,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


class ElectrodeMapWidget(QWidget):
    """Scalable nose-up head map with native checkable electrode buttons."""

    selection_changed = Signal(str, bool)

    def __init__(self, canonical_electrodes: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        canonical_lookup = {
            str(label).strip().casefold(): str(label).strip()
            for label in canonical_electrodes
            if str(label).strip()
        }
        expected = {label.casefold() for label in BIOSEMI64_LABELS}
        if set(canonical_lookup) != expected:
            missing = sorted(expected - set(canonical_lookup))
            extra = sorted(set(canonical_lookup) - expected)
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if extra:
                details.append("unexpected " + ", ".join(extra))
            raise ValueError("BioSemi64 selector catalog mismatch: " + "; ".join(details))

        self._canonical_lookup = canonical_lookup
        self._positions = {
            label: electrode_logical_position(theta, phi)
            for label, theta, phi in BIOSEMI64_POLAR_COORDINATES
        }
        self.electrode_buttons: dict[str, QToolButton] = {}
        self.setObjectName("roi_electrode_map")
        self.setMinimumSize(520, 480)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        for label in BIOSEMI64_LABELS:
            button = QToolButton(self)
            button.setObjectName(f"roi_electrode_{label.casefold()}")
            button.setCheckable(True)
            button.setFocusPolicy(Qt.StrongFocus)
            button.setAccessibleName(f"Electrode {label}")
            button.setFont(font_for_role("caption", button.font()))
            button.toggled.connect(
                lambda checked, electrode=label: self._on_button_toggled(electrode, checked)
            )
            self.electrode_buttons[label] = button
            self._update_button_presentation(label)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return QSize(640, 480)

    def _transform(self) -> tuple[float, float, float]:
        scale = min(self.width() / 640, self.height() / 590)
        return scale, (self.width() - 640 * scale) / 2, (self.height() - 590 * scale) / 2

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        scale, left, top = self._transform()
        diameter = max(30, round(34 * scale))
        for label, button in self.electrode_buttons.items():
            x, y = self._positions[label]
            button.setGeometry(
                round(left + x * scale - diameter / 2),
                round(top + y * scale - diameter / 2),
                diameter,
                diameter,
            )
            self._update_button_presentation(label)

    def set_selection(self, selected_labels: Sequence[str]) -> None:
        selected_keys = {str(label).strip().casefold() for label in selected_labels}
        for label, button in self.electrode_buttons.items():
            with QSignalBlocker(button):
                button.setChecked(label.casefold() in selected_keys)
            self._update_button_presentation(label)

    def _on_button_toggled(self, label: str, checked: bool) -> None:
        self._update_button_presentation(label)
        self.selection_changed.emit(self._canonical_lookup[label.casefold()], checked)

    def _update_button_presentation(self, label: str) -> None:
        button = self.electrode_buttons[label]
        checked = button.isChecked()
        button.setText(label)
        state_text = "Selected" if checked else "Not selected"
        button.setAccessibleDescription(
            f"{state_text}. Click or press Space to toggle {label} in this ROI."
        )
        button.setToolTip(
            f"{state_text}: {label}. Click or press Space to toggle this electrode."
        )
        background = ACCENT_COLOR if checked else SURFACE_BG
        foreground = SURFACE_BG if checked else TEXT_PRIMARY
        border_width = 3 if checked else 1
        border_style = "double" if checked else "solid"
        hover_border_width = 3 if checked else 2
        focus_border_style = "double" if checked else "solid"
        button.setStyleSheet(
            f"""
            QToolButton {{
                background: {background};
                color: {foreground};
                border: {border_width}px {border_style} {ACCENT_COLOR if checked else BORDER_COLOR};
                border-radius: {button.width() // 2}px;
                padding: 0;
            }}
            QToolButton:hover {{
                background: {ACCENT_SOFT_BG};
                color: {TEXT_PRIMARY};
                border: {hover_border_width}px {border_style} {ACCENT_COLOR};
            }}
            QToolButton:focus {{
                border: 3px {focus_border_style} {HEADER_BG};
            }}
            """
        )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(SURFACE_ALT_BG))
        scale, left, top = self._transform()
        painter.translate(left, top)
        painter.scale(scale, scale)
        painter.setPen(QPen(QColor(TEXT_MUTED), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(320, 300), 195, 195)

        outline = QPainterPath(QPointF(289, 108))
        outline.lineTo(320, 77)
        outline.lineTo(351, 108)
        outline.moveTo(123, 262)
        outline.cubicTo(92, 267, 91, 333, 123, 338)
        outline.moveTo(517, 262)
        outline.cubicTo(548, 267, 549, 333, 517, 338)
        painter.drawPath(outline)

        painter.setFont(font_for_role("caption", self.font()))
        painter.setPen(QColor(TEXT_SECONDARY))
        for text, rect in (
            ("FRONT", QRectF(260, 21, 120, 24)),
            ("BACK", QRectF(260, 560, 120, 24)),
            ("LEFT", QRectF(12, 288, 70, 24)),
            ("RIGHT", QRectF(558, 288, 70, 24)),
        ):
            painter.drawText(rect, Qt.AlignCenter, text)


class ROIElectrodeSelectorDialog(AppDialog):
    """Edit a row-local ROI draft; only an accepted dialog exposes changes."""

    def __init__(
        self,
        *,
        canonical_electrodes: Sequence[str],
        current_name: str,
        current_electrodes: Sequence[str],
        presets: Sequence[tuple[str, Sequence[str], bool]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Select ROI Electrodes",
            parent,
            size=SurfaceSize(width=1000, height=760, min_width=760, min_height=600),
        )
        self.setObjectName("roi_electrode_selector_dialog")
        self.setModal(True)
        self._initial_name = str(current_name)
        self._state = ROIElectrodeSelectionState(canonical_electrodes, current_electrodes)
        self._presets = tuple(
            (
                str(name),
                tuple(str(electrode) for electrode in electrodes),
                bool(is_default),
            )
            for name, electrodes, is_default in presets
        )
        self._accepted_name = self._initial_name
        self._accepted_electrodes = self._state.original_electrodes
        self._context_status: tuple[str, str] | None = None

        intro = QLabel(
            "Choose electrodes on the nose-up BioSemi64 map. The text row in Settings remains available "
            "for manual or noncanonical labels.",
            self,
        )
        intro.setWordWrap(True)
        self.root_layout.addWidget(intro)

        self.map_widget = ElectrodeMapWidget(canonical_electrodes, self)
        self.name_edit = QLineEdit(self._initial_name, self)
        self.name_edit.setObjectName("roi_selector_name")
        self.name_edit.setPlaceholderText("ROI name")
        self.name_edit.setAccessibleName("ROI name")

        self.preset_combo = QComboBox(self)
        self.preset_combo.setObjectName("roi_selector_preset")
        self.preset_combo.setAccessibleName("ROI preset")
        self.preset_combo.addItem("Choose a preset...", None)
        for index, (name, _electrodes, is_default) in enumerate(self._presets):
            source = "Default" if is_default else "Custom"
            self.preset_combo.addItem(f"{name} ({source})", index)

        self.apply_preset_button = make_action_button("Apply Preset", compact=True, parent=self)
        self.apply_preset_button.setObjectName("roi_selector_apply_preset")
        self.apply_preset_button.setAccessibleName("Apply selected ROI preset")
        self.apply_preset_button.setEnabled(False)

        self.selection_label = QLabel(self)
        self.selection_label.setObjectName("roi_selector_summary")
        self.selection_label.setWordWrap(True)
        self.selection_label.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.unmapped_edit = QLineEdit(self)
        self.unmapped_edit.setObjectName("roi_selector_unmapped")
        self.unmapped_edit.setPlaceholderText("Optional labels not drawn on the BioSemi64 map")
        self.unmapped_edit.setAccessibleName("Unmapped ROI electrode labels")
        self.unmapped_edit.setToolTip(
            "Comma-separated noncanonical labels retained from the Settings row. Remove a label here only "
            "when you intend to remove it from the ROI."
        )

        self.status = StatusBanner("", self, variant="info")
        self.status.setObjectName("roi_selector_status")
        self.status.label.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setVisible(False)

        scroll = QScrollArea(self)
        scroll.setObjectName("roi_selector_scroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget(scroll)
        self._content_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(18)
        self._content_layout.addWidget(self.map_widget, 2)

        self._details = QWidget(content)
        self._details.setMinimumWidth(290)
        self._details.setMaximumWidth(350)
        details_layout = QVBoxLayout(self._details)
        details_layout.setContentsMargins(0, 4, 8, 4)
        details_layout.setSpacing(8)

        details_layout.addWidget(SubsectionHeaderLabel("ROI name", self._details))
        name_label = QLabel("Name:", self._details)
        name_label.setBuddy(self.name_edit)
        details_layout.addWidget(name_label)
        details_layout.addWidget(self.name_edit)

        details_layout.addWidget(SubsectionHeaderLabel("Start from a preset", self._details))
        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(8)
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.apply_preset_button)
        details_layout.addLayout(preset_row)

        details_layout.addWidget(SubsectionHeaderLabel("Draft selection", self._details))
        details_layout.addWidget(self.selection_label)
        unmapped_label = QLabel("Unmapped labels:", self._details)
        unmapped_label.setBuddy(self.unmapped_edit)
        details_layout.addWidget(unmapped_label)
        details_layout.addWidget(self.unmapped_edit)
        details_layout.addWidget(self.status)
        details_layout.addStretch(1)
        self._content_layout.addWidget(self._details, 1)
        scroll.setWidget(content)
        self.root_layout.addWidget(scroll, 1)

        actions = ActionRow(self, alignment=Qt.AlignLeft)
        actions.setObjectName("roi_selector_actions")
        self.clear_button = make_action_button("Clear", variant="tertiary", parent=actions)
        self.clear_button.setObjectName("roi_selector_clear")
        self.cancel_button = make_action_button("Cancel", parent=actions)
        self.cancel_button.setObjectName("roi_selector_cancel")
        self.use_button = make_action_button("Use Selection", variant="primary", parent=actions)
        self.use_button.setObjectName("roi_selector_use")
        self.use_button.setDefault(True)
        actions.add_button(self.clear_button)
        actions.row_layout.addStretch(1)
        actions.add_button(self.cancel_button)
        actions.add_button(self.use_button)
        self.root_layout.addWidget(actions)

        self.map_widget.selection_changed.connect(self._on_map_selection_changed)
        self.name_edit.textChanged.connect(self._refresh)
        self.unmapped_edit.textChanged.connect(self._preview_unmapped_text)
        self.unmapped_edit.editingFinished.connect(self._commit_unmapped_text)
        self.preset_combo.currentIndexChanged.connect(
            lambda _index: self.apply_preset_button.setEnabled(
                self.preset_combo.currentData() is not None
            )
        )
        self.apply_preset_button.clicked.connect(self._apply_selected_preset)
        self.clear_button.clicked.connect(self._clear_selection)
        self.cancel_button.clicked.connect(self.reject)
        self.use_button.clicked.connect(self.accept)
        self._sync_widgets_from_state()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if not hasattr(self, "_content_layout"):
            return
        narrow = self.width() < 940
        self._content_layout.setDirection(
            QBoxLayout.Direction.TopToBottom
            if narrow
            else QBoxLayout.Direction.LeftToRight
        )
        self._details.setMinimumWidth(0 if narrow else 290)
        self._details.setMaximumWidth(16777215 if narrow else 350)
        self.map_widget.setMaximumHeight(650 if narrow else 16777215)

    def selection_name(self) -> str:
        return self._accepted_name

    def selected_electrodes(self) -> tuple[str, ...]:
        return self._accepted_electrodes

    def name_changed(self) -> bool:
        return self._accepted_name != self._initial_name

    def electrodes_changed(self) -> bool:
        return self._accepted_electrodes != self._state.original_electrodes

    def accept(self) -> None:
        self._commit_unmapped_text()
        name = self.name_edit.text()
        electrodes = self._state.selected_electrodes()
        if not name.strip() or not electrodes:
            self._refresh()
            return
        self._accepted_name = self._initial_name if name == self._initial_name else name.strip()
        self._accepted_electrodes = electrodes
        super().accept()

    def _on_map_selection_changed(self, label: str, checked: bool) -> None:
        self._state.set_checked(label, checked)
        self._context_status = None
        self._refresh()

    def _preview_unmapped_text(self, _text: str) -> None:
        self._context_status = None
        self._refresh()

    def _commit_unmapped_text(self) -> None:
        promoted = self._state.set_unmapped(
            split_electrode_text(self.unmapped_edit.text())
        )
        if promoted:
            self._context_status = (
                "Moved mapped labels onto the BioSemi64 selector: " + ", ".join(promoted) + ".",
                "info",
            )
        else:
            self._context_status = None
        self._sync_widgets_from_state()

    def _apply_selected_preset(self) -> None:
        preset_index = self.preset_combo.currentData()
        if not isinstance(preset_index, int) or not 0 <= preset_index < len(self._presets):
            return
        name, electrodes, _is_default = self._presets[preset_index]
        unmapped = self._state.replace_with(electrodes)
        self.name_edit.setText(name)
        if unmapped:
            self._context_status = (
                "This preset includes labels not drawn on the BioSemi64 map. They remain selected below: "
                + ", ".join(unmapped),
                "warning",
            )
        else:
            self._context_status = (f"Applied {name} to the draft.", "success")
        self._sync_widgets_from_state()

    def _clear_selection(self) -> None:
        self._state.clear()
        self._context_status = ("Draft electrode selection cleared.", "info")
        self._sync_widgets_from_state()

    def _sync_widgets_from_state(self) -> None:
        self.map_widget.set_selection(self._state.selected_map_labels())
        with QSignalBlocker(self.unmapped_edit):
            self.unmapped_edit.setText(",".join(self._state.unmapped_electrodes()))
        self._refresh()

    def _refresh(self) -> None:
        entered_unmapped = split_electrode_text(self.unmapped_edit.text())
        electrodes = self._state.preview_electrodes(entered_unmapped)
        if electrodes:
            self.selection_label.setText(
                f"Selected electrode entries ({len(electrodes)}): " + ", ".join(electrodes)
            )
        else:
            self.selection_label.setText("No electrodes selected.")

        valid_name = bool(self.name_edit.text().strip())
        self.use_button.setEnabled(valid_name and bool(electrodes))
        if not valid_name:
            status = ("Enter a nonblank ROI name before using the selection.", "warning")
        elif not electrodes:
            status = ("Select at least one electrode before using the selection.", "warning")
        else:
            status = self._context_status

        if status is None:
            self.status.setVisible(False)
        else:
            text, variant = status
            self.status.set_variant(variant)
            self.status.set_text(text)
            self.status.setVisible(True)


__all__ = ["ElectrodeMapWidget", "ROIElectrodeSelectorDialog"]
