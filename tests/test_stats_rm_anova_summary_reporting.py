from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - lightweight test env
    pytest.skip("pandas is required for stats reporting tests", allow_module_level=True)

from Tools.Stats.PySide6.reporting.reporting_summary import ReportingSummaryContext, build_reporting_summary
from Tools.Stats.PySide6.stats_core import PipelineId
from Tools.Stats.PySide6.stats_workers import run_rm_anova
from Tools.Stats.PySide6.reporting.summary_utils import StatsSummaryFrames, SummaryConfig, build_summary_from_frames


def test_reporting_summary_anova_includes_interaction_gg_epsilon_and_sphericity_fields() -> None:
    anova_df = pd.DataFrame(
        [
            {
                "Effect": "condition",
                "Num DF": 1,
                "Den DF": 19,
                "F Value": 4.2,
                "Pr > F": 0.04,
                "Pr > F (GG)": 0.03,
                "epsilon (GG)": 0.87,
                "W (Mauchly)": 0.92,
                "p (Mauchly)": 0.11,
                "Sphericity (bool)": True,
            },
            {
                "Effect": "roi",
                "Num DF": 2,
                "Den DF": 38,
                "F Value": 5.4,
                "Pr > F": 0.01,
                "Pr > F (GG)": 0.02,
                "epsilon (GG)": 0.8,
                "W (Mauchly)": 0.9,
                "p (Mauchly)": 0.09,
                "Sphericity (bool)": True,
            },
            {
                "Effect": "condition * roi",
                "Num DF": 2,
                "Den DF": 38,
                "F Value": 8.8,
                "Pr > F": 0.004,
                "Pr > F (GG)": 0.0014,
                "epsilon (GG)": 0.72,
                "W (Mauchly)": 0.78,
                "p (Mauchly)": 0.03,
                "Sphericity (bool)": False,
            },
        ]
    )
    anova_df.attrs["rm_anova_backend"] = "pingouin"

    context = ReportingSummaryContext(
        project_name="Demo",
        project_root=Path("/tmp/demo"),
        pipeline_name=PipelineId.SINGLE.name,
        generated_local=datetime(2025, 1, 1, 12, 0, 0),
        elapsed_ms=100,
        timezone_label="UTC",
        total_participants=20,
        included_participants=[f"S{i:02d}" for i in range(1, 21)],
        excluded_reasons={},
        selected_conditions=["A", "B"],
        selected_rois=["ROI1", "ROI2"],
    )

    text = build_reporting_summary(context, anova_df=anova_df, lmm_df=None, posthoc_df=None)

    assert "- condition * roi:" in text
    assert "p_reported: 0.0014 (GG corrected)" in text
    assert "epsilon (GG): 0.72" in text
    assert "W (Mauchly): 0.78" in text
    assert "Sphericity (bool): False" in text


def test_gui_rm_anova_summary_reports_significant_interaction_using_gg_p() -> None:
    anova_df = pd.DataFrame(
        {
            "Effect": ["condition", "roi", "condition:roi"],
            "Pr > F": [0.2, 0.3, 0.08],
            "Pr > F (GG)": [0.2, 0.3, 0.0014],
        }
    )

    summary = build_summary_from_frames(
        StatsSummaryFrames(anova_terms=anova_df),
        SummaryConfig(alpha=0.05),
    )

    assert "Significant effect of condition * roi (p = 0.0014, GG corrected)." in summary


def test_between_reporting_summary_omits_rm_anova_section() -> None:
    context = ReportingSummaryContext(
        project_name="Demo",
        project_root=Path("/tmp/demo"),
        pipeline_name=PipelineId.BETWEEN.name,
        generated_local=datetime(2025, 1, 1, 12, 0, 0),
        elapsed_ms=100,
        timezone_label="UTC",
        total_participants=8,
        included_participants=[f"S{i:02d}" for i in range(1, 9)],
        excluded_reasons={},
        selected_conditions=["A", "B"],
        selected_rois=["ROI1", "ROI2"],
    )
    anova_df = pd.DataFrame([{"Effect": "group", "Pr > F": 0.01}])
    lmm_df = pd.DataFrame([{"Effect": "group", "Estimate": 0.5, "P>|z|": 0.03}])
    contrasts_df = pd.DataFrame(
        [
            {
                "group_pair": "G1 vs G2",
                "mean_diff": 0.4,
                "t_statistic": 2.1,
                "df": 10.5,
                "p_raw": 0.04,
                "p_fdr_bh": 0.05,
            }
        ]
    )

    text = build_reporting_summary(
        context,
        anova_df=anova_df,
        lmm_df=lmm_df,
        posthoc_df=contrasts_df,
    )

    assert "RM-ANOVA (REPEATED MEASURES)" not in text
    assert "GROUP CONTRASTS" in text


def test_between_reporting_summary_reads_supported_multigroup_contrast_schema() -> None:
    context = ReportingSummaryContext(
        project_name="Demo",
        project_root=Path("/tmp/demo"),
        pipeline_name=PipelineId.BETWEEN.name,
        generated_local=datetime(2025, 1, 1, 12, 0, 0),
        elapsed_ms=100,
        timezone_label="UTC",
        total_participants=8,
        included_participants=[f"P{i}" for i in range(1, 7)],
        excluded_reasons={"P7": "missing group assignment", "P8": "manual exclusion"},
        selected_conditions=["A", "B"],
        selected_rois=["ROI1", "ROI2"],
    )
    lmm_df = pd.DataFrame([{"Effect": "Intercept", "Estimate": 0.5, "P>|z|": 0.03}])
    contrasts_df = pd.DataFrame(
        [
            {
                "ROI": "Occipital",
                "Condition": "Face",
                "GroupA": "G1",
                "GroupB": "G2",
                "Estimate": 0.4,
                "TestStat": 2.1,
                "DF": 10.5,
                "P": 0.04,
                "P_corrected": 0.05,
                "Method": "fdr_bh",
            }
        ]
    )

    text = build_reporting_summary(
        context,
        anova_df=None,
        lmm_df=lmm_df,
        posthoc_df=contrasts_df,
    )

    assert "RM-ANOVA (REPEATED MEASURES)" not in text
    assert "GROUP CONTRASTS" in text
    assert "POST-HOC TESTS" not in text
    assert "Included in supported multigroup model: 6" in text
    assert "Not modeled: 2" in text
    assert "Occipital / Face: G1 vs G2" in text
    assert "p_adj=0.05" in text


def test_rm_anova_text_report_exports_to_results_dir_used_by_stats_outputs(tmp_path: Path, monkeypatch) -> None:
    messages: list[str] = []
    results_dir = tmp_path / "3 - Statistical Analysis"

    monkeypatch.setattr("Tools.Stats.PySide6.stats_workers.set_rois", lambda _rois: None)
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers._apply_qc_screening",
        lambda **kwargs: (kwargs["subjects"], kwargs["subject_data"], None, None),
    )
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers._apply_manual_exclusions",
        lambda **kwargs: (kwargs["subjects"], kwargs["subject_data"], None, []),
    )
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers.prepare_summed_bca_data",
        lambda **kwargs: {"S1": {"A": {"ROI1": 1.0}, "B": {"ROI1": 2.0}}},
    )
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers._long_format_from_bca",
        lambda _data: pd.DataFrame(
            [
                {"subject": "S1", "condition": "A", "roi": "ROI1", "value": 1.0},
                {"subject": "S1", "condition": "B", "roi": "ROI1", "value": 2.0},
            ]
        ),
    )
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers._apply_outlier_exclusion",
        lambda df, **kwargs: (df, None),
    )
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers.merge_exclusion_reports",
        lambda a, b: None,
    )
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers._extract_required_exclusions",
        lambda _report: [],
    )
    monkeypatch.setattr("Tools.Stats.PySide6.stats_workers._diag_subject_data_structure", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers.analysis_run_rm_anova",
        lambda *args, **kwargs: (
            "ok",
            pd.DataFrame(
                [
                    {
                        "Effect": "condition * roi",
                        "F Value": 7.0,
                        "Num DF": 1,
                        "Den DF": 1,
                        "Pr > F": 0.01,
                        "Pr > F (GG)": 0.0014,
                    }
                ]
            ),
        ),
    )

    run_rm_anova(
        lambda _progress: None,
        messages.append,
        subjects=["S1"],
        conditions=["A", "B"],
        conditions_all=["A", "B"],
        subject_data={"S1": {"A": {"ROI1": 1.0}, "B": {"ROI1": 2.0}}},
        base_freq=6.0,
        rois={"ROI1": ["O1"]},
        rois_all={"ROI1": ["O1"]},
        results_dir=str(results_dir),
    )

    exported = list(results_dir.glob("RM_ANOVA_Report_*.txt"))
    assert len(exported) == 1
    assert any("RM-ANOVA text report exported:" in msg for msg in messages)


def test_single_file_rm_anova_still_excludes_required_nonfinite_subjects(monkeypatch) -> None:
    seen: dict[str, object] = {}

    monkeypatch.setattr("Tools.Stats.PySide6.stats_workers.set_rois", lambda _rois: None)
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers._apply_qc_screening",
        lambda **kwargs: (kwargs["subjects"], kwargs["subject_data"], None, None),
    )
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers._apply_manual_exclusions",
        lambda **kwargs: (kwargs["subjects"], kwargs["subject_data"], None, []),
    )
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers.prepare_summed_bca_data",
        lambda **kwargs: {"P1": {"A": {"ROI1": 1.0}}, "P2": {"A": {"ROI1": 2.0}}},
    )
    monkeypatch.setattr(
        "Tools.Stats.PySide6.stats_workers._long_format_from_bca",
        lambda _data: pd.DataFrame(
            [
                {"subject": "P1", "condition": "A", "roi": "ROI1", "value": 1.0},
                {"subject": "P2", "condition": "A", "roi": "ROI1", "value": float("nan")},
            ]
        ),
    )

    def _capture_rm_anova(all_subject_bca_data, message_cb, **kwargs):  # noqa: ANN001, ANN002
        seen["subjects"] = list(kwargs["subjects"])
        return "ok", pd.DataFrame([{"Effect": "condition", "Pr > F": 0.01}])

    monkeypatch.setattr("Tools.Stats.PySide6.stats_workers.analysis_run_rm_anova", _capture_rm_anova)

    run_rm_anova(
        lambda _progress: None,
        lambda _message: None,
        subjects=["P1", "P2"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={"P1": {"A": {"ROI1": 1.0}}, "P2": {"A": {"ROI1": 2.0}}},
        base_freq=6.0,
        rois={"ROI1": ["O1"]},
        rois_all={"ROI1": ["O1"]},
    )

    assert seen["subjects"] == ["P1"]
