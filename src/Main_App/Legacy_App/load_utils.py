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

    """Load an EEG file and apply the standard montage.


    Parameters
    ----------
    app : object
        Application or object providing a ``log`` method for status messages.
    filepath : str
        Path to the EEG data file.

    Returns
    -------
    mne.io.Raw | None
        The loaded Raw object on success, otherwise ``None``.
    """
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
                    preload=memmap_path,
                    stim_channel="Status",
                    verbose=False,
                )
            drop_pre = [ch for ch in ("EXG3", "EXG4", "EXG5", "EXG6", "EXG7", "EXG8") if ch in raw.ch_names]
            if drop_pre:
                raw.drop_channels(drop_pre)
            raw.load_data(dtype=np.float32)
            app.log("BDF loaded successfully.")

        elif ext == ".set":
            with mne.utils.use_log_level("WARNING"):
                raw = mne.io.read_raw_eeglab(filepath, preload=True, verbose=False)
            app.log("EEGLAB file loaded successfully.")

        else:
            messagebox.showwarning(
                "Unsupported File",
                f"Format '{ext}' not supported. Only '.bdf' files are supported.",
            )
            return None

        if raw is None:
            raise ValueError("MNE load returned None.")

        app.log(f"Load OK: {len(raw.ch_names)} channels @ {raw.info['sfreq']:.1f} Hz.")
        app.log("Applying standard_1020 montage...")
        try:
            montage = mne.channels.make_standard_montage('standard_1020')
            raw.set_montage(montage, on_missing='warn', match_case=False, verbose=False)
            app.log("Montage applied.")
        except Exception as e:
            app.log(f"Warning: Montage error: {e}")
        return raw
    except Exception as e:
        app.log(f"!!! Load Error {base}: {e}")
        messagebox.showerror("Loading Error", f"Could not load: {base}\nError: {e}")
        return None
