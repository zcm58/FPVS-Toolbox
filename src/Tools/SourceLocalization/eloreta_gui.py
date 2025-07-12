"""Simple GUI for running eLORETA/sLORETA localization."""

import os
import sys
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import time
import queue
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from typing import Optional

from Main_App.settings_manager import SettingsManager

import customtkinter as ctk

from config import PAD_X, PAD_Y, CORNER_RADIUS, init_fonts, FONT_MAIN
from . import runner, worker


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

        settings = SettingsManager()
        try:
            thr = float(settings.get('loreta', 'loreta_threshold', '0.0'))
        except ValueError:
            thr = 0.0
        self.threshold_var = tk.DoubleVar(master=self, value=thr)
        # use a separate StringVar for the entry widget so partially typed
        # values don't raise TclError
        self.threshold_str = tk.StringVar(master=self, value=str(thr))

        # Default to 50% transparency (alpha = 0.5)
        self.alpha_var = tk.DoubleVar(master=self, value=0.5)
        # similarly, the entry uses a StringVar to avoid invalid double strings
        self.alpha_str = tk.StringVar(master=self, value="0.5")

        self.hemi_var = tk.StringVar(master=self, value="both")

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
        self.harm_var = tk.StringVar(
            master=self,
            value=settings.get(
                'loreta',
                'oddball_harmonics',
                '1.2,2.4,3.6,4.8,7.2,8.4,9.6,10.8',
            ),
        )
        try:
            snr = float(settings.get('loreta', 'loreta_snr', '3.0'))
        except ValueError:
            snr = 3.0
        self.snr_var = tk.DoubleVar(master=self, value=snr)
        self.oddball_var = tk.BooleanVar(master=self, value=False)
        self.time_start_var = tk.StringVar(
            master=self, value=settings.get('loreta', 'time_window_start_ms', '')
        )
        self.time_end_var = tk.StringVar(
            master=self, value=settings.get('loreta', 'time_window_end_ms', '')
        )

        try:
            ti_ms = float(settings.get('visualization', 'time_index_ms', '50'))
        except ValueError:
            ti_ms = 50.0
        self.time_index_var = tk.DoubleVar(master=self, value=ti_ms)
        self.time_index_str = tk.StringVar(master=self, value=str(ti_ms))

        self.avg_mode_var = tk.StringVar(master=self, value="Raw amplitudes")


        self.brain = None
        self.last_stc_path: Optional[str] = None

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
        self.threshold_entry = ctk.CTkEntry(frame, textvariable=self.threshold_str, width=60)
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
        self.alpha_entry = ctk.CTkEntry(frame, textvariable=self.alpha_str, width=60)
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

        ctk.CTkLabel(frame, text="Display time (ms)").grid(row=9, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        self.time_index_entry = ctk.CTkEntry(frame, textvariable=self.time_index_str, width=60)
        self.time_index_entry.grid(row=9, column=1, sticky="w", padx=PAD_X, pady=PAD_Y)
        self.time_index_entry.bind("<Return>", self._on_time_index_entry)
        self.time_index_entry.bind("<FocusOut>", self._on_time_index_entry)

        ctk.CTkLabel(frame, text="LORETA time window (ms)").grid(row=10, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        ctk.CTkEntry(frame, textvariable=self.time_start_var, width=60).grid(row=10, column=1, sticky="w", padx=PAD_X, pady=PAD_Y)
        ctk.CTkEntry(frame, textvariable=self.time_end_var, width=60).grid(row=10, column=2, sticky="w", padx=PAD_X, pady=PAD_Y)

        ctk.CTkCheckBox(frame, text="Oddball localization", variable=self.oddball_var).grid(row=11, column=0, columnspan=3, sticky="w", padx=PAD_X, pady=PAD_Y)

        run_btn = ctk.CTkButton(frame, text="Run LORETA", command=self._run)
        run_btn.grid(row=12, column=0, columnspan=3, pady=(PAD_Y * 2, PAD_Y))


        view_btn = ctk.CTkButton(
            frame,
            text="View 3D brain heatmap",
            command=self._view_stc,
        )

        view_btn.grid(row=13, column=0, columnspan=3, pady=(0, PAD_Y))


        self.avgModeLabel = ctk.CTkLabel(frame, text="Averaging mode:")
        self.avgModeLabel.grid(row=14, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        self.avgModeOptions = ctk.CTkOptionMenu(
            frame,
            variable=self.avg_mode_var,
            values=["Raw amplitudes", "Normalized"],
            command=self._on_avg_mode_change,
        )
        self.avgModeOptions.grid(row=14, column=1, sticky="w", padx=PAD_X, pady=PAD_Y)

        avg_btn = ctk.CTkButton(
            frame,
            text="Average LORETA results",
            command=self._average_results,
        )

        avg_btn.grid(row=15, column=0, columnspan=3, pady=(0, PAD_Y))

        self.progress_bar = ctk.CTkProgressBar(frame, orientation="horizontal", variable=self.progress_var)
        self.progress_bar.grid(row=16, column=0, columnspan=3, sticky="ew", padx=PAD_X, pady=(0, PAD_Y))
        self.progress_bar.set(0)

        ctk.CTkLabel(frame, textvariable=self.remaining_var).grid(row=17, column=0, columnspan=3, sticky="w", padx=PAD_X, pady=(0, PAD_Y))


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
        if path.endswith("-lh.stc") or path.endswith("-rh.stc"):
            path = path[:-7]
        log_func = getattr(self.master, "log", print)
        log_func(f"Opening STC viewer for {path}")
        # log the threshold that will be used in the viewer
        try:
            current_thr = float(self.threshold_var.get())
        except Exception:
            current_thr = 0.0
        log_func(f"LORETA threshold: {current_thr}")

        # read the source estimate to report the initial time index
        try:
            import mne

            stc = mne.read_source_estimate(path)
            first_time_ms = stc.times[0] * 1000
            log_func(f"Initial timestamp: {first_time_ms:.1f} ms")
        except Exception as err:
            log_func(f"Could not read initial timestamp: {err}")

        def _open_viewer():
            try:
                script = Path(__file__).with_name("pyqt_viewer.py")
                args = [sys.executable, str(script), "--stc", path]
                try:
                    time_ms = float(self.time_index_var.get())
                    args.extend(["--time-ms", str(time_ms)])
                except Exception:
                    pass
                subprocess.Popen(args)
            except Exception as err:
                log_func(f"STC viewer failed: {err}")
                messagebox.showerror("Error", str(err))

        self.after(0, _open_viewer)


    def _average_results(self):
        folder = filedialog.askdirectory(
            title="Select LORETA RESULTS folder", parent=self
        )
        if not folder:
            return

        # Check for previously averaged STC files
        existing = []
        for root_dir, _, files in os.walk(folder):
            for name in files:
                if not name.endswith(".stc"):
                    continue
                base = name[:-7] if name.endswith(("-lh.stc", "-rh.stc")) else name
                if base.startswith("Average ") or base == "fsaverage":
                    existing.append(os.path.join(root_dir, name))

        if existing:
            msg = (
                "Existing averaged files were found.\n"
                "Do you want to overwrite them?"
            )
            if not messagebox.askyesno("Overwrite?", msg, parent=self):
                return
            for path in existing:
                try:
                    os.remove(path)
                except Exception:
                    pass

        log_func = getattr(self.master, "log", print)

        settings = SettingsManager()
        stored_dir = settings.get("loreta", "mri_path", "")
        if stored_dir:
            stored_dir = os.path.normpath(stored_dir)
        subject = "fsaverage"
        if os.path.basename(stored_dir) == subject:
            subjects_dir = os.path.dirname(stored_dir)
        else:
            from .data_utils import _default_template_location

            subjects_dir = stored_dir if stored_dir else os.path.dirname(
                _default_template_location()
            )

        def _task():
            try:
                mode = self.avgModeOptions.get()
                normalize = mode == "Normalized"
                log_func(f"Averaging mode: {mode}")
                runner.average_conditions_to_fsaverage(
                    folder,
                    subjects_dir,
                    log_func=log_func,
                    normalize=normalize,
                )
                self.after(
                    0,
                    lambda: messagebox.showinfo("Done", "Averaging complete."),
                )
            except Exception as err:
                err_str = str(err)
                self.after(0, lambda e=err_str: messagebox.showerror("Error", e))

        threading.Thread(target=_task, daemon=True).start()

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
        # ensure any in-progress edits are parsed
        self._on_threshold_entry()
        self._on_alpha_entry()
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
        settings = SettingsManager()
        try:
            b_start = float(settings.get('loreta', 'baseline_tmin', '0'))
            b_end = float(settings.get('loreta', 'baseline_tmax', '0'))
            baseline = (b_start, b_end)
        except ValueError:
            baseline = None
        try:
            start_ms = float(self.time_start_var.get())
            end_ms = float(self.time_end_var.get())
            time_window = (start_ms, end_ms)
        except ValueError:
            time_window = None
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
                False,
                baseline,
                time_window,
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
        export_rois,
        baseline,
        time_window,
    ):
        log_func = getattr(self.master, "log", print)
        ctx = mp.get_context("spawn")
        q = ctx.Queue()

        with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
            future = ex.submit(
                worker.run_localization_worker,
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
                export_rois=export_rois,
                baseline=baseline,
                time_window=time_window,
                queue=q,
            )

            while True:
                try:
                    msg = q.get(timeout=0.1)
                    if msg["type"] == "progress":
                        self.after(0, self._update_progress, msg["value"])
                    elif msg["type"] == "log":
                        self.after(0, log_func, msg["message"])
                except queue.Empty:
                    if future.done():
                        break

            try:
                _stc_path, _ = future.result()
                self.last_stc_path = _stc_path
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
            new_val = round(float(value), 3)
            self.threshold_var.set(new_val)
            self.threshold_str.set(str(new_val))
        except tk.TclError:
            pass

    def _on_threshold_entry(self, _event=None) -> None:
        """Validate entry value and update slider."""
        try:
            value = float(self.threshold_str.get())
        except (ValueError, tk.TclError):
            return
        value = max(0.0, min(1.0, value))
        self.threshold_var.set(value)
        self.threshold_str.set(str(value))
        self.threshold_slider.set(value)

    def _on_alpha_slider(self, value: float) -> None:
        """Update alpha when slider moves."""
        try:
            new_val = round(float(value), 2)
            self.alpha_var.set(new_val)
            self.alpha_str.set(str(new_val))
        except tk.TclError:
            return


    def _on_alpha_entry(self, _event=None) -> None:
        """Validate entry value and update slider."""
        try:
            value = float(self.alpha_str.get())
        except (ValueError, tk.TclError):
            return
        value = max(0.1, min(1.0, value))
        self.alpha_var.set(value)
        self.alpha_str.set(str(value))
        self.alpha_slider.set(value)


    def _on_time_index_entry(self, _event=None) -> None:
        """Validate time entry value."""
        try:
            value = float(self.time_index_str.get())
        except (ValueError, tk.TclError):
            return
        value = max(0.0, value)
        self.time_index_var.set(value)
        self.time_index_str.set(str(value))

    def _on_avg_mode_change(self, value: str) -> None:
        """Callback when the averaging mode option is changed."""
        self.avg_mode_var.set(value)

