# src/Main_App/menu_bar.py
# -*- coding: utf-8 -*-
"""
Handles the creation and command linking for the main application menu bar
of the FPVS Toolbox.
"""
import tkinter as tk
# Note: Other imports like webbrowser, messagebox, etc., are not needed here
# if the command methods themselves remain in the main FPVSApp class.

class AppMenuBar:
    def __init__(self, app_reference):
        """
        Initializes the AppMenuBar.

        Args:
            app_reference: A reference to the main FPVSApp instance.
                           This allows menu commands to call methods on the main app.
        """
        self.app_ref = app_reference

    def populate_menu(self, menubar_widget):
        """
        Creates and populates the menu bar structure onto the provided menubar_widget.

        Args:
            menubar_widget: The tk.Menu widget created in the main app
                            (e.g., self.menubar in FPVSApp).
        """
        # === File menu ===
        file_menu = tk.Menu(menubar_widget, tearoff=0)
        menubar_widget.add_cascade(label="File", menu=file_menu)

        file_menu.add_command(label="Settings", command=self.app_ref.open_settings_window)

        file_menu.add_separator()
        file_menu.add_command(label="Check for Updates", command=self.app_ref.check_for_updates)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.app_ref.quit) # Calls quit method on main app

        # === Tools menu ===
        tools_menu = tk.Menu(menubar_widget, tearoff=0)
        menubar_widget.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Stats Toolbox", command=self.app_ref.open_stats_analyzer)
        tools_menu.add_separator()
        tools_menu.add_command(label="Image_Resizer", command=self.app_ref.open_image_resizer)
        tools_menu.add_separator()
        tools_menu.add_command(
            label="Average Epochs in Pre-Processing Phase",
            command=self.app_ref.open_advanced_analysis_window,
        )

        # === Help menu ===
        help_menu = tk.Menu(menubar_widget, tearoff=0)
        menubar_widget.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About...", command=self.app_ref.show_about_dialog)
