"""Accessible BioSemi64 electrode map for the embedded ROI editor."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolButton, QWidget

from Main_App.gui.components import font_for_role
from Main_App.gui.roi_electrode_selector_state import (
    BIOSEMI64_LABELS,
    BIOSEMI64_POLAR_COORDINATES,
    electrode_logical_position,
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


ROIMembership = tuple[str, str]


class _ElectrodeButton(QToolButton):
    """Native electrode control with membership arcs painted inside its bounds."""

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        colors = tuple(str(color) for color in (self.property("roiMembershipColors") or ()))
        if not colors:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        ring = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        if len(colors) == 1:
            painter.setPen(QPen(QColor(colors[0]), 2))
            painter.drawEllipse(ring)
            return
        span = 360 / len(colors)
        gap = min(5.0, span / 5)
        for index, color in enumerate(colors):
            pen = QPen(QColor(color), 2)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            start = 90 - index * span
            painter.drawArc(ring, round(start * 16), round(-(span - gap) * 16))


class ElectrodeMapWidget(QWidget):
    """Scalable nose-up map with native, keyboard-operable electrode buttons."""

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
        self._memberships: dict[str, tuple[ROIMembership, ...]] = {}
        self._active_color = ACCENT_COLOR
        self._active_roi_label = "active ROI"
        self.electrode_buttons: dict[str, QToolButton] = {}
        self.setObjectName("roi_electrode_map")
        self.setMinimumSize(500, 425)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        for label in BIOSEMI64_LABELS:
            button = _ElectrodeButton(self)
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
        return QSize(620, 520)

    def _transform(self) -> tuple[float, float, float]:
        scale = min(self.width() / 640, self.height() / 590)
        return scale, (self.width() - 640 * scale) / 2, (self.height() - 590 * scale) / 2

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        scale, left, top = self._transform()
        diameter = max(28, round(34 * scale))
        for label, button in self.electrode_buttons.items():
            x, y = self._positions[label]
            button.setGeometry(
                round(left + x * scale - diameter / 2),
                round(top + y * scale - diameter / 2),
                diameter,
                diameter,
            )
            self._update_button_presentation(label)

    def set_roi_context(
        self,
        selected_labels: Sequence[str],
        *,
        memberships_by_label: Mapping[str, Sequence[ROIMembership]],
        active_color: str,
        active_roi_label: str,
    ) -> None:
        """Atomically show the active ROI and every ROI membership on the map."""

        selected_keys = {str(label).strip().casefold() for label in selected_labels}
        self._memberships = {
            str(label).strip().casefold(): tuple(
                (str(member_label), str(color)) for member_label, color in memberships
            )
            for label, memberships in memberships_by_label.items()
        }
        self._active_color = str(active_color) or ACCENT_COLOR
        self._active_roi_label = str(active_roi_label) or "active ROI"
        for label, button in self.electrode_buttons.items():
            checked = label.casefold() in selected_keys
            with QSignalBlocker(button):
                button.setChecked(checked)
            button.setProperty(
                "roiMemberships",
                tuple(member_label for member_label, _color in self._membership_details(label)),
            )
            button.setProperty(
                "roiMembershipColors",
                tuple(color for _member_label, color in self._membership_details(label)),
            )
            button.setProperty("activeRoiMember", checked)
            button.setProperty("activeRoiColor", self._active_color)
            self._update_button_presentation(label)
            button.update()
        self.update()

    def roi_memberships(self, label: str) -> tuple[str, ...]:
        """Return ordered, non-color membership labels for tests and accessibility."""

        return tuple(member_label for member_label, _color in self._membership_details(label))

    def _membership_details(self, label: str) -> tuple[ROIMembership, ...]:
        return self._memberships.get(str(label).strip().casefold(), ())

    def _on_button_toggled(self, label: str, checked: bool) -> None:
        self._update_button_presentation(label)
        self.selection_changed.emit(self._canonical_lookup[label.casefold()], checked)

    def _update_button_presentation(self, label: str) -> None:
        button = self.electrode_buttons[label]
        checked = button.isChecked()
        memberships = self._membership_details(label)
        membership_labels = tuple(member_label for member_label, _color in memberships)
        if membership_labels:
            membership_text = "In " + ", ".join(membership_labels) + "."
        else:
            membership_text = "Not assigned to a defined ROI."
        action = "remove it from" if checked else "add it to"
        plain_description = (
            f"{membership_text} Editing {self._active_roi_label}; click or press Space to "
            f"{action} {self._active_roi_label}."
        )
        tooltip_membership = (
            "In " + ", ".join(escape(item) for item in membership_labels) + "."
            if membership_labels
            else "Not assigned to a defined ROI."
        )
        button.setText(label)
        button.setAccessibleDescription(plain_description)
        button.setToolTip(
            f"{escape(label)}. {tooltip_membership} Editing {escape(self._active_roi_label)}; "
            f"click or press Space to {action} {escape(self._active_roi_label)}."
        )
        background = self._active_color if checked else SURFACE_BG
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
                border: {border_width}px {border_style} {self._active_color if checked else BORDER_COLOR};
                border-radius: {button.width() // 2}px;
                padding: 0;
            }}
            QToolButton:hover {{
                background: {ACCENT_SOFT_BG};
                color: {TEXT_PRIMARY};
                border: {hover_border_width}px {border_style} {self._active_color};
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
        painter.save()
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
        painter.restore()

__all__ = ["ElectrodeMapWidget", "ROIMembership"]
