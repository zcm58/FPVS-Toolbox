"""Import surface for generated/main UI assembly helpers."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.GUI import ui_main as _impl

sys.modules[__name__] = _impl
