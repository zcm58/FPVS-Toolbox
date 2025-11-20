from __future__ import annotations

"""
Thin compatibility wrapper for stats data loading helpers.

Historically this module housed the scanning helpers that discover subjects and
conditions from the Excel data folders. The logic now lives in
``stats_data_loader`` so that it can be reused by non-Qt code. Imports remain
for backward compatibility.
"""

from Tools.Stats.PySide6.stats_data_loader import ScanError, scan_folder_simple

__all__ = ["ScanError", "scan_folder_simple"]

