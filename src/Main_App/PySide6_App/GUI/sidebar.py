# sidebar.py
# Sidebar construction helpers (custom buttons with precise icon/text alignment)
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSizePolicy,
    QFrame,
    QApplication,
    QStyle,
    QLabel,
    QHBoxLayout,
)
from Main_App.PySide6_App.GUI.icons import division_icon
from Tools.Ratio_Calculator.launcher import open_ratio_calculator_tool

# ---- Tunables -------------------------------------------------------------
ICON_PX = 20          # normalize all icons to the same visual size
ROW_MIN_HEIGHT = 40   # total button height (card)
TEXT_BOX_PX = 22      # common vertical box for the text (matches icon box)
TEXT_NUDGE_PX = -1    # small vertical nudge to lift text
# ---------------------------------------------------------------------------

DOCS_URL = "https://zcm58.github.io/FPVS-Toolbox-Repo/"  # MkDocs site for documentation


def white_icon(source: QIcon | str | Path) -> QIcon:
    """Return a white-tinted icon from a file path, theme name, or QIcon."""
    if isinstance(source, QIcon):
        icon = source
    else:
        p = Path(str(source))
        icon = QIcon(str(p)) if p.exists() else QIcon.fromTheme(str(source))

    if icon.isNull():
        return icon

    pm = icon.pixmap(ICON_PX, ICON_PX)
    tinted = QPixmap(pm.size())
    tinted.fill(Qt.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, pm)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), QColor("white"))
    painter.end()
    return QIcon(tinted)


def chart_icon() -> QIcon:
    """
    Try common theme bar-chart icons. If none exist, draw a white bar chart.
    Avoids Qt standard pixmap fallback that appeared as a white square.
    """
    for name in ("view-statistics", "office-chart-bar", "insert-chart", "chart", "analytics"):
        ic = QIcon.fromTheme(name)
        if not ic.isNull():
            return white_icon(ic)

    # Draw fallback bars
    pm = QPixmap(ICON_PX, ICON_PX)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("white"))

    margin = 2
    gap = 3
    bars = 3
    total_gap = gap * (bars - 1)
    bar_w = max(2, (ICON_PX - 2 * margin - total_gap) // bars)
    heights = [int(ICON_PX * 0.45), int(ICON_PX * 0.7), int(ICON_PX * 0.9)]

    x = margin
    for h in heights:
        y = ICON_PX - margin - h
        p.drawRoundedRect(x, y, bar_w, h, 2, 2)
        x += bar_w + gap

    p.end()
    return QIcon(pm)


class SidebarButton(QWidget):
    """Custom sidebar button: card style, icon + text aligned visually in the center."""
    clicked = Signal()

    def __init__(self, name: str, text: str, icon: QIcon | str | Path | None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SidebarButton")
        self.setProperty("role", name)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(ROW_MIN_HEIGHT)
        self.setFocusPolicy(Qt.StrongFocus)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignVCenter)

        self.icon_lbl = QLabel(self)
        self.icon_lbl.setFixedSize(ICON_PX, ICON_PX)
        self.icon_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        if icon:
            self.icon_lbl.setPixmap(white_icon(icon).pixmap(ICON_PX, ICON_PX))
        lay.addWidget(self.icon_lbl, 0, Qt.AlignVCenter)

        self.text_lbl = QLabel(text, self)
        f = QFont()
        f.setPointSize(f.pointSize() + 1)
        self.text_lbl.setFont(f)
        self.text_lbl.setMinimumHeight(TEXT_BOX_PX)
        self.text_lbl.setMaximumHeight(TEXT_BOX_PX)
        self.text_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        if TEXT_NUDGE_PX != 0:
            self.text_lbl.setContentsMargins(0, max(0, -TEXT_NUDGE_PX), 0, 0)
        lay.addWidget(self.text_lbl, 1, Qt.AlignVCenter)

        self.setStyleSheet("""
            #SidebarButton {
                background-color: #363636;
                border: 1px solid #3A3A3A;
                border-radius: 8px;
            }
            #SidebarButton:hover  { background-color: #3B3B3B; }
            #SidebarButton:pressed{ background-color: #444444; }
            #SidebarButton:focus  {
                outline: none;
                border: 1px solid #0078D4;
            }
            #SidebarButton QLabel { color: white; }
        """)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(e)


def make_button(
    layout: QVBoxLayout, name: str, text: str, icon: QIcon | str | Path | None, slot
) -> SidebarButton:
    """API-compatible factory that returns a SidebarButton."""
    btn = SidebarButton(name, text, icon)
    if slot:
        btn.clicked.connect(slot)
    layout.addWidget(btn)
    return btn


def init_sidebar(self) -> None:
    """
    Populate the permanent left sidebar created in ui_main.py.
    Fixed column only.
    """
    sidebar: QWidget = getattr(self, "sidebar", None)
    if sidebar is None:
        sidebar = QWidget(self)
        self.sidebar = sidebar

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
    sidebar.setContentsMargins(8, 8, 8, 8)
    sidebar.setStyleSheet("""
        #sidebar { background-color: #2E2E2E; border-right: 1px solid #3A3A3A; }
    """)

    lay = QVBoxLayout(sidebar)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)

    # Top group
    make_button(lay, "btn_home", "Home", "go-home", lambda: None)
    make_button(
        lay,
        "btn_data",
        "Statistical Analysis",
        QApplication.instance().style().standardIcon(QStyle.SP_ComputerIcon),
        self.open_stats_analyzer,
    )

    # SNR Plots: theme icon or drawn bar chart (no external files)
    make_button(lay, "btn_graphs", "SNR Plots", chart_icon(), self.open_plot_generator)
    make_button(
        lay,
        "btn_ratio",
        "Ratio Calculator",
        division_icon(ICON_PX),
        lambda: open_ratio_calculator_tool(self),
    )

    make_button(lay, "btn_image", "Image Resizer", "camera-photo", self.open_image_resizer)
    make_button(lay, "btn_epoch", "Epoch Averaging", "view-refresh", self.open_epoch_averaging)
    # Divider
    divider = QFrame()
    divider.setFrameShape(QFrame.HLine)
    divider.setFixedHeight(1)
    divider.setStyleSheet("background:#444; margin: 6px 0;")
    lay.addWidget(divider)

    lay.addStretch(1)

    # Bottom group
    make_button(lay, "btn_settings", "Settings", "settings", self.open_settings_window)

    def _open_docs() -> None:
        QDesktopServices.openUrl(QUrl(DOCS_URL))

    make_button(lay, "btn_info", "Information", None, _open_docs)
    make_button(lay, "btn_help", "Help", None, self.show_about_dialog)
