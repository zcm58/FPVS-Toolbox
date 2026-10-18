"""Compatibility alias for :mod:`Main_App.io.file_filters`."""

import sys

from Main_App.io import file_filters as _implementation

sys.modules[__name__] = _implementation
