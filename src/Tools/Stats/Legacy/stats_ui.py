# UI creation method extracted from stats.py

import customtkinter as ctk
from config import FONT_BOLD
from . import stats_export


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

    # --- Row 1: Section A - Summed BCA Analysis ---
    summed_bca_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    summed_bca_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=(10, 5))
    ctk.CTkLabel(summed_bca_frame, text="Summed BCA Analysis:", font=FONT_BOLD).pack(anchor="w",
                          pady=(0, 5))
    buttons_summed_frame = ctk.CTkFrame(summed_bca_frame)
    buttons_summed_frame.pack(fill="x", padx=0, pady=0)
    buttons_summed_frame.grid_columnconfigure(0, weight=1)
    buttons_summed_frame.grid_columnconfigure(1, weight=1)
    # Paired t-tests were removed; only RM-ANOVA remains
    ctk.CTkButton(
        buttons_summed_frame,
        text="Run RM-ANOVA (Summed BCA)",
        command=self.run_rm_anova,
    ).grid(row=0, column=0, padx=5, pady=(0, 5), sticky="ew")

    ctk.CTkButton(
        buttons_summed_frame,
        text="Run Mixed Model",
        command=self.run_mixed_model,
    ).grid(row=1, column=0, padx=5, pady=(0, 5), sticky="ew")

    self.run_posthoc_btn = ctk.CTkButton(
        buttons_summed_frame,
        text="Run Interaction Post-hocs",
        command=self.run_interaction_posthocs,
    )
    self.run_posthoc_btn.grid(row=2, column=0, padx=5, pady=(0, 5), sticky="ew")

    self.export_rm_anova_btn = ctk.CTkButton(
        buttons_summed_frame,
        text="Export RM-ANOVA",
        state="disabled",
        command=lambda: stats_export.export_rm_anova_results_to_excel(
            anova_table=self.rm_anova_results_data,
            parent_folder=self.stats_data_folder_var.get(),
            log_func=self.log_to_main_app,
        ),
    )
    self.export_rm_anova_btn.grid(row=0, column=1, padx=5, pady=(0, 5), sticky="ew")

    self.export_mixed_model_btn = ctk.CTkButton(
        buttons_summed_frame,
        text="Export Mixed Model",
        state="disabled",
        command=lambda: stats_export.export_mixed_model_results_to_excel(
            results_df=self.mixed_model_results_data,
            parent_folder=self.stats_data_folder_var.get(),
            log_func=self.log_to_main_app,
        ),
    )
    self.export_mixed_model_btn.grid(row=1, column=1, padx=5, pady=(0, 5), sticky="ew")

    self.export_posthoc_btn = ctk.CTkButton(
        buttons_summed_frame,
        text="Export Post-hoc Results",
        state="disabled",
        command=lambda: stats_export.export_posthoc_results_to_excel(
            results_df=self.posthoc_results_data,
            factor=self.posthoc_factor_var.get(),
            parent_folder=self.stats_data_folder_var.get(),
            log_func=self.log_to_main_app,
        ),
    )
    self.export_posthoc_btn.grid(row=2, column=1, padx=5, pady=(0, 5), sticky="ew")

    # --- Row 3: Section B - Harmonic Significance Check ---
    harmonic_check_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
    harmonic_check_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)
    ctk.CTkLabel(harmonic_check_frame, text="Per-Harmonic Significance Check:",
                 font=FONT_BOLD).pack(anchor="w", pady=(0, 5))
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
    self.export_harmonic_check_btn = ctk.CTkButton(
        controls_harmonic_frame,
        text="Export Harmonic Results",
        state="disabled",
        command=lambda: stats_export.export_significance_results_to_excel(
            findings_dict=self._structure_harmonic_results(),
            metric=self.harmonic_metric_var.get(),
            threshold=float(self.harmonic_threshold_var.get()),
            parent_folder=self.stats_data_folder_var.get(),
            log_func=self.log_to_main_app,
        ),
    )
    self.export_harmonic_check_btn.grid(row=0, column=5, padx=5, pady=5)
    controls_harmonic_frame.grid_columnconfigure(1, weight=1)  # Allow metric menu to expand

    # --- Row 4: Results Textbox ---
    self.results_textbox = ctk.CTkTextbox(main_frame, wrap="word", state="disabled",
                                          font=ctk.CTkFont(family="Courier New", size=12))
    self.results_textbox.grid(row=3, column=0, sticky="nsew", padx=5, pady=(10, 5))
    main_frame.grid_rowconfigure(3, weight=1)
