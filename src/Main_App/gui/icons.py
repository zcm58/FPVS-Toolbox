"""Import surface for GUI icon helpers."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.GUI import icons as _impl

sys.modules[__name__] = _impl
