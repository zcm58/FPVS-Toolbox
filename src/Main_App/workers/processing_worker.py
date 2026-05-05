"""Import surface for post-processing Qt worker code."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.workers import processing_worker as _impl

sys.modules[__name__] = _impl
