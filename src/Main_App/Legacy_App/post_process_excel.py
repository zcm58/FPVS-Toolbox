"""Compatibility wrapper for post-processing workbook helpers.

The implementation lives in :mod:`Main_App.Shared.post_process_excel`.
Keep this module thin while stale callers migrate away from ``Legacy_App``.
"""

from Main_App.Shared.post_process_excel import (  # noqa: F401
    NEIGHBOR_OFFSETS,
    build_fft_neighbors_rows,
    write_results_workbook,
)
