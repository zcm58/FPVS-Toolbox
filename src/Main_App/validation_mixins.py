# -*- coding: utf-8 -*-
"""Validation logic separated from the main app."""
import os
import traceback
import tkinter as tk
from tkinter import messagebox

class ValidationMixin:
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

            if not event_map:  # If after iterating all rows, event_map is still empty
                self.log("Validation Error: Event Map contains no valid entries after parsing all rows.")
                messagebox.showerror("Event Map Error", "Please provide at least one valid Condition Label and Numerical ID pair in the Event Map.")
                if self.event_map_entries and self.event_map_entries[0].get('label'):  # Focus first row if it exists
                     self.event_map_entries[0]['label'].focus_set()
                elif hasattr(self, 'add_map_button') and self.add_map_button:  # Or focus add button
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
