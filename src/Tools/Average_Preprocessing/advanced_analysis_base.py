# ruff: noqa
# advanced_analysis.py
"""GUI window for advanced averaging of multiple EEG files.

This module defines :class:`AdvancedAnalysisWindow`, a stand-alone window used
to configure and launch averaging of preprocessed EEG data from multiple files.
Users can group source files together, choose an averaging method and then
initiate processing via :mod:`advanced_analysis_core`.
"""

import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
from customtkinter import CTkInputDialog
import CTkMessagebox
import os
import json
from pathlib import Path
import re
import threading
from typing import List, Dict, Any, Optional
import traceback
import logging

from Main_App.settings_manager import SettingsManager

logger = logging.getLogger(__name__)

# Shared constants (with fallbacks)
try:
    from config import (
        PAD_X, PAD_Y, CORNER_RADIUS, ENTRY_WIDTH,
        BUTTON_WIDTH as CONFIG_BUTTON_WIDTH,
        ADV_ENTRY_WIDTH as CONFIG_ADV_ENTRY_WIDTH,
        ADV_LABEL_ID_ENTRY_WIDTH as CONFIG_ADV_LABEL_ID_ENTRY_WIDTH,
        ADV_ID_ENTRY_WIDTH as CONFIG_ADV_ID_ENTRY_WIDTH
    )

    BUTTON_WIDTH = CONFIG_BUTTON_WIDTH
    ADV_ENTRY_WIDTH = CONFIG_ADV_ENTRY_WIDTH
    ADV_LABEL_ID_ENTRY_WIDTH = CONFIG_ADV_LABEL_ID_ENTRY_WIDTH
    ADV_ID_ENTRY_WIDTH = CONFIG_ADV_ID_ENTRY_WIDTH
except ImportError:
    PAD_X, PAD_Y, CORNER_RADIUS, ENTRY_WIDTH = 5, 5, 8, 120
    BUTTON_WIDTH, ADV_ENTRY_WIDTH = 180, ENTRY_WIDTH
    ADV_LABEL_ID_ENTRY_WIDTH, ADV_ID_ENTRY_WIDTH = int(ENTRY_WIDTH * 1.5), int(ENTRY_WIDTH * 0.5)

# Core processing
try:
    # Keep relative import for a module in the same package
    from .advanced_analysis_core import run_advanced_averaging_processing

    # CORRECTED: Use ABSOLUTE import from src root for post_process
    from Main_App.post_process import post_process as _external_post_process_actual

except ImportError as e:
    # Keep the error handling for robustness
    run_advanced_averaging_processing = None
    _external_post_process_actual = None
    # You might want to update this message slightly to be more general
    logger.error("ERROR importing core components for Advanced Analysis: %s", e)


def create_themed_listbox(parent: ctk.CTkBaseClass, **kwargs) -> tk.Listbox:
    """Creates a tk.Listbox styled to match CTk."""
    appearance = ctk.get_appearance_mode()
    theme = ctk.ThemeManager.theme

    # Helper to safely get theme colors
    def get_color(component: str, property_key: str) -> str:
        try:
            return theme[component][property_key][appearance]
        except TypeError:  # Fallback for older theme structures if colors are tuples
            idx = 0 if appearance == "Light" else 1
            return theme[component][property_key][idx]
        except KeyError:
            logger.warning(
                "Theme color for %s.%s not found for mode %s.",
                component,
                property_key,
                appearance,
            )

        default_bg = "white" if appearance == "Light" else "#2B2B2B"
        default_fg = "black" if appearance == "Light" else "white"
        if "background" in property_key or "fg_color" in property_key:
            return default_bg
        return default_fg

    return tk.Listbox(
        parent,
        background=get_color("CTkFrame", "fg_color"),
        fg=get_color("CTkLabel", "text_color"),
        highlightbackground=get_color("CTkFrame", "border_color"),
        highlightcolor=get_color("CTkButton", "fg_color"),
        selectbackground=get_color("CTkButton", "hover_color"),
        selectforeground=get_color("CTkButton", "text_color"),
        borderwidth=0, highlightthickness=1, activestyle="none", **kwargs)


def attach_tooltip(widget: ctk.CTkBaseClass, text: str):
    """Attach a tooltip to ``widget`` with ``text`` if possible."""
    try:  # Prefer CTkToolTip from customtkinter if available
        tooltip = ctk.CTkToolTip(widget, message=text)
    except Exception:  # Fallback simple tooltip implementation
        tooltip = tk.Toplevel(widget)
        tooltip.withdraw()
        tooltip.overrideredirect(True)
        label = ctk.CTkLabel(tooltip, text=text)
        label.pack(padx=2, pady=2)

        def on_enter(_):
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + 20
            tooltip.geometry(f"+{x}+{y}")
            tooltip.deiconify()

        def on_leave(_):
            tooltip.withdraw()

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)
    return tooltip


class AdvancedAnalysisWindow(ctk.CTkToplevel):
    """Toplevel window for advanced averaging analysis."""

    def __init__(self, master: ctk.CTkBaseClass):
        super().__init__(master)
        # Keep this window above its parent
        self.transient(master)
        self.master_app = master
        self.debug_mode = SettingsManager().debug_enabled()
        self.title("Advanced Averaging Analysis")

        # Respect custom window dimensions from settings if available
        default_size = "1050x850"
        size_str = default_size
        if hasattr(master, "settings"):
            try:
                size_str = master.settings.get("gui", "advanced_size", default_size)
            except Exception:
                size_str = default_size

        self.geometry(size_str)
        if self.debug_mode:
            logger.debug("Advanced window geometry set to %s", size_str)

        # Try to parse width/height from the size string to set a matching
        # ``minsize``.  Fall back to previous defaults if parsing fails.
        try:
            width, height = [int(x) for x in re.split("[xX]", size_str)]
            self.minsize(width, height)
        except Exception:
            self.minsize(950, 750)

        # Ensure this window opens above the main application
        self.lift()
        self.attributes('-topmost', True)
        self.after(0, lambda: self.attributes('-topmost', False))
        # Give the window focus so it appears above the main GUI
        self.focus_force()

        self.source_eeg_files: List[str] = []
        self.defined_groups: List[Dict[str, Any]] = []
        self.selected_group_index: Optional[int] = None
        self.processing_thread: Optional[threading.Thread] = None
        self._stop_requested = threading.Event()
        self._tooltips = []

        self._build_ui()
        if self.debug_mode:
            logger.debug("UI built; initializing main app parameter checks")
        self.log("Advanced Averaging Analysis window initialized.")
        self._check_main_app_params()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._center_window)
        self._update_start_processing_button_state()

    def _check_main_app_params(self) -> None:
        """Warn only if main app params/output folder attributes are missing or None."""
        # Check for the existence of validated_params; warn only if it's completely absent or None
        params = getattr(self.master_app, 'validated_params', None)
        if params is None:
            self.log("Warning: Main app's parameters not set. Processing may fail.")

        # Check for the save_folder_path attribute; warn only if it's missing or not providing a .get() method
        save_path_obj = getattr(self.master_app, 'save_folder_path', None)
        if save_path_obj is None or not hasattr(save_path_obj, 'get'):
            self.log("Warning: Main app's output folder path not configured. Processing will fail.")

    def save_current_group_config(self) -> bool:
        """Saves the current group's configuration, primarily for averaging method changes."""
        idx = self.selected_group_index
        if idx is None:
            self.log("No group selected to save configuration for.")
            return False

        group = self.defined_groups[idx]
        group["config_saved"] = True
        self.log(
            f"Configuration (averaging method: {group['averaging_method']}) confirmed for group '{group['name']}'.")
        if self.debug_mode:
            logger.debug("Group '%s' configuration saved", group['name'])
        self._update_groups_listbox()
        self._update_start_processing_button_state()
        self.save_group_config_button.configure(state="disabled")
        CTkMessagebox.CTkMessagebox(
            title="Configuration Saved",
            message=f"Configuration for group '{group['name']}' has been saved.",
            icon="info",
            master=self,
        )
        return True

    def _build_ui(self):
        """Create all UI elements."""
        self.grid_columnconfigure(0, weight=1, minsize=350)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        left = ctk.CTkFrame(self, corner_radius=CORNER_RADIUS)
        left.grid(row=0, column=0, padx=PAD_X, pady=PAD_Y, sticky="nsew")
        left.grid_rowconfigure(1, weight=1)
        left.grid_rowconfigure(4, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Source EEG Files", font=ctk.CTkFont(weight="bold")) \
            .grid(row=0, column=0, padx=PAD_X, pady=PAD_Y, sticky="w")
        self.source_files_listbox = create_themed_listbox(left, selectmode=tk.EXTENDED, exportselection=False)
        self.source_files_listbox.grid(row=1, column=0, padx=PAD_X, pady=PAD_Y, sticky="nsew")

        sb = ctk.CTkFrame(left, fg_color="transparent")
        sb.grid(row=2, column=0, pady=PAD_Y, sticky="ew")
        ctk.CTkButton(sb, text="Add Files...", command=self.add_source_files, width=BUTTON_WIDTH) \
            .pack(side="left", padx=PAD_X, expand=True)
        ctk.CTkButton(sb, text="Remove Selected", command=self.remove_source_files, width=BUTTON_WIDTH) \
            .pack(side="left", padx=PAD_X, expand=True)

        ctk.CTkLabel(left, text="Defined Averaging Groups", font=ctk.CTkFont(weight="bold")) \
            .grid(row=3, column=0, padx=PAD_X, pady=(PAD_Y * 2, PAD_Y), sticky="w")
        self.groups_listbox = create_themed_listbox(left, exportselection=False)
        self.groups_listbox.grid(row=4, column=0, padx=PAD_X, pady=PAD_Y, sticky="nsew")
        self.groups_listbox.bind("<<ListboxSelect>>", self.on_group_select)

        gb = ctk.CTkFrame(left, fg_color="transparent")
        gb.grid(row=5, column=0, pady=PAD_Y, sticky="ew")
        ctk.CTkButton(gb, text="Create New Group", command=self.create_new_group, width=BUTTON_WIDTH) \
            .pack(side="left", padx=PAD_X, expand=True)
        ctk.CTkButton(gb, text="Rename Group", command=self.rename_selected_group, width=BUTTON_WIDTH) \
            .pack(side="left", padx=PAD_X, expand=True)
        ctk.CTkButton(gb, text="Delete Group", command=self.delete_selected_group, width=BUTTON_WIDTH) \
            .pack(side="left", padx=PAD_X, expand=True)

        right = ctk.CTkFrame(self, corner_radius=CORNER_RADIUS)
        right.grid(row=0, column=1, padx=(0, PAD_X), pady=PAD_Y, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(right, text="Group Configuration", font=ctk.CTkFont(weight="bold")) \
            .grid(row=0, column=0, padx=PAD_X, pady=PAD_Y, sticky="w")
        self.group_config_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.group_config_frame.grid(row=1, column=0, padx=PAD_X, pady=PAD_Y, sticky="new")
        self.group_config_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="Condition Mapping for Selected Group", font=ctk.CTkFont(weight="bold")) \
            .grid(row=2, column=0, padx=PAD_X, pady=(PAD_Y * 2, PAD_Y), sticky="w")
        self.condition_mapping_frame = ctk.CTkScrollableFrame(right,
                                                              label_text="Define how conditions are averaged for this group")
        self.condition_mapping_frame.grid(row=3, column=0, padx=PAD_X, pady=PAD_Y, sticky="nsew")
        if hasattr(self.condition_mapping_frame, "_scrollbar") and self.condition_mapping_frame._scrollbar:
            self.condition_mapping_frame._scrollbar.configure(height=0)
        self.condition_mapping_frame.grid_columnconfigure(0, weight=1)

        avgf = ctk.CTkFrame(right, fg_color="transparent")
        avgf.grid(row=4, column=0, padx=PAD_X, pady=PAD_Y, sticky="ew")
        ctk.CTkLabel(avgf, text="Averaging Method:").pack(side="left", padx=PAD_X)
        self.averaging_method_var = tk.StringVar(value="Pool Trials")
        self.pool_trials_rb = ctk.CTkRadioButton(
            avgf,
            text="Pool Trials",
            variable=self.averaging_method_var,
            value="Pool Trials",
            command=self._update_current_group_avg_method,
        )
        self.pool_trials_rb.pack(side="left", padx=PAD_X)
        self._tooltips.append(
            attach_tooltip(
                self.pool_trials_rb,
                "All epochs from all files are pooled and averaged simultaneously."
                " Gives equal weight to every epoch and is typically preferred.",
            )
        )

        self.avg_of_avgs_rb = ctk.CTkRadioButton(
            avgf,
            text="Average of Averages",
            variable=self.averaging_method_var,
            value="Average of Averages",
            command=self._update_current_group_avg_method,
        )
        self.avg_of_avgs_rb.pack(side="left", padx=PAD_X)
        self._tooltips.append(
            attach_tooltip(
                self.avg_of_avgs_rb,
                "Each file is averaged separately before averaging those results."
                " Gives equal weight to files rather than epochs.",
            )
        )

        self.save_group_config_button = ctk.CTkButton(
            right, text="Save Group Configuration", command=self.save_current_group_config,
            width=int(BUTTON_WIDTH * 1.2)
        )
        self.save_group_config_button.grid(row=5, column=0, padx=PAD_X, pady=PAD_Y * 2, sticky="e")
        self.save_group_config_button.configure(state="disabled")

        bottom = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        bottom.grid(row=1, column=0, columnspan=2, padx=PAD_X, pady=PAD_Y, sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=0)

        self.log_textbox = ctk.CTkTextbox(bottom, height=100, wrap="word", state="disabled")
        self.log_textbox.grid(row=0, column=0, columnspan=2, padx=PAD_X, pady=PAD_Y, sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(bottom, orientation="horizontal")
        self.progress_bar.grid(row=1, column=0, padx=PAD_X, pady=(0, PAD_Y), sticky="ew")
        self.progress_bar.set(0)
        self.progress_bar.grid_remove()

        self.clear_log_button = ctk.CTkButton(bottom, text="Clear Log", command=self.clear_log)
        self.clear_log_button.grid(row=1, column=1, padx=PAD_X, pady=(0, PAD_Y))

        cf = ctk.CTkFrame(bottom, fg_color="transparent")
        cf.grid(row=2, column=0, columnspan=2, pady=PAD_Y, sticky="e")
        self.start_adv_processing_button = ctk.CTkButton(
            cf,
            text="Start Advanced Processing",
            command=self.start_advanced_processing,
            font=ctk.CTkFont(weight="bold"),
        )
        self.start_adv_processing_button.pack(side="left", padx=PAD_X)


        self.stop_processing_button = ctk.CTkButton(
            cf,
            text="Stop",
            command=self.stop_processing,
            font=ctk.CTkFont(weight="bold"),
        )
        self.stop_processing_button.pack(side="left", padx=PAD_X)
        self.stop_processing_button.configure(state="disabled")


        self.close_button = ctk.CTkButton(cf, text="Close", command=self._on_close)
        self.close_button.pack(side="left", padx=PAD_X)

        self._clear_group_config_display()

    def _center_window(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        if self.debug_mode:
            logger.debug("Window centered at %dx%d", w, h)

    def log(self, message: str):
        if hasattr(self, 'log_textbox') and self.log_textbox.winfo_exists():
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert(tk.END, message + "\n")
            self.log_textbox.see(tk.END)
            self.log_textbox.configure(state="disabled")
        if hasattr(self.master_app, "log"):
            self.master_app.log(f"[AdvAnalysis] {message}")

    def clear_log(self) -> None:
        """Clear all text from the log textbox."""
        if hasattr(self, 'log_textbox') and self.log_textbox.winfo_exists():
            self.log_textbox.configure(state="normal")
            self.log_textbox.delete("1.0", tk.END)
            self.log_textbox.configure(state="disabled")

    def debug(self, message: str) -> None:
        if self.debug_mode:
            self.log(f"[DEBUG] {message}")
            logger.debug(message)

