from datetime import datetime
import importlib.util
from pathlib import Path
import sys

import pandas as pd


def _load_reporting_module():
    module_path = Path(__file__).resolve().parents[1] / "src" / "Tools" / "Stats" / "PySide6" / "reporting_summary.py"
    spec = importlib.util.spec_from_file_location("reporting_summary", module_path)
    if spec is None or spec.loader is None:
        raise ImportError("Failed to load reporting_summary module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


REPORTING_MODULE = _load_reporting_module()
ReportingSummaryContext = REPORTING_MODULE.ReportingSummaryContext
build_reporting_summary = REPORTING_MODULE.build_reporting_summary


def test_reporting_summary_includes_posthoc_direction_and_slice_labels():
    context = ReportingSummaryContext(
        project_name="Demo",
        project_root=Path("/tmp/demo"),
        pipeline_name="Single",
        generated_local=datetime(2025, 1, 1, 12, 0, 0),
        elapsed_ms=1234,
        timezone_label="UTC",
        total_participants=6,
        included_participants=["S1", "S2", "S3", "S4", "S5", "S6"],
        excluded_reasons={},
        selected_conditions=["C1", "C2"],
        selected_rois=["R1", "R2", "R3"],
    )
    posthoc_df = pd.DataFrame(
        [
            {
                "Direction": "condition_within_roi",
                "Slice": "R1",
                "Factor": "condition",
                "Level_A": "C1",
                "Level_B": "C2",
                "mean_diff": 1.2,
                "t_statistic": 3.4,
                "p_value": 0.02,
                "p_fdr_bh": 0.03,
            },
            {
                "Direction": "roi_within_condition",
                "Slice": "C1",
                "Factor": "roi",
                "Level_A": "R1",
                "Level_B": "R2",
                "mean_diff": -0.8,
                "t_statistic": -2.9,
                "p_value": 0.04,
                "p_fdr_bh": 0.05,
            },
        ]
    )

    summary = build_reporting_summary(
        context,
        anova_df=None,
        lmm_df=None,
        posthoc_df=posthoc_df,
    )

    assert "Conditions within ROI rows: 1" in summary
    assert "ROIs within condition rows: 1" in summary
    assert "[condition_within_roi] slice=R1 factor=condition" in summary
    assert "[roi_within_condition] slice=C1 factor=roi" in summary
