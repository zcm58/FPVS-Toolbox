"""Import surface for project preprocessing settings normalization."""

from __future__ import annotations

import sys

from Main_App.PySide6_App.Backend import preprocessing_settings as _impl

sys.modules[__name__] = _impl
