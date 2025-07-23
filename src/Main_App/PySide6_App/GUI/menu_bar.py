from __future__ import annotations
from PySide6.QtWidgets import QMenuBar, QMainWindow
from PySide6.QtGui    import QAction
from Main_App.Legacy_App.eloreta_launcher import open_eloreta_tool

def build_menu_bar(parent: QMainWindow) -> QMenuBar:
    """
    Returns a QMenuBar with File, Tools, and Help menus.
    """
    menu_bar = QMenuBar(parent)

    # File
    file_menu = menu_bar.addMenu("File")
    file_menu.setObjectName("fileMenu")
    for text, slot in [
        ("Settings",         parent.open_settings_window),
        ("Check for Updates", parent.check_for_updates),
        ("Exit",              parent.quit),
    ]:
        action = QAction(text, parent)
        action.triggered.connect(slot)
        file_menu.addAction(action)
        file_menu.addSeparator()
    file_menu.removeAction(file_menu.actions()[-1])  # drop trailing separator

    # Tools
    tools_menu = menu_bar.addMenu("Tools")
    items = [
        ("Stats Toolbox",                              parent.open_stats_analyzer),
        ("Source Localization (eLORETA/sLORETA)",      lambda: open_eloreta_tool(parent)),
        ("Image Resizer",                              parent.open_image_resizer),
        ("Generate SNR Plots",                         parent.open_plot_generator),
        ("Average Epochs in Pre-Processing Phase",     parent.open_advanced_analysis_window),
    ]
    for text, slot in items:
        action = QAction(text, parent)
        action.triggered.connect(slot)
        tools_menu.addAction(action)
        tools_menu.addSeparator()
    tools_menu.removeAction(tools_menu.actions()[-1])

    # Help
    help_menu = menu_bar.addMenu("Help")
    for text, slot in [
        ("Relevant Publications", parent.show_relevant_publications),
        ("About…",                parent.show_about_dialog),
    ]:
        action = QAction(text, parent)
        action.triggered.connect(slot)
        help_menu.addAction(action)
        help_menu.addSeparator()
    help_menu.removeAction(help_menu.actions()[-1])

    return menu_bar
