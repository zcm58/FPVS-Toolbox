# advanced_analysis_core.py
"""Core processing logic for the advanced averaging window.

This module implements functions that take the groups configured in the
``advanced_analysis`` GUI and perform the actual averaging, leveraging the main
FPVS application's loading, preprocessing and post-processing callbacks.
"""

import gc
import logging
import traceback
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional, Union

import mne
import threading

# Set up module level logger
logger = logging.getLogger(__name__)


class PostProcessContextForAdvanced:
    """
    A context object to pass to the _external_post_process function,
    mimicking the necessary parts of the FPVSApp instance for averaged data.
    """

    def __init__(self,
                 log_callback: Callable[[str], None],
                 save_folder_path_str: str,
                 pid_for_output: str,  # This will be the participant's specific PID (e.g., "P1")
                 averaged_epochs_dict: Dict[str, List[Union[mne.Epochs, mne.Evoked]]],
                 condition_name_for_output: str):  # This is the recipe name (e.g., "Average A")
        self.log_callback = log_callback
        self.save_folder_path_str = save_folder_path_str

        # Store participant PID using the attribute name post_process.py expects for "group" PIDs
        self.pid_for_group = pid_for_output
        self.averaged_epochs_dict = averaged_epochs_dict
        # Store recipe name using the attribute name post_process.py expects for "group" names
        self.group_name_for_output = condition_name_for_output

    def log(self, msg: str) -> None:
        self.log_callback(f"[AdvCorePostProc] {msg}")

    @property
    def save_folder_path(self):
        class Getter:
            def __init__(self, val): self._val = val

            def get(self): return self._val

        return Getter(self.save_folder_path_str)

    @property
    def data_paths(self) -> List[str]:
        # This dummy path helps post_process.py form a unique base if needed,
        # reflecting the participant and condition.
        return [f"{self.pid_for_group}_{self.group_name_for_output}_averaged.fif"]

    @property
    def preprocessed_data(self) -> Dict[str, List[Union[mne.Epochs, mne.Evoked]]]:
        return self.averaged_epochs_dict


def run_advanced_averaging_processing(
        defined_groups: List[Dict[str, Any]],
        main_app_params: Dict[str, Any],
        main_app_load_file_func: Callable[[str], Optional[mne.io.Raw]],
        main_app_preprocess_raw_func: Callable[[mne.io.Raw, Dict[str, Any]], Optional[mne.io.Raw]],
        external_post_process_func: Callable[[Any, List[str]], None],
        output_dir_str: str,
        pid_extraction_func: Callable[[Dict[str, Any]], str],  # Expects group-like data
        log_callback: Callable[[str], None],
        progress_callback: Callable[[float], None],
        stop_event: threading.Event
) -> bool:
    """Run advanced averaging for each participant using provided groups.

    Parameters
    ----------
    defined_groups : List[Dict[str, Any]]
        Group definitions including file paths and mapping rules.
    main_app_params : Dict[str, Any]
        Validated parameters from the main application.
    main_app_load_file_func : Callable[[str], Optional[mne.io.Raw]]
        Function used to load raw EEG files.
    main_app_preprocess_raw_func : Callable[[mne.io.Raw, Dict[str, Any]], Optional[mne.io.Raw]]
        Function performing preprocessing on loaded data.
    external_post_process_func : Callable[[Any, List[str]], None]
        Callback invoked after averaging to run post-processing.
    output_dir_str : str
        Directory where results should be written.
    pid_extraction_func : Callable[[Dict[str, Any]], str]
        Function returning a participant ID based on group data.
    log_callback : Callable[[str], None]
        Callback used for logging messages to the UI.
    progress_callback : Callable[[float], None]
        Callback for updating progress in the UI.
    stop_event : threading.Event
        Event used to cancel processing.

    Returns
    -------
    bool
        ``True`` if processing completed without major errors, otherwise ``False``.
    """

    log_callback("Starting advanced averaging core processing (per-participant output)...")

    # Estimate total operations for progress bar
    total_source_ops = 0
    total_participant_post_ops = 0

    for group_data_template in defined_groups:
        unique_files_in_group = list(set(group_data_template.get('file_paths', [])))
        total_participant_post_ops += len(unique_files_in_group)
        for participant_file_path_for_estimate in unique_files_in_group:
            for mapping_rule_template in group_data_template.get('condition_mappings', []):
                for source_info_template in mapping_rule_template.get('sources', []):
                    if source_info_template['file_path'] == participant_file_path_for_estimate:
                        total_source_ops += 1

    total_operations_estimate = total_source_ops + total_participant_post_ops
    if total_operations_estimate == 0:
        total_operations_estimate = 1
    current_operation_count = 0
    overall_success = True

    for group_definition in defined_groups:  # A "group definition" is like a recipe, e.g., "Average A"
        if stop_event.is_set():
            log_callback("Processing cancelled by user.")
            return False

        group_recipe_name = group_definition['name']  # e.g., "Average A"
        log_callback(f"--- Applying Group Recipe: {group_recipe_name} ---")

        unique_participant_files = sorted(list(set(group_definition.get('file_paths', []))))
        if not unique_participant_files:
            log_callback(f"  No files specified for recipe '{group_recipe_name}'. Skipping.")
            continue

        # Loop through each unique participant file associated with this group recipe
        for participant_file_path in unique_participant_files:
            if stop_event.is_set():
                return False

            participant_pid = pid_extraction_func({'file_paths': [participant_file_path]})
            log_callback(
                f"  -- Processing Participant: {participant_pid} (File: {Path(participant_file_path).name}) for Recipe: '{group_recipe_name}' --")

            averaged_data_for_this_participant: Dict[str, List[Union[mne.Epochs, mne.Evoked]]] = {}

            for mapping_rule in group_definition.get('condition_mappings', []):
                if stop_event.is_set():
                    return False

                output_label_for_average = mapping_rule['output_label']
                log_callback(f"    Applying rule for: '{output_label_for_average}' to participant {participant_pid}")

                epochs_for_this_participant_this_rule: List[mne.Epochs] = []

                for source_info in mapping_rule.get('sources', []):
                    if stop_event.is_set():
                        return False

                    if source_info['file_path'] != participant_file_path:
                        continue

                    file_path_of_source = source_info['file_path']
                    original_event_label = source_info['original_label']
                    original_event_id = source_info['original_id']
                    file_basename = Path(file_path_of_source).name

                    log_callback(
                        f"      Loading & Preprocessing: {file_basename} for Event ID {original_event_id} ('{original_event_label}')")

                    raw = None
                    raw_copy_for_preproc = None
                    raw_proc = None
                    participant_source_epochs = None  # MODIFICATION: Ensure initialization
                    try:
                        raw = main_app_load_file_func(file_path_of_source)
                        if raw is None or stop_event.is_set():
                            log_callback(f"      Skipping {file_basename} (load failed or stop event).")
                            overall_success = False
                            continue

                        raw_copy_for_preproc = raw.copy()
                        # MODIFICATION: Removed 'del raw;' and 'gc.collect()' from here

                        raw_proc = main_app_preprocess_raw_func(raw_copy_for_preproc, **main_app_params.copy())
                        # MODIFICATION: Removed 'del raw_copy_for_preproc;' and 'gc.collect()' from here

                        if raw_proc is None or stop_event.is_set():
                            log_callback(f"      Skipping {file_basename} (preprocess failed or stop event).")
                            overall_success = False
                            continue

                        stim_channel = main_app_params.get('stim_channel', 'Status')
                        events = mne.find_events(raw_proc, stim_channel=stim_channel, consecutive=True, verbose=False)

                        if original_event_id not in events[:, 2]:
                            log_callback(
                                f"      Warning: Event ID {original_event_id} not found in {file_basename}. Skipping this event for {participant_pid}.")
                            continue

                        event_id_dict_for_mne = {original_event_label: original_event_id}
                        participant_source_epochs = mne.Epochs(  # Assignment happens here
                            raw_proc, events, event_id=event_id_dict_for_mne,
                            tmin=main_app_params['epoch_start'], tmax=main_app_params['epoch_end'],
                            preload=True, baseline=None, verbose=False, on_missing='warn'
                        )
                        if len(participant_source_epochs) > 0:
                            log_callback(
                                f"        Created {len(participant_source_epochs)} epochs from {file_basename} for ID {original_event_id}.")
                            epochs_for_this_participant_this_rule.append(participant_source_epochs)
                        else:
                            log_callback(
                                f"        No epochs created from {file_basename} for ID {original_event_id}.")
                    except Exception as e:
                        logger.exception("Error during epoching for %s", file_basename)
                        log_callback(
                            f"      !!! Error during epoching for {file_basename}, ID {original_event_id} for {participant_pid}: {e}\n{traceback.format_exc()}")
                        overall_success = False
                    finally:
                        if raw_proc is not None:
                            del raw_proc
                        if raw_copy_for_preproc is not None:
                            del raw_copy_for_preproc
                        if raw is not None:
                            del raw
                        if participant_source_epochs is not None:
                            del participant_source_epochs  # MODIFICATION: Cleanup added
                        gc.collect()

                    current_operation_count += 1
                    progress_callback(current_operation_count / total_operations_estimate)

                if epochs_for_this_participant_this_rule:
                    averaging_method = group_definition.get('averaging_method', "Pool Trials")
                    log_callback(
                        f"    Averaging {len(epochs_for_this_participant_this_rule)} sets of epochs for '{output_label_for_average}' (Participant: {participant_pid}, Method: {averaging_method})")
                    try:
                        if averaging_method == "Pool Trials":
                            concatenated_epochs = mne.concatenate_epochs(epochs_for_this_participant_this_rule)
                            averaged_evoked = concatenated_epochs.average()
                            averaged_data_for_this_participant[output_label_for_average] = [averaged_evoked]
                            log_callback(
                                f"      Pooled {len(concatenated_epochs)} total trials for '{output_label_for_average}'.")
                        elif averaging_method == "Average of Averages":
                            evokeds_to_average = [ep.average() for ep in epochs_for_this_participant_this_rule if
                                                  len(ep) > 0]
                            if evokeds_to_average:
                                averaged_evoked = mne.grand_average(evokeds_to_average,
                                                                    interpolate_bads=False)
                                averaged_data_for_this_participant[output_label_for_average] = [averaged_evoked]
                                log_callback(
                                    f"      Averaged {len(evokeds_to_average)} evoked responses for '{output_label_for_average}'.")
                            else:
                                log_callback(
                                    f"      No valid evoked responses to average for '{output_label_for_average}'.")
                        else:
                            log_callback(f"    Unknown averaging method: {averaging_method}. Skipping.")
                            overall_success = False
                    except Exception as e:
                        logger.exception("Error during averaging for participant %s", participant_pid)
                        log_callback(
                            f"    !!! Error during averaging for '{output_label_for_average}', PID {participant_pid}: {e}\n{traceback.format_exc()}")
                        overall_success = False
                else:
                    log_callback(
                        f"    No epochs collected for rule '{output_label_for_average}' for participant {participant_pid}. Cannot average.")

                del epochs_for_this_participant_this_rule
                gc.collect()

            if averaged_data_for_this_participant:
                if stop_event.is_set():
                    return False
                log_callback(
                    f"  --- Initiating Post-Processing for Participant {participant_pid} (Recipe: '{group_recipe_name}') ---")

                post_proc_context = PostProcessContextForAdvanced(
                    log_callback=log_callback,
                    save_folder_path_str=output_dir_str,
                    pid_for_output=participant_pid,
                    averaged_epochs_dict=averaged_data_for_this_participant,
                    condition_name_for_output=group_recipe_name
                )
                try:
                    external_post_process_func(post_proc_context, list(averaged_data_for_this_participant.keys()))
                    log_callback(
                        f"  --- Post-processing for {participant_pid} (Recipe: '{group_recipe_name}') completed. ---")
                except Exception as e:
                    logger.exception("Error during post-processing for participant %s", participant_pid)
                    log_callback(
                        f"  !!! Error during post-processing for {participant_pid} (Recipe: '{group_recipe_name}'): {e}\n{traceback.format_exc()}")
                    overall_success = False

                current_operation_count += 1
                progress_callback(current_operation_count / total_operations_estimate)
            else:
                log_callback(
                    f"  No data averaged for participant {participant_pid} (Recipe: '{group_recipe_name}'). Skipping post-processing.")

            del averaged_data_for_this_participant
            gc.collect()
            log_callback(
                f"  -- Finished processing for Participant: {participant_pid} (Recipe: '{group_recipe_name}') --")

        log_callback(f"--- All participants processed for Group Recipe: {group_recipe_name} ---")

    log_callback("Advanced averaging core processing finished.")
    return overall_success
