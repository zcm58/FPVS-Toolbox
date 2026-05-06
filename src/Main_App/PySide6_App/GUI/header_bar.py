"""Compatibility wrapper for :mod:`Main_App.gui.header_bar`."""

from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module("Main_App.gui.header_bar")

sys.modules[__name__] = _impl
