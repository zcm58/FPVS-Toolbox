"""Import surface for multiprocessing environment helpers."""

from __future__ import annotations

import sys

from Main_App.Performance import mp_env as _impl

sys.modules[__name__] = _impl
