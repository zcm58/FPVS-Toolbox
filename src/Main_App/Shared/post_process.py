"""Compatibility alias for :mod:`Main_App.exports.post_process`."""

import sys

from Main_App.exports import post_process as _implementation

sys.modules[__name__] = _implementation
