"""Compatibility alias for the moved Stats module."""
from __future__ import annotations

import sys as _sys
from Tools.Stats.PySide6.ui import stats_window_actions as _impl

globals().update(_impl.__dict__)
_sys.modules[__name__] = _impl
