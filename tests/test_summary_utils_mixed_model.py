from enum import Enum, auto
import importlib.util
from pathlib import Path
import sys
import types

import pandas as pd


class _PipelineId(Enum):
    SINGLE = auto()
    BETWEEN = auto()


def _load_summary_utils_module():
    stats_core_stub = types.ModuleType("Tools.Stats.PySide6.stats_core")
    stats_core_stub.ANOVA_BETWEEN_XLS = "Mixed ANOVA Between Groups.xlsx"
    stats_core_stub.ANOVA_XLS = "RM-ANOVA Results.xlsx"
    stats_core_stub.GROUP_CONTRAST_XLS = "Group Contrasts.xlsx"
    stats_core_stub.LMM_BETWEEN_XLS = "Mixed Model Between Groups.xlsx"
    stats_core_stub.LMM_XLS = "Mixed Model Results.xlsx"
    stats_core_stub.POSTHOC_XLS = "Posthoc Results.xlsx"
    stats_core_stub.PipelineId = _PipelineId
    sys.modules["Tools.Stats.PySide6.stats_core"] = stats_core_stub

    module_path = Path("src/Tools/Stats/PySide6/summary_utils.py")
    spec = importlib.util.spec_from_file_location("summary_utils_mixed_model_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


summary_utils = _load_summary_utils_module()
StatsSummaryFrames = summary_utils.StatsSummaryFrames
SummaryConfig = summary_utils.SummaryConfig
build_summary_from_frames = summary_utils.build_summary_from_frames
format_mixed_model_plain_language = summary_utils.format_mixed_model_plain_language
_format_p_value = summary_utils._format_p_value


def test_mixed_model_summary_populates_when_terms_present():
    df = pd.DataFrame({
        "Effect": ["Intercept", "C(condition, Sum)[S.Test Condition]"],
        "P>|z|": [0.01, 0.2],
        "Estimate": [1.2, -0.5],
    })

    frames = StatsSummaryFrames(mixed_model_terms=df)
    summary = build_summary_from_frames(frames, SummaryConfig())

    assert "Overall response present" in summary
    assert "no summary is available" not in summary


def test_lmm_summary_includes_intercept_and_mains():
    lmm_df = pd.DataFrame({
        "Effect (raw)": [
            "Intercept",
            "C(condition, Sum)[S.Face]",
            "C(roi, Sum)[S.Occipital]",
            "C(condition, Sum)[S.Face]:C(roi, Sum)[S.Occipital]",
        ],
        "Coef.": [1.1, -0.3, 0.4, 0.2],
        "P>|z|": [1.2e-24, 0.0049, 0.03, 7.91e-08],
    })

    lines = format_mixed_model_plain_language(lmm_df, alpha=0.05)
    summary = "\n".join(lines)

    assert "Overall response present" in summary
    assert "Condition difference" in summary
    assert "ROI difference" in summary
    assert "Condition-by-ROI interaction" in summary


def test_fmt_p_scientific_under_0_001():
    assert "e-" in _format_p_value(1.2e-24)
    assert _format_p_value(0.0049) == "0.0049"


def test_no_summary_when_missing_df():
    frames = StatsSummaryFrames(mixed_model_terms=None)
    summary = build_summary_from_frames(frames, SummaryConfig())

    assert "NOT AVAILABLE" in summary
    assert "Wald z-tests" not in summary
