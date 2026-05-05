"""Import surface for projects-root settings helpers."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.config import projects_root as _impl

sys.modules[__name__] = _impl
