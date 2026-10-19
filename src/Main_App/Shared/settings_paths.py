"""Compatibility alias for :mod:`Main_App.settings.settings_paths`."""

import sys

from Main_App.settings import settings_paths as _implementation

sys.modules[__name__] = _implementation
