"""Compatibility wrapper for FFT crop helpers.

The implementation lives in :mod:`Main_App.Shared.fft_crop_utils`.
Keep this module thin while callers migrate away from ``Legacy_App``.
"""

from Main_App.Shared.fft_crop_utils import (  # noqa: F401
    CropResult,
    ODDBALL_FREQ,
    compute_fft_crop_from_events,
    compute_onbin_N,
    compute_onbin_step,
)
