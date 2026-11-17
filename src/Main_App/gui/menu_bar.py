from __future__ import annotations

from functools import partial

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenuBar, QMainWindow

# Role, label, and MainWindow opener, in menu order.
DEFAULT_TOOL_SPECS = (
    ("btn_free_harmonic_clustering", "Free Harmonic Clustering Analysis", "open_free_harmonic_clustering"),
    ("btn_graphs", "SNR Plots", "open_plot_generator"),
)

BETA_TOOL_SPECS = (
    ("btn_publication_maps", "Scalp Maps", "open_publication_maps"),
    ("btn_data", "Standard FPVS Screening", "open_stats_analyzer"),
    ("btn_sensitivity_analysis", "Sensitivity Analysis", "open_sensitivity_analysis"),
    ("btn_loreta_visualizer", "LORETA Visualizer", "open_loreta_visualizer"),
    ("btn_sequence_figure", "Sequence Figure", "open_sequence_figure"),
    ("btn_individual_detectability", "Individual Detectability", "open_individual_detectability"),
)


def build_menu_bar(parent: QMainWindow) -> QMenuBar:
    """Return the app-level File, View, and Tools menus."""
    menu_bar = QMenuBar(parent)
    menu_bar.setObjectName("workspaceMenuBar")
    menu_bar.setNativeMenuBar(False)

    file_menu = menu_bar.addMenu("&File")
    file_menu.setObjectName("fileMenu")

    view_menu = menu_bar.addMenu("&View")
    view_menu.setObjectName("viewMenu")
    home_action = view_menu.addAction("Home")
    home_action.setObjectName("btn_home")
    home_action.setShortcut(QKeySequence("Ctrl+1"))
    parent.addAction(home_action)

    def show_home() -> None:
        if menu_bar.isVisible() and menu_bar.isEnabled():
            parent.show_home_page()

    home_action.triggered.connect(show_home)

    tools_menu = menu_bar.addMenu("&Tools")
    tools_menu.setObjectName("toolsMenu")
    parent.tool_actions = {}
    for role, text, opener_name in DEFAULT_TOOL_SPECS:
        action = QAction(text, parent)
        action.setObjectName(role)
        action.triggered.connect(getattr(parent, opener_name))
        tools_menu.addAction(action)
        parent.tool_actions[role] = action

    if parent.settings.beta_tools_enabled():
        tools_menu.addSeparator()
        beta_menu = tools_menu.addMenu("Beta Tools")
        beta_menu.setObjectName("betaToolsMenu")
        for role, text, opener_name in BETA_TOOL_SPECS:
            action = QAction(text, parent)
            action.setObjectName(role)
            action.triggered.connect(
                partial(parent._open_beta_tool, role, getattr(parent, opener_name))
            )
            beta_menu.addAction(action)
            parent.tool_actions[role] = action

    return menu_bar
