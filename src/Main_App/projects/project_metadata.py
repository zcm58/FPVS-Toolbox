"""Import surface for project metadata scanning."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.Backend import project_metadata as _impl

sys.modules[__name__] = _impl
