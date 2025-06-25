#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FPVS all-in-one toolbox using MNE-Python and CustomTkinter.

Version: 1.1.0

Key functionalities:

- Process and clean BioSemi datafiles from FPVS experiments. (.BDF Format)
- Allows the user to process one file at a time, or multiple files at once.

- Preprocessing Steps:

    - Imports the data and subtracts the average reference from the mastoid electrodes.
    - Downsamples the data to 256Hz if necessary.
    - Apply standard_1020 montage for channel locations.
    - Removes all channels except the 64 main electrodes.
    - Applies basic FIR bandpass filter.
    - Kurtosis-based channel rejection & interpolation.
    - Re-references to the average common reference.
    - Extracts each PsychoPy condition separately

- Extracts epochs based on numerical triggers from PsychoPy.
- Post-processing using FFT, SNR, Z-score, BCA computation.
- Saves Excel files with separate sheets per metric, named by condition label.

"""

# === Dependencies ===
import os
import queue
import tkinter as tk
from tkinter import messagebox
import webbrowser
import customtkinter as ctk
import requests
from packaging.version import parse as version_parse
from Main_App.menu_bar import AppMenuBar
from Main_App.ui_setup_panels import SetupPanelManager
from Main_App.ui_event_map_manager import EventMapManager
from Main_App.event_map_utils import EventMapMixin
from Main_App.file_selection import FileSelectionMixin
from Main_App.event_detection import EventDetectionMixin
from Main_App.validation_mixins import ValidationMixin
from Main_App.processing_utils import ProcessingMixin
from Main_App.logging_mixin import LoggingMixin
from Main_App import update_manager

from config import (
    FPVS_TOOLBOX_VERSION,
    FPVS_TOOLBOX_UPDATE_API,
    FPVS_TOOLBOX_REPO_PAGE,
    DEFAULT_STIM_CHANNEL
)

from Main_App.post_process import post_process as _external_post_process


# Advanced averaging UI and core function
from Tools.Average_Preprocessing import AdvancedAnalysisWindow

# Image resizer
from Tools.Image_Resizer import FPVSImageResizer

# Statistics toolbox
import Tools.Stats as stats
from Main_App.relevant_publications_window import RelevantPublicationsWindow
from Main_App.settings_manager import SettingsManager
from Main_App.settings_window import SettingsWindow
# =====================================================
# GUI Configuration (unchanged)
# =====================================================
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class FPVSApp(ctk.CTk, LoggingMixin, EventMapMixin, FileSelectionMixin,
              EventDetectionMixin, ValidationMixin, ProcessingMixin):

    """ Main application class replicating MATLAB FPVS analysis workflow using numerical triggers. """

    def __init__(self):
        super().__init__()

        update_manager.cleanup_old_executable()

        self.settings = SettingsManager()


        # --- App Version and Title ---
        from datetime import datetime
        self.title(f"FPVS Toolbox v{FPVS_TOOLBOX_VERSION} — {datetime.now():%Y-%m-%d}")
        self.minsize(750, 920)
        self.geometry(self.settings.get('gui', 'main_size', '750x920'))
        ctk.set_appearance_mode(self.settings.get('appearance', 'mode', 'System'))

        # Ensure the main window appears above other applications on launch
        self.lift()
        self.attributes('-topmost', True)
        self.after(0, lambda: self.attributes('-topmost', False))


        # --- Core State Variables ---
        self.busy = False
        self.preprocessed_data = {}
        self.event_map_entries = []
        self.data_paths = []
        self.processing_thread = None
        self.detection_thread = None
        self.gui_queue = queue.Queue()
        self._max_progress = 1
        self.validated_params = {}


        # --- Tkinter Variables for UI State ---
        self.file_mode = tk.StringVar(master=self, value="Single")
        self.file_type = tk.StringVar(master=self, value=".BDF")
        self.save_folder_path = tk.StringVar(master=self)
        # Save preprocessed FIF files by default
        self.save_fif_var = tk.BooleanVar(master=self, value=True)

        # --- Initialize Widget Attributes ---
        self.select_button = None
        self.select_output_button = None
        self.start_button = None
        self.options_frame = None
        self.radio_single = None
        self.radio_batch = None
        self.radio_bdf = None
        self.radio_set = None
        self.params_frame = None
        self.low_pass_entry = None
        self.high_pass_entry = None
        self.downsample_entry = None
        self.epoch_start_entry = None
        self.epoch_end_entry = None
        self.reject_thresh_entry = None
        self.ref_channel1_entry = None
        self.ref_channel2_entry = None
        self.max_idx_keep_entry = None
        self.max_bad_channels_alert_entry = None
        self.save_fif_checkbox = None
        self.event_map_outer_frame = None
        self.event_map_scroll_frame = None
        self.detect_button = None
        self.add_map_button = None
        self.log_text = None
        self.progress_bar = None
        self.menubar = None
        self.debug_label = None
        self.remaining_time_var = None
        self.remaining_time_label = None

        self._start_time = None
        self._processed_count = 0
        self._current_progress = 0.0
        self._target_progress = 0.0
        self._animating_progress = False

        # --- Register Validation Commands ---
        self.validate_num_cmd = (self.register(self._validate_numeric_input), '%P')
        self.validate_int_cmd = (self.register(self._validate_integer_input), '%P')

        # --- Build UI ---

        self.create_menu()
        self.create_widgets()  # This will call SetupPanelManager and EventMapManager
        self._apply_loaded_settings()


        # --- Initial UI State ---
        # The initial event map row is now added by EventMapManager._build_event_map_ui()
        # So, the explicit call to self.add_event_map_entry() is REMOVED from here.


        # --- Welcome and Logging ---
        self.log("Welcome to the FPVS Toolbox!")
        self.log(f"Appearance Mode: {ctk.get_appearance_mode()}")

        # --- Set Initial Focus ---
        # If EventMapManager's _add_new_event_row_ui focuses its new row,
        # this specific block might be redundant or could be generalized
        # to focus the main window or another element if no event map entries exist yet.
        # For now, let's keep it, as it checks winfo_exists().
        if self.event_map_entries:  # event_map_entries should be populated by EventMapManager by now
            try:
                first_entry_widgets = self.event_map_entries[0]
                if first_entry_widgets.get('label') and first_entry_widgets['label'].winfo_exists():
                    first_entry_widgets['label'].focus_set()
                    # self.app_ref.after(50, lambda: label_entry.select_range(0, tk.END)) # This was in EventMapManager, good there.
            except (IndexError, tk.TclError, AttributeError) as e:
                self.log(f"Warning: Could not set initial focus on event map label: {e}")
        else:
            self.log("No event map entries present after UI creation to set initial focus.")

        # --- Define List of Widgets to Toggle Enabled/Disabled State ---
        self._toggle_widgets = [
            self.select_button, self.select_output_button, self.start_button,
            self.radio_single, self.radio_batch, self.radio_bdf, self.radio_set,
            self.low_pass_entry, self.high_pass_entry, self.downsample_entry,
            self.epoch_start_entry, self.epoch_end_entry, self.reject_thresh_entry,
            self.ref_channel1_entry, self.ref_channel2_entry, self.max_idx_keep_entry,
            self.max_bad_channels_alert_entry, self.save_fif_checkbox,
            self.detect_button,
            self.add_map_button,
        ]
        self._toggle_widgets = [widget for widget in self._toggle_widgets if widget is not None]

        # Automatically check for updates without blocking the UI
        try:
            update_manager.check_for_updates_async(
                self, silent=False, notify_if_no_update=False
            )
        except Exception as e:
            self.log(f"Auto update check failed: {e}")

    def open_advanced_analysis_window(self):
        """Opens the Advanced Preprocessing Epoch Averaging window."""
        self.log("Opening Advanced Analysis (Preprocessing Epoch Averaging) tool...")
        self.debug("Advanced analysis window requested")
        # AdvancedAnalysisWindow is imported from Tools.Average_Preprocessing
        adv_win = AdvancedAnalysisWindow(master=self)
        adv_win.geometry(self.settings.get('gui', 'advanced_size', '1050x850'))

    def _set_controls_enabled(self, enabled: bool):
        """
        Enable or disable all main interactive widgets based on the `enabled` flag.
        """
        state = "normal" if enabled else "disabled"
        for w in self._toggle_widgets:
            try:
                w.configure(state=state)
            except Exception:
                pass
        self.update_idletasks()

    def open_stats_analyzer(self):
        """Opens the statistical analysis Toplevel window."""
        self.log("Opening Statistical Analysis tool...")  # Log the action
        self.debug("Stats window requested")

        # Get the last used output folder path from the main GUI's variable
        last_output_folder = self.save_folder_path.get()
        if not last_output_folder:
            self.log("No output folder previously set in main app. Stats tool will prompt user.")

        # Create an instance of the StatsAnalysisWindow from the imported module
        # Pass 'self' (the main FPVSApp instance) as the master window
        # Pass the folder path so the stats window can suggest it
        stats_win = stats.StatsAnalysisWindow(master=self, default_folder=last_output_folder)
        stats_win.geometry(self.settings.get('gui', 'stats_size', '950x950'))

    def open_image_resizer(self):
        """Open the FPVS Image_Resizer tool in a new CTkToplevel."""
        self.debug("Image resizer window requested")
        # We pass `self` so the new window is a child of the main app:
        win = FPVSImageResizer(self)
        win.geometry(self.settings.get('gui', 'resizer_size', '800x600'))


    # --- Menu Methods ---
    def create_menu(self):
        """
        Creates the main application menubar by instantiating and using
        the AppMenuBar class from Main_App.menu_bar.
        """
        # Create the top-level menu bar widget itself, attached to the main window (self)
        self.menubar = tk.Menu(self)

        # Instantiate our AppMenuBar handler, passing a reference to this FPVSApp instance (self).
        # The AppMenuBar class will use this reference to call back to methods
        # in FPVSApp (like self.quit, self.open_stats_analyzer, etc.)
        menu_manager = AppMenuBar(app_reference=self)

        # Ask the menu_manager instance to populate our menubar widget.
        # The populate_menu method in AppMenuBar will add all the cascades (File, Tools, etc.)
        # and commands to self.menubar.
        menu_manager.populate_menu(self.menubar)

        # Configure the main window (self, which is the CTk instance) to use this menubar.
        self.config(menu=self.menubar)

    # Note: All the methods that are actual commands for the menu items, such as:
    #   - set_appearance_mode(self, mode)
    #   - check_for_updates(self)
    #   - quit(self)
    #   - open_stats_analyzer(self)
    #   - open_image_resizer(self)
    #   - show_about_dialog(self)
    #   - open_advanced_analysis_window(self) (the new one we discussed)
    # ...should REMAIN as methods within this FPVSApp class because AppMenuBar
    # calls them via `self.app_ref.method_name()`.


    def check_for_updates(self):
        """
        Checks the FPVS_TOOLBOX_UPDATE_API on github for the latest version.
        If the version on Github is newer than FPVS_TOOLBOX_VERSION,
        The user is prompted to download the new version.

        If the user is using a NEWER version than what is available on Github (a beta release, for example),
        they will NOT be prompted to update their app. This works based on semantic versioning.

        """
        self.log("Checking for updates...")
        try:
            resp = requests.get(FPVS_TOOLBOX_UPDATE_API, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            latest = data.get("tag_name") or data.get("version")
            if not latest:
                raise ValueError("No version field in update response.")
            current = version_parse(FPVS_TOOLBOX_VERSION)
            remote = version_parse(latest.lstrip("v"))
            if remote > current:
                if messagebox.askyesno(
                        "Update Available",
                        f"A new version ({latest}) is available.\n"
                        f"You have {FPVS_TOOLBOX_VERSION}.\n\n"
                        "Would you like to open the release page?"
                ):
                    webbrowser.open(FPVS_TOOLBOX_REPO_PAGE)
            else:
                messagebox.showinfo(
                    "Up to Date",
                    f"You are running the latest version ({FPVS_TOOLBOX_VERSION})."
                )
            self.log("Update check complete.")
        except Exception as e:
            self.log(f"Update check failed: {e}")
            messagebox.showwarning(
                "Update Check Failed",
                f"Could not check for updates:\n{e}"
            )

    def set_appearance_mode(self, mode):
        self.log(f"Setting appearance mode to: {mode}")
        ctk.set_appearance_mode(mode)

    def show_about_dialog(self):
        messagebox.showinfo(
            "About FPVS ToolBox",
            f"Version: {FPVS_TOOLBOX_VERSION} was developed by Zack Murphy at Mississippi State University."
        )

    def show_relevant_publications(self):
        """Display a window with supporting literature."""
        win = RelevantPublicationsWindow(self)
        win.geometry("600x600")

    def quit(self):
        if (self.processing_thread and self.processing_thread.is_alive()) or \
           (self.detection_thread and self.detection_thread.is_alive()):
            if messagebox.askyesno("Exit Confirmation", "Processing or detection ongoing. Stop and exit?"):
                self.destroy()
        else:
            self.destroy()


    # --- Validation Methods ---
    def _validate_numeric_input(self, P):
        if P == "" or P == "-":
            return True
        try:
            float(P)
            return True
        except ValueError:
            self.bell()
            return False

    def _validate_integer_input(self, P):
        if P == "":
            return True
        try:
            int(P)
            return True
        except ValueError:
            self.bell()
            return False

    # --- GUI Creation ---

    def create_widgets(self):
        """Creates all the widgets for the main application window,
        delegating panel creation to respective managers."""


        # Attempt to import UI constants from config, with fallbacks
        try:
            from config import PAD_X, PAD_Y, CORNER_RADIUS
            # LABEL_ID_ENTRY_WIDTH is now primarily used within EventMapManager
        except ImportError:
            PAD_X = 5
            PAD_Y = 5
            CORNER_RADIUS = 6
            print("Warning [FPVSApp.create_widgets]: Could not import UI constants from config. Using fallbacks.")

        # Main container
        main_frame = ctk.CTkFrame(self, corner_radius=0)
        main_frame.pack(fill="both", expand=True, padx=PAD_X * 2, pady=PAD_Y * 2)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(0, weight=0)  # Top Bar
        main_frame.grid_rowconfigure(1, weight=0)  # Options Panel (created by SetupPanelManager)
        main_frame.grid_rowconfigure(2, weight=0)  # Params Panel (created by SetupPanelManager)
        main_frame.grid_rowconfigure(3, weight=1)  # Event Map Frame (content by EventMapManager, expands)
        main_frame.grid_rowconfigure(4, weight=0)  # Bottom Frame (Log/Progress)

        # --- Top Control Bar (Row 0) ---
        top_bar = ctk.CTkFrame(main_frame, corner_radius=0)
        top_bar.grid(row=0, column=0, sticky="ew", padx=PAD_X, pady=PAD_Y)
        top_bar.grid_columnconfigure(0, weight=0)  # Select button
        top_bar.grid_columnconfigure(1, weight=1)  # Output folder button (centered)
        top_bar.grid_columnconfigure(2, weight=0)  # Start button
        top_bar.grid_columnconfigure(3, weight=0)  # Debug label

        self.select_button = ctk.CTkButton(top_bar, text="Select EEG File…",
                                           command=self.select_data_source,
                                           corner_radius=CORNER_RADIUS, width=180)
        self.select_button.grid(row=0, column=0, sticky="w", padx=(0, PAD_X))

        # self.save_folder_path (StringVar) should be initialized in FPVSApp.__init__
        self.select_output_button = ctk.CTkButton(top_bar, text="Select Output Folder…",
                                                  command=self.select_save_folder,
                                                  corner_radius=CORNER_RADIUS, width=180)
        self.select_output_button.grid(row=0, column=1, sticky="", padx=PAD_X)

        self.start_button = ctk.CTkButton(top_bar, text="Start Processing",
                                          command=self.start_processing,
                                          corner_radius=CORNER_RADIUS, width=180,
                                          font=ctk.CTkFont(weight="bold"))
        self.start_button.grid(row=0, column=2, sticky="e", padx=(PAD_X, 0))

        if self.settings.debug_enabled():
            self.debug_label = ctk.CTkLabel(top_bar, text="DEBUG MODE ENABLED", text_color="red")
            self.debug_label.grid(row=0, column=3, padx=(PAD_X, 0))

        # --- Create Setup Panels using SetupPanelManager ---
        # (Options Panel on row=1, Params Panel on row=2, inside main_frame)
        setup_panel_handler = SetupPanelManager(app_reference=self, main_parent_frame=main_frame)
        setup_panel_handler.create_all_setup_panels()

        # --- Event ID Mapping Frame (Row 3 - EXPANDS) ---
        # Create the outer container frame that will be passed to EventMapManager
        self.event_map_outer_frame = ctk.CTkFrame(main_frame)
        self.event_map_outer_frame.grid(row=3, column=0, sticky="nsew", padx=PAD_X, pady=PAD_Y)
        # EventMapManager will configure the grid inside self.event_map_outer_frame
        # and populate self.event_map_scroll_frame, self.detect_button, self.add_map_button

        # Instantiate EventMapManager to build the event map UI
        # The EventMapManager's __init__ calls its _build_event_map_ui method,
        # which now also adds the initial event map row.
        EventMapManager(app_reference=self, parent_ui_frame=self.event_map_outer_frame)
        # No further calls to event_map_manager needed here if its __init__ builds the UI.

        # --- Bottom Frame: Log & Progress (Row 4) ---
        bottom_frame = ctk.CTkFrame(main_frame)
        bottom_frame.grid(row=4, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, 0))
        bottom_frame.grid_columnconfigure(0, weight=1)

        log_outer = ctk.CTkFrame(bottom_frame)
        log_outer.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, PAD_Y))
        log_outer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_outer, text="Log", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=PAD_X, pady=(PAD_Y, 0))
        self.log_text = ctk.CTkTextbox(log_outer, height=100, wrap="word", state="disabled",
                                       corner_radius=CORNER_RADIUS)
        self.log_text.grid(row=1, column=0, sticky="ew", padx=PAD_X, pady=(0, PAD_Y))

        prog_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        prog_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=PAD_Y)
        prog_frame.grid_columnconfigure(0, weight=1)

        self.remaining_time_var = tk.StringVar(value="")
        self.remaining_time_label = ctk.CTkLabel(prog_frame, textvariable=self.remaining_time_var)
        self.remaining_time_label.grid(row=0, column=0, sticky="w", padx=0, pady=(0, 2))

        self.progress_bar = ctk.CTkProgressBar(
            prog_frame, orientation="horizontal", height=20,
            progress_color="#4caf50"
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=0, pady=0)
        self.progress_bar.set(0)

        # Sync select button label initially
        if hasattr(self, 'update_select_button_text'):
            self.update_select_button_text()

    # Override to use external function
    def post_process(self, condition_labels_present):
        _external_post_process(self, condition_labels_present)

    def _apply_loaded_settings(self):
        """Apply saved preferences to the GUI on startup."""
        # Default directories
        data_folder = self.settings.get('paths', 'data_folder', '')
        if data_folder and os.path.isdir(data_folder):
            self.log(f"Default data folder loaded: {data_folder}")
            self.data_paths = [data_folder]

        out_folder = self.settings.get('paths', 'output_folder', '')
        if out_folder and os.path.isdir(out_folder):
            self.save_folder_path.set(out_folder)

        # Event map defaults
        pairs = self.settings.get_event_pairs()
        # Clear any existing rows without auto-adding a blank one
        self.clear_event_map_entries()
        if pairs:
            for label, id_val in pairs:
                self.add_event_map_entry()
                row = self.event_map_entries[-1]
                row['label'].insert(0, label)
                row['id'].insert(0, id_val)
        else:
            # Ensure at least one empty row is present
            self.add_event_map_entry()

        # Stim channel override
        global DEFAULT_STIM_CHANNEL
        DEFAULT_STIM_CHANNEL = self.settings.get('stim', 'channel', DEFAULT_STIM_CHANNEL)

    def open_settings_window(self):
        SettingsWindow(self, self.settings)
