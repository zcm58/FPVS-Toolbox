"""Import surface for the Qt multiprocessing runner bridge."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.workers import mp_runner_bridge as _impl

sys.modules[__name__] = _impl
