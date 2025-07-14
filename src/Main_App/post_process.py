# post_process.py
import os
import pandas as pd
import numpy as np
import traceback
import gc
import mne
import re
from config import TARGET_FREQUENCIES, DEFAULT_ELECTRODE_NAMES_64  # Ensure these are correct
from typing import List, Any
from Tools.Stats.full_snr import compute_full_snr


def post_process(app: Any, condition_labels_present: List[str]) -> None:
    """
    Calculates metrics (FFT, SNR, Z-score, BCA) and saves results to Excel.
    Handles single-file processing (FPVSApp) and per-participant averaged results (AdvancedAnalysis).

    This file should NOT BE EDITED for any reason unless given explicit instructions to do so.
    """
    app.log("--- Post-processing: Calculating Metrics & Saving Excel ---")
    parent_folder = app.save_folder_path.get()
    if not parent_folder or not os.path.isdir(parent_folder):
        app.log(f"Error: Invalid save folder: '{parent_folder}'")
        return

    # --- PID Determination ---
    pid = "UnknownPID"
    # For Advanced Analysis, 'pid_for_group' on the context now holds the participant_pid
    if hasattr(app, 'pid_for_group') and app.pid_for_group:
        pid = app.pid_for_group  # This should be "P1", "P2", etc.
        app.log(f"Using PID from context: {pid}")
    elif app.data_paths:  # Fallback for original FPVSApp single-file processing
        try:
            first_file_path = app.data_paths[0]
            first_file_basename = os.path.basename(first_file_path)
            pid_base = os.path.splitext(first_file_basename)[0]
            pid_regex = r'\b(P\d+|Sub\d+|S\d+)\b'
            match = re.search(pid_regex, pid_base, re.IGNORECASE)
            if match:
                pid = match.group(1).upper()
            else:
                pid_cleaned = re.sub(r'(_unamb|_ambig|_mid|_run\d*|_sess\d*|_task\w*|_eeg|_fpvs|_raw|_preproc|_ica).*$',
                                     '', pid_base, flags=re.IGNORECASE)
                pid_cleaned = re.sub(r'[^a-zA-Z0-9]', '', pid_cleaned)
                pid = pid_cleaned if pid_cleaned else pid_base
            app.log(f"Extracted PID for single file processing: {pid}")
        except Exception as e:
            app.log(f"Warn: Could not extract PID from app.data_paths[0]: {e}")
    else:
        app.log("Warning: Could not determine PID. Using default 'UnknownPID'.")

    any_results_saved = False
    current_epochs_data_source = app.preprocessed_data

    for cond_label_from_keys in condition_labels_present:
        data_list = current_epochs_data_source.get(cond_label_from_keys, [])
        if not data_list:
            app.log(f"\nSkipping post-processing for '{cond_label_from_keys}': No data found.")
            continue

        app.log(f"\nPost-processing '{cond_label_from_keys}' (PID: {pid}, {len(data_list)} data object(s))...")

        # --- Output Naming Logic ---
        folder_name_base = ""
        filename_condition_part = ""
        excel_final_suffix = ".xlsx"  # Desired suffix for advanced outputs

        # Check if this is an output from the advanced analysis per-participant flow
        is_advanced_output = (hasattr(app, 'group_name_for_output') and
                              app.group_name_for_output and
                              app.group_name_for_output == cond_label_from_keys)

        if is_advanced_output:
            # Use the recipe name (e.g., "Average A") from the context
            condition_recipe_name = app.group_name_for_output
            # Sanitize for folder and file: replace spaces with underscores, etc.
            sanitized_recipe_name = condition_recipe_name.replace(' ', '_').replace('/', '-').replace('\\', '-').strip()
            sanitized_recipe_name = re.sub(r'^\d+\s*-\s*', '', sanitized_recipe_name)  # Remove "1 - " prefixes etc.

            folder_name_base = sanitized_recipe_name  # Subfolder e.g., "Average_A"
            filename_condition_part = sanitized_recipe_name  # File part e.g., "Average_A"
            # pid is already the participant_pid, e.g., "P1"
            excel_filename = f"{pid}_{filename_condition_part}{excel_final_suffix}"  # e.g., "P1_Average_A.xlsx"
        else:
            # Original FPVSApp single-file processing path
            raw_condition_label = cond_label_from_keys
            sanitized_condition_label = re.sub(r'^\d+\s*-\s*', '',
                                               raw_condition_label.replace('/', '-').replace('\\', '-').strip())

            folder_name_base = sanitized_condition_label
            filename_condition_part = sanitized_condition_label
            # Original naming for FPVSApp might be different, adjust if needed
            excel_filename = f"{pid}_{filename_condition_part}_Results.xlsx"

            # Create subfolder
        output_subfolder_path = os.path.join(parent_folder, folder_name_base)
        try:
            os.makedirs(output_subfolder_path, exist_ok=True)
        except OSError as e:
            app.log(f"Error creating subfolder {output_subfolder_path}: {e}. Saving to parent folder: {parent_folder}")
            output_subfolder_path = parent_folder

        full_excel_path = os.path.join(output_subfolder_path, excel_filename)
        app.log(f"Target Excel path for '{cond_label_from_keys}': {full_excel_path}")

        # --- Metrics Calculation (largely unchanged) ---
        accum = {'fft': None, 'snr': None, 'z': None, 'bca': None}
        full_snr_accum = None
        valid_data_count = 0
        final_num_channels = 0
        final_electrode_names_ordered = []

        for data_idx, data_object in enumerate(data_list):  # Should be one Evoked for advanced
            is_evoked = isinstance(data_object, mne.Evoked)
            if not (hasattr(data_object, 'info') and (is_evoked or hasattr(data_object, 'get_data'))):
                app.log(f"    Item {data_idx + 1} is not a valid MNE data object. Skipping.")
                continue
            app.log(f"  Processing data object {data_idx + 1}/{len(data_list)} for '{cond_label_from_keys}'...")
            gc.collect()
            try:
                if not is_evoked:  # Epochs
                    if not data_object.preload:
                        data_object.load_data()
                    if len(data_object.events) == 0:
                        app.log("    Epochs object 0 events. Skip.")
                        continue

                    # ...
                data_eeg = data_object.copy().pick(
                    'eeg', exclude='bads' if not is_evoked else []
                )
                if not data_eeg.ch_names:
                    app.log("    No good EEG channels. Skip.")
                    continue

                if is_evoked:
                        avg_data = data_eeg.data
                else:  # Epochs
                    ep_data = data_eeg.get_data()
                    avg_data = np.mean(ep_data.astype(np.float64), axis=0)
                num_channels, num_times = avg_data.shape
                    # ...
                current_ch_names_from_obj = data_eeg.info['ch_names']
                ordered_electrode_names_for_df = []

                if num_channels == len(DEFAULT_ELECTRODE_NAMES_64) and \
                        set(current_ch_names_from_obj) == set(DEFAULT_ELECTRODE_NAMES_64):
                    ordered_electrode_names_for_df = [name for name in DEFAULT_ELECTRODE_NAMES_64 if
                                                      name in current_ch_names_from_obj]
                    name_to_idx_map = {name: i for i, name in enumerate(current_ch_names_from_obj)}
                    reorder_indices = [name_to_idx_map[name] for name in ordered_electrode_names_for_df]
                    avg_data = avg_data[reorder_indices, :]
                    app.log(f"    Standardized channel order to {len(ordered_electrode_names_for_df)} channels.")
                elif num_channels == len(DEFAULT_ELECTRODE_NAMES_64):
                    app.log(
                        f"    Warn: Found {num_channels} channels, names don't match default. Using default order/names.")
                    ordered_electrode_names_for_df = DEFAULT_ELECTRODE_NAMES_64
                else:
                    app.log(f"    Warn: Found {num_channels} channels. Using actual names/order.")
                    ordered_electrode_names_for_df = current_ch_names_from_obj

                if valid_data_count == 0:
                    final_num_channels = num_channels
                    final_electrode_names_ordered = ordered_electrode_names_for_df
                if num_channels != final_num_channels or ordered_electrode_names_for_df != final_electrode_names_ordered:
                    app.log("    Error: Channel mismatch. Skipping object.")
                    continue

                avg_data_uv = avg_data * 1e6
                if data_idx == 0:
                    app.log(
                        f"    Scaling to uV. Max: {np.max(np.abs(avg_data_uv)):.2f} uV"
                    )

                sfreq = data_eeg.info['sfreq']
                num_fft_bins = num_times // 2 + 1
                fft_frequencies = np.linspace(0, sfreq / 2.0, num=num_fft_bins, endpoint=True)
                fft_full_spectrum = np.fft.fft(avg_data_uv, axis=1)
                fft_amplitudes = np.abs(fft_full_spectrum[:, :num_fft_bins]) / num_times * 2

                full_snr_matrix = compute_full_snr(avg_data_uv, sfreq)

                num_target_freqs = len(TARGET_FREQUENCIES)
                metrics_fft = np.zeros((final_num_channels, num_target_freqs))
                metrics_snr = np.zeros((final_num_channels, num_target_freqs))
                metrics_z = np.zeros((final_num_channels, num_target_freqs))
                metrics_bca = np.zeros((final_num_channels, num_target_freqs))

                for chan_idx in range(final_num_channels):
                    for freq_idx, target_freq in enumerate(TARGET_FREQUENCIES):
                        if not (fft_frequencies[0] <= target_freq <= fft_frequencies[-1]):
                            if chan_idx == 0 and data_idx == 0:
                                app.log(
                                    f"    Skipping target freq {target_freq} Hz."
                                )
                            continue
                        target_bin_index = np.argmin(np.abs(fft_frequencies - target_freq))
                        noise_bin_low = target_bin_index - 12
                        noise_bin_high = target_bin_index + 12
                        bins_to_exclude_from_noise = {target_bin_index - 2, target_bin_index - 1, target_bin_index,
                                                      target_bin_index + 1, target_bin_index + 2}
                        valid_noise_indices = [i for i in range(noise_bin_low, noise_bin_high + 1) if
                                               0 <= i < len(fft_frequencies) and i not in bins_to_exclude_from_noise]
                        noise_mean_val, noise_std_val = 0.0, 0.0
                        if len(valid_noise_indices) >= 4:
                            noise_amplitudes = fft_amplitudes[chan_idx, valid_noise_indices]
                            noise_mean_val = np.mean(noise_amplitudes)
                            noise_std_val = np.std(noise_amplitudes)
                        elif data_idx == 0 and chan_idx == 0:
                            app.log(f"    Warn: Not enough noise bins near {target_freq:.1f} Hz.")
                        signal_amplitude = fft_amplitudes[chan_idx, target_bin_index]
                        peak_val_slice = slice(max(0, target_bin_index - 1),
                                               min(len(fft_frequencies), target_bin_index + 2))
                        peak_signal_amplitude = np.max(fft_amplitudes[chan_idx, peak_val_slice])
                        snr_val = signal_amplitude / noise_mean_val if noise_mean_val > 1e-12 else 0
                        z_score_val = (
                                                  peak_signal_amplitude - noise_mean_val) / noise_std_val if noise_std_val > 1e-12 else 0
                        bca_val = signal_amplitude - noise_mean_val
                        metrics_fft[chan_idx, freq_idx] = signal_amplitude
                        metrics_snr[chan_idx, freq_idx] = snr_val
                        metrics_z[chan_idx, freq_idx] = z_score_val
                        metrics_bca[chan_idx, freq_idx] = bca_val

                if accum['fft'] is None:
                    accum = {'fft': metrics_fft, 'snr': metrics_snr, 'z': metrics_z, 'bca': metrics_bca}
                    full_snr_accum = full_snr_matrix
                else:
                    accum['fft'] += metrics_fft
                    accum['snr'] += metrics_snr
                    accum['z'] += metrics_z
                    accum['bca'] += metrics_bca
                    full_snr_accum += full_snr_matrix
                valid_data_count += 1
            except Exception as e:
                app.log(f"!!! Error post-processing data object {data_idx + 1}: {e}\n{traceback.format_exc()}")
            finally:
                del data_eeg
                gc.collect()

        if valid_data_count > 0 and final_electrode_names_ordered:
            avg_metrics = {k: v / valid_data_count for k, v in accum.items()}
            freq_column_names = [f"{f:.4f}_Hz" for f in TARGET_FREQUENCIES]
            full_snr_avg = full_snr_accum / valid_data_count if full_snr_accum is not None else None
            dataframes_to_save = {
                'FFT Amplitude (uV)': pd.DataFrame(
                    avg_metrics['fft'], index=final_electrode_names_ordered, columns=freq_column_names
                ),
                'SNR': pd.DataFrame(
                    avg_metrics['snr'], index=final_electrode_names_ordered, columns=freq_column_names
                ),
                'Z Score': pd.DataFrame(
                    avg_metrics['z'], index=final_electrode_names_ordered, columns=freq_column_names
                ),
                'BCA (uV)': pd.DataFrame(
                    avg_metrics['bca'], index=final_electrode_names_ordered, columns=freq_column_names
                ),
            }
            if full_snr_avg is not None:

                try:
                    upper_limit = float(app.settings.get('analysis', 'bca_upper_limit', '16.8'))
                except Exception:
                    upper_limit = 16.8
                mask = fft_frequencies <= upper_limit
                freq_cols_full = [f"{f:.4f}_Hz" for f in fft_frequencies[mask]]

                dataframes_to_save['FullSNR'] = pd.DataFrame(
                    full_snr_avg[:, mask],
                    index=final_electrode_names_ordered,
                    columns=freq_cols_full,
                )
            for df_name_iter in dataframes_to_save:
                dataframes_to_save[df_name_iter].insert(0, 'Electrode', dataframes_to_save[df_name_iter].index)

            try:
                with pd.ExcelWriter(full_excel_path, engine='xlsxwriter') as writer:
                    workbook = writer.book
                    center_fmt = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
                    for sheet_name, df_to_write in dataframes_to_save.items():
                        df_to_write.to_excel(writer, sheet_name=sheet_name, index=False)
                        worksheet = writer.sheets[sheet_name]
                        for col_idx, header_name in enumerate(df_to_write.columns):
                            max_len = max(len(str(header_name)),
                                          df_to_write[header_name].astype(str).map(len).max() if not df_to_write[
                                              header_name].empty else 0)
                            worksheet.set_column(col_idx, col_idx, max_len + 4, center_fmt)
                app.log(f"Successfully saved Excel: {excel_filename}")
                any_results_saved = True
            except Exception as write_err:
                app.log(f"!!! Error writing Excel file {full_excel_path}: {write_err}\n{traceback.format_exc()}")
        else:
            app.log(f"No valid data to save for '{cond_label_from_keys}' (PID: {pid}). No Excel file generated.")

    if not any_results_saved:
        app.log("Warning: Post-processing completed, but no Excel files were saved.")
    del current_epochs_data_source
    gc.collect()
    app.log("--- Post-processing finished. ---")