"""Simple GUI for running eLORETA/sLORETA localization."""

import os
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import time
from typing import Optional

from Main_App.settings_manager import SettingsManager

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
        # Default to 60% transparency (alpha = 0.4)
        self.alpha_var = tk.DoubleVar(master=self, value=0.4)

        self.hemi_var = tk.StringVar(master=self, value="both")

        settings = SettingsManager()
        try:
            low = float(settings.get('loreta', 'loreta_low_freq', '0.1'))
        except ValueError:
            low = 0.1
        try:
            high = float(settings.get('loreta', 'loreta_high_freq', '40.0'))
        except ValueError:
            high = 40.0
        self.low_var = tk.DoubleVar(master=self, value=low)
        self.high_var = tk.DoubleVar(master=self, value=high)
        self.harm_var = tk.StringVar(master=self, value=settings.get('loreta', 'oddball_harmonics', '1,2,3'))
        try:
            snr = float(settings.get('loreta', 'loreta_snr', '3.0'))
        except ValueError:
            snr = 3.0
        self.snr_var = tk.DoubleVar(master=self, value=snr)
        self.oddball_var = tk.BooleanVar(master=self, value=False)


        self.brain = None

        self.progress_var = tk.DoubleVar(master=self, value=0.0)
        self.remaining_var = tk.StringVar(master=self, value="")
        self._start_time = None
        self.processing_thread = None

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

        ctk.CTkLabel(frame, text="Transparency:").grid(row=4, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        self.alpha_slider = ctk.CTkSlider(
            frame,
            from_=0.1,
            to=1.0,
            variable=self.alpha_var,
            command=self._on_alpha_slider,
        )
        self.alpha_slider.grid(row=4, column=1, sticky="we", padx=PAD_X, pady=PAD_Y)
        self.alpha_entry = ctk.CTkEntry(frame, textvariable=self.alpha_var, width=60)
        self.alpha_entry.grid(row=4, column=2, sticky="w", padx=PAD_X, pady=PAD_Y)
        self.alpha_entry.bind("<Return>", self._on_alpha_entry)
        self.alpha_entry.bind("<FocusOut>", self._on_alpha_entry)

        ctk.CTkLabel(frame, text="Low Freq (Hz)").grid(row=5, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        ctk.CTkEntry(frame, textvariable=self.low_var, width=60).grid(row=5, column=1, sticky="w", padx=PAD_X, pady=PAD_Y)

        ctk.CTkLabel(frame, text="High Freq (Hz)").grid(row=6, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        ctk.CTkEntry(frame, textvariable=self.high_var, width=60).grid(row=6, column=1, sticky="w", padx=PAD_X, pady=PAD_Y)

        ctk.CTkLabel(frame, text="Oddball Harmonics").grid(row=7, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        ctk.CTkEntry(frame, textvariable=self.harm_var, width=100).grid(row=7, column=1, sticky="w", padx=PAD_X, pady=PAD_Y)

        ctk.CTkLabel(frame, text="SNR").grid(row=8, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        ctk.CTkEntry(frame, textvariable=self.snr_var, width=60).grid(row=8, column=1, sticky="w", padx=PAD_X, pady=PAD_Y)

        ctk.CTkCheckBox(frame, text="Oddball localization", variable=self.oddball_var).grid(row=9, column=0, columnspan=3, sticky="w", padx=PAD_X, pady=PAD_Y)

        view_btn = ctk.CTkButton(
            frame,
            text="View 3D brain heatmap",
            command=self._view_stc,
        )
        view_btn.grid(row=10, column=0, columnspan=3, pady=(0, PAD_Y))

        self.progress_bar = ctk.CTkProgressBar(frame, orientation="horizontal", variable=self.progress_var)
        self.progress_bar.grid(row=12, column=0, columnspan=3, sticky="ew", padx=PAD_X, pady=(0, PAD_Y))
        self.progress_bar.set(0)

        ctk.CTkLabel(frame, textvariable=self.remaining_var).grid(row=13, column=0, columnspan=3, sticky="w", padx=PAD_X, pady=(0, PAD_Y))


    def _browse_file(self):
        path = filedialog.askopenfilename(title="Select FIF file", filetypes=[("FIF files", "*.fif")], parent=self)
        if path:
            self.input_var.set(path)

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Select Output Folder", parent=self)
        if folder:
            self.output_var.set(folder)

    def _view_stc(self):
        path = filedialog.askopenfilename(
            title="Select SourceEstimate file",
            filetypes=[("SourceEstimate", "*-lh.stc"), ("All files", "*")],
            parent=self,
        )
        if not path:
            return
        title = os.path.basename(path)
        if path.endswith("-lh.stc") or path.endswith("-rh.stc"):
            path = path[:-7]
        log_func = getattr(self.master, "log", print)
        log_func(f"Opening STC viewer for {path}")
        try:

            self.brain = eloreta_runner.view_source_estimate(
                path,
                threshold=self.threshold_var.get(),
                alpha=self.alpha_var.get(),
                window_title=title,

            )

        except Exception as err:
            log_func(f"STC viewer failed: {err}")
            messagebox.showerror("Error", str(err))

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
        self.progress_var.set(0)
        self.remaining_var.set("")
        self._start_time = time.time()
        harmonics = []
        for h in self.harm_var.get().split(','):
            try:
                harmonics.append(float(h))
            except ValueError:
                pass
        self.processing_thread = threading.Thread(
            target=self._run_thread,
            args=(
                fif_path,
                out_dir,
                method,
                thr,
                self.alpha_var.get(),
                self.hemi_var.get(),
                self.low_var.get(),
                self.high_var.get(),
                harmonics,
                self.snr_var.get(),
                self.oddball_var.get(),
            ),
            daemon=True
        )
        self.processing_thread.start()
        self.after(100, self._update_time_remaining)


    def _run_thread(
        self,
        fif_path,
        out_dir,
        method,
        thr,
        alpha,
        hemi,
        low_freq,
        high_freq,
        harmonics,
        snr,
        oddball,
    ):

        log_func = getattr(self.master, "log", print)
        try:
            _stc_path, self.brain = eloreta_runner.run_source_localization(
                fif_path,
                out_dir,
                method=method,
                threshold=thr,
                alpha=alpha,

                hemi=hemi,
                low_freq=low_freq,
                high_freq=high_freq,
                harmonics=harmonics,
                snr=snr,
                oddball=oddball,
                log_func=log_func,
                progress_cb=lambda f: self.after(0, self._update_progress, f),
            )
            self.after(0, self._on_finish, None)
        except Exception as e:
            self.after(0, self._on_finish, e)

    def _update_progress(self, fraction: float) -> None:
        self.progress_var.set(fraction)

    def _on_finish(self, error: Optional[Exception]) -> None:
        self.processing_thread = None
        self._start_time = None
        self.remaining_var.set("")
        if error is None:
            messagebox.showinfo("Done", "Source localization finished.")
        else:
            messagebox.showerror("Error", str(error))

    def _update_time_remaining(self) -> None:
        if self._start_time is None:
            return
        elapsed = time.time() - self._start_time
        frac = self.progress_var.get()
        if frac > 0:
            remaining = elapsed * (1 - frac) / frac
            mins, secs = divmod(int(remaining), 60)
            self.remaining_var.set(f"Estimated time remaining: {mins:02d}:{secs:02d}")
        else:
            self.remaining_var.set("")
        if self.processing_thread and self.processing_thread.is_alive():
            self.after(1000, self._update_time_remaining)

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

    def _on_alpha_slider(self, value: float) -> None:
        """Update alpha when slider moves."""
        try:
            self.alpha_var.set(round(float(value), 2))
        except tk.TclError:
            return
        if self.brain is not None:
            eloreta_runner.logger.debug(
                "_on_alpha_slider updating brain to %s", self.alpha_var.get()
            )
            eloreta_runner._set_brain_alpha(self.brain, self.alpha_var.get())

    def _on_alpha_entry(self, _event=None) -> None:
        """Validate entry value and update slider."""
        try:
            value = float(self.alpha_var.get())
        except (ValueError, tk.TclError):
            return
        value = max(0.1, min(1.0, value))
        self.alpha_var.set(value)
        self.alpha_slider.set(value)
        if self.brain is not None:
            eloreta_runner.logger.debug(
                "_on_alpha_entry updating brain to %s", value
            )
            eloreta_runner._set_brain_alpha(self.brain, value)

