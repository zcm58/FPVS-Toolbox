"""Legacy data processing entry point.

This module exposes the ``process_data`` function used by the
PySide6 GUI. The original implementation resided under a
``Main_App.Processing`` package which no longer exists. The
function here provides a stub interface so that the GUI can import
it without raising ``ImportError``.
"""

from __future__ import annotations

def process_data(input_dir: str, output_dir: str, run_loreta: bool) -> None:
    """Process EEG data using the legacy pipeline.

    Parameters
    ----------
    input_dir : str
        Path to the directory containing raw data files.
    output_dir : str
        Destination directory for processed results.
    run_loreta : bool
        Whether to run LORETA source localization.
    """

    # Placeholder for the removed legacy implementation
    pass
