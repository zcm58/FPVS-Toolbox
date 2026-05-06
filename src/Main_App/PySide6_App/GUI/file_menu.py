"""Compatibility wrapper for :mod:`Main_App.gui.file_menu`."""

from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module("Main_App.gui.file_menu")

sys.modules[__name__] = _impl
