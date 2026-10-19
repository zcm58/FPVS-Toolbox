"""Compatibility alias for :mod:`Main_App.exports.post_process_excel`."""

import sys

from Main_App.exports import post_process_excel as _implementation

sys.modules[__name__] = _implementation
