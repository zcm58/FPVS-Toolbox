"""Average preprocessing tool exports."""

from __future__ import annotations

import os

if os.getenv("FPVS_TEST_MODE") or os.getenv("PYTEST_CURRENT_TEST"):
    AdvancedAnalysisWindow = None
    run_advanced_averaging_processing = None
    __all__ = []
else:
    from Tools.Average_Preprocessing.Legacy.advanced_analysis import AdvancedAnalysisWindow
    from Tools.Average_Preprocessing.Legacy.advanced_analysis_core import run_advanced_averaging_processing

    __all__ = [
        "AdvancedAnalysisWindow",
        "run_advanced_averaging_processing",
    ]
