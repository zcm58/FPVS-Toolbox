# stats_export.py
# -*- coding: utf-8 -*-
"""
Contains functions for exporting statistical analysis results from the FPVS Stats Tool
to formatted Excel files using pandas and xlsxwriter.
"""

import os
import pandas as pd
import tkinter as tk  # Required for filedialog/messagebox
from tkinter import filedialog, messagebox
import numpy as np  # For handling np.nan if necessary
import traceback  # For detailed error logging


# --- Helper Function for Excel Formatting ---
def _auto_format_and_write_excel(writer, df, sheet_name, log_func, custom_formats=None, default_col_width=15,
                                 padding=2):
    """
    Writes a DataFrame to an Excel sheet with auto-adjusted column widths and basic formatting.
    Uses xlsxwriter engine.

    Args:
        writer (pd.ExcelWriter): Pandas ExcelWriter object.
        df (pd.DataFrame): DataFrame to write.
        sheet_name (str): Name of the sheet.
        log_func (callable): Logging function.
        custom_formats (dict, optional): Dict of {'col_name': xlsxwriter_format_object}.
        default_col_width (int): Default column width if auto-sizing fails.
        padding (int): Padding to add to auto-sized column width.
    """
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    workbook = writer.book
    worksheet = writer.sheets[sheet_name]

    # Default formats
    header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top',
                                         'align': 'center', 'border': 1, 'fg_color': '#DDEBF7'})
    center_format = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
    left_format = workbook.add_format({'align': 'left', 'valign': 'vcenter'})
    num_format_2dp = workbook.add_format({'num_format': '0.00', 'align': 'center', 'valign': 'vcenter'})
    num_format_3dp = workbook.add_format({'num_format': '0.000', 'align': 'center', 'valign': 'vcenter'})
    num_format_4dp = workbook.add_format({'num_format': '0.0000', 'align': 'center', 'valign': 'vcenter'})
    int_format = workbook.add_format({'num_format': '0', 'align': 'center', 'valign': 'vcenter'})

    # Write headers with formatting
    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, header_format)

    # Apply formatting and auto-adjust column widths
    for col_idx, col_name in enumerate(df.columns):
        # Determine format
        cell_format = center_format  # Default to center
        if custom_formats and col_name in custom_formats:
            cell_format = custom_formats[col_name]
        elif df[col_name].dtype == np.int64 or df[col_name].dtype == np.int32:
            cell_format = int_format
        elif df[col_name].dtype == np.float64 or df[col_name].dtype == np.float32:
            # Basic heuristic for float precision, can be refined
            if 'p_value' in col_name.lower() or 'P_Value' in col_name:  # more decimals for p-values
                cell_format = num_format_4dp
            elif 't_statistic' in col_name.lower() or 'F_value' in col_name.lower() or 'Mean_Difference' in col_name:  # 2dp for t-stats, F
                cell_format = num_format_2dp
            else:  # Default for other floats (means etc.)
                cell_format = num_format_3dp
        elif pd.api.types.is_string_dtype(df[col_name]) or pd.api.types.is_object_dtype(df[col_name]):
            # Check if column name suggests it should be centered or left aligned
            if col_name in ['Condition', 'ROI', 'Effect']:  # Typically longer text
                cell_format = left_format
            else:  # Shorter text like Frequency
                cell_format = center_format

        # Calculate width based on data and header length
        try:
            # Ensure data is string for length calculation, handle potential NaN properly
            max_len_data = df[col_name].astype(str).map(len).max()
            if pd.isna(max_len_data): max_len_data = 0  # Handle all-NaN columns

            # Header length
            header_len = len(str(col_name))

            col_width = max(int(max_len_data), header_len) + padding
            col_width = max(col_width, 10)  # Minimum width of 10
            col_width = min(col_width, 50)  # Maximum width of 50 to prevent overly wide columns

        except Exception as e_width:
            log_func(f"Warning: Could not auto-set width for column '{col_name}': {e_width}")
            col_width = default_col_width  # Fallback width

        worksheet.set_column(col_idx, col_idx, col_width, cell_format)
    log_func(f"Formatted sheet: {sheet_name}")


# --- Export Function for Per-Harmonic Significance Check Results ---
def export_significance_results_to_excel(findings_dict, metric, threshold, parent_folder, log_func=print):
    """
    Exports structured Per-Harmonic Significance Check findings to a formatted Excel file.

    Args:
        findings_dict (dict): Nested {condition: {roi: [finding_list]}}.
                              finding_list contains dicts with keys like 'Frequency',
                              'Mean_MetricName', 'N_Subjects', 'T_Statistic', 'P_Value', 'df',
                              'Threshold' (previously documented as 'Threshold_Used').
        metric (str): Metric analyzed (e.g., "SNR", "Z-Score").
        threshold (float): Mean value threshold used.
        parent_folder (str): Path for suggesting save location.
        log_func (callable): Logging function.
    """
    log_func("Attempting to export Per-Harmonic Significance Check results...")

    if not findings_dict or not any(any(roi_data.values()) for roi_data in findings_dict.values()):
        log_func("No significant findings available to export for Harmonic Check.")
        messagebox.showwarning("No Results", "No significant findings from Harmonic Check to export.")
        return

    flat_results = []
    mean_metric_col_key = f'Mean_{metric.replace(" ", "_")}'  # Key for the mean metric value column

    for condition, roi_data in findings_dict.items():
        for roi_name, findings_list in roi_data.items():
            for finding in findings_list:
                row = {
                    'Condition': condition,
                    'ROI': roi_name,
                    'Frequency': finding.get('Frequency', 'N/A'),
                    mean_metric_col_key: finding.get(mean_metric_col_key, np.nan),
                    'N_Subjects': finding.get('N', np.nan),  # 'N' from stats.py's dict structure for this
                    'df': finding.get('df', np.nan),
                    'T_Statistic': finding.get('T_Statistic', np.nan),
                    'P_Value': finding.get('P_Value', np.nan),
                    'Mean_Threshold_Used': finding.get('Threshold', np.nan)  # value from the 'Threshold' field
                }
                flat_results.append(row)

    if not flat_results:
        log_func("Harmonic check data yielded no results to flatten for export.")
        messagebox.showwarning("No Results", "Could not prepare Harmonic Check results for export.")
        return

    df_export = pd.DataFrame(flat_results)

    # Define preferred column order
    preferred_cols = ['Condition', 'ROI', 'Frequency', mean_metric_col_key,
                      'N_Subjects', 'df', 'T_Statistic', 'P_Value', 'Mean_Threshold_Used']
    df_export = df_export[[col for col in preferred_cols if col in df_export.columns]]

    initial_dir = parent_folder if os.path.isdir(parent_folder) else os.path.expanduser("~")
    metric_filename = metric.replace(" ", "").replace("-", "")
    threshold_filename = f"{threshold:.2f}".replace('.', 'p')
    suggested_filename = f"Stats_HarmonicCheck_{metric_filename}_Thresh{threshold_filename}.xlsx"

    save_path = filedialog.asksaveasfilename(
        title=f"Save Harmonic Check Results ({metric}, Mean > {threshold:.2f})",
        initialdir=initial_dir, initialfile=suggested_filename, defaultextension=".xlsx",
        filetypes=[("Excel Workbook", "*.xlsx"), ("All Files", "*.*")]
    )
    if not save_path: log_func("Harmonic Check export cancelled."); return

    try:
        log_func(f"Exporting Harmonic Check results to: {save_path}")
        with pd.ExcelWriter(save_path, engine='xlsxwriter') as writer:
            _auto_format_and_write_excel(writer, df_export, 'Significant Harmonics', log_func)
        log_func("Harmonic Check results export successful.")
        messagebox.showinfo("Export Successful", f"Harmonic Check results exported to:\n{save_path}")
    except PermissionError:
        err_msg = f"Permission denied writing to {save_path}. File may be open or folder write-protected."
        log_func(f"!!! Export Failed: {err_msg}")
        messagebox.showerror("Export Failed", err_msg)
    except Exception as e:
        log_func(f"!!! Harmonic Check Export Failed: {e}\n{traceback.format_exc()}")
        messagebox.showerror("Export Failed", f"Could not save Excel file: {e}")


# --- Export Function for Paired t-test Results (Summed BCA) ---
def export_paired_results_to_excel(data, parent_folder, log_func=print):
    """
    Exports structured Paired t-test results to a formatted Excel file.

    Args:
        data (list of dict): List of dictionaries, each representing a significant paired test.
                             Expected keys: 'ROI', 'Condition_A', 'Condition_B', 'N_Pairs',
                                           't_statistic', 'df', 'p_value',
                                           'Mean_A', 'Mean_B', 'Mean_Difference'.
        parent_folder (str): Path for suggesting save location.
        log_func (callable): Logging function.
    """
    log_func("Attempting to export Paired Test results...")
    if not data:
        log_func("No Paired Test results data available to export.")
        messagebox.showwarning("No Results", "No Paired Test results to export.")
        return

    df_export = pd.DataFrame(data)

    # Define preferred column order
    preferred_cols = ['ROI', 'Condition_A', 'Condition_B', 'N_Pairs',
                      'Mean_A', 'Mean_B', 'Mean_Difference',
                      'Cohen_d', 't_statistic', 'df', 'p_value']
    df_export = df_export[[col for col in preferred_cols if col in df_export.columns]]

    # Suggest filename (try to get condition names if available from first result)
    cond_a_name = data[0].get('Condition_A', 'CondA').replace(" ", "_")
    cond_b_name = data[0].get('Condition_B', 'CondB').replace(" ", "_")
    initial_dir = parent_folder if os.path.isdir(parent_folder) else os.path.expanduser("~")
    suggested_filename = f"Stats_PairedTests_SummedBCA_{cond_a_name}_vs_{cond_b_name}.xlsx"

    save_path = filedialog.asksaveasfilename(
        title="Save Paired Test Results (Summed BCA)",
        initialdir=initial_dir, initialfile=suggested_filename, defaultextension=".xlsx",
        filetypes=[("Excel Workbook", "*.xlsx"), ("All Files", "*.*")]
    )
    if not save_path: log_func("Paired Test export cancelled."); return

    try:
        log_func(f"Exporting Paired Test results to: {save_path}")
        with pd.ExcelWriter(save_path, engine='xlsxwriter') as writer:
            _auto_format_and_write_excel(writer, df_export, 'Paired Test Results', log_func)
        log_func("Paired Test results export successful.")
        messagebox.showinfo("Export Successful", f"Paired Test results exported to:\n{save_path}")
    except PermissionError:
        err_msg = f"Permission denied writing to {save_path}. File may be open or folder write-protected."
        log_func(f"!!! Export Failed: {err_msg}")
        messagebox.showerror("Export Failed", err_msg)
    except Exception as e:
        log_func(f"!!! Paired Test Export Failed: {e}\n{traceback.format_exc()}")
        messagebox.showerror("Export Failed", f"Could not save Excel file: {e}")


# --- Export Function for RM-ANOVA Results (Summed BCA) ---
def export_rm_anova_results_to_excel(anova_table, parent_folder, log_func=print):
    """
    Exports RM-ANOVA table (DataFrame) to a formatted Excel file.

    Args:
        anova_table (pd.DataFrame): DataFrame containing the ANOVA results.
        parent_folder (str): Path for suggesting save location.
        log_func (callable): Logging function.
    """
    log_func("Attempting to export RM-ANOVA results...")
    if anova_table is None or not isinstance(anova_table, pd.DataFrame) or anova_table.empty:
        log_func("No RM-ANOVA results data available or data is not a DataFrame.")
        messagebox.showwarning("No Results", "No RM-ANOVA results available to export or data format is incorrect.")
        return

    df_export = anova_table.copy()  # Use the DataFrame as is

    initial_dir = parent_folder if os.path.isdir(parent_folder) else os.path.expanduser("~")
    suggested_filename = f"Stats_RM_ANOVA_SummedBCA.xlsx"

    save_path = filedialog.asksaveasfilename(
        title="Save RM-ANOVA Results (Summed BCA)",
        initialdir=initial_dir, initialfile=suggested_filename, defaultextension=".xlsx",
        filetypes=[("Excel Workbook", "*.xlsx"), ("All Files", "*.*")]
    )
    if not save_path: log_func("RM-ANOVA export cancelled."); return

    try:
        log_func(f"Exporting RM-ANOVA results to: {save_path}")
        with pd.ExcelWriter(save_path, engine='xlsxwriter') as writer:
            # The anova_table from statsmodels often has 'F', 'p-unc', 'ddof1', 'ddof2' etc.
            # Or 'SS', 'DF', 'MS', 'F', 'PR(>F)' from other packages.
            # The _auto_format_and_write_excel helper will handle standard numeric types.
            _auto_format_and_write_excel(writer, df_export, 'RM-ANOVA Table', log_func)
        log_func("RM-ANOVA results export successful.")
        messagebox.showinfo("Export Successful", f"RM-ANOVA results exported to:\n{save_path}")
    except PermissionError:
        err_msg = f"Permission denied writing to {save_path}. File may be open or folder write-protected."
        log_func(f"!!! Export Failed: {err_msg}")
        messagebox.showerror("Export Failed", err_msg)
    except Exception as e:
        log_func(f"!!! RM-ANOVA Export Failed: {e}\n{traceback.format_exc()}")
        messagebox.showerror("Export Failed", f"Could not save Excel file: {e}")


# --- Export Function for Mixed Effects Model Results ---
def export_mixedlm_results_to_excel(mixedlm_table, parent_folder, log_func=print):
    """Exports MixedLM fixed effects table to a formatted Excel file."""
    log_func("Attempting to export Mixed Model results...")
    if mixedlm_table is None or not isinstance(mixedlm_table, pd.DataFrame) or mixedlm_table.empty:
        log_func("No Mixed Model results data available or data is not a DataFrame.")
        messagebox.showwarning("No Results", "No Mixed Model results available to export or data format is incorrect.")
        return

    df_export = mixedlm_table.copy()

    initial_dir = parent_folder if os.path.isdir(parent_folder) else os.path.expanduser("~")
    suggested_filename = "Stats_MixedModel_SummedBCA.xlsx"

    save_path = filedialog.asksaveasfilename(
        title="Save Mixed Model Results (Summed BCA)",
        initialdir=initial_dir, initialfile=suggested_filename, defaultextension=".xlsx",
        filetypes=[("Excel Workbook", "*.xlsx"), ("All Files", "*.*")]
    )
    if not save_path:
        log_func("Mixed Model export cancelled.")
        return

    try:
        log_func(f"Exporting Mixed Model results to: {save_path}")
        with pd.ExcelWriter(save_path, engine='xlsxwriter') as writer:
            _auto_format_and_write_excel(writer, df_export, 'Mixed Model Results', log_func)
        log_func("Mixed Model results export successful.")
        messagebox.showinfo("Export Successful", f"Mixed Model results exported to:\n{save_path}")
    except PermissionError:
        err_msg = f"Permission denied writing to {save_path}. File may be open or folder write-protected."
        log_func(f"!!! Export Failed: {err_msg}")
        messagebox.showerror("Export Failed", err_msg)
    except Exception as e:
        log_func(f"!!! Mixed Model Export Failed: {e}\n{traceback.format_exc()}")
        messagebox.showerror("Export Failed", f"Could not save Excel file: {e}")