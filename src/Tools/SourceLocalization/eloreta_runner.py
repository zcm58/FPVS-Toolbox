# src/Tools/SourceLocalization/eloreta_runner.py
"""Compatibility wrapper for the legacy ``eloreta_runner`` module."""

from __future__ import annotations

import os
from importlib.util import spec_from_file_location, module_from_spec

_runner_path = os.path.join(os.path.dirname(__file__), "runner.py")
_spec = spec_from_file_location("SourceLocalization.runner", _runner_path)
if _spec is None or _spec.loader is None:  # safety guard
    raise ImportError(f"Cannot load runner module from {_runner_path}")

_runner = module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_runner)  # type: ignore[union-attr]

# Re-export public names
__all__ = [name for name in vars(_runner).keys() if not name.startswith("__")]
for name in __all__:
    globals()[name] = getattr(_runner, name)
