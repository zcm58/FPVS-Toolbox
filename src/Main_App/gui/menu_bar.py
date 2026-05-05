"""Import surface for menu-bar GUI helpers."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.GUI import menu_bar as _impl

sys.modules[__name__] = _impl
