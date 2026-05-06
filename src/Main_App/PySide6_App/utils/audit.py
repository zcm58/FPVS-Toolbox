"""Compatibility wrapper for :mod:`Main_App.diagnostics.audit`."""

from __future__ import annotations

import sys
from importlib import import_module

_impl = import_module("Main_App.diagnostics.audit")

sys.modules[__name__] = _impl
