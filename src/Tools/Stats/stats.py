#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stats.py

Provides a Toplevel window for statistical analysis of FPVS results.

Dual-track workflow:
  1. Summed BCA analysis using RM-ANOVA, excluding base frequency multiples
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

# Import fonts and initialization helper from the main config so the Stats
# window uses the same style settings as the rest of the application.
from config import init_fonts, FONT_MAIN, FONT_BOLD

import pandas as pd
import numpy as np
import scipy.stats as stats
from .repeated_m_anova import run_repeated_measures_anova
from .mixed_effects_model import run_mixed_effects_model
from .interpretation_helpers import generate_lme_summary
from Main_App.settings_manager import SettingsManager


from . import stats_export  # Excel export helpers
from . import stats_analysis  # Heavy data processing functions
from .posthoc_tests import (
    run_posthoc_pairwise_tests,
    run_interaction_posthocs as perform_interaction_posthocs,
)
from .stats_file_scanner import browse_folder, scan_folder, update_condition_menus, update_condition_B_options
from .stats_ui import create_widgets
from .stats_runners import (
    run_rm_anova,
    run_mixed_model,
    run_posthoc_tests,
    run_interaction_posthocs,
    run_harmonic_check,
    _structure_harmonic_results,
)
from .stats_helpers import (
    _load_base_freq,
    _load_alpha,
    _validate_numeric,
    _get_included_freqs,
    aggregate_bca_sum,
    prepare_all_subject_summed_bca_data,
    log_to_main_app,
    on_close,
    load_rois_from_settings,
    apply_rois_to_modules,
)


# Regions of Interest (10-20 montage)
ROIS = load_rois_from_settings()
apply_rois_to_modules(ROIS)
ALL_ROIS_OPTION = "(All ROIs)"
HARMONIC_CHECK_ALPHA = 0.05  # Significance level for one-sample t-test


class StatsAnalysisWindow(ctk.CTkToplevel):
    def __init__(self, master, default_folder=""):
        super().__init__(master)
        # Keep this window above its parent
        self.transient(master)

        # Ensure fonts are initialised in case this window is launched
        # independently of the main application.
        init_fonts()
        # ``option_add`` expects a concrete priority value.  Without it the
        # ``None`` forwarded by ``tkinter.Misc.option_add`` can cause Tcl to
        # complain about the number of arguments.  Using ``str`` and an
        # explicit priority sidesteps that issue.
        self.option_add("*Font", str(FONT_MAIN), 80)
        self.title("FPVS Statistical Analysis Tool")
        self.geometry("950x950")  # Adjusted for clarity of layout
        # Ensure stats window opens above the main app
        self.lift()
        self.attributes('-topmost', True)
        self.after(0, lambda: self.attributes('-topmost', False))
        self.focus_force()

        self.master_app = master

        # Reload ROI configuration in case settings changed
        self.refresh_rois()

        # Data structures
        self.subject_data = {}
        self.all_subject_data = {}  # For summed BCA: {pid: {condition: {roi: sum_bca}}}
        self.subjects = []
        self.conditions = []

        # Results storage for export (structured data)
        self.rm_anova_results_data = None  # Will store ANOVA table (ideally DataFrame)
        self.mixed_model_results_data = None  # Will store MixedLM fixed effects table
        self.harmonic_check_results_data = []
        self.posthoc_results_data = None  # DataFrame from post-hoc pairwise tests

        # UI state variables
        self.stats_data_folder_var = tk.StringVar(master=self, value=default_folder)
        self.detected_info_var = tk.StringVar(master=self, value="Select folder containing FPVS results.")
        self.base_freq = self._load_base_freq()
        self.alpha_var = tk.StringVar(master=self, value=self._load_alpha())
        self.roi_var = tk.StringVar(master=self, value=ALL_ROIS_OPTION)
        self.condition_A_var = tk.StringVar(master=self)
        self.condition_B_var = tk.StringVar(master=self)
        self.harmonic_metric_var = tk.StringVar(master=self, value="SNR")
        self.harmonic_threshold_var = tk.StringVar(master=self, value="1.96")

        # Only the interaction post-hoc is supported so default to that option
        self.posthoc_factor_var = tk.StringVar(master=self, value="condition by roi")


        # UI Widget References (stored for potential future dynamic updates)
        self.roi_menu = None
        self.condA_menu = None
        self.condB_menu = None
        self.harmonic_metric_menu = None

        # Export Buttons (instance variables to manage state)
        self.export_rm_anova_btn = None
        self.export_mixed_model_btn = None
        self.export_harmonic_check_btn = None
        self.export_posthoc_btn = None

        self.create_widgets()
        if default_folder and os.path.isdir(default_folder):
            self.scan_folder()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def refresh_rois(self):
        """Reload ROI definitions from settings and update all modules."""
        rois_from_settings = load_rois_from_settings(getattr(self.master_app, "settings", None))
        apply_rois_to_modules(rois_from_settings)
        if self.roi_menu is not None:
            new_values = [ALL_ROIS_OPTION] + list(rois_from_settings.keys())
            self.roi_menu.configure(values=new_values)
            if self.roi_var.get() not in new_values:
                self.roi_var.set(ALL_ROIS_OPTION)

    # Bind imported methods to keep class API unchanged
    browse_folder = browse_folder
    scan_folder = scan_folder
    update_condition_menus = update_condition_menus
    update_condition_B_options = update_condition_B_options
    create_widgets = create_widgets
    run_rm_anova = run_rm_anova
    run_mixed_model = run_mixed_model
    run_posthoc_tests = run_posthoc_tests
    run_interaction_posthocs = run_interaction_posthocs
    run_harmonic_check = run_harmonic_check
    _structure_harmonic_results = _structure_harmonic_results
    log_to_main_app = log_to_main_app
    on_close = on_close
    _load_base_freq = _load_base_freq
    _load_alpha = _load_alpha
    _validate_numeric = _validate_numeric
    _get_included_freqs = _get_included_freqs
    aggregate_bca_sum = aggregate_bca_sum
    prepare_all_subject_summed_bca_data = prepare_all_subject_summed_bca_data





if __name__ == "__main__":
    try:
        root = ctk.CTk()
        root.title("Main_App Test Host")
        root.geometry("300x100")


        class TestMaster:
            log = staticmethod(lambda msg: logger.info("[TestHost] %s", msg))


        # Mock stats_export and repeated_m_anova for standalone testing if not available
        class MockStatsExport:
            def export_rm_anova_results_to_excel(self, anova_table, parent_folder, log_func): log_func(
                "Mock: export_rm_anova_results_to_excel called")

            def export_significance_results_to_excel(self, findings_dict, metric, threshold, parent_folder,
                                                     log_func): log_func(
                f"Mock: export_significance_results_to_excel called for {metric}")

            def export_posthoc_results_to_excel(self, results_df, factor, parent_folder, log_func): log_func(
                "Mock: export_posthoc_results_to_excel called")


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
