"""Helper functions for reading EEG recordings into MNE.

Supports ``.bdf`` and ``.set``. Uses disk-backed memmaps to bound RAM usage and
applies a cached standard_1020 montage. Numerical output is unchanged.

Update: preserve the user-selected EXG reference pair as EEG, demote only the
non-selected EXG* channels to misc, and type the stim channel explicitly.

This is a clone of the legacy load_utils.py file. We're cloning this file here so
we can move away from a dependency on the Legacy_App directory and streamline development.
"""
from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from tkinter import messagebox
from typing import Tuple, Optional, Iterable, Dict, Set

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


def _resolve_ref_pair(app) -> Tuple[str, str]:
    """
    Resolve the desired reference pair in priority:
      project.preprocessing.{ref_channel1|ref_chan1, ref_channel2|ref_chan2}
      → settings['preprocessing'] → defaults ('EXG1','EXG2').
    Returns raw channel labels as strings (case preserved from inputs).
    """
    try:
        p = getattr(app.currentProject, "preprocessing", {}) or {}
    except Exception:
        p = {}

    def _s(section: str, key: str, default=None):
        try:
            return app.settings.get(section, key, default)
        except Exception:
            return default

    ref1 = p.get("ref_channel1") or p.get("ref_chan1") or _s("preprocessing", "ref_channel1") or "EXG1"
    ref2 = p.get("ref_channel2") or p.get("ref_chan2") or _s("preprocessing", "ref_channel2") or "EXG2"
    return str(ref1), str(ref2)


def _resolve_stim(app) -> str:
    """Resolve the stim channel name. Defaults to 'Status'."""
    try:
        p = getattr(app.currentProject, "preprocessing", {}) or {}
    except Exception:
        p = {}
    try:
        return p.get("stim_channel") or app.settings.get("stim", "channel", "Status") or "Status"
    except Exception:
        return "Status"


def _map_present_case_insensitive(names: Iterable[str]) -> Dict[str, str]:
    """Build a case-insensitive lookup: UPPER -> actual name present."""
    return {n.upper(): n for n in names}


def _canon_present(raw_names: Iterable[str], candidates: Iterable[str]) -> Set[str]:
    """
    Return the subset of candidates that are present in raw_names,
    matching case-insensitively but returning the actual casing from raw_names.
    """
    lut = _map_present_case_insensitive(raw_names)
    out: Set[str] = set()
    for c in candidates:
        if not isinstance(c, str):
            continue
        k = c.upper()
        if k in lut:
            out.add(lut[k])
    return out


def load_eeg_file(app, filepath: str, ref_pair: Optional[Tuple[str, str]] = None):
    """
    Load an EEG file with disk-backed memmap and apply montage (no resample).

    ref_pair:
      Optional explicit pair to preserve as EEG for initial referencing.
      If not provided, resolved from project/settings with defaults EXG1/EXG2.
    """
    ext = os.path.splitext(filepath)[1].lower()
    base = os.path.basename(filepath)
    app.log(f"Loading: {base}...")
    try:
        memmap_dir = _memmap_dir_for_pid()
        memmap_path = str(memmap_dir / (Path(filepath).stem + "_raw.dat"))

        stim_name = _resolve_stim(app)
        if not ref_pair:
            ref_pair = _resolve_ref_pair(app)

        if ext == ".bdf":
            with mne.utils.use_log_level("WARNING"):
                raw = mne.io.read_raw_bdf(
                    filepath,
                    preload=memmap_path,          # disk-backed; safe for big filters
                    stim_channel=stim_name if stim_name else "Status",
                    verbose=False,
                )
            # Do NOT drop EXG channels here. We may need EXG3/EXG4, etc. for referencing.
            raw.load_data()  # ensures the memmap is materialized
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

        # Channel typing policy for BioSemi EXG* and stim (Policy A):
        # - Preserve the selected reference pair as EEG so set_eeg_reference can use them.
        # - Demote all other EXG1..EXG8 to 'misc' to avoid accidental inclusion.
        # - Ensure stim channel is typed as 'stim'.
        try:
            # Canonicalize ref pair to actual names present in raw
            ref_keep = _canon_present(raw.ch_names, ref_pair or ())
            exg_labels = [f"EXG{i}" for i in range(1, 9)]
            exg_present = _canon_present(raw.ch_names, exg_labels)

            to_misc = {ch: "misc" for ch in exg_present if ch not in ref_keep}
            to_eeg = {ch: "eeg" for ch in ref_keep}

            # Apply in two stages to avoid conflicts
            if to_misc:
                raw.set_channel_types(to_misc)
            if to_eeg:
                raw.set_channel_types(to_eeg)
            if stim_name in raw.ch_names:
                raw.set_channel_types({stim_name: "stim"})

            kept = sorted(ref_keep)
            demoted = sorted([ch for ch in exg_present if ch not in ref_keep])
            app.log(f"EXG policy A applied. Keep as EEG: {kept} | Demoted to misc: {demoted}")
        except Exception as e:
            app.log(f"Warning: EXG/stim typing adjustment failed: {e}")

        # Apply standard 10-20 montage to EEG channels only; EXG* are not in the montage.
        app.log("Applying standard_1020 montage...")
        try:
            raw.set_montage(_cached_1020(), on_missing="warn", match_case=False, verbose=False)
            app.log("Montage applied.")
        except Exception as e:
            app.log(f"Warning: Montage error: {e}")

        return raw

    except Exception as e:
        app.log(f"!!! Load Error {base}: {e}")
        try:
            messagebox.showerror("Loading Error", f"Could not load: {base}\nError: {e}")
        except Exception:
            pass
        return None
