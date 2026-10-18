"""Compatibility alias for :mod:`Main_App.io.load_utils`."""

import sys

from Main_App.io import load_utils as _implementation

sys.modules[__name__] = _implementation
