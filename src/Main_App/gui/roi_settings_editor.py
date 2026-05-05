"""Import surface for ROI settings editor widgets."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.GUI import roi_settings_editor as _impl

sys.modules[__name__] = _impl
