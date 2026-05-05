"""Import surface for project manager workflows."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.Backend import project_manager as _impl

sys.modules[__name__] = _impl
