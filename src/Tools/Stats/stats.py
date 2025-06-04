#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stats.py

Provides a Toplevel window for statistical analysis of FPVS results.

Dual-track workflow:
  1. Summed BCA analysis (paired t-tests & RM-ANOVA) excluding base frequency multiples
  2. Per-harmonic significance check on SNR or Z-Score, excluding base frequency multiples

Results are displayed in a textbox and exportable to Excel.
"""

import os
import glob
import re
import traceback
import logging

logger = logging.getLogger(__name__)

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

import pandas as pd
import numpy as np
import scipy.stats as stats

from . import stats_export  # Assuming stats_export.py is in the same package
from .repeated_m_anova import run_repeated_measures_anova  # Assuming repeated_m_anova.py
from .mixed_effects_model import run_mixed_effects_model

# Regions of Interest (10-20 montage)
ROIS = {
    "Frontal Lobe": ["F3", "F4", "Fz"],
    "Occipital Lobe": ["O1", "O2", "Oz"],
    "Parietal Lobe": ["P3", "P4", "Pz"],
    "Central Lobe": ["C3", "C4", "Cz"]
}
ALL_ROIS_OPTION = "(All ROIs)"
HARMONIC_CHECK_ALPHA = 0.05  # Significance level for one-sample t-test


class StatsAnalysisWindow(ctk.CTkToplevel):
    def __init__(self, master, default_folder=""):
        super().__init__(master)
        self.title("FPVS Statistical Analysis Tool")
        self.geometry("950x950")  # Adjusted for clarity of layout
        self.grab_set()
        self.focus_force()

        self.master_app = master

        # Data structures
        self.subject_data = {}
        self.all_subject_data = {}  # For summed BCA: {pid: {condition: {roi: sum_bca}}}
        self.subjects = []
        self.conditions = []

        # Results storage for export (structured data)
        self.paired_tests_results_data = []
        self.rm_anova_results_data = None  # Will store ANOVA table (ideally DataFrame)
        self.mixed_model_results_data = None  # Will store MixedLM fixed effects table
        self.harmonic_check_results_data = []

        # UI state variables
        self.stats_data_folder_var = tk.StringVar(master=self, value=default_folder)
        self.detected_info_var = tk.StringVar(master=self, value="Select folder containing FPVS results.")
        self.base_freq_var = tk.StringVar(master=self, value="6.0")
        self.roi_var = tk.StringVar(master=self, value=ALL_ROIS_OPTION)
        self.condition_A_var = tk.StringVar(master=self)
        self.condition_B_var = tk.StringVar(master=self)
        self.harmonic_metric_var = tk.StringVar(master=self, value="SNR")
        self.harmonic_threshold_var = tk.StringVar(master=self, value="1.96")
        self.alpha_var = tk.StringVar(master=self, value="0.05")

        # UI Widget References (stored for potential future dynamic updates)
        self.roi_menu = None
        self.condA_menu = None
        self.condB_menu = None
        self.harmonic_metric_menu = None

        # Export Buttons (instance variables to manage state)
        self.export_paired_tests_btn = None
        self.export_rm_anova_btn = None
        self.export_mixed_model_btn = None
        self.export_harmonic_check_btn = None

        self.create_widgets()
        if default_folder and os.path.isdir(default_folder):
            self.scan_folder()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def log_to_main_app(self, message):
        try:
            if hasattr(self.master_app, 'log') and callable(self.master_app.log):
                self.master_app.log(f"[Stats] {message}")
            else:
                logger.info("[Stats] %s", message)
        except Exception as e:
            logger.error("[Stats Log Error] %s | Original message: %s", e, message)

    def on_close(self):
        self.log_to_main_app("Closing Stats Analysis window.")
        self.grab_release()
        self.destroy()

    def _validate_numeric(self, P):
        if P in ("", "-"): return True
        try:
            float(P)
            return True
        except ValueError:
            return False

    def create_widgets(self):
        validate_num_cmd = (self.register(self._validate_numeric), '%P')

        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        # --- Row 0: Folder Selection ---
        folder_frame = ctk.CTkFrame(main_frame)
        folder_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 10))
        folder_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(folder_frame, text="Data Folder:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ctk.CTkEntry(folder_frame, textvariable=self.stats_data_folder_var, state="readonly").grid(row=0, column=1,
                                                                                                   padx=5, pady=5,
                                                                                                   sticky="ew")
        ctk.CTkButton(folder_frame, text="Browse...", command=self.browse_folder).grid(row=0, column=2, padx=5, pady=5)
        ctk.CTkLabel(folder_frame, textvariable=self.detected_info_var, justify="left", anchor="w").grid(row=1,
                                                                                                         column=0,
                                                                                                         columnspan=3,
                                                                                                         padx=5, pady=5,
                                                                                                         sticky="w")

        # --- Row 1: Common Setup ---
        common_setup_frame = ctk.CTkFrame(main_frame)
        common_setup_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        common_setup_frame.grid_columnconfigure(1, weight=1)
        common_setup_frame.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(common_setup_frame, text="Base Freq (Hz):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ctk.CTkEntry(common_setup_frame, textvariable=self.base_freq_var, validate='key',
                     validatecommand=validate_num_cmd, width=100).grid(row=0, column=1, padx=5, pady=5, sticky="w")
        ctk.CTkLabel(common_setup_frame, text="ROI (Paired/ANOVA):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        roi_options = [ALL_ROIS_OPTION] + list(ROIS.keys())
        self.roi_menu = ctk.CTkOptionMenu(common_setup_frame, variable=self.roi_var,
                                          values=roi_options)  # Stored instance
        self.roi_menu.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        ctk.CTkLabel(common_setup_frame, text="Condition A (Paired):").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.condA_menu = ctk.CTkOptionMenu(common_setup_frame, variable=self.condition_A_var, values=["(Scan Folder)"],
                                            command=lambda *_: self.update_condition_B_options())  # Already stored
        self.condA_menu.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        ctk.CTkLabel(common_setup_frame, text="Condition B (Paired):").grid(row=2, column=2, padx=(15, 5), pady=5,
                                                                            sticky="w")
        self.condB_menu = ctk.CTkOptionMenu(common_setup_frame, variable=self.condition_B_var,
                                            values=["(Scan Folder)"])  # Already stored
        self.condB_menu.grid(row=2, column=3, padx=5, pady=5, sticky="ew")

        ctk.CTkLabel(common_setup_frame, text="Alpha (Sig. Level):").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        ctk.CTkEntry(common_setup_frame, textvariable=self.alpha_var, validate='key',
                     validatecommand=validate_num_cmd, width=100).grid(row=3, column=1, padx=5, pady=5, sticky="w")

        # --- Row 2: Section A - Summed BCA Analysis ---
        summed_bca_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        summed_bca_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=(10, 5))
        ctk.CTkLabel(summed_bca_frame, text="Summed BCA Analysis:", font=ctk.CTkFont(weight="bold")).pack(anchor="w",
                                                                                                          pady=(0, 5))
        buttons_summed_frame = ctk.CTkFrame(summed_bca_frame)
        buttons_summed_frame.pack(fill="x", padx=0, pady=0)  # Use pack for horizontal button layout
        ctk.CTkButton(buttons_summed_frame, text="Run Paired Tests (Summed BCA)", command=self.run_paired_tests).pack(
            side="left", padx=(0, 5), pady=5)
        ctk.CTkButton(buttons_summed_frame, text="Run RM-ANOVA (Summed BCA)", command=self.run_rm_anova).pack(
            side="left", padx=5, pady=5)
        ctk.CTkButton(buttons_summed_frame, text="Run Mixed Model (Summed BCA)", command=self.run_mixed_model).pack(
            side="left", padx=5, pady=5)
        self.export_paired_tests_btn = ctk.CTkButton(buttons_summed_frame, text="Export Paired Results",
                                                     state="disabled", command=self.export_paired_results)
        self.export_paired_tests_btn.pack(side="left", padx=5, pady=5)
        self.export_rm_anova_btn = ctk.CTkButton(buttons_summed_frame, text="Export RM-ANOVA", state="disabled",
                                                 command=self.export_rm_anova_results)
        self.export_rm_anova_btn.pack(side="left", padx=5, pady=5)
        self.export_mixed_model_btn = ctk.CTkButton(buttons_summed_frame, text="Export Mixed Model", state="disabled",
                                                   command=self.export_mixed_model_results)
        self.export_mixed_model_btn.pack(side="left", padx=5, pady=5)

        # --- Row 3: Section B - Harmonic Significance Check ---
        harmonic_check_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        harmonic_check_frame.grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        ctk.CTkLabel(harmonic_check_frame, text="Per-Harmonic Significance Check:",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(0, 5))
        controls_harmonic_frame = ctk.CTkFrame(harmonic_check_frame)
        controls_harmonic_frame.pack(fill="x", padx=0, pady=0)
        ctk.CTkLabel(controls_harmonic_frame, text="Metric:").grid(row=0, column=0, padx=(0, 5), pady=5, sticky="w")
        self.harmonic_metric_menu = ctk.CTkOptionMenu(controls_harmonic_frame, variable=self.harmonic_metric_var,
                                                      values=["SNR", "Z Score"])  # Stored instance
        self.harmonic_metric_menu.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ctk.CTkLabel(controls_harmonic_frame, text="Mean Threshold:").grid(row=0, column=2, padx=(15, 5), pady=5,
                                                                           sticky="w")
        ctk.CTkEntry(controls_harmonic_frame, textvariable=self.harmonic_threshold_var, validate='key',
                     validatecommand=validate_num_cmd, width=100).grid(row=0, column=3, padx=5, pady=5, sticky="w")
        ctk.CTkButton(controls_harmonic_frame, text="Run Harmonic Check", command=self.run_harmonic_check).grid(row=0,
                                                                                                                column=4,
                                                                                                                padx=15,
                                                                                                                pady=5)
        self.export_harmonic_check_btn = ctk.CTkButton(controls_harmonic_frame, text="Export Harmonic Results",
                                                       state="disabled", command=self.export_harmonic_check_results)
        self.export_harmonic_check_btn.grid(row=0, column=5, padx=5, pady=5)
        controls_harmonic_frame.grid_columnconfigure(1, weight=1)  # Allow metric menu to expand

        # --- Row 4: Results Textbox ---
        self.results_textbox = ctk.CTkTextbox(main_frame, wrap="word", state="disabled",
                                              font=ctk.CTkFont(family="Courier New", size=12))
        self.results_textbox.grid(row=4, column=0, sticky="nsew", padx=5, pady=(10, 5))
        main_frame.grid_rowconfigure(4, weight=1)

    def browse_folder(self):
        current_folder = self.stats_data_folder_var.get()
        initial_dir = current_folder if os.path.isdir(current_folder) else os.path.expanduser("~")
        folder = filedialog.askdirectory(title="Select Parent Folder Containing Condition Subfolders",
                                         initialdir=initial_dir)
        if folder:
            self.stats_data_folder_var.set(folder)
            self.scan_folder()
        else:
            self.log_to_main_app("Folder selection cancelled.")

    def scan_folder(self):
        """ Scans folder for PIDs and Conditions """
        parent_folder = self.stats_data_folder_var.get()
        if not parent_folder or not os.path.isdir(parent_folder):
            self.detected_info_var.set("Invalid parent folder selected.")
            self.update_condition_menus([])
            return

        self.log_to_main_app(f"Scanning parent folder: {parent_folder}")
        subjects_set = set()
        conditions_set = set()
        self.subject_data.clear()  # Clear previous data

        # Revised PID pattern:
        # Looks for an optional prefix of letters, then P (case-insensitive) followed by digits.
        # Captures the P and digits part.
        pid_pattern = re.compile(r"(?:[a-zA-Z]*)?(P\d+).*\.xlsx$", re.IGNORECASE)

        try:
            for item_name in os.listdir(parent_folder):  # These are expected to be condition subfolders
                item_path = os.path.join(parent_folder, item_name)
                if os.path.isdir(item_path):
                    condition_name_raw = item_name
                    # Clean condition name (remove leading numbers/hyphens/spaces if any)
                    condition_name = re.sub(r'^\d+\s*[-_]*\s*', '', condition_name_raw).strip()
                    if not condition_name:
                        self.log_to_main_app(
                            f"  Skipping subfolder '{condition_name_raw}' due to empty name after cleaning.")
                        continue

                    self.log_to_main_app(
                        f"  Processing Condition Subfolder: '{condition_name_raw}' as Condition: '{condition_name}'")

                    files_in_subfolder = glob.glob(os.path.join(item_path, "*.xlsx"))
                    found_files_for_condition = False
                    for f_path in files_in_subfolder:
                        excel_filename = os.path.basename(f_path)
                        pid_match = pid_pattern.search(
                            excel_filename)  # Use search to find pattern anywhere before .xlsx

                        if pid_match:
                            pid = pid_match.group(1).upper()  # group(1) is (P\d+)
                            subjects_set.add(pid)
                            conditions_set.add(condition_name)
                            found_files_for_condition = True

                            if pid not in self.subject_data:
                                self.subject_data[pid] = {}

                            if condition_name in self.subject_data[pid]:
                                self.log_to_main_app(
                                    f"    Warning: Duplicate Excel file found for Subject {pid}, Condition '{condition_name}'. Overwriting path from '{os.path.basename(self.subject_data[pid][condition_name])}' to '{excel_filename}'")
                            self.subject_data[pid][condition_name] = f_path
                            self.log_to_main_app(
                                f"      Found PID: {pid} in file: {excel_filename} for Condition: {condition_name}")
                        # else: # Optional: log files that don't match the PID pattern
                        # self.log_to_main_app(f"      File '{excel_filename}' does not match PID pattern. Skipping.")

                    if not found_files_for_condition:
                        self.log_to_main_app(
                            f"    Warning: No Excel files matching PID pattern (e.g., SCP1_data.xlsx, P01_data.xlsx) found in subfolder '{condition_name_raw}'.")

        except PermissionError as e:
            self.log_to_main_app(f"!!! Permission Error scanning folder: {parent_folder}. {e}")
            messagebox.showerror("Scanning Error",
                                 f"Permission denied accessing folder or its contents:\n{parent_folder}\n{e}")
            self.update_condition_menus([])
            return
        except Exception as e:
            self.log_to_main_app(f"!!! Error scanning folder structure: {e}\n{traceback.format_exc()}")
            messagebox.showerror("Scanning Error", f"An unexpected error occurred during scanning:\n{e}")
            self.update_condition_menus([])
            return

        self.subjects = sorted(list(subjects_set))
        self.conditions = sorted(list(conditions_set))

        if not self.conditions or not self.subjects:
            info_text = "Scan complete: No valid condition subfolders or subject Excel files (e.g., P01_data.xlsx, SCP1_data.xlsx) found with recognized PIDs."
            # messagebox.showwarning("Scan Results", info_text) # Can be noisy if expected
        else:
            info_text = f"Scan complete: Found {len(self.subjects)} subjects and {len(self.conditions)} conditions."

        self.log_to_main_app(info_text)
        if self.subjects: self.log_to_main_app(f"Detected Subjects (PIDs): {', '.join(self.subjects)}")
        if self.conditions: self.log_to_main_app(f"Detected Conditions: {', '.join(self.conditions)}")

        self.detected_info_var.set(info_text)
        self.update_condition_menus(self.conditions)

        # Reset pre-calculated data as new files are scanned
        self.all_subject_data.clear()
        self.paired_tests_results_data.clear()
        self.rm_anova_results_data = None
        self.harmonic_check_results_data.clear()

    def update_condition_menus(self, conditions_list):
        current_a = self.condition_A_var.get()
        display_list = conditions_list if conditions_list else ["(Scan Folder)"]
        if current_a not in display_list and display_list:
            self.condition_A_var.set(display_list[0])
        elif not display_list:
            self.condition_A_var.set("(Scan Folder)")
        if self.condA_menu: self.condA_menu.configure(values=display_list)  # Check if widget exists
        self.update_condition_B_options()

    def update_condition_B_options(self, *args):
        cond_a = self.condition_A_var.get()
        valid_b = [c for c in self.conditions if c and c != cond_a]
        if not self.conditions:
            valid_b_display = ["(Scan Folder)"]
        elif not valid_b:
            valid_b_display = [
                "(No other conditions)" if cond_a and cond_a != "(Scan Folder)" else "(Select Condition A)"]
        else:
            valid_b_display = valid_b

        current_b = self.condition_B_var.get()
        if self.condB_menu: self.condB_menu.configure(values=valid_b_display)  # Check if widget exists
        if current_b not in valid_b_display or current_b == cond_a:
            self.condition_B_var.set(valid_b_display[0] if valid_b_display else "")

    def _get_included_freqs(self, all_col_names):
        try:
            base_freq_val = float(self.base_freq_var.get())
            if base_freq_val <= 0: raise ValueError("Base frequency must be positive.")
        except ValueError as e:
            self.log_to_main_app(f"Error: Invalid Base Frequency '{self.base_freq_var.get()}': {e}")
            # messagebox.showerror("Input Error", f"Invalid Base Frequency: {self.base_freq_var.get()}") # Can be noisy
            return []
        numeric_freqs = []
        for col_name in all_col_names:
            if isinstance(col_name, str) and col_name.endswith('_Hz'):
                try:
                    numeric_freqs.append(float(col_name[:-3]))
                except ValueError:
                    self.log_to_main_app(f"Could not parse freq from col: {col_name}")
        if not numeric_freqs: return []
        sorted_numeric_freqs = sorted(list(set(numeric_freqs)))
        excluded_freqs = {f_val for f_val in sorted_numeric_freqs if
                          abs(f_val / base_freq_val - round(f_val / base_freq_val)) < 1e-6}
        included_freqs = [f_val for f_val in sorted_numeric_freqs if f_val not in excluded_freqs]
        return included_freqs

    def aggregate_bca_sum(self, file_path, roi_name):
        try:
            df = pd.read_excel(file_path, sheet_name="BCA (uV)", index_col="Electrode")
            roi_channels = ROIS.get(roi_name)
            if not roi_channels: self.log_to_main_app(f"ROI {roi_name} not defined."); return np.nan
            df_roi = df.reindex(roi_channels).dropna(how='all')
            if df_roi.empty: self.log_to_main_app(f"No data for ROI {roi_name} in {file_path}."); return np.nan
            included_freq_values = self._get_included_freqs(df.columns)
            if not included_freq_values: self.log_to_main_app(f"No freqs to sum for BCA in {file_path}."); return np.nan
            cols_to_sum = [f"{f:.1f}_Hz" for f in included_freq_values if f"{f:.1f}_Hz" in df_roi.columns]
            if not cols_to_sum: self.log_to_main_app(
                f"No matching BCA freq columns for ROI {roi_name} in {file_path}."); return np.nan
            return df_roi[cols_to_sum].sum(axis=1).mean()
        except Exception as e:
            self.log_to_main_app(f"Error aggregating BCA for {os.path.basename(file_path)}, ROI {roi_name}: {e}")
            return np.nan

    def prepare_all_subject_summed_bca_data(self):
        self.log_to_main_app("Preparing summed BCA data...")
        self.all_subject_data.clear()
        if not self.subjects or not self.subject_data:
            messagebox.showwarning("Data Error", "No subject data. Scan folder first.")
            return False
        for pid in self.subjects:
            self.all_subject_data[pid] = {}
            for cond_name in self.conditions:
                file_path = self.subject_data.get(pid, {}).get(cond_name)
                self.all_subject_data[pid].setdefault(cond_name, {})
                for roi_name in ROIS.keys():
                    sum_val = self.aggregate_bca_sum(file_path, roi_name) if file_path and os.path.exists(
                        file_path) else np.nan
                    self.all_subject_data[pid][cond_name][roi_name] = sum_val
        self.log_to_main_app("Summed BCA data prep complete.")
        return True

        # In stats.py

        # ... (other parts of the class) ...

    def run_paired_tests(self):
            self.log_to_main_app("Running Paired Tests (Summed BCA)...")
            self.results_textbox.configure(state="normal");
            self.results_textbox.delete("1.0", tk.END)
            self.export_paired_tests_btn.configure(state="disabled")
            self.paired_tests_results_data.clear()

            cond_a = self.condition_A_var.get()
            cond_b = self.condition_B_var.get()

            if not (cond_a and cond_a != "(Scan Folder)" and \
                    cond_b and cond_b not in ["(Scan Folder)", "(No other conditions)", "(Select Condition A)"] and \
                    cond_a != cond_b):
                messagebox.showerror("Input Error",
                                     "Please select two different and valid conditions for paired tests.")
                self.results_textbox.configure(state="disabled");
                return

            if not self.all_subject_data and not self.prepare_all_subject_summed_bca_data():
                messagebox.showerror("Data Error",
                                     "Summed BCA data could not be prepared. Please check logs or re-scan folder.")
                self.results_textbox.configure(state="disabled");
                return

            rois_to_analyze = []
            selected_roi_option = self.roi_var.get()
            if selected_roi_option == ALL_ROIS_OPTION:
                rois_to_analyze = list(ROIS.keys())
            elif selected_roi_option in ROIS:
                rois_to_analyze = [selected_roi_option]
            else:
                messagebox.showerror("Input Error", f"Invalid ROI selected: {selected_roi_option}")
                self.results_textbox.configure(state="disabled");
                return

            # --- Start Building Output Text ---
            output_text = f"============================================================\n"
            output_text += f"              Paired t-tests (Summed BCA)\n"
            output_text += f"============================================================\n\n"
            output_text += f"Comparing Condition A: '{cond_a}'\n"
            output_text += f"With Condition B:      '{cond_b}'\n"
            output_text += f"ROIs Analyzed:         {selected_roi_option}\n"
            try:
                alpha = float(self.alpha_var.get())
            except ValueError:
                messagebox.showerror("Input Error", "Invalid alpha value. Please enter a numeric value.")
                self.results_textbox.configure(state="disabled");
                return

            output_text += f"(Significance level for p-values: p < {alpha})\n\n"

            significant_tests_found_overall = False

            for roi_name in rois_to_analyze:
                output_text += f"--- ROI: {roi_name} ---\n"

                values_a, values_b = [], []
                for pid in self.subjects:
                    val_a = self.all_subject_data.get(pid, {}).get(cond_a, {}).get(roi_name, np.nan)
                    val_b = self.all_subject_data.get(pid, {}).get(cond_b, {}).get(roi_name, np.nan)
                    if not (pd.isna(val_a) or pd.isna(val_b)):
                        values_a.append(val_a)
                        values_b.append(val_b)

                n_pairs = len(values_a)

                if n_pairs < 3:  # Need at least 3 pairs for a meaningful t-test
                    output_text += f"  Insufficient paired data (N={n_pairs}). Minimum 3 pairs required for a t-test.\n\n"
                    continue

                try:
                    t_stat, p_value_raw = stats.ttest_rel(values_a, values_b)
                    df_val = n_pairs - 1

                    mean_a = np.mean(values_a)
                    mean_b = np.mean(values_b)
                    mean_diff = mean_a - mean_b
                    diff_std = np.std(np.array(values_a) - np.array(values_b), ddof=1)
                    cohen_d = mean_diff / diff_std if diff_std != 0 else np.nan

                    is_significant = p_value_raw < alpha
                    p_value_str = "< .0001" if p_value_raw < 0.0001 else f"{p_value_raw:.4f}"

                    if is_significant:
                        significant_tests_found_overall = True
                        output_text += f"  FINDING: SIGNIFICANT DIFFERENCE found between conditions.\n"
                    else:
                        output_text += f"  FINDING: NO SIGNIFICANT DIFFERENCE found between conditions.\n"

                    output_text += f"    - Average Summed BCA for '{cond_a}': {mean_a:.3f} (approx. uV)\n"
                    output_text += f"    - Average Summed BCA for '{cond_b}': {mean_b:.3f} (approx. uV)\n"
                    output_text += f"    - Mean Difference ('{cond_a}' - '{cond_b}'): {mean_diff:.3f} (approx. uV)\n"
                    output_text += f"    - Effect Size (Cohen's d): {cohen_d:.3f}\n"

                    if is_significant:
                        if mean_diff > 1e-9:  # Check if meaningfully positive (accounting for float precision)
                            output_text += f"      Interpretation: On average, '{cond_a}' showed a significantly HIGHER Summed BCA than '{cond_b}'.\n"
                        elif mean_diff < -1e-9:  # Check if meaningfully negative
                            output_text += f"      Interpretation: On average, '{cond_b}' showed a significantly HIGHER Summed BCA than '{cond_a}'.\n"
                        else:  # Difference is very close to zero despite significance (unlikely with typical data if p is low)
                            output_text += f"      Interpretation: A significant difference was found, but the average values are very close.\n"
                    else:
                        output_text += f"      Interpretation: The observed difference in averages was not statistically significant.\n"

                    output_text += f"    - Statistics: t({df_val}) = {t_stat:.2f}, p-value = {p_value_str}\n"
                    output_text += f"    - Number of pairs included: N = {n_pairs}\n\n"

                    if is_significant:  # Store data for export only if significant
                        self.paired_tests_results_data.append({
                            'ROI': roi_name,
                            'Condition_A': cond_a,
                            'Condition_B': cond_b,
                            'N_Pairs': n_pairs,
                            'Mean_A': mean_a,
                            'Mean_B': mean_b,
                            'Mean_Difference': mean_diff,
                            't_statistic': t_stat,
                            'df': df_val,
                            'p_value': p_value_raw,
                            'Cohen_d': cohen_d  # Store effect size for export
                        })

                except Exception as e:
                    output_text += f"  Error performing t-test for this ROI: {e}\n\n"
                    self.log_to_main_app(
                        f"Paired t-test error for ROI {roi_name} ({cond_a} vs {cond_b}): {e}\n{traceback.format_exc()}")

            if not self.paired_tests_results_data:  # If no significant results were stored
                output_text += "------------------------------------------------------------\n"
                if not any(f"ROI: {r}" in output_text for r in rois_to_analyze if
                           "Insufficient paired data" not in output_text and "Error performing t-test" not in output_text):  # Check if any ROI was actually tested without error/insufficient data
                    output_text += "No ROIs had sufficient data for all paired tests.\n"
                else:
                    output_text += f"No statistically significant differences (p < {alpha}) were found for any of the analyzed ROIs that had sufficient data.\n"
            else:
                output_text += "------------------------------------------------------------\n"
                output_text += "Tip: For a detailed table of significant findings, please use the 'Export Paired Results' feature.\n"

            output_text += "============================================================\n"

            self.results_textbox.insert("1.0", output_text)
            if self.paired_tests_results_data:  # Enable export if there are structured significant results
                self.export_paired_tests_btn.configure(state="normal")

            self.results_textbox.configure(state="disabled")
            self.log_to_main_app("Paired tests (Summed BCA) complete.")

    def run_rm_anova(self):
        self.log_to_main_app("Running RM-ANOVA (Summed BCA)...")
        self.results_textbox.configure(state="normal");
        self.results_textbox.delete("1.0", tk.END)  # Clear textbox
        self.export_rm_anova_btn.configure(state="disabled");
        self.rm_anova_results_data = None

        if not self.all_subject_data and not self.prepare_all_subject_summed_bca_data():
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
                output_text += "------------------------------------------------------------\n"
                output_text += "                 STATISTICAL TABLE (RM-ANOVA)\n"
                output_text += "------------------------------------------------------------\n"
                output_text += anova_df_results.to_string(index=False) + "\n\n"
                self.rm_anova_results_data = anova_df_results
                self.export_rm_anova_btn.configure(state="normal")

                # --- Add Plain Language Interpretation ---
                output_text += "------------------------------------------------------------\n"
                output_text += "           SIMPLIFIED EXPLANATION OF RESULTS\n"
                output_text += "------------------------------------------------------------\n"
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

                output_text += "------------------------------------------------------------\n"
                output_text += "IMPORTANT NOTE:\n"
                output_text += ("  This explanation simplifies the main statistical patterns. For detailed scientific\n"
                                "  reporting, precise interpretation, and any follow-up analyses (e.g., post-hoc tests\n"
                                "  for significant effects or interactions), please refer to the statistical table above\n"
                                "  and consider consulting with a statistician or researcher familiar with ANOVA.\n")
                output_text += "------------------------------------------------------------\n"

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
        self.log_to_main_app("Running Mixed Effects Model (Summed BCA)...")
        self.results_textbox.configure(state="normal")
        self.results_textbox.delete("1.0", tk.END)
        self.export_mixed_model_btn.configure(state="disabled")
        self.mixed_model_results_data = None

        if not self.all_subject_data and not self.prepare_all_subject_summed_bca_data():
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

        if df_long['condition'].nunique() < 2 or df_long['roi'].nunique() < 1:
            messagebox.showerror("Data Error", "Mixed model requires at least two conditions and at least one ROI with valid data.")
            self.results_textbox.configure(state="disabled")
            return

        output_text = "===========================================================\n"
        output_text += "           Mixed Effects Model Results\n"
        output_text += "           Analysis conducted on: Summed BCA Data\n"
        output_text += "===========================================================\n\n"

        try:
            self.log_to_main_app(f"Calling run_mixed_effects_model with DataFrame of shape: {df_long.shape}")
            mixed_df = run_mixed_effects_model(data=df_long, dv_col='value', group_col='subject',
                                               fixed_effects=['condition', 'roi'])
            if mixed_df is not None and not mixed_df.empty:
                output_text += "-----------------------------\n"
                output_text += "            FIXED EFFECTS\n"
                output_text += "-----------------------------\n"
                output_text += mixed_df.to_string(index=False) + "\n"
                self.mixed_model_results_data = mixed_df
                self.export_mixed_model_btn.configure(state="normal")
            else:
                output_text += "Mixed model did not return any results or the result was empty.\n"
                self.log_to_main_app("Mixed model did not return results or was empty.")
        except ImportError:
            output_text += "Error: statsmodels is required for Mixed Effects modeling. Please install it via `pip install statsmodels`.\n"
            self.log_to_main_app("ImportError during Mixed Model execution.")
        except Exception as e:
            output_text += f"Mixed model analysis failed: {e}\n"
            self.log_to_main_app(f"!!! Mixed Model Error: {e}\n{traceback.format_exc()}")

        self.results_textbox.insert("1.0", output_text)
        self.results_textbox.configure(state="disabled")
        self.log_to_main_app("Mixed Effects Model attempt complete.")

    def run_harmonic_check(self):
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

        for cond_name in self.conditions:
            output_text += f"\n=== Condition: {cond_name} ===\n"
            found_significant_in_this_condition = False

            for roi_name in ROIS.keys():
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

                            output_text += f"    ----------------------------------------------------\n"
                            output_text += f"    Harmonic: {harmonic_col_name} -> SIGNIFICANT RESPONSE\n"
                            output_text += f"        Average {selected_metric}: {mean_group_value:.3f} (based on N={num_subjects_in_test} subjects)\n"
                            output_text += f"        Statistical Test: t({df_val}) = {t_stat:.2f}, p-value = {p_value_str}\n"
                            output_text += f"    ----------------------------------------------------\n"
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

    def export_paired_results(self):
        self.log_to_main_app("Exporting Paired Test results...")
        if not self.paired_tests_results_data: messagebox.showwarning("No Results",
                                                                      "No paired results data to export."); return
        try:
            # Using keyword arguments for clarity and robustness
            stats_export.export_paired_results_to_excel(
                data=self.paired_tests_results_data,
                parent_folder=self.stats_data_folder_var.get(),
                log_func=self.log_to_main_app
            )
        except AttributeError:
            messagebox.showerror("Export Error", "'export_paired_results_to_excel' is missing in stats_export.py.")
        except Exception as e:
            messagebox.showerror("Export Error", f"Paired export failed: {e}\n{traceback.format_exc()}")

    def export_rm_anova_results(self):
        self.log_to_main_app("Exporting RM-ANOVA results...")
        if self.rm_anova_results_data is None or (
                isinstance(self.rm_anova_results_data, pd.DataFrame) and self.rm_anova_results_data.empty):
            messagebox.showwarning("No Results", "No RM-ANOVA results data to export.");
            return
        try:
            # Using keyword arguments
            stats_export.export_rm_anova_results_to_excel(
                anova_table=self.rm_anova_results_data,
                parent_folder=self.stats_data_folder_var.get(),
                log_func=self.log_to_main_app
            )
        except AttributeError:
            messagebox.showerror("Export Error", "'export_rm_anova_results_to_excel' is missing in stats_export.py.")
        except Exception as e:
            messagebox.showerror("Export Error", f"RM-ANOVA export failed: {e}\n{traceback.format_exc()}")

    def export_mixed_model_results(self):
        self.log_to_main_app("Exporting Mixed Model results...")
        if self.mixed_model_results_data is None or (
                isinstance(self.mixed_model_results_data, pd.DataFrame) and self.mixed_model_results_data.empty):
            messagebox.showwarning("No Results", "No Mixed Model results data to export.")
            return
        try:
            stats_export.export_mixedlm_results_to_excel(
                mixedlm_table=self.mixed_model_results_data,
                parent_folder=self.stats_data_folder_var.get(),
                log_func=self.log_to_main_app
            )
        except AttributeError:
            messagebox.showerror("Export Error", "'export_mixedlm_results_to_excel' is missing in stats_export.py.")
        except Exception as e:
            messagebox.showerror("Export Error", f"Mixed Model export failed: {e}\n{traceback.format_exc()}")

    def export_harmonic_check_results(self):
        self.log_to_main_app("Exporting Per-Harmonic Check results...")
        if not self.harmonic_check_results_data: messagebox.showwarning("No Results",
                                                                        "No harmonic check results data to export."); return
        findings_dict = {}
        metric_key_name = f'Mean_{self.harmonic_metric_var.get().replace(" ", "_")}'  # Dynamic key for mean metric value
        for item in self.harmonic_check_results_data:
            cond, roi = item['Condition'], item['ROI']
            findings_dict.setdefault(cond, {}).setdefault(roi, []).append({
                'Frequency': item['Frequency'],
                metric_key_name: item[metric_key_name],  # Use the dynamic key from item
                'N': item['N_Subjects'],
                'T_Statistic': item['T_Statistic'],
                'P_Value': item['P_Value'],
                'df': item['df'],
                # Store the mean value threshold used for this harmonic
                'Threshold': item['Threshold_Criteria_Mean_Value']
            })
        if not findings_dict: messagebox.showwarning("No Results",
                                                     "Failed to structure harmonic results for export."); return
        try:
            # Using keyword arguments
            stats_export.export_significance_results_to_excel(
                findings_dict=findings_dict,
                metric=self.harmonic_metric_var.get(),
                threshold=float(self.harmonic_threshold_var.get()),  # This is the input mean value threshold
                parent_folder=self.stats_data_folder_var.get(),
                log_func=self.log_to_main_app
            )
        except Exception as e:
            messagebox.showerror("Export Error", f"Harmonic check export failed: {e}\n{traceback.format_exc()}")

    def call_export_significance_results(self):  # Legacy
        self.log_to_main_app("call_export_significance_results is legacy and unused.")
        pass


if __name__ == "__main__":
    try:
        root = ctk.CTk()
        root.title("Main App Test Host")
        root.geometry("300x100")


        class TestMaster:
            log = staticmethod(lambda msg: logger.info("[TestHost] %s", msg))


        # Mock stats_export and repeated_m_anova for standalone testing if not available
        class MockStatsExport:
            def export_paired_results_to_excel(self, data, parent_folder, log_func): log_func(
                "Mock: export_paired_results_to_excel called")

            def export_rm_anova_results_to_excel(self, anova_table, parent_folder, log_func): log_func(
                "Mock: export_rm_anova_results_to_excel called")

            def export_significance_results_to_excel(self, findings_dict, metric, threshold, parent_folder,
                                                     log_func): log_func(
                f"Mock: export_significance_results_to_excel called for {metric}")


        class MockRepeatedMAnova:
            def run_repeated_measures_anova(self, data, dv_col, within_cols, subject_col):
                logger.info(
                    "Mock: run_repeated_measures_anova called with DV:%s, Within:%s, Subj:%s",
                    dv_col,
                    within_cols,
                    subject_col,
                )
                return pd.DataFrame(
                    {'Source': ['condition', 'roi', 'condition:roi'], 'F': [1.0, 2.0, 3.0], 'p-unc': [0.5, 0.4, 0.3]})


        # Replace actual imports with mocks if they cause issues during standalone run
        import sys

        if 'stats_export' not in sys.modules: sys.modules['stats_export'] = MockStatsExport()
        if 'repeated_m_anova' not in sys.modules: sys.modules['repeated_m_anova'] = MockRepeatedMAnova()
        # Re-import after mocking (or ensure they are imported after this block)
        from . import stats_export
        from repeated_m_anova import run_repeated_measures_anova

        ctk.CTkButton(root, text="Open Stats Tool",
                      command=lambda: StatsAnalysisWindow(master=TestMaster(), default_folder="")).pack(pady=20)
        root.mainloop()
    except Exception as e_main:
        logger.error("Error in __main__ block: %s\n%s", e_main, traceback.format_exc())
