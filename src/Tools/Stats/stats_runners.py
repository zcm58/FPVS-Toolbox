# Analysis routine methods extracted from stats.py

import tkinter as tk
from tkinter import messagebox
import pandas as pd
import numpy as np
from scipy import stats
import traceback

from .repeated_m_anova import run_repeated_measures_anova
from .mixed_effects_model import run_mixed_effects_model
from .interpretation_helpers import generate_lme_summary
from .posthoc_tests import (
    run_posthoc_pairwise_tests,
    run_interaction_posthocs as perform_interaction_posthocs,
)
from .stats_helpers import load_rois_from_settings, apply_rois_to_modules
from .stats_analysis import ALL_ROIS_OPTION

# These variables are set from settings at runtime
ROIS = {}
HARMONIC_CHECK_ALPHA = 0.05


def run_rm_anova(self):
    self.refresh_rois()
    self.log_to_main_app("Running RM-ANOVA (Summed BCA)...")
    self.results_textbox.configure(state="normal");
    self.results_textbox.delete("1.0", tk.END)  # Clear textbox
    self.export_rm_anova_btn.configure(state="disabled");
    self.rm_anova_results_data = None

    self.all_subject_data.clear()
    roi_list = None if self.roi_var.get() == ALL_ROIS_OPTION else [self.roi_var.get()]
    if not self.prepare_all_subject_summed_bca_data(roi_filter=roi_list):
        messagebox.showerror("Data Error", "Summed BCA data could not be prepared for RM-ANOVA.");
        self.results_textbox.configure(state="disabled");
        return

    long_format_data = []
    for pid, cond_data in self.all_subject_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    long_format_data.append(
                        {'subject': pid, 'condition': cond_name, 'roi': roi_name, 'value': value})

    if not long_format_data:
        messagebox.showerror("Data Error", "No valid data available for RM-ANOVA after filtering NaNs.");
        self.results_textbox.configure(state="disabled");
        return

    df_long = pd.DataFrame(long_format_data)

    if df_long['condition'].nunique() < 2 or df_long['roi'].nunique() < 1:
        messagebox.showerror("Data Error",
                             "RM-ANOVA requires at least two conditions and at least one ROI with valid data.")
        self.results_textbox.configure(state="disabled");
        return

    # --- Start Building Output Text ---
    output_text = "============================================================\n"
    output_text += "       Repeated Measures ANOVA (RM-ANOVA) Results\n"
    output_text += "       Analysis conducted on: Summed BCA Data\n"
    output_text += "============================================================\n\n"
    output_text += (
        "This test examines the overall effects of your experimental conditions (e.g., different stimuli),\n"
        "the different brain regions (ROIs) you analyzed, and, crucially, whether the\n"
        "effect of the conditions changes depending on the brain region (interaction effect).\n\n")

    try:
        self.log_to_main_app(f"Calling run_repeated_measures_anova with DataFrame of shape: {df_long.shape}")
        anova_df_results = run_repeated_measures_anova(data=df_long, dv_col='value',
                                                       within_cols=['condition', 'roi'],
                                                       subject_col='subject')

        if anova_df_results is not None and not anova_df_results.empty:
            # Calculate partial eta squared for each effect
            pes_vals = []
            for _, row in anova_df_results.iterrows():
                f_val = row.get('F Value', row.get('F', np.nan))
                df1 = row.get('Num DF', row.get('df1', row.get('ddof1', np.nan)))
                df2 = row.get('Den DF', row.get('df2', row.get('ddof2', np.nan)))
                if not pd.isna(f_val) and not pd.isna(df1) and not pd.isna(df2) and (f_val * df1 + df2) != 0:
                    pes_vals.append((f_val * df1) / ((f_val * df1) + df2))
                else:
                    pes_vals.append(np.nan)
            anova_df_results['partial eta squared'] = pes_vals

            # --- Display the Statistical Table ---
            output_text += "--------------------------------------------\n"
            output_text += "                 STATISTICAL TABLE (RM-ANOVA)\n"
            output_text += "--------------------------------------------\n"
            output_text += anova_df_results.to_string(index=False) + "\n\n"
            self.rm_anova_results_data = anova_df_results
            self.export_rm_anova_btn.configure(state="normal")

            # --- Add Plain Language Interpretation ---
            output_text += "--------------------------------------------\n"
            output_text += "           SIMPLIFIED EXPLANATION OF RESULTS\n"
            output_text += "--------------------------------------------\n"
            try:
                alpha = float(self.alpha_var.get())
            except ValueError:
                messagebox.showerror("Input Error", "Invalid alpha value. Please enter a numeric value.")
                self.results_textbox.configure(state="disabled");
                return
            output_text += f"(A result is typically considered 'statistically significant' if its p-value ('Pr > F') is less than {alpha:.2f})\n\n"

            for index, row in anova_df_results.iterrows():
                effect_name_raw = str(row.get('Effect', 'Unknown Effect'))
                effect_display_name = effect_name_raw.replace(':', ' by ').replace('_', ' ').title()

                p_value_raw = row.get('Pr > F', row.get('p-unc', np.nan))
                # f_value = row.get('F Value', row.get('F', np.nan)) # F-value is in the table, not explicitly used in this text yet

                output_text += f"Effect: {effect_display_name}\n"

                if pd.isna(p_value_raw):
                    output_text += "  - Significance: Could not be determined (p-value missing from table).\n\n"
                    continue

                is_significant = p_value_raw < alpha
                significance_status = "SIGNIFICANT" if is_significant else "NOT SIGNIFICANT"

                # Format p-value for display in explanation
                p_value_display_str = "< .0001" if p_value_raw < 0.0001 else f"{p_value_raw:.4f}"

                eta_sq = row.get('Partial_Eta_Squared', np.nan)
                eta_sq_display = f"{eta_sq:.3f}" if not pd.isna(eta_sq) else "N/A"
                output_text += f"  - Statistical Finding: {significance_status} (p-value = {p_value_display_str})\n"
                output_text += f"  - Partial Eta Squared: {eta_sq_display}\n"

                explanation = ""
                # Assuming within_cols are 'condition' and 'roi' for these interpretations
                if 'condition' in effect_name_raw.lower() and 'roi' in effect_name_raw.lower() and (
                        ':' in effect_name_raw or '_' in effect_name_raw):  # Interaction
                    if is_significant:
                        explanation = (
                            "  - Interpretation: This is often a very important finding! It means the way brain\n"
                            "                    activity (Summed BCA) changed across your different experimental conditions\n"
                            "                    **significantly depended on which brain region (ROI)** you were observing.\n"
                            "                    The effect of conditions isn't the same for all ROIs.\n"
                            "                    (For example, Condition A might boost activity in the Frontal lobe more than\n"
                            "                     Condition B, but this pattern might be different or even reversed in the\n"
                            "                     Occipital lobe.)\n"
                            "  - Next Steps: Consider creating interaction plots to visualize this. Post-hoc tests\n"
                            "                are often needed to understand where these specific differences lie.\n"
                        )
                    else:
                        explanation = (
                            "  - Interpretation: The effect of your experimental conditions on brain activity (Summed BCA)\n"
                            "                    was generally consistent across the different brain regions analyzed.\n"
                            "                    There wasn't a significant 'it depends' relationship found here.\n"
                        )
                elif 'condition' == effect_name_raw.lower():  # Main effect of Condition
                    if is_significant:
                        explanation = (
                            "  - Interpretation: Overall, when averaging across all your brain regions (ROIs),\n"
                            "                    your different experimental conditions led to statistically different\n"
                            "                    average levels of brain activity (Summed BCA).\n"
                            "  - Next Steps: If you have more than two conditions, post-hoc tests can help\n"
                            "                identify which specific conditions differ from each other.\n"
                        )
                    else:
                        explanation = (
                            "  - Interpretation: When averaging across all brain regions, your different experimental\n"
                            "                    conditions did not produce statistically different overall levels of\n"
                            "                    brain activity (Summed BCA).\n"
                        )
                elif 'roi' == effect_name_raw.lower():  # Main effect of ROI
                    if is_significant:
                        explanation = (
                            "  - Interpretation: Different brain regions (ROIs) showed reliably different average levels\n"
                            "                    of brain activity (Summed BCA), regardless of the specific experimental condition.\n"
                            "                    Some regions were consistently more (or less) active than others.\n"
                            "  - Next Steps: If you have more than two ROIs, post-hoc tests can show which specific\n"
                            "                ROIs differ from each other in overall activity.\n"
                        )
                    else:
                        explanation = (
                            "  - Interpretation: There wasn't a statistically significant overall difference in brain activity\n"
                            "                    (Summed BCA) between the different brain regions analyzed (when averaged\n"
                            "                    across your experimental conditions).\n"
                        )
                else:
                    explanation = f"  - Interpretation: This effect relates to '{effect_display_name}'.\n"  # Generic for other potential effects

                output_text += explanation + "\n"

            output_text += "--------------------------------------------\n"
            output_text += "IMPORTANT NOTE:\n"
            output_text += ("  This explanation simplifies the main statistical patterns. For detailed scientific\n"
                            "  reporting, precise interpretation, and any follow-up analyses (e.g., post-hoc tests\n"
                            "  for significant effects or interactions), please refer to the statistical table above\n"
                            "  and consider consulting with a statistician or researcher familiar with ANOVA.\n")
            output_text += "--------------------------------------------\n"

        else:
            output_text += "RM-ANOVA did not return any results or the result was empty.\n"
            self.log_to_main_app("RM-ANOVA did not return results or was empty.")

    except ImportError:
        output_text += "Error: The `repeated_m_anova.py` module or its dependency `statsmodels` could not be loaded.\nPlease ensure `statsmodels` is installed (`pip install statsmodels`).\nContact developer if issues persist.\n"
        self.log_to_main_app("ImportError during RM-ANOVA execution, likely statsmodels or the custom module.")
    except Exception as e:
        output_text += f"RM-ANOVA analysis failed unexpectedly: {e}\n"
        output_text += "Common issues include insufficient data after removing missing values, or data not having\nenough variation or levels for each factor (e.g., needing at least 2 conditions).\n"
        output_text += "Please check your input data structure and console logs for more details.\n"
        self.log_to_main_app(f"!!! RM-ANOVA Error: {e}\n{traceback.format_exc()}")

    self.results_textbox.insert("1.0", output_text)
    self.results_textbox.configure(state="disabled")
    self.log_to_main_app("RM-ANOVA (Summed BCA) attempt complete.")


def run_mixed_model(self):
    self.refresh_rois()
    """Run a linear mixed-effects model on the summed BCA data."""
    self.log_to_main_app("Running Mixed Effects Model (Summed BCA)...")
    self.results_textbox.configure(state="normal")
    self.results_textbox.delete("1.0", tk.END)
    self.export_mixed_model_btn.configure(state="disabled")
    self.mixed_model_results_data = None

    self.all_subject_data.clear()
    roi_list = None if self.roi_var.get() == ALL_ROIS_OPTION else [self.roi_var.get()]
    if not self.prepare_all_subject_summed_bca_data(roi_filter=roi_list):
        messagebox.showerror("Data Error", "Summed BCA data could not be prepared for Mixed Model.")
        self.results_textbox.configure(state="disabled")
        return

    long_format_data = []
    for pid, cond_data in self.all_subject_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    long_format_data.append({'subject': pid, 'condition': cond_name, 'roi': roi_name, 'value': value})

    if not long_format_data:
        messagebox.showerror("Data Error", "No valid data available for Mixed Model after filtering NaNs.")
        self.results_textbox.configure(state="disabled")
        return

    df_long = pd.DataFrame(long_format_data)

    output_text = "============================================================\n"
    output_text += "       Linear Mixed-Effects Model Results\n"
    output_text += "       Analysis conducted on: Summed BCA Data\n"
    output_text += "============================================================\n\n"
    output_text += (
        "This model accounts for repeated observations from each subject by including\n"
        "a random intercept. Fixed effects assess how conditions and ROIs influence\n"
        "Summed BCA values, including their interaction.\n\n"
    )

    try:
        self.log_to_main_app(f"Calling run_mixed_effects_model with DataFrame of shape: {df_long.shape}")
        mixed_results = run_mixed_effects_model(
            data=df_long,
            dv_col='value',
            group_col='subject',
            fixed_effects=['condition * roi']
        )

        if mixed_results is not None and not mixed_results.empty:
            output_text += "--------------------------------------------\n"
            output_text += "                 FIXED EFFECTS TABLE\n"
            output_text += "--------------------------------------------\n"
            output_text += mixed_results.to_string(index=False) + "\n"
            try:
                alpha = float(self.alpha_var.get())
            except Exception:
                alpha = 0.05
            output_text += generate_lme_summary(mixed_results, alpha=alpha)
            self.mixed_model_results_data = mixed_results
            self.export_mixed_model_btn.configure(state="normal")
        else:
            output_text += "Mixed effects model did not return any results or the result was empty.\n"
            self.log_to_main_app("Mixed effects model returned no results or empty table.")
    except ImportError:
        output_text += "Error: The `statsmodels` package is required for mixed effects modeling.\n"
        output_text += "Please install it via `pip install statsmodels`.\n"
        self.log_to_main_app("ImportError during mixed model execution.")
    except Exception as e:
        output_text += f"Mixed effects model failed unexpectedly: {e}\n"
        self.log_to_main_app(f"!!! Mixed Model Error: {e}\n{traceback.format_exc()}")

    self.results_textbox.insert("1.0", output_text)
    self.results_textbox.configure(state="disabled")
    self.log_to_main_app("Mixed Effects Model attempt complete.")


def run_posthoc_tests(self):
    self.refresh_rois()
    self.log_to_main_app("Running post-hoc pairwise tests...")
    self.results_textbox.configure(state="normal")
    self.results_textbox.delete("1.0", tk.END)
    self.export_posthoc_btn.configure(state="disabled")
    self.posthoc_results_data = None

    self.all_subject_data.clear()
    roi_list = None if self.roi_var.get() == ALL_ROIS_OPTION else [self.roi_var.get()]
    if not self.prepare_all_subject_summed_bca_data(roi_filter=roi_list):
        messagebox.showerror("Data Error", "Summed BCA data could not be prepared for post-hoc tests.")

        self.results_textbox.configure(state="disabled")
        return

    long_format_data = []
    for pid, cond_data in self.all_subject_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    long_format_data.append({'subject': pid, 'condition': cond_name, 'roi': roi_name, 'value': value})

    if not long_format_data:

        messagebox.showerror("Data Error", "No valid data available for post-hoc tests after filtering NaNs.")

        self.results_textbox.configure(state="disabled")
        return

    df_long = pd.DataFrame(long_format_data)


    factor = self.posthoc_factor_var.get()
    if factor not in ["condition", "roi", "condition by roi"]:
        messagebox.showerror("Input Error", f"Invalid factor selected for post-hoc tests: {factor}")
        self.results_textbox.configure(state="disabled")
        return

    if factor == "condition by roi":
        output_text, results_df = perform_interaction_posthocs(
            data=df_long,
            dv_col='value',
            roi_col='roi',
            condition_col='condition',
            subject_col='subject',
        )
    else:
        output_text, results_df = run_posthoc_pairwise_tests(
            data=df_long,
            dv_col='value',
            factor_col=factor,
            subject_col='subject'
        )

    self.posthoc_results_data = results_df
    self.results_textbox.insert("1.0", output_text)
    if results_df is not None and not results_df.empty:
        self.export_posthoc_btn.configure(state="normal")
    self.results_textbox.configure(state="disabled")
    self.log_to_main_app("Post-hoc pairwise tests complete.")


def run_interaction_posthocs(self):
    self.refresh_rois()
    """
    Runs post-hoc tests to break down a significant interaction from the last RM-ANOVA.
    This version builds a summary of significant findings and places it at the top of the output.
    """
    self.log_to_main_app("Running post-hoc tests for ANOVA interaction...")
    self.run_posthoc_btn.configure(state="disabled")

    self.all_subject_data.clear()
    roi_list = None if self.roi_var.get() == ALL_ROIS_OPTION else [self.roi_var.get()]
    if not self.prepare_all_subject_summed_bca_data(roi_filter=roi_list):
        messagebox.showwarning("No Data", "Summed BCA data not found. Please re-run the main analysis pipeline.")
        self.run_posthoc_btn.configure(state="normal")
        return

    if self.rm_anova_results_data is None:
        messagebox.showwarning("No ANOVA Data", "Please run a successful RM-ANOVA first.")
        self.run_posthoc_btn.configure(state="normal")
        return

    long_format_data = []
    for pid, cond_data in self.all_subject_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    long_format_data.append(
                        {'subject': pid, 'condition': cond_name, 'roi': roi_name, 'value': value})

    if not long_format_data:
        messagebox.showerror("Data Error", "Could not assemble any data for post-hoc tests.")
        return

    df_long = pd.DataFrame(long_format_data)

    # Ensure we use the same balanced dataset as the ANOVA
    num_conditions = df_long['condition'].nunique()
    num_rois = df_long['roi'].nunique()
    expected_cells_per_subject = num_conditions * num_rois
    subject_cell_counts = df_long.groupby('subject').size()
    complete_subjects = subject_cell_counts[subject_cell_counts == expected_cells_per_subject].index.tolist()
    df_long_balanced = df_long[df_long['subject'].isin(complete_subjects)]

    if len(complete_subjects) < df_long['subject'].nunique():
        self.log_to_main_app(
            f"NOTE: Post-hoc tests will be run only on the {len(complete_subjects)} subjects with complete data.")

    # --- Loop through ROIs, run post-hocs, and collect results ---
    if self.roi_var.get() == ALL_ROIS_OPTION:
        all_rois = sorted(df_long_balanced['roi'].unique())
    else:
        all_rois = [self.roi_var.get()] if self.roi_var.get() in df_long_balanced['roi'].unique() else []
    full_details_output = ""  # For the detailed breakdown
    significant_findings_for_summary = []  # For the top-level summary

    for roi_name in all_rois:
        roi_specific_df = df_long_balanced[df_long_balanced['roi'] == roi_name]

        if roi_specific_df.empty or roi_specific_df['subject'].nunique() < 2:
            continue

        log_text, results_df = run_posthoc_pairwise_tests(
            data=roi_specific_df,
            dv_col='value',
            factor_col='condition',
            subject_col='subject'
        )

        # Add the detailed breakdown for this ROI to the main detailed log
        full_details_output += f"\n\n***************************************************\n"
        full_details_output += f" Detailed Post-Hoc Results for ROI: {roi_name}\n"
        full_details_output += f"***************************************************\n"
        full_details_output += log_text

        # Check the returned DataFrame for significant results to add to our summary
        if results_df is not None and not results_df.empty:
            significant_pairs = results_df[results_df['Significant'] == True]
            if not significant_pairs.empty:
                # Add this ROI to the summary list
                significant_findings_for_summary.append({
                    'roi': roi_name,
                    'findings': significant_pairs.to_dict('records')
                })

    # --- Now, build the final output string with the summary at the top ---
    final_output_string = ""
    if significant_findings_for_summary:
        summary_section = "============================================================\n"
        summary_section += "             SUMMARY OF SIGNIFICANT FINDINGS\n"
        summary_section += "============================================================\n"
        summary_section += "(Holm-corrected p-values < 0.05)\n"

        for finding_group in significant_findings_for_summary:
            roi = finding_group['roi']
            summary_section += f"\n* In ROI: {roi}\n"
            for row in finding_group['findings']:
                # Build a clear comparison string
                comp_str = f"'{row['Level_A']}' vs. '{row['Level_B']}'"
                t_val = row['t_statistic']
                df = row['N_Pairs'] - 1
                p_corr = row['p_value_corrected']
                p_corr_str = "< .0001" if p_corr < 0.0001 else f"{p_corr:.4f}"

                summary_section += f"  - Difference between {comp_str} is significant.\n"
                summary_section += f"    (t({df}) = {t_val:.2f}, corrected p = {p_corr_str})\n"

        summary_section += "============================================================\n"
        final_output_string += summary_section
    else:
        final_output_string += "No significant pairwise differences found after multiple comparison correction.\n"

    final_output_string += "\n\n============================================================\n"
    final_output_string += "           Full Post-Hoc Comparison Details\n"
    final_output_string += "============================================================\n"
    final_output_string += full_details_output

    # Append all results to the textbox
    self.results_textbox.configure(state="normal")
    # Prepend to existing text (so user sees summary first) or clear and insert
    # Let's clear and insert so only post-hoc results are shown for this action
    self.results_textbox.delete("1.0", tk.END)
    self.results_textbox.insert("1.0", final_output_string)
    self.results_textbox.configure(state="disabled")

    self.log_to_main_app("Post-hoc analysis complete.")
    self.run_posthoc_btn.configure(state="normal")


def run_harmonic_check(self):
    self.refresh_rois()
    self.log_to_main_app("Running Per-Harmonic Significance Check...")
    self.results_textbox.configure(state="normal");
    self.results_textbox.delete("1.0", tk.END)
    self.export_harmonic_check_btn.configure(state="disabled")
    self.harmonic_check_results_data.clear()

    selected_metric = self.harmonic_metric_var.get()
    try:
        mean_value_threshold = float(self.harmonic_threshold_var.get())
    except ValueError:
        messagebox.showerror("Input Error", "Invalid Mean Threshold. Please enter a numeric value.")
        self.results_textbox.configure(state="disabled");
        return

    if not (self.subject_data and self.subjects and self.conditions):
        messagebox.showerror("Data Error", "No subject data found. Please scan a folder first.")
        self.results_textbox.configure(state="disabled");
        return

    output_text = f"===== Per-Harmonic Significance Check ({selected_metric}) =====\n"
    output_text += f"A harmonic is flagged as 'Significant' if:\n"
    output_text += f"1. Its average {selected_metric} is reliably different from zero across subjects\n"
    output_text += f"   (statistically tested using a 1-sample t-test vs 0, p-value < {HARMONIC_CHECK_ALPHA}).\n"
    output_text += f"2. AND this average {selected_metric} is also greater than your threshold of {mean_value_threshold}.\n"
    output_text += f"(N = number of subjects included in each specific test listed below)\n\n"

    any_significant_found_overall = False
    loaded_dataframes = {}  # Cache for loaded DataFrames: {file_path: df}

    roi_list = list(ROIS.keys()) if self.roi_var.get() == ALL_ROIS_OPTION else [self.roi_var.get()]
    for cond_name in self.conditions:
        output_text += f"\n=== Condition: {cond_name} ===\n"
        found_significant_in_this_condition = False

        for roi_name in roi_list:
            # Determine included frequencies based on a sample file for this condition
            sample_file_path = None
            for pid_s in self.subjects:  # Find first subject with data for this condition
                if self.subject_data.get(pid_s, {}).get(cond_name):
                    sample_file_path = self.subject_data[pid_s][cond_name]
                    break

            if not sample_file_path:
                self.log_to_main_app(
                    f"No sample file for Cond '{cond_name}' to determine frequencies for ROI '{roi_name}'.")
                output_text += f"\n  --- ROI: {roi_name} ---\n"
                output_text += f"      Could not determine checkable frequencies (no sample data file found for this condition).\n\n"
                continue

            try:
                # Load sample DF for columns if not already cached
                if sample_file_path not in loaded_dataframes:
                    self.log_to_main_app(
                        f"Cache miss for sample file columns: {os.path.basename(sample_file_path)}. Loading sheet: '{selected_metric}'")
                    loaded_dataframes[sample_file_path] = pd.read_excel(sample_file_path,
                                                                        sheet_name=selected_metric,
                                                                        index_col="Electrode")
                    loaded_dataframes[sample_file_path].index = loaded_dataframes[sample_file_path].index.str.upper()

                sample_df_cols = loaded_dataframes[sample_file_path].columns
                included_freq_values = self._get_included_freqs(sample_df_cols)
            except Exception as e:
                self.log_to_main_app(
                    f"Error reading columns for ROI '{roi_name}', Cond '{cond_name}' from sample file {os.path.basename(sample_file_path)}: {e}")
                output_text += f"\n  --- ROI: {roi_name} ---\n"
                output_text += f"      Error determining checkable frequencies for this ROI (could not read sample file columns).\n\n"
                continue

            if not included_freq_values:
                output_text += f"\n  --- ROI: {roi_name} ---\n"
                output_text += f"      No applicable harmonics to check for this ROI after frequency exclusions.\n\n"
                continue

            roi_header_printed_for_cond = False
            significant_harmonics_count_for_roi = 0

            for freq_val in included_freq_values:
                harmonic_col_name = f"{freq_val:.1f}_Hz"
                subject_harmonic_roi_values = []

                for pid in self.subjects:
                    file_path = self.subject_data.get(pid, {}).get(cond_name)
                    if not (file_path and os.path.exists(file_path)):
                        # self.log_to_main_app(f"File path missing or invalid for PID {pid}, Cond {cond_name}")
                        continue

                    current_df = loaded_dataframes.get(file_path)
                    if current_df is None:  # Check for None (DataFrame not in cache)
                        try:
                            self.log_to_main_app(
                                f"Cache miss for {os.path.basename(file_path)}. Loading sheet: '{selected_metric}'")
                            current_df = pd.read_excel(file_path, sheet_name=selected_metric, index_col="Electrode")
                            current_df.index = current_df.index.str.upper()
                            loaded_dataframes[file_path] = current_df  # Cache it
                        except FileNotFoundError:
                            self.log_to_main_app(
                                f"Error: File not found {file_path} for PID {pid}, Cond {cond_name}.")
                            continue
                        except KeyError as e_key:  # Handles wrong sheet name or missing 'Electrode'
                            self.log_to_main_app(
                                f"Error: Sheet '{selected_metric}' or index 'Electrode' not found in {os.path.basename(file_path)}. {e_key}")
                            continue
                        except Exception as e:
                            self.log_to_main_app(
                                f"Error loading DataFrame for {os.path.basename(file_path)}, sheet '{selected_metric}': {e}")
                            continue

                    # After loading or retrieving from cache, check if it's empty or harmonic column exists
                    if current_df.empty:
                        # self.log_to_main_app(f"DataFrame for {os.path.basename(file_path)} is empty. Skipping harmonic {harmonic_col_name}.")
                        continue
                    if harmonic_col_name not in current_df.columns:
                        # self.log_to_main_app(f"Harmonic {harmonic_col_name} not in {os.path.basename(file_path)} for PID {pid}.")
                        continue

                    try:
                        roi_channels = ROIS.get(roi_name)
                        df_roi_metric = current_df.reindex(roi_channels)  # Select ROI channels
                        # Mean of the specific harmonic across selected ROI channels for this subject
                        mean_val_subj_roi_harmonic = df_roi_metric[harmonic_col_name].dropna().mean()

                        if not pd.isna(mean_val_subj_roi_harmonic):
                            subject_harmonic_roi_values.append(mean_val_subj_roi_harmonic)
                    except Exception as e_proc:
                        self.log_to_main_app(
                            f"Error processing Subj {pid}, Cond {cond_name}, ROI {roi_name}, Freq {harmonic_col_name}: {e_proc}")
                        continue

                if len(subject_harmonic_roi_values) >= 3:
                    t_stat, p_value_raw = stats.ttest_1samp(subject_harmonic_roi_values, 0, nan_policy='omit')

                    # After ttest_1samp with nan_policy='omit', N might change if NaNs were present
                    valid_values_for_stat = [v for v in subject_harmonic_roi_values if not pd.isna(v)]
                    num_subjects_in_test = len(valid_values_for_stat)

                    if num_subjects_in_test < 3:  # Re-check N after potential NaN omission by t-test
                        # self.log_to_main_app(f"Skipping {harmonic_col_name} for {roi_name}/{cond_name}: N < 3 after NaN removal for t-test.")
                        continue

                    mean_group_value = np.mean(valid_values_for_stat)
                    df_val = num_subjects_in_test - 1

                    p_value_str = "< .0001" if p_value_raw < 0.0001 else f"{p_value_raw:.4f}"

                    if p_value_raw < HARMONIC_CHECK_ALPHA and mean_group_value > mean_value_threshold:
                        if not roi_header_printed_for_cond:
                            output_text += f"\n  --- ROI: {roi_name} ---\n"
                            roi_header_printed_for_cond = True
                        found_significant_in_this_condition = True
                        any_significant_found_overall = True
                        significant_harmonics_count_for_roi += 1

                        output_text += f"    ---------------------------------------------\n"
                        output_text += f"    Harmonic: {harmonic_col_name} -> SIGNIFICANT RESPONSE\n"
                        output_text += f"        Average {selected_metric}: {mean_group_value:.3f} (based on N={num_subjects_in_test} subjects)\n"
                        output_text += f"        Statistical Test: t({df_val}) = {t_stat:.2f}, p-value = {p_value_str}\n"
                        output_text += f"    ---------------------------------------------\n"
                        self.harmonic_check_results_data.append({
                            'Condition': cond_name, 'ROI': roi_name, 'Frequency': harmonic_col_name,
                            'N_Subjects': num_subjects_in_test,
                            f'Mean_{selected_metric.replace(" ", "_")}': mean_group_value,
                            'T_Statistic': t_stat, 'P_Value': p_value_raw, 'df': df_val,
                            'Threshold_Criteria_Mean_Value': mean_value_threshold,
                            'Threshold_Criteria_Alpha': HARMONIC_CHECK_ALPHA
                        })

            if roi_header_printed_for_cond:  # If any finding was printed for this ROI
                if significant_harmonics_count_for_roi > 1:
                    output_text += f"    Summary for {roi_name}: Found {significant_harmonics_count_for_roi} significant harmonics (details above).\n"
                output_text += "\n"
            elif included_freq_values:  # If ROI was processed (had included_freqs) but no sig results printed
                output_text += f"\n  --- ROI: {roi_name} ---\n"
                output_text += f"      No significant harmonics met criteria for this ROI.\n\n"

        if not found_significant_in_this_condition:
            # Check if any ROI header was printed for this condition at all.
            # If an ROI header was printed, it means it was processed but had no sig results (message printed above).
            # If no ROI header at all, it means no ROIs had processable data or findings.
            if not any(f"--- ROI:" in line for line in
                       output_text.split(f"=== Condition: {cond_name} ===")[-1].splitlines()):
                output_text += f"  No processable data or no significant harmonics found for any ROI in this condition.\n\n"
            else:
                output_text += f"  No significant harmonics met criteria in this condition across reported ROIs.\n\n"

        else:
            output_text += "\n"  # Space after condition block with results

    if not any_significant_found_overall:
        output_text += "Overall: No harmonics met the significance criteria across all conditions and ROIs.\n"
    else:
        output_text += "\n--- End of Report ---\nTip: For a comprehensive table of all significant findings, please use the 'Export Harmonic Results' feature.\n"

    self.results_textbox.insert("1.0", output_text)
    if self.harmonic_check_results_data: self.export_harmonic_check_btn.configure(state="normal")
    self.results_textbox.configure(state="disabled")
    loaded_dataframes.clear()  # Clear cache after run completes


def _structure_harmonic_results(self):
    """Return nested dict for exporting harmonic check results."""
    metric_key_name = f"Mean_{self.harmonic_metric_var.get().replace(' ', '_')}"
    findings = {}

    for item in self.harmonic_check_results_data:
        cond, roi = item['Condition'], item['ROI']
        findings.setdefault(cond, {}).setdefault(roi, []).append({
            'Frequency': item['Frequency'],
            metric_key_name: item[metric_key_name],
            'N': item['N_Subjects'],
            'T_Statistic': item['T_Statistic'],
            'P_Value': item['P_Value'],
            'df': item['df'],

            'Threshold_Used': item['Threshold_Criteria_Mean_Value'],

        })
    return findings
