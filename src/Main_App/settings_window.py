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
        self.geometry("400x600")
        self.resizable(False, False)
        self._build_ui()

    def _build_ui(self):
        pad = 10
        self.columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Appearance", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, pady=(pad,0))
        mode_var = tk.StringVar(value=self.manager.get('appearance','mode','System'))
        ctk.CTkOptionMenu(self, variable=mode_var, values=["System","Dark","Light"]).grid(row=1, column=0, columnspan=2, padx=pad, pady=(0,pad), sticky="ew")
        self.mode_var = mode_var

        ctk.CTkLabel(self, text="Default Data Folder").grid(row=2, column=0, sticky="w", padx=pad)
        data_var = tk.StringVar(value=self.manager.get('paths','data_folder',''))
        ctk.CTkEntry(self, textvariable=data_var).grid(row=2, column=1, sticky="ew", padx=pad)
        ctk.CTkButton(self, text="Browse", command=lambda:self._select_folder(data_var)).grid(row=2, column=2, padx=(0,pad))
        self.data_var = data_var

        ctk.CTkLabel(self, text="Default Output Folder").grid(row=3, column=0, sticky="w", padx=pad, pady=(pad,0))
        out_var = tk.StringVar(value=self.manager.get('paths','output_folder',''))
        ctk.CTkEntry(self, textvariable=out_var).grid(row=3, column=1, sticky="ew", padx=pad, pady=(pad,0))
        ctk.CTkButton(self, text="Browse", command=lambda:self._select_folder(out_var)).grid(row=3, column=2, padx=(0,pad), pady=(pad,0))
        self.out_var = out_var

        ctk.CTkLabel(self, text="Main Window Size (WxH)").grid(row=4, column=0, sticky="w", padx=pad, pady=(pad,0))
        main_var = tk.StringVar(value=self.manager.get('gui','main_size','750x920'))
        ctk.CTkEntry(self, textvariable=main_var).grid(row=4, column=1, columnspan=2, sticky="ew", padx=pad, pady=(pad,0))
        self.main_var = main_var

        ctk.CTkLabel(self, text="Stats Window Size (WxH)").grid(row=5, column=0, sticky="w", padx=pad)
        stats_var = tk.StringVar(value=self.manager.get('gui','stats_size','950x950'))
        ctk.CTkEntry(self, textvariable=stats_var).grid(row=5, column=1, columnspan=2, sticky="ew", padx=pad)
        self.stats_var = stats_var

        ctk.CTkLabel(self, text="Image Resizer Size (WxH)").grid(row=6, column=0, sticky="w", padx=pad)
        resize_var = tk.StringVar(value=self.manager.get('gui','resizer_size','800x600'))
        ctk.CTkEntry(self, textvariable=resize_var).grid(row=6, column=1, columnspan=2, sticky="ew", padx=pad)
        self.resize_var = resize_var

        ctk.CTkLabel(self, text="Advanced Analysis Size (WxH)").grid(row=7, column=0, sticky="w", padx=pad)
        adv_var = tk.StringVar(value=self.manager.get('gui','advanced_size','1050x850'))
        ctk.CTkEntry(self, textvariable=adv_var).grid(row=7, column=1, columnspan=2, sticky="ew", padx=pad)
        self.adv_var = adv_var

        ctk.CTkLabel(self, text="Stim Channel").grid(row=8, column=0, sticky="w", padx=pad, pady=(pad,0))
        stim_var = tk.StringVar(value=self.manager.get('stim','channel','Status'))
        ctk.CTkEntry(self, textvariable=stim_var).grid(row=8, column=1, columnspan=2, sticky="ew", padx=pad, pady=(pad,0))
        self.stim_var = stim_var

        ctk.CTkLabel(self, text="Default Conditions (comma)").grid(row=9, column=0, sticky="w", padx=pad, pady=(pad,0))
        cond_var = tk.StringVar(value=self.manager.get('events','labels',''))
        ctk.CTkEntry(self, textvariable=cond_var).grid(row=9, column=1, columnspan=2, sticky="ew", padx=pad, pady=(pad,0))
        self.cond_var = cond_var

        ctk.CTkLabel(self, text="Default IDs (comma)").grid(row=10, column=0, sticky="w", padx=pad)
        id_var = tk.StringVar(value=self.manager.get('events','ids',''))
        ctk.CTkEntry(self, textvariable=id_var).grid(row=10, column=1, columnspan=2, sticky="ew", padx=pad)
        self.id_var = id_var

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=11, column=0, columnspan=3, pady=(pad*2, pad))
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
        self.manager.set('appearance','mode', self.mode_var.get())
        self.manager.set('paths','data_folder', self.data_var.get())
        self.manager.set('paths','output_folder', self.out_var.get())
        self.manager.set('gui','main_size', self.main_var.get())
        self.manager.set('gui','stats_size', self.stats_var.get())
        self.manager.set('gui','resizer_size', self.resize_var.get())
        self.manager.set('gui','advanced_size', self.adv_var.get())
        self.manager.set('stim','channel', self.stim_var.get())
        self.manager.set('events','labels', self.cond_var.get())
        self.manager.set('events','ids', self.id_var.get())
        self.manager.save()

        # Apply the new appearance mode immediately across the app
        if hasattr(self.master, "set_appearance_mode"):
            self.master.set_appearance_mode(self.mode_var.get())

        self.destroy()
