# -*- coding: utf-8 -*-
"""Mixins that drive the background processing workflow.
They start worker threads, load each file, call preprocessing and
post-processing routines and update progress so the GUI stays
responsive."""
import gc
import os
import queue
import threading
import traceback
import time
import logging
import mne
import numpy as np
import pandas as pd
import re
from tkinter import messagebox
import tkinter as tk
import config
from Tools.SourceLocalization import runner as eloreta_runner, source_model
from Tools.SourceLocalization.logging_utils import QueueLogHandler
from Main_App.Legacy_App.post_process import post_process as _external_post_process
from Main_App.Legacy_App.eeg_preprocessing import perform_preprocessing
from Main_App.Legacy_App.load_utils import load_eeg_file


def _sanitize_folder_name(label: str) -> str:
    """Return a filesystem-safe folder name without underscores."""
    sanitized = label.replace('_', ' ').replace('/', '-').replace('\\', '-')
    sanitized = sanitized.strip()
    sanitized = re.sub(r'^\d+\s*-\s*', '', sanitized)
    return sanitized


def _stc_basename_from_fif(path: str) -> str:
    """Generate a SourceEstimate base filename from a FIF file path."""
    name = os.path.splitext(os.path.basename(path))[0]
    name = re.sub(r'[\s_-]*epo$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', '_', name.strip())
    name = re.sub(r'_+', '_', name)
    return name

class ProcessingMixin:
    _queue_job_id = None

    def start_processing(self):
        print("\n--- 'start_processing' has been called ---")
        thread_obj = getattr(self, "_processing_thread", None)
        print(f"--> Current thread object is: {thread_obj}")
        if thread_obj:
            print(f"--> Is thread alive? {thread_obj.is_alive()}")

        # Guard against re-entrant calls only when a real thread is active
        if getattr(self, "_processing_thread", None) and self._processing_thread.is_alive():
            print("!!! GUARD IS TRUE: Blocking start.")
            messagebox.showerror("Error", "Processing already started")
            return

        print("--> GUARD IS FALSE: Proceeding to start a new run.")

        # Immediately disable the Start Processing button to prevent a duplicate call and error
        self._set_controls_enabled(False)

        if self.detection_thread and self.detection_thread.is_alive():
            messagebox.showwarning("Busy", "Event detection is running. Please wait.")
            return

        self.log("=" * 50)
        self.log("START PROCESSING Initiated...")
        if getattr(self, 'run_loreta_var', None) and getattr(self.run_loreta_var, 'get', lambda: False)():
            if not messagebox.askyesno(
                    "Run LORETA",
                    (
                            "WARNING: Enabling LORETA will significantly increase the "
                            "processing time of your dataset. Do you wish to continue?"
                    ),
            ):
                self.log("User canceled processing after LORETA warning.")
                return

        if not self._validate_inputs():
            return

        self.preprocessed_data = {}
        self.progress_bar.set(0)
        self._current_progress = 0.0
        self._target_progress = 0.0
        self._max_progress = len(self.data_paths)
        self._start_time = time.time()
        self._processed_count = 0
        if hasattr(self, 'remaining_time_var') and self.remaining_time_var is not None:
            self.remaining_time_var.set("")
            self.after(0, self._update_time_remaining)
        self.busy = True


        self.log("Starting background processing thread...")
        args = (list(self.data_paths), self.validated_params.copy(), self.gui_queue)
        self.processing_thread = threading.Thread(target=self._processing_thread_func, args=args, daemon=True)
        self.processing_thread.start()
        # Mirror reference used by the run guard
        self._processing_thread = self.processing_thread
        self._queue_job_id = self.after(100, self._periodic_queue_check)

    def _periodic_queue_check(self):
        done = False
        try:
            while True:
                msg = self.gui_queue.get_nowait()
                t   = msg.get('type')

                if t == 'log':
                    self.log(msg['message'])

                elif t == 'progress':
                    self._processed_count = msg['value']
                    frac = msg['value'] / self._max_progress
                    self._animate_progress_to(frac)

                elif t == 'post':
                    fname       = msg['file']
                    epochs_dict = msg['epochs_dict']    # { label: [Epochs, ...], ... }
                    labels      = msg['labels']         # [ 'Fruit vs Veg', ... ]

                    self.log(f"\n--- Post-processing File: {fname} ---")
                    # Temporarily replace preprocessed_data with this file's dict
                    original_data = self.preprocessed_data
                    self.preprocessed_data = epochs_dict
                    try:
                        self.log(f"Post-process condition labels: {labels}")
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
                        # Log the traceback through the standard logger
                        self.log(tb)
                    done = True

                elif t == 'done':
                    done = True

        except queue.Empty:
            pass

        if not done and self.processing_thread and self.processing_thread.is_alive():
            self._queue_job_id = self.after(100, self._periodic_queue_check)
        else:
            self._finalize_processing(done)

    def _finalize_processing(self, success):
        """Finalize the batch/single processing: show completion dialog and reset state."""
        # PySide6 sets _suppress_completion_dialogs only when the user cancels a run.
        # Treat this flag as the indicator that a cancellation occurred so we don't
        # mis-report the run as an error when the user explicitly cancelled it.
        cancelled = bool(getattr(self, "_suppress_completion_dialogs", False))

        if cancelled and not success:
            self.log("--- Processing Run Cancelled by User ---")
            return

        if success:
            self.log("--- Processing Run Completed Successfully ---")
            if self.validated_params and self.data_paths:
                output_folder = self.save_folder_path.get()
                n = len(self.data_paths)
                messagebox.showinfo(
                    "Processing Complete",
                    f"Analysis finished for {n} file{'s' if n!=1 else ''}.\n"\
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

        self.busy = False
        self._set_controls_enabled(True)
        self.log(f"--- GUI Controls Re-enabled at {pd.Timestamp.now()} ---")

        self.data_paths = []
        self._max_progress = 1
        self.progress_bar.set(0.0)
        self._current_progress = 0.0
        self._target_progress = 0.0
        self._start_time = None
        self._processed_count = 0
        if hasattr(self, 'remaining_time_var') and self.remaining_time_var is not None:
            self.remaining_time_var.set("")
        self.preprocessed_data = {}

        if hasattr(self, 'log_text') and self.log_text.winfo_exists():
            self.log_text.configure(state="normal")
            ready_msg = (
                f"{pd.Timestamp.now().strftime('%H:%M:%S.%f')[:-3]} [GUI]: "
                "Ready for next file selection...\n"
            )
            self.log_text.insert(tk.END, ready_msg)
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")

        self.processing_thread = None
        self._queue_job_id = None
        gc.collect()

        self.log("--- State Reset. Ready for next run. ---")

    def _animate_progress_to(self, target: float) -> None:
        self._target_progress = max(0.0, min(1.0, target))
        if not self._animating_progress:
            self._animating_progress = True
            self.after(0, self._animate_progress_step)

    def _animate_progress_step(self):
        diff = self._target_progress - self._current_progress
        if abs(diff) < 0.005:
            self._current_progress = self._target_progress
            self.progress_bar.set(self._current_progress)
            self._animating_progress = False
            return
        self._current_progress += 0.01 if diff > 0 else -0.01
        self.progress_bar.set(self._current_progress)
        self.after(20, self._animate_progress_step)

    def _update_time_remaining(self) -> None:
        if self._start_time is None:
            return
        elapsed = time.time() - self._start_time
        progress = self._current_progress
        if progress > 0:
            total_est = elapsed / progress
            remaining = max(0.0, total_est - elapsed)
            mins, secs = divmod(int(remaining), 60)
            text = f"Estimated time remaining: {mins:02d}:{secs:02d}"
        else:
            text = ""
        if hasattr(self, 'remaining_time_var') and self.remaining_time_var is not None:
            self.remaining_time_var.set(text)
        if self.processing_thread and self.processing_thread.is_alive():
            self.after(1000, self._update_time_remaining)

    def _processing_thread_func(self, data_paths, params, gui_queue):
        import gc

        event_id_map_from_gui = params.get('event_id_map', {})
        stim_channel_name = params.get('stim_channel', config.DEFAULT_STIM_CHANNEL)
        save_folder = self.save_folder_path.get()
        max_bad_channels_alert_thresh = params.get('max_bad_channels_alert_thresh', 9999)
        run_loreta_enabled = (
            getattr(self, 'run_loreta_var', None)
            and getattr(self.run_loreta_var, 'get', lambda: False)()
        )

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
                    if temp_pid:
                        extracted_pid_for_flagging = temp_pid

                try:
                    raw = self.load_eeg_file(f_path)
                    if raw is None:
                        gui_queue.put({'type': 'log', 'message': f"Skipping file {f_name} due to load error."})
                        continue

                    if self.settings.debug_enabled():
                        gui_queue.put(
                            {'type': 'log', 'message': f"DEBUG [{f_name}]: Raw channel names after load: {raw.ch_names}"})

                    def thread_log_func_for_preprocess(message_from_preprocess):
                        if message_from_preprocess.startswith("DEBUG") and not self.settings.debug_enabled():
                            return
                        gui_queue.put({'type': 'log', 'message': message_from_preprocess})

                    if self.settings.debug_enabled():
                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: Calling perform_preprocessing. Stim_channel: '{stim_channel_name}'"})

                    raw_proc, num_kurtosis_bads = perform_preprocessing(
                        raw_input=raw.copy(), params=params,
                        log_func=thread_log_func_for_preprocess, filename_for_log=f_name
                    )
                    del raw
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

                    if self.settings.debug_enabled():
                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: Channels after perform_preprocessing: {raw_proc.ch_names}"})

                    file_extension = os.path.splitext(f_path)[1].lower()

                    if file_extension == ".set":
                        if hasattr(raw_proc, 'annotations') and raw_proc.annotations and len(raw_proc.annotations) > 0:
                            if self.settings.debug_enabled():
                                gui_queue.put({'type': 'log',
                                               'message': f"DEBUG [{f_name}]: Attempting event extraction using MNE annotations."})
                            mne_annots_event_id_map = {}
                            user_gui_int_ids = set(event_id_map_from_gui.values())
                            unique_raw_ann_descriptions = list(np.unique(raw_proc.annotations.description))
                            if self.settings.debug_enabled():
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
                                            if (
                                                extracted_num_from_desc
                                                in user_gui_int_ids
                                            ):
                                                mapped_id_for_this_desc = (
                                                    extracted_num_from_desc
                                                )
                                        except ValueError:
                                            pass
                                if mapped_id_for_this_desc is not None:
                                    mne_annots_event_id_map[desc_str_from_file] = (
                                        mapped_id_for_this_desc
                                    )
                            if not mne_annots_event_id_map:
                                gui_queue.put({'type': 'log',
                                               'message': f"WARNING [{f_name}]: Could not create MNE event_id map from annotations."})
                            else:
                                if self.settings.debug_enabled():
                                    gui_queue.put({'type': 'log',
                                                   'message': f"DEBUG [{f_name}]: Using MNE event_id map for annotations: {mne_annots_event_id_map}"})
                                try:
                                    events, _ = mne.events_from_annotations(raw_proc, event_id=mne_annots_event_id_map,
                                                                            verbose=False, regexp=None)
                                    if events.size == 0:
                                        gui_queue.put(
                                            {
                                                'type': 'log',
                                                'message': (
                                                    f"WARNING [{f_name}]: mne.events_from_annotations returned no events with map: {mne_annots_event_id_map}."
                                                ),
                                            }
                                        )
                                except Exception as e_ann:
                                    gui_queue.put(
                                        {
                                            'type': 'log',
                                            'message': f"ERROR [{f_name}]: Failed to get events from annotations: {e_ann}",
                                        }
                                    )
                                    events = np.array([])
                        else:
                            gui_queue.put(
                                {
                                    'type': 'log',
                                    'message': f"WARNING [{f_name}]: File has no MNE annotations on raw_proc.",
                                }
                            )
                        if events.size == 0:
                            gui_queue.put(
                                {
                                    'type': 'log',
                                    'message': f"FINAL WARNING [{f_name}]: No events extracted from annotations for this file.",
                                }
                            )

                    else:
                        try:
                            events = mne.find_events(raw_proc, stim_channel=stim_channel_name, consecutive=True,
                                                     verbose=False)
                        except Exception as e_find:
                            gui_queue.put({'type': 'log',
                                           'message': f"ERROR [{f_name}]: Exception mne.find_events: {e_find}"})
                    if events.size == 0:
                        gui_queue.put(
                            {
                                'type': 'log',
                                'message': f"CRITICAL WARNING [{f_name}]: Event extraction resulted in empty events array.",
                            }
                        )

                    if self.settings.debug_enabled():
                        gui_queue.put({'type': 'log',
                                       'message': f"DEBUG [{f_name}]: Starting epoching based on GUI event_id_map: {event_id_map_from_gui}"})
                    for lbl, num_id_val_gui in event_id_map_from_gui.items():
                        if self.settings.debug_enabled():
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: Attempting to epoch for GUI label '{lbl}' (using Int ID: {num_id_val_gui}). Events array shape: {events.shape}"})
                        if events.size > 0 and num_id_val_gui in events[:, 2]:
                            try:
                                epochs = mne.Epochs(
                                    raw_proc,
                                    events,
                                    event_id={lbl: num_id_val_gui},
                                    tmin=params['epoch_start'],
                                    tmax=params['epoch_end'],
                                    preload=False,
                                    verbose=False,
                                    baseline=None,
                                    on_missing='warn',
                                    decim=1,
                                )
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
                            if self.settings.debug_enabled():
                                gui_queue.put({'type': 'log',
                                               'message': f"DEBUG [{f_name}]: Target Int ID {num_id_val_gui} for GUI label '{lbl}' not found in extracted events. Skipping."})
                    if self.settings.debug_enabled():
                        gui_queue.put(
                            {'type': 'log', 'message': f"DEBUG [{f_name}]: Epoching loop for all GUI labels finished."})

                except Exception as file_proc_err:
                    gui_queue.put({'type': 'log',
                                   'message': f"!!! Error during main processing for {f_name}: {file_proc_err}\n{traceback.format_exc()}"})

                finally:
                    if self.settings.debug_enabled():
                        gui_queue.put({'type': 'log', 'message': f"DEBUG [{f_name}]: Entering finally block for file."})
                    has_valid_data = False
                    if file_epochs:
                        has_valid_data = any(
                            elist and elist[0] and isinstance(elist[0], mne.Epochs) and hasattr(elist[0],
                                'events') and len(
                                elist[0].events) > 0
                            for elist in file_epochs.values()
                        )
                    if self.settings.debug_enabled():
                        gui_queue.put(
                            {'type': 'log', 'message': f"DEBUG [{f_name}]: Value of has_valid_data: {has_valid_data}"})

                    if raw_proc is not None and has_valid_data:
                        gui_queue.put({'type': 'log', 'message': f"--- Calling Post‐process for {f_name} ---"})
                        temp_original_data_paths = self.data_paths
                        temp_original_preprocessed_data = self.preprocessed_data
                        self.data_paths = [f_path]
                        self.preprocessed_data = file_epochs
                        labels_list = list(file_epochs.keys())
                        if self.settings.debug_enabled():
                            gui_queue.put(
                                {
                                    'type': 'log',
                                    'message': f"DEBUG [{f_name}]: post_process function {self.post_process} with labels {labels_list}",
                                }
                            )
                        try:

                            self.post_process(labels_list)

                        except Exception as e_post:
                            gui_queue.put({
                                'type': 'log',
                                'message': f"!!! Post-processing/Excel error for {f_name}: {e_post}\n{traceback.format_exc()}",
                            })
                        finally:
                            self.data_paths = temp_original_data_paths
                            self.preprocessed_data = temp_original_preprocessed_data

                        # === Source localization ===
                        if run_loreta_enabled:
                            try:

                                fwd, subj, subj_dir = source_model.prepare_head_model(raw_proc)
                                noise_cov = source_model.estimate_noise_cov(raw_proc)
                                inv = source_model.make_inverse_operator(raw_proc, fwd, noise_cov)
                                stc_dict = source_model.apply_sloreta(file_epochs, inv)

                                for cond_label, stc in stc_dict.items():
                                    cond_folder = os.path.join(
                                        save_folder,
                                        "LORETA RESULTS",
                                        _sanitize_folder_name(cond_label),
                                    )
                                    os.makedirs(cond_folder, exist_ok=True)
                                    base_name = _stc_basename_from_fif(
                                        f"{os.path.splitext(f_name)[0]} {cond_label}.fif"
                                    )
                                    stc_base = os.path.join(cond_folder, base_name)
                                    stc.save(stc_base)


                                    excel_name = f"{extracted_pid_for_flagging}_{cond_label.replace(' ', '_')}_Results.xlsx"
                                    excel_path = os.path.join(cond_folder, excel_name)
                                    try:
                                        df = source_model.source_to_dataframe(stc)
                                        source_model.append_source_to_excel(excel_path, f"{cond_label}_Source", df)
                                    except Exception as e_xl:
                                        gui_queue.put({'type': 'log', 'message': f"Error appending source results: {e_xl}"})
                            except Exception as e_src:
                                gui_queue.put({'type': 'log', 'message': f"Source localization error for {f_name}: {e_src}"})
                    if raw_proc is not None and getattr(self, 'save_fif_var', None) and getattr(self.save_fif_var, 'get', lambda: False)():
                        try:
                            fif_dir = os.path.join(save_folder, ".fif files")
                            os.makedirs(fif_dir, exist_ok=True)
                            for cond_label, epoch_list in file_epochs.items():
                                if not epoch_list or not isinstance(epoch_list[0], mne.Epochs):
                                    continue
                                cond_subfolder = os.path.join(
                                    fif_dir, _sanitize_folder_name(cond_label)
                                )
                                os.makedirs(cond_subfolder, exist_ok=True)
                                cond_fname = (
                                    f"{os.path.splitext(f_name)[0]}_{cond_label.replace(' ', '_')}-epo.fif"
                                )
                                cond_path = os.path.join(cond_subfolder, cond_fname)

                                auto_loc = (
                                    self.settings.get(
                                        'loreta',
                                        'auto_oddball_localization',
                                        'False',
                                    ).lower()
                                    == 'true'
                                ) and run_loreta_enabled
                                if auto_loc:
                                    sanitized_folder = _sanitize_folder_name(cond_label)
                                    out_folder = os.path.join(
                                        save_folder, 'LORETA RESULTS', sanitized_folder
                                    )
                                    os.makedirs(out_folder, exist_ok=True)
                                    try:
                                        gui_queue.put({'type': 'log', 'message': f"Running oddball localization for {cond_label}..."})
                                        thr_str = self.settings.get('loreta', 'loreta_threshold', '0.0')
                                        try:
                                            thr_val = float(thr_str)
                                        except ValueError:
                                            thr_val = None
                                        start_ms = self.settings.get('loreta', 'time_window_start_ms', '')
                                        end_ms = self.settings.get('loreta', 'time_window_end_ms', '')
                                        try:
                                            t_window = (
                                                float(start_ms),
                                                float(end_ms),
                                            ) if start_ms and end_ms else None
                                        except ValueError:
                                            t_window = None
                                        handler = QueueLogHandler(gui_queue)
                                        pkg_logger = logging.getLogger("Tools.SourceLocalization")
                                        pkg_logger.addHandler(handler)
                                        try:
                                            eloreta_runner.run_source_localization(
                                                cond_path,
                                                out_folder,
                                                oddball=True,
                                                stc_basename=_stc_basename_from_fif(cond_path),
                                                log_func=lambda m: gui_queue.put({'type': 'log', 'message': m}),
                                                progress_cb=lambda f: gui_queue.put({'type': 'log', 'message': f"Localization {cond_label}: {int(f*100)}%"}),
                                                show_brain=False,
                                                epochs=epoch_list[0],
                                                threshold=thr_val,
                                                time_window=t_window,
                                            )
                                        finally:
                                            pkg_logger.removeHandler(handler)
                                        gui_queue.put({'type': 'log', 'message': f"Localization complete for {cond_label}."})
                                    except Exception as e_loc:
                                        gui_queue.put({'type': 'log', 'message': f"Localization failed for {cond_label}: {e_loc}"})

                                epoch_list[0].save(cond_path, overwrite=True)
                                gui_queue.put({'type': 'log', 'message': f"Condition FIF saved to: {cond_path}"})

                        except Exception as e_save:
                            gui_queue.put({'type': 'log', 'message': f"Error saving FIF for {f_name}: {e_save}"})
                    elif raw_proc is not None:
                        gui_queue.put({'type': 'log', 'message': 'FIF saving disabled.'})
                    else:
                        gui_queue.put({'type': 'log', 'message': f'Skipping FIF save for {f_name} (no preprocessed data).'})

                    gui_queue.put({'type': 'log', 'message': f"Cleaning up memory for {f_name}..."})
                    if isinstance(file_epochs, dict):
                        for epochs_list_to_del in file_epochs.values():
                            if epochs_list_to_del and epochs_list_to_del[0] is not None:
                                if hasattr(epochs_list_to_del[0], '_data') and epochs_list_to_del[0]._data is not None:
                                    del epochs_list_to_del[0]._data
                                del epochs_list_to_del[0]
                        file_epochs.clear()
                    if isinstance(raw_proc, mne.io.BaseRaw):
                        del raw_proc
                    gc.collect()
                    gui_queue.put({'type': 'log', 'message': f"Memory cleanup for {f_name} complete."})

                gui_queue.put({'type': 'progress', 'value': i + 1})
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

    def load_eeg_file(self, filepath):
        """Wrapper around :func:`load_eeg_file` that passes ``self`` as the logger."""
        return load_eeg_file(self, filepath)
