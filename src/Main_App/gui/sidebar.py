# sidebar.py
# Sidebar construction helpers (custom buttons with precise icon/text alignment)
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from Main_App.gui.icons import sidebar_icon
from .style_tokens import (
    SIDEBAR_WIDTH,
    build_sidebar_stylesheet,
)
from Main_App.gui.typography import apply_font_role

# ---- Tunables -------------------------------------------------------------
ICON_PX = 20          # normalize all icons to the same visual size
ROW_MIN_HEIGHT = 46   # total button height
TEXT_BOX_PX = 26      # common vertical box for the text
SECTION_LABEL_MIN_HEIGHT = 28
ROW_LEFT_PADDING = 6
ROW_RIGHT_PADDING = 8
ROW_ITEM_GAP = 7
SELECTION_BAR_WIDTH = 3
CENTERED_TEXT_TRAILING_SPACER_PX = (
    ROW_LEFT_PADDING + SELECTION_BAR_WIDTH + ICON_PX + ROW_ITEM_GAP - ROW_RIGHT_PADDING
)
# ---------------------------------------------------------------------------

DOCS_URL = "https://zcm58.github.io/FPVS-Toolbox-Repo/"  # MkDocs site for documentation


def tinted_icon(source: QIcon | str | Path, color: QColor) -> QIcon:
    """Return a tinted icon from a file path, theme name, or QIcon."""
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
    painter.fillRect(tinted.rect(), color)
    painter.end()
    return QIcon(tinted)


def white_icon(source: QIcon | str | Path) -> QIcon:
    """Return a white-tinted icon from a file path, theme name, or QIcon."""
    return tinted_icon(source, QColor("white"))


class SidebarButton(QWidget):
    """Custom sidebar button: card style, icon + text aligned visually in the center."""
    clicked = Signal()

    def __init__(
        self,
        name: str,
        text: str,
        icon: QIcon | str | Path | None,
        parent: QWidget | None = None,
        *,
        center_content: bool = False,
    ):
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
        lay.setContentsMargins(ROW_LEFT_PADDING, 8, ROW_RIGHT_PADDING, 8)
        lay.setSpacing(ROW_ITEM_GAP)
        lay.setAlignment(Qt.AlignVCenter)

        self.selection_bar = QFrame(self)
        self.selection_bar.setObjectName("SidebarSelectionBar")
        self.selection_bar.setFixedWidth(SELECTION_BAR_WIDTH)
        self.selection_bar.setFixedHeight(20)
        self.selection_bar.setProperty("active", False)
        lay.addWidget(self.selection_bar, 0, Qt.AlignVCenter)
        if center_content:
            lay.addStretch(1)

        self.icon_lbl = QLabel(self)
        self.icon_lbl.setFixedSize(ICON_PX, ICON_PX)
        self.icon_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._normal_icon_pixmap: QPixmap | None = None
        self._locked_icon_pixmap: QPixmap | None = None
        if icon:
            self._normal_icon_pixmap = white_icon(icon).pixmap(ICON_PX, ICON_PX)
            self._locked_icon_pixmap = tinted_icon(icon, QColor(255, 255, 255, 97)).pixmap(
                ICON_PX,
                ICON_PX,
            )
            self.icon_lbl.setPixmap(self._normal_icon_pixmap)
        lay.addWidget(self.icon_lbl, 0, Qt.AlignVCenter)

        self.text_lbl = QLabel(text, self)
        apply_font_role(self.text_lbl, "sidebar_item")
        self.text_lbl.setMinimumHeight(TEXT_BOX_PX)
        self.text_lbl.setMaximumHeight(TEXT_BOX_PX)
        self.text_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        lay.addWidget(self.text_lbl, 0 if center_content else 1, Qt.AlignVCenter)
        if center_content:
            lay.addSpacing(CENTERED_TEXT_TRAILING_SPACER_PX)
            lay.addStretch(1)

    def set_processing_locked(self, locked: bool) -> None:
        self.setProperty("processingLocked", locked)
        self.setCursor(Qt.ArrowCursor if locked else Qt.PointingHandCursor)
        if self._normal_icon_pixmap is not None and self._locked_icon_pixmap is not None:
            self.icon_lbl.setPixmap(self._locked_icon_pixmap if locked else self._normal_icon_pixmap)
        self.style().unpolish(self)
        self.style().polish(self)
        self.style().unpolish(self.text_lbl)
        self.style().polish(self.text_lbl)
        self.update()

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.selection_bar.setProperty("active", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.style().unpolish(self.selection_bar)
        self.style().polish(self.selection_bar)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and not self.property("processingLocked"):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and not self.property("processingLocked"):
            self.clicked.emit()
        else:
            super().keyPressEvent(e)


def make_button(
    layout: QVBoxLayout,
    name: str,
    text: str,
    icon: QIcon | str | Path | None,
    slot,
    *,
    center_content: bool = False,
) -> SidebarButton:
    """API-compatible factory that returns a SidebarButton."""
    btn = SidebarButton(name, text, icon, center_content=center_content)
    if slot:
        btn.clicked.connect(slot)
    layout.addWidget(btn)
    return btn


def make_section_label(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("SidebarSectionLabel")
    apply_font_role(label, "sidebar_section")
    label.setMinimumHeight(SECTION_LABEL_MIN_HEIGHT)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
    return label


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
    sidebar.setFixedWidth(SIDEBAR_WIDTH)
    sidebar.setContentsMargins(12, 12, 12, 12)
    sidebar.setStyleSheet(build_sidebar_stylesheet())

    lay = QVBoxLayout(sidebar)
    lay.setContentsMargins(0, 6, 0, 6)
    lay.setSpacing(4)

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

    home_btn = make_button(
        primary_layout,
        "btn_home",
        "Home",
        sidebar_icon("home", ICON_PX),
        self.show_home_page,
        center_content=True,
    )
    home_btn.setProperty("homeEntry", True)
    self.sidebar_home_button = home_btn

    primary_layout.addSpacing(8)
    primary_layout.addWidget(make_divider(primary_group, "sidebar_home_divider"))
    primary_layout.addSpacing(8)

    tools_label = make_section_label("Workspace Tools", primary_group)
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
        sidebar_icon("stats", ICON_PX),
        self.open_stats_analyzer,
    )

    make_button(tools_layout, "btn_graphs", "SNR Plots", sidebar_icon("chart", ICON_PX), self.open_plot_generator)
    make_button(
        tools_layout,
        "btn_publication_maps",
        "Scalp Maps",
        sidebar_icon("scalp", ICON_PX),
        self.open_publication_maps,
    )
    make_button(
        tools_layout,
        "btn_ratio",
        "Ratio Calculator",
        sidebar_icon("ratio", ICON_PX),
        self.open_ratio_calculator,
    )
    make_button(
        tools_layout,
        "btn_individual_detectability",
        "Individual Detectability",
        sidebar_icon("detectability", ICON_PX),
        self.open_individual_detectability,
    )
    image_btn = make_button(
        tools_layout,
        "btn_image",
        "Image Resizer",
        sidebar_icon("image", ICON_PX),
        self.open_image_resizer,
    )
    self.sidebar_image_button = image_btn
    epoch_btn = make_button(
        tools_layout,
        "btn_epoch",
        "Epoch Averaging",
        sidebar_icon("epoch", ICON_PX),
        self.open_epoch_averaging,
    )
    self.sidebar_epoch_button = epoch_btn

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

    utility_label = make_section_label("Utilities", utilities_group)
    utilities_layout.addWidget(utility_label)
    self.sidebar_utilities_label = utility_label

    make_button(utilities_layout, "btn_settings", "Settings", sidebar_icon("settings", ICON_PX), self.open_settings_window)

    def _open_docs() -> None:
        QDesktopServices.openUrl(QUrl(DOCS_URL))

    make_button(
        utilities_layout,
        "btn_info",
        "Information",
        sidebar_icon("info", ICON_PX),
        _open_docs,
    )
    make_button(
        utilities_layout,
        "btn_help",
        "Help",
        sidebar_icon("help", ICON_PX),
        self.show_about_dialog,
    )

    self.sidebar_utilities_group = utilities_group
    lower_layout.addWidget(utilities_group)
    lower_layout.addStretch(1)
    lay.addWidget(lower_region, 1)

    home_btn.set_selected(True)
