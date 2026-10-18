"""Compatibility alias for :mod:`Main_App.workers.processing_mixin`."""

import sys

from Main_App.workers import processing_mixin as _implementation

sys.modules[__name__] = _implementation
