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
    spec = importlib.util.spec_from_file_location("summary_utils_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


summary_utils = _load_summary_utils_module()
_summarize_posthocs = summary_utils._summarize_posthocs
SummaryConfig = summary_utils.SummaryConfig


def test_posthoc_summary_includes_both_directions_when_significant():
    posthoc_df = pd.DataFrame(
        {
            "Direction": ["roi_within_condition", "condition_within_roi"],
            "Condition": ["Face", "Face"],
            "ROI": ["ROI1", "ROI1"],
            "Level_A": ["ROI_A", "Cond_A"],
            "Level_B": ["ROI_B", "Cond_B"],
            "mean_diff": [0.3, -0.2],
            "cohens_dz": [0.9, -0.7],
            "p_fdr": [0.01, 0.02],
            "Significant": [True, True],
        }
    )

    lines = _summarize_posthocs(posthoc_df, None, SummaryConfig())
    summary = "\n".join(lines)

    assert "[roi_within_condition]" in summary
    assert "[condition_within_roi]" in summary
    assert "Condition Face [roi_within_condition]" in summary
    assert "ROI ROI1 [condition_within_roi]" in summary


def test_posthoc_summary_reports_none_found_for_empty_direction():
    posthoc_df = pd.DataFrame(
        {
            "Direction": ["roi_within_condition"],
            "Condition": ["Face"],
            "ROI": ["ROI1"],
            "Level_A": ["ROI_A"],
            "Level_B": ["ROI_B"],
            "mean_diff": [0.3],
            "cohens_dz": [0.9],
            "p_fdr": [0.01],
            "Significant": [True],
        }
    )

    lines = _summarize_posthocs(posthoc_df, None, SummaryConfig())
    summary = "\n".join(lines)

    assert "Condition Face [roi_within_condition]" in summary
    assert "[condition_within_roi] No significant differences found for this direction." in summary
