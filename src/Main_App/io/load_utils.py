"""Compatibility-free import surface for active EEG loading.

Production BioSemi loading remains in ``Main_App.Shared.load_utils`` during
this layout slice. Explicit Unicorn inspection and context-owned Raw reading
are additive entry points; neither releases Unicorn for scientific processing.
"""

from Main_App.Shared.load_utils import (
    BDF_RECORDING_NOT_STARTED_REASON,
    BdfPreflightInfo,
    _cached_1010,
    _cached_1020,
    _canon_present,
    _emit_reader_warnings,
    format_bdf_recording_not_started_message,
    inspect_bdf_header,
    is_bdf_recording_not_started,
    _map_present_case_insensitive,
    _memmap_dir_for_pid,
    _resolve_ref_pair,
    _resolve_electrode_mapping_profile,
    _resolve_electrode_montage,
    _resolve_stim,
    _try_warning_log,
    load_eeg_file,
    open_preflight_eeg_file,
)
from Main_App.io.recording_inspection import inspect_eeg_recording
from Main_App.io.unicorn_raw import open_unicorn_recording_raw

__all__ = [
    "BDF_RECORDING_NOT_STARTED_REASON",
    "BdfPreflightInfo",
    "_cached_1010",
    "_cached_1020",
    "_canon_present",
    "_emit_reader_warnings",
    "format_bdf_recording_not_started_message",
    "inspect_bdf_header",
    "inspect_eeg_recording",
    "is_bdf_recording_not_started",
    "_map_present_case_insensitive",
    "_memmap_dir_for_pid",
    "_resolve_ref_pair",
    "_resolve_electrode_mapping_profile",
    "_resolve_electrode_montage",
    "_resolve_stim",
    "_try_warning_log",
    "load_eeg_file",
    "open_preflight_eeg_file",
    "open_unicorn_recording_raw",
]
