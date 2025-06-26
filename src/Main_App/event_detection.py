# -*- coding: utf-8 -*-
""" This file handles the method for scanning the .BDF files to detect PsychoPy condition IDs."""

import os
import gc
import threading
import queue
import traceback
import numpy as np
import mne
from tkinter import messagebox
import config

class EventDetectionMixin:
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

        stim_channel_name = config.DEFAULT_STIM_CHANNEL
        self.log(f"Using stim channel: {stim_channel_name}")
        representative_file = self.data_paths[0]
        self.busy = True
        self._set_controls_enabled(False)

        try:
            self.detection_thread = threading.Thread(
                target=self._detection_thread_func,
                args=(representative_file, stim_channel_name, self.gui_queue),
                daemon=True,
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
