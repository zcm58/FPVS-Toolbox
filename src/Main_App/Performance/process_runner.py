"""Compatibility alias for :mod:`Main_App.workers.process_runner`."""

import sys

from Main_App.workers import process_runner as _implementation

sys.modules[__name__] = _implementation
