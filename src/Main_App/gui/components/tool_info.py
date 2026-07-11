"""Shared single-page and tabbed tool information dialog helpers."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QWidget,
)

from Main_App.gui.icons import tool_info_icon

from .surfaces import AppDialog, SurfaceSize

DEFAULT_TOOL_INFO_SIZE = SurfaceSize(width=620, height=520, min_width=460, min_height=360)


@dataclass(frozen=True)
class ToolInfoTab:
    """One named HTML page in a tabbed tool-information dialog."""

    key: str
    title: str
    html: str


@dataclass(frozen=True)
class ToolInfoContent:
    """Editable user-facing information shown by a shared modal shell.

    When ``tabs`` is non-empty, the tab content takes precedence over ``html``.
    """

    key: str
    title: str
    html: str = ""
    size: SurfaceSize = DEFAULT_TOOL_INFO_SIZE
    tabs: tuple[ToolInfoTab, ...] = ()


class ToolInfoDialog(AppDialog):
    """Read-only HTML dialog for short tool descriptions."""

    def __init__(
        self,
        content: ToolInfoContent,
        parent: QWidget | None = None,
        *,
        browser_object_name: str | None = None,
    ) -> None:
        super().__init__(content.title, parent, size=content.size)
        self.setObjectName(f"{content.key}_tool_info_dialog")

        self.tab_widget: QTabWidget | None = None
        self.browsers: tuple[QTextBrowser, ...]
        if content.tabs:
            tab_widget = QTabWidget(self)
            tab_widget.setObjectName(f"{content.key}_tool_info_tabs")
            browsers: list[QTextBrowser] = []
            for index, tab in enumerate(content.tabs):
                browser = QTextBrowser(tab_widget)
                object_name = (
                    browser_object_name
                    if index == 0 and browser_object_name
                    else f"{content.key}_tool_info_{tab.key}_browser"
                )
                browser.setObjectName(object_name)
                browser.setOpenExternalLinks(True)
                browser.setHtml(tab.html)
                tab_widget.addTab(browser, tab.title)
                browsers.append(browser)
            self.root_layout.addWidget(tab_widget, 1)
            self.tab_widget = tab_widget
            self.browsers = tuple(browsers)
            self.browser = self.browsers[0]
        else:
            browser = QTextBrowser(self)
            browser.setObjectName(
                browser_object_name or f"{content.key}_tool_info_browser"
            )
            browser.setOpenExternalLinks(True)
            browser.setHtml(content.html)
            self.root_layout.addWidget(browser, 1)
            self.browsers = (browser,)
            self.browser = browser

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.setObjectName(f"{content.key}_tool_info_buttons")
        buttons.rejected.connect(self.reject)
        self.root_layout.addWidget(buttons)


def make_info_button(
    *,
    parent: QWidget | None = None,
    tooltip: str = "About this tool",
    object_name: str | None = None,
    size: int = 20,
) -> QToolButton:
    """Create the standard compact information icon button."""
    button = QToolButton(parent)
    if object_name:
        button.setObjectName(object_name)
    button.setIcon(tool_info_icon(size))
    button.setIconSize(QSize(size, size))
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setAccessibleDescription("Open a short information dialog about this tool.")
    button.setCursor(Qt.PointingHandCursor)
    button.setProperty("compact", True)
    button.setProperty("iconButton", True)
    return button


def show_tool_info(parent: QWidget | None, content: ToolInfoContent) -> int:
    """Open a shared modal information dialog for a tool."""
    dialog = ToolInfoDialog(content, parent)
    return int(dialog.exec())
