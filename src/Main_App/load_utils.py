"""Helper functions for reading EEG recordings into MNE.
Supported ``.bdf`` and ``.set`` files are loaded with the
appropriate options, and warnings are shown for unsupported
formats."""

import os
from tkinter import messagebox

import mne


def load_eeg_file(app, filepath):
    """Load an EEG file (.bdf or .set) and apply the standard montage.

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
        kwargs = {"preload": True, "verbose": False}
        if ext == ".bdf":
            with mne.utils.use_log_level('WARNING'):
                raw = mne.io.read_raw_bdf(filepath, **kwargs)
            app.log("BDF loaded successfully.")
        elif ext == ".set":
            with mne.utils.use_log_level('WARNING'):
                raw = mne.io.read_raw_eeglab(filepath, **kwargs)
            app.log("SET loaded successfully.")
        else:
            messagebox.showwarning("Unsupported File", f"Format '{ext}' not supported.")
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
