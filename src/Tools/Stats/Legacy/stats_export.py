# stats_export.py
# -*- coding: utf-8 -*-
"""
Contains UI-agnostic functions for exporting statistical analysis results to
formatted Excel files using pandas and xlsxwriter.
"""

import pandas as pd
import numpy as np
import traceback


def _auto_format_and_write_excel(writer, df, sheet_name, log_func, default_col_width=15, padding=2):
    """
    Writes a DataFrame to an Excel sheet with auto-adjusted column widths.
    This is a helper function and does not need to be called directly.
    """
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    workbook = writer.book
    worksheet = writer.sheets[sheet_name]

    header_format = workbook.add_format({'bold': True, 'text_wrap': True, 'valign': 'top',
                                         'align': 'center', 'border': 1, 'fg_color': '#DDEBF7'})
    center_format = workbook.add_format({'align': 'center', 'valign': 'vcenter'})
    left_format = workbook.add_format({'align': 'left', 'valign': 'vcenter'})
    num_format_2dp = workbook.add_format({'num_format': '0.00', 'align': 'center', 'valign': 'vcenter'})
    num_format_3dp = workbook.add_format({'num_format': '0.000', 'align': 'center', 'valign': 'vcenter'})
    num_format_4dp = workbook.add_format({'num_format': '0.0000', 'align': 'center', 'valign': 'vcenter'})
    int_format = workbook.add_format({'num_format': '0', 'align': 'center', 'valign': 'vcenter'})

    for col_num, value in enumerate(df.columns.values):
        worksheet.write(0, col_num, value, header_format)

    for col_idx, col_name in enumerate(df.columns):
        cell_format = center_format
        if df[col_name].dtype in [np.int64, np.int32]:
            cell_format = int_format
        elif df[col_name].dtype in [np.float64, np.float32]:
            if 'p_value' in col_name.lower() or 'pr > f' in col_name.lower():
                cell_format = num_format_4dp
            elif 'statistic' in col_name.lower() or 'value' in col_name.lower():
                cell_format = num_format_2dp
            else:
                cell_format = num_format_3dp
        elif pd.api.types.is_string_dtype(df[col_name]) or pd.api.types.is_object_dtype(df[col_name]):
            cell_format = left_format

        try:
            max_len = max(df[col_name].astype(str).map(len).max(), len(str(col_name)))
            col_width = min(max(int(max_len) + padding, 10), 50)
        except Exception:
            col_width = default_col_width

        worksheet.set_column(col_idx, col_idx, col_width, cell_format)
    log_func(f"Formatted sheet: {sheet_name}")
    return True


def export_rm_anova_results_to_excel(anova_table, save_path, log_func):
    """Exports RM-ANOVA table to a formatted Excel file."""
    if anova_table is None or not isinstance(anova_table, pd.DataFrame) or anova_table.empty:
        raise ValueError("No RM-ANOVA results data available to export.")
    try:
        with pd.ExcelWriter(save_path, engine='xlsxwriter') as writer:
            _auto_format_and_write_excel(writer, anova_table, 'RM-ANOVA Table', log_func)
        return True
    except Exception as e:
        log_func(f"!!! RM-ANOVA Export Failed: {e}\n{traceback.format_exc()}")
        raise e


def export_mixed_model_results_to_excel(results_df, save_path, log_func):
    """Exports linear mixed-effects model results to a formatted Excel file."""
    if results_df is None or not isinstance(results_df, pd.DataFrame) or results_df.empty:
        raise ValueError("No Mixed Model results data available to export.")
    try:
        with pd.ExcelWriter(save_path, engine='xlsxwriter') as writer:
            _auto_format_and_write_excel(writer, results_df, 'Mixed Model', log_func)
        return True
    except Exception as e:
        log_func(f"!!! Mixed Model Export Failed: {e}\n{traceback.format_exc()}")
        raise e


def export_posthoc_results_to_excel(results_df, save_path, log_func, factor=""):
    """Exports post-hoc pairwise test results to an Excel file."""
    if results_df is None or not isinstance(results_df, pd.DataFrame) or results_df.empty:
        raise ValueError("No Post-hoc results data available to export.")
    try:
        with pd.ExcelWriter(save_path, engine='xlsxwriter') as writer:
            _auto_format_and_write_excel(writer, results_df, 'Post-hoc Results', log_func)
        return True
    except Exception as e:
        log_func(f"!!! Post-hoc Export Failed: {e}\n{traceback.format_exc()}")
        raise e


def export_significance_results_to_excel(findings_dict, save_path, log_func, metric=""):
    """Exports structured Per-Harmonic Significance Check findings to a formatted Excel file."""
    if not findings_dict or not any(any(roi_data.values()) for roi_data in findings_dict.values()):
        raise ValueError("No significant findings available to export for Harmonic Check.")

    flat_results = []
    mean_metric_col_key = f'Mean_{metric.replace(" ", "_")}'
    for condition, roi_data in findings_dict.items():
        for roi_name, findings_list in roi_data.items():
            for finding in findings_list:
                row = {
                    'Condition': condition,
                    'ROI': roi_name,
                    'Frequency': finding.get('Frequency', 'N/A'),
                    mean_metric_col_key: finding.get(mean_metric_col_key, np.nan),
                    'N_Subjects': finding.get('N_Subjects', np.nan),
                    'df': finding.get('df', np.nan),
                    'T_Statistic': finding.get('T_Statistic', np.nan),
                    'P_Value': finding.get('P_Value', np.nan),
                    'Mean_Threshold_Used': finding.get('Threshold_Criteria_Mean_Value', np.nan)
                }
                flat_results.append(row)

    if not flat_results:
        raise ValueError("Could not prepare Harmonic Check results for export.")

    df_export = pd.DataFrame(flat_results)
    preferred_cols = ['Condition', 'ROI', 'Frequency', mean_metric_col_key,
                      'N_Subjects', 'df', 'T_Statistic', 'P_Value', 'Mean_Threshold_Used']
    df_export = df_export[[col for col in preferred_cols if col in df_export.columns]]

    try:
        with pd.ExcelWriter(save_path, engine='xlsxwriter') as writer:
            _auto_format_and_write_excel(writer, df_export, 'Significant Harmonics', log_func)
        return True
    except Exception as e:
        log_func(f"!!! Harmonic Check Export Failed: {e}\n{traceback.format_exc()}")
        raise e
