# sidebar.py
# Sidebar construction helpers
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QToolButton,
    QSizePolicy,
    QFrame,
    QApplication,
    QStyle,
)


def white_icon(source: QIcon | str | Path) -> QIcon:
    """Return a white-tinted icon from a file path, theme name, or QIcon."""
    if isinstance(source, QIcon):
        icon = source
    else:
        p = Path(str(source))
        icon = QIcon(str(p)) if p.exists() else QIcon.fromTheme(str(source))

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
    layout: QVBoxLayout, name: str, text: str, icon: QIcon | str | Path | None, slot
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
        btn.setIcon(white_icon(icon))
    if slot:
        btn.clicked.connect(slot)
    layout.addWidget(btn)
    return btn


def init_sidebar(self) -> None:
    """
    Populate the permanent left sidebar created in ui_main.py.
    No QDockWidget is used—this prevents duplicate/floating sidebars.
    """
    sidebar: QWidget = getattr(self, "sidebar", None)
    if sidebar is None:
        sidebar = QWidget(self)
        self.sidebar = sidebar

    # Clear prior content if re-inited
    old_layout = sidebar.layout()
    if old_layout:
        while old_layout.count():
            item = old_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        old_layout.deleteLater()

    sidebar.setObjectName("sidebar")
    sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    sidebar.setMinimumWidth(200)
    sidebar.setContentsMargins(0, 0, 0, 0)
    sidebar.setStyleSheet("""
        #sidebar { background-color: #2E2E2E; border-right: 1px solid #3A3A3A; }
        #sidebar QToolButton { color: #FFFFFF; }
        #sidebar QToolButton:hover { background-color: rgba(255,255,255,0.06); }
    """)

    lay = QVBoxLayout(sidebar)
    lay.setContentsMargins(0, 8, 0, 8)
    lay.setSpacing(0)

    # Top group
    make_button(lay, "btn_home", "Home", "go-home", lambda: None)
    make_button(
        lay,
        "btn_data",
        "Statistical Analysis",
        QApplication.instance().style().standardIcon(QStyle.SP_ComputerIcon),
        self.open_stats_analyzer,
    )

    icon_dir = Path(__file__).resolve().parent / "icons"
    make_button(lay, "btn_graphs", "SNR Plots", icon_dir / "snr_plots.svg", self.open_plot_generator)
    make_button(lay, "btn_image", "Image Resizer", "camera-photo", self.open_image_resizer)
    make_button(lay, "btn_epoch", "Epoch Averaging", "view-refresh", self.open_epoch_averaging)

    # Divider
    divider = QFrame()
    divider.setFrameShape(QFrame.HLine)
    divider.setFixedHeight(1)
    divider.setStyleSheet("background:#444; margin: 8px 0;")
    lay.addWidget(divider)

    lay.addStretch(1)

    # Bottom group
    make_button(lay, "btn_settings", "Settings", "settings", self.open_settings_window)
    make_button(lay, "btn_info", "Information", None, self.show_relevant_publications)
    make_button(lay, "btn_help", "Help", None, self.show_about_dialog)
