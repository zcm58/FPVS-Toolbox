"""Compatibility alias for :mod:`Main_App.io.resource_paths`."""

import sys

from Main_App.io import resource_paths as _implementation

sys.modules[__name__] = _implementation
