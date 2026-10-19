"""Compatibility alias for :mod:`Main_App.workers.mp_env`."""

import sys

from Main_App.workers import mp_env as _implementation

sys.modules[__name__] = _implementation
