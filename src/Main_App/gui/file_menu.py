"""Import surface for file-menu GUI helpers."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.GUI import file_menu as _impl

sys.modules[__name__] = _impl
