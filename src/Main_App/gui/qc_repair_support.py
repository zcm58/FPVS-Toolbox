"""Presentation of proposed or confirmed repair locations and usable donors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QWidget

from Main_App.gui.components import ActionRow, AppDialog, StatusBanner, SurfaceSize, make_action_button
from Main_App.gui.style_tokens import ACCENT_COLOR, BORDER_COLOR, DANGER_COLOR, TEXT_MUTED, TEXT_PRIMARY
from Main_App.io.eeg_geometry import canonical_biosemi64_head_coordinates
from Main_App.processing.qc_review_diagnostics import review_repair_topology


class RepairSupportMap(QWidget):
    """Small head-coordinate location map; it does not estimate EEG values."""

    def __init__(self, positions: Mapping[str, Sequence[float]], repair_channels: Sequence[str], parent=None):
        super().__init__(parent)
        self.positions = dict(positions)
        self.repairs = set(repair_channels)
        self.selected = ""
        self.donors: set[str] = set()
        self.setMinimumSize(360, 330)
        self.setAccessibleName("Repair and donor locations viewed from above the head")

    def select_channel(self, channel: str, donors: Sequence[str]) -> None:
        self.selected, self.donors = channel, set(donors)
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = QRectF(self.rect()).adjusted(28, 35, -28, -28)
        radius = min(bounds.width(), bounds.height()) / 2
        center = bounds.center()
        extent = max((abs(float(value)) for xyz in self.positions.values() for value in xyz[:2]), default=1.0)
        extent = max(extent, 1e-12)
        points = {name: QPointF(center.x() + float(xyz[0]) / extent * radius * .88,
                                center.y() - float(xyz[1]) / extent * radius * .88)
                  for name, xyz in self.positions.items()}
        painter.setPen(QPen(QColor(BORDER_COLOR), 1.5))
        painter.drawEllipse(center, radius, radius)
        painter.drawLine(QPointF(center.x() - 9, center.y() - radius),
                         QPointF(center.x(), center.y() - radius - 14))
        painter.drawLine(QPointF(center.x(), center.y() - radius - 14),
                         QPointF(center.x() + 9, center.y() - radius))
        painter.setPen(QColor(TEXT_PRIMARY))
        painter.drawText(QRectF(0, 0, self.width(), 22), Qt.AlignmentFlag.AlignCenter, "Front / nose")
        if self.selected in points:
            painter.setPen(QPen(QColor(ACCENT_COLOR), 1, Qt.PenStyle.DotLine))
            for donor in self.donors:
                if donor in points:
                    painter.drawLine(points[self.selected], points[donor])
        for name, point in points.items():
            color = DANGER_COLOR if name in self.repairs else ACCENT_COLOR if name in self.donors else TEXT_MUTED
            painter.setPen(QPen(QColor(color), 1.0))
            painter.setBrush(QColor(color))
            size = 5.0 if name in self.repairs or name == self.selected else 3.0
            painter.drawEllipse(point, size, size)
            if name in self.repairs or name in self.donors:
                painter.drawText(point + QPointF(6, -5), name)


class RepairSupportDialog(AppDialog):
    """Review spatial support without adding a repair acceptance criterion."""

    def __init__(self, *, channels: Sequence[str], repair_channels: Sequence[str],
                 confirmed: bool, parent=None, unusable_channels: Sequence[str] = ()):
        super().__init__("Repair locations and donor support", parent,
                         size=SurfaceSize(940, 610, min_width=800, min_height=520))
        self.setObjectName("qc_repair_support_dialog")
        positions = canonical_biosemi64_head_coordinates()
        self._report = review_repair_topology(
            channels, positions, repair_channels=repair_channels,
            unusable_channels=unusable_channels,
        ) if channels else {
            "status": "unavailable", "channels": [], "components": [],
            "limitations": ["The retained scalp-channel set is unavailable; donor support cannot be assessed."],
        }
        label = "Confirmed successful repairs" if confirmed else "Proposed repair scenario · no changes applied"
        self.root_layout.addWidget(StatusBanner(label, self, variant="info"))
        description = QLabel(
            "Red: repaired/proposed electrodes. Blue: nearby usable donors for the selected electrode. "
            "Neighbor distances describe spatial support; they are not interpolation weights or proof of reconstruction accuracy.", self)
        description.setWordWrap(True)
        self.root_layout.addWidget(description)
        self.channel_combo = QComboBox(self)
        self.channel_combo.setAccessibleName("Repaired electrode to inspect")
        for row in self._report.get("channels", ()):
            self.channel_combo.addItem(str(row["channel"]))
        self.root_layout.addWidget(self.channel_combo)
        body = QHBoxLayout()
        retained_positions = {name: positions[name] for name in channels if name in positions}
        self.map = RepairSupportMap(retained_positions, repair_channels, self)
        body.addWidget(self.map, 1)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Donor support evidence and limitations")
        body.addWidget(self.details, 1)
        self.root_layout.addLayout(body, 1)
        self.channel_combo.currentTextChanged.connect(self._show_channel)
        actions = ActionRow(self)
        close = actions.add_button(make_action_button("Close", variant="primary", parent=actions))
        close.clicked.connect(self.accept)
        self.root_layout.addWidget(actions)
        self._show_channel(self.channel_combo.currentText())

    def _show_channel(self, name: str) -> None:
        row = next((item for item in self._report.get("channels", ()) if item["channel"] == name), {})
        donors = row.get("usable_donors", ())
        self.map.select_channel(name, [str(item["channel"]) for item in donors])
        components = self._report.get("components", ())
        lines = ["Connected repair groups: " + ("; ".join(", ".join(group) for group in components) or "None"), ""]
        if self._report.get("status") != "available":
            lines.extend(("Donor support is unavailable or incomplete.",))
        unknown = self._report.get("unknown_channels", ())
        missing = self._report.get("missing_geometry_channels", ())
        if unknown:
            lines.append("Outside the retained scalp set: " + ", ".join(unknown))
        if missing:
            lines.append("Missing location evidence: " + ", ".join(missing))
        if row:
            lines.extend((f"{name}: {row.get('available_donor_count', 0)} usable donor(s)", "Nearby usable donors:"))
            lines.extend(f"  {item['channel']}: {float(item['distance_m']) * 1000:.1f} mm" for item in donors)
            excluded = row.get("excluded_neighbors", ())
            if excluded:
                lines.append("Excluded neighboring donors: " + ", ".join(excluded))
        else:
            lines.append("No repaired electrode has usable location evidence.")
        lines.extend(("", *[str(value) for value in self._report.get("limitations", ())]))
        self.details.setPlainText("\n".join(lines))
