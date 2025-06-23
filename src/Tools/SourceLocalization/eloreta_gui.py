"""Simple GUI for running eLORETA/sLORETA localization."""

import os
import tkinter as tk
from tkinter import filedialog, messagebox
import threading

import customtkinter as ctk

from config import PAD_X, PAD_Y, CORNER_RADIUS, init_fonts, FONT_MAIN
from . import eloreta_runner


class SourceLocalizationWindow(ctk.CTkToplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.transient(master)
        init_fonts()
        self.option_add("*Font", str(FONT_MAIN), 80)
        self.title("Source Localization")
        self.geometry("500x300")
        self.lift()
        self.attributes('-topmost', True)
        self.after(0, lambda: self.attributes('-topmost', False))
        self.focus_force()

        self.input_var = tk.StringVar(master=self)
        self.output_var = tk.StringVar(master=self)
        self.method_var = tk.StringVar(master=self, value="eLORETA")
        self.threshold_var = tk.DoubleVar(master=self, value=0.0)

        self._build_ui()

    def _build_ui(self):
        frame = ctk.CTkFrame(self, corner_radius=CORNER_RADIUS)
        frame.pack(fill="both", expand=True, padx=PAD_X, pady=PAD_Y)
        frame.columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="Input FIF file:").grid(row=0, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        ctk.CTkEntry(frame, textvariable=self.input_var, width=300).grid(row=0, column=1, sticky="we", padx=PAD_X, pady=PAD_Y)
        ctk.CTkButton(frame, text="Browse", command=self._browse_file).grid(row=0, column=2, padx=PAD_X, pady=PAD_Y)

        ctk.CTkLabel(frame, text="Output folder:").grid(row=1, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        ctk.CTkEntry(frame, textvariable=self.output_var, width=300).grid(row=1, column=1, sticky="we", padx=PAD_X, pady=PAD_Y)
        ctk.CTkButton(frame, text="Browse", command=self._browse_folder).grid(row=1, column=2, padx=PAD_X, pady=PAD_Y)

        ctk.CTkLabel(frame, text="Method:").grid(row=2, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        method_menu = ctk.CTkOptionMenu(frame, variable=self.method_var, values=["eLORETA", "sLORETA"])
        method_menu.grid(row=2, column=1, sticky="w", padx=PAD_X, pady=PAD_Y)

        ctk.CTkLabel(frame, text="Threshold:").grid(row=3, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        self.threshold_slider = ctk.CTkSlider(
            frame,
            from_=0.0,
            to=1.0,
            variable=self.threshold_var,
            command=self._on_threshold_slider,
        )
        self.threshold_slider.grid(row=3, column=1, sticky="we", padx=PAD_X, pady=PAD_Y)
        self.threshold_entry = ctk.CTkEntry(frame, textvariable=self.threshold_var, width=60)
        self.threshold_entry.grid(row=3, column=2, sticky="w", padx=PAD_X, pady=PAD_Y)
        self.threshold_entry.bind("<Return>", self._on_threshold_entry)
        self.threshold_entry.bind("<FocusOut>", self._on_threshold_entry)

        run_btn = ctk.CTkButton(frame, text="Run", command=self._run)
        run_btn.grid(row=4, column=0, columnspan=3, pady=(PAD_Y * 2, PAD_Y))

    def _browse_file(self):
        path = filedialog.askopenfilename(title="Select FIF file", filetypes=[("FIF files", "*.fif")], parent=self)
        if path:
            self.input_var.set(path)

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select Output Folder", parent=self)
        if folder:
            self.output_var.set(folder)

    def _run(self):
        fif_path = self.input_var.get()
        out_dir = self.output_var.get()
        if not fif_path or not os.path.isfile(fif_path):
            messagebox.showerror("Error", "Valid FIF file required.")
            return
        if not out_dir:
            messagebox.showerror("Error", "Select an output folder.")
            return
        method = self.method_var.get()
        thr = self.threshold_var.get()
        threading.Thread(
            target=self._run_thread,
            args=(fif_path, out_dir, method, thr),
            daemon=True
        ).start()

    def _run_thread(self, fif_path, out_dir, method, thr):
        log_func = getattr(self.master, "log", print)
        try:
            eloreta_runner.run_source_localization(
                fif_path,
                out_dir,
                method=method,
                threshold=thr,
                log_func=log_func,
            )
            self.after(0, lambda: messagebox.showinfo("Done", "Source localization finished."))
        except Exception as e:

            self.after(0, lambda: messagebox.showerror("Error", str(e)))

    def _on_threshold_slider(self, value: float) -> None:
        """Update variable when slider moves."""
        try:
            self.threshold_var.set(round(float(value), 3))
        except tk.TclError:
            pass

    def _on_threshold_entry(self, _event=None) -> None:
        """Validate entry value and update slider."""
        try:
            value = float(self.threshold_var.get())
        except (ValueError, tk.TclError):
            return
        value = max(0.0, min(1.0, value))
        self.threshold_var.set(value)
        self.threshold_slider.set(value)

