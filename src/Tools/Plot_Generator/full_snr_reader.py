"""Compatibility alias for the canonical spectral workbook reader."""

import sys

from Main_App.io import spectral_workbook as _implementation

sys.modules[__name__] = _implementation
