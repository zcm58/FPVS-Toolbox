"""Import surface for settings-panel GUI helpers."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.GUI import settings_panel as _impl

sys.modules[__name__] = _impl
