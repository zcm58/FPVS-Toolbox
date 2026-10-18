"""Compatibility alias for :mod:`Main_App.processing.fft_crop_utils`."""

import sys

from Main_App.processing import fft_crop_utils as _implementation

sys.modules[__name__] = _implementation
