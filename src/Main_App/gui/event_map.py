"""Import surface for event-map GUI helpers."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.GUI import event_map as _impl

sys.modules[__name__] = _impl
