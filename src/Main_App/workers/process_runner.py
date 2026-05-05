"""Import surface for process-based project runner code."""

from __future__ import annotations

import sys

from Main_App.Performance import process_runner as _impl

sys.modules[__name__] = _impl
