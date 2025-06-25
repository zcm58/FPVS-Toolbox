"""Handles the main preprocessing routine for the FPVS Toolbox.
It manages referencing, filtering, resampling and kurtosis-based
artifact rejection while logging progress for the user. Cleaned
``mne.Raw`` objects are returned for further analysis."""

import os
import traceback

import mne
import numpy as np
from scipy.stats import kurtosis

from config import DEFAULT_STIM_CHANNEL




def preprocess_raw(app, raw, **params):
    """Apply preprocessing steps to the raw MNE object."""
    downsample_rate = params.get('downsample_rate')
    low_pass = params.get('low_pass')
    high_pass = params.get('high_pass')
    reject_thresh = params.get('reject_thresh')
    ref1 = params.get('ref_channel1')
    ref2 = params.get('ref_channel2')
    max_keep = params.get('max_idx_keep')
    stim_ch = params.get('stim_channel', DEFAULT_STIM_CHANNEL)

    current_filename = "UnknownFile"
    if raw.filenames and raw.filenames[0]:
        current_filename = os.path.basename(raw.filenames[0])
    elif getattr(raw, 'filename', None):
        current_filename = os.path.basename(raw.filename)

    try:
        orig_ch_names = list(raw.info['ch_names'])
        app.log(f"Preprocessing {len(orig_ch_names)} chans from '{current_filename}'...")
        if app.settings.debug_enabled():
            app.log(
                f"DEBUG [preprocess_raw for {current_filename}]: Initial channel names ({len(orig_ch_names)}): {orig_ch_names}")
            app.log(
                f"DEBUG [preprocess_raw for {current_filename}]: Expected stim_ch for preservation: '{stim_ch}', max_idx_keep parameter: {max_keep}")
        if stim_ch not in orig_ch_names:
            if app.settings.debug_enabled():
                app.log(
                    f"DEBUG [preprocess_raw for {current_filename}]: WARNING - Expected stim_ch '{stim_ch}' is NOT in the initial channel list.")

        if ref1 and ref2 and ref1 in orig_ch_names and ref2 in orig_ch_names:
            try:
                app.log(f"Applying reference: Subtract average of {ref1} & {ref2} for {current_filename}...")
                raw.set_eeg_reference(ref_channels=[ref1, ref2], projection=False, verbose=False)
                app.log(f"Initial reference applied to {current_filename}.")
            except Exception as e:
                app.log(f"Warn: Initial reference failed for {current_filename}: {e}")
        else:
            app.log(
                f"Skip initial referencing for {current_filename} (Ref channels '{ref1}', '{ref2}' not found or not specified).")

        current_names_before_drop = list(raw.info['ch_names'])
        if app.settings.debug_enabled():
            app.log(
                f"DEBUG [preprocess_raw for {current_filename}]: Channel names BEFORE drop logic ({len(current_names_before_drop)}): {current_names_before_drop}")

        if max_keep is not None and 0 < max_keep < len(current_names_before_drop):
            channels_to_keep_by_index = current_names_before_drop[:max_keep]
            if app.settings.debug_enabled():
                app.log(
                    f"DEBUG [preprocess_raw for {current_filename}]: Initial channels selected by index (first {max_keep}): {channels_to_keep_by_index}")

            final_channels_to_keep = list(channels_to_keep_by_index)
            if stim_ch in current_names_before_drop:
                if stim_ch not in final_channels_to_keep:
                    final_channels_to_keep.append(stim_ch)
                    if app.settings.debug_enabled():
                        app.log(
                            f"DEBUG [preprocess_raw for {current_filename}]: Stim_ch '{stim_ch}' was present in data and explicitly added to keep_channels.")
                else:
                    if app.settings.debug_enabled():
                        app.log(
                            f"DEBUG [preprocess_raw for {current_filename}]: Stim_ch '{stim_ch}' was present and already within the first {max_keep} channels.")
            else:
                if app.settings.debug_enabled():
                    app.log(
                        f"DEBUG [preprocess_raw for {current_filename}]: NOTE - Configured stim_ch '{stim_ch}' was NOT FOUND in current channel names before drop logic execution: {current_names_before_drop}.")

            unique_set_to_keep = set(final_channels_to_keep)
            ordered_unique_keep_channels = [name for name in current_names_before_drop if
                                            name in unique_set_to_keep]

            channels_to_drop = [ch for ch in current_names_before_drop if
                                ch not in ordered_unique_keep_channels]

            if app.settings.debug_enabled():
                app.log(
                    f"DEBUG [preprocess_raw for {current_filename}]: Final list of channels to KEEP ({len(ordered_unique_keep_channels)}): {ordered_unique_keep_channels}")
                app.log(
                    f"DEBUG [preprocess_raw for {current_filename}]: Final list of channels to DROP ({len(channels_to_drop)}): {channels_to_drop}")

            if channels_to_drop:
                app.log(f"Attempting to drop {len(channels_to_drop)} channels from {current_filename}...")
                raw.drop_channels(channels_to_drop, on_missing='warn')
                app.log(f"{len(raw.ch_names)} channels remain in {current_filename} after drop operation.")
                if app.settings.debug_enabled():
                    app.log(
                        f"DEBUG [preprocess_raw for {current_filename}]: Channel names AFTER drop operation: {list(raw.info['ch_names'])}")
            else:
                app.log(f"No channels were ultimately selected to be dropped for {current_filename}.")
        else:
            app.log(
                f"Skip channel drop based on max_keep for {current_filename} (max_keep is None, 0, or >= num channels). Current channels: {len(current_names_before_drop)}")

        if downsample_rate:
            sf = raw.info['sfreq']
            app.log(f"Downsample check for {current_filename}: Curr {sf:.1f}Hz, Tgt {downsample_rate}Hz.")
            if sf > downsample_rate:
                resample_window = 'hann'
                try:
                    raw.resample(downsample_rate, npad="auto", window=resample_window, verbose=False)
                    app.log(f"Resampled {current_filename} to {raw.info['sfreq']:.1f}Hz.")
                except Exception as resample_err:
                    app.log(f"Warn: Resampling failed for {current_filename}: {resample_err}")
            else:
                app.log(f"No downsampling needed for {current_filename}.")
        else:
            app.log(f"Skip downsample for {current_filename}.")

        l_freq = low_pass if low_pass and low_pass > 0 else None
        h_freq = high_pass
        if l_freq or h_freq:
            try:
                low_trans_bw = 0.1
                high_trans_bw = 0.1
                filter_len_points = 8449
                app.log(
                    f"Filtering {current_filename} ({l_freq if l_freq else 'DC'}-{h_freq if h_freq else 'Nyq'}Hz) ...")
                raw.filter(l_freq, h_freq, method='fir', phase='zero-double',
                           fir_window='hamming', fir_design='firwin',
                           l_trans_bandwidth=low_trans_bw, h_trans_bandwidth=high_trans_bw,
                           filter_length=filter_len_points, skip_by_annotation='edge', verbose=False)
                app.log(f"Filter OK for {current_filename}.")
            except Exception as e:
                app.log(f"Warn: Filter failed for {current_filename}: {e}")
        else:
            app.log(f"Skip filter for {current_filename}.")

        if reject_thresh:
            app.log(f"Kurtosis rejection for {current_filename} (Z > {reject_thresh})...")
            bad_k_auto = []
            eeg_picks_for_kurtosis = mne.pick_types(raw.info, eeg=True,
                                                    exclude=raw.info['bads'] + ([stim_ch] if stim_ch in raw.ch_names else []))
            if len(eeg_picks_for_kurtosis) >= 2:
                data = raw.get_data(picks=eeg_picks_for_kurtosis)
                k_values = kurtosis(data, axis=1, fisher=True, bias=False)
                k_values = np.nan_to_num(k_values)
                proportion_to_cut = 0.1
                n_k = len(k_values)
                trim_count = int(np.floor(n_k * proportion_to_cut))
                if n_k - 2 * trim_count > 1:
                    k_sorted = np.sort(k_values)
                    k_trimmed = k_sorted[trim_count: n_k - trim_count]
                    m_trimmed, s_trimmed = np.mean(k_trimmed), np.std(k_trimmed)
                    app.log(
                        f"Trimmed Norm for {current_filename}: Mean={m_trimmed:.3f}, Std={s_trimmed:.3f} (N_trimmed={len(k_trimmed)})")
                    if s_trimmed > 1e-9:
                        z_scores_trimmed = (k_values - m_trimmed) / s_trimmed
                        bad_k_indices_in_eeg_picks = np.where(np.abs(z_scores_trimmed) > reject_thresh)[0]
                        ch_names_picked_for_kurtosis = [raw.info['ch_names'][i] for i in eeg_picks_for_kurtosis]
                        bad_k_auto = [ch_names_picked_for_kurtosis[i] for i in bad_k_indices_in_eeg_picks]
                    else:
                        app.log(f"Kurtosis Trimmed Std Dev near zero for {current_filename}.")
                else:
                    app.log(f"Not enough data for Kurtosis trimmed stats in {current_filename} (N_k={n_k}).")
                if bad_k_auto:
                    app.log(f"Bad by Kurtosis for {current_filename}: {bad_k_auto}")
                else:
                    app.log(f"No channels bad by Kurtosis for {current_filename}.")
            else:
                app.log(f"Skip Kurtosis for {current_filename} ( < 2 good EEG channels).")
            new_bads_from_kurtosis = [b for b in bad_k_auto if b not in raw.info['bads']]
            if new_bads_from_kurtosis:
                raw.info['bads'].extend(new_bads_from_kurtosis)
            if raw.info['bads']:
                app.log(f"Interpolating bads in {current_filename}: {raw.info['bads']}")
                if raw.get_montage():
                    try:
                        raw.interpolate_bads(reset_bads=True, mode='accurate', verbose=False)
                        app.log(f"Interpolation OK for {current_filename}.")
                    except Exception as e:
                        app.log(f"Warn: Interpolation failed for {current_filename}: {e}")
                else:
                    app.log(
                        f"Warn: No montage for {current_filename}, cannot interpolate. Bads remain: {raw.info['bads']}")
            else:
                app.log(f"No bads to interpolate in {current_filename}.")
        else:
            app.log(f"Skip Kurtosis for {current_filename} (no threshold).")

        try:
            app.log(f"Applying average reference to {current_filename}...")
            eeg_picks_for_ref = mne.pick_types(raw.info, eeg=True, exclude=raw.info['bads'])
            if len(eeg_picks_for_ref) > 0:
                raw.set_eeg_reference(ref_channels='average', picks=eeg_picks_for_ref, projection=True,
                                      verbose=False)
                raw.apply_proj(verbose=False)
                app.log(f"Average reference applied to {current_filename}.")
            else:
                app.log(f"Skip average ref for {current_filename}: No good EEG channels.")
        except Exception as e:
            app.log(f"Warn: Average reference failed for {current_filename}: {e}")

        app.log(
            f"Preprocessing OK for {current_filename}. {len(raw.ch_names)} channels, {raw.info['sfreq']:.1f}Hz.")
        final_ch_names = list(raw.info['ch_names'])
        if app.settings.debug_enabled():
            app.log(
                f"DEBUG [preprocess_raw for {current_filename}]: Final channel names before returning ({len(final_ch_names)}): {final_ch_names}")
            if stim_ch in final_ch_names:
                app.log(
                    f"DEBUG [preprocess_raw for {current_filename}]: Expected stim_ch '{stim_ch}' IS PRESENT at the VERY END of preprocessing.")
            else:
                app.log(
                    f"DEBUG [preprocess_raw for {current_filename}]: CRITICAL! Expected stim_ch '{stim_ch}' IS NOT PRESENT at the VERY END of preprocessing.")
        return raw

    except Exception as e:
        app.log(f"!!! CRITICAL Preprocessing error for {current_filename}: {e}")
        app.log(f"Traceback: {traceback.format_exc()}")
        return None
