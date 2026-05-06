"""Compatibility wrapper for :mod:`Main_App.processing.processing_controller`."""

from Main_App.processing.processing_controller import (
    RawFileInfo,
    _animate_progress_to,
    discover_raw_files,
    prepare_batch_files,
    start_processing,
)

__all__ = [
    "RawFileInfo",
    "_animate_progress_to",
    "discover_raw_files",
    "prepare_batch_files",
    "start_processing",
]
