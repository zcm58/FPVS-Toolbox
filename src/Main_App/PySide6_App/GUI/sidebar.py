# Sidebar construction helpers extracted from main_window.py
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QToolButton,
    QSizePolicy,
    QFrame,
    QDockWidget,
    QApplication,
)
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt, QSize
from pathlib import Path
from PySide6.QtWidgets import QStyle


def white_icon(name: str) -> QIcon:
    icon = QIcon.fromTheme(name)
    if icon.isNull():
        return icon
    pm = icon.pixmap(24, 24)
    tinted = QPixmap(pm.size())
    tinted.fill(Qt.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, pm)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor("white"))
    painter.end()
    return QIcon(tinted)


def make_button(
    layout: QVBoxLayout, name: str, text: str, icon: QIcon | str | None, slot
) -> QToolButton:
    btn = QToolButton()
    btn.setObjectName(name)
    btn.setText(text)
    btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setIconSize(QSize(24, 24))
    btn.setStyleSheet("padding: 12px 16px; text-align: left;")
    if icon:
        if isinstance(icon, QIcon):
            btn.setIcon(icon)
        else:
            btn.setIcon(white_icon(icon))
    if slot:
        btn.clicked.connect(slot)
    layout.addWidget(btn)
    return btn


def init_sidebar(self) -> None:
    """Create the dark sidebar with tool buttons."""
    sidebar = QWidget(self)
    sidebar.setObjectName("sidebar")
    sidebar.setFixedWidth(200)
    lay = QVBoxLayout(sidebar)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    self.btn_home = make_button(lay, "btn_home", "Home", "go-home", lambda: None)
    self.btn_data = make_button(
        lay,
        "btn_data",
        "Statistical Analysis",
        QApplication.instance().style().standardIcon(QStyle.SP_ComputerIcon),
        self.open_stats_analyzer,
    )
    icon_dir = Path(__file__).resolve().parent / "icons"
    snr_icon = QIcon(str(icon_dir / "snr_plots.svg"))
    self.btn_graphs = make_button(
        lay, "btn_graphs", "SNR Plots", snr_icon, self.open_plot_generator
    )
    self.btn_image = make_button(
        lay, "btn_image", "Image Resizer", "camera-photo", self.open_image_resizer
    )
    self.btn_epoch = make_button(
        lay, "btn_epoch", "Epoch Averaging", "view-refresh", self.open_epoch_averaging
    )
    divider = QFrame()
    divider.setFrameShape(QFrame.HLine)
    divider.setFixedHeight(1)
    divider.setStyleSheet("background:#444;")
    lay.addWidget(divider)

    lay.addStretch(1)

    self.btn_settings = make_button(
        lay, "btn_settings", "Settings", "settings", self.open_settings_window
    )
    self.btn_info = make_button(
        lay, "btn_info", "Information", None, self.show_relevant_publications
    )
    self.btn_help = make_button(lay, "btn_help", "Help", None, self.show_about_dialog)

    dock = QDockWidget("", self)
    dock.setWidget(sidebar)
    dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
    self.addDockWidget(Qt.LeftDockWidgetArea, dock)
