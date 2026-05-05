# post_process.py
import os
import pandas as pd
import numpy as np
import traceback
import gc
import mne
import re
from fractions import Fraction
import config
from config import DEFAULT_ELECTRODE_NAMES_64  # Ensure these are correct
from typing import List, Any, Dict
from Tools.Stats.analysis.full_snr import compute_full_snr
from Tools.Stats.analysis.noise_utils import compute_noise_stats_for_bin
from Main_App.Shared.fft_crop_utils import compute_onbin_N, compute_onbin_step


from Main_App.Shared.post_process_excel import build_fft_neighbors_rows, write_results_workbook


ODDBALL_FREQ = Fraction(6, 5)


def _read_analysis_setting(app: Any, option: str, default: float | str) -> Any:
    """Return analysis setting from SettingsManager-like objects or plain dict payloads."""
    settings = getattr(app, "settings", None)
    if settings is None:
        return default

    getter = getattr(settings, "get", None)
    if callable(getter):
        try:
            # SettingsManager signature: get(section, option, fallback)
            return getter("analysis", option, str(default))
        except TypeError:
            # dict-like getter may not accept 3 args
            pass
        except Exception:
            pass

    if isinstance(settings, dict):
        analysis_section = settings.get("analysis")
        if isinstance(analysis_section, dict) and option in analysis_section:
            return analysis_section.get(option, default)
        if option in settings:
            return settings.get(option, default)

    if hasattr(settings, option):
        try:
            return getattr(settings, option)
        except Exception:
            pass

    return default


def _read_analysis_float(app: Any, option: str, default: float) -> float:
    value = _read_analysis_setting(app, option, default)
    try:
        return float(value)
    except Exception:
        return float(default)


def _resolve_target_frequencies(app: Any) -> tuple[np.ndarray, float]:
    oddball_freq = _read_analysis_float(app, "oddball_freq", config.DEFAULT_ODDBALL_FREQ)
    upper_limit = _read_analysis_float(app, "bca_upper_limit", config.DEFAULT_BCA_UPPER_LIMIT)
    return config.update_target_frequencies(oddball_freq, upper_limit), upper_limit


def _resolve_condition_id(event_id_map: Dict[str, Any], condition_label: str) -> int | None:
    if not event_id_map:
        return None

    if condition_label in event_id_map:
        try:
            return int(event_id_map[condition_label])
        except Exception:
            return None

    def _normalize(lbl: str) -> str:
        return re.sub(r"^\d+\s*-\s*", "", str(lbl)).strip().lower()

    target = _normalize(condition_label)
    for label, value in event_id_map.items():
        if _normalize(label) == target:
            try:
                return int(value)
            except Exception:
                return None
    return None


def _load_events_for_file(raw_path: str, event_id_map: Dict[str, Any], stim_channel_name: str = "Status"):
    raw = mne.io.read_raw(raw_path, preload=False, verbose=False)
    try:
        events = np.array([])
        if len(raw.annotations) > 0 and event_id_map:
            mne_annots_event_id_map = {
                str(desc): int(val)
                for desc, val in event_id_map.items()
                if str(desc) in raw.annotations.description
            }
            if mne_annots_event_id_map:
                events, _ = mne.events_from_annotations(raw, event_id=mne_annots_event_id_map, verbose=False)
        if events.size == 0:
            events = mne.find_events(raw, stim_channel=stim_channel_name, consecutive=True, verbose=False)
        return events, int(raw.n_times)
    finally:
        raw.close()


def _attempt_legacy_55_onbin_crop(
    avg_data: np.ndarray,
    sfreq: float,
    data_idx: int,
    condition_id: int,
    onset_ids: list[int],
    global_events: np.ndarray,
    stream_end_sample: int,
    epoch_start_sec: float,
):
    num_channels, num_times = avg_data.shape
    samples_55 = []
    n55 = None
    first55_samp = None
    last55_samp = None
    n_step = None

    cond_starts = [int(row[0]) for row in global_events if int(row[2]) == condition_id]
    all_starts = sorted([int(row[0]) for row in global_events if int(row[2]) in onset_ids])
    if not cond_starts:
        return avg_data, "fixed_epoch_fallback", n55, first55_samp, last55_samp, n_step, "no_condition_starts"
    if not all_starts:
        return avg_data, "fixed_epoch_fallback", n55, first55_samp, last55_samp, n_step, "no_onset_starts"

    rep_idx = min(data_idx, len(cond_starts) - 1)
    block_start = cond_starts[rep_idx]
    block_end = next((s for s in all_starts if s > block_start), stream_end_sample)

    samples_55 = [
        int(row[0])
        for row in global_events
        if block_start < int(row[0]) < block_end and int(row[2]) == 55
    ]
    n55 = int(len(samples_55))
    first55_samp = int(samples_55[0]) if samples_55 else None
    last55_samp = int(samples_55[-1]) if samples_55 else None

    _, n_step, step_err = compute_onbin_step(fs=float(sfreq), f_oddball=ODDBALL_FREQ)
    if step_err or n_step is None:
        return avg_data, "fixed_epoch_fallback", n55, first55_samp, last55_samp, n_step, step_err or "step_error"
    if len(samples_55) < 2:
        reason = "no_55_in_block" if len(samples_55) == 0 else "insufficient_55"
        return avg_data, "fixed_epoch_fallback", n55, first55_samp, last55_samp, n_step, reason

    available_samples = int(block_end - first55_samp)
    n_used = int(compute_onbin_N(available_samples=available_samples, N_step=n_step))
    epoch_start_sample = int(round(block_start + epoch_start_sec * sfreq))
    crop_start_idx = int(max(0, first55_samp - epoch_start_sample))
    max_available_from_epoch = int(max(0, num_times - crop_start_idx))
    n_used = int(compute_onbin_N(available_samples=min(n_used, max_available_from_epoch), N_step=n_step))

    if n_used < n_step:
        return avg_data, "fixed_epoch_fallback", n55, first55_samp, last55_samp, n_step, "too_short_for_step"

    cropped = avg_data[:, crop_start_idx:crop_start_idx + n_used]
    return cropped, "55_onbin", n55, first55_samp, last55_samp, n_step, ""

def post_process(app: Any, condition_labels_present: List[str]) -> None:
    """
    Calculates metrics (FFT, SNR, Z-score, BCA) and saves results to Excel.
    Handles single-file processing (FPVSApp) and per-participant averaged results (AdvancedAnalysis).

    This is migration-boundary export code. Targeted refactor edits are allowed,
    but must not change metric calculation, processing order, output formats,
    filenames, sheet names, or export behavior.
    """
    app.log("--- Post-processing: Calculating Metrics & Saving Excel ---")
    parent_folder = app.save_folder_path.get()
    if not parent_folder or not os.path.isdir(parent_folder):
        app.log(f"Error: Invalid save folder: '{parent_folder}'")
        return

    target_frequencies, configured_upper_limit = _resolve_target_frequencies(app)
    app.log(
        "Using target frequencies from settings: "
        f"oddball={target_frequencies[0] if len(target_frequencies) else 'n/a'} Hz, "
        f"upper_limit={configured_upper_limit} Hz, "
        f"count={len(target_frequencies)}"
    )

    # --- PID Determination ---
    pid = "UnknownPID"
    # For Advanced Analysis, 'pid_for_group' on the context now holds the participant_pid
    if hasattr(app, "pid_for_group") and app.pid_for_group:
        pid = app.pid_for_group  # This should be "P1", "P2", etc.
        app.log(f"Using PID from context: {pid}")
    elif app.data_paths:  # Fallback for original FPVSApp single-file processing
        try:
            first_file_path = app.data_paths[0]
            first_file_basename = os.path.basename(first_file_path)
            pid_base = os.path.splitext(first_file_basename)[0]
            pid_regex = r"\b(P\d+|Sub\d+|S\d+)\b"
            match = re.search(pid_regex, pid_base, re.IGNORECASE)
            if match:
                pid = match.group(1).upper()
            else:
                pid_cleaned = re.sub(
                    r"(_unamb|_ambig|_mid|_run\d*|_sess\d*|_task\w*|_eeg|_fpvs|_raw|_preproc|_ica).*$",
                    "",
                    pid_base,
                    flags=re.IGNORECASE,
                )
                pid_cleaned = re.sub(r"[^a-zA-Z0-9]", "", pid_cleaned)
                pid = pid_cleaned if pid_cleaned else pid_base
            app.log(f"Extracted PID for single file processing: {pid}")
        except Exception as e:
            app.log(f"Warn: Could not extract PID from app.data_paths[0]: {e}")
    else:
        app.log("Warning: Could not determine PID. Using default 'UnknownPID'.")

    any_results_saved = False
    current_epochs_data_source = app.preprocessed_data
    event_cache: Dict[str, tuple[np.ndarray, int]] = {}

    for cond_label_from_keys in condition_labels_present:
        data_list = current_epochs_data_source.get(cond_label_from_keys, [])
        if not data_list:
            app.log(f"\nSkipping post-processing for '{cond_label_from_keys}': No data found.")
            continue

        app.log(
            f"\nPost-processing '{cond_label_from_keys}' (PID: {pid}, {len(data_list)} data object(s))..."
        )

        # --- Output Naming Logic ---
        folder_name_base = ""
        filename_condition_part = ""
        excel_final_suffix = ".xlsx"  # Desired suffix for advanced outputs

        # Check if this is an output from the advanced analysis per-participant flow
        is_advanced_output = (
            hasattr(app, "group_name_for_output")
            and app.group_name_for_output
            and app.group_name_for_output == cond_label_from_keys
        )

        if is_advanced_output:
            # Use the recipe name (e.g., "Average A") from the context
            condition_recipe_name = app.group_name_for_output
            # Sanitize for folder and file: replace spaces with underscores, etc.
            sanitized_recipe_name = (
                condition_recipe_name.replace(" ", "_")
                .replace("/", "-")
                .replace("\\", "-")
                .strip()
            )
            sanitized_recipe_name = re.sub(
                r"^\d+\s*-\s*", "", sanitized_recipe_name
            )  # Remove "1 - " prefixes etc.

            folder_name_base = sanitized_recipe_name  # Subfolder e.g., "Average_A"
            filename_condition_part = sanitized_recipe_name  # File part e.g., "Average_A"
            # pid is already the participant_pid, e.g., "P1"
            excel_filename = f"{pid}_{filename_condition_part}{excel_final_suffix}"  # e.g., "P1_Average_A.xlsx"
        else:
            # Original FPVSApp single-file processing path
            raw_condition_label = cond_label_from_keys
            sanitized_condition_label = re.sub(
                r"^\d+\s*-\s*",
                "",
                raw_condition_label.replace("/", "-").replace("\\", "-").strip(),
            )

            folder_name_base = sanitized_condition_label
            filename_condition_part = sanitized_condition_label
            # Original naming for FPVSApp might be different, adjust if needed
            excel_filename = f"{pid}_{filename_condition_part}_Results.xlsx"

        # Create subfolder
        output_subfolder_path = os.path.join(parent_folder, folder_name_base)
        try:
            os.makedirs(output_subfolder_path, exist_ok=True)
        except OSError as e:
            app.log(
                f"Error creating subfolder {output_subfolder_path}: {e}. Saving to parent folder: {parent_folder}"
            )
            output_subfolder_path = parent_folder

        full_excel_path = os.path.join(output_subfolder_path, excel_filename)
        app.log(f"Target Excel path for '{cond_label_from_keys}': {full_excel_path}")

        # --- Metrics Calculation (largely unchanged) ---
        accum = {"fft": None, "snr": None, "z": None, "bca": None}
        full_snr_accum = None
        fft_neighbors_rows: List[Dict[str, Any]] = []
        valid_data_count = 0
        final_num_channels = 0
        final_electrode_names_ordered = []

        for data_idx, data_object in enumerate(data_list):  # Should be one Evoked for advanced
            is_evoked = isinstance(data_object, mne.Evoked)
            if not (hasattr(data_object, "info") and (is_evoked or hasattr(data_object, "get_data"))):
                app.log(
                    f"    Item {data_idx + 1} is not a valid MNE data object. Skipping."
                )
                continue
            app.log(
                f"  Processing data object {data_idx + 1}/{len(data_list)} for '{cond_label_from_keys}'..."
            )
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
                    "eeg", exclude="bads" if not is_evoked else []
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
                current_ch_names_from_obj = data_eeg.info["ch_names"]
                ordered_electrode_names_for_df = []

                if num_channels == len(DEFAULT_ELECTRODE_NAMES_64) and set(
                    current_ch_names_from_obj
                ) == set(DEFAULT_ELECTRODE_NAMES_64):
                    ordered_electrode_names_for_df = [
                        name
                        for name in DEFAULT_ELECTRODE_NAMES_64
                        if name in current_ch_names_from_obj
                    ]
                    name_to_idx_map = {
                        name: i for i, name in enumerate(current_ch_names_from_obj)
                    }
                    reorder_indices = [
                        name_to_idx_map[name] for name in ordered_electrode_names_for_df
                    ]
                    avg_data = avg_data[reorder_indices, :]
                    app.log(
                        f"    Standardized channel order to {len(ordered_electrode_names_for_df)} channels."
                    )
                elif num_channels == len(DEFAULT_ELECTRODE_NAMES_64):
                    app.log(
                        f"    Warn: Found {num_channels} channels, names don't match default. Using default order/names."
                    )
                    ordered_electrode_names_for_df = DEFAULT_ELECTRODE_NAMES_64
                else:
                    app.log(
                        f"    Warn: Found {num_channels} channels. Using actual names/order."
                    )
                    ordered_electrode_names_for_df = current_ch_names_from_obj

                if valid_data_count == 0:
                    final_num_channels = num_channels
                    final_electrode_names_ordered = ordered_electrode_names_for_df
                if (
                    num_channels != final_num_channels
                    or ordered_electrode_names_for_df != final_electrode_names_ordered
                ):
                    app.log("    Error: Channel mismatch. Skipping object.")
                    continue

                sfreq = data_eeg.info["sfreq"]

                crop_mode = "fixed_epoch_fallback"
                n55 = None
                first55_samp = None
                last55_samp = None
                n_step = None
                fallback_reason = "legacy_epoch_path"

                if is_evoked and app.data_paths:
                    validated_params = getattr(app, "validated_params", {}) or {}
                    event_id_map = validated_params.get("event_id_map", {})
                    condition_id = _resolve_condition_id(event_id_map, cond_label_from_keys)
                    onset_ids = sorted({int(v) for v in event_id_map.values() if str(v).isdigit()})
                    epoch_start_sec = float(validated_params.get("epoch_start", 0.0))
                    if condition_id is None:
                        fallback_reason = "missing_condition_id"
                    elif not onset_ids:
                        fallback_reason = "missing_onset_ids"
                    else:
                        try:
                            source_path = app.data_paths[0]
                            if source_path not in event_cache:
                                event_cache[source_path] = _load_events_for_file(raw_path=source_path, event_id_map=event_id_map)
                            global_events, stream_end_sample = event_cache[source_path]

                            avg_data, crop_mode, n55, first55_samp, last55_samp, n_step, fallback_reason = _attempt_legacy_55_onbin_crop(
                                avg_data=avg_data,
                                sfreq=float(sfreq),
                                data_idx=int(data_idx),
                                condition_id=int(condition_id),
                                onset_ids=onset_ids,
                                global_events=global_events,
                                stream_end_sample=int(stream_end_sample),
                                epoch_start_sec=float(epoch_start_sec),
                            )
                            num_channels, num_times = avg_data.shape
                        except Exception as crop_err:
                            app.log(f"    Warn: 55-based crop attempt failed in legacy path: {crop_err}")
                            fallback_reason = "crop_exception"

                if not is_evoked and getattr(data_object, "metadata", None) is not None and not data_object.metadata.empty:
                    md = data_object.metadata
                    crop_modes = [m for m in md.get("crop_mode", pd.Series(dtype=object)).dropna().astype(str).tolist() if m]
                    if crop_modes and all(m == "55_onbin" for m in crop_modes):
                        crop_mode = "55_onbin"
                        fallback_reason = ""
                    elif crop_modes:
                        crop_mode = "fixed_epoch_fallback"
                        fallback_reasons = [
                            r
                            for r in md.get("fallback_reason", pd.Series(dtype=object)).fillna("").astype(str).tolist()
                            if r
                        ]
                        fallback_reason = "; ".join(sorted(set(fallback_reasons))) if fallback_reasons else "mixed_or_fallback_reps"

                    n55_vals = md.get("n55", pd.Series(dtype=float)).dropna().tolist()
                    if n55_vals:
                        n55 = int(min(n55_vals))

                    first_vals = md.get("first55_samp", pd.Series(dtype=float)).dropna().tolist()
                    if first_vals:
                        first55_samp = int(min(first_vals))

                    last_vals = md.get("last55_samp", pd.Series(dtype=float)).dropna().tolist()
                    if last_vals:
                        last55_samp = int(max(last_vals))

                    step_vals = md.get("N_step", pd.Series(dtype=float)).dropna().tolist()
                    if step_vals:
                        unique_steps = sorted({int(v) for v in step_vals})
                        if len(unique_steps) > 1:
                            raise ValueError(f"Inconsistent N_step values for {cond_label_from_keys}: {unique_steps}")
                        n_step = unique_steps[0]

                if crop_mode == "55_onbin":
                    if not n_step:
                        raise ValueError(f"Missing N_step for 55_onbin path in condition {cond_label_from_keys}")
                    if num_times % n_step != 0:
                        raise ValueError(
                            f"55_onbin data is not divisible by N_step in post_process: N={num_times}, N_step={n_step}"
                        )

                avg_data_uv = avg_data * 1e6
                if data_idx == 0:
                    app.log(
                        f"    Scaling to uV. Max: {np.max(np.abs(avg_data_uv)):.2f} uV"
                    )

                num_fft_bins = num_times // 2 + 1
                fft_frequencies = np.fft.rfftfreq(num_times, d=1.0 / sfreq)
                fft_full_spectrum = np.fft.fft(avg_data_uv, axis=1)
                fft_amplitudes = (
                    np.abs(fft_full_spectrum[:, :num_fft_bins]) / num_times * 2
                )

                source_file_name = os.path.basename(app.data_paths[0]) if app.data_paths else pid
                fft_neighbors_rows.extend(
                    build_fft_neighbors_rows(
                        file_name=source_file_name,
                        condition_label=cond_label_from_keys,
                        condition_id=cond_label_from_keys,
                        repetition_index=str(data_idx + 1),
                        electrode_names=ordered_electrode_names_for_df,
                        fft_amplitudes=fft_amplitudes,
                        freqs=fft_frequencies,
                        fs=sfreq,
                        n_samples=num_times,
                        target_freq=1.2,
                        crop_mode=crop_mode,
                        n55=n55,
                        first55_samp=first55_samp,
                        last55_samp=last55_samp,
                        n_step=n_step,
                        fallback_reason=fallback_reason,
                    )
                )

                # Full-spectrum SNR (uses shared noise logic via compute_full_snr)
                full_snr_matrix = compute_full_snr(avg_data_uv, sfreq)

                num_target_freqs = len(target_frequencies)
                metrics_fft = np.zeros((final_num_channels, num_target_freqs))
                metrics_snr = np.zeros((final_num_channels, num_target_freqs))
                metrics_z = np.zeros((final_num_channels, num_target_freqs))
                metrics_bca = np.zeros((final_num_channels, num_target_freqs))

                for chan_idx in range(final_num_channels):
                    channel_amplitudes = fft_amplitudes[chan_idx, :]
                    for freq_idx, target_freq in enumerate(target_frequencies):
                        if not (fft_frequencies[0] <= target_freq <= fft_frequencies[-1]):
                            if chan_idx == 0 and data_idx == 0:
                                app.log(
                                    f"    Skipping target freq {target_freq} Hz."
                                )
                            continue

                        target_bin_index = int(np.argmin(np.abs(fft_frequencies - target_freq)))
                        exact_k = int(round(target_freq * num_times / sfreq))
                        on_bin = abs((target_freq * num_times / sfreq) - round(target_freq * num_times / sfreq)) < 1e-9
                        if on_bin and 0 <= exact_k < len(fft_frequencies):
                            if exact_k != target_bin_index:
                                app.log(
                                    f"WARN [fft_crop] bin_mismatch cond={cond_label_from_keys} target={target_freq} argmin={target_bin_index} exact={exact_k}"
                                )
                            target_bin_index = exact_k

                        # Shared noise-floor logic: ±10 bins, exclude neighbors, remove 2 extremes
                        noise_mean_val, noise_std_val = compute_noise_stats_for_bin(
                            channel_amplitudes,
                            target_bin_index,
                            window_size=10,
                            min_bins=4,
                        )
                        if (
                            noise_mean_val == 0.0
                            and noise_std_val == 0.0
                            and data_idx == 0
                            and chan_idx == 0
                        ):
                            app.log(
                                f"    Warn: Not enough noise bins near {target_freq:.1f} Hz."
                            )

                        signal_amplitude = channel_amplitudes[target_bin_index]
                        peak_signal_amplitude = signal_amplitude

                        snr_val = (
                            signal_amplitude / noise_mean_val
                            if noise_mean_val > 1e-12
                            else 0.0
                        )
                        z_score_val = (
                            (peak_signal_amplitude - noise_mean_val) / noise_std_val
                            if noise_std_val > 1e-12
                            else 0.0
                        )
                        bca_val = signal_amplitude - noise_mean_val

                        metrics_fft[chan_idx, freq_idx] = signal_amplitude
                        metrics_snr[chan_idx, freq_idx] = snr_val
                        metrics_z[chan_idx, freq_idx] = z_score_val
                        metrics_bca[chan_idx, freq_idx] = bca_val

                if accum["fft"] is None:
                    accum = {
                        "fft": metrics_fft,
                        "snr": metrics_snr,
                        "z": metrics_z,
                        "bca": metrics_bca,
                    }
                    full_snr_accum = full_snr_matrix
                else:
                    accum["fft"] += metrics_fft
                    accum["snr"] += metrics_snr
                    accum["z"] += metrics_z
                    accum["bca"] += metrics_bca
                    full_snr_accum += full_snr_matrix
                valid_data_count += 1
            except Exception as e:
                app.log(
                    f"!!! Error post-processing data object {data_idx + 1}: {e}\n{traceback.format_exc()}"
                )
            finally:
                del data_eeg
                gc.collect()

        if valid_data_count > 0 and final_electrode_names_ordered:
            avg_metrics = {k: v / valid_data_count for k, v in accum.items()}
            freq_column_names = [f"{f:.4f}_Hz" for f in target_frequencies]
            full_snr_avg = (
                full_snr_accum / valid_data_count if full_snr_accum is not None else None
            )
            dataframes_to_save = {
                "FFT Amplitude (uV)": pd.DataFrame(
                    avg_metrics["fft"],
                    index=final_electrode_names_ordered,
                    columns=freq_column_names,
                ),
                "SNR": pd.DataFrame(
                    avg_metrics["snr"],
                    index=final_electrode_names_ordered,
                    columns=freq_column_names,
                ),
                "Z Score": pd.DataFrame(
                    avg_metrics["z"],
                    index=final_electrode_names_ordered,
                    columns=freq_column_names,
                ),
                "BCA (uV)": pd.DataFrame(
                    avg_metrics["bca"],
                    index=final_electrode_names_ordered,
                    columns=freq_column_names,
                ),
            }
            if full_snr_avg is not None:
                max_freq = min(configured_upper_limit, float(fft_frequencies[-1]))
                freq_grid = np.arange(0.5, max_freq + 0.01, 0.01)

                interp_snr = np.zeros((full_snr_avg.shape[0], len(freq_grid)))
                for ch_idx in range(full_snr_avg.shape[0]):
                    interp_snr[ch_idx] = np.interp(
                        freq_grid, fft_frequencies, full_snr_avg[ch_idx]
                    )

                freq_cols_full = [f"{f:.4f}_Hz" for f in freq_grid]

                dataframes_to_save["FullSNR"] = pd.DataFrame(
                    interp_snr,
                    index=final_electrode_names_ordered,
                    columns=freq_cols_full,
                )
            for df_name_iter in dataframes_to_save:
                dataframes_to_save[df_name_iter].insert(
                    0, "Electrode", dataframes_to_save[df_name_iter].index
                )

            neighbor_columns = [
                "file_name",
                "condition_label",
                "condition_id",
                "repetition_index",
                "channel_or_roi",
                "target",
                "fs",
                "N",
                "T_sec",
                "df_hz",
                "k0",
                "f_bin_hz",
                "crop_mode",
                "n55",
                "first55_samp",
                "last55_samp",
                "N_step",
                "N_mod_step",
                "fallback_reason",
                *[f"amp_m{i}" for i in range(11, 0, -1)],
                *[f"amp_p{i}" for i in range(1, 12)],
                "warning",
            ]
            fft_neighbors_df = pd.DataFrame(fft_neighbors_rows)
            if fft_neighbors_df.empty:
                fft_neighbors_df = pd.DataFrame(columns=neighbor_columns)
            else:
                fft_neighbors_df = fft_neighbors_df.reindex(columns=neighbor_columns)

            try:
                write_results_workbook(
                    full_excel_path=full_excel_path,
                    dataframes_to_save=dataframes_to_save,
                    fft_neighbors_df=fft_neighbors_df,
                )
                app.log(f"Successfully saved Excel: {excel_filename}")
                any_results_saved = True
            except Exception as write_err:
                app.log(
                    f"!!! Error writing Excel file {full_excel_path}: {write_err}\n{traceback.format_exc()}"
                )
        else:
            app.log(
                f"No valid data to save for '{cond_label_from_keys}' (PID: {pid}). No Excel file generated."
            )

    if not any_results_saved:
        app.log("Warning: Post-processing completed, but no Excel files were saved.")
    del current_epochs_data_source
    gc.collect()
    app.log("--- Post-processing finished. ---")
