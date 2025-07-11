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

        self.log_textbox = ctk.CTkTextbox(bottom, height=100, wrap="word", state="disabled")
        self.log_textbox.grid(row=0, column=0, columnspan=2, padx=PAD_X, pady=PAD_Y, sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(bottom, orientation="horizontal")
        self.progress_bar.grid(row=1, column=0, columnspan=2, padx=PAD_X, pady=(0, PAD_Y), sticky="ew")
        self.progress_bar.set(0)
        self.progress_bar.grid_remove()

        cf = ctk.CTkFrame(bottom, fg_color="transparent")
        cf.grid(row=2, column=0, columnspan=2, pady=PAD_Y, sticky="e")
        self.start_adv_processing_button = ctk.CTkButton(cf, text="Start Advanced Processing",
                                                         command=self.start_advanced_processing,
                                                         font=ctk.CTkFont(weight="bold"))
        self.start_adv_processing_button.pack(side="left", padx=PAD_X)
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

    def debug(self, message: str) -> None:
        if self.debug_mode:
            self.log(f"[DEBUG] {message}")
            logger.debug(message)

    def add_source_files(self):
        """Prompt the user for EEG files and add them to the source list."""

        files = filedialog.askopenfilenames(
            title="Select EEG Files",
            filetypes=[("EEG files", "*.bdf *.set"), ("All files", "*.*")],
            parent=self,
        )
        if not files:
            return
        if self.debug_mode:
            logger.debug("Selected %d file(s): %s", len(files), files)

        added_count = 0
        for f_path in files:
            if f_path not in self.source_eeg_files:
                self.source_eeg_files.append(f_path)
                added_count += 1

        if self.debug_mode:
            logger.debug("%d new files will be added", added_count)

        if added_count > 0:
            self.source_eeg_files.sort()
            self._update_source_files_listbox()
            self.log(
                f"Added {added_count} source file(s). Total: {len(self.source_eeg_files)}."
            )

    def remove_source_files(self):
        """Remove the files selected in the listbox from the source list."""

        selected_indices = self.source_files_listbox.curselection()
        if not selected_indices:
            self.log("No source files selected to remove.")
            return
        if self.debug_mode:
            logger.debug("Indices selected for removal: %s", selected_indices)

        removed_file_paths = [self.source_eeg_files[i] for i in selected_indices]
        self.source_eeg_files = [f for i, f in enumerate(self.source_eeg_files) if i not in selected_indices]

        if removed_file_paths:
            self._update_source_files_listbox()
            self.log(f"Removed {len(removed_file_paths)} file(s) from source list.")
            self._check_groups_for_removed_files(removed_file_paths)
            if self.debug_mode:
                logger.debug("Removed file paths: %s", removed_file_paths)

    def _update_source_files_listbox(self):
        """Refresh the source files listbox to match ``self.source_eeg_files``."""

        self.source_files_listbox.delete(0, tk.END)
        for f_path in self.source_eeg_files:
            self.source_files_listbox.insert(tk.END, Path(f_path).name)
        if self.debug_mode:
            logger.debug("Source file listbox refreshed with %d entries", len(self.source_eeg_files))

    def _check_groups_for_removed_files(self, removed_paths: List[str]):
        """
        Updated to reflect user's snippet structure while retaining robust logic.
        Removes deleted EEG files from each group’s file_paths and their mapping sources.
        """
        if self.debug_mode:
            logger.debug("Checking groups for removed files: %s", removed_paths)
        updated_any = False  # Renamed from updated_any_group
        affected_indices = []  # Renamed from affected_group_indices

        for idx, group in enumerate(self.defined_groups):  # Using idx, group as per user snippet
            original_file_count = len(group['file_paths'])
            group['file_paths'] = [fp for fp in group['file_paths'] if fp not in removed_paths]

            if len(group['file_paths']) != original_file_count:
                self.log(f"Group '{group['name']}' updated: removed files.")  # Using group['name']
                updated_any = True
                affected_indices.append(idx)  # Using affected_indices
                group['config_saved'] = False

                if 'condition_mappings' in group:
                    new_mappings_for_group = []
                    for mapping_rule in group['condition_mappings']:
                        original_sources_count = len(mapping_rule['sources'])
                        # Prune sources from this rule
                        mapping_rule['sources'] = [
                            src for src in mapping_rule['sources']
                            if src['file_path'] not in removed_paths
                        ]

                        if len(mapping_rule['sources']) != original_sources_count:
                            self.log(
                                f"  Mapping '{mapping_rule['output_label']}' in group '{group['name']}' lost {original_sources_count - len(mapping_rule['sources'])} source(s).")

                        # Only keep the rule if it still has sources
                        if mapping_rule['sources']:
                            new_mappings_for_group.append(mapping_rule)
                        elif original_sources_count > 0:  # It had sources, now it doesn't
                            msg = (f"Mapping rule '{mapping_rule['output_label']}' in group "
                                   f"'{group['name']}' lost all its source files and was removed.")
                            self.log(f"Warning: {msg}")
                            CTkMessagebox.CTkMessagebox(
                                title="Mapping Rule Removed",
                                message=msg,
                                icon="warning",
                                master=self,
                            )

                    group['condition_mappings'] = new_mappings_for_group
                    if not group['condition_mappings']:
                        self.log(f"Group '{group['name']}' has no valid mapping rules left after file removal.")
        if updated_any:
            self._update_groups_listbox()
            if self.selected_group_index is not None and self.selected_group_index in affected_indices:
                self._display_group_configuration()
            self._update_start_processing_button_state()

    def create_new_group(self):
        """Prompt for details and create a new averaging group."""

        if self.debug_mode:
            logger.debug("Creating new averaging group")

        dlg_name = CTkInputDialog(title="New Averaging Group", text="Enter a name for this averaging group:")
        name = dlg_name.get_input()
        if not name or not name.strip():
            self.log("Group creation cancelled.")
            return
        name = name.strip()
        if self.debug_mode:
            logger.debug("Group name entered: %s", name)
        if any(g['name'] == name for g in self.defined_groups):
            CTkMessagebox.CTkMessagebox(
                title="Error",
                message=f"A group named '{name}' already exists.",
                icon="cancel",
                master=self,
            )
            return

        id_dlg = CTkInputDialog(title="Event IDs to Average",
                                text="Enter the event IDs to average within each participant,\nseparated by commas (e.g. 11,12):")
        id_str = id_dlg.get_input()
        if not id_str:
            self.log("Group creation cancelled (no IDs).")
            return
        if self.debug_mode:
            logger.debug("Event IDs input: %s", id_str)
        try:
            ids_to_average = [int(x.strip()) for x in id_str.split(",") if x.strip()]
        except ValueError:
            CTkMessagebox.CTkMessagebox(
                title="Error",
                message="Enter only integers separated by commas.",
                icon="cancel",
                master=self,
            )
            return
        if self.debug_mode:
            logger.debug("Parsed event IDs: %s", ids_to_average)
        if not ids_to_average:
            CTkMessagebox.CTkMessagebox(
                title="Error",
                message="Enter at least one event ID.",
                icon="cancel",
                master=self,
            )
            return

        if not self.source_eeg_files:
            CTkMessagebox.CTkMessagebox(
                title="Error",
                message="No EEG files selected. Add files first.",
                icon="cancel",
                master=self,
            )
            return

        mapping_rule = {'output_label': name, 'sources': []}
        for f_path in self.source_eeg_files:
            for event_id_val in ids_to_average:
                mapping_rule['sources'].append({
                    'file_path': f_path,
                    'original_label': str(event_id_val),
                    'original_id': event_id_val
                })
        if self.debug_mode:
            logger.debug("Mapping rule for group '%s': %s", name, mapping_rule)

        new_grp_data = {
            'name': name,
            'file_paths': list(self.source_eeg_files),
            'condition_mappings': [mapping_rule],
            'averaging_method': self.averaging_method_var.get(),
            'config_saved': True,
            'ui_mapping_rules': []
        }
        self.defined_groups.append(new_grp_data)
        if self.debug_mode:
            logger.debug("New group appended: %s", new_grp_data)
        self._update_groups_listbox()
        self.log(f"Created group '{name}' averaging IDs {ids_to_average} in all {len(self.source_eeg_files)} files.")
        if self.debug_mode:
            logger.debug("Group '%s' created with IDs %s", name, ids_to_average)

        new_group_idx = len(self.defined_groups) - 1
        self.groups_listbox.selection_clear(0, tk.END)
        self.groups_listbox.selection_set(new_group_idx)
        self.on_group_select(None)
        self._update_start_processing_button_state()

    def delete_selected_group(self):
        """Remove the currently selected averaging group."""

        if self.selected_group_index is None:
            self.log("No group selected to delete.")
            return

        group_name_to_delete = self.defined_groups[self.selected_group_index]['name']
        msg_box = CTkMessagebox.CTkMessagebox(
            title="Confirm Delete",
            message=f"Delete group '{group_name_to_delete}'?",
            icon="question",
            option_1="No",
            option_2="Yes",
            master=self,
        )
        if msg_box.get() == "Yes":
            del self.defined_groups[self.selected_group_index]
            self._update_groups_listbox()
            self.log(f"Deleted group: {group_name_to_delete}")
            self.selected_group_index = None
            self._clear_group_config_display()
            self._update_start_processing_button_state()
            if self.debug_mode:
                logger.debug("Group '%s' deleted", group_name_to_delete)

    def rename_selected_group(self) -> None:
        """Prompt the user to rename the currently selected group."""

        if self.selected_group_index is None:
            self.log("No group selected to rename.")
            return

        current_name = self.defined_groups[self.selected_group_index]['name']
        dlg = CTkInputDialog(
            title="Rename Averaging Group",
            text=f"Enter a new name for '{current_name}':",
        )
        new_name = dlg.get_input()
        if not new_name or not new_name.strip():
            return
        new_name = new_name.strip()

        # ensure name is unique
        for i, grp in enumerate(self.defined_groups):
            if i != self.selected_group_index and grp['name'] == new_name:
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message=f"A group named '{new_name}' already exists.",
                    icon="cancel",
                    master=self,
                )
                return

        self.defined_groups[self.selected_group_index]['name'] = new_name
        self.defined_groups[self.selected_group_index]['config_saved'] = False
        self._update_groups_listbox()
        self._display_group_configuration()
        self.log(f"Renamed group to '{new_name}'.")

    def _update_groups_listbox(self):
        current_selection = self.groups_listbox.curselection()

        self.groups_listbox.delete(0, tk.END)
        for g_data in self.defined_groups:
            status_str = "" if g_data.get('config_saved', False) else " (Unsaved)"
            display_text = f"{g_data['name']} ({len(g_data['file_paths'])} files){status_str}"
            self.groups_listbox.insert(tk.END, display_text)
        if self.debug_mode:
            logger.debug("Groups listbox updated with %d groups", len(self.defined_groups))

        if current_selection and current_selection[0] < self.groups_listbox.size():
            self.groups_listbox.selection_set(current_selection[0])
            self.groups_listbox.activate(current_selection[0])

    def on_group_select(self, event: Optional[tk.Event] = None):
        selected_indices = self.groups_listbox.curselection()
        if not selected_indices:
            return
        if self.debug_mode:
            logger.debug("Group listbox selection changed: %s", selected_indices)

        newly_selected_idx = selected_indices[0]
        if self.selected_group_index != newly_selected_idx:
            self.selected_group_index = newly_selected_idx
            self.log(
                f"Selected group: {self.defined_groups[newly_selected_idx]['name']}"
            )

        self._display_group_configuration()
        self.save_group_config_button.configure(
            state="normal" if not self.defined_groups[newly_selected_idx].get('config_saved', True) else "disabled"
        )

    def _clear_group_config_display(self):
        for widget in self.group_config_frame.winfo_children():
            widget.destroy()
        for widget in self.condition_mapping_frame.winfo_children():
            widget.destroy()
        ctk.CTkLabel(self.condition_mapping_frame, text="Select or create a group.") \
            .pack(padx=PAD_X, pady=PAD_Y)
        self.save_group_config_button.configure(state="disabled")
        self.averaging_method_var.set("Pool Trials")

    def _display_group_configuration(self):
        self._clear_group_config_display()
        idx = self.selected_group_index
        if idx is None or idx >= len(self.defined_groups):
            return
        if self.debug_mode:
            logger.debug("Displaying configuration for group index %s", idx)

        group_data = self.defined_groups[idx]
        ctk.CTkLabel(self.group_config_frame, text=f"Group Name: {group_data['name']}", font=ctk.CTkFont(weight="bold")) \
            .pack(anchor="w", padx=PAD_X, pady=PAD_Y)

        files_display_text = "\n".join(
            Path(fp).name for fp in group_data['file_paths']
        )
        if not files_display_text:
            files_display_text = "No files currently in this group."
        ctk.CTkLabel(self.group_config_frame, text="Files in this group:\n" + files_display_text, justify=tk.LEFT) \
            .pack(anchor="w", padx=PAD_X)

        for widget in self.condition_mapping_frame.winfo_children():
            widget.destroy()

        if group_data.get('condition_mappings'):
            mapping_rule = group_data['condition_mappings'][0]
            ctk.CTkLabel(self.condition_mapping_frame,
                         text=f"Averaging Rule: Output Label '{mapping_rule['output_label']}'",
                         font=ctk.CTkFont(weight="bold")) \
                .pack(anchor="w", padx=PAD_X, pady=(PAD_Y, 0))

            ids_averaged = sorted(list(set(src['original_id'] for src in mapping_rule['sources'])))
            ctk.CTkLabel(self.condition_mapping_frame,
                         text=f"  Averages Event IDs: {', '.join(map(str, ids_averaged))} across all files in group.") \
                .pack(anchor="w", padx=PAD_X)
        else:
            ctk.CTkLabel(self.condition_mapping_frame, text="No mapping rules defined for this group.") \
                .pack(anchor="w", padx=PAD_X)

        self.averaging_method_var.set(group_data.get('averaging_method', 'Pool Trials'))
        self.save_group_config_button.configure(state="normal" if not group_data.get('config_saved') else "disabled")

    def _update_current_group_avg_method(self):
        idx = self.selected_group_index
        if idx is None:
            return

        group_data = self.defined_groups[idx]
        new_method = self.averaging_method_var.get()
        if group_data.get('averaging_method') != new_method:
            group_data['averaging_method'] = new_method
            group_data['config_saved'] = False
            self.log(f"Averaging method for '{group_data['name']}' changed to '{new_method}'. Needs re-saving.")
            if self.debug_mode:
                logger.debug("Group '%s' averaging method set to %s", group_data['name'], new_method)
            self._update_groups_listbox()
            self._update_start_processing_button_state()
            self.save_group_config_button.configure(state="normal")

    def _update_start_processing_button_state(self):
        all_groups_valid_and_saved = False
        if self.defined_groups:
            all_groups_valid_and_saved = all(
                g.get('config_saved') and g.get('file_paths') and g.get('condition_mappings')
                for g in self.defined_groups
            )

        button_state = "normal" if all_groups_valid_and_saved else "disabled"
        if hasattr(self, 'start_adv_processing_button'):
            self.start_adv_processing_button.configure(state=button_state)

    def _thread_target_wrapper(self,
                               defined_groups_arg,
                               main_app_params_arg,
                               load_file_method_arg,
                               preprocess_raw_method_arg,
                               external_post_process_func_arg,
                               output_directory_arg,
                               pid_extraction_func_arg,
                               log_callback_arg,
                               progress_callback_arg,
                               stop_event_arg):
        if self.debug_mode:
            logger.debug("Processing thread wrapper started")
        try:
            run_advanced_averaging_processing(
                defined_groups_arg,
                main_app_params_arg,
                load_file_method_arg,
                preprocess_raw_method_arg,
                external_post_process_func_arg,
                output_directory_arg,
                pid_extraction_func_arg,
                log_callback_arg,
                progress_callback_arg,
                stop_event_arg
            )
        except Exception:
            # Log the full traceback from the crashed thread
            detailed_error = traceback.format_exc()
            # Ensure logging happens in the main GUI thread using self.after
            error_message = (f"!!! CRITICAL THREAD ERROR !!!\n"
                             f"Target function 'run_advanced_averaging_processing' crashed unexpectedly:\n"
                             f"{detailed_error}")
            self.after(0, self.log, error_message)
        finally:
            if self.debug_mode:
                logger.debug("Processing thread wrapper exiting")
        # The _check_processing_thread method will handle UI finalization
        # when this wrapper function (and thus the thread) completes.

    def _validate_processing_setup(self) -> Optional[tuple]:
        """Validate configuration before launching the processing thread.

        Returns
        -------
        tuple[Dict[str, Any], str] or None
            ``(main_app_params, output_directory)`` if validation succeeds,
            otherwise ``None``.
        """


        # 0) If the main app hasn't yet validated its entries, do so now.
        self.debug(
            f"[PARAM_CHECK] Initial check: self.master_app has 'validated_params' attribute: {hasattr(self.master_app, 'validated_params')}" )
        if hasattr(self.master_app, 'validated_params'):
            current_params = getattr(self.master_app, 'validated_params', 'Attribute exists but is None')
            self.debug(
                f"[PARAM_CHECK] Initial self.master_app.validated_params (type: {type(current_params)}): {current_params}")

        main_app_params_are_set = bool(getattr(self.master_app, "validated_params", None))

        if not main_app_params_are_set:
            self.debug(
                "[PARAM_CHECK] Main app's 'validated_params' not set or is None/empty. Attempting to call _validate_inputs().")
            ok = False
            if hasattr(self.master_app, "_validate_inputs"):
                self.debug("[PARAM_CHECK] Calling self.master_app._validate_inputs()...")
                try:
                    ok = self.master_app._validate_inputs()
                    self.debug(f"[PARAM_CHECK] self.master_app._validate_inputs() returned: {ok}")

                    if hasattr(self.master_app, 'validated_params'):
                        current_params_after_call = getattr(self.master_app, 'validated_params', 'Attribute exists but is None')
                        self.debug(
                            f"[PARAM_CHECK] After _validate_inputs(), self.master_app.validated_params (type: {type(current_params_after_call)}): {current_params_after_call}")
                        main_app_params_are_set = bool(current_params_after_call)
                    else:
                        self.debug(
                            "[PARAM_CHECK] After _validate_inputs(), self.master_app still does not have 'validated_params' attribute.")
                        main_app_params_are_set = False

                except Exception as e:
                    self.debug(f"[PARAM_CHECK] Error during self.master_app._validate_inputs(): {traceback.format_exc()}")
                    CTkMessagebox.CTkMessagebox(
                        title="Error",
                        message=f"An error occurred while validating main application inputs: {e}",
                        icon="cancel",
                        master=self,
                    )
                    return None
            else:
                self.debug(
                    "[PARAM_CHECK] Warning: Main app does not have a '_validate_inputs' method, and 'validated_params' was not already set.")

            if not ok and not main_app_params_are_set:
                self.debug(
                    "[PARAM_CHECK] Main app input validation failed or was not performed, and parameters are still not set.")
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message="Main application parameters could not be validated or are missing. Please check the main app settings and ensure they are confirmed/applied.",
                    icon="cancel",
                    master=self,
                )
                return None
            elif ok and not main_app_params_are_set:
                self.debug(
                    "[PARAM_CHECK] Warning: _validate_inputs returned True, but validated_params is still not set or is None/empty.")
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message="Main app validation reported success, but parameters are missing. Please check the main app's _validate_inputs method.",
                    icon="cancel",
                    master=self,
                )
                return None


        if not self.defined_groups:
            CTkMessagebox.CTkMessagebox(
                title="Error",
                message="No averaging groups defined.",
                icon="cancel",
                master=self,
            )
            return None

        for i, group in enumerate(self.defined_groups):
            if not group.get("config_saved", False):
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message=f"Group '{group['name']}' has unsaved changes. Please save it first.",
                    icon="cancel",
                    master=self,
                )
                self.groups_listbox.selection_set(i)
                self.on_group_select(None)
                return None
            if not group.get("file_paths"):
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message=f"Group '{group['name']}' contains no files.",
                    icon="cancel",
                    master=self,
                )
                self.groups_listbox.selection_set(i)
                self.on_group_select(None)
                return None
            if not group.get("condition_mappings"):
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message=f"Group '{group['name']}' has no mapping rules defined.",
                    icon="cancel",
                    master=self,
                )
                self.groups_listbox.selection_set(i)
                self.on_group_select(None)
                return None


        main_app_params = getattr(self.master_app, 'validated_params', None)

        self.debug(f"[PARAM_CHECK] Final fetched main_app_params to be used for processing: {main_app_params}")

        if main_app_params is None or not main_app_params:
            self.debug("[PARAM_CHECK] Critical Error: main_app_params is None or empty after validation attempts.")
            CTkMessagebox.CTkMessagebox(
                title="Critical Error",
                message="Could not retrieve necessary parameters from the main application. Processing cannot start.",
                icon="cancel",
                master=self,
            )
            return None

        if not isinstance(main_app_params, dict):
            self.debug(
                f"[PARAM_CHECK] Critical Error: main_app_params is not a dictionary (type: {type(main_app_params)}).")
            CTkMessagebox.CTkMessagebox(
                title="Critical Error",
                message=f"Main application parameters are not in the expected format (should be a dictionary, but got {type(main_app_params)}).",
                icon="cancel",
                master=self,
            )
            return None

        save_folder_path_obj = getattr(self.master_app, "save_folder_path", None)
        if save_folder_path_obj is None or not hasattr(save_folder_path_obj, "get"):
            CTkMessagebox.CTkMessagebox(
                title="Error",
                message="Main application output folder path is not configured.",
                icon="cancel",
                master=self,
            )
            return None

        output_directory = save_folder_path_obj.get()
        if not output_directory:
            CTkMessagebox.CTkMessagebox(
                title="Error",
                message="Main application output folder path is missing.",
                icon="cancel",
                master=self,
            )
            return None

        if run_advanced_averaging_processing is None or _external_post_process_actual is None:
            CTkMessagebox.CTkMessagebox(
                title="Critical Error",
                message="Core processing module or post_process function not loaded.",
                icon="cancel",
                master=self,
            )
            return None

        return main_app_params, output_directory

    def _launch_processing_thread(self, main_app_params: Dict[str, Any], output_directory: str) -> None:
        """Start the background thread that performs advanced averaging."""

        self.log("All configurations validated. Starting processing thread...")
        if self.debug_mode:
            logger.debug("Launching processing thread with %d groups", len(self.defined_groups))
        self.progress_bar.grid()
        self.progress_bar.set(0)
        self.start_adv_processing_button.configure(state="disabled")
        self.close_button.configure(state="disabled")
        self._stop_requested.clear()

        load_file_method = self.master_app.load_eeg_file
        preprocess_raw_method = self.master_app.preprocess_raw

        self.processing_thread = threading.Thread(
            target=self._thread_target_wrapper,
            args=(
                self.defined_groups,
                main_app_params,
                load_file_method,
                preprocess_raw_method,
                _external_post_process_actual,
                output_directory,
                self._extract_pid_for_group,
                lambda msg: self.after(0, self.log, msg),
                lambda val: self.after(0, self.progress_bar.set, val),
                self._stop_requested,
            ),
            daemon=True,
        )
        self.processing_thread.start()
        if self.debug_mode:
            logger.debug("Background processing thread started")
        self.after(100, self._check_processing_thread)

    def start_advanced_processing(self) -> None:
        """Validate configuration and spawn the processing thread."""

        self.log("=" * 30 + "\nAttempting to Start Advanced Processing...")
        if self.debug_mode:
            logger.debug("Starting advanced processing validation")

        validation = self._validate_processing_setup()
        if not validation:
            return
        if self.debug_mode:
            logger.debug("Validation successful")

        main_app_params, output_directory = validation
        self._launch_processing_thread(main_app_params, output_directory)

    def _check_processing_thread(self):
        if self.processing_thread and self.processing_thread.is_alive():
            if self.debug_mode:
                logger.debug("Processing thread still running")
            self.after(100, self._check_processing_thread)
        else:
            if not self._stop_requested.is_set() and \
                    hasattr(self, 'close_button') and self.close_button.winfo_exists() and \
                    self.close_button.cget('state') == "disabled":
                self.log("Processing thread has finished.")
                self._finalize_processing_ui_state()

    def _finalize_processing_ui_state(self):
        if self.debug_mode:
            logger.debug("Finalizing UI state after processing")
        if hasattr(self, 'progress_bar') and self.progress_bar.winfo_exists():
            self.progress_bar.set(0)
            self.progress_bar.grid_remove()

        if hasattr(self, 'close_button') and self.close_button.winfo_exists():
            self.close_button.configure(state="normal")

        self._update_start_processing_button_state()

        if not self._stop_requested.is_set():
            self.log("Ready for next advanced analysis.")

        self._stop_requested.clear()
        self.processing_thread = None

    def _extract_pid_for_group(self, group_data: Dict[str, Any]) -> str:
        """Return a participant identifier extracted from a group's first file."""

        if self.debug_mode:
            logger.debug("Extracting PID for group")

        file_paths = group_data.get('file_paths', [])
        if not file_paths:
            return "UnknownPID"

        base_name = Path(file_paths[0]).stem  # e.g., "mooney_P1"

        # Primary Regex (should capture "P1" from "mooney_P1" or "P1_mooney" etc.)
        pid_regex_primary = r"\b(P\d+|S\d+|Sub\d+)\b"  # Added S\d+ as common alternative
        match = re.search(pid_regex_primary, base_name, re.IGNORECASE)
        if match:
            return match.group(1).upper()  # e.g., "P1"

        # Fallback 1: Check for patterns like "name_P1" or "name_S1"
        # This is useful if the primary regex \b boundary fails for some reason with underscores
        if '_' in base_name:
            parts = base_name.split('_')
            for part in parts:  # Check all parts, e.g., last part or any part
                if re.fullmatch(r"(P\d+|S\d+|Sub\d+)", part, re.IGNORECASE):
                    return part.upper()

        # Fallback 2: Original cleanup logic (less precise for getting "P1" from "mooneyP1")
        # This will turn "mooney_P1" into "mooneyP1" if above failed.
        cleaned_pid = re.sub(r"(_unamb|_ambig|_mid|_run\d*|_sess\d*|_task\w*|_eeg|_raw|_preproc|_ica).*", "", base_name,
                             flags=re.IGNORECASE)
        cleaned_pid = re.sub(r"[^A-Za-z0-9_]", "", cleaned_pid)  # Allow underscore in initial cleaned version

        # If after initial cleanup, it still looks like "text_P1", try to get "P1"
        if '_' in cleaned_pid:
            parts = cleaned_pid.split('_')
            for part in parts:
                if re.fullmatch(r"(P\d+|S\d+|Sub\d+)", part, re.IGNORECASE):
                    return part.upper()

        # Final cleanup if no P<number> pattern was extracted
        cleaned_pid_alphanum_only = re.sub(r"[^A-Za-z0-9]", "", cleaned_pid)
        result_pid = cleaned_pid_alphanum_only if cleaned_pid_alphanum_only else base_name
        if self.debug_mode:
            logger.debug("Extracted PID: %s", result_pid)
        return result_pid

    def _on_close(self):
        if self.processing_thread and self.processing_thread.is_alive():
            msg_box = CTkMessagebox.CTkMessagebox(
                title="Confirm Close",
                message="Processing is ongoing. Stop and close?",
                icon="question",
                option_1="No",
                option_2="Yes",
                master=self,
            )
            if msg_box.get() == "Yes":
                self._stop_requested.set()
                self.log("Stop requested. Waiting for thread to terminate gracefully...")
                self.after(1000, self._force_destroy)
            else:
                return
        else:
            if self.debug_mode:
                logger.debug("Window closed without active processing")
            self.destroy()

    def _force_destroy(self):
        if self.processing_thread and self.processing_thread.is_alive():
            self.log("Thread still active after timeout. Forcing close.")
            if self.debug_mode:
                logger.debug("Force destroying window while thread active")
        self.destroy()


if __name__ == "__main__":
    root = ctk.CTk()


    class DummyMasterApp(ctk.CTk):
        def __init__(self):
            super().__init__()
            self.withdraw()
            self.validated_params = {
                "low_pass": 0.1, "high_pass": 50,
                "epoch_start": -1, "epoch_end": 2,
                "stim_channel": "Status"
            }
            self.save_folder_path = tk.StringVar(
                value=str(Path(os.getcwd()) / "test_adv_output_standalone")
            )
            try:
                os.makedirs(self.save_folder_path.get(), exist_ok=True)
            except Exception as e:
                logger.error("Error creating dummy output dir for test: %s", e)
            self.DEFAULT_STIM_CHANNEL = "Status"

        def log(self, message):
            logger.info("[DummyMasterLog] %s", message)

        def load_eeg_file(self, filepath):
            logger.info("DummyLoad: %s", filepath)
            return "dummy_raw_obj_for_test"

        def preprocess_raw(self, raw, **params):
            logger.info("DummyPreproc of '%s' with %s", raw, params)
            return "dummy_proc_raw_obj_for_test"


    try:
        dummy_master_app = DummyMasterApp()
        if run_advanced_averaging_processing is None:
            logger.critical(
                "CRITICAL ERROR: advanced_analysis_core.py (run_advanced_averaging_processing) could not be imported. Processing will fail.")

        advanced_window = AdvancedAnalysisWindow(master=dummy_master_app)
        dummy_master_app.mainloop()
    except Exception:
        logger.error("Error in __main__ of advanced_analysis.py: %s", traceback.format_exc())

