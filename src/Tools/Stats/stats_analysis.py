# -*- coding: utf-8 -*-
"""Utility functions for data processing used by the Stats UI."""

import os
import re
import pandas as pd
import numpy as np
import scipy.stats as stats

from .repeated_m_anova import run_repeated_measures_anova
from Main_App.settings_manager import SettingsManager

# Regions of Interest (10-20 montage)
DEFAULT_ROIS = {
    "Frontal Lobe": ["F3", "F4", "Fz"],
    "Occipital Lobe": ["O1", "O2", "Oz"],
    "Parietal Lobe": ["P3", "P4", "Pz"],
    "Central Lobe": ["C3", "C4", "Cz"],
}

def _load_rois():
    mgr = SettingsManager()
    pairs = mgr.get_roi_pairs()
    rois = {}
    for name, electrodes in pairs:
        if name and electrodes:
            rois[name] = [e.upper() for e in electrodes]
    for name, default_chans in DEFAULT_ROIS.items():
        rois.setdefault(name, default_chans)
    return rois

ROIS = _load_rois()

def set_rois(rois_dict):
    """Update the module-level ROI dictionary."""
    global ROIS
    ROIS = {name: [e.upper() for e in chans] for name, chans in rois_dict.items()}
ALL_ROIS_OPTION = "(All ROIs)"
HARMONIC_CHECK_ALPHA = 0.05


def get_included_freqs(base_freq, all_col_names, log_func):
    try:
        base_freq_val = float(base_freq)
        if base_freq_val <= 0:
            raise ValueError("Base frequency must be positive.")
    except ValueError as e:
        log_func(f"Error: Invalid Base Frequency '{base_freq}': {e}")
        return []

    numeric_freqs = []
    for col_name in all_col_names:
        if isinstance(col_name, str) and col_name.endswith("_Hz"):
            try:
                numeric_freqs.append(float(col_name[:-3]))
            except ValueError:
                log_func(f"Could not parse freq from col: {col_name}")
    if not numeric_freqs:
        return []
    sorted_numeric_freqs = sorted(set(numeric_freqs))
    excluded = {f for f in sorted_numeric_freqs if abs(f / base_freq_val - round(f / base_freq_val)) < 1e-6}
    return [f for f in sorted_numeric_freqs if f not in excluded]


def aggregate_bca_sum(file_path, roi_name, base_freq, log_func):
    try:
        df = pd.read_excel(file_path, sheet_name="BCA (uV)", index_col="Electrode")
        roi_channels = ROIS.get(roi_name)
        if not roi_channels:
            log_func(f"ROI {roi_name} not defined.")
            return np.nan
        df_roi = df.reindex(roi_channels).dropna(how="all")
        if df_roi.empty:
            log_func(f"No data for ROI {roi_name} in {file_path}.")
            return np.nan
        included_freq_values = get_included_freqs(base_freq, df.columns, log_func)
        if not included_freq_values:
            log_func(f"No freqs to sum for BCA in {file_path}.")
            return np.nan
        cols_to_sum = [f"{f:.1f}_Hz" for f in included_freq_values if f"{f:.1f}_Hz" in df_roi.columns]
        if not cols_to_sum:
            log_func(f"No matching BCA freq columns for ROI {roi_name} in {file_path}.")
            return np.nan
        return df_roi[cols_to_sum].sum(axis=1).mean()
    except Exception as e:  # pragma: no cover - simple logging
        log_func(f"Error aggregating BCA for {os.path.basename(file_path)}, ROI {roi_name}: {e}")
        return np.nan


def prepare_all_subject_summed_bca_data(subjects, conditions, subject_data, base_freq, log_func):
    all_subject_data = {}
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None
    for pid in subjects:
        all_subject_data[pid] = {}
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            all_subject_data[pid].setdefault(cond_name, {})
            for roi_name in ROIS.keys():
                sum_val = aggregate_bca_sum(file_path, roi_name, base_freq, log_func) if file_path and os.path.exists(file_path) else np.nan
                all_subject_data[pid][cond_name][roi_name] = sum_val
    log_func("Summed BCA data prep complete.")
    return all_subject_data



def run_rm_anova(all_subject_data, log_func):
    long_format_data = []
    for pid, cond_data in all_subject_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    long_format_data.append({'subject': pid, 'condition': cond_name, 'roi': roi_name, 'value': value})
    if not long_format_data:
        return "No valid data available for RM-ANOVA after filtering NaNs.", None
    df_long = pd.DataFrame(long_format_data)
    if df_long['condition'].nunique() < 2 or df_long['roi'].nunique() < 1:
        return "RM-ANOVA requires at least two conditions and at least one ROI with valid data.", None
    try:
        log_func(f"Calling run_repeated_measures_anova with DataFrame of shape: {df_long.shape}")
        anova_df_results = run_repeated_measures_anova(data=df_long, dv_col='value', within_cols=['condition', 'roi'], subject_col='subject')
    except Exception as e:
        log_func(f"!!! RM-ANOVA Error: {e}")
        return f"RM-ANOVA analysis failed unexpectedly: {e}", None
    if anova_df_results is None or anova_df_results.empty:
        return "RM-ANOVA did not return any results or the result was empty.", None
    return anova_df_results.to_string(index=False), anova_df_results


def run_harmonic_check(subject_data, subjects, conditions, selected_metric, mean_value_threshold, base_freq, log_func):
    findings = []
    output_lines = [f"===== Per-Harmonic Significance Check ({selected_metric}) ====="]
    output_lines.append("A harmonic is flagged as 'Significant' if:")
    output_lines.append(f"1. Its average {selected_metric} is reliably different from zero across subjects")
    output_lines.append(f"   (p-value < {HARMONIC_CHECK_ALPHA}).")
    output_lines.append(f"2. AND this average {selected_metric} is also greater than your threshold of {mean_value_threshold}.")
    output_lines.append("(N = number of subjects included in each specific test listed below)\n")
    any_significant_found = False
    loaded_dataframes = {}
    for cond_name in conditions:
        output_lines.append(f"\n=== Condition: {cond_name} ===")
        for roi_name in ROIS.keys():
            sample_file = None
            for pid_s in subjects:
                if subject_data.get(pid_s, {}).get(cond_name):
                    sample_file = subject_data[pid_s][cond_name]
                    break
            if not sample_file:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append("      Could not determine checkable frequencies (no sample data file found for this condition).\n")
                continue
            try:
                if sample_file not in loaded_dataframes:
                    loaded_dataframes[sample_file] = pd.read_excel(sample_file, sheet_name=selected_metric, index_col="Electrode")
                sample_df_cols = loaded_dataframes[sample_file].columns
                included_freq_values = get_included_freqs(base_freq, sample_df_cols, log_func)
            except Exception as e:
                log_func(f"Error reading columns for ROI '{roi_name}', Cond '{cond_name}': {e}")
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append("      Error determining checkable frequencies for this ROI.\n")
                continue
            if not included_freq_values:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append("      No applicable harmonics to check for this ROI after frequency exclusions.\n")
                continue
            roi_header_printed = False
            sig_count = 0
            for freq_val in included_freq_values:
                harmonic_col = f"{freq_val:.1f}_Hz"
                subj_values = []
                for pid in subjects:
                    f_path = subject_data.get(pid, {}).get(cond_name)
                    if not (f_path and os.path.exists(f_path)):
                        continue
                    current_df = loaded_dataframes.get(f_path)
                    if current_df is None:
                        try:
                            current_df = pd.read_excel(f_path, sheet_name=selected_metric, index_col="Electrode")
                            loaded_dataframes[f_path] = current_df
                        except FileNotFoundError:
                            log_func(f"Error: File not found {f_path} for PID {pid}, Cond {cond_name}.")
                            continue
                    if harmonic_col not in current_df.columns:
                        continue
                    roi_channels = ROIS.get(roi_name)
                    df_roi_metric = current_df.reindex(roi_channels)
                    mean_val_subj_roi_harmonic = df_roi_metric[harmonic_col].dropna().mean()
                    if not pd.isna(mean_val_subj_roi_harmonic):
                        subj_values.append(mean_val_subj_roi_harmonic)
                if len(subj_values) >= 3:
                    t_stat, p_value_raw = stats.ttest_1samp(subj_values, 0, nan_policy='omit')
                    valid_vals = [v for v in subj_values if not pd.isna(v)]
                    n_subj = len(valid_vals)
                    if n_subj < 3:
                        continue
                    mean_group = np.mean(valid_vals)
                    df_val = n_subj - 1
                    if p_value_raw < HARMONIC_CHECK_ALPHA and mean_group > mean_value_threshold:
                        if not roi_header_printed:
                            output_lines.append(f"  --- ROI: {roi_name} ---")
                            roi_header_printed = True
                        any_significant_found = True
                        sig_count += 1
                        p_value_str = "< .0001" if p_value_raw < 0.0001 else f"{p_value_raw:.4f}"
                        output_lines.append("    -------------------------------------------")
                        output_lines.append(f"    Harmonic: {harmonic_col} -> SIGNIFICANT RESPONSE")
                        output_lines.append(f"        Average {selected_metric}: {mean_group:.3f} (based on N={n_subj} subjects)")
                        output_lines.append(f"        Statistical Test: t({df_val}) = {t_stat:.2f}, p-value = {p_value_str}")
                        output_lines.append("    -------------------------------------------")
                        findings.append({
                            'Condition': cond_name,
                            'ROI': roi_name,
                            'Frequency': harmonic_col,
                            'N_Subjects': n_subj,
                            f'Mean_{selected_metric.replace(" ", "_")}' : mean_group,
                            'T_Statistic': t_stat,
                            'P_Value': p_value_raw,
                            'df': df_val,
                            'Threshold_Criteria_Mean_Value': mean_value_threshold,
                            'Threshold_Criteria_Alpha': HARMONIC_CHECK_ALPHA,
                        })
            if roi_header_printed:
                if sig_count > 1:
                    output_lines.append(f"    Summary for {roi_name}: Found {sig_count} significant harmonics (details above).\n")
            elif included_freq_values:
                output_lines.append(f"  --- ROI: {roi_name} ---")
                output_lines.append("      No significant harmonics met criteria for this ROI.\n")
        if not any('--- ROI:' in line for line in output_lines if f"=== Condition: {cond_name} ===" in line):
            output_lines.append("  No processable data or no significant harmonics found for any ROI in this condition.\n")
        output_lines.append("")
    if not any_significant_found:
        output_lines.append("Overall: No harmonics met the significance criteria across all conditions and ROIs.")
    else:
        output_lines.append("\n--- End of Report ---\nTip: For a comprehensive table of all significant findings, please use the 'Export Harmonic Results' feature.")
    return "\n".join(output_lines), findings
