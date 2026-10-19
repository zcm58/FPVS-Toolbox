"""Compatibility alias for :mod:`Main_App.processing.roi_presets`."""

import sys

from Main_App.processing import roi_presets as _implementation

sys.modules[__name__] = _implementation
