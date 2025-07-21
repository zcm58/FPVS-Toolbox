"""Menu bar creation utilities for the FPVS Toolbox main window."""

from __future__ import annotations

from PySide6.QtWidgets import QAction, QMainWindow, QMenu, QMenuBar

__all__ = ["build_menu_bar"]


def build_menu_bar(parent: QMainWindow) -> QMenuBar:
    """Create and return the application's menu bar.

    Parameters
    ----------
    parent : QMainWindow
        Main window that will own the returned :class:`QMenuBar`.

    Returns
    -------
    QMenuBar
        The fully constructed menu bar with File, Tools and Help menus.
    """
    menu_bar = QMenuBar(parent)
    parent.setMenuBar(menu_bar)

    # === File menu ===
    file_menu = QMenu("File", menu_bar)
    menu_bar.addMenu(file_menu)

    file_menu.addAction(QAction("Settings", parent))
    file_menu.addSeparator()
    file_menu.addAction(QAction("Check for Updates", parent))
    file_menu.addSeparator()
    file_menu.addAction(QAction("Exit", parent))

    # === Tools menu ===
    tools_menu = QMenu("Tools", menu_bar)
    menu_bar.addMenu(tools_menu)

    tools_menu.addAction(QAction("Stats Toolbox", parent))
    tools_menu.addSeparator()
    tools_menu.addAction(QAction("Source Localization (eLORETA/sLORETA)", parent))
    tools_menu.addSeparator()
    tools_menu.addAction(QAction("Image Resizer", parent))
    tools_menu.addSeparator()
    tools_menu.addAction(QAction("Generate SNR Plots", parent))
    tools_menu.addSeparator()
    tools_menu.addAction(QAction("Average Epochs in Pre-Processing Phase", parent))

    # === Help menu ===
    help_menu = QMenu("Help", menu_bar)
    menu_bar.addMenu(help_menu)

    help_menu.addAction(QAction("Relevant Publications", parent))
    help_menu.addSeparator()
    help_menu.addAction(QAction("About...", parent))

    return menu_bar
