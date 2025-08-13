"""Helper functions for reading EEG recordings into MNE.

Only ``.bdf`` files are supported and loaded with the appropriate
options. A warning is shown for any unsupported format."""

import os
from pathlib import Path
import tempfile
from tkinter import messagebox

import numpy as np
import mne


def load_eeg_file(app, filepath):
    """Load an EEG file with disk-backed memmap and apply montage (no resample)."""
    ext = os.path.splitext(filepath)[1].lower()
    base = os.path.basename(filepath)
    app.log(f"Loading: {base}...")
    try:
        if ext == ".bdf":
            memmap_dir = Path(tempfile.gettempdir()) / "fpvs_memmap"
            memmap_dir.mkdir(exist_ok=True)
            memmap_path = str(memmap_dir / (Path(filepath).stem + "_raw.dat"))
            with mne.utils.use_log_level("WARNING"):
                raw = mne.io.read_raw_bdf(
                    filepath,
                    preload=memmap_path,      # disk-backed; safe for big filters
                    stim_channel="Status",
                    verbose=False,
                )
            # Drop unused EXG3–EXG8 immediately
            drop_pre = [c for c in ("EXG3","EXG4","EXG5","EXG6","EXG7","EXG8") if c in raw.ch_names]
            if drop_pre:
                raw.drop_channels(drop_pre)

            # Materialize against the memmap (older MNE has no dtype kw)
            raw.load_data()
            app.log("BDF loaded successfully.")

        elif ext == ".set":
            with mne.utils.use_log_level("WARNING"):
                raw = mne.io.read_raw_eeglab(filepath, preload=True, verbose=False)
            try:
                raw.load_data()
            except TypeError:
                pass
            app.log("EEGLAB file loaded successfully.")
        else:
            messagebox.showwarning("Unsupported File",
                                   f"Format '{ext}' not supported. Only '.bdf' and '.set' are supported.")
            return None

        if raw is None:
            raise ValueError("MNE load returned None.")

        app.log(f"Load OK: {len(raw.ch_names)} channels @ {raw.info['sfreq']:.1f} Hz.")

        # Mark EXG1/EXG2 as misc so montage doesn’t warn
        try:
            for ch in ("EXG1", "EXG2"):
                if ch in raw.ch_names:
                    raw.set_channel_types({ch: "misc"})
        except Exception:
            pass

        app.log("Applying standard_1020 montage...")
        try:
            montage = mne.channels.make_standard_montage("standard_1020")
            raw.set_montage(montage, on_missing="warn", match_case=False, verbose=False)
            app.log("Montage applied.")
        except Exception as e:
            app.log(f"Warning: Montage error: {e}")

        return raw

    except Exception as e:
        app.log(f"!!! Load Error {base}: {e}")
        messagebox.showerror("Loading Error", f"Could not load: {base}\nError: {e}")
        return None

