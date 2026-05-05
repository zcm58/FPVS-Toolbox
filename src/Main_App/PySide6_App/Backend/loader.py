# -*- coding: utf-8 -*-
"""Compatibility wrapper for the canonical shared BDF loader.

The implementation lives in :mod:`Main_App.Shared.load_utils`.
Keep this module thin while stale PySide6 backend imports migrate away.
"""

from Main_App.Shared.load_utils import (  # noqa: F401
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
