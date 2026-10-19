"""Compatibility alias for :mod:`Main_App.io.eeg_geometry`."""

import sys

from Main_App.io import eeg_geometry as _implementation

sys.modules[__name__] = _implementation
