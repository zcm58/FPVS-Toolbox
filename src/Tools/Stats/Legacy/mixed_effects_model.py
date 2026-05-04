"""Compatibility alias for the moved Stats module."""
from __future__ import annotations

import sys as _sys
import importlib as _importlib

_impl = _importlib.import_module("Tools.Stats.analysis.mixed_effects_model")
globals().update(_impl.__dict__)
_sys.modules[__name__] = _impl