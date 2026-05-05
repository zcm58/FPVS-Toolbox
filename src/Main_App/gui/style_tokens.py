"""Import surface for GUI style tokens."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.GUI import style_tokens as _impl

sys.modules[__name__] = _impl
