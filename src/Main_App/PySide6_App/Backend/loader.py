# -*- coding: utf-8 -*-
"""
Data loading utilities for the FPVS Toolbox.

This module provides helper functions for reading EEG recordings into MNE,
specifically targeting `.bdf` (BioSemi) and `.set` (EEGLAB) formats.
It uses disk-backed memmaps to bound RAM usage, ensuring the application
can handle large high-density files without system instability.

Channel Management Policy:
    - Preserves user-selected EXG reference pairs as 'eeg'.
    - Demotes non-selected EXG channels to 'misc'.
    - Explicitly types the stimulus/trigger channel as 'stim'.
    - Applies a cached Standard 10-20 montage.
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path
from tkinter import messagebox
from typing import Tuple, Optional, Iterable, Dict, Set, Any

import mne


def _memmap_dir_for_pid() -> Path:
    """
    Generate a per-process directory for MNE memmap files.

    This prevents collisions between different instances of the app or
    different worker processes attempting to write to the same temporary file.

    Returns:
        Path: A platform-independent Path object pointing to the temp directory.
    """
    d = Path(tempfile.gettempdir()) / "fpvs_memmap" / f"pid_{os.getpid()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


@lru_cache(maxsize=1)
def _cached_1020() -> mne.channels.DigMontage:
    """
    Generate and cache the standard 10-20 montage.

    Returns:
        mne.channels.DigMontage: The MNE montage object for 10-20 electrode placement.
    """
    return mne.channels.make_standard_montage("standard_1020")


def _resolve_ref_pair(app: Any) -> Tuple[str, str]:
    """
    Resolve the desired reference channel pair from app settings or project state.

    The resolution follows this priority:
        1. Project-specific preprocessing settings.
        2. Global application settings.
        3. Hardcoded defaults ('EXG1', 'EXG2').

    Args:
        app: The Main Application instance containing settings and project state.

    Returns:
        Tuple[str, str]: A pair of channel labels as strings.
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

    ref1 = (
        p.get("ref_channel1")
        or p.get("ref_chan1")
        or _s("preprocessing", "ref_channel1")
        or "EXG1"
    )
    ref2 = (
        p.get("ref_channel2")
        or p.get("ref_chan2")
        or _s("preprocessing", "ref_channel2")
        or "EXG2"
    )
    return str(ref1), str(ref2)


def _resolve_stim(app: Any) -> str:
    """
    Resolve the stimulus/trigger channel name.

    Args:
        app: The Main Application instance.

    Returns:
        str: The name of the stimulus channel (defaults to 'Status').
    """
    try:
        p = getattr(app.currentProject, "preprocessing", {}) or {}
    except Exception:
        p = {}
    try:
        return p.get("stim_channel") or app.settings.get("stim", "channel", "Status") or "Status"
    except Exception:
        return "Status"


def _map_present_case_insensitive(names: Iterable[str]) -> Dict[str, str]:
    """
    Create a lookup dictionary for case-insensitive channel name matching.

    Args:
        names: An iterable of actual channel names present in the recording.

    Returns:
        Dict[str, str]: A mapping of UPPERCASE_NAME to actual_casing_name.
    """
    return {n.upper(): n for n in names}


def _canon_present(raw_names: Iterable[str], candidates: Iterable[str]) -> Set[str]:
    """
    Identify which candidate channels exist in the raw data, preserving casing.

    Args:
        raw_names: All channel names found in the MNE Raw object.
        candidates: A list of channel names to look for (e.g., ['EXG1', 'EXG2']).

    Returns:
        Set[str]: A set of correctly-cased strings for candidates found in raw_names.
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


def load_eeg_file(
    app: Any,
    filepath: str,
    ref_pair: Optional[Tuple[str, str]] = None
) -> Optional[mne.io.BaseRaw]:
    """
    Load an EEG file from disk with memory optimization and channel typing.

    This function is the primary entry point for file ingestion. It handles
    loading via MNE, implements disk-backed preloading (memmap) to save RAM,
    corrects BioSemi channel types, and applies the electrode montage.

    Args:
        app: The Main Application instance (used for logging and setting resolution).
        filepath: Absolute path to the .bdf or .set file.
        ref_pair: Optional explicit reference pair. If None, it is resolved
            automatically from project settings.

    Returns:
        Optional[mne.io.BaseRaw]: The loaded MNE Raw object, or None if the
            loading process failed or the format is unsupported.
    """
    ext = os.path.splitext(filepath)[1].lower()
    base = os.path.basename(filepath)
    app.log(f"[LOADER START] {base}: ext='{ext}'")
    try:
        memmap_dir = _memmap_dir_for_pid()
        memmap_path = str(memmap_dir / (Path(filepath).stem + "_raw.dat"))

        stim_name = _resolve_stim(app)
        if not ref_pair:
            ref_pair = _resolve_ref_pair(app)

        app.log(
            f"[LOADER DEBUG] {base}: stim='{stim_name}' "
            f"ref_pair={ref_pair} memmap_path='{memmap_path}'"
        )

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

        app.log(
            f"Load OK: {len(raw.ch_names)} channels @ {raw.info['sfreq']:.1f} Hz."
        )

        # Channel typing policy for BioSemi EXG* and stim (Policy A):
        # - Preserve the selected reference pair as EEG so set_eeg_reference can use them.
        # - Demote all other EXG1..EXG8 to 'misc' to avoid accidental inclusion.
        # - Ensure stim channel is typed as 'stim'.
        try:
            # Canonicalize ref pair to actual names present in raw
            ref_keep = _canon_present(raw.ch_names, ref_pair or ())
            exg_labels = [f"EXG{i}" for i in range(1, 9)]
            exg_present = _canon_present(raw.ch_names, exg_labels)

            app.log(
                f"[LOADER DEBUG] {base}: exg_present={sorted(exg_present)} "
                f"ref_keep={sorted(ref_keep)}"
            )

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
            app.log(
                f"EXG policy A applied. Keep as EEG: {kept} | Demoted to misc: {demoted}"
            )
        except Exception as e:
            app.log(f"Warning: EXG/stim typing adjustment failed: {e}")

        # Apply standard 10-20 montage to EEG channels only; EXG* are not in the montage.
        app.log("Applying standard_1020 montage...")
        try:
            raw.set_montage(_cached_1020(), on_missing="warn", match_case=False, verbose=False)
            app.log("Montage applied.")
        except Exception as e:
            app.log(f"Warning: Montage error: {e}")

        app.log(f"[LOADER END] {base}")
        return raw

    except Exception as e:
        app.log(f"!!! Load Error {base}: {e}")
        try:
            messagebox.showerror("Loading Error", f"Could not load: {base}\nError: {e}")
        except Exception:
            pass
        return None