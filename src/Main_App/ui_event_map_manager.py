# src/Main_App/ui_event_map_manager.py
# -*- coding: utf-8 -*-
"""
Manages the UI and basic interactions for the Event ID Mapping section
of the FPVS Toolbox.
"""
import tkinter as tk
import customtkinter as ctk
import traceback
import warnings
from typing import Optional, Dict

try:
    from config import get_ui_constants
    PAD_X, PAD_Y, CORNER_RADIUS, ENTRY_WIDTH, LABEL_ID_ENTRY_WIDTH = get_ui_constants()
except Exception:
    warnings.warn(
        "Warning [ui_event_map_manager.py]: Could not import from config. "
        "Using fallback UI constants."
    )
    PAD_X, PAD_Y, CORNER_RADIUS = 5, 5, 6
    ENTRY_WIDTH = 100
    LABEL_ID_ENTRY_WIDTH = 100  # Condition Label width fallback

NUMERICAL_ID_ENTRY_FIXED_WIDTH = 140  # Fixed width for the ID entry box
REMOVE_BUTTON_WIDTH = 28


class EventMapManager:
    def __init__(self, app_reference, parent_ui_frame):
        self.app_ref = app_reference
        self.parent_ui_frame = parent_ui_frame
        self.validate_int_cmd = self.app_ref.validate_int_cmd  # Get from main app


        self._build_event_map_ui()

    def _build_event_map_ui(self):


        self.parent_ui_frame.grid_columnconfigure(0, weight=1)
        self.parent_ui_frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(self.parent_ui_frame, text="Event Map (Condition Label → Numerical ID)",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=PAD_X, pady=(PAD_Y, PAD_Y))

        # Header Frame for Column Titles
        header_frame = ctk.CTkFrame(self.parent_ui_frame, fg_color="transparent")
        header_frame.grid(row=1, column=0, sticky="ew", padx=PAD_X, pady=(0, 2))

        header_frame.grid_columnconfigure(0, weight=1)  # Condition Label header (takes available space)
        header_frame.grid_columnconfigure(1, weight=0)  # PsychoPy Condition Number header (fixed width)
        header_frame.grid_columnconfigure(2, weight=0)  # Spacer for remove button

        ctk.CTkLabel(header_frame, text="Condition Label", anchor="w").grid(
            row=0, column=0, sticky="ew", padx=(0, PAD_X))
        ctk.CTkLabel(header_frame, text="PsychoPy Condition Number", anchor="w").grid(  # Updated Text
            row=0, column=1, sticky="w", padx=(0, PAD_X))  # Sticky west, width determined by text
        ctk.CTkLabel(header_frame, text="", width=REMOVE_BUTTON_WIDTH).grid(  # Spacer to align with remove buttons
            row=0, column=2, sticky="e", padx=(0, PAD_X))

        self.app_ref.event_map_scroll_frame = ctk.CTkScrollableFrame(self.parent_ui_frame, label_text="")
        self.app_ref.event_map_scroll_frame.grid(row=2, column=0, sticky="nsew", padx=PAD_X, pady=(0, PAD_Y))
        self.app_ref.debug(
            f"[EventMapManager] self.app_ref.event_map_scroll_frame created: {self.app_ref.event_map_scroll_frame}")

        event_map_button_frame = ctk.CTkFrame(self.parent_ui_frame, fg_color="transparent")
        event_map_button_frame.grid(row=3, column=0, sticky="ew", pady=(PAD_Y, 0), padx=PAD_X)

        self.app_ref.detect_button = ctk.CTkButton(event_map_button_frame, text="Detect Trigger IDs",
                                                   command=self.app_ref.detect_and_show_event_ids,
                                                   corner_radius=CORNER_RADIUS)
        self.app_ref.detect_button.pack(side="left", padx=(0, PAD_X))

        self.app_ref.add_map_button = ctk.CTkButton(event_map_button_frame, text="+ Add Condition",
                                                    command=self.add_event_map_entry_from_manager,
                                                    corner_radius=CORNER_RADIUS)
        self.app_ref.add_map_button.pack(side="left")


        # The initial row should not request focus to avoid log spam about a
        # missing widget during startup. Subsequent rows will still request
        # focus when added via the "+ Add Condition" button.
        self._add_new_event_row_ui(focus_new_row=False)


    def add_event_map_entry_from_manager(self, event=None):
        self.app_ref.debug(
            f"[EventMapManager] add_event_map_entry_from_manager called (event: {event is not None}).")
        self._add_new_event_row_ui(event_details=None, focus_new_row=(event is None))

    def _add_new_event_row_ui(self, event_details: Optional[Dict] = None, focus_new_row: bool = True):
        self.app_ref.debug(f"[EventMapManager] _add_new_event_row_ui called. focus_new_row: {focus_new_row}")

        if not hasattr(self.app_ref, 'event_map_scroll_frame') or \
                not self.app_ref.event_map_scroll_frame or \
                not self.app_ref.event_map_scroll_frame.winfo_exists():
            self.app_ref.log("ERROR [EventMapManager]: Cannot add event map row, scroll frame not ready.")
            return
        self.app_ref.debug(f"[EventMapManager] Scroll frame found: {self.app_ref.event_map_scroll_frame}")

        entry_frame = ctk.CTkFrame(self.app_ref.event_map_scroll_frame, fg_color="transparent")
        entry_frame.pack(fill="x", pady=1, padx=1)
        self.app_ref.debug("[EventMapManager] New entry_frame packed into scroll_frame.")

        # Configure columns within this specific entry_frame for alignment
        entry_frame.grid_columnconfigure(0, weight=1)  # Condition Label column (takes available space)
        entry_frame.grid_columnconfigure(1, weight=0)  # Numerical ID column (fixed width)
        entry_frame.grid_columnconfigure(2, weight=0)  # Remove Button column (fixed width)

        label_text = event_details.get("label", "") if event_details else ""
        id_text = str(event_details.get("id", "")) if event_details else ""

        label_entry = ctk.CTkEntry(entry_frame, placeholder_text="Condition Label",
                                   # Use a portion of LABEL_ID_ENTRY_WIDTH or let it expand with column weight
                                   # width=LABEL_ID_ENTRY_WIDTH * 2, # This makes it quite wide
                                   corner_radius=CORNER_RADIUS)
        label_entry.insert(0, label_text)
        label_entry.grid(row=0, column=0, sticky="ew", padx=(0, PAD_X))
        label_entry._entry.bind("<Return>", self._trigger_add_row_and_focus_from_manager)
        label_entry._entry.bind("<KP_Enter>", self._trigger_add_row_and_focus_from_manager)

        id_entry = ctk.CTkEntry(entry_frame, placeholder_text="ID",  # Shorter placeholder
                                width=int(NUMERICAL_ID_ENTRY_FIXED_WIDTH),  # Use the new fixed width
                                validate='key', validatecommand=self.validate_int_cmd,
                                corner_radius=CORNER_RADIUS)
        id_entry.insert(0, id_text)
        id_entry.grid(row=0, column=1, sticky="w", padx=(0, PAD_X))  # Sticky west, fixed width

        remove_btn = ctk.CTkButton(
            entry_frame,
            text="✕",
            width=REMOVE_BUTTON_WIDTH,
            height=REMOVE_BUTTON_WIDTH,
            # Consistent size
            corner_radius=CORNER_RADIUS,

            fg_color="red",
            hover_color="#cc0000",  # Slightly darker on hover
            text_color="white",
            font=ctk.CTkFont(weight="bold"),

            command=lambda ef=entry_frame: self.remove_event_map_entry_from_manager(ef),
        )
        remove_btn.grid(row=0, column=2, sticky="e", padx=(0, PAD_X))  # Add padx to not touch edge
        self.app_ref.debug("[EventMapManager] Widgets for new row created and gridded.")

        new_entry_data = {'frame': entry_frame, 'label': label_entry, 'id': id_entry, 'button': remove_btn}
        self.app_ref.event_map_entries.append(new_entry_data)
        self.app_ref.debug(f"[EventMapManager] New entry appended. Count: {len(self.app_ref.event_map_entries)}")

        if focus_new_row:
            self.app_ref.debug("[EventMapManager] Attempting to focus new label_entry (focus_new_row is True).")
            try:
                def deferred_focus():
                    if label_entry.winfo_exists():
                        label_entry.focus_set()
                        label_entry.select_range(0, tk.END)
                        self.app_ref.debug(
                            "[EventMapManager] Deferred focus and select_range set on label_entry.")
                    else:
                        self.app_ref.debug("[EventMapManager] Deferred focus: label_entry does not exist.")

                self.app_ref.after(50, deferred_focus)
            except Exception as e:
                self.app_ref.log(f"Warning [EventMapManager]: Error during focus attempt: {e}")
        else:
            self.app_ref.debug("[EventMapManager] Skipping focus (focus_new_row is False).")

        def deferred_scroll():
            if self.app_ref.event_map_scroll_frame and self.app_ref.event_map_scroll_frame.winfo_exists():
                self.app_ref.event_map_scroll_frame._parent_canvas.yview_moveto(1.0)
                self.app_ref.debug("[EventMapManager] Deferred scroll of event_map_scroll_frame to bottom.")
            else:
                self.app_ref.debug("[EventMapManager] Deferred scroll: scroll_frame does not exist.")

        self.app_ref.after(100, deferred_scroll)

    def remove_event_map_entry_from_manager(self, entry_frame_to_remove):
        try:
            entry_to_remove_idx = -1
            for i, entry_dict in enumerate(self.app_ref.event_map_entries):
                if entry_dict['frame'] == entry_frame_to_remove:
                    entry_to_remove_idx = i
                    break
            if entry_to_remove_idx != -1:
                if entry_frame_to_remove.winfo_exists():
                    entry_frame_to_remove.destroy()
                del self.app_ref.event_map_entries[entry_to_remove_idx]
                self.app_ref.log("Event map row removed.")
                if not self.app_ref.event_map_entries:
                    self.add_event_map_entry_from_manager()
                elif entry_to_remove_idx > 0 and entry_to_remove_idx <= len(self.app_ref.event_map_entries):
                    self.app_ref.event_map_entries[entry_to_remove_idx - 1]['label'].focus_set()
                elif self.app_ref.event_map_entries:
                    self.app_ref.event_map_entries[-1]['label'].focus_set()
            else:
                self.app_ref.log("Warning [EventMapManager]: Could not find row to remove.")
        except Exception as e:
            self.app_ref.log(f"Error [EventMapManager]: Removing row: {e}\n{traceback.format_exc()}")

    def _trigger_add_row_and_focus_from_manager(self, event):
        self.add_event_map_entry_from_manager(event=event)
        if self.app_ref.event_map_entries:
            newly_added_row_label = self.app_ref.event_map_entries[-1]['label']
            if newly_added_row_label.winfo_exists():
                newly_added_row_label.focus_set()
        return "break"