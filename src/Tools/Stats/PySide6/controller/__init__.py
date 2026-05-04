"""Compatibility alias for the moved Stats controller package."""
from __future__ import annotations

import sys as _sys
from Tools.Stats import controller as _impl

globals().update(_impl.__dict__)
_sys.modules[__name__] = _impl
