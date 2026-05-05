"""Compatibility-free import surface for active EEG loading.

The implementation remains in ``Main_App.Shared.load_utils`` during this layout
slice so the BDF loader contract and path behavior stay unchanged.
"""

from Main_App.Shared.load_utils import (
    _cached_1010,
    _cached_1020,
    _canon_present,
    _emit_reader_warnings,
    _map_present_case_insensitive,
    _memmap_dir_for_pid,
    _resolve_ref_pair,
    _resolve_stim,
    _try_warning_log,
    load_eeg_file,
)

__all__ = [
    "_cached_1010",
    "_cached_1020",
    "_canon_present",
    "_emit_reader_warnings",
    "_map_present_case_insensitive",
    "_memmap_dir_for_pid",
    "_resolve_ref_pair",
    "_resolve_stim",
    "_try_warning_log",
    "load_eeg_file",
]
