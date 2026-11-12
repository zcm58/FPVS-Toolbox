# sidebar.py
# Sidebar construction helpers (custom buttons with precise icon/text alignment)
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtGui import QAction, QIcon, QPixmap
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

_TOOL_ICONS = {
    "btn_free_harmonic_clustering": "harmonic",
    "btn_graphs": "chart",
    "btn_publication_maps": "scalp",
    "btn_data": "stats",
    "btn_sensitivity_analysis": "sensitivity",
    "btn_loreta_visualizer": "loreta",
    "btn_sequence_figure": "sequence",
    "btn_individual_detectability": "detectability",
}

_TOOL_LABELS = {
    "btn_data": "Data Screening",
    "btn_free_harmonic_clustering": "Free Harmonic Clustering",
}


def _resolve_icon(source: QIcon | str | Path) -> QIcon:
    """Return an icon from a file path, theme name, or existing QIcon."""
    if isinstance(source, QIcon):
        return source
    path = Path(str(source))
    return QIcon(str(path)) if path.exists() else QIcon.fromTheme(str(source))


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
            resolved_icon = _resolve_icon(icon)
            icon_size = QSize(ICON_PX, ICON_PX)
            pixel_ratio = max(1.0, self.devicePixelRatioF())
            self._normal_icon_pixmap = resolved_icon.pixmap(
                icon_size,
                pixel_ratio,
                QIcon.Normal,
                QIcon.Off,
            )
            self._locked_icon_pixmap = resolved_icon.pixmap(
                icon_size,
                pixel_ratio,
                QIcon.Disabled,
                QIcon.Off,
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

    @Slot(bool)
    def set_action_enabled(self, enabled: bool) -> None:
        locked = not enabled
        self.setProperty("processingLocked", locked)
        self.setEnabled(enabled)
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
        if e.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.isEnabled():
            self.clicked.emit()
        else:
            super().keyPressEvent(e)


def make_button(
    layout: QVBoxLayout,
    action: QAction,
    icon_kind: str,
    *,
    label: str | None = None,
    center_content: bool = False,
) -> SidebarButton:
    btn = SidebarButton(
        action.objectName(),
        label if label is not None else action.text(),
        sidebar_icon(icon_kind, ICON_PX),
        center_content=center_content,
    )
    btn.clicked.connect(action.trigger)
    action.enabledChanged.connect(btn.set_action_enabled)
    btn.set_action_enabled(action.isEnabled())
    layout.addWidget(btn)
    return btn


def make_section_label(
    text: str,
    parent: QWidget,
    *,
    centered: bool = False,
) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("SidebarSectionLabel")
    label.setProperty("centered", centered)
    apply_font_role(label, "sidebar_section")
    label.setMinimumHeight(SECTION_LABEL_MIN_HEIGHT)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    horizontal_alignment = Qt.AlignHCenter if centered else Qt.AlignLeft
    label.setAlignment(Qt.AlignVCenter | horizontal_alignment)
    return label


def _make_divider(parent: QWidget, object_name: str = "sidebar_divider") -> QFrame:
    divider = QFrame(parent)
    divider.setObjectName(object_name)
    divider.setFrameShape(QFrame.HLine)
    divider.setFixedHeight(1)
    return divider


def _add_tool_button(layout: QVBoxLayout, action: QAction, *, beta: bool = False) -> None:
    role = action.objectName()
    label = _TOOL_LABELS.get(role)
    button = make_button(layout, action, _TOOL_ICONS[role], label=label)
    if beta or label:
        title = action.text()
        button.setToolTip(f"{title} (Beta)" if beta else title)
        button.setAccessibleName(title)


def _add_tool_buttons(layout: QVBoxLayout, host) -> None:
    actions = host.shell_actions
    for action in actions.default_tools:
        _add_tool_button(layout, action)

    host.sidebar_beta_tools_divider = None
    host.sidebar_beta_tools_label = None
    if not actions.beta_tools:
        return

    layout.addSpacing(8)
    beta_divider = _make_divider(layout.parentWidget(), "sidebar_beta_tools_divider")
    layout.addWidget(beta_divider)
    host.sidebar_beta_tools_divider = beta_divider

    beta_label = make_section_label(
        "Beta Tools",
        layout.parentWidget(),
        centered=True,
    )
    beta_label.setProperty("sectionRole", "beta")
    layout.addWidget(beta_label)
    host.sidebar_beta_tools_label = beta_label

    for action in actions.beta_tools:
        _add_tool_button(layout, action, beta=True)


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

    primary_group = QWidget(sidebar)
    primary_group.setObjectName("sidebar_primary_group")
    primary_layout = QVBoxLayout(primary_group)
    primary_layout.setContentsMargins(0, 0, 0, 0)
    primary_layout.setSpacing(4)

    actions = self.shell_actions
    home_btn = make_button(
        primary_layout,
        actions.home,
        "home",
        center_content=True,
    )
    home_btn.setProperty("homeEntry", True)
    self.sidebar_home_button = home_btn

    primary_layout.addSpacing(8)
    primary_layout.addWidget(_make_divider(primary_group, "sidebar_home_divider"))
    primary_layout.addSpacing(8)

    tools_label = make_section_label("Quick Tools", primary_group, centered=True)
    primary_layout.addWidget(tools_label)
    self.sidebar_tools_label = tools_label

    tools_group = QWidget(primary_group)
    tools_group.setObjectName("sidebar_tools_group")
    tools_layout = QVBoxLayout(tools_group)
    tools_layout.setContentsMargins(0, 0, 0, 0)
    tools_layout.setSpacing(4)

    _add_tool_buttons(tools_layout, self)

    primary_layout.addWidget(tools_group)
    self.sidebar_tools_group = tools_group
    lay.addWidget(primary_group)

    lower_region = QWidget(sidebar)
    lower_region.setObjectName("sidebar_lower_region")
    lower_layout = QVBoxLayout(lower_region)
    lower_layout.setContentsMargins(0, 0, 0, 0)
    lower_layout.setSpacing(0)
    lower_layout.addStretch(1)

    utilities_group = QWidget(lower_region)
    utilities_group.setObjectName("sidebar_utilities_group")
    utilities_layout = QVBoxLayout(utilities_group)
    utilities_layout.setContentsMargins(0, 0, 0, 0)
    utilities_layout.setSpacing(4)
    utilities_layout.addWidget(_make_divider(utilities_group))
    utilities_layout.addSpacing(8)

    utility_label = make_section_label("Utilities", utilities_group)
    utilities_layout.addWidget(utility_label)
    self.sidebar_utilities_label = utility_label

    make_button(utilities_layout, actions.settings, "settings")
    make_button(utilities_layout, actions.documentation, "info")
    make_button(utilities_layout, actions.about, "help", label="Help")

    self.sidebar_utilities_group = utilities_group
    lower_layout.addWidget(utilities_group)
    lay.addWidget(lower_region, 1)

    home_btn.set_selected(True)
