"""Import surface for GUI update checks."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.GUI import update_manager as _impl

sys.modules[__name__] = _impl
