"""Compatibility alias for :mod:`Main_App.gui.user_messages`."""

import sys

from Main_App.gui import user_messages as _implementation

sys.modules[__name__] = _implementation
