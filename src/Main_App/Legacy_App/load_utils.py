"""Helper functions for reading EEG recordings into MNE.

Supports ``.bdf`` and ``.set``. Uses disk-backed memmaps to bound RAM usage and
applies a cached standard_1020 montage. Numerical output is unchanged.
"""
from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from tkinter import messagebox

import mne


def _memmap_dir_for_pid() -> Path:
    """Per-process memmap directory to avoid worker collisions."""
    d = Path(tempfile.gettempdir()) / "fpvs_memmap" / f"pid_{os.getpid()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


@lru_cache(maxsize=1)
def _cached_1020():
    """Cached once per process to avoid repeated montage builds."""
    return mne.channels.make_standard_montage("standard_1020")


def load_eeg_file(app, filepath):
    """Load an EEG file with disk-backed memmap and apply montage (no resample)."""
    ext = os.path.splitext(filepath)[1].lower()
    base = os.path.basename(filepath)
    app.log(f"Loading: {base}...")
    try:
        memmap_dir = _memmap_dir_for_pid()
        memmap_path = str(memmap_dir / (Path(filepath).stem + "_raw.dat"))

        if ext == ".bdf":
            with mne.utils.use_log_level("WARNING"):
                raw = mne.io.read_raw_bdf(
                    filepath,
                    preload=memmap_path,          # disk-backed; safe for big filters
                    stim_channel="Status",
                    verbose=False,
                )
            # Drop unused EXG3–EXG8 immediately
            drop_pre = [c for c in ("EXG3", "EXG4", "EXG5", "EXG6", "EXG7", "EXG8") if c in raw.ch_names]
            if drop_pre:
                raw.drop_channels(drop_pre)
            # Ensure the memmap is materialized as preload store
            raw.load_data()  # uses the memmap path above
            app.log("BDF loaded successfully.")

        elif ext == ".set":
            # Prefer disk-backed preload if available in current MNE version
            try:
                with mne.utils.use_log_level("WARNING"):
                    raw = mne.io.read_raw_eeglab(
                        filepath,
                        preload=memmap_path,      # memmap instead of RAM (newer MNE)
                        verbose=False,
                    )
                raw.load_data()
            except TypeError:
                # Fallback for older MNE that doesn't accept a path for preload
                with mne.utils.use_log_level("WARNING"):
                    raw = mne.io.read_raw_eeglab(filepath, preload=True, verbose=False)
            app.log("EEGLAB file loaded successfully.")
        else:
            messagebox.showwarning(
                "Unsupported File",
                f"Format '{ext}' not supported. Only '.bdf' and '.set' are supported.",
            )
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
            raw.set_montage(_cached_1020(), on_missing="warn", match_case=False, verbose=False)
            app.log("Montage applied.")
        except Exception as e:
            app.log(f"Warning: Montage error: {e}")

        return raw

    except Exception as e:
        app.log(f"!!! Load Error {base}: {e}")
        messagebox.showerror("Loading Error", f"Could not load: {base}\nError: {e}")
        return None
