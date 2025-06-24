"""GUI window for editing FPVS Toolbox preferences.

The :class:`SettingsWindow` presents tabs of configurable options such as file
paths, appearance settings and analysis parameters.  It interfaces with
``SettingsManager`` to load existing values and persist any changes made by the
user.
"""

import os
import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk
from Tools.SourceLocalization.eloreta_runner import fetch_fsaverage_with_progress

from config import init_fonts, FONT_MAIN
from .settings_manager import SettingsManager
from .roi_settings_editor import ROISettingsEditor


def _find_fsaverage_dir() -> str:
    """Return the fsaverage directory if it exists locally."""
    try:
        import mne
        subjects_dir = mne.get_config('SUBJECTS_DIR', os.getenv('SUBJECTS_DIR'))
        if subjects_dir:
            path = os.path.join(subjects_dir, 'fsaverage')
            if os.path.isdir(path):
                return path
    except Exception:
        pass
    return ''


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, manager: SettingsManager):
        super().__init__(master)
        # Ensure this window stays above its parent
        self.transient(master)
        self.manager = manager
        init_fonts()
        self.option_add("*Font", str(FONT_MAIN), 80)
        self.title("Settings")
        # Widen the window slightly so the debug checkbox
        # is not clipped on some platforms
        self.geometry("600x600")
        self.resizable(False, False)
        self._build_ui()
        # Bring settings window to the front when opened
        self.lift()
        self.attributes('-topmost', True)
        self.after(0, lambda: self.attributes('-topmost', False))
        self.focus_force()

    def _build_ui(self):
        pad = 10
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        tabview = ctk.CTkTabview(self)
        tabview.grid(row=0, column=0, padx=pad, pady=pad, sticky="nsew")
        gen_tab = tabview.add("General")
        stats_tab = tabview.add("Stats")
        loreta_tab = tabview.add("LORETA")
        gen_tab.columnconfigure(1, weight=1)
        stats_tab.columnconfigure(1, weight=1)
        loreta_tab.columnconfigure(1, weight=1)

        # --- General Tab ---
        ctk.CTkLabel(gen_tab, text="Appearance", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, pady=(pad, 0))
        mode_var = tk.StringVar(value=self.manager.get('appearance', 'mode', 'System'))
        ctk.CTkOptionMenu(gen_tab, variable=mode_var, values=["System", "Dark", "Light"]).grid(row=1, column=0, columnspan=2, padx=pad, pady=(0, pad), sticky="ew")
        self.mode_var = mode_var

        ctk.CTkLabel(gen_tab, text="Default Data Folder").grid(row=2, column=0, sticky="w", padx=pad)
        data_var = tk.StringVar(value=self.manager.get('paths', 'data_folder', ''))
        ctk.CTkEntry(gen_tab, textvariable=data_var).grid(row=2, column=1, sticky="ew", padx=pad)
        ctk.CTkButton(gen_tab, text="Browse", command=lambda: self._select_folder(data_var)).grid(row=2, column=2, padx=(0, pad))
        self.data_var = data_var

        ctk.CTkLabel(gen_tab, text="Default Output Folder").grid(row=3, column=0, sticky="w", padx=pad, pady=(pad, 0))
        out_var = tk.StringVar(value=self.manager.get('paths', 'output_folder', ''))
        ctk.CTkEntry(gen_tab, textvariable=out_var).grid(row=3, column=1, sticky="ew", padx=pad, pady=(pad, 0))
        ctk.CTkButton(gen_tab, text="Browse", command=lambda: self._select_folder(out_var)).grid(row=3, column=2, padx=(0, pad), pady=(pad, 0))
        self.out_var = out_var

        ctk.CTkLabel(gen_tab, text="Main Window Size (WxH)").grid(row=4, column=0, sticky="w", padx=pad, pady=(pad, 0))
        main_var = tk.StringVar(value=self.manager.get('gui', 'main_size', '750x920'))
        ctk.CTkEntry(gen_tab, textvariable=main_var).grid(row=4, column=1, columnspan=2, sticky="ew", padx=pad, pady=(pad, 0))
        self.main_var = main_var

        ctk.CTkLabel(gen_tab, text="Stats Window Size (WxH)").grid(row=5, column=0, sticky="w", padx=pad)
        stats_var = tk.StringVar(value=self.manager.get('gui', 'stats_size', '950x950'))
        ctk.CTkEntry(gen_tab, textvariable=stats_var).grid(row=5, column=1, columnspan=2, sticky="ew", padx=pad)
        self.stats_var = stats_var

        ctk.CTkLabel(gen_tab, text="Image Resizer Size (WxH)").grid(row=6, column=0, sticky="w", padx=pad)
        resize_var = tk.StringVar(value=self.manager.get('gui', 'resizer_size', '800x600'))
        ctk.CTkEntry(gen_tab, textvariable=resize_var).grid(row=6, column=1, columnspan=2, sticky="ew", padx=pad)
        self.resize_var = resize_var

        ctk.CTkLabel(gen_tab, text="Advanced Analysis Size (WxH)").grid(row=7, column=0, sticky="w", padx=pad)
        adv_var = tk.StringVar(value=self.manager.get('gui', 'advanced_size', '1050x850'))
        ctk.CTkEntry(gen_tab, textvariable=adv_var).grid(row=7, column=1, columnspan=2, sticky="ew", padx=pad)
        self.adv_var = adv_var

        ctk.CTkLabel(gen_tab, text="Stim Channel").grid(row=8, column=0, sticky="w", padx=pad, pady=(pad, 0))
        stim_var = tk.StringVar(value=self.manager.get('stim', 'channel', 'Status'))
        ctk.CTkEntry(gen_tab, textvariable=stim_var).grid(row=8, column=1, columnspan=2, sticky="ew", padx=pad, pady=(pad, 0))
        self.stim_var = stim_var

        ctk.CTkLabel(gen_tab, text="Default Conditions (comma)").grid(row=9, column=0, sticky="w", padx=pad, pady=(pad, 0))
        cond_var = tk.StringVar(value=self.manager.get('events', 'labels', ''))
        ctk.CTkEntry(gen_tab, textvariable=cond_var).grid(row=9, column=1, columnspan=2, sticky="ew", padx=pad, pady=(pad, 0))
        self.cond_var = cond_var

        ctk.CTkLabel(gen_tab, text="Default IDs (comma)").grid(row=10, column=0, sticky="w", padx=pad)
        id_var = tk.StringVar(value=self.manager.get('events', 'ids', ''))
        ctk.CTkEntry(gen_tab, textvariable=id_var).grid(row=10, column=1, columnspan=2, sticky="ew", padx=pad)
        self.id_var = id_var

        debug_default = self.manager.get('debug', 'enabled', 'False').lower() == 'true'
        self.debug_var = tk.BooleanVar(value=debug_default)
        ctk.CTkLabel(gen_tab, text="Debug Mode").grid(row=11, column=0, sticky="w", padx=pad, pady=(pad, 0))
        ctk.CTkCheckBox(gen_tab, text="Enable", variable=self.debug_var).grid(row=11, column=1, sticky="w", padx=pad, pady=(pad, 0))

        # --- Stats Tab ---
        ctk.CTkLabel(stats_tab, text="FPVS Base Frequency (Hz)").grid(row=0, column=0, sticky="w", padx=pad, pady=(pad, 0))
        base_var = tk.StringVar(value=self.manager.get('analysis', 'base_freq', '6.0'))
        ctk.CTkEntry(stats_tab, textvariable=base_var).grid(row=0, column=1, columnspan=2, sticky="ew", padx=pad, pady=(pad, 0))
        self.base_var = base_var

        ctk.CTkLabel(stats_tab, text="Oddball Frequency (Hz)").grid(row=1, column=0, sticky="w", padx=pad, pady=(pad, 0))
        odd_var = tk.StringVar(value=self.manager.get('analysis', 'oddball_freq', '1.2'))
        ctk.CTkEntry(stats_tab, textvariable=odd_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=pad, pady=(pad, 0))
        self.odd_var = odd_var

        ctk.CTkLabel(stats_tab, text="BCA Harmonic Upper Limit (Hz)").grid(row=2, column=0, sticky="w", padx=pad)
        bca_var = tk.StringVar(value=self.manager.get('analysis', 'bca_upper_limit', '16.8'))
        ctk.CTkEntry(stats_tab, textvariable=bca_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=pad)
        self.bca_var = bca_var

        ctk.CTkLabel(stats_tab, text="Alpha value for ANOVA").grid(row=3, column=0, sticky="w", padx=pad, pady=(pad, 0))
        alpha_var = tk.StringVar(value=self.manager.get('analysis', 'alpha', '0.05'))
        ctk.CTkEntry(stats_tab, textvariable=alpha_var).grid(row=3, column=1, columnspan=2, sticky="ew", padx=pad, pady=(pad, 0))
        self.alpha_var = alpha_var

        ctk.CTkLabel(stats_tab, text="Regions of Interest", font=ctk.CTkFont(weight="bold")).grid(row=4, column=0, columnspan=3, sticky="w", padx=pad, pady=(pad, 0))
        roi_pairs = self.manager.get_roi_pairs()
        self.roi_editor = ROISettingsEditor(stats_tab, roi_pairs)
        self.roi_editor.scroll.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=pad)
        stats_tab.rowconfigure(5, weight=1)
        ctk.CTkButton(stats_tab, text="+ Add ROI", command=self.roi_editor.add_entry).grid(row=6, column=0, columnspan=3, sticky="w", padx=pad, pady=(0, pad))

        # --- LORETA Tab ---


        install_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fs_default = fetch_fsaverage_with_progress(install_base, log_func=print)

        ctk.CTkLabel(loreta_tab, text="MRI Directory").grid(row=0, column=0, sticky="w", padx=pad, pady=(pad, 0))
        mri_var = tk.StringVar(value=self.manager.get('loreta', 'mri_path', fs_default))
        ctk.CTkEntry(loreta_tab, textvariable=mri_var).grid(row=0, column=1, sticky="ew", padx=pad, pady=(pad, 0))
        ctk.CTkButton(loreta_tab, text="Browse", command=lambda: self._select_folder(mri_var)).grid(row=0, column=2, padx=(0, pad), pady=(pad, 0))
        self.mri_var = mri_var

        ctk.CTkLabel(loreta_tab, text="Low Freq (Hz)").grid(row=1, column=0, sticky="w", padx=pad)
        low_var = tk.StringVar(value=self.manager.get('loreta', 'loreta_low_freq', '0.1'))
        ctk.CTkEntry(loreta_tab, textvariable=low_var).grid(row=1, column=1, sticky="ew", padx=pad)
        self.low_var = low_var

        ctk.CTkLabel(loreta_tab, text="High Freq (Hz)").grid(row=2, column=0, sticky="w", padx=pad)
        high_var = tk.StringVar(value=self.manager.get('loreta', 'loreta_high_freq', '40.0'))
        ctk.CTkEntry(loreta_tab, textvariable=high_var).grid(row=2, column=1, sticky="ew", padx=pad)
        self.high_var = high_var

        ctk.CTkLabel(loreta_tab, text="Oddball Harmonics").grid(row=3, column=0, sticky="w", padx=pad)
        harm_var = tk.StringVar(value=self.manager.get('loreta', 'oddball_harmonics', '1,2,3'))
        ctk.CTkEntry(loreta_tab, textvariable=harm_var).grid(row=3, column=1, sticky="ew", padx=pad)
        self.harm_var = harm_var

        ctk.CTkLabel(loreta_tab, text="SNR").grid(row=4, column=0, sticky="w", padx=pad)
        snr_var = tk.StringVar(value=self.manager.get('loreta', 'loreta_snr', '3.0'))
        ctk.CTkEntry(loreta_tab, textvariable=snr_var).grid(row=4, column=1, sticky="ew", padx=pad)
        self.snr_var = snr_var

        auto_loc_default = self.manager.get('loreta', 'auto_oddball_localization', 'False').lower() == 'true'
        self.auto_loc_var = tk.BooleanVar(value=auto_loc_default)
        ctk.CTkCheckBox(
            loreta_tab,
            text="Auto Oddball Localization",
            variable=self.auto_loc_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=pad)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=1, column=0, pady=(0, pad))
        ctk.CTkButton(btn_frame, text="Reset to Defaults", command=self._reset).pack(side="left", padx=pad)
        ctk.CTkButton(btn_frame, text="Save", command=self._save).pack(side="right", padx=pad)

    def _select_folder(self, var):
        folder = filedialog.askdirectory()
        if folder:
            var.set(folder)

    def _reset(self):
        self.manager.reset()
        self.destroy()

    def _save(self):
        self.manager.set('appearance', 'mode', self.mode_var.get())
        self.manager.set('paths', 'data_folder', self.data_var.get())
        self.manager.set('paths', 'output_folder', self.out_var.get())
        self.manager.set('gui', 'main_size', self.main_var.get())
        self.manager.set('gui', 'stats_size', self.stats_var.get())
        self.manager.set('gui', 'resizer_size', self.resize_var.get())
        self.manager.set('gui', 'advanced_size', self.adv_var.get())
        self.manager.set('stim', 'channel', self.stim_var.get())
        self.manager.set('events', 'labels', self.cond_var.get())
        self.manager.set('events', 'ids', self.id_var.get())
        self.manager.set('analysis', 'base_freq', self.base_var.get())
        self.manager.set('analysis', 'oddball_freq', self.odd_var.get())
        self.manager.set('analysis', 'bca_upper_limit', self.bca_var.get())
        self.manager.set('analysis', 'alpha', self.alpha_var.get())
        self.manager.set_roi_pairs(self.roi_editor.get_pairs())
        self.manager.set('loreta', 'mri_path', self.mri_var.get())
        self.manager.set('loreta', 'loreta_low_freq', self.low_var.get())
        self.manager.set('loreta', 'loreta_high_freq', self.high_var.get())
        self.manager.set('loreta', 'oddball_harmonics', self.harm_var.get())
        self.manager.set('loreta', 'loreta_snr', self.snr_var.get())
        self.manager.set(
            'loreta',
            'auto_oddball_localization',
            str(self.auto_loc_var.get()),
        )
        prev_debug = self.manager.get('debug', 'enabled', 'False').lower() == 'true'
        self.manager.set('debug', 'enabled', str(self.debug_var.get()))
        self.manager.save()

        # Update ROI definitions in any open Stats windows
        try:
            from Tools.Stats.stats_helpers import load_rois_from_settings, apply_rois_to_modules
            from Tools.Stats.stats import StatsAnalysisWindow
            rois = load_rois_from_settings(self.manager)
            apply_rois_to_modules(rois)
            for child in self.master.winfo_children():
                if isinstance(child, StatsAnalysisWindow):
                    child.refresh_rois()
        except Exception:
            pass

        try:
            from config import update_target_frequencies
            update_target_frequencies(float(self.odd_var.get()), float(self.bca_var.get()))
        except Exception:
            pass

        if hasattr(self.master, 'set_appearance_mode'):
            self.master.set_appearance_mode(self.mode_var.get())

        if prev_debug != self.debug_var.get():
            from tkinter import messagebox
            messagebox.showinfo("Restart Required", "Please restart the app for debug mode changes to take effect.")

        self.destroy()

