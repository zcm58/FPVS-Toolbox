"""Compatibility wrapper for :mod:`Main_App.gui.ui_main`."""

from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module("Main_App.gui.ui_main")

sys.modules[__name__] = _impl
