import tkinter as tk
from tkinter import filedialog
import customtkinter as ctk

from config import init_fonts, FONT_MAIN
from .settings_manager import SettingsManager


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master, manager: SettingsManager):
        super().__init__(master)
        self.manager = manager
        init_fonts()
        self.option_add("*Font", str(FONT_MAIN), 80)
        self.title("Settings")
        # Widen the window slightly so the debug checkbox
        # is not clipped on some platforms
        self.geometry("600x600")
        self.resizable(False, False)
        self._build_ui()
        self.focus_force()

    def _build_ui(self):
        pad = 10
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        tabview = ctk.CTkTabview(self)
        tabview.grid(row=0, column=0, padx=pad, pady=pad, sticky="nsew")
        gen_tab = tabview.add("General")
        stats_tab = tabview.add("Stats")
        gen_tab.columnconfigure(1, weight=1)
        stats_tab.columnconfigure(1, weight=1)

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

        ctk.CTkLabel(stats_tab, text="BCA Upper Limit (Hz)").grid(row=2, column=0, sticky="w", padx=pad)
        bca_var = tk.StringVar(value=self.manager.get('analysis', 'bca_upper_limit', '16.8'))
        ctk.CTkEntry(stats_tab, textvariable=bca_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=pad)
        self.bca_var = bca_var

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
        prev_debug = self.manager.get('debug', 'enabled', 'False').lower() == 'true'
        self.manager.set('debug', 'enabled', str(self.debug_var.get()))
        self.manager.save()

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
