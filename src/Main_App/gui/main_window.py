"""Import surface for the Main App window."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.GUI import main_window as _impl

sys.modules[__name__] = _impl
