# src/Main_App/ui_setup_panels.py
# -*- coding: utf-8 -*-
"""
Manages the creation of the "Processing Options" and "Preprocessing Parameters"
UI panels for the FPVS Toolbox.
"""
import tkinter as tk
import customtkinter as ctk
import warnings

# Attempt to import constants from config.py
try:
    # When ``main.py`` is executed directly the package hierarchy is not
    # recognised, so ``..config`` cannot be resolved.  Importing from
    # ``config`` allows the app to run both as ``python src/main.py`` and
    # ``python -m src.main``.
    from config import (
        ENTRY_WIDTH,
        PAD_X,
        PAD_Y,
        CORNER_RADIUS,
        # ``DEFAULT_STIM_CHANNEL`` and ``STIM_CHANNEL_ENTRY_WIDTH`` are no
        # longer needed here. ``LABEL_ID_ENTRY_WIDTH`` is only used in the
        # event map manager.
    )
except ImportError:
    warnings.warn(
        "Warning [ui_setup_panels.py]: Could not import from config. "
        "Using fallback UI constants."
    )
    ENTRY_WIDTH = 80
    PAD_X = 5
    PAD_Y = 5
    CORNER_RADIUS = 6


class SetupPanelManager:
    def __init__(self, app_reference, main_parent_frame):
        """
        Initializes the SetupPanelManager.

        Args:
            app_reference: The main FPVSApp instance.
            main_parent_frame: The CTkFrame in FPVSApp where these panels will be placed.
        """
        self.app_ref = app_reference
        self.main_parent_frame = main_parent_frame

        # Get registered validation commands from the main app instance
        self.validate_num_cmd = self.app_ref.validate_num_cmd
        self.validate_int_cmd = self.app_ref.validate_int_cmd

    def create_all_setup_panels(self):
        """Creates and grids both the options and parameters panels."""
        self._create_options_panel()
        self._create_params_panel()

    def _create_options_panel(self):
        """Creates the 'Processing Options' panel (Mode, File Type)."""
        self.app_ref.options_frame = ctk.CTkFrame(self.main_parent_frame)
        self.app_ref.options_frame.grid(row=1, column=0, sticky="ew", padx=PAD_X, pady=PAD_Y)

        ctk.CTkLabel(self.app_ref.options_frame, text="Processing Options",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=PAD_X, pady=(PAD_Y, PAD_Y * 2)
        )

        ctk.CTkLabel(self.app_ref.options_frame, text="Mode:").grid(row=1, column=0, sticky="w", padx=PAD_X, pady=PAD_Y)
        self.app_ref.radio_single = ctk.CTkRadioButton(self.app_ref.options_frame, text="Single File",
                                                       variable=self.app_ref.file_mode,
                                                       value="Single", command=self.app_ref.update_select_button_text,
                                                       corner_radius=CORNER_RADIUS)
        self.app_ref.radio_single.grid(row=1, column=1, padx=PAD_X, pady=PAD_Y, sticky="w")
        self.app_ref.radio_batch = ctk.CTkRadioButton(self.app_ref.options_frame, text="Batch Folder",
                                                      variable=self.app_ref.file_mode,
                                                      value="Batch", command=self.app_ref.update_select_button_text,
                                                      corner_radius=CORNER_RADIUS)
        self.app_ref.radio_batch.grid(row=1, column=2, padx=PAD_X, pady=PAD_Y, sticky="w")

        ctk.CTkLabel(self.app_ref.options_frame, text="File Type:").grid(row=2, column=0, sticky="w", padx=PAD_X,
                                                                         pady=PAD_Y)
        self.app_ref.radio_bdf = ctk.CTkRadioButton(self.app_ref.options_frame, text=".BDF",
                                                    variable=self.app_ref.file_type, value=".BDF",
                                                    corner_radius=CORNER_RADIUS)
        self.app_ref.radio_bdf.grid(row=2, column=1, padx=PAD_X, pady=PAD_Y, sticky="w")
        self.app_ref.radio_set = ctk.CTkRadioButton(self.app_ref.options_frame, text=".set",
                                                    variable=self.app_ref.file_type, value=".set",
                                                    corner_radius=CORNER_RADIUS)
        self.app_ref.radio_set.grid(row=2, column=2, padx=PAD_X, pady=PAD_Y, sticky="w")

    def _create_params_panel(self):
        """Creates the 'Preprocessing Parameters' panel."""
        self.app_ref.params_frame = ctk.CTkFrame(self.main_parent_frame)
        self.app_ref.params_frame.grid(row=2, column=0, sticky="ew", padx=PAD_X, pady=PAD_Y)

        self.app_ref.params_frame.grid_columnconfigure(0, weight=0)
        self.app_ref.params_frame.grid_columnconfigure(1, weight=1)
        self.app_ref.params_frame.grid_columnconfigure(2, weight=0)
        self.app_ref.params_frame.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(self.app_ref.params_frame, text="Preprocessing Parameters",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=PAD_X, pady=(PAD_Y, PAD_Y * 2))

        # Row 1: Low/High pass
        ctk.CTkLabel(self.app_ref.params_frame, text="Low Pass (Hz):").grid(row=1, column=0, sticky="w", padx=PAD_X,
                                                                            pady=PAD_Y)
        self.app_ref.low_pass_entry = ctk.CTkEntry(self.app_ref.params_frame, width=ENTRY_WIDTH, validate='key',
                                                   validatecommand=self.validate_num_cmd, corner_radius=CORNER_RADIUS)
        self.app_ref.low_pass_entry.insert(0, "0.1")
        self.app_ref.low_pass_entry.grid(row=1, column=1, padx=PAD_X, pady=PAD_Y, sticky="w")

        ctk.CTkLabel(self.app_ref.params_frame, text="High Pass (Hz):").grid(row=1, column=2, sticky="w", padx=PAD_X,
                                                                             pady=PAD_Y)
        self.app_ref.high_pass_entry = ctk.CTkEntry(self.app_ref.params_frame, width=ENTRY_WIDTH, validate='key',
                                                    validatecommand=self.validate_num_cmd, corner_radius=CORNER_RADIUS)
        self.app_ref.high_pass_entry.insert(0, "50")
        self.app_ref.high_pass_entry.grid(row=1, column=3, padx=PAD_X, pady=PAD_Y, sticky="w")

        # Row 2: Downsample / Epoch Start
        ctk.CTkLabel(self.app_ref.params_frame, text="Downsample (Hz):").grid(row=2, column=0, sticky="w", padx=PAD_X,
                                                                              pady=PAD_Y)
        self.app_ref.downsample_entry = ctk.CTkEntry(self.app_ref.params_frame, width=ENTRY_WIDTH, validate='key',
                                                     validatecommand=self.validate_num_cmd, corner_radius=CORNER_RADIUS)
        self.app_ref.downsample_entry.insert(0, "256")
        self.app_ref.downsample_entry.grid(row=2, column=1, padx=PAD_X, pady=PAD_Y, sticky="w")

        ctk.CTkLabel(self.app_ref.params_frame, text="Epoch Start (s):").grid(row=2, column=2, sticky="w", padx=PAD_X,
                                                                              pady=PAD_Y)
        self.app_ref.epoch_start_entry = ctk.CTkEntry(self.app_ref.params_frame, width=ENTRY_WIDTH, validate='key',
                                                      validatecommand=self.validate_num_cmd,
                                                      corner_radius=CORNER_RADIUS)
        self.app_ref.epoch_start_entry.insert(0, "-1")
        self.app_ref.epoch_start_entry.grid(row=2, column=3, padx=PAD_X, pady=PAD_Y, sticky="w")

        # Row 3: Reject Thresh / Epoch End
        ctk.CTkLabel(self.app_ref.params_frame, text="Rejection Z-Thresh:").grid(row=3, column=0, sticky="w",
                                                                                 padx=PAD_X, pady=PAD_Y)
        self.app_ref.reject_thresh_entry = ctk.CTkEntry(self.app_ref.params_frame, width=ENTRY_WIDTH, validate='key',
                                                        validatecommand=self.validate_num_cmd,
                                                        corner_radius=CORNER_RADIUS)
        self.app_ref.reject_thresh_entry.insert(0, "5")
        self.app_ref.reject_thresh_entry.grid(row=3, column=1, padx=PAD_X, pady=PAD_Y, sticky="w")

        ctk.CTkLabel(self.app_ref.params_frame, text="Epoch End (s):").grid(row=3, column=2, sticky="w", padx=PAD_X,
                                                                            pady=PAD_Y)
        self.app_ref.epoch_end_entry = ctk.CTkEntry(self.app_ref.params_frame, width=ENTRY_WIDTH, validate='key',
                                                    validatecommand=self.validate_num_cmd, corner_radius=CORNER_RADIUS)
        self.app_ref.epoch_end_entry.insert(0, "125")
        self.app_ref.epoch_end_entry.grid(row=3, column=3, padx=PAD_X, pady=PAD_Y, sticky="w")

        # Row 4: Initial Reference Channels
        ctk.CTkLabel(self.app_ref.params_frame, text="Ref Chan 1:").grid(row=4, column=0, sticky="w", padx=PAD_X,
                                                                         pady=PAD_Y)
        self.app_ref.ref_channel1_entry = ctk.CTkEntry(self.app_ref.params_frame, width=ENTRY_WIDTH,
                                                       corner_radius=CORNER_RADIUS)
        self.app_ref.ref_channel1_entry.insert(0, "EXG1")
        self.app_ref.ref_channel1_entry.grid(row=4, column=1, padx=PAD_X, pady=PAD_Y, sticky="w")

        ctk.CTkLabel(self.app_ref.params_frame, text="Ref Chan 2:").grid(row=4, column=2, sticky="w", padx=PAD_X,
                                                                         pady=PAD_Y)
        self.app_ref.ref_channel2_entry = ctk.CTkEntry(self.app_ref.params_frame, width=ENTRY_WIDTH,
                                                       corner_radius=CORNER_RADIUS)
        self.app_ref.ref_channel2_entry.insert(0, "EXG2")
        self.app_ref.ref_channel2_entry.grid(row=4, column=3, padx=PAD_X, pady=PAD_Y, sticky="w")

        # Row 5: Max Chan Idx Keep / Max Bad Chans (Flag)
        ctk.CTkLabel(self.app_ref.params_frame, text="Max Chan Idx Keep:").grid(row=5, column=0, sticky="w", padx=PAD_X,
                                                                                pady=PAD_Y)
        self.app_ref.max_idx_keep_entry = ctk.CTkEntry(self.app_ref.params_frame, width=ENTRY_WIDTH,
                                                       corner_radius=CORNER_RADIUS,
                                                       validate='key', validatecommand=self.validate_int_cmd)
        self.app_ref.max_idx_keep_entry.insert(0, "64")
        self.app_ref.max_idx_keep_entry.grid(row=5, column=1, padx=PAD_X, pady=PAD_Y, sticky="w")

        ctk.CTkLabel(self.app_ref.params_frame, text="Max Bad Chans (Flag):").grid(row=5, column=2, sticky="w",
                                                                                   padx=PAD_X,
                                                                                   pady=PAD_Y)  # Moved to row 5, col 2
        self.app_ref.max_bad_channels_alert_entry = ctk.CTkEntry(self.app_ref.params_frame, width=ENTRY_WIDTH,
                                                                 corner_radius=CORNER_RADIUS,
                                                                 validate='key', validatecommand=self.validate_int_cmd)
        self.app_ref.max_bad_channels_alert_entry.insert(0, "10")
        self.app_ref.max_bad_channels_alert_entry.grid(row=5, column=3, padx=PAD_X, pady=PAD_Y,
                                                       sticky="w")  # Moved to row 5, col 3

        # Row 6: Save preprocessed FIF option (enabled by default)
        self.app_ref.save_fif_var = tk.BooleanVar(value=True)
        self.app_ref.save_fif_checkbox = ctk.CTkCheckBox(
            self.app_ref.params_frame,
            text="Save Preprocessed .fif",
            variable=self.app_ref.save_fif_var,
            corner_radius=CORNER_RADIUS
        )
        self.app_ref.save_fif_checkbox.grid(row=6, column=0, columnspan=4, sticky="w",
                                            padx=PAD_X, pady=PAD_Y)
