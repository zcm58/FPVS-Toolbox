"""Compatibility wrapper for the legacy stats_file_scanner module."""

from __future__ import annotations

import importlib.util
import os
from types import ModuleType

_path = os.path.join(os.path.dirname(__file__), "Legacy", "stats_file_scanner.py")
_spec = importlib.util.spec_from_file_location("_legacy_stats_file_scanner", _path)
_legacy_module: ModuleType = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_legacy_module)

# Export all public names from the legacy module
__all__ = [name for name in dir(_legacy_module) if not name.startswith("_")]
for name in __all__:
    globals()[name] = getattr(_legacy_module, name)
