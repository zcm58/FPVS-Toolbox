"""Compatibility alias for :mod:`Main_App.settings.settings_manager`."""

import sys

from Main_App.settings import settings_manager as _implementation

sys.modules[__name__] = _implementation
