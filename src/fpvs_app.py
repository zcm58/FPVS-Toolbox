#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FPVS all-in-one toolbox using MNE-Python and CustomTkinter.

Version: 0.9.0 (May 2025) - Revised to use mne.find_events for event extraction
from a stimulus channel using numerical IDs mapped to labels provided by the user.
Replaces annotation-based extraction from v1.10.

Key functionalities:
- Modern GUI using CustomTkinter.
- Load EEG data (.BDF, .set).
- Process single files or batch folders.
- Preprocessing Steps:
    - Specify Stimulus Channel Name (default: 'Status').
    - Initial Bipolar Reference using user-specified channels.
    - Downsample.
    - Apply standard_1020 montage.
    - Drop channels above a specified index (preserving Stim/Status channel).
    - Bandpass filter.
    - Kurtosis-based channel rejection & interpolation.
    - Average common reference.
- Extract epochs based on numerical triggers found via mne.find_events,
  using a user-provided mapping of Labels to Numerical IDs.
- Post-processing using FFT, SNR, Z-score, BCA computation.
- Saves Excel files with separate sheets per metric, named by condition label.
- Background processing with progress updates.
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
import logging
import numpy as np
import pandas as pd
import customtkinter as ctk
import mne
import requests
from packaging.version import parse as version_parse
from typing import Optional, Dict, Any  # Add any other type hints you use, like List

from config import (
    FPVS_TOOLBOX_VERSION,
    FPVS_TOOLBOX_UPDATE_API,
    FPVS_TOOLBOX_REPO_PAGE,
    DEFAULT_STIM_CHANNEL,
    CORNER_RADIUS,
    PAD_X,
    init_fonts,
    FONT_MAIN,
    FONT_BOLD,
    FONT_HEADING
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


class AppLoggingHandler(logging.Handler):
    """Logging handler that routes records to the FPVSApp.log method."""

    def __init__(self, app: "FPVSApp"):
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        try:
            self.app.log(msg)
        except Exception:
            pass

class FPVSApp(ctk.CTk):
    """ Main application class replicating MATLAB FPVS analysis workflow using numerical triggers. """

    def __init__(self):
        super().__init__()

        # Initialise fonts now that a root window exists
        init_fonts()

        # use modern default font
        # ``option_add`` internally forwards arguments directly to the
        # underlying Tcl interpreter. Passing ``None`` as the optional
        # priority argument results in Tcl receiving five tokens instead of
        # four, which raises "wrong # args" on some platforms. Casting the
        # ``CTkFont`` instance to ``str`` and explicitly providing the default
        # priority avoids this issue.
        self.option_add("*Font", str(FONT_MAIN), 80)


        # 2) State variables
        self.save_preprocessed = tk.BooleanVar(value=False)
        self.busy = False
        self.preprocessed_data = {}
        self.event_map_entries = []  # Initialize list for event map rows
        self.data_paths = []
        self.processing_thread = None
        self.detection_thread = None
        self.gui_queue = queue.Queue()
        self._max_progress = 1
        self.validated_params = {}

        # Toolbar button icons have been removed to reduce binary dependencies

        # 3) Window Setup
        from datetime import datetime
        self.title(f"FPVS Toolbox v{FPVS_TOOLBOX_VERSION} — {datetime.now():%Y-%m-%d}")
        self.minsize(700, 900)  # <<< SET MINIMUM SIZE HERE

        # 4) Build UI
        self.create_menu()
        self.create_widgets()  # <-- all widgets are created here

        # Configure logging to route messages through the app log
        logging.basicConfig(level=logging.INFO)
        self._log_handler = AppLoggingHandler(self)
        logging.getLogger().addHandler(self._log_handler)

        # 5) Add initial event map row
        self.add_event_map_entry()  # <<< ADD FIRST EVENT MAP ROW

        # 6) Welcome messages
        self.log("Welcome to the FPVS Toolbox!")
        self.log(f"Appearance Mode: {ctk.get_appearance_mode()}")

        # 7) Set initial focus
        if self.event_map_entries:  # <<< SET INITIAL FOCUS
            try:
                # Ensure frame and label exist before focusing
                if self.event_map_entries[0]['frame'].winfo_exists() and \
                        self.event_map_entries[0]['label'].winfo_exists():
                    self.event_map_entries[0]['label'].focus_set()
            except Exception as e:
                self.log(f"Warning: Could not set initial focus: {e}")

        # 8) Define toggle widgets list *after* create_widgets runs
        #    Make sure self.detect_button and self.add_map_button exist now
        self._toggle_widgets = [
            # Top‐bar buttons
            self.select_button,
            self.select_output_button,
            self.start_button,

            # Mode & file‐type controls
            self.radio_single, self.radio_batch,
            self.radio_bdf, self.radio_set,

            # Preprocessing entries
            self.low_pass_entry, self.high_pass_entry,
            self.downsample_entry, self.epoch_start_entry,
            self.epoch_end_entry, self.reject_thresh_entry,
            self.ref_channel1_entry,
            self.ref_channel2_entry,
            self.max_idx_keep_entry,
            self.detect_button,
            self.add_map_button,

            # Add individual event map row widgets if desired (more complex)
        ]
        # Add logic to disable event map entries/buttons themselves in _set_controls_enabled
        # for w_dict in self.event_map_entries:
        #     w_dict['label'].configure(state=state)
        #     w_dict['id'].configure(state=state)
        #     w_dict['button'].configure(state=state) # The 'X' button

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
        self.menubar = tk.Menu(self)
        self.config(menu=self.menubar)

        # === File menu ===
        file_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="File", menu=file_menu)

        # Appearance submenu
        appearance_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Appearance", menu=appearance_menu)
        appearance_menu.add_command(label="Dark Mode", command=lambda: self.set_appearance_mode("Dark"))
        appearance_menu.add_command(label="Light Mode", command=lambda: self.set_appearance_mode("Light"))
        appearance_menu.add_command(label="System Default", command=lambda: self.set_appearance_mode("System"))

        file_menu.add_separator()

        # Check for Updates moved here
        file_menu.add_command(label="Check for Updates", command=self.check_for_updates)
        file_menu.add_separator()

        file_menu.add_command(label="Exit", command=self.quit)

        # === Tools menu ===
        tools_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Stats Toolbox", command=self.open_stats_analyzer)
        tools_menu.add_separator()
        tools_menu.add_command(label="Image_Resizer", command=self.open_image_resizer)

        # === Help menu ===
        help_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About...", command=self.show_about_dialog)

        # === Advanced Analysis menu ===
        adv_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Advanced Analysis", menu=adv_menu)
        adv_menu.add_command(
        label = "Preprocessing Epoch Averaging",
        command = lambda: AdvancedAnalysisWindow(self)
                                            )

    def check_for_updates(self):
        """
        Checks the FPVS_TOOLBOX_UPDATE_API endpoint for the latest version.
        If newer than FPVS_TOOLBOX_VERSION, prompts the user to download.
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
        # --- GUI Creation ---
    def create_widgets(self):
            """Creates all the widgets for the main application window."""
            validate_num_cmd = (self.register(self._validate_numeric_input), '%P')
            validate_int_cmd = (self.register(self._validate_integer_input), '%P')
            # Use constants for widths if defined in config, otherwise use defaults
            try:
                from config import LABEL_ID_ENTRY_WIDTH, ENTRY_WIDTH, PAD_X, PAD_Y, CORNER_RADIUS
            except ImportError:
                LABEL_ID_ENTRY_WIDTH = 100;
                ENTRY_WIDTH = 80;
                PAD_X = 5;
                PAD_Y = 5;
                CORNER_RADIUS = 6  # Fallbacks

            # Main container - Configure rows/columns for grid layout
            main_frame = ctk.CTkFrame(self, corner_radius=0)
            main_frame.pack(fill="both", expand=True, padx=PAD_X * 2, pady=PAD_Y * 2)
            main_frame.grid_columnconfigure(0, weight=1)  # Allow content to expand horizontally
            main_frame.grid_rowconfigure(0, weight=0)  # Options + Buttons
            main_frame.grid_rowconfigure(1, weight=0)  # Params - no vertical expand
            main_frame.grid_rowconfigure(2, weight=1)  # Event Map - *should* expand vertically
            main_frame.grid_rowconfigure(3, weight=0)  # Bottom (Log/Progress) - no vertical expand

            self.save_folder_path = tk.StringVar()

            # --- Options & Buttons Frame (Row 0) ---
            self.options_frame = ctk.CTkFrame(main_frame)
            self.options_frame.grid(row=0, column=0, sticky="ew", padx=PAD_X, pady=PAD_Y)

            button_frame = ctk.CTkFrame(self.options_frame, fg_color="transparent")
            button_frame.grid(row=0, column=0, columnspan=4, sticky="w")

            self.select_button = ctk.CTkButton(
                button_frame, text="Select EEG File…",
                command=self.select_data_source, corner_radius=CORNER_RADIUS
            )
            self.select_button.grid(row=0, column=0, padx=(0, PAD_X))

            self.select_output_button = ctk.CTkButton(
                button_frame, text="Select Output Folder…",
                command=self.select_save_folder, corner_radius=CORNER_RADIUS
            )
            self.select_output_button.grid(row=0, column=1, padx=(0, PAD_X))

            self.start_button = ctk.CTkButton(
                button_frame, text="Start Processing",
                command=self.start_processing, corner_radius=CORNER_RADIUS
            )
            self.start_button.grid(row=0, column=2)

            # --- Processing Options Heading ---
            ctk.CTkLabel(self.options_frame, text="Processing Options",
                         font=FONT_BOLD).grid(
                row=1, column=0, columnspan=4, sticky="w", padx=PAD_X, pady=(PAD_Y, PAD_Y * 2)
            )

            # Mode radios
            ctk.CTkLabel(self.options_frame, text="Mode:").grid(row=2, column=0, sticky="w", padx=PAD_X, pady=PAD_Y)
            self.file_mode = tk.StringVar(value="Single")
            self.radio_single = ctk.CTkRadioButton(self.options_frame, text="Single File", variable=self.file_mode,
                                                   value="Single", command=self.update_select_button_text,
                                                   corner_radius=CORNER_RADIUS)
            self.radio_single.grid(row=2, column=1, padx=PAD_X, pady=PAD_Y, sticky="w")
            self.radio_batch = ctk.CTkRadioButton(self.options_frame, text="Batch Folder", variable=self.file_mode,
                                                  value="Batch", command=self.update_select_button_text,
                                                  corner_radius=CORNER_RADIUS)
            self.radio_batch.grid(row=2, column=2, padx=PAD_X, pady=PAD_Y, sticky="w")
            # File-type radios
            ctk.CTkLabel(self.options_frame, text="File Type:").grid(row=3, column=0, sticky="w", padx=PAD_X,
                                                                     pady=PAD_Y)
            self.file_type = tk.StringVar(value=".BDF")
            self.radio_bdf = ctk.CTkRadioButton(self.options_frame, text=".BDF", variable=self.file_type, value=".BDF",
                                                corner_radius=CORNER_RADIUS)
            self.radio_bdf.grid(row=3, column=1, padx=PAD_X, pady=PAD_Y, sticky="w")
            self.radio_set = ctk.CTkRadioButton(self.options_frame, text=".set", variable=self.file_type, value=".set",
                                                corner_radius=CORNER_RADIUS)
            self.radio_set.grid(row=3, column=2, padx=PAD_X, pady=PAD_Y, sticky="w")

            # --- Preprocessing Parameters Frame (Row 2) ---
            self.params_frame = ctk.CTkFrame(main_frame)
            self.params_frame.grid(row=2, column=0, sticky="ew", padx=PAD_X, pady=PAD_Y)
            ctk.CTkLabel(self.params_frame, text="Preprocessing Parameters",
                         font=FONT_BOLD).grid(
                row=0, column=0, columnspan=6, sticky="w", padx=PAD_X, pady=(PAD_Y, PAD_Y * 2)
            )
            # Row 1: Low/High pass
            ctk.CTkLabel(self.params_frame, text="Low Pass (Hz):").grid(row=1, column=0, sticky="w", padx=PAD_X,
                                                                        pady=PAD_Y)
            self.low_pass_entry = ctk.CTkEntry(self.params_frame, width=ENTRY_WIDTH, validate='key',
                                               validatecommand=validate_num_cmd, corner_radius=CORNER_RADIUS)
            self.low_pass_entry.insert(0, "0.1");
            self.low_pass_entry.grid(row=1, column=1, padx=PAD_X, pady=PAD_Y)
            ctk.CTkLabel(self.params_frame, text="High Pass (Hz):").grid(row=1, column=2, sticky="w", padx=PAD_X,
                                                                         pady=PAD_Y)
            self.high_pass_entry = ctk.CTkEntry(self.params_frame, width=ENTRY_WIDTH, validate='key',
                                                validatecommand=validate_num_cmd, corner_radius=CORNER_RADIUS)
            self.high_pass_entry.insert(0, "50");
            self.high_pass_entry.grid(row=1, column=3, padx=PAD_X, pady=PAD_Y)
            # Row 2: Downsample / Epoch
            ctk.CTkLabel(self.params_frame, text="Downsample (Hz):").grid(row=2, column=0, sticky="w", padx=PAD_X,
                                                                          pady=PAD_Y)
            self.downsample_entry = ctk.CTkEntry(self.params_frame, width=ENTRY_WIDTH, validate='key',
                                                 validatecommand=validate_num_cmd, corner_radius=CORNER_RADIUS)
            self.downsample_entry.insert(0, "256");
            self.downsample_entry.grid(row=2, column=1, padx=PAD_X, pady=PAD_Y)
            ctk.CTkLabel(self.params_frame, text="Epoch Start (s):").grid(row=2, column=2, sticky="w", padx=PAD_X,
                                                                          pady=PAD_Y)
            self.epoch_start_entry = ctk.CTkEntry(self.params_frame, width=ENTRY_WIDTH, validate='key',
                                                  validatecommand=validate_num_cmd, corner_radius=CORNER_RADIUS)
            self.epoch_start_entry.insert(0, "-1");
            self.epoch_start_entry.grid(row=2, column=3, padx=PAD_X, pady=PAD_Y)
            ctk.CTkLabel(self.params_frame, text="Epoch End (s):").grid(row=3, column=2, sticky="w", padx=PAD_X,
                                                                        pady=PAD_Y)
            self.epoch_end_entry = ctk.CTkEntry(self.params_frame, width=ENTRY_WIDTH, validate='key',
                                                validatecommand=validate_num_cmd, corner_radius=CORNER_RADIUS)
            self.epoch_end_entry.insert(0, "125");
            self.epoch_end_entry.grid(row=3, column=3, padx=PAD_X, pady=PAD_Y)
            # Row 3: Reject / Save
            ctk.CTkLabel(self.params_frame, text="Rejection Z-Thresh:").grid(row=3, column=0, sticky="w", padx=PAD_X,
                                                                             pady=PAD_Y)
            self.reject_thresh_entry = ctk.CTkEntry(self.params_frame, width=ENTRY_WIDTH, validate='key',
                                                    validatecommand=validate_num_cmd, corner_radius=CORNER_RADIUS)
            self.reject_thresh_entry.insert(0, "5");
            self.reject_thresh_entry.grid(row=3, column=1, padx=PAD_X, pady=PAD_Y)

            # Row 4: Initial Reference Channels
            ctk.CTkLabel(self.params_frame, text="Ref Chan 1:").grid(row=4, column=0, sticky="w", padx=PAD_X,
                                                                     pady=PAD_Y)
            self.ref_channel1_entry = ctk.CTkEntry(self.params_frame, width=ENTRY_WIDTH, corner_radius=CORNER_RADIUS)
            self.ref_channel1_entry.insert(0, "EXG1") # Optional default
            self.ref_channel1_entry.grid(row=4, column=1, padx=PAD_X, pady=PAD_Y)
            ctk.CTkLabel(self.params_frame, text="Ref Chan 2:").grid(row=4, column=2, sticky="w", padx=PAD_X,
                                                                     pady=PAD_Y)
            self.ref_channel2_entry = ctk.CTkEntry(self.params_frame, width=ENTRY_WIDTH, corner_radius=CORNER_RADIUS)
            self.ref_channel2_entry.insert(0, "EXG2") # Optional default
            self.ref_channel2_entry.grid(row=4, column=3, padx=PAD_X, pady=PAD_Y)
            # Row 5: Max Index Keep / Stim Channel
            ctk.CTkLabel(self.params_frame, text="Max Chan Idx Keep:").grid(row=5, column=0, sticky="w", padx=PAD_X,
                                                                            pady=PAD_Y)
            self.max_idx_keep_entry = ctk.CTkEntry(self.params_frame, width=ENTRY_WIDTH, corner_radius=CORNER_RADIUS,
                                                   validate='key', validatecommand=validate_int_cmd)
            self.max_idx_keep_entry.insert(0, "64") # Optional default
            self.max_idx_keep_entry.grid(row=5, column=1, padx=PAD_X, pady=PAD_Y)


            # --- Event ID Mapping Frame (Row 2 - EXPANDS) ---
            event_map_outer = ctk.CTkFrame(main_frame)
            event_map_outer.grid(row=2, column=0, sticky="nsew", padx=PAD_X, pady=PAD_Y)  # Use grid, allow expand
            # Configure event_map_outer's internal layout (using pack is fine here)
            event_map_outer.columnconfigure(0, weight=1)
            event_map_outer.rowconfigure(2, weight=1)  # Scroll frame should expand vertically

            # Header Label for Event Map
            ctk.CTkLabel(event_map_outer, text="Event Map (Condition Label → Numerical ID)",
                         font=FONT_BOLD).pack(anchor="w", padx=PAD_X, pady=(PAD_Y, 0))

            # Header Frame for Column Titles
            header_frame = ctk.CTkFrame(event_map_outer, fg_color="transparent")
            header_frame.pack(fill="x", padx=PAD_X, pady=(2, 0))
            # Adjust label widths if needed
            ctk.CTkLabel(header_frame, text="Condition Label",
                         width=LABEL_ID_ENTRY_WIDTH * 2 + PAD_X,  # Approximate width needed
                         anchor="w").pack(side="left", padx=(0, 0))  # Align left
            ctk.CTkLabel(header_frame, text="Numerical ID",
                         width=LABEL_ID_ENTRY_WIDTH + PAD_X,  # Approximate width
                         anchor="w").pack(side="left", padx=(0, 0))
            # Spacer for the 'X' button column
            ctk.CTkLabel(header_frame, text="", width=28 + PAD_X).pack(side="right", padx=(0, 0))

            # Scrollable Frame for the dynamic rows
            self.event_map_scroll_frame = ctk.CTkScrollableFrame(event_map_outer, label_text="")
            self.event_map_scroll_frame.pack(fill="both", expand=True, padx=PAD_X, pady=(0, PAD_Y))
            # No need to configure grid inside scroll frame if using pack for rows

            # Button Frame below scroll frame
            event_map_button_frame = ctk.CTkFrame(event_map_outer, fg_color="transparent")
            event_map_button_frame.pack(fill="x", pady=(0, PAD_Y), padx=PAD_X)
            self.detect_button = ctk.CTkButton(event_map_button_frame, text="Detect Trigger IDs",
                                               command=self.detect_and_show_event_ids, corner_radius=CORNER_RADIUS)
            self.detect_button.pack(side="left", padx=(0, PAD_X))
            self.add_map_button = ctk.CTkButton(event_map_button_frame, text="+ Add Condition",
                                                command=self.add_event_map_entry, corner_radius=CORNER_RADIUS)
            self.add_map_button.pack(side="left")

            # --- Bottom Frame: Log & Progress (Row 3 - NO VERTICAL EXPAND) ---
            bottom_frame = ctk.CTkFrame(main_frame)
            # Use grid, fill horizontally, but DO NOT expand vertically
            bottom_frame.grid(row=3, column=0, sticky="ew", padx=PAD_X, pady=(PAD_Y, 0))
            bottom_frame.grid_columnconfigure(0, weight=1)  # Column containing log/progress expands horizontally

            # Log box Frame
            log_outer = ctk.CTkFrame(bottom_frame)
            log_outer.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, PAD_Y))  # Log takes full width
            log_outer.grid_columnconfigure(0, weight=1)  # Textbox expands horizontally
            log_outer.grid_rowconfigure(1, weight=0)  # Textbox does NOT expand vertically
            ctk.CTkLabel(log_outer, text="Log", font=FONT_BOLD).grid(
                row=0, column=0, sticky="w", padx=PAD_X, pady=(PAD_Y, 0)
            )
            self.log_text = ctk.CTkTextbox(
                log_outer,
                height=75,  # Reduced log height
                wrap="word", state="disabled", corner_radius=CORNER_RADIUS
            )
            self.log_text.grid(row=1, column=0, sticky="ew", padx=PAD_X, pady=(0, PAD_Y))

            # Progress bar Frame (below log box)
            prog_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
            prog_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=PAD_Y)
            prog_frame.grid_columnconfigure(0, weight=1)  # Progress bar stretches horizontally
            self.progress_bar = ctk.CTkProgressBar(
                prog_frame, orientation="horizontal", height=20
            )
            self.progress_bar.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
            self.progress_bar.set(0)

            # Sync select button label to current mode initially (if method exists)
            if hasattr(self, 'update_select_button_text'):
                self.update_select_button_text()
            # Note: _toggle_widgets list is now defined in __init__ after this function runs
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
        # Validate data selection
        if not self.data_paths:
            self.log("V-Error: No data.")
            messagebox.showerror("Input Error", "No data selected.")
            return False


        # Validate output folder
        save_folder = self.save_folder_path.get()
        if not save_folder:
            self.log("V-Error: No save folder.")
            messagebox.showerror("Input Error", "No output folder selected.")
            return False
        if not os.path.isdir(save_folder):
            try:
                os.makedirs(save_folder, exist_ok=True)
                self.log(f"Created save folder: {save_folder}")
            except Exception as e:
                self.log(f"V-Error: Cannot create folder {save_folder}: {e}")
                messagebox.showerror("Input Error", f"Cannot create folder:\n{save_folder}\n{e}")
                return False

        # Validate parameters
        params = {}
        try:
            def get_float(e): return float(e.get().strip()) if e.get().strip() else None
            def get_int(e): return int(e.get().strip()) if e.get().strip() else None

            params['low_pass'] = get_float(self.low_pass_entry)
            assert params['low_pass'] is None or params['low_pass'] >= 0
            params['high_pass'] = get_float(self.high_pass_entry)
            assert params['high_pass'] is None or params['high_pass'] > 0
            params['downsample_rate'] = get_float(self.downsample_entry)
            assert params['downsample_rate'] is None or params['downsample_rate'] > 0
            params['epoch_start'] = get_float(self.epoch_start_entry); assert params['epoch_start'] is not None
            params['epoch_end'] = get_float(self.epoch_end_entry); assert params['epoch_end'] is not None
            assert params['epoch_start'] < params['epoch_end']
            params['reject_thresh'] = get_float(self.reject_thresh_entry)
            assert params['reject_thresh'] is None or params['reject_thresh'] > 0
            params['ref_channel1'] = self.ref_channel1_entry.get().strip()
            params['ref_channel2'] = self.ref_channel2_entry.get().strip()
            params['max_idx_keep'] = get_int(self.max_idx_keep_entry)
            assert params['max_idx_keep'] is None or params['max_idx_keep'] > 0
            if params['low_pass'] is not None and params['high_pass'] is not None:
                assert params['low_pass'] < params['high_pass']
            params['stim_channel'] = DEFAULT_STIM_CHANNEL
            params['save_preprocessed'] = self.save_preprocessed.get()

        except AssertionError as e:
            self.log(f"V-Error: Invalid parameter: {e}")
            messagebox.showerror("Parameter Error", f"Invalid parameter value:\n{e}")
            return False
        except Exception:
            self.log("V-Error: Parameter validation error.")
            messagebox.showerror("Parameter Error", "Invalid numeric value entered.\nPlease check parameters.")
            return False

        # Validate Event Map
        event_map = {}
        try:
            labels, ids = set(), set()
            for entry in self.event_map_entries:
                lbl = entry['label'].get().strip()
                id_str = entry['id'].get().strip()
                if not lbl and not id_str:
                    continue
                if not lbl:
                    messagebox.showerror("Event Map Error", "Found a row with a Numerical ID but no Condition Label.")
                    entry['label'].focus_set()
                    return False
                if not id_str:
                    messagebox.showerror("Event Map Error", f"Condition '{lbl}' has no Numerical ID.")
                    entry['id'].focus_set()
                    return False
                if lbl in labels:
                    messagebox.showerror("Event Map Error", f"Duplicate Condition Label: '{lbl}'.")
                    entry['label'].focus_set()
                    return False
                labels.add(lbl)
                try:
                    num_id = int(id_str)
                except ValueError:
                    messagebox.showerror("Event Map Error", f"Invalid Numerical ID for '{lbl}': '{id_str}'.")
                    entry['id'].focus_set()
                    return False
                ids.add(num_id)
                event_map[lbl] = num_id

            if not event_map:
                self.log("V-Error: No Event Map entries.")
                messagebox.showerror("Event Map Error", "Please enter at least one Condition Label and its ID.")
                if self.event_map_entries:
                    self.event_map_entries[0]['label'].focus_set()
                return False

            params['event_id_map'] = event_map
            self.validated_params = params
        except Exception as e:
            self.log(f"V-Error: Event Map validation error: {e}")
            messagebox.showerror("Event Map Error", f"Error validating Event Map:\n{e}")
            return False

        self.log("Inputs Validated Successfully.")
        self.log(f"Parameters: {self.validated_params}")
        return True

    def get_fpvs_params(self) -> Optional[Dict[str, Any]]:
        """Return a validated copy of current parameters or ``None`` if invalid."""
        if not self._validate_inputs():
            # _validate_inputs already reports errors
            return None
        return self.validated_params.copy()


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
        # In fpvs_app.py

        # --- Background Processing Thread ---
    def _processing_thread_func(self, data_paths, params, gui_queue):
            # Import necessary libraries locally within the thread
            import os
            import gc
            import traceback
            import mne
            import numpy as np
            import pandas as pd  # Just in case, though not directly used for DataFrame creation here now
            import re  # For extracting numbers from annotation descriptions

            event_id_map_from_gui = params['event_id_map']  # This is {'User Label': int_id, ...}
            stim_channel_name = params.get('stim_channel', DEFAULT_STIM_CHANNEL)
            save_folder = self.save_folder_path.get()

            original_app_data_paths = list(self.data_paths)
            original_app_preprocessed_data = dict(self.preprocessed_data)

            try:
                for i, f_path in enumerate(data_paths):
                    f_name = os.path.basename(f_path)
                    gui_queue.put(
                        {'type': 'log', 'message': f"\n--- Processing file {i + 1}/{len(data_paths)}: {f_name} ---"})

                    raw = None
                    raw_proc = None
                    file_epochs = {}
                    events = np.array([])  # Initialize events array

                    try:
                        # 1) LOAD
                        raw = self.load_eeg_file(f_path)
                        if raw is None:
                            gui_queue.put(
                                {'type': 'log', 'message': f"Skipping file {f_name} due to load error (raw is None)."})
                            continue

                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: Raw channel names immediately after load: {raw.ch_names}"})
                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: Raw channel types after load: {raw.get_channel_types(unique=True)}"})
                        # This check is less critical now if .set files use annotations, but good for .bdf
                        if stim_channel_name in raw.ch_names:
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: Configured stim channel '{stim_channel_name}' IS PRESENT in raw data after load."})
                        else:
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: NOTE: Configured stim channel '{stim_channel_name}' IS NOT PRESENT in raw data after load (may be fine for .set files using annotations)."})

                        # 2) PREPROCESS
                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: Calling preprocess_raw. Configured stim_channel for potential preservation (if found): '{stim_channel_name}'"})
                        raw_proc = self.preprocess_raw(raw.copy(), **params)
                        del raw;
                        gc.collect()
                        if raw_proc is None:
                            gui_queue.put({'type': 'log',
                                           'message': f"Skipping file {f_name} due to preprocess error (raw_proc is None)."})
                            continue

                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: Channel names AFTER preprocess_raw: {raw_proc.ch_names}"})
                        # This check is critical before find_events (for BDF)
                        if stim_channel_name in raw_proc.ch_names:
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: Configured stim channel '{stim_channel_name}' IS PRESENT in raw_proc data."})
                        else:
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: Configured stim channel '{stim_channel_name}' IS NOT PRESENT in raw_proc data."})

                        # 3) EVENT EXTRACTION (Conditional: Annotations for .SET, Stim Channel for .BDF)
                        file_extension = os.path.splitext(f_path)[1].lower()

                        if file_extension == ".set":
                            if hasattr(raw_proc, 'annotations') and raw_proc.annotations and len(
                                    raw_proc.annotations) > 0:
                                gui_queue.put({'type': 'log',
                                               'message': f"DEBUG [{f_name}]: Attempting event extraction using MNE Annotations for .set file."})

                                mne_annots_event_id_map = {}  # This will map actual annotation descriptions to the GUI's integer IDs
                                user_gui_int_ids = set(
                                    event_id_map_from_gui.values())  # Integer IDs from GUI {1, 2, 3...}
                                unique_raw_ann_descriptions = list(np.unique(raw_proc.annotations.description))
                                gui_queue.put({'type': 'log',
                                               'message': f"DEBUG [{f_name}]: Unique annotation descriptions in file: {unique_raw_ann_descriptions}"})
                                gui_queue.put({'type': 'log',
                                               'message': f"DEBUG [{f_name}]: User-defined GUI event map (Label -> Int ID): {event_id_map_from_gui}"})

                                for desc_str_from_file in unique_raw_ann_descriptions:
                                    mapped_id_for_this_desc = None
                                    # Priority 1: Direct match of annotation description with a GUI Label
                                    if desc_str_from_file in event_id_map_from_gui:
                                        mapped_id_for_this_desc = event_id_map_from_gui[desc_str_from_file]
                                        gui_queue.put({'type': 'log',
                                                       'message': f"DEBUG [{f_name}]: Annotation description '{desc_str_from_file}' directly matches a GUI Label. Mapping to ID: {mapped_id_for_this_desc}."})

                                    # Priority 2 (Fallback or Augment): Match by extracting number from annotation description
                                    if mapped_id_for_this_desc is None:  # Only if not already matched by label
                                        numeric_part_match = re.search(r'\d+', desc_str_from_file)
                                        if numeric_part_match:
                                            try:
                                                extracted_num_from_desc = int(numeric_part_match.group(0))
                                                if extracted_num_from_desc in user_gui_int_ids:
                                                    mapped_id_for_this_desc = extracted_num_from_desc
                                                    gui_queue.put({'type': 'log',
                                                                   'message': f"DEBUG [{f_name}]: Annotation description '{desc_str_from_file}' contains numeric part '{extracted_num_from_desc}' which matches a GUI ID. Mapping to ID: {mapped_id_for_this_desc}."})
                                            except ValueError:
                                                pass  # Could not convert numeric part to int

                                    if mapped_id_for_this_desc is not None:
                                        if desc_str_from_file in mne_annots_event_id_map and mne_annots_event_id_map[
                                            desc_str_from_file] != mapped_id_for_this_desc:
                                            gui_queue.put({'type': 'log',
                                                           'message': f"WARNING [{f_name}]: Ambiguous mapping for ann. desc. '{desc_str_from_file}'. Already mapped to {mne_annots_event_id_map[desc_str_from_file]}, now also matches ID {mapped_id_for_this_desc}. Check your annotation descriptions and GUI map."})
                                        mne_annots_event_id_map[desc_str_from_file] = mapped_id_for_this_desc

                                if not mne_annots_event_id_map:
                                    gui_queue.put({'type': 'log',
                                                   'message': f"WARNING [{f_name}]: For .set file, could not create any MNE event_id map from annotations based on GUI event map. No events will be extracted from annotations."})
                                else:
                                    gui_queue.put({'type': 'log',
                                                   'message': f"DEBUG [{f_name}]: Constructed MNE event_id map for annotations: {mne_annots_event_id_map}"})
                                    try:
                                        # regexp=None ensures exact string matching for keys in mne_annots_event_id_map
                                        events, _ = mne.events_from_annotations(raw_proc,
                                                                                event_id=mne_annots_event_id_map,
                                                                                verbose=False, regexp=None)
                                        gui_queue.put({'type': 'log',
                                                       'message': f"DEBUG [{f_name}]: Events successfully extracted from annotations. Shape: {events.shape if events.size > 0 else 'Empty'}"})
                                        if events.size == 0:
                                            gui_queue.put({'type': 'log',
                                                           'message': f"WARNING [{f_name}]: mne.events_from_annotations returned no events even with map: {mne_annots_event_id_map}."})
                                    except KeyError as ke:
                                        gui_queue.put({'type': 'log',
                                                       'message': f"ERROR [{f_name}]: KeyError getting events from annotations. Likely a description in annotations was expected in map but not found, or map was empty. Error: {ke}"})
                                        events = np.array([])
                                    except Exception as e_ann:
                                        gui_queue.put({'type': 'log',
                                                       'message': f"ERROR [{f_name}]: Failed to get events from annotations: {e_ann}\n{traceback.format_exc()}"})
                                        events = np.array([])
                            else:  # .set file but no annotations found on raw_proc object
                                gui_queue.put({'type': 'log',
                                               'message': f"WARNING [{f_name}]: .set file has no MNE annotations attached to raw_proc. Cannot use events_from_annotations."})

                            if events.size == 0:  # If .set file and annotations didn't yield events
                                gui_queue.put({'type': 'log',
                                               'message': f"FINAL WARNING [{f_name}]: No events could be extracted for this .set file using annotations."})

                        else:  # Not a .set file (e.g., .bdf), use find_events
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: File is '{file_extension}'. Using mne.find_events on stim channel '{stim_channel_name}'."})
                            if stim_channel_name not in raw_proc.ch_names:
                                gui_queue.put({'type': 'log',
                                               'message': f"ERROR [{f_name}]: Configured stim channel '{stim_channel_name}' is NOT in preprocessed data. Cannot find events for this BDF/other file."})
                            else:
                                try:
                                    events = mne.find_events(raw_proc, stim_channel=stim_channel_name, consecutive=True,
                                                             verbose=False)
                                    gui_queue.put({'type': 'log',
                                                   'message': f"DEBUG [{f_name}]: mne.find_events call completed for BDF/other."})
                                    gui_queue.put({'type': 'log',
                                                   'message': f"DEBUG [{f_name}]: Events found (shape): {events.shape if events.size > 0 else 'None or Empty'}"})
                                    if events.size > 0:
                                        unique_ids_in_file = np.unique(events[:, 2])
                                        gui_queue.put({'type': 'log',
                                                       'message': f"DEBUG [{f_name}]: Unique event IDs from stim channel: {unique_ids_in_file}"})
                                except ValueError as find_err_stim:  # Should have been caught by the "not in raw_proc.ch_names" check above, but good to have
                                    gui_queue.put({'type': 'log',
                                                   'message': f"ERROR [{f_name}]: ValueError during mne.find_events for BDF/other: {find_err_stim}"})
                                except Exception as e_find_stim:
                                    gui_queue.put({'type': 'log',
                                                   'message': f"ERROR [{f_name}]: Exception during mne.find_events for BDF/other: {e_find_stim}"})

                        # Central check for empty events array after attempting extraction
                        if events.size == 0:
                            gui_queue.put({'type': 'log',
                                           'message': f"CRITICAL WARNING [{f_name}]: Event extraction resulted in an empty events array. Epoching will not produce results."})

                        # 4) EPOCH for each condition (using the events array derived from either method)
                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: Starting epoching based on GUI event_id_map: {event_id_map_from_gui}"})
                        for lbl, num_id_val_gui in event_id_map_from_gui.items():  # Iterate through GUI map
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: Attempting to epoch for GUI label '{lbl}' (using Int ID: {num_id_val_gui}). Events array shape: {events.shape}"})

                            # Now, num_id_val_gui is the integer ID we want to find in the events array's 3rd column
                            if events.size > 0 and num_id_val_gui in events[:, 2]:
                                try:
                                    # When epoching, event_id takes the form {' Epoch_Label_You_Want ': Int_ID_from_Events_Array }
                                    # Here, lbl is the User's Condition Label, and num_id_val_gui is the Int_ID.
                                    epochs = mne.Epochs(
                                        raw_proc, events,
                                        event_id={lbl: num_id_val_gui},
                                        tmin=params['epoch_start'],
                                        tmax=params['epoch_end'],
                                        preload=True, verbose=False, baseline=None, on_missing='warn'
                                    )
                                    gui_queue.put({'type': 'log',
                                                   'message': f"DEBUG [{f_name}]: MNE Epochs object created for GUI label '{lbl}'. Length: {len(epochs)}. Events in this obj: {len(epochs.events)}."})

                                    if len(epochs.events) > 0:
                                        gui_queue.put({'type': 'log',
                                                       'message': f"  -> Successfully created {len(epochs.events)} epochs for GUI label '{lbl}' (target Int ID: {num_id_val_gui}) in {f_name}."})
                                        file_epochs[lbl] = [epochs]
                                    else:
                                        gui_queue.put({'type': 'log',
                                                       'message': f"  -> No epochs generated for GUI label '{lbl}' (target Int ID: {num_id_val_gui}) in {f_name} (MNE Epochs object empty or len(epochs.events) was 0)."})

                                except Exception as e_epoch:
                                    gui_queue.put({'type': 'log',
                                                   'message': f"!!! Epoching error for GUI label '{lbl}' (target Int ID: {num_id_val_gui}) in {f_name}: {e_epoch}\n{traceback.format_exc()}"})
                            else:
                                gui_queue.put({'type': 'log',
                                               'message': f"DEBUG [{f_name}]: Target Int ID {num_id_val_gui} for GUI label '{lbl}' not found in the extracted events array (unique IDs found: {np.unique(events[:, 2]) if events.size > 0 else 'empty events array'}). Skipping epoching for this label."})

                        gui_queue.put(
                            {'type': 'log', 'message': f"DEBUG [{f_name}]: Epoching loop for all GUI labels finished."})

                        # 5) OPTIONAL: save preprocessed .fif
                        if params.get('save_preprocessed', False) and raw_proc is not None:
                            p_path = os.path.join(save_folder, f"{os.path.splitext(f_name)[0]}_preproc_raw.fif")
                            try:
                                gui_queue.put({'type': 'log', 'message': f"Saving preprocessed to: {p_path}"})
                                raw_proc.save(p_path, overwrite=True, verbose=False)
                            except Exception as e_save_fif:
                                gui_queue.put({'type': 'log',
                                               'message': f"Warn: Failed to save preprocessed file {p_path}: {e_save_fif}"})

                    except Exception as file_proc_err:  # Catch errors in main try block for this file
                        gui_queue.put({'type': 'log',
                                       'message': f"!!! Error during main processing stages for {f_name} (before post-processing): {file_proc_err}\n{traceback.format_exc()}"})

                    finally:  # For current file processing
                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: Entering finally block for post-processing and cleanup."})
                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: file_epochs before has_valid_data check. Keys: {list(file_epochs.keys()) if file_epochs is not None else 'None'}"})
                        if file_epochs:
                            for lbl_debug, epochs_list_debug in file_epochs.items():
                                if epochs_list_debug and epochs_list_debug[0] and isinstance(epochs_list_debug[0],
                                                                                             mne.Epochs):  # check if list is not empty and first element is Epochs
                                    gui_queue.put({'type': 'log',
                                                   'message': f"  DEBUG [{f_name}]: Label '{lbl_debug}': Epochs obj contains {len(epochs_list_debug[0].events)} events."})
                                else:
                                    gui_queue.put({'type': 'log',
                                                   'message': f"  DEBUG [{f_name}]: Label '{lbl_debug}': No valid Epochs object found in list or list empty."})

                        has_valid_data = False
                        if file_epochs:  # Check if file_epochs dict itself is not None and not empty
                            has_valid_data = any(
                                epochs_list and epochs_list[0] and isinstance(epochs_list[0], mne.Epochs) and hasattr(
                                    epochs_list[0], 'events') and len(epochs_list[0].events) > 0
                                for epochs_list in file_epochs.values()
                            )
                        gui_queue.put(
                            {'type': 'log', 'message': f"DEBUG [{f_name}]: Value of has_valid_data: {has_valid_data}"})

                        if raw_proc is not None and has_valid_data:
                            gui_queue.put({'type': 'log',
                                           'message': f"--- Post‐processing & Saving Excel for {f_name} (has_valid_data is True) ---"})

                            current_file_original_app_data_paths_temp = list(self.data_paths)  # copy
                            current_file_original_app_preprocessed_data_temp = dict(self.preprocessed_data)  # copy

                            self.data_paths = [f_path]
                            self.preprocessed_data = file_epochs

                            try:
                                self.post_process(list(file_epochs.keys()))
                            except Exception as e_post:
                                gui_queue.put({'type': 'log',
                                               'message': f"!!! Post-processing/Excel error for {f_name}: {e_post}\n{traceback.format_exc()}"})
                            finally:
                                self.data_paths = current_file_original_app_data_paths_temp
                                self.preprocessed_data = current_file_original_app_preprocessed_data_temp

                        elif raw_proc is not None and not has_valid_data:
                            gui_queue.put({'type': 'log',
                                           'message': f"Skipping Excel generation for {f_name} as no valid epochs were created (has_valid_data was False)."})
                        elif raw_proc is None:
                            gui_queue.put({'type': 'log',
                                           'message': f"Skipping Excel generation for {f_name} as preprocessed data (raw_proc) is None."})

                        gui_queue.put({'type': 'log', 'message': f"Cleaning up memory for {f_name}..."})
                        if isinstance(file_epochs, dict):
                            for epochs_list_to_del in file_epochs.values():
                                if epochs_list_to_del and epochs_list_to_del[
                                    0] is not None:  # Check list and its first element
                                    if hasattr(epochs_list_to_del[0], '_data') and epochs_list_to_del[
                                        0]._data is not None:
                                        del epochs_list_to_del[0]._data  # Try to free data more explicitly
                                    del epochs_list_to_del[0]
                            file_epochs.clear()
                        del file_epochs
                        if raw_proc is not None: del raw_proc
                        gc.collect()
                        gui_queue.put({'type': 'log', 'message': f"Memory cleanup for {f_name} complete."})

                    gui_queue.put({'type': 'progress', 'value': i + 1})
                # --- End of loop for one file ---

                gui_queue.put({'type': 'done'})  # Signal successful completion of all files

            except Exception as e_thread:  # Catch errors in the main try block of the thread
                gui_queue.put({'type': 'error', 'message': f"Critical error in processing thread: {e_thread}",
                               'traceback': traceback.format_exc()})
                gui_queue.put({'type': 'done'})
            finally:
                # Final restore of app state in case of unhandled exit from loop
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


    # --- Preprocessing Method ---

    def preprocess_raw(self, raw, **params):
            """
            Applies preprocessing steps to the raw MNE object.
            Includes detailed logging for channel dropping.
            """
            # Extract parameters
            downsample_rate = params.get('downsample_rate')
            low_pass = params.get('low_pass')
            high_pass = params.get('high_pass')
            reject_thresh = params.get('reject_thresh')
            ref1 = params.get('ref_channel1')
            ref2 = params.get('ref_channel2')
            max_keep = params.get('max_idx_keep')
            # Use stim_channel from params, falling back to DEFAULT_STIM_CHANNEL if not provided in params
            stim_ch = params.get('stim_channel', DEFAULT_STIM_CHANNEL)

            # Import necessary libraries
            import numpy as np
            from scipy.stats import kurtosis
            import mne
            import traceback
            import os  # For os.path.basename

            # Get filename for logging, handle if raw.filenames is empty or None
            current_filename = "UnknownFile"
            if raw.filenames and raw.filenames[0]:  # Check raw.filenames is not None and not empty
                current_filename = os.path.basename(raw.filenames[0])
            elif hasattr(raw, 'filename') and raw.filename:  # Fallback for some MNE versions/objects
                current_filename = os.path.basename(raw.filename)

            try:
                orig_ch_names = list(raw.info['ch_names'])  # Make a copy
                self.log(f"Preprocessing {len(orig_ch_names)} chans from '{current_filename}'...")
                # === DETAILED DEBUG LOGGING: Initial state ===
                self.log(
                    f"DEBUG [preprocess_raw for {current_filename}]: Initial channel names ({len(orig_ch_names)}): {orig_ch_names}")
                self.log(
                    f"DEBUG [preprocess_raw for {current_filename}]: Expected stim_ch for preservation: '{stim_ch}', max_idx_keep parameter: {max_keep}")
                if stim_ch not in orig_ch_names:
                    self.log(
                        f"DEBUG [preprocess_raw for {current_filename}]: WARNING - Expected stim_ch '{stim_ch}' is NOT in the initial channel list.")
                # === END DEBUG LOGGING ===

                # 1. Initial Reference (e.g., Mastoids)
                if ref1 and ref2 and ref1 in orig_ch_names and ref2 in orig_ch_names:
                    try:
                        self.log(f"Applying reference: Subtract average of {ref1} & {ref2} for {current_filename}...")
                        raw.set_eeg_reference(ref_channels=[ref1, ref2], projection=False, verbose=False)
                        self.log(f"Initial reference applied to {current_filename}.")
                    except Exception as e:
                        self.log(f"Warn: Initial reference failed for {current_filename}: {e}")
                else:
                    self.log(
                        f"Skip initial referencing for {current_filename} (Ref channels '{ref1}', '{ref2}' not found or not specified).")

                # 2. Drop Channels
                current_names_before_drop = list(
                    raw.info['ch_names'])  # Get names after potential re-ref (though unlikely to change names)
                self.log(
                    f"DEBUG [preprocess_raw for {current_filename}]: Channel names BEFORE drop logic ({len(current_names_before_drop)}): {current_names_before_drop}")

                if max_keep is not None and 0 < max_keep < len(current_names_before_drop):
                    channels_to_keep_by_index = current_names_before_drop[:max_keep]
                    self.log(
                        f"DEBUG [preprocess_raw for {current_filename}]: Initial channels selected by index (first {max_keep}): {channels_to_keep_by_index}")

                    final_channels_to_keep = list(channels_to_keep_by_index)  # Start with a copy
                    if stim_ch in current_names_before_drop:
                        if stim_ch not in final_channels_to_keep:
                            final_channels_to_keep.append(stim_ch)
                            self.log(
                                f"DEBUG [preprocess_raw for {current_filename}]: Stim_ch '{stim_ch}' was present in data and explicitly added to keep_channels.")
                        else:
                            self.log(
                                f"DEBUG [preprocess_raw for {current_filename}]: Stim_ch '{stim_ch}' was present and already within the first {max_keep} channels.")
                    else:
                        # This was already logged at the start of the function, but good to be aware here too.
                        self.log(
                            f"DEBUG [preprocess_raw for {current_filename}]: NOTE - Configured stim_ch '{stim_ch}' was NOT FOUND in current channel names before drop logic execution: {current_names_before_drop}.")

                    # Ensure uniqueness (in case stim_ch was already in channels_to_keep_by_index)
                    # and preserve original order as much as possible for the kept channels.
                    unique_set_to_keep = set(final_channels_to_keep)
                    ordered_unique_keep_channels = [name for name in current_names_before_drop if
                                                    name in unique_set_to_keep]

                    channels_to_drop = [ch for ch in current_names_before_drop if
                                        ch not in ordered_unique_keep_channels]

                    self.log(
                        f"DEBUG [preprocess_raw for {current_filename}]: Final list of channels to KEEP ({len(ordered_unique_keep_channels)}): {ordered_unique_keep_channels}")
                    self.log(
                        f"DEBUG [preprocess_raw for {current_filename}]: Final list of channels to DROP ({len(channels_to_drop)}): {channels_to_drop}")

                    if channels_to_drop:
                        self.log(f"Attempting to drop {len(channels_to_drop)} channels from {current_filename}...")
                        raw.drop_channels(channels_to_drop, on_missing='warn')  # on_missing='warn' is safer
                        self.log(f"{len(raw.ch_names)} channels remain in {current_filename} after drop operation.")
                        self.log(
                            f"DEBUG [preprocess_raw for {current_filename}]: Channel names AFTER drop operation: {list(raw.info['ch_names'])}")
                    else:
                        self.log(f"No channels were ultimately selected to be dropped for {current_filename}.")
                else:
                    self.log(
                        f"Skip channel drop based on max_keep for {current_filename} (max_keep is None, 0, or >= num channels). Current channels: {len(current_names_before_drop)}")

                # 3. Downsample (rest of the function remains as previously provided)
                if downsample_rate:
                    sf = raw.info['sfreq']
                    self.log(f"Downsample check for {current_filename}: Curr {sf:.1f}Hz, Tgt {downsample_rate}Hz.")
                    if sf > downsample_rate:
                        resample_window = 'hann'
                        try:
                            raw.resample(downsample_rate, npad="auto", window=resample_window, verbose=False)
                            self.log(f"Resampled {current_filename} to {raw.info['sfreq']:.1f}Hz.")
                        except Exception as resample_err:
                            self.log(f"Warn: Resampling failed for {current_filename}: {resample_err}")
                    else:
                        self.log(f"No downsampling needed for {current_filename}.")
                else:
                    self.log(f"Skip downsample for {current_filename}.")

                # 4. Filter
                l_freq = low_pass if low_pass and low_pass > 0 else None
                h_freq = high_pass
                if l_freq or h_freq:
                    try:
                        low_trans_bw = 0.1;
                        high_trans_bw = 0.1;
                        filter_len_points = 8449
                        self.log(
                            f"Filtering {current_filename} ({l_freq if l_freq else 'DC'}-{h_freq if h_freq else 'Nyq'}Hz) ...")
                        raw.filter(l_freq, h_freq, method='fir', phase='zero-double',
                                   fir_window='hamming', fir_design='firwin',
                                   l_trans_bandwidth=low_trans_bw, h_trans_bandwidth=high_trans_bw,
                                   filter_length=filter_len_points, skip_by_annotation='edge', verbose=False)
                        self.log(f"Filter OK for {current_filename}.")
                    except Exception as e:
                        self.log(f"Warn: Filter failed for {current_filename}: {e}")
                else:
                    self.log(f"Skip filter for {current_filename}.")

                # 5. Kurtosis rejection & interp
                if reject_thresh:
                    self.log(f"Kurtosis rejection for {current_filename} (Z > {reject_thresh})...")
                    bad_k_auto = []
                    eeg_picks_for_kurtosis = mne.pick_types(raw.info, eeg=True, exclude=raw.info['bads'] + (
                        [stim_ch] if stim_ch in raw.ch_names else []))
                    if len(eeg_picks_for_kurtosis) >= 2:
                        data = raw.get_data(picks=eeg_picks_for_kurtosis)
                        k_values = kurtosis(data, axis=1, fisher=True, bias=False);
                        k_values = np.nan_to_num(k_values)
                        proportion_to_cut = 0.1;
                        n_k = len(k_values);
                        trim_count = int(np.floor(n_k * proportion_to_cut))
                        if n_k - 2 * trim_count > 1:
                            k_sorted = np.sort(k_values);
                            k_trimmed = k_sorted[trim_count: n_k - trim_count]
                            m_trimmed, s_trimmed = np.mean(k_trimmed), np.std(k_trimmed)
                            self.log(
                                f"Trimmed Norm for {current_filename}: Mean={m_trimmed:.3f}, Std={s_trimmed:.3f} (N_trimmed={len(k_trimmed)})")
                            if s_trimmed > 1e-9:
                                z_scores_trimmed = (k_values - m_trimmed) / s_trimmed
                                bad_k_indices_in_eeg_picks = np.where(np.abs(z_scores_trimmed) > reject_thresh)[0]
                                ch_names_picked_for_kurtosis = [raw.info['ch_names'][i] for i in eeg_picks_for_kurtosis]
                                bad_k_auto = [ch_names_picked_for_kurtosis[i] for i in bad_k_indices_in_eeg_picks]
                            else:
                                self.log(f"Kurtosis Trimmed Std Dev near zero for {current_filename}.")
                        else:
                            self.log(f"Not enough data for Kurtosis trimmed stats in {current_filename} (N_k={n_k}).")
                        if bad_k_auto:
                            self.log(f"Bad by Kurtosis for {current_filename}: {bad_k_auto}")
                        else:
                            self.log(f"No channels bad by Kurtosis for {current_filename}.")
                    else:
                        self.log(f"Skip Kurtosis for {current_filename} ( < 2 good EEG channels).")
                    new_bads_from_kurtosis = [b for b in bad_k_auto if b not in raw.info['bads']]
                    if new_bads_from_kurtosis: raw.info['bads'].extend(new_bads_from_kurtosis)
                    if raw.info['bads']:
                        self.log(f"Interpolating bads in {current_filename}: {raw.info['bads']}")
                        if raw.get_montage():
                            try:
                                raw.interpolate_bads(reset_bads=True, mode='accurate', verbose=False); self.log(
                                    f"Interpolation OK for {current_filename}.")
                            except Exception as e:
                                self.log(f"Warn: Interpolation failed for {current_filename}: {e}")
                        else:
                            self.log(
                                f"Warn: No montage for {current_filename}, cannot interpolate. Bads remain: {raw.info['bads']}")
                    else:
                        self.log(f"No bads to interpolate in {current_filename}.")
                else:
                    self.log(f"Skip Kurtosis for {current_filename} (no threshold).")

                # 6. Average Reference
                try:
                    self.log(f"Applying average reference to {current_filename}...")
                    eeg_picks_for_ref = mne.pick_types(raw.info, eeg=True, exclude=raw.info['bads'])
                    if len(eeg_picks_for_ref) > 0:
                        raw.set_eeg_reference(ref_channels='average', picks=eeg_picks_for_ref, projection=True,
                                              verbose=False)
                        raw.apply_proj(verbose=False)
                        self.log(f"Average reference applied to {current_filename}.")
                    else:
                        self.log(f"Skip average ref for {current_filename}: No good EEG channels.")
                except Exception as e:
                    self.log(f"Warn: Average reference failed for {current_filename}: {e}")

                self.log(
                    f"Preprocessing OK for {current_filename}. {len(raw.ch_names)} channels, {raw.info['sfreq']:.1f}Hz.")
                # === FINAL DEBUG LOGGING before returning raw_proc ===
                final_ch_names = list(raw.info['ch_names'])
                self.log(
                    f"DEBUG [preprocess_raw for {current_filename}]: Final channel names before returning ({len(final_ch_names)}): {final_ch_names}")
                if stim_ch in final_ch_names:
                    self.log(
                        f"DEBUG [preprocess_raw for {current_filename}]: Expected stim_ch '{stim_ch}' IS PRESENT at the VERY END of preprocessing.")
                else:
                    self.log(
                        f"DEBUG [preprocess_raw for {current_filename}]: CRITICAL! Expected stim_ch '{stim_ch}' IS NOT PRESENT at the VERY END of preprocessing.")
                # === END FINAL DEBUG LOGGING ===
                return raw

            except Exception as e:
                self.log(f"!!! CRITICAL Preprocessing error for {current_filename}: {e}")
                self.log(f"Traceback: {traceback.format_exc()}")
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
