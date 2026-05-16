# sidebar.py
# Sidebar construction helpers (custom buttons with precise icon/text alignment)
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from Main_App.gui.icons import division_icon, individual_detectability_icon, settings_icon
from Tools.Ratio_Calculator.launcher import open_ratio_calculator_tool
from Tools.Individual_Detectability.launcher import open_individual_detectability_tool
from .style_tokens import (
    SIDEBAR_WIDTH,
    build_sidebar_stylesheet,
)

# ---- Tunables -------------------------------------------------------------
ICON_PX = 18          # normalize all icons to the same visual size
ROW_MIN_HEIGHT = 42   # total button height
TEXT_BOX_PX = 22      # common vertical box for the text
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
        self.setProperty("selected", False)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(ROW_MIN_HEIGHT)
        self.setFocusPolicy(Qt.StrongFocus)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 14, 8)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignVCenter)

        self.selection_bar = QFrame(self)
        self.selection_bar.setObjectName("SidebarSelectionBar")
        self.selection_bar.setFixedWidth(3)
        self.selection_bar.setFixedHeight(20)
        self.selection_bar.setVisible(False)
        lay.addWidget(self.selection_bar, 0, Qt.AlignVCenter)

        self.icon_lbl = QLabel(self)
        self.icon_lbl.setFixedSize(ICON_PX, ICON_PX)
        self.icon_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        if icon:
            self.icon_lbl.setPixmap(white_icon(icon).pixmap(ICON_PX, ICON_PX))
        lay.addWidget(self.icon_lbl, 0, Qt.AlignVCenter)

        self.text_lbl = QLabel(text, self)
        f = QFont()
        f.setPointSize(f.pointSize() + 1)
        f.setWeight(QFont.Medium)
        self.text_lbl.setFont(f)
        self.text_lbl.setMinimumHeight(TEXT_BOX_PX)
        self.text_lbl.setMaximumHeight(TEXT_BOX_PX)
        self.text_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lay.addWidget(self.text_lbl, 1, Qt.AlignVCenter)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.selection_bar.setVisible(selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

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
    sidebar.setAttribute(Qt.WA_StyledBackground, True)
    sidebar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    sidebar.setMinimumWidth(SIDEBAR_WIDTH)
    sidebar.setContentsMargins(12, 12, 12, 12)
    sidebar.setStyleSheet(build_sidebar_stylesheet())

    lay = QVBoxLayout(sidebar)
    lay.setContentsMargins(0, 6, 0, 6)
    lay.setSpacing(4)

    app_style = QApplication.instance().style() if QApplication.instance() else self.style()

    def make_divider(parent: QWidget, object_name: str = "sidebar_divider") -> QFrame:
        divider = QFrame(parent)
        divider.setObjectName(object_name)
        divider.setFrameShape(QFrame.HLine)
        divider.setFixedHeight(1)
        return divider

    primary_group = QWidget(sidebar)
    primary_group.setObjectName("sidebar_primary_group")
    primary_layout = QVBoxLayout(primary_group)
    primary_layout.setContentsMargins(0, 0, 0, 0)
    primary_layout.setSpacing(4)

    home_btn = make_button(primary_layout, "btn_home", "Home", "go-home", self.show_home_page)
    home_btn.setProperty("homeEntry", True)
    self.sidebar_home_button = home_btn

    primary_layout.addSpacing(8)
    primary_layout.addWidget(make_divider(primary_group, "sidebar_home_divider"))
    primary_layout.addSpacing(8)

    tools_label = QLabel("Workspace Tools", primary_group)
    tools_label.setObjectName("SidebarSectionLabel")
    primary_layout.addWidget(tools_label)
    self.sidebar_tools_label = tools_label

    tools_group = QWidget(primary_group)
    tools_group.setObjectName("sidebar_tools_group")
    tools_layout = QVBoxLayout(tools_group)
    tools_layout.setContentsMargins(0, 0, 0, 0)
    tools_layout.setSpacing(4)

    make_button(
        tools_layout,
        "btn_data",
        "Statistical Analysis",
        app_style.standardIcon(QStyle.SP_ComputerIcon),
        self.open_stats_analyzer,
    )

    # SNR Plots: theme icon or drawn bar chart (no external files)
    make_button(tools_layout, "btn_graphs", "SNR Plots", chart_icon(), self.open_plot_generator)
    make_button(
        tools_layout,
        "btn_ratio",
        "Ratio Calculator",
        division_icon(ICON_PX),
        lambda: open_ratio_calculator_tool(self),
    )
    make_button(
        tools_layout,
        "btn_individual_detectability",
        "Individual Detectability",
        individual_detectability_icon(ICON_PX),
        lambda: open_individual_detectability_tool(self),
    )
    image_btn = make_button(
        tools_layout,
        "btn_image",
        "Image Resizer",
        "camera-photo",
        self.open_image_resizer,
    )
    self.sidebar_image_button = image_btn
    make_button(
        tools_layout,
        "btn_epoch",
        "Epoch Averaging",
        "view-refresh",
        self.open_epoch_averaging,
    )

    primary_layout.addWidget(tools_group)
    self.sidebar_tools_group = tools_group
    lay.addWidget(primary_group)

    lower_region = QWidget(sidebar)
    lower_region.setObjectName("sidebar_lower_region")
    lower_layout = QVBoxLayout(lower_region)
    lower_layout.setContentsMargins(0, 0, 0, 0)
    lower_layout.setSpacing(0)
    lower_layout.addStretch(2)

    utilities_group = QWidget(lower_region)
    utilities_group.setObjectName("sidebar_utilities_group")
    utilities_layout = QVBoxLayout(utilities_group)
    utilities_layout.setContentsMargins(0, 0, 0, 0)
    utilities_layout.setSpacing(4)
    utilities_layout.addWidget(make_divider(utilities_group))
    utilities_layout.addSpacing(8)

    utility_label = QLabel("Utilities", utilities_group)
    utility_label.setObjectName("SidebarSectionLabel")
    utilities_layout.addWidget(utility_label)
    self.sidebar_utilities_label = utility_label

    make_button(utilities_layout, "btn_settings", "Settings", settings_icon(ICON_PX), self.open_settings_window)

    def _open_docs() -> None:
        QDesktopServices.openUrl(QUrl(DOCS_URL))

    make_button(
        utilities_layout,
        "btn_info",
        "Information",
        app_style.standardIcon(QStyle.SP_MessageBoxInformation),
        _open_docs,
    )
    make_button(
        utilities_layout,
        "btn_help",
        "Help",
        app_style.standardIcon(QStyle.SP_DialogHelpButton),
        self.show_about_dialog,
    )

    self.sidebar_utilities_group = utilities_group
    lower_layout.addWidget(utilities_group)
    lower_layout.addStretch(1)
    lay.addWidget(lower_region, 1)

    home_btn.set_selected(True)
