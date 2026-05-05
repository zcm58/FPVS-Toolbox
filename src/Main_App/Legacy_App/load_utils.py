"""Compatibility wrapper for shared EEG loading helpers.

The implementation lives in :mod:`Main_App.Shared.load_utils`.
Keep this module thin while stale callers migrate away from ``Legacy_App``.
"""

from Main_App.Shared.load_utils import (  # noqa: F401
    _cached_1010,
    _cached_1020,
    _canon_present,
    _map_present_case_insensitive,
    _memmap_dir_for_pid,
    _resolve_ref_pair,
    _resolve_stim,
    load_eeg_file,
)
