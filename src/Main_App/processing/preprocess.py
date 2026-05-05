"""Compatibility-free import surface for active EEG preprocessing.

The implementation remains in the PySide6 backend during this layout slice so
the preprocessing math and pipeline order stay unchanged.
"""

from Main_App.PySide6_App.Backend.preprocess import (
    begin_preproc_audit,
    finalize_preproc_audit,
    perform_preprocessing,
)

__all__ = [
    "begin_preproc_audit",
    "finalize_preproc_audit",
    "perform_preprocessing",
]
