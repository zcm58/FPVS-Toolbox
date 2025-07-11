# ruff: noqa: F401,F403,F405
from .advanced_analysis_base import *  # noqa: F401,F403,F405
class AdvancedAnalysisProcessingMixin:
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
            if hasattr(self, "stop_processing_button"):
                self.stop_processing_button.configure(state="normal")
            self.close_button.configure(state="disabled")
            self._stop_requested.clear()
    
            # Acquire the file loading and preprocessing callables. The main
            # application may expose these as bound methods (legacy behaviour),
            # but newer versions provide standalone helpers.  We handle both
            # cases here for compatibility.
    
            if hasattr(self.master_app, "load_eeg_file"):
                load_file_method = self.master_app.load_eeg_file
            else:  # Fallback to utility function
                from Main_App.load_utils import load_eeg_file as _load
    
                def load_file_method(fp):
                    return _load(self.master_app, fp)
    
            if hasattr(self.master_app, "preprocess_raw"):
                preprocess_raw_method = self.master_app.preprocess_raw
            else:
                from Main_App.eeg_preprocessing import perform_preprocessing as _pp
    
                def preprocess_raw_method(raw, **params):
                    """Wrapper to match legacy ``preprocess_raw`` interface."""
                    filename = "UnknownFile"
                    if getattr(raw, "filenames", None):
                        try:
                            filename = os.path.basename(raw.filenames[0])
                        except Exception:
                            pass
                    elif getattr(raw, "filename", None):
                        filename = os.path.basename(raw.filename)
    
                    processed, _ = _pp(
                        raw_input=raw,
                        params=params,
                        log_func=self.master_app.log,
                        filename_for_log=filename,
                    )
                    return processed
    
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
    
        def stop_processing(self) -> None:
            """Request the running processing thread to stop."""
    
            if not (self.processing_thread and self.processing_thread.is_alive()):
                return
    
            if not self._stop_requested.is_set():
                self._stop_requested.set()
                self.log("Stop requested. Waiting for processing to terminate...")
                if hasattr(self, "stop_processing_button"):
                    self.stop_processing_button.configure(state="disabled")
    
        def _check_processing_thread(self):
            if self.processing_thread and self.processing_thread.is_alive():
                # The processing thread can run for a long time, so avoid spamming
                # the debug log on every check.
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
    
            if hasattr(self, 'stop_processing_button') and self.stop_processing_button.winfo_exists():
                self.stop_processing_button.configure(state="disabled")
    
            self._update_start_processing_button_state()
    
            if not self._stop_requested.is_set():
                self.log("Ready for next advanced analysis.")
    
            self._stop_requested.clear()
            self.processing_thread = None
