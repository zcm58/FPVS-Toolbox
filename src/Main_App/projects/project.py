"""Import surface for the Main App project model."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.Backend import project as _impl

sys.modules[__name__] = _impl
