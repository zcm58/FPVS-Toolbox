# -*- coding: utf-8 -*-
"""
Processing entry point used by the PySide6 GUI.

For now, this is a *thin orchestrator* (no-op) that exists so the GUI
can call a stable function. It accepts a preprocessed Raw and an output
directory, and can later be expanded to run epoching/LORETA, etc.
"""

from __future__ import annotations
from typing import Optional

import mne


def process_data(raw: Optional[mne.io.BaseRaw], output_dir: str, run_loreta: bool) -> None:
    """
    Parameters
    ----------
    raw : mne.io.BaseRaw | None
        Already preprocessed Raw. (Currently unused.)
    output_dir : str
        Destination directory for processed results.
    run_loreta : bool
        Whether to run LORETA source localization (reserved for future hook).
    """
    # Placeholder: keep for compatibility; real work is handled elsewhere.
    return
