# -*- coding: utf-8 -*-
"""Utility mixin for managing the Event Map interface.
It lets the user add or remove rows that map condition labels to
numeric IDs and validates the entries in the scrollable frame."""
import tkinter as tk
import customtkinter as ctk
import traceback
from tkinter import filedialog, messagebox
from config import CORNER_RADIUS, PAD_X

class EventMapMixin:
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
        remove_btn = ctk.CTkButton(
            entry_frame,
            text="✕",  # Use a clear 'X' symbol
            width=28,
            height=28,
            corner_radius=CORNER_RADIUS,
            fg_color="red",  # Red background for better visibility
            hover_color="#cc0000",  # Slightly darker on hover
            text_color="white",  # White "X"
            font=ctk.CTkFont(weight="bold"),  # Bold text for clarity
            # Pass the specific frame to remove
            command=lambda ef=entry_frame: self.remove_event_map_entry(ef),
        )
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

    def clear_event_map_entries(self):
        """Remove all event map rows without adding a new blank row."""
        if not hasattr(self, 'event_map_entries'):
            return
        for entry in list(self.event_map_entries):
            frame = entry.get('frame')
            if frame and frame.winfo_exists():
                frame.destroy()
        self.event_map_entries.clear()

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
        return "break"  # Prevents default Enter behavior
