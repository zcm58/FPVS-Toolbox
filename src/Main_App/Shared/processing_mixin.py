# -*- coding: utf-8 -*-
"""Mixin that drives the background processing workflow.

This is the current-app owner for the single/legacy processing path.
`Main_App.Legacy_App.processing_utils` remains as a thin compatibility wrapper.

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
from datetime import datetime
import mne
import numpy as np
import pandas as pd
import re
import config
from Main_App.Shared import user_messages
from Main_App.Shared.post_process import post_process as _external_post_process
from Main_App.Legacy_App.eeg_preprocessing import perform_preprocessing
from Main_App.Shared.load_utils import load_eeg_file
from Main_App.Shared.fft_crop_utils import compute_fft_crop_from_events, compute_onbin_step, ODDBALL_FREQ

logger = logging.getLogger(__name__)


class ProcessingMixin:
    _queue_job_id = None

    def start_processing(self):
        logger.debug("start_processing called")
        thread_obj = getattr(self, "_processing_thread", None)
        logger.debug("current processing thread object: %s", thread_obj)
        if thread_obj:
            logger.debug("processing thread alive: %s", thread_obj.is_alive())

        # Guard against re-entrant calls only when a real thread is active
        if getattr(self, "_processing_thread", None) and self._processing_thread.is_alive():
            logger.debug("processing start blocked because thread is already active")
            user_messages.show_error("Error", "Processing already started", self)
            return

        logger.debug("processing start guard clear")

        # Immediately disable the Start Processing button to prevent a duplicate call and error
        self._set_controls_enabled(False)

        if self.detection_thread and self.detection_thread.is_alive():
            user_messages.show_warning("Busy", "Event detection is running. Please wait.", self)
            return

        self.log("=" * 50)
        self.log("START PROCESSING Initiated...")

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
                user_messages.show_info(
                    "Processing Complete",
                    f"Analysis finished for {n} file{'s' if n!=1 else ''}.\n"\
                    f"Excel files saved to:\n{output_folder}",
                    self,
                )
            else:
                user_messages.show_info(
                    "Processing Finished",
                    "Processing run finished. Check logs for details.",
                    self,
                )
        else:
            self.log("--- Processing Run Finished with ERRORS ---")
            user_messages.show_error(
                "Processing Error",
                "An error occurred during processing. Please check the log for details.",
                self,
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
            self.log_text.insert("end", ready_msg)
            self.log_text.see("end")
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
        project_root = save_folder if save_folder else os.getcwd()
        logs_dir = os.path.join(project_root, "Logs")
        os.makedirs(logs_dir, exist_ok=True)
        fft_crop_log_path = os.path.join(
            logs_dir,
            f"fft_crop_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        )

        def fft_crop_log(level, message):
            prefix = f"{level} [fft_crop]"
            gui_queue.put({'type': 'log', 'message': f"{prefix} {message}"})
            with open(fft_crop_log_path, "a", encoding="utf-8") as fp:
                fp.write(f"{datetime.now().isoformat()} {prefix} {message}\n")
        max_bad_channels_alert_thresh = params.get('max_bad_channels_alert_thresh', 9999)

        original_app_data_paths = list(self.data_paths)
        original_app_preprocessed_data = dict(self.preprocessed_data)

        quality_flagged_files_info_for_run = []

        try:
            with open(fft_crop_log_path, "w", encoding="utf-8") as fp:
                fp.write(f"project_root={project_root}\n")
                fp.write(f"timestamp={datetime.now().isoformat()}\n")
                fp.write("oddball_hz=1.2\n")
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
                    onset_ids = set(event_id_map_from_gui.values())
                    sfreq = float(raw_proc.info['sfreq'])
                    crop_results, n_step, run_warnings = compute_fft_crop_from_events(
                        events=events,
                        fs=sfreq,
                        onset_ids=onset_ids,
                        oddball_id=55,
                        stream_end_sample=int(raw_proc.n_times),
                    )
                    fft_crop_log("INFO", f"file={f_name} input={f_path} fs={sfreq:.6f} n_step={n_step}")
                    for warning_msg in run_warnings:
                        fft_crop_log("WARN", f"file={f_name} run_warning={warning_msg}")

                    n_common_by_label = {}
                    for lbl, num_id_val_gui in event_id_map_from_gui.items():
                        if self.settings.debug_enabled():
                            gui_queue.put({'type': 'log',
                                           'message': f"DEBUG [{f_name}]: Attempting to epoch for GUI label '{lbl}' (using Int ID: {num_id_val_gui}). Events array shape: {events.shape}"})
                        if events.size > 0 and num_id_val_gui in events[:, 2]:
                            try:
                                rep_keys = sorted([k for k in crop_results if k[0] == int(num_id_val_gui)], key=lambda x: x[1])
                                rep_segments = []
                                rep_events = []
                                rep_diagnostics = []
                                rep_fallback_count = 0
                                n_common = None
                                for rep_key in rep_keys:
                                    crop = crop_results[rep_key]
                                    for w in crop.warnings:
                                        fft_crop_log("WARN", f"file={f_name} condition={lbl} rep={rep_key[1]} warn={w}")

                                    if not crop.fallback and crop.n_samples > 0:
                                        n_common = crop.n_samples if n_common is None else min(n_common, crop.n_samples)

                                if n_common is not None and n_step is not None:
                                    n_common = (n_common // n_step) * n_step
                                    if n_common <= 0:
                                        n_common = None

                                if n_common_by_label.get(lbl) is None and n_common is not None:
                                    n_common_by_label[lbl] = n_common

                                for rep_key in rep_keys:
                                    crop = crop_results[rep_key]
                                    use_fallback = crop.fallback or n_common is None
                                    if use_fallback:
                                        rep_fallback_count += 1
                                        start_samp = int(crop.block_start_sample + params['epoch_start'] * sfreq)
                                        stop_samp = int(crop.block_start_sample + params['epoch_end'] * sfreq)
                                        start_samp = max(0, start_samp)
                                        stop_samp = min(int(raw_proc.n_times), stop_samp)
                                        n_used = max(0, stop_samp - start_samp)
                                        fallback_reason = crop.fallback_reason or "no_nonfallback_n_common"
                                    else:
                                        start_samp = int(crop.crop_start_sample)
                                        stop_samp = int(start_samp + n_common)
                                        n_used = int(n_common)
                                        fallback_reason = None

                                    if n_used <= 0 or stop_samp <= start_samp:
                                        fft_crop_log("WARN", f"file={f_name} condition={lbl} rep={rep_key[1]} skipped=true reason=empty_segment")
                                        continue

                                    data = raw_proc.get_data(start=start_samp, stop=stop_samp)
                                    rep_segments.append(data)
                                    rep_events.append([start_samp, 0, int(num_id_val_gui)])

                                    t_sec = n_used / sfreq if sfreq > 0 else 0.0
                                    df_hz = sfreq / n_used if n_used > 0 else 0.0
                                    k = (1.2 * n_used / sfreq) if sfreq > 0 else 0.0
                                    k_is_int = abs(k - round(k)) < 1e-9
                                    _, n_step_check, step_err = compute_onbin_step(fs=sfreq, f_oddball=ODDBALL_FREQ)
                                    f_bin_hz = (sfreq / n_used) * round(k) if n_used > 0 and sfreq > 0 else 0.0
                                    if not use_fallback:
                                        if n_step_check is None or n_used % n_step_check != 0:
                                            raise ValueError(
                                                f"FFT crop enforcement failed for {f_name}/{lbl}: N={n_used}, N_step={n_step_check}"
                                            )
                                        fs_i = int(round(sfreq))
                                        if (ODDBALL_FREQ.numerator * n_used) % (ODDBALL_FREQ.denominator * fs_i) != 0:
                                            raise ValueError(
                                                f"FFT bin-lock failed for {f_name}/{lbl}: N={n_used}, fs_i={fs_i}"
                                            )
                                        fft_crop_log(
                                            "INFO",
                                            f"FFT_CROP_ACTIVE file={f_name} condition={lbl} rep={rep_key[1]} fs={sfreq:.6f} "
                                            f"N_step={n_step_check} N={n_used} N%N_step={n_used % n_step_check} "
                                            f"k={k:.8f} f_bin={f_bin_hz:.12f}",
                                        )
                                    else:
                                        fft_crop_log(
                                            "WARN",
                                            f"FFT_CROP_FALLBACK file={f_name} condition={lbl} rep={rep_key[1]} reason={fallback_reason or step_err or 'unknown'} "
                                            f"N={n_used} k={k:.8f} f_bin={f_bin_hz:.12f}",
                                        )
                                    fft_crop_log(
                                        "INFO" if not use_fallback else "WARN",
                                        f"file={f_name} condition={lbl} rep={rep_key[1]} block=({crop.block_start_sample},{crop.block_end_sample}) "
                                        f"n55_raw={crop.n55_raw} n55_dedup={crop.n55_dedup} cycles={crop.cycles} "
                                        f"first55={crop.first55_sample} last55={crop.last55_sample} available={crop.available_samples} "
                                        f"N={n_used} T={t_sec:.6f} df={df_hz:.6f} k={k:.8f} on_bin_pass={k_is_int} "
                                        f"fallback={use_fallback} fallback_reason={fallback_reason} dedup_dropped={crop.dedup_dropped} missing_gap_warns={crop.missing_gap_count}",
                                    )
                                    rep_diagnostics.append(
                                        {
                                            "crop_mode": "fixed_epoch_fallback" if use_fallback else "55_onbin",
                                            "n55": int(crop.n55_dedup),
                                            "first55_samp": int(crop.first55_sample) if crop.first55_sample is not None else np.nan,
                                            "last55_samp": int(crop.last55_sample) if crop.last55_sample is not None else np.nan,
                                            "N_step": int(n_step_check) if n_step_check is not None else np.nan,
                                            "N_mod_step": int(n_used % n_step_check) if n_step_check else np.nan,
                                            "fallback_reason": fallback_reason or "",
                                        }
                                    )

                                if rep_segments:
                                    epoch_data = np.stack(rep_segments, axis=0)
                                    epochs = mne.EpochsArray(
                                        epoch_data,
                                        raw_proc.info.copy(),
                                        events=np.asarray(rep_events, dtype=int),
                                        event_id={lbl: int(num_id_val_gui)},
                                        tmin=0.0,
                                        baseline=None,
                                        verbose=False,
                                    )
                                    if rep_diagnostics and len(rep_diagnostics) == len(epochs.events):
                                        epochs.metadata = pd.DataFrame(rep_diagnostics)
                                    gui_queue.put({'type': 'log',
                                                   'message': f"  -> Successfully created {len(epochs.events)} epochs for GUI label '{lbl}' in {f_name}."})
                                    file_epochs[lbl] = [epochs]
                                    if rep_fallback_count:
                                        fft_crop_log("WARN", f"file={f_name} condition={lbl} fallback_reps={rep_fallback_count}")
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
                    if n_common_by_label:
                        summary = ", ".join([f"{k}:{v}" for k, v in n_common_by_label.items()])
                        fft_crop_log("INFO", f"file={f_name} n_common_summary={summary}")
                        unique_n = sorted(set(n_common_by_label.values()))
                        if len(unique_n) > 1:
                            fft_crop_log("WARN", f"file={f_name} n_common_mismatch={unique_n}")

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
