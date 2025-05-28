#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FPVS all-in-one toolbox using MNE-Python and CustomTkinter.

Version: 0.9.1 (May 2025) - the main app file (fpvs_app.py) has been refactored to remove roughly
350 lines of code in an effort to simplify future development.

Removed lines of code will be placed into new files under the Main_App package.


Key functionalities:

- Process BioSemi datafiles. (.BDF Format)
- Allows the user to process one file at a time, or multiple files at once.

- Preprocessing Steps:

    - Imports the data and subtracts the average reference from the mastoid electrodes.
    - Downsamples the data to 256Hz if necessary.
    - Apply standard_1020 montage for channel locations.
    - Removes all channels except the 64 main electrodes.
    - Applies basic FIR bandpass filter.
    - Kurtosis-based channel rejection & interpolation.
    - Re-references to the average common reference.
    - Extracts each PsychoPy condition separately.

- Extracts epochs based on numerical triggers from PsychoPy.
- Post-processing using FFT, SNR, Z-score, BCA computation.
- Saves Excel files with separate sheets per metric, named by condition label.

"""

# === Dependencies ===
import os
import glob
import threading
import queue
import traceback
import gc
import tkinter as tk
from tkinter import filedialog, messagebox
import webbrowser
import numpy as np
import pandas as pd
import customtkinter as ctk
import mne
import requests
from packaging.version import parse as version_parse
from typing import Optional, Dict, Any  # Add any other type hints you use, like List
from Main_App.menu_bar import AppMenuBar
from Main_App.eeg_preprocessing import perform_preprocessing
from Main_App.ui_setup_panels import SetupPanelManager

from config import (
    FPVS_TOOLBOX_VERSION,
    FPVS_TOOLBOX_UPDATE_API,
    FPVS_TOOLBOX_REPO_PAGE,
    DEFAULT_STIM_CHANNEL,
    CORNER_RADIUS,
    PAD_X
)
from post_process import post_process as _external_post_process

# Advanced averaging UI and core function
from Tools.Average_Preprocessing import AdvancedAnalysisWindow
from Tools.Average_Preprocessing import run_advanced_averaging_processing

# Image resizer
from Tools.Image_Resizer import FPVSImageResizer

# Statistics toolbox
import Tools.Stats as stats
# =====================================================
# GUI Configuration (unchanged)
# =====================================================
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class FPVSApp(ctk.CTk):
    """ Main application class replicating MATLAB FPVS analysis workflow using numerical triggers. """

    def __init__(self):
        super().__init__()

        # --- App Version and Title ---
        from datetime import datetime
        self.title(f"FPVS Toolbox v{FPVS_TOOLBOX_VERSION} — {datetime.now():%Y-%m-%d}")
        self.minsize(750, 920)  # Adjusted height slightly as params panel is shorter

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

        # --- Tkinter Variables for UI State (used by SetupPanelManager and other parts) ---
        # self.save_preprocessed tk.BooleanVar is REMOVED
        self.file_mode = tk.StringVar(master=self, value="Single")
        self.file_type = tk.StringVar(master=self, value=".BDF")
        self.save_folder_path = tk.StringVar(master=self)

        # --- Initialize Widget Attributes ---
        # Top bar
        self.select_button = None
        self.select_output_button = None
        self.start_button = None
        # Options Panel
        self.options_frame = None
        self.radio_single = None
        self.radio_batch = None
        self.radio_bdf = None
        self.radio_set = None
        # Params Panel
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
        # self.stim_channel_entry = None # REMOVED FROM UI
        self.max_bad_channels_alert_entry = None  # This one STAYS
        # self.save_preprocessed_checkbox = None # REMOVED FROM UI
        # Event Map
        self.event_map_scroll_frame = None
        self.detect_button = None
        self.add_map_button = None
        # Log/Progress
        self.log_text = None
        self.progress_bar = None
        self.menubar = None

        # --- Register Validation Commands ---
        self.validate_num_cmd = (self.register(self._validate_numeric_input), '%P')
        self.validate_int_cmd = (self.register(self._validate_integer_input), '%P')

        # --- Build UI ---
        self.create_menu()
        self.create_widgets()

        # --- Initial UI State ---
        self.add_event_map_entry()

        # --- Welcome and Logging ---
        self.log("Welcome to the FPVS Toolbox!")
        self.log(f"Appearance Mode: {ctk.get_appearance_mode()}")

        # --- Set Initial Focus ---
        if self.event_map_entries:
            try:
                first_entry_widgets = self.event_map_entries[0]
                if first_entry_widgets['frame'].winfo_exists() and \
                        first_entry_widgets['label'].winfo_exists():
                    first_entry_widgets['label'].focus_set()
            except Exception as e:
                self.log(f"Warning: Could not set initial focus on event map: {e}")

        # --- Define List of Widgets to Toggle Enabled/Disabled State ---
        self._toggle_widgets = [
            self.select_button, self.select_output_button, self.start_button,
            self.radio_single, self.radio_batch, self.radio_bdf, self.radio_set,
            self.low_pass_entry, self.high_pass_entry, self.downsample_entry,
            self.epoch_start_entry, self.epoch_end_entry, self.reject_thresh_entry,
            self.ref_channel1_entry, self.ref_channel2_entry, self.max_idx_keep_entry,
            # self.stim_channel_entry, # REMOVED
            self.max_bad_channels_alert_entry,  # STAYS
            # self.save_preprocessed_checkbox, # REMOVED
            self.detect_button, self.add_map_button,
        ]
        self._toggle_widgets = [widget for widget in self._toggle_widgets if widget is not None]

    def open_advanced_analysis_window(self):
        """Opens the Advanced Preprocessing Epoch Averaging window."""
        self.log("Opening Advanced Analysis (Preprocessing Epoch Averaging) tool...")
        # AdvancedAnalysisWindow is imported from Tools.Average_Preprocessing
        adv_win = AdvancedAnalysisWindow(master=self)
        adv_win.grab_set()  # Make it modal

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

        # Get the last used output folder path from the main GUI's variable
        last_output_folder = self.save_folder_path.get()
        if not last_output_folder:
            self.log("No output folder previously set in main app. Stats tool will prompt user.")

        # Create an instance of the StatsAnalysisWindow from the imported module
        # Pass 'self' (the main FPVSApp instance) as the master window
        # Pass the folder path so the stats window can suggest it
        stats_win = stats.StatsAnalysisWindow(master=self, default_folder=last_output_folder)

        # Make the stats window modal (user must close it before using main window)
        stats_win.grab_set()

    def open_image_resizer(self):
        """Open the FPVS Image_Resizer tool in a new CTkToplevel."""
        # We pass `self` so the new window is a child of the main app:
        win = FPVSImageResizer(self)
        win.grab_set()  # optional: make it modal


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
            f"Version: 0.9.1 was developed by Zack Murphy at Mississippi State University."
        )

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
        """Creates all the widgets for the main application window, delegating panel creation."""

        # Constants for padding (can also be from config)
        PAD_X = 5 # Assuming PAD_X is from global scope or config
        PAD_Y = 5 # Assuming PAD_Y is from global scope or config
        # LABEL_ID_ENTRY_WIDTH = 100 # Assuming this is from global/config for event_map_headers

        # Main container
        main_frame = ctk.CTkFrame(self, corner_radius=0)
        main_frame.pack(fill="both", expand=True, padx=PAD_X * 2, pady=PAD_Y * 2)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(0, weight=0)  # Top Bar
        main_frame.grid_rowconfigure(1, weight=0)  # Options Panel (created by manager)
        main_frame.grid_rowconfigure(2, weight=0)  # Params Panel (created by manager)
        main_frame.grid_rowconfigure(3, weight=1)  # Event Map (expands)
        main_frame.grid_rowconfigure(4, weight=0)  # Bottom (Log/Progress)

        # --- Top Control Bar (Row 0) ---
        # (This section remains the same as your current create_widgets)
        top_bar = ctk.CTkFrame(main_frame, corner_radius=0)
        top_bar.grid(row=0, column=0, sticky="ew", padx=PAD_X, pady=PAD_Y)
        top_bar.grid_columnconfigure(0, weight=0)
        top_bar.grid_columnconfigure(1, weight=1)
        top_bar.grid_columnconfigure(2, weight=0)

        self.select_button = ctk.CTkButton(top_bar, text="Select EEG File…",
                                           command=self.select_data_source,
                                           corner_radius=CORNER_RADIUS, width=180)
        self.select_button.grid(row=0, column=0, sticky="w", padx=(0, PAD_X))

        # self.save_folder_path should be initialized in __init__
        self.select_output_button = ctk.CTkButton(top_bar, text="Select Output Folder…",
                                                  command=self.select_save_folder,
                                                  corner_radius=CORNER_RADIUS, width=180)
        self.select_output_button.grid(row=0, column=1, sticky="", padx=PAD_X)

        self.start_button = ctk.CTkButton(top_bar, text="Start Processing",
                                          command=self.start_processing,
                                          corner_radius=CORNER_RADIUS, width=180,
                                          font=ctk.CTkFont(weight="bold"))
        self.start_button.grid(row=0, column=2, sticky="e", padx=(PAD_X, 0))

        # --- Create Setup Panels using the Manager ---
        # The SetupPanelManager will create self.options_frame (gridded at row=1)
        # and self.params_frame (gridded at row=2) within main_frame.
        setup_panel_handler = SetupPanelManager(app_reference=self, main_parent_frame=main_frame)
        setup_panel_handler.create_all_setup_panels()  # This populates the frames and widgets

        # --- Event ID Mapping Frame (Row 3 - EXPANDS) ---
        # (This section remains the same as your current create_widgets)
        event_map_outer = ctk.CTkFrame(main_frame)  # This will be parent for EventMapManager later
        event_map_outer.grid(row=3, column=0, sticky="nsew", padx=PAD_X, pady=PAD_Y)
        event_map_outer.grid_columnconfigure(0, weight=1)
        event_map_outer.grid_rowconfigure(2, weight=1)  # Scrollable frame's row

        ctk.CTkLabel(event_map_outer, text="Event Map (Condition Label → Numerical ID)",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=PAD_X, pady=(PAD_Y, 0))  # Changed to pack

        header_frame = ctk.CTkFrame(event_map_outer, fg_color="transparent")
        header_frame.pack(fill="x", padx=PAD_X, pady=(2, 0))  # Changed to pack

        # Assuming LABEL_ID_ENTRY_WIDTH and PAD_X are accessible (e.g., imported from config or defined globally)
        # If not, pass them or use default values. For now, assuming they are available.
        try:
            from config import LABEL_ID_ENTRY_WIDTH  # Local import just for this section if preferred
        except:
            LABEL_ID_ENTRY_WIDTH = 100

        ctk.CTkLabel(header_frame, text="Condition Label", width=LABEL_ID_ENTRY_WIDTH * 2 + PAD_X, anchor="w").pack(
            side="left", padx=(0, 0))
        ctk.CTkLabel(header_frame, text="Numerical ID", width=LABEL_ID_ENTRY_WIDTH + PAD_X, anchor="w").pack(
            side="left", padx=(0, 0))
        ctk.CTkLabel(header_frame, text="", width=28 + PAD_X).pack(side="right", padx=(0, 0))  # Spacer

        self.event_map_scroll_frame = ctk.CTkScrollableFrame(event_map_outer, label_text="")
        self.event_map_scroll_frame.pack(fill="both", expand=True, padx=PAD_X, pady=(0, PAD_Y))  # Changed to pack

        event_map_button_frame = ctk.CTkFrame(event_map_outer, fg_color="transparent")
        event_map_button_frame.pack(fill="x", pady=(0, PAD_Y), padx=PAD_X)  # Changed to pack
        self.detect_button = ctk.CTkButton(event_map_button_frame, text="Detect Trigger IDs",
                                           command=self.detect_and_show_event_ids, corner_radius=CORNER_RADIUS)
        self.detect_button.pack(side="left", padx=(0, PAD_X))
        self.add_map_button = ctk.CTkButton(event_map_button_frame, text="+ Add Condition",
                                            command=self.add_event_map_entry, corner_radius=CORNER_RADIUS)
        self.add_map_button.pack(side="left")

        # --- Bottom Frame: Log & Progress (Row 4) ---
        # (This section remains the same as your current create_widgets)
        bottom_frame = ctk.CTkFrame(main_frame)
        bottom_frame.grid(row=4, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, 0))
        bottom_frame.grid_columnconfigure(0, weight=1)

        log_outer = ctk.CTkFrame(bottom_frame)
        log_outer.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, PAD_Y))
        log_outer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_outer, text="Log", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w",
                                                                                  padx=PAD_X, pady=(PAD_Y, 0))
        self.log_text = ctk.CTkTextbox(log_outer, height=100, wrap="word", state="disabled",
                                       corner_radius=CORNER_RADIUS)
        self.log_text.grid(row=1, column=0, sticky="ew", padx=PAD_X, pady=(0, PAD_Y))

        prog_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        prog_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=PAD_Y)
        prog_frame.grid_columnconfigure(0, weight=1)
        self.progress_bar = ctk.CTkProgressBar(prog_frame, orientation="horizontal", height=20)
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=0, pady=0);
        self.progress_bar.set(0)

        # Sync select button label initially
        if hasattr(self, 'update_select_button_text'):
            self.update_select_button_text()


    def add_event_map_entry(self, event=None):
        """Adds a new row (Label Entry, ID Entry, Remove Button) to the event map scroll frame."""
        # Ensure scroll frame exists before adding to it
        if not hasattr(self, 'event_map_scroll_frame') or not self.event_map_scroll_frame.winfo_exists():
            self.log("Error: Cannot add event map row, scroll frame not ready.")
            return

        validate_int_cmd = (self.register(self._validate_integer_input), '%P')
        # Use constants for widths if defined in config, otherwise use defaults
        try:
            from config import LABEL_ID_ENTRY_WIDTH
        except ImportError:
            LABEL_ID_ENTRY_WIDTH = 100  # Fallback width

        entry_frame = ctk.CTkFrame(self.event_map_scroll_frame, fg_color="transparent")
        # Use pack for layout within the scroll frame's canvas
        entry_frame.pack(fill="x", pady=1, padx=1)

        # Create Label Entry
        label_entry = ctk.CTkEntry(entry_frame, placeholder_text="Condition Label",
                                   width=LABEL_ID_ENTRY_WIDTH * 2,  # Wider for labels
                                   corner_radius=CORNER_RADIUS)
        label_entry.pack(side="left", fill="x", expand=True, padx=(0, PAD_X))
        # Bind Enter key press inside the underlying Tkinter entry
        label_entry._entry.bind("<Return>", self._add_row_and_focus_label)
        label_entry._entry.bind("<KP_Enter>", self._add_row_and_focus_label)  # Numpad Enter

        # Create ID Entry
        id_entry = ctk.CTkEntry(entry_frame, placeholder_text="Numerical ID",
                                width=LABEL_ID_ENTRY_WIDTH,
                                validate='key', validatecommand=validate_int_cmd,
                                corner_radius=CORNER_RADIUS)
        id_entry.pack(side="left", padx=(0, PAD_X))
        # Bind Enter key press
        id_entry._entry.bind("<Return>", self._add_row_and_focus_label)
        id_entry._entry.bind("<KP_Enter>", self._add_row_and_focus_label)

        # Create Remove Button
        remove_btn = ctk.CTkButton(entry_frame, text="✕",  # Use a clear 'X' symbol
                                   width=28, height=28,
                                   corner_radius=CORNER_RADIUS,
                                   # Pass the specific frame to remove
                                   command=lambda ef=entry_frame: self.remove_event_map_entry(ef))
        remove_btn.pack(side="right")

        # Store references to the widgets for this row
        self.event_map_entries.append({
            'frame': entry_frame,
            'label': label_entry,
            'id': id_entry,
            'button': remove_btn
        })

        # Focus the label entry of the new row if it wasn't triggered by an event (i.e., initial call)
        # This focusing is now handled in __init__ and _add_row_and_focus_label
        # if event is None:
        #    try:
        #        if label_entry.winfo_exists():
        #           label_entry.focus_set()
        #    except Exception as e:
        #        self.log(f"Warning: Error focusing initial label entry: {e}")

    def remove_event_map_entry(self, entry_frame_to_remove):
        """Removes the specified row frame and its widgets from the event map."""
        try:
            entry_to_remove = None
            # Find the dictionary corresponding to the frame
            for i, entry in enumerate(self.event_map_entries):
                if entry['frame'] == entry_frame_to_remove:
                    entry_to_remove = entry
                    del self.event_map_entries[i]
                    break

            if entry_to_remove:
                # Destroy the frame (which destroys widgets inside it)
                if entry_frame_to_remove.winfo_exists():
                    entry_frame_to_remove.destroy()

                # If no rows left, add a new default one
                if not self.event_map_entries:
                    self.add_event_map_entry()
                # Otherwise, focus the label of the last remaining row
                elif self.event_map_entries:
                     try:
                         # Check if the last entry's widgets still exist
                         last_entry = self.event_map_entries[-1]
                         if last_entry['frame'].winfo_exists() and last_entry['label'].winfo_exists():
                              last_entry['label'].focus_set()
                     except Exception as e:
                           self.log(f"Warning: Could not focus after removing row: {e}")
            else:
                self.log("Warning: Could not find the specified event map row to remove.")
        except Exception as e:
            self.log(f"Error removing Event Map row: {e}\n{traceback.format_exc()}")


    def select_save_folder(self):
        folder = filedialog.askdirectory(title="Select Parent Folder for Excel Output")
        if folder:
            self.save_folder_path.set(folder)
            self.log(f"Output folder: {folder}")
        else:
            self.log("Save folder selection cancelled.")

    def update_select_button_text(self):
        """
        Update the label on the Select EEG File… button to match the current mode.
        """
        if self.file_mode.get() == "Single":
            self.select_button.configure(text="Select EEG File…")
        else:
            self.select_button.configure(text="Select Folder…")

    def select_data_source(self):
        self.data_paths = []
        file_ext = "*" + self.file_type.get().lower()
        file_type_desc = self.file_type.get().upper()
        try:
            if self.file_mode.get() == "Single":
                ftypes = [(f"{file_type_desc} files", file_ext)]
                other_ext = "*.set" if file_type_desc == ".BDF" else "*.bdf"
                other_desc = ".SET" if file_type_desc == ".BDF" else ".BDF"
                ftypes.append((f"{other_desc} files", other_ext))
                ftypes.append(("All files", "*.*"))

                file_path = filedialog.askopenfilename(title="Select EEG File", filetypes=ftypes)
                if file_path:
                    selected_ext = os.path.splitext(file_path)[1].lower()
                    if selected_ext in ['.bdf', '.set']:
                        self.file_type.set(selected_ext.upper())
                        self.log(f"File type set to {selected_ext.upper()}")
                    self.data_paths = [file_path]
                    self.log(f"Selected file: {os.path.basename(file_path)}")
                else:
                    self.log("No file selected.")
            else:
                folder = filedialog.askdirectory(title=f"Select Folder with {file_type_desc} Files")
                if folder:
                    search_path = os.path.join(folder, file_ext)
                    found_files = sorted(glob.glob(search_path))
                    if found_files:
                        self.data_paths = found_files
                        self.log(f"Selected folder: {folder}, Found {len(found_files)} '{file_ext}' file(s).")
                    else:
                        self.log(f"No '{file_ext}' files found in {folder}.")
                        messagebox.showwarning("No Files Found", f"No '{file_type_desc}' files found in:\n{folder}")
                else:
                    self.log("No folder selected.")
        except Exception as e:
            self.log(f"Error selecting data: {e}")
            messagebox.showerror("Selection Error", f"Error during selection:\n{e}")

        self._max_progress = len(self.data_paths) if self.data_paths else 1
        self.progress_bar.set(0)


    # --- Logging ---
    def log(self, message):
        if hasattr(self, 'log_text') and self.log_text:
            try:
                ct = threading.current_thread()
                ts = pd.Timestamp.now().strftime('%H:%M:%S.%f')[:-3]
                prefix = "[BG]" if ct != threading.main_thread() else "[GUI]"
                log_msg = f"{ts} {prefix}: {message}\n"
                def update_gui():
                    if self.log_text.winfo_exists():
                        self.log_text.configure(state="normal")
                        self.log_text.insert(tk.END, log_msg)
                        self.log_text.see(tk.END)
                        self.log_text.configure(state="disabled")
                if ct != threading.main_thread():
                    if self.after and self.winfo_exists():
                        self.after(0, update_gui)
                    print(log_msg, end='')
                else:
                    update_gui()
                    self.update_idletasks()
            except Exception as e:
                print(f"--- GUI Log Error: {e} ---\n{pd.Timestamp.now().strftime('%H:%M:%S.%f')[:-3]} Log Console: {message}")


    # --- Event ID Detection ---
    def detect_and_show_event_ids(self):
        self.busy = True
        self._set_controls_enabled(False)
        self.log("Detect Numerical IDs button clicked...")
        if self.detection_thread and self.detection_thread.is_alive():
            messagebox.showwarning("Busy", "Event detection is already running.")
            return
        if not self.data_paths:
            messagebox.showerror("No Data Selected", "Please select a data file or folder first.")
            self.log("Detection failed: No data selected.")
            return

        stim_channel_name = DEFAULT_STIM_CHANNEL
        self.log(f"Using stim channel: {stim_channel_name}")
        representative_file = self.data_paths[0]
        self.busy = True
        self._set_controls_enabled(False)

        try:
            self.detection_thread = threading.Thread(
                target=self._detection_thread_func,
                args=(representative_file, stim_channel_name, self.gui_queue),
                daemon=True
            )
            self.detection_thread.start()
            self.after(100, self._periodic_detection_queue_check)
        except Exception as start_err:
            self.log(f"Error starting detection thread: {start_err}")
            messagebox.showerror("Thread Error", f"Could not start detection thread:\n{start_err}")
            self.busy = False
            self._set_controls_enabled(True)

    def _detection_thread_func(self, file_path, stim_channel_name, gui_queue):
        raw = None
        gc.collect()
        try:
            raw = self.load_eeg_file(file_path)
            if raw is None:
                raise ValueError("File loading failed (check log).")
            gui_queue.put({'type': 'log', 'message': f"Searching for numerical triggers on channel '{stim_channel_name}'..."})
            try:
                events = mne.find_events(raw, stim_channel=stim_channel_name, consecutive=True, verbose=False)
            except ValueError as find_err:
                if "not found" in str(find_err):
                    gui_queue.put({'type': 'log', 'message': f"Error: Stim channel '{stim_channel_name}' not found in {os.path.basename(file_path)}."})
                    gui_queue.put({'type': 'detection_error', 'message': f"Stim channel '{stim_channel_name}' not found."})
                    return
                else:
                    raise find_err

            if events is None or len(events) == 0:
                gui_queue.put({'type': 'log', 'message': f"No events found on channel '{stim_channel_name}'."})
                detected_ids = []
            else:
                unique_numeric_ids = sorted(np.unique(events[:, 2]).tolist())
                gui_queue.put({'type': 'log', 'message': f"Found {len(events)} triggers. Unique IDs: {unique_numeric_ids}"})
                detected_ids = unique_numeric_ids

            gui_queue.put({'type': 'detection_result', 'ids': detected_ids})
        except Exception as e:
            gui_queue.put({'type': 'log', 'message': f"Error during event detection: {e}\n{traceback.format_exc()}"})
            gui_queue.put({'type': 'detection_error', 'message': str(e)})
        finally:
            if raw:
                del raw
                gc.collect()
            gui_queue.put({'type': 'detection_done'})


    def _periodic_detection_queue_check(self):
        finished = False
        try:
            while True:
                msg = self.gui_queue.get_nowait()
                t = msg.get('type')
                if t == 'log':
                    self.log(msg.get('message', ''))
                elif t == 'detection_result':
                    ids = msg.get('ids', [])
                    if ids:
                        id_str = ", ".join(map(str, ids))
                        self.log(f"Detected IDs: {id_str}")
                        messagebox.showinfo("Numerical IDs Detected", f"Unique IDs found:\n\n{id_str}\n\nEnter Label:ID pairs manually.")
                    else:
                        messagebox.showinfo("No IDs", "No numerical event triggers found.")
                    finished = True
                elif t == 'detection_error':
                    messagebox.showerror("Detection Error", msg.get('message', 'Unknown error.'))
                    finished = True
                elif t == 'detection_done':
                    self.log("Detection thread finished.")
                    finished = True
        except queue.Empty:
            pass

        if finished:
            self.busy = False
            self._set_controls_enabled(True)

            self.detection_thread = None
            gc.collect()
        else:
            if self.detection_thread and self.detection_thread.is_alive():
                self.after(100, self._periodic_detection_queue_check)
            else:
                self.log("Warning: Detection thread ended unexpectedly.")
                self.busy = False
                self._set_controls_enabled(True)
                self.detection_thread = None


    # --- Core Processing Control ---
    def start_processing(self):
        if self.processing_thread and self.processing_thread.is_alive():
            messagebox.showwarning("Busy", "Processing is already running.")
            return
        if self.detection_thread and self.detection_thread.is_alive():
            messagebox.showwarning("Busy", "Event detection is running. Please wait.")
            return

        self.log("="*50)
        self.log("START PROCESSING Initiated...")
        if not self._validate_inputs():
            return

        self.preprocessed_data = {}
        self.progress_bar.set(0)
        self._max_progress = len(self.data_paths)
        self.busy = True
        self._set_controls_enabled(False)

        self.log("Starting background processing thread...")
        args = (list(self.data_paths), self.validated_params.copy(), self.gui_queue)
        self.processing_thread = threading.Thread(target=self._processing_thread_func, args=args, daemon=True)
        self.processing_thread.start()
        self.after(100, self._periodic_queue_check)

    def _validate_inputs(self):
        print("DEBUG_VALIDATE: _validate_inputs START") # Direct print for robustness
        self.log("DEBUG_VALIDATE: _validate_inputs called via self.log.")

        # Validate data selection
        if not self.data_paths:
            self.log("Validation Error: No data file(s) selected for processing.")
            messagebox.showerror("Input Error", "No data file(s) selected. Please select files or a folder first.")
            print("DEBUG_VALIDATE: Returning False - No data_paths")
            return False
        self.log("DEBUG_VALIDATE: Data paths validated.")

        # Validate output folder
        save_folder = self.save_folder_path.get()
        if not save_folder:
            self.log("Validation Error: No output folder selected.")
            messagebox.showerror("Input Error", "No output folder selected. Please select where to save results.")
            print("DEBUG_VALIDATE: Returning False - No save_folder")
            return False
        if not os.path.isdir(save_folder):
            try:
                os.makedirs(save_folder, exist_ok=True)
                self.log(f"Output folder did not exist. Created: {save_folder}")
            except Exception as e:
                self.log(f"Validation Error: Cannot create output folder {save_folder}: {e}")
                messagebox.showerror("Input Error", f"Cannot create output folder:\n{save_folder}\nError: {e}")
                print(f"DEBUG_VALIDATE: Returning False - Cannot create save_folder: {e}")
                return False
        self.log("DEBUG_VALIDATE: Save folder validated.")

        params = {}
        try:
            print("DEBUG_VALIDATE: Attempting to parse numeric parameters...")
            def get_float(entry_widget, field_name_for_error="value"):
                val_str = entry_widget.get().strip()
                if not val_str: return None
                try: return float(val_str)
                except ValueError: raise ValueError(f"Invalid numeric input for {field_name_for_error}: '{val_str}'")

            def get_int(entry_widget, field_name_for_error="value"):
                val_str = entry_widget.get().strip()
                if not val_str: return None
                try: return int(val_str)
                except ValueError: raise ValueError(f"Invalid integer input for {field_name_for_error}: '{val_str}'")

            params['low_pass'] = get_float(self.low_pass_entry, "Low Pass (Hz)")
            if params['low_pass'] is not None: assert params['low_pass'] >= 0, "Low Pass (Hz) must be zero or positive."

            params['high_pass'] = get_float(self.high_pass_entry, "High Pass (Hz)")
            if params['high_pass'] is not None: assert params['high_pass'] > 0, "High Pass (Hz) must be positive."

            if params['low_pass'] is not None and params['high_pass'] is not None:
                assert params['low_pass'] < params['high_pass'], "Low Pass (Hz) must be less than High Pass (Hz)."

            params['downsample_rate'] = get_float(self.downsample_entry, "Downsample (Hz)")
            if params['downsample_rate'] is not None: assert params['downsample_rate'] > 0, "Downsample (Hz) must be positive."

            params['epoch_start'] = get_float(self.epoch_start_entry, "Epoch Start (s)"); assert params['epoch_start'] is not None, "Epoch Start (s) cannot be empty."
            params['epoch_end'] = get_float(self.epoch_end_entry, "Epoch End (s)"); assert params['epoch_end'] is not None, "Epoch End (s) cannot be empty."
            assert params['epoch_start'] < params['epoch_end'], "Epoch Start (s) must be less than Epoch End (s)."

            params['reject_thresh'] = get_float(self.reject_thresh_entry, "Rejection Z-Thresh")
            if params['reject_thresh'] is not None: assert params['reject_thresh'] > 0, "Rejection Z-Thresh must be positive."

            params['ref_channel1'] = self.ref_channel1_entry.get().strip()
            params['ref_channel2'] = self.ref_channel2_entry.get().strip()

            params['max_idx_keep'] = get_int(self.max_idx_keep_entry, "Max Chan Idx Keep")
            if params['max_idx_keep'] is not None: assert params['max_idx_keep'] > 0, "Max Chan Idx Keep must be positive."

            params['stim_channel'] = DEFAULT_STIM_CHANNEL
            self.log(f"Using Stimulus Channel: '{params['stim_channel']}' (from configuration)")
            print(f"DEBUG_VALIDATE: Using Stimulus Channel: '{params['stim_channel']}'")

            max_bad_thresh_val = get_int(self.max_bad_channels_alert_entry, "Max Bad Chans (Flag)")
            if max_bad_thresh_val is not None:
                assert max_bad_thresh_val >= 0, "Max Bad Channels to Flag must be zero or a positive integer."
                params['max_bad_channels_alert_thresh'] = max_bad_thresh_val
            else:
                params['max_bad_channels_alert_thresh'] = 9999
                self.log("Max Bad Channels to Flag is blank; quality flagging based on this will be disabled.")
            self.log("DEBUG_VALIDATE: Basic parameters and thresholds validated.")
            print("DEBUG_VALIDATE: Basic parameters and thresholds validated.")

        except (AssertionError, ValueError) as e:
            self.log(f"Validation Error: Invalid parameter input: {e}")
            messagebox.showerror("Parameter Error", f"Invalid parameter value: {e}")
            print(f"DEBUG_VALIDATE: Returning False - Invalid parameter (AssertionError/ValueError): {e}")
            return False
        except Exception as e_gen:
            self.log(f"Validation Error: General error during parameter validation: {e_gen}\n{traceback.format_exc()}")
            messagebox.showerror("Parameter Error", "A general error occurred validating parameters. Please check all entries.")
            print(f"DEBUG_VALIDATE: Returning False - General parameter validation error: {e_gen}")
            return False

        self.log("DEBUG_VALIDATE: Proceeding to Event Map validation.")
        print("DEBUG_VALIDATE: Proceeding to Event Map validation.")
        event_map = {}
        try:
            if not self.event_map_entries:
                self.log("Validation Error: Event Map is empty (no rows defined).")
                messagebox.showerror("Event Map Error", "The Event Map is empty. Please use '+ Add Condition' to define at least one event.")
                if hasattr(self, 'add_map_button') and self.add_map_button: self.add_map_button.focus_set()
                print("DEBUG_VALIDATE: Returning False - Event Map has no rows.")
                return False

            labels_seen = set()

            is_event_map_effectively_empty = True
            for i, entry_widgets in enumerate(self.event_map_entries):
                print(f"DEBUG_VALIDATE: Processing event map row {i+1}")
                label_widget = entry_widgets.get('label')
                id_widget = entry_widgets.get('id')

                if not label_widget or not id_widget:
                    self.log(f"Internal Error: Event map row {i+1} is missing widget references.")
                    messagebox.showerror("Internal Error", f"Event Map row {i+1} is improperly constructed.")
                    print(f"DEBUG_VALIDATE: Returning False - Event map row {i+1} malformed.")
                    return False

                lbl_str = label_widget.get().strip()
                id_str = id_widget.get().strip()
                print(f"DEBUG_VALIDATE: Row {i+1}: Label='{lbl_str}', ID='{id_str}'")

                if lbl_str or id_str:
                    is_event_map_effectively_empty = False

                if not lbl_str and not id_str:
                    if len(self.event_map_entries) == 1:
                        self.log("Validation Error: The only Event Map row is empty.")
                        messagebox.showerror("Event Map Error", "Please enter a Condition Label and its Numerical ID in the Event Map.")
                        label_widget.focus_set()
                        print("DEBUG_VALIDATE: Returning False - Only event map row is empty.")
                        return False
                    print(f"DEBUG_VALIDATE: Row {i+1} is completely empty, skipping.")
                    continue

                if not lbl_str:
                    self.log(f"Validation Error: Event Map row {i+1} has an ID ('{id_str}') but no Condition Label.")
                    messagebox.showerror("Event Map Error", f"Event Map row {i+1}: Found a Numerical ID ('{id_str}') but no Condition Label.")
                    label_widget.focus_set()
                    print(f"DEBUG_VALIDATE: Returning False - Event map row {i+1} no label.")
                    return False
                if not id_str:
                    self.log(f"Validation Error: Event Map Condition '{lbl_str}' (row {i+1}) has no Numerical ID.")
                    messagebox.showerror("Event Map Error", f"Event Map: Condition '{lbl_str}' (row {i+1}) has no Numerical ID.")
                    id_widget.focus_set()
                    print(f"DEBUG_VALIDATE: Returning False - Event map row {i+1} no ID for label '{lbl_str}'.")
                    return False

                if lbl_str in labels_seen:
                    self.log(f"Validation Error: Duplicate Condition Label in Event Map: '{lbl_str}'.")
                    messagebox.showerror("Event Map Error", f"Duplicate Condition Label found in Event Map: '{lbl_str}'. Labels must be unique.")
                    label_widget.focus_set()
                    print(f"DEBUG_VALIDATE: Returning False - Duplicate label '{lbl_str}'.")
                    return False
                labels_seen.add(lbl_str)

                try:
                    num_id = int(id_str)
                except ValueError:
                    self.log(f"Validation Error: Invalid Numerical ID for '{lbl_str}' in Event Map: '{id_str}'.")
                    messagebox.showerror("Event Map Error", f"Invalid Numerical ID for Condition '{lbl_str}': '{id_str}'. Must be an integer.")
                    id_widget.focus_set()
                    print(f"DEBUG_VALIDATE: Returning False - Invalid ID for '{lbl_str}': '{id_str}'.")
                    return False

                event_map[lbl_str] = num_id
                print(f"DEBUG_VALIDATE: Added to event_map: '{lbl_str}' -> {num_id}")

            if not event_map: # If after iterating all rows, event_map is still empty
                self.log("Validation Error: Event Map contains no valid entries after parsing all rows.")
                messagebox.showerror("Event Map Error", "Please provide at least one valid Condition Label and Numerical ID pair in the Event Map.")
                if self.event_map_entries and self.event_map_entries[0].get('label'): # Focus first row if it exists
                     self.event_map_entries[0]['label'].focus_set()
                elif hasattr(self, 'add_map_button') and self.add_map_button: # Or focus add button
                    self.add_map_button.focus_set()
                print("DEBUG_VALIDATE: Returning False - event_map is empty after loop.")
                return False

            params['event_id_map'] = event_map
            self.validated_params = params
            self.log("DEBUG_VALIDATE: Event Map validated successfully.")
            print("DEBUG_VALIDATE: Event Map validated successfully.")

        except Exception as e_map_general:
            self.log(f"Validation Error: Unexpected error during Event Map validation: {e_map_general}\n{traceback.format_exc()}")
            messagebox.showerror("Event Map Error", f"An unexpected error occurred during Event Map validation:\n{e_map_general}")
            print(f"DEBUG_VALIDATE: Returning False - Unexpected Event Map error: {e_map_general}")
            return False

        self.log("Inputs Validated Successfully.")
        self.log(f"Effective Parameters for this run: {self.validated_params}")
        print("DEBUG_VALIDATE: _validate_inputs RETURNING TRUE")
        return True


    # --- Periodic Queue Check ---
    def _periodic_queue_check(self):
        done = False
        try:
            while True:
                msg = self.gui_queue.get_nowait()
                t   = msg.get('type')

                if t == 'log':
                    self.log(msg['message'])

                elif t == 'progress':
                    frac = msg['value'] / self._max_progress
                    self.progress_bar.set(frac)
                    self.update_idletasks()

                elif t == 'post':
                    fname       = msg['file']
                    epochs_dict = msg['epochs_dict']    # { label: [Epochs, ...], ... }
                    labels      = msg['labels']         # [ 'Fruit vs Veg', ... ]

                    self.log(f"\n--- Post-processing File: {fname} ---")
                    # Temporarily replace preprocessed_data with this file's dict
                    original_data = self.preprocessed_data
                    self.preprocessed_data = epochs_dict
                    try:
                        _external_post_process(self, labels)
                    except Exception as e:
                        self.log(f"!!! post_process error for {fname}: {e}")
                    finally:
                        # restore (and free)
                        self.preprocessed_data = original_data
                        for lst in epochs_dict.values():
                            for ep in lst:
                                del ep
                        del epochs_dict
                        gc.collect()

                elif t == 'error':
                    self.log("!!! THREAD ERROR: " + msg['message'])
                    if tb := msg.get('traceback'):
                        print(tb)
                    done = True

                elif t == 'done':
                    done = True

        except queue.Empty:
            pass

        if not done and self.processing_thread and self.processing_thread.is_alive():
            self.after(100, self._periodic_queue_check)
        else:
            self._finalize_processing(done)



   # Finalize Processing
        # --- Finalize Processing (Simplified & Resetting) ---
    def _finalize_processing(self, success):
        """
        Finalize the batch/single processing: show a completion dialog,
        re-enable the UI, reset state for a new run.
        """
        # 1. Show result message
        if success:
            self.log("--- Processing Run Completed Successfully ---")
            if self.validated_params and self.data_paths:
                output_folder = self.save_folder_path.get()
                n = len(self.data_paths)
                messagebox.showinfo(
                    "Processing Complete",
                    f"Analysis finished for {n} file{'s' if n!=1 else ''}.\n"
                    f"Excel files saved to:\n{output_folder}"
                )
            else:
                messagebox.showinfo(
                    "Processing Finished",
                    "Processing run finished. Check logs for details."
                )
        else:
            self.log("--- Processing Run Finished with ERRORS ---")
            messagebox.showerror(
                "Processing Error",
                "An error occurred during processing. Please check the log for details."
            )

        # 2. Re-enable UI
        self.busy = False
        self._set_controls_enabled(True)
        self.log(f"--- GUI Controls Re-enabled at {pd.Timestamp.now()} ---")

        # 3. Reset progress & data
        self.data_paths = []
        self._max_progress = 1
        self.progress_bar.set(0.0)
        self.preprocessed_data = {}

        # 4. Append a "Ready" message, but do NOT clear existing log
        if hasattr(self, 'log_text') and self.log_text.winfo_exists():
            self.log_text.configure(state="normal")
            ready_msg = (
                f"{pd.Timestamp.now().strftime('%H:%M:%S.%f')[:-3]} [GUI]: "
                "Ready for next file selection...\n"
            )
            self.log_text.insert(tk.END, ready_msg)
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")

        # 5. Clean up thread handle
        self.processing_thread = None
        gc.collect()

        # 6. Final internal log
        self.log("--- State Reset. Ready for next run. ---")

        # --- Background Processing Thread ---

    def _processing_thread_func(self, data_paths, params, gui_queue):
        import os
        import gc
        import traceback
        import mne
        import numpy as np
        import pandas as pd
        import re

        event_id_map_from_gui = params.get('event_id_map', {})
        # stim_channel_name is now directly from params, which _validate_inputs sets from DEFAULT_STIM_CHANNEL
        stim_channel_name = params.get('stim_channel', DEFAULT_STIM_CHANNEL)
        save_folder = self.save_folder_path.get()
        max_bad_channels_alert_thresh = params.get('max_bad_channels_alert_thresh', 9999)

        original_app_data_paths = list(self.data_paths)
        original_app_preprocessed_data = dict(self.preprocessed_data)

        quality_flagged_files_info_for_run = []

        try:
            for i, f_path in enumerate(data_paths):
                f_name = os.path.basename(f_path)
                gui_queue.put(
                    {'type': 'log', 'message': f"\n--- Processing file {i + 1}/{len(data_paths)}: {f_name} ---"})

                raw = None
                raw_proc = None
                num_kurtosis_bads = 0
                file_epochs = {}
                events = np.array([])

                extracted_pid_for_flagging = "UnknownPID"  # PID for quality_review_suggestions.txt
                pid_base_for_flagging = os.path.splitext(f_name)[0]
                pid_regex_flag = r"(?:[a-zA-Z_]*?)?(P\d+)"
                match_flag = re.search(pid_regex_flag, pid_base_for_flagging, re.IGNORECASE)
                if match_flag:
                    extracted_pid_for_flagging = match_flag.group(1).upper()
                else:
                    temp_pid = re.sub(
                        r'(_unamb|_ambig|_mid|_run\d*|_sess\d*|_task\w*|_eeg|_fpvs|_raw|_preproc|_ica|_EventsUpdated).*$',
                        '', pid_base_for_flagging, flags=re.IGNORECASE)
                    temp_pid = re.sub(r'[^a-zA-Z0-9]', '', temp_pid)
                    if temp_pid: extracted_pid_for_flagging = temp_pid

                try:
                    # 1) LOAD
                    raw = self.load_eeg_file(f_path)
                    if raw is None:
                        gui_queue.put({'type': 'log', 'message': f"Skipping file {f_name} due to load error."})
                        continue

                    # ... (debug logs for raw load as before) ...
                    gui_queue.put(
                        {'type': 'log', 'message': f"DEBUG [{f_name}]: Raw channel names after load: {raw.ch_names}"})

                    # 2) PREPROCESS
                    def thread_log_func_for_preprocess(message_from_preprocess):
                        gui_queue.put({'type': 'log', 'message': message_from_preprocess})

                    gui_queue.put({'type': 'log',
                                   'message': f"DEBUG [{f_name}]: Calling perform_preprocessing. Stim_channel: '{stim_channel_name}'"})

                    raw_proc, num_kurtosis_bads = perform_preprocessing(
                        raw_input=raw.copy(), params=params,
                        log_func=thread_log_func_for_preprocess, filename_for_log=f_name
                    )
                    del raw;
                    gc.collect()

                    if raw_proc is None:
                        gui_queue.put({'type': 'log', 'message': f"Skipping file {f_name} due to preprocess error."})
                        continue

                    if num_kurtosis_bads > max_bad_channels_alert_thresh:
                        alert_message = (f"QUALITY ALERT for {f_name} (PID: {extracted_pid_for_flagging}): "
                                         f"{num_kurtosis_bads} channels by Kurtosis (thresh: {max_bad_channels_alert_thresh}). File noted.")
                        gui_queue.put({'type': 'log', 'message': alert_message})
                        quality_flagged_files_info_for_run.append({
                            'pid': extracted_pid_for_flagging, 'filename': f_name,
                            'bad_channels_count': num_kurtosis_bads, 'threshold_used': max_bad_channels_alert_thresh
                        })

                    gui_queue.put({'type': 'log',
                                   'message': f"DEBUG [{f_name}]: Channels after perform_preprocessing: {raw_proc.ch_names}"})

                    # 3) EVENT EXTRACTION (Conditional Logic)
                    # ... (This extensive block for .set vs .bdf event extraction remains unchanged from the last version I provided) ...
                    file_extension = os.path.splitext(f_path)[1].lower()
                    if file_extension == ".set":
                        if hasattr(raw_proc, 'annotations') and raw_proc.annotations and len(raw_proc.annotations) > 0:
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: Attempting event extraction using MNE Annotations for .set file."})
                            mne_annots_event_id_map = {}
                            user_gui_int_ids = set(event_id_map_from_gui.values())
                            unique_raw_ann_descriptions = list(np.unique(raw_proc.annotations.description))
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: Unique annotation descriptions in file: {unique_raw_ann_descriptions}"})
                            for desc_str_from_file in unique_raw_ann_descriptions:
                                mapped_id_for_this_desc = None
                                if desc_str_from_file in event_id_map_from_gui:
                                    mapped_id_for_this_desc = event_id_map_from_gui[desc_str_from_file]
                                if mapped_id_for_this_desc is None:
                                    numeric_part_match = re.search(r'\d+', desc_str_from_file)
                                    if numeric_part_match:
                                        try:
                                            extracted_num_from_desc = int(numeric_part_match.group(0))
                                            if extracted_num_from_desc in user_gui_int_ids: mapped_id_for_this_desc = extracted_num_from_desc
                                        except ValueError:
                                            pass
                                if mapped_id_for_this_desc is not None: mne_annots_event_id_map[
                                    desc_str_from_file] = mapped_id_for_this_desc
                            if not mne_annots_event_id_map:
                                gui_queue.put({'type': 'log',
                                               'message': f"WARNING [{f_name}]: For .set file, could not create MNE event_id map from annotations."})
                            else:
                                gui_queue.put({'type': 'log',
                                               'message': f"DEBUG [{f_name}]: Using MNE event_id map for annotations: {mne_annots_event_id_map}"})
                                try:
                                    events, _ = mne.events_from_annotations(raw_proc, event_id=mne_annots_event_id_map,
                                                                            verbose=False, regexp=None)
                                    if events.size == 0: gui_queue.put({'type': 'log',
                                                                        'message': f"WARNING [{f_name}]: mne.events_from_annotations returned no events with map: {mne_annots_event_id_map}."})
                                except Exception as e_ann:
                                    gui_queue.put({'type': 'log',
                                                   'message': f"ERROR [{f_name}]: Failed to get events from annotations: {e_ann}"}); events = np.array(
                                        [])
                        else:
                            gui_queue.put({'type': 'log',
                                           'message': f"WARNING [{f_name}]: .set file has no MNE annotations on raw_proc."})
                        if events.size == 0: gui_queue.put({'type': 'log',
                                                            'message': f"FINAL WARNING [{f_name}]: No events extracted for this .set file from annotations."})
                    else:
                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: File is '{file_extension}'. Using mne.find_events on stim_channel '{stim_channel_name}'."})
                        if stim_channel_name not in raw_proc.ch_names:
                            gui_queue.put({'type': 'log',
                                           'message': f"ERROR [{f_name}]: Stim_channel '{stim_channel_name}' NOT in preprocessed data."})
                        else:
                            try:
                                events = mne.find_events(raw_proc, stim_channel=stim_channel_name, consecutive=True,
                                                         verbose=False)
                            except Exception as e_find:
                                gui_queue.put({'type': 'log',
                                               'message': f"ERROR [{f_name}]: Exception mne.find_events: {e_find}"})
                    if events.size == 0: gui_queue.put({'type': 'log',
                                                        'message': f"CRITICAL WARNING [{f_name}]: Event extraction resulted in empty events array."})

                    # 4) EPOCH for each condition
                    # ... (This loop remains unchanged, using event_id_map_from_gui and the 'events' array) ...
                    gui_queue.put({'type': 'log',
                                   'message': f"DEBUG [{f_name}]: Starting epoching based on GUI event_id_map: {event_id_map_from_gui}"})
                    for lbl, num_id_val_gui in event_id_map_from_gui.items():
                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: Attempting to epoch for GUI label '{lbl}' (using Int ID: {num_id_val_gui}). Events array shape: {events.shape}"})
                        if events.size > 0 and num_id_val_gui in events[:, 2]:
                            try:
                                epochs = mne.Epochs(raw_proc, events, event_id={lbl: num_id_val_gui},
                                                    tmin=params['epoch_start'], tmax=params['epoch_end'],
                                                    preload=True, verbose=False, baseline=None, on_missing='warn')
                                if len(epochs.events) > 0:
                                    gui_queue.put({'type': 'log',
                                                   'message': f"  -> Successfully created {len(epochs.events)} epochs for GUI label '{lbl}' in {f_name}."})
                                    file_epochs[lbl] = [epochs]
                                else:
                                    gui_queue.put({'type': 'log',
                                                   'message': f"  -> No epochs generated for GUI label '{lbl}' in {f_name}."})
                            except Exception as e_epoch:
                                gui_queue.put({'type': 'log',
                                               'message': f"!!! Epoching error for GUI label '{lbl}' in {f_name}: {e_epoch}\n{traceback.format_exc()}"})
                        else:
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: Target Int ID {num_id_val_gui} for GUI label '{lbl}' not found in extracted events. Skipping."})
                    gui_queue.put(
                        {'type': 'log', 'message': f"DEBUG [{f_name}]: Epoching loop for all GUI labels finished."})

                    # 5) OPTIONAL: save preprocessed .fif - THIS SECTION IS REMOVED
                    # if params.get('save_preprocessed', False) and raw_proc is not None:
                    #    # ... (logic was here) ...
                    #    pass # Now removed based on user request

                except Exception as file_proc_err:
                    gui_queue.put({'type': 'log',
                                   'message': f"!!! Error during main processing for {f_name}: {file_proc_err}\n{traceback.format_exc()}"})

                finally:
                    gui_queue.put({'type': 'log', 'message': f"DEBUG [{f_name}]: Entering finally block for file."})
                    # ... (has_valid_data check, call to self.post_process, and memory cleanup as before) ...
                    has_valid_data = False
                    if file_epochs:
                        has_valid_data = any(
                            elist and elist[0] and isinstance(elist[0], mne.Epochs) and hasattr(elist[0],
                                                                                                'events') and len(
                                elist[0].events) > 0
                            for elist in file_epochs.values()
                        )
                    gui_queue.put(
                        {'type': 'log', 'message': f"DEBUG [{f_name}]: Value of has_valid_data: {has_valid_data}"})

                    if raw_proc is not None and has_valid_data:
                        gui_queue.put({'type': 'log', 'message': f"--- Calling Post‐process for {f_name} ---"})
                        temp_original_data_paths = self.data_paths
                        temp_original_preprocessed_data = self.preprocessed_data
                        self.data_paths = [f_path]
                        self.preprocessed_data = file_epochs
                        try:
                            self.post_process(list(file_epochs.keys()))
                        except Exception as e_post:
                            gui_queue.put({'type': 'log',
                                           'message': f"!!! Post-processing/Excel error for {f_name}: {e_post}\n{traceback.format_exc()}"})
                        finally:
                            self.data_paths = temp_original_data_paths
                            self.preprocessed_data = temp_original_preprocessed_data
                    elif raw_proc is not None:  # but not has_valid_data
                        gui_queue.put(
                            {'type': 'log', 'message': f"Skipping Excel generation for {f_name} (no valid epochs)."})
                    elif raw_proc is None:
                        gui_queue.put({'type': 'log',
                                       'message': f"Skipping Excel generation for {f_name} (no preprocessed data)."})

                    gui_queue.put({'type': 'log', 'message': f"Cleaning up memory for {f_name}..."})
                    if isinstance(file_epochs, dict):  # Ensure it's a dict before iterating
                        for epochs_list_to_del in file_epochs.values():
                            if epochs_list_to_del and epochs_list_to_del[0] is not None:
                                if hasattr(epochs_list_to_del[0], '_data') and epochs_list_to_del[0]._data is not None:
                                    del epochs_list_to_del[0]._data
                                del epochs_list_to_del[0]
                        file_epochs.clear()
                    if isinstance(raw_proc, mne.io.BaseRaw): del raw_proc  # Check type before del
                    gc.collect()
                    gui_queue.put({'type': 'log', 'message': f"Memory cleanup for {f_name} complete."})

                gui_queue.put({'type': 'progress', 'value': i + 1})
            # --- End of loop for one file ---

            if quality_flagged_files_info_for_run:
                quality_file_path = os.path.join(save_folder, "quality_review_suggestions.txt")
                try:
                    with open(quality_file_path, 'w') as qf:
                        qf.write("PID,OriginalFilename,NumBadChannels,ThresholdUsed\n")
                        for item in quality_flagged_files_info_for_run:
                            qf.write(
                                f"{item['pid']},{item['filename']},{item['bad_channels_count']},{item['threshold_used']}\n")
                    gui_queue.put(
                        {'type': 'log', 'message': f"Quality review suggestions saved to: {quality_file_path}"})
                except Exception as e_qf:
                    gui_queue.put({'type': 'log', 'message': f"Error saving quality review file: {e_qf}"})

            gui_queue.put({'type': 'done'})

        except Exception as e_thread:
            gui_queue.put({'type': 'error', 'message': f"Critical error in processing thread: {e_thread}",
                           'traceback': traceback.format_exc()})
            gui_queue.put({'type': 'done'})
        finally:
            self.data_paths = original_app_data_paths
            self.preprocessed_data = original_app_preprocessed_data


    # --- EEG Loading Method ---
    def load_eeg_file(self, filepath):
        ext = os.path.splitext(filepath)[1].lower()
        base = os.path.basename(filepath)
        self.log(f"Loading: {base}...")
        try:
            kwargs = {'preload': True, 'verbose': False}
            if ext == ".bdf":
                with mne.utils.use_log_level('WARNING'):
                    raw = mne.io.read_raw_bdf(filepath, **kwargs)
                self.log("BDF loaded successfully.")
            elif ext == ".set":
                with mne.utils.use_log_level('WARNING'):
                    raw = mne.io.read_raw_eeglab(filepath, **kwargs)
                self.log("SET loaded successfully.")
            else:
                messagebox.showwarning("Unsupported File", f"Format '{ext}' not supported.")
                return None

            if raw is None:
                raise ValueError("MNE load returned None.")

            self.log(f"Load OK: {len(raw.ch_names)} channels @ {raw.info['sfreq']:.1f} Hz.")
            self.log("Applying standard_1020 montage...")
            try:
                montage = mne.channels.make_standard_montage('standard_1020')
                raw.set_montage(montage, on_missing='warn', match_case=False, verbose=False)
                self.log("Montage applied.")
            except Exception as e:
                self.log(f"Warning: Montage error: {e}")
            return raw
        except Exception as e:
            self.log(f"!!! Load Error {base}: {e}")
            messagebox.showerror("Loading Error", f"Could not load: {base}\nError: {e}")
            return None


    def _focus_next_id_entry(self, event):
        # (left intentionally blank)
        pass

    def _add_row_and_focus_label(self, event):
        """Callback for Return/Enter key in event map entries to add a new row."""
        self.add_event_map_entry()
        # Focus the label of the newly added row
        if self.event_map_entries:
             try:
                 # Ensure frame and label exist before focusing
                 if self.event_map_entries[-1]['frame'].winfo_exists() and \
                    self.event_map_entries[-1]['label'].winfo_exists():
                     self.event_map_entries[-1]['label'].focus_set()
             except Exception as e:
                 self.log(f"Warning: Could not focus new event map row: {e}")
        return "break" # Prevents default Enter behavior


    # Override to use external function
    def post_process(self, condition_labels_present):
        _external_post_process(self, condition_labels_present)
