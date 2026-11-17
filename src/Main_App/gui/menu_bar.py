from __future__ import annotations

from functools import partial

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
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

DOCS_URL = "https://zcm58.github.io/FPVS-Toolbox/"


def build_menu_bar(parent: QMainWindow) -> QMenuBar:
    """Return the app-level File, View, Tools, and Help menus."""
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

    library_action = view_menu.addAction("Experiment Library…")
    library_action.setObjectName("actionExperimentLibrary")

    def show_library() -> None:
        from Main_App.gui.experiment_library_workflow import show_experiment_library

        show_experiment_library(parent)

    library_action.triggered.connect(show_library)

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

    help_menu = menu_bar.addMenu("&Help")
    help_menu.setObjectName("helpMenu")
    help_menu.addAction(
        "Documentation", lambda: QDesktopServices.openUrl(QUrl(DOCS_URL)),
    )

    return menu_bar
